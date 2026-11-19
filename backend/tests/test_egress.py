"""SSRF regressions use owned listeners or fake DNS/socket streams only."""

import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from threading import Thread
from unittest.mock import patch

import httpcore
import httpx
import pytest
from pydantic import ValidationError
from test_jobs import submit, target

from app.core.config import Settings, get_settings
from app.judges.providers import OpenAIProvider
from app.models import TargetApplication
from app.models.job import EvaluationJob
from app.network.policy import EgressDenied, EgressPolicy
from app.network.transport import CheckedBackend, EgressTransport
from app.services.job_service import JobService
from app.services.target_client import TargetClient, TargetRequestError
from app.worker import run_once


def answers(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443),
        )
        for address in addresses
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://owned.test",
        "https://owned.test:444",
        "https://child.owned.test",
        "https://owned.test.attacker.test",
        "https://owned.test.",
        "https://user:FAKE_SECRET@owned.test",
        "https://owned.test/#fragment",
        "https://[fe80::1%25en0]",
        "https://owned.test:0",
    ],
)
def test_unapproved_origins_do_not_even_resolve(url):
    with patch("socket.getaddrinfo") as resolve:
        with httpx.Client(
            transport=EgressTransport({"https://owned.test": []})
        ) as client:
            with pytest.raises(EgressDenied):
                client.post(url, headers={"Authorization": "Bearer FAKE_SECRET"})
        resolve.assert_not_called()


@pytest.mark.parametrize(
    "rules",
    [
        {"https://*.test": []},
        {"https://owned.test/path": []},
        {"https://owned.test?secret=x": []},
        {"file:///tmp/test": []},
        {"https://owned.test": ["0.0.0.0/0"]},
        {"https://owned.test": ["169.254.0.0/16"]},
        {"https://owned.test": ["127.0.0.1/8"]},
        {"http://0177.0.0.1": []},
        {"https://owned.test": [], "https://OWNED.test:443/": []},
    ],
)
def test_invalid_operator_rules_fail_configuration(rules):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, target_egress_rules=rules)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.1.2",
        "192.168.1.2",
        "::1",
        "fd00::1",
        "169.254.169.254",
        "100.100.100.200",
        "0.0.0.0",
        "::",
        "224.0.0.1",
        "ff02::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:93.184.216.34",
        "64:ff9b::7f00:1",
        "64:ff9b:1::1",
        "2002:7f00:1::",
        "2001::1",
        "168.63.129.16",
        "192.0.2.1",
        "2001:db8::1",
    ],
)
def test_non_public_and_transition_addresses_block_entire_dns_answer(address):
    rule = EgressPolicy({"https://owned.test": []}).select(
        httpx.URL("https://owned.test")
    )
    with patch("socket.getaddrinfo", return_value=answers("93.184.216.34", address)):
        with patch.object(httpcore.SyncBackend, "connect_tcp") as connect:
            with pytest.raises(EgressDenied):
                CheckedBackend(rule).connect_tcp("owned.test", 443)
            connect.assert_not_called()


def test_private_grants_are_narrow_and_cannot_enable_metadata():
    rule = EgressPolicy(
        {"http://owned.test": ["127.0.0.1/32", "::1/128", "10.1.0.0/16", "fc00::/7"]}
    ).select(httpx.URL("http://owned.test"))
    for address in ("127.0.0.1", "::1", "10.1.2.3", "fd00::1"):
        assert rule.permits(ip_address(address))
    for address in ("127.0.0.2", "10.2.0.1", "169.254.169.254", "fd00:ec2::254"):
        assert not rule.permits(ip_address(address))


def test_dns_is_pinned_and_rechecked_on_next_connection():
    rule = EgressPolicy({"https://owned.test": []}).select(
        httpx.URL("https://owned.test")
    )
    with patch(
        "socket.getaddrinfo",
        side_effect=[answers("93.184.216.34"), answers("127.0.0.1")],
    ) as resolve:
        with patch.object(httpcore.SyncBackend, "connect_tcp") as connect:
            backend = CheckedBackend(rule)
            backend.connect_tcp("owned.test", 443, timeout=1)
            assert connect.call_args.args == ("93.184.216.34", 443)
            assert resolve.call_count == 1
            with pytest.raises(EgressDenied):
                backend.connect_tcp("owned.test", 443, timeout=1)
            assert connect.call_count == 1


def test_https_preserves_host_sni_and_verification():
    class Stream(httpcore.NetworkStream):
        sent = b""

        def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"

        def write(self, buffer, timeout=None):
            self.sent += buffer

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert server_hostname == "owned.test"
            assert ssl_context.check_hostname
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            return self

        def close(self):
            pass

        def get_extra_info(self, info):
            return None

    stream = Stream()
    with patch("socket.getaddrinfo", return_value=answers("93.184.216.34")):
        with patch.object(httpcore.SyncBackend, "connect_tcp", return_value=stream):
            with httpx.Client(
                transport=EgressTransport({"https://owned.test": []})
            ) as client:
                response = client.get(
                    "https://owned.test/path",
                    extensions={"sni_hostname": "attacker.test"},
                )
                assert response.text == "OK"
    assert b"Host: owned.test\r\n" in stream.sent


@pytest.fixture
def listener():
    state = {"requests": [], "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302 if state["redirect"] else 200)
            self.send_header("Location", "/redirected")
            self.end_headers()
            self.wfile.write(b'{"response":"SAFE"}')

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["port"] = server.server_port
    state["url"] = f"http://127.0.0.1:{server.server_port}/chat"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def configured_target(url):
    return TargetApplication(
        name="Owned",
        endpoint_url=url,
        http_method="POST",
        api_key="FAKE_SECRET",
        request_template={"message": ""},
        prompt_field="message",
        response_field="response",
    )


def test_target_denial_then_explicit_grant_and_no_redirects(
    listener, monkeypatch, allow_owned_http
):
    monkeypatch.setenv("TARGET_EGRESS_RULES", "{}")
    client = TargetClient(configured_target(listener["url"] + "?secret=FAKE_QUERY"))
    try:
        with pytest.raises(TargetRequestError) as error:
            client.send_prompt("synthetic")
        assert (
            str(error.value)
            == "Target destination is not permitted by operator policy."
        )
        assert not error.value.observation.retryable
    finally:
        client.close()
    assert listener["requests"] == []
    allow_owned_http(listener["port"])
    # An invalid proxy must not intercept this authorized request.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    client = TargetClient(configured_target(listener["url"]))
    try:
        assert client.send_prompt("synthetic").content == "SAFE"
        listener["redirect"] = True
        with pytest.raises(TargetRequestError, match="HTTP 302"):
            client.send_prompt("synthetic")
    finally:
        client.close()
    assert listener["requests"] == [("/chat", "Bearer FAKE_SECRET")] * 2


def test_judge_policy_is_separate_from_target_grant(
    listener, monkeypatch, allow_owned_http
):
    allow_owned_http(listener["port"])
    monkeypatch.setenv("JUDGE_EGRESS_RULES", "{}")
    get_settings.cache_clear()
    result = OpenAIProvider().evaluate(
        {"model": "owned", "instructions": "synthetic", "input": "synthetic"},
        {"timeout": 1, "api_key": "FAKE_PROVIDER_SECRET", "endpoint": listener["url"]},
    )
    assert result.error == "judge_destination_denied" and not result.retryable
    assert listener["requests"] == []


def test_accepted_job_uses_current_worker_policy_not_frozen_grants(
    session_factory, listener, monkeypatch, allow_owned_http
):
    allow_owned_http(listener["port"])
    tid = target(session_factory)
    with session_factory() as db:
        db.get(TargetApplication, tid).endpoint_url = listener["url"]
        db.commit()
    rid = submit(session_factory, tid)
    # Revoke network permission after admission, without rewriting accepted work.
    monkeypatch.setenv("TARGET_EGRESS_RULES", "{}")
    get_settings.cache_clear()
    assert run_once(session_factory)
    with session_factory() as db:
        run = JobService(db).evaluations.get_run(rid)
        assert run.results[0].outcome == "errored"
        assert "operator policy" in run.results[0].failure_reason
        assert db.get(EvaluationJob, rid).payload is None
    assert listener["requests"] == []


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001"])
def test_alternate_ipv4_spellings_cannot_bypass_address_check(host):
    rule = EgressPolicy({f"http://{host}": []}).select(httpx.URL(f"http://{host}"))
    # Model the system resolver's numeric normalization without platform dependence.
    with patch("socket.getaddrinfo", return_value=answers("127.0.0.1")):
        with patch.object(httpcore.SyncBackend, "connect_tcp") as connect:
            with pytest.raises(EgressDenied):
                CheckedBackend(rule).connect_tcp(host, 80)
            connect.assert_not_called()


@pytest.mark.parametrize(
    "trusted,hostname",
    [(True, "owned.test"), (False, "owned.test"), (True, "wrong.test")],
)
def test_real_tls_validates_certificate_and_original_hostname(
    tmp_path, monkeypatch, trusted, hostname
):
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "owned.test")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("owned.test")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers["Host"])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SAFE")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_resolve = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        # The actual TCP connection must receive only the approved numeric IP.
        return real_resolve(
            "127.0.0.1" if host == hostname else host, port, *args, **kwargs
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    url = f"https://{hostname}:{server.server_port}"
    transport = EgressTransport({url: ["127.0.0.1/32"]})
    if trusted:
        transport.ssl_context.load_verify_locations(cert_path)
    try:
        with httpx.Client(transport=transport, timeout=2, trust_env=False) as client:
            if trusted and hostname == "owned.test":
                assert client.get(url).text == "SAFE"
                assert seen == [f"owned.test:{server.server_port}"]
            else:
                with pytest.raises(httpx.NetworkError):
                    client.get(url)
                assert seen == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_ipv6_requires_explicit_loopback_permission():
    class IPv6Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"SAFE")

        def log_message(self, *_):
            pass

    try:
        server = IPv6Server(("::1", 0), Handler)
    except OSError:
        pytest.skip("Host does not support IPv6 loopback listeners")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://[::1]:{server.server_port}"
    try:
        with httpx.Client(
            transport=EgressTransport({url: []}), trust_env=False
        ) as client:
            with pytest.raises(EgressDenied):
                client.get(url)
        with httpx.Client(
            transport=EgressTransport({url: ["::1/128"]}), trust_env=False
        ) as client:
            assert client.get(url).text == "SAFE"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
