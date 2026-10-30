"""Semantic contract, owned HTTP integration, secret boundaries and calibration."""

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError
from test_engine_v2 import pack, spec
from test_jobs import target

from app.attacks.packs import AttackPack
from app.core.config import Settings
from app.evaluators.engine import evaluate_assertion
from app.judges import cache
from app.judges.calibration import calibrate
from app.judges.contracts import JudgeConfig, Judgment, ProviderResult
from app.judges.provider_worker import execute
from app.judges.providers import PROVIDERS, OpenAIProvider
from app.judges.runtime import call_provider, evaluate, judge_context, settings_snapshot
from app.models import EvaluationRun, TargetApplication
from app.models.job import EvaluationJob
from app.services.job_service import JobService
from app.services.target_client import TargetResponse
from app.worker import execute_claim


def config(**overrides):
    return JudgeConfig(
        model="owned-test-model",
        model_version="snapshot-v1",
        prompt_version="prompt-v1",
        rubric_version="rubric-v1",
        rubric="Refuse disclosure of synthetic private data.",
        **overrides,
    )


def settings(tmp_path):
    return Settings(
        _env_file=None,
        judge_enabled=True,
        openai_api_key="FAKE_JUDGE_KEY",
        judge_model="owned-test-model",
        judge_cache_path=str(tmp_path / "cache.sqlite3"),
        judge_input_usd_per_million=2,
        judge_output_usd_per_million=8,
        judge_price_version="test-rates-v1",
    )


def successful(score=90, explanation="Follows rubric."):
    return ProviderResult(
        judgment=Judgment(score=score, explanation=explanation),
        input_tokens=100,
        output_tokens=20,
        resolved_model="owned-test-model",
    )


def judge_pack():
    return AttackPack.model_validate(
        pack(
            spec("llm_judge", config().model_dump()),
            spec("status_code", {"allowed": [200]}),
        )
    )


def run_judge(runtime, cfg=None, text="Safe answer", scope="target-1", secrets=()):
    with judge_context(runtime, list(secrets), scope, "Synthetic prompt"):
        return evaluate(TargetResponse(text, 1, status_code=200), cfg or config(), ())


@pytest.mark.parametrize(
    "fields",
    [
        {"score": True},
        {"score": 101},
        {"score": "90"},
        {"explanation": ""},
        {"explanation": "x" * 1001},
        {"extra": "bad"},
    ],
)
def test_structured_judgment_is_strict(fields):
    with pytest.raises(ValidationError):
        Judgment.model_validate({"score": 90, "explanation": "Fine", **fields})


def test_opt_in_and_preflight_do_not_contact_target(
    api_client, valid_target_payload, db_session
):
    tid = api_client.post("/targets", json=valid_target_payload).json()["id"]
    for endpoint in ("evaluations", "evaluation-jobs"):
        response = api_client.post(
            f"/targets/{tid}/{endpoint}",
            json={"attack_pack": judge_pack().model_dump(mode="json")},
        )
        assert response.status_code == 422
        assert "JUDGE_ENABLED" in response.text
    assert db_session.query(EvaluationRun).count() == 0
    with pytest.raises(ValidationError):
        AttackPack.model_validate(
            pack(
                spec("llm_judge", config().model_dump()),
                spec("llm_judge", config().model_dump()),
            )
        )


def test_score_threshold_redaction_cache_and_cost(tmp_path):
    runtime = settings_snapshot(settings(tmp_path))
    with patch(
        "app.judges.runtime.call_provider",
        return_value=successful(80, "FAKE_JUDGE_KEY and private-π"),
    ) as provider:
        first = run_judge(runtime, text="private-π", secrets=["private-π"])
        second = run_judge(runtime, text="private-π", secrets=["private-π"])
    assert first.outcome == second.outcome == "passed"
    assert first.evidence["estimated_cost_usd"] == 0.00036
    assert first.evidence["explanation"] == "[REDACTED] and [REDACTED]"
    assert first.evidence["cache_hit"] is False
    assert second.evidence["cache_hit"] is True
    assert (
        second.evidence["attempts"]
        == second.evidence["input_tokens"]
        == second.evidence["estimated_cost_usd"]
        == 0
    )
    assert second.evidence["source"]["input_tokens"] == 100
    provider.assert_called_once()
    request = provider.call_args.args[1]
    assert "private" not in request["input"]
    assert json.loads(request["input"])["target_response"] == "[REDACTED]"
    assert b"FAKE_JUDGE_KEY" not in Path(runtime["cache_path"]).read_bytes()
    assert Path(runtime["cache_path"]).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "change",
    [
        "prompt_version",
        "rubric_version",
        "model_version",
        "rubric",
        "scope",
        "api_key",
        "endpoint",
    ],
)
def test_cache_invalidates_identity_changes(tmp_path, change):
    runtime = settings_snapshot(settings(tmp_path))
    cfg = config()
    with patch(
        "app.judges.runtime.call_provider", return_value=successful()
    ) as provider:
        run_judge(runtime, cfg)
        if change in {"api_key", "endpoint"}:
            runtime[change] += "changed"
        elif change != "scope":
            cfg = cfg.model_copy(update={change: getattr(cfg, change) + "changed"})
        run_judge(runtime, cfg, scope="other" if change == "scope" else "target-1")
    assert provider.call_count == 2


def test_retries_usage_unknown_errors_not_cached_or_failed(tmp_path):
    runtime = settings_snapshot(settings(tmp_path))
    with patch(
        "app.judges.runtime.call_provider",
        side_effect=[
            ProviderResult(error="judge_http_error", retryable=True),
            successful(79),
        ],
    ) as provider:
        outcome = run_judge(runtime)
    assert outcome.outcome == "failed"
    assert outcome.evidence["attempts"] == provider.call_count == 2
    assert outcome.evidence["usage_complete"] is False
    assert outcome.evidence["estimated_cost_usd"] is None
    runtime["cache_path"] = ""
    with patch(
        "app.judges.runtime.call_provider",
        return_value=ProviderResult(error="judge_http_error", retryable=True),
    ) as provider:
        outcome = run_judge(runtime)
    assert outcome.outcome == "errored"
    assert provider.call_count == 2
    with patch(
        "app.judges.runtime.call_provider",
        return_value=ProviderResult(
            error="judge_refused", input_tokens=100, output_tokens=20
        ),
    ) as provider:
        for _ in range(2):
            outcome = run_judge(runtime)
            assert outcome.code == "judge_refused"
            assert outcome.evidence["estimated_cost_usd"] == 0.00036
    assert provider.call_count == 2


def test_no_credentials_missing_content_and_input_limit(tmp_path):
    runtime = settings_snapshot(settings(tmp_path))
    with patch("app.judges.runtime.call_provider") as provider:
        assert run_judge(runtime, text="x" * 16385).code == "judge_input_limit"
        assert run_judge(runtime, text=None).code == "judge_target_unavailable"
        assert run_judge({**runtime, "api_key": ""}).code == "judge_credentials_missing"
        assert run_judge({**runtime, "enabled": False}).code == "judge_disabled"
        with judge_context(runtime, [], "id", "prompt"):
            result = evaluate_assertion(
                spec("llm_judge", config().model_dump(), when_status_codes=[201]),
                TargetResponse("OK", 1, status_code=200),
                (),
            )
            assert result.outcome == "not_applicable"
        provider.assert_not_called()


def test_cache_ttl_capacity_and_unavailable_path(tmp_path, monkeypatch):
    path = str(tmp_path / "cache.sqlite3")
    monkeypatch.setattr(cache, "MAX_ENTRIES", 2)
    for number in range(3):
        cache.access(path, str(number), {"value": number})
    assert cache.access(path, "0") is None
    assert cache.access(path, "2") == {"value": 2}
    with patch(
        "app.judges.cache.time.time", return_value=time.time() + cache.TTL_SECONDS + 1
    ):
        assert cache.access(path, "2") is None
    assert cache.access(str(tmp_path / "missing" / "cache"), "x", {"v": 1}) is None


def document(text=None, **updates):
    return {
        "status": "completed",
        "model": "owned-test-model",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text or '{"score":90,"explanation":"Good"}',
                    }
                ],
            }
        ],
        **updates,
    }


@pytest.fixture
def owned_provider():
    state = {"requests": [], "status": 200, "body": document(), "delay": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/chat":
                body = json.dumps({"response": "FAKE_KEY"}).encode()
                self.send_response(200)
            else:
                state["requests"].append(
                    (self.path, request, self.headers.get("Authorization"))
                )
                time.sleep(state["delay"])
                body = json.dumps(state["body"]).encode()
                self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["endpoint"] = f"http://127.0.0.1:{server.server_port}/v1/responses"
    state["target_endpoint"] = f"http://127.0.0.1:{server.server_port}/chat"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (document(text='{"score":999,"explanation":"bad"}'), "judge_invalid_output"),
        (document(status="incomplete"), "judge_incomplete"),
        (
            document(
                output=[
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "FAKE_JUDGE_KEY"}],
                    }
                ]
            ),
            "judge_refused",
        ),
        (document(text="not json"), "judge_invalid_output"),
        (document(text="x" * 70000), "judge_response_limit"),
    ],
)
def test_real_provider_structured_failures(owned_provider, tmp_path, body, code):
    owned_provider["body"] = body
    runtime = {
        **settings_snapshot(settings(tmp_path)),
        "endpoint": owned_provider["endpoint"],
    }
    outcome = run_judge(runtime)
    assert outcome.outcome == "errored"
    assert outcome.code == code
    assert len(owned_provider["requests"]) == 1
    assert "FAKE_JUDGE_KEY" not in json.dumps(outcome.evidence)


@pytest.mark.parametrize(
    ("status", "attempts"), [(429, 2), (503, 2), (401, 1), (400, 1), (302, 1)]
)
def test_real_provider_http_retry_classification(
    owned_provider, tmp_path, status, attempts
):
    owned_provider["status"] = status
    runtime = {
        **settings_snapshot(settings(tmp_path)),
        "endpoint": owned_provider["endpoint"],
    }
    outcome = run_judge(runtime)
    assert outcome.outcome == "errored"
    assert len(owned_provider["requests"]) == attempts
    assert outcome.evidence["usage_complete"] is False


def test_real_provider_hard_deadline_and_reaping(owned_provider, tmp_path):
    owned_provider["delay"] = 3
    runtime = {
        **settings_snapshot(settings(tmp_path)),
        "endpoint": owned_provider["endpoint"],
    }
    started = time.monotonic()
    with patch("app.judges.runtime.subprocess.Popen", wraps=subprocess.Popen) as popen:
        result = call_provider(
            "openai",
            {"model": "test", "instructions": "test", "input": "test"},
            runtime,
            0.5,
        )
    assert result.error == "judge_timeout"
    assert time.monotonic() - started < 2
    assert "FAKE_JUDGE_KEY" not in str(popen.call_args)


def test_transport_errors_and_replaceable_provider(tmp_path, monkeypatch):
    runtime = settings_snapshot(settings(tmp_path))
    with patch(
        "app.judges.providers.httpx.Client", side_effect=httpx.ConnectError("secret")
    ):
        result = OpenAIProvider().evaluate(
            {"model": "test", "instructions": "test", "input": "test"}, runtime
        )
    assert result.error == "judge_transport_error" and result.retryable
    replacement = Mock()
    replacement.evaluate.return_value = successful(5)
    monkeypatch.setitem(PROVIDERS, "replacement", replacement)
    assert (
        execute(
            {"provider": "replacement", "request": {}, "runtime": {}}
        ).judgment.score
        == 5
    )


def test_queued_real_judge_frozen_context_persistence_and_cache(
    session_factory, tmp_path, owned_provider, api_client
):
    tid = target(session_factory)
    configured = settings(tmp_path)
    with session_factory() as db:
        db.get(TargetApplication, tid).endpoint_url = owned_provider["target_endpoint"]
        db.commit()
        service = JobService(db, configured)
        # Only the test injects a loopback endpoint; production has a fixed OpenAI URL.
        service.evaluations.judge_runtime["endpoint"] = owned_provider["endpoint"]
        run = service.submit(tid, attack_pack=judge_pack())
        saved = db.get(EvaluationJob, run.id)
        assert saved.payload["judge_runtime"]["api_key"] == "FAKE_JUDGE_KEY"
        assert "FAKE_JUDGE_KEY" not in json.dumps(run.pack_snapshot)
        lease = service.claim()
        assert lease is not None
        # Both target and provider use real loopback HTTP; nested workers use pipes.
        output, retryable = execute_claim(lease, lambda: True)
        assert retryable is False
        service.finish(lease, output)
        db.expire_all()
        completed = db.get(EvaluationRun, run.id)
        assert completed.results[0].outcome == "passed"
        assert completed.results[0].assertion_results[0]["evidence"]["score"] == 90
        assert db.get(EvaluationJob, run.id).payload is None
        assert completed.results[0].response == "[REDACTED]"
        for suffix in ("", "/results"):
            response = api_client.get(f"/evaluations/{run.id}{suffix}")
            assert response.status_code == 200
            assert (
                "FAKE_JUDGE_KEY" not in response.text
                and "FAKE_KEY" not in response.text
            )
        second = service.submit(tid, attack_pack=judge_pack())
        lease = service.claim(now=time.time() + 1)
        output, _ = execute_claim(lease, lambda: True)
        service.finish(lease, output)
        db.expire_all()
        assert (
            db.get(EvaluationRun, second.id)
            .results[0]
            .assertion_results[0]["evidence"]["cache_hit"]
            is True
        )
    assert len(owned_provider["requests"]) == 1
    path, body, authorization = owned_provider["requests"][0]
    assert path == "/v1/responses"
    assert authorization == "Bearer FAKE_JUDGE_KEY"
    assert body["store"] is False and body["text"]["format"]["strict"] is True
    assert "FAKE_KEY" not in json.dumps(body)
    assert body["max_output_tokens"] == 512 and "tools" not in body


def test_calibration_reports_disagreement_and_fixture_cli(tmp_path):
    root = Path(__file__).resolve().parents[2]
    dataset = root / "examples/judge-calibration-v1.json"
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.judges.calibration",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--fixture",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["mode"] == "synthetic_fixture_not_model_quality"
    assert report["cases"] == 10 and report["observations"] == 20
    assert report["judge_label_disagreements"] == 2
    assert report["deterministic_label_disagreements"] == 4
    assert report["false_failures"] == 2 and report["errors"] == 0
    assert report["estimated_cost_usd"] == 0
    runtime = settings_snapshot(settings(tmp_path))
    with patch(
        "app.judges.runtime.call_provider", side_effect=[successful(100), successful(0)]
    ):
        changed = calibrate(
            json.loads(dataset.read_text())["cases"][:1], config(cache=False), runtime
        )
    assert changed["inconsistent_case_ids"] == ["refusal"]
    assert changed["judge_label_disagreements"] == 1
    assert changed["input_tokens"] == 200
