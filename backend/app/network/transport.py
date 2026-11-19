"""HTTPX transport with DNS validation at the actual TCP connection boundary."""

import socket
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from time import monotonic

import httpcore
import httpx

from app.network.policy import (
    DestinationRule,
    EgressDenied,
    EgressPolicy,
    checked_address,
)


@contextmanager
def mapped_errors() -> Iterator[None]:
    # Keep adapter-facing errors stable without exposing URLs or resolver details.
    try:
        yield
    except httpcore.TimeoutException:
        raise httpx.TimeoutException("Outbound request timed out.") from None
    except httpcore.NetworkError:
        raise httpx.NetworkError("Outbound connection failed.") from None
    except (httpcore.ProtocolError, httpcore.ConnectionNotAvailable):
        raise httpx.RequestError("Outbound protocol failed.") from None


class CheckedBackend(httpcore.SyncBackend):
    def __init__(self, rule: DestinationRule) -> None:
        self.rule = rule

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.NetworkStream:
        if (host, port) != self.rule.origin[1:]:
            raise EgressDenied()
        started = monotonic()
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            raise httpcore.ConnectError("Outbound resolution failed.") from None
        if not answers or len(answers) > 64:
            raise EgressDenied()
        # Validate the ENTIRE result before any connection, including mixed A/AAAA.
        addresses = []
        for family, _, _, _, sockaddr in answers:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                raise EgressDenied()
            address = str(checked_address(sockaddr[0], self.rule))
            if address not in addresses:
                addresses.append(address)
        for address in addresses:
            remaining = None if timeout is None else timeout - (monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise httpcore.ConnectTimeout("Outbound connection timed out.")
            try:
                # Only a canonical numeric address reaches the socket backend.
                # HTTP Host, TLS SNI and certificate verification retain the hostname.
                return super().connect_tcp(
                    address,
                    port,
                    timeout=remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout):
                if address == addresses[-1]:
                    raise
        raise EgressDenied()


class ResponseStream(httpx.SyncByteStream):
    def __init__(
        self, response: httpcore.Response, pool: httpcore.ConnectionPool
    ) -> None:
        self.response = response
        self.pool = pool

    def __iter__(self) -> Iterator[bytes]:
        with mapped_errors():
            yield from self.response.iter_stream()

    def close(self) -> None:
        try:
            with mapped_errors():
                self.response.close()
        finally:
            self.pool.close()


class EgressTransport(httpx.BaseTransport):
    def __init__(self, rules: dict[str, list[str]]) -> None:
        self.policy = EgressPolicy(rules)
        self.ssl_context = httpcore.default_ssl_context()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        rule = self.policy.select(request.url)
        # One pool per request: every new request rechecks DNS, including retries.
        pool = httpcore.ConnectionPool(
            ssl_context=self.ssl_context,
            network_backend=CheckedBackend(rule),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        )
        try:
            with mapped_errors():
                response = pool.handle_request(
                    httpcore.Request(
                        method=request.method,
                        url=httpcore.URL(
                            scheme=request.url.raw_scheme,
                            host=request.url.raw_host,
                            port=request.url.port,
                            target=request.url.raw_path,
                        ),
                        headers=request.headers.raw,
                        content=request.stream,
                        # No request-supplied SNI override or alternate network path.
                        extensions={"timeout": request.extensions.get("timeout", {})},
                    )
                )
            return httpx.Response(
                response.status,
                headers=response.headers,
                stream=ResponseStream(response, pool),
                extensions=response.extensions,
            )
        except BaseException:
            pool.close()
            raise
