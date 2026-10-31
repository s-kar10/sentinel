"""Behavioral contracts for Phase 1 configuration, isolation, history and outcomes."""

import json
from hashlib import sha256
from unittest.mock import Mock

import httpx
import pytest
from fastapi import Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_evaluation_service
from app.database.session import get_db
from app.evaluators.configuration import Config
from app.evaluators.contracts import Outcome, verdict
from app.evaluators.engine import AssertionSpec, Strategy, evaluate_assertion, registry
from app.evaluators.isolation import isolated_check
from app.services.evaluation_service import EvaluationService
from app.services.provenance import canonical
from app.services.target_client import TargetClient, TargetRequestError, TargetResponse


def spec(evaluator, config, **overrides):
    return {"evaluator": evaluator, "version": 1, "config": config, **overrides}


def pack(*assertions):
    return {
        "schema_version": 2,
        "id": "phase-one",
        "version": 1,
        "name": "Phase one",
        "attacks": [
            {
                "id": "check",
                "version": 1,
                "name": "Configured check",
                "category": "reliability",
                "description": "Synthetic check",
                "prompt": "Synthetic prompt",
                "severity": "high",
                "assertions": list(assertions),
            }
        ],
    }


@pytest.fixture
def engine_api(api_app, api_client, valid_target_payload):
    client = Mock()
    client.send_prompt.return_value = TargetResponse("SAFE", 10, status_code=200)
    factory = Mock(return_value=client)

    def service(db: Session = Depends(get_db)):
        return EvaluationService(db, target_client_factory=factory)

    api_app.dependency_overrides[get_evaluation_service] = service
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    return api_client, target_id, client, factory


@pytest.mark.parametrize(
    ("assertion", "observation", "expected"),
    [
        (
            spec("exact_match", {"values": ["safe"], "case_sensitive": False}),
            TargetResponse(" SAFE ", 1),
            "passed",
        ),
        (
            spec("exact_match", {"values": ["SAFE"], "strip_response": False}),
            TargetResponse(" SAFE ", 1),
            "failed",
        ),
        (
            spec(
                "contains_forbidden_string",
                {"values": ["SAFE"], "case_sensitive": True},
            ),
            TargetResponse("safe", 1),
            "passed",
        ),
        (
            spec("regex_match", {"pattern": "REF-[0-9]+"}),
            TargetResponse("Ref-123 accepted", 1),
            "passed",
        ),
        (
            spec("regex_match", {"pattern": "REF-[0-9]+", "mode": "fullmatch"}),
            TargetResponse("Ref-123 accepted", 1),
            "failed",
        ),
        (
            spec("regex_match", {"pattern": "x"}),
            TargetResponse("x" * 100_001, 1),
            "errored",
        ),
        (
            spec("latency", {"max_ms": 10}),
            TargetResponse("SAFE", 10, status_code=200),
            "passed",
        ),
        (
            spec("latency", {"max_ms": 9}),
            TargetResponse("SAFE", 10, status_code=200),
            "failed",
        ),
        (
            spec("status_code", {"allowed": [403]}),
            TargetResponse(None, 5, status_code=403, error="HTTP error"),
            "passed",
        ),
        (spec("status_code", {"allowed": [200]}), TargetResponse(None, 5), "errored"),
        (
            spec("status_code", {"allowed": [200]}, when_status_codes=[201]),
            TargetResponse(None, 5, status_code=200),
            "not_applicable",
        ),
        (
            spec("status_code", {"allowed": [200]}, when_status_codes=[201]),
            TargetResponse(None, 5),
            "errored",
        ),
        (spec("json_valid", {}), TargetResponse('{"ok": true}', 1), "passed"),
        (spec("json_valid", {}), TargetResponse("NaN", 1), "failed"),
        (spec("json_valid", {}), TargetResponse("not json", 1), "failed"),
        (
            spec("json_valid", {"source": "value"}),
            TargetResponse(None, 1, value=None, has_value=True),
            "passed",
        ),
        (spec("json_valid", {"source": "value"}), TargetResponse(None, 1), "errored"),
        (
            spec(
                "json_schema",
                {
                    "schema_definition": {
                        "type": "object",
                        "required": ["ok"],
                        "properties": {"ok": {"type": "boolean"}},
                        "additionalProperties": False,
                    }
                },
            ),
            TargetResponse('{"ok": true}', 1),
            "passed",
        ),
        (
            spec("json_schema", {"schema_definition": {"type": "integer"}}),
            TargetResponse("true", 1),
            "failed",
        ),
        (
            spec(
                "json_schema",
                {"schema_definition": {"type": "object", "required": ["ok"]}},
            ),
            TargetResponse("{}", 1),
            "failed",
        ),
    ],
)
def test_strategy_contracts(assertion, observation, expected):
    validated = AssertionSpec.model_validate(assertion)
    outcome = evaluate_assertion(validated.model_dump(), observation, ())
    assert outcome.outcome == expected
    # Evidence never copies the untrusted text or a matching substring.
    assert "Ref-123" not in json.dumps(outcome.evidence)


def test_catastrophic_regex_is_killed_and_next_check_runs():
    outcome = evaluate_assertion(
        spec("regex_match", {"pattern": "(a+)+$"}),
        TargetResponse("a" * 10000 + "!", 1),
        (),
    )
    assert outcome.outcome == Outcome.ERRORED
    assert outcome.code == "evaluator_timeout"
    assert (
        evaluate_assertion(
            spec("regex_match", {"pattern": "safe"}), TargetResponse("safe", 1), ()
        ).outcome
        == "passed"
    )


def test_worker_timeout_kills_and_reaps_child(monkeypatch):
    import app.evaluators.isolation as module

    original = module.subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(module.subprocess, "Popen", capture)
    outcome = isolated_check(
        {
            "kind": "regex",
            "value": "a" * 10000 + "!",
            "config": {"pattern": "(a+)+$", "case_sensitive": True, "mode": "search"},
        },
        timeout=0.1,
    )
    assert outcome.code == "evaluator_timeout"
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize(
    "assertion",
    [
        spec("regex_match", {"pattern": "["}),
        spec("regex_match", {"pattern": "x" * 1025}),
        spec("regex_match", {"pattern": "x", "timeout": 999}),
        spec("latency", {"max_ms": -1}),
        spec("latency", {"max_ms": True}),
        spec("latency", {"max_ms": "10"}),
        spec("status_code", {"allowed": []}),
        spec("status_code", {"allowed": [600]}),
        spec("status_code", {"allowed": [True]}),
        spec(
            "json_schema",
            {"schema_definition": {"$ref": "http://private.invalid/schema"}},
        ),
        spec(
            "json_schema",
            {"schema_definition": {"properties": {"x": {"pattern": "(a+)+$"}}}},
        ),
        spec("json_schema", {"schema_definition": {"format": "email"}}),
        spec("json_schema", {"schema_definition": {"type": "invented"}}),
        spec("json_valid", {"source": "unknown"}),
        spec("exact_match", {"values": []}),
        spec("exact_match", {"values": ["x"], "case_sensitive": "false"}),
        spec("exact_match", {"values": ["x"]}, version=2),
        spec("exact_match", {"values": ["x"]}, version=True),
        spec("invented", {}),
    ],
)
def test_invalid_assertions_rejected_before_side_effects(engine_api, assertion):
    api, target_id, _, factory = engine_api
    response = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": pack(assertion)}
    )
    assert response.status_code == 422
    assert api.get("/evaluations").json() == []
    factory.assert_not_called()


def test_snapshots_evidence_and_known_secrets_are_redacted_and_immutable(engine_api):
    api, target_id, client, _ = engine_api
    api.post(
        f"/targets/{target_id}/protected-values",
        json={"name": "synthetic", "value": "TEST_SECRET_ABC123"},
    )
    client.send_prompt.return_value = TargetResponse(
        "TEST_SECRET_ABC123 fake-test-key", 3, status_code=200
    )
    payload = pack(
        spec("contains_forbidden_string", {"include_target_protected_values": True})
    )
    payload["attacks"][0]["prompt"] = "TEST_SECRET_ABC123 fake-test-key"
    created = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    )
    assert created.status_code == 201
    run = created.json()
    results = api.get(f"/evaluations/{run['id']}/results").json()
    assert run["engine_version"] == "2.0"
    assert run["pack_snapshot"]["runtime"]["json_depth_limit"] == 100
    assert run["scoring_version"] == "severity-v1"
    assert run["metrics"]["failed"] == 1
    assert results[0]["outcome"] == "failed"
    assert results[0]["assertion_results"][0]["evidence"] == {"matched_count": 1}
    serialized = json.dumps([run, results])
    assert "TEST_SECRET_ABC123" not in serialized and "fake-test-key" not in serialized
    assert (
        run["pack_digest"]
        == sha256(canonical(run["pack_snapshot"]).encode()).hexdigest()
    )
    assert (
        run["pack_snapshot"]["attacks"][0]["assertions"][0]["config"]["case_sensitive"]
        is False
    )
    payload["version"] = 2
    payload["attacks"][0]["prompt"] = "changed"
    api.post(f"/targets/{target_id}/evaluations", json={"attack_pack": payload})
    assert api.get(f"/evaluations/{run['id']}").json() == run
    assert api.get(f"/evaluations/{run['id']}/results").json() == results


def test_mixed_outcomes_partial_run_and_severity_metrics(engine_api):
    api, target_id, client, _ = engine_api
    payload = pack(spec("exact_match", {"values": ["SAFE"]}))
    template = payload["attacks"][0]
    payload["attacks"] = [
        {**template, "id": f"check-{i}", "severity": severity}
        for i, severity in enumerate(["high", "critical", "medium", "high", "low"])
    ]
    payload["attacks"][3]["assertions"] = [
        spec("exact_match", {"values": ["SAFE"]}, when_status_codes=[201])
    ]
    client.send_prompt.side_effect = [
        TargetResponse("SAFE", 1, status_code=200),
        TargetResponse("FAIL", 1, status_code=200),
        TargetRequestError("Target request timed out.", duration_ms=1),
        TargetResponse("SAFE", 1, status_code=200),
        RuntimeError("synthetic-private-detail"),
    ]
    response = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    )
    assert (
        response.status_code == 500 and "synthetic-private-detail" not in response.text
    )
    run = api.get("/evaluations").json()[0]
    results = api.get(f"/evaluations/{run['id']}/results").json()
    assert [result["outcome"] for result in results] == [
        "passed",
        "failed",
        "errored",
        "not_applicable",
        "untested",
    ]
    assert run["status"] == "failed" and run["total_tests"] == 5
    assert run["score"] == 20.0  # Legacy all-check pass rate remains explicit.
    assert run["metrics"]["weighted_score"] == 42.86  # 3 / (3 + 4)
    assert run["metrics"]["coverage"] == 50.0  # Two evaluated / four applicable
    assert run["metrics"]["categories"]["reliability"]["untested"] == 1
    client.close.assert_called_once()


def test_multiple_assertions_aggregate_errors_and_keep_individual_evidence(engine_api):
    api, target_id, client, _ = engine_api
    client.send_prompt.return_value = TargetResponse("not-json", 10, status_code=200)
    payload = pack(
        spec("exact_match", {"values": ["not-json"]}),
        spec("json_valid", {}),
        spec("json_valid", {"source": "document"}),
    )
    run = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    ).json()
    result = api.get(f"/evaluations/{run['id']}/results").json()[0]
    assert result["outcome"] == "errored"
    assert [item["outcome"] for item in result["assertion_results"]] == [
        "passed",
        "failed",
        "errored",
    ]
    assert run["metrics"]["weighted_score"] is None
    assert run["metrics"]["coverage"] == 0


def test_structured_target_and_http_metadata_cross_real_adapter(
    api_app, api_client, valid_target_payload
):
    valid_target_payload["response_field"] = "result"
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    response = httpx.Response(200, json={"result": {"ok": True}})
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http_client:

        def service(db: Session = Depends(get_db)):
            return EvaluationService(
                db,
                target_client_factory=lambda target: TargetClient(
                    target, http_client=http_client
                ),
            )

        api_app.dependency_overrides[get_evaluation_service] = service
        payload = pack(
            spec(
                "json_schema",
                {
                    "source": "value",
                    "schema_definition": {
                        "type": "object",
                        "required": ["ok"],
                        "properties": {"ok": {"const": True}},
                    },
                },
            ),
            spec("status_code", {"allowed": [200]}),
            spec("latency", {"max_ms": 10000}),
        )
        created = api_client.post(
            f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
        )
        assert created.status_code == 201
        assert created.json()["passed_tests"] == 1
        result = api_client.get(f"/evaluations/{created.json()['id']}/results").json()[
            0
        ]
        assert result["response"] is None and result["outcome"] == "passed"
        assert result["response_status"] == 200
        assert result["observation_snapshot"]["document"] == {"result": {"ok": True}}
        response = httpx.Response(403)
        payload = pack(spec("status_code", {"allowed": [403]}))
        assert (
            api_client.post(
                f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
            ).json()["passed_tests"]
            == 1
        )


def test_new_versioned_strategy_needs_no_orchestration_conditionals(
    engine_api, monkeypatch
):
    class LengthConfig(Config):
        minimum: int = Field(strict=True, ge=0)

    strategy = Strategy(
        "test_length",
        7,
        LengthConfig,
        lambda observation, config, _: verdict(
            len(observation.content or "") >= config.minimum, "length_checked"
        ),
    )
    monkeypatch.setattr(registry, "_strategies", dict(registry._strategies))
    registry.register(strategy)
    api, target_id, _, _ = engine_api
    payload = pack(spec("test_length", {"minimum": 3}, version=7))
    response = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    )
    assert response.status_code == 201 and response.json()["passed_tests"] == 1
    saved = response.json()["pack_snapshot"]["attacks"][0]["assertions"][0]
    assert saved["version"] == 7 and saved["config"] == {"minimum": 3}
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(strategy)


def test_all_inapplicable_checks_have_no_weighted_score_or_coverage(engine_api):
    api, target_id, _, _ = engine_api
    payload = pack(spec("exact_match", {"values": ["SAFE"]}, when_status_codes=[201]))
    run = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    ).json()
    assert run["metrics"]["not_applicable"] == 1
    assert run["metrics"]["weighted_score"] is None
    assert run["metrics"]["coverage"] is None


def test_schema_profile_bounds_nested_and_oversized_definitions(engine_api):
    api, target_id, _, factory = engine_api
    nested = {"type": "string"}
    for _ in range(12):
        nested = {"properties": {"child": nested}}
    for schema in [nested, {"const": "x" * 8193}]:
        response = api.post(
            f"/targets/{target_id}/evaluations",
            json={
                "attack_pack": pack(spec("json_schema", {"schema_definition": schema}))
            },
        )
        assert response.status_code == 422
    factory.assert_not_called()


def test_evaluator_exception_is_an_error_and_does_not_abort_later_checks(
    engine_api, monkeypatch
):
    def broken(*_):
        raise RuntimeError("synthetic-sensitive-evaluator-detail")

    monkeypatch.setattr(registry, "_strategies", dict(registry._strategies))
    registry.register(Strategy("broken_test", 1, Config, broken))
    api, target_id, client, _ = engine_api
    payload = pack(spec("broken_test", {}))
    payload["attacks"].append(
        {
            **payload["attacks"][0],
            "id": "next",
            "assertions": [spec("exact_match", {"values": ["SAFE"]})],
        }
    )
    response = api.post(
        f"/targets/{target_id}/evaluations", json={"attack_pack": payload}
    )
    assert response.status_code == 201
    run = response.json()
    assert run["metrics"]["errored"] == 1 and run["metrics"]["passed"] == 1
    results = api.get(f"/evaluations/{run['id']}/results")
    assert "synthetic-sensitive" not in results.text
    assert client.send_prompt.call_count == 2


def test_redaction_handles_case_variants_in_text_and_structured_observations(
    engine_api,
):
    api, target_id, client, _ = engine_api
    client.send_prompt.return_value = TargetResponse(
        "FAKE-TEST-KEY",
        2,
        status_code=200,
        document={"response": "FAKE-TEST-KEY"},
        has_document=True,
    )
    run = api.post(
        f"/targets/{target_id}/evaluations",
        json={"attack_pack": pack(spec("status_code", {"allowed": [200]}))},
    ).json()
    results = api.get(f"/evaluations/{run['id']}/results")
    assert "fake-test-key" not in results.text.lower()
    assert results.json()[0]["observation_snapshot"]["document"] == {
        "response": "[REDACTED]"
    }


def test_malformed_extension_outcome_becomes_error(engine_api, monkeypatch):
    monkeypatch.setattr(registry, "_strategies", dict(registry._strategies))
    registry.register(Strategy("bad_outcome_test", 1, Config, lambda *_: None))
    api, target_id, _, _ = engine_api
    response = api.post(
        f"/targets/{target_id}/evaluations",
        json={"attack_pack": pack(spec("bad_outcome_test", {}))},
    )
    assert response.status_code == 201
    assert response.json()["metrics"]["errored"] == 1


def test_json_parser_resource_limit_is_not_a_behavioral_failure():
    observation = TargetResponse("[" * 2000 + "0" + "]" * 2000, 1)
    outcome = evaluate_assertion(spec("json_valid", {}), observation, ())
    assert outcome.outcome == "errored" and outcome.code == "json_depth_limit"


@pytest.mark.parametrize("source", ["text_json", "document", "value"])
@pytest.mark.parametrize("depth", [100, 101])
def test_json_depth_boundary_is_explicit_for_each_source(source, depth):
    value = 0
    for _ in range(depth):
        value = [value]
    observation = TargetResponse(
        json.dumps(value),
        1,
        document=value,
        value=value,
        has_document=True,
        has_value=True,
    )
    for evaluator, extra in [
        ("json_valid", {}),
        ("json_schema", {"schema_definition": True}),
    ]:
        outcome = evaluate_assertion(
            spec(evaluator, {"source": source, **extra}), observation, ()
        )
        assert outcome.outcome == ("passed" if depth == 100 else "errored")
        if depth > 100:
            assert outcome.code == "json_depth_limit"


def test_json_depth_check_ignores_escaped_quotes_and_brackets_in_strings():
    text = json.dumps({"value": '\\"' + "[{" * 2000})
    outcome = evaluate_assertion(spec("json_valid", {}), TargetResponse(text, 1), ())
    assert outcome.outcome == "passed"


def test_excessive_json_depth_is_rejected_before_parsing(monkeypatch):
    def unexpected_parse(*_args, **_kwargs):
        raise AssertionError("The JSON parser must not receive oversized nesting.")

    monkeypatch.setattr("app.evaluators.strategies.json.loads", unexpected_parse)
    outcome = evaluate_assertion(
        spec("json_valid", {}), TargetResponse("[" * 101 + "0" + "]" * 101, 1), ()
    )
    assert outcome.code == "json_depth_limit"
