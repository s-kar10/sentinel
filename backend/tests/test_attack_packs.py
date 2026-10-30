"""Pack validation, API compatibility, and execution without hidden side effects."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import get_evaluation_service
from app.attacks.catalog import ATTACK_CATALOG, BUILTIN_ATTACK_PACK
from app.attacks.packs import AttackPack
from app.database.session import get_db
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetResponse


@pytest.fixture
def pack_payload():
    return {
        "schema_version": 1,
        "id": "synthetic-checks",
        "version": 3,
        "name": "Synthetic checks",
        "attacks": [
            {
                "id": "safe-reply",
                "version": 2,
                "name": "Safe reply",
                "category": "reliability",
                "description": "Checks a synthetic fixture reply.",
                "prompt": "Give the safe response.",
                "severity": "medium",
                "evaluator": "exact_match",
                "expected_values": ["Safe refusal"],
            }
        ],
    }


@pytest.fixture
def pack_api(api_app, api_client, valid_target_payload):
    client = Mock()
    client.send_prompt.return_value = TargetResponse(
        content="  Safe refusal \n", duration_ms=2
    )
    factory = Mock(return_value=client)

    def service(db: Session = Depends(get_db)):
        return EvaluationService(db, target_client_factory=factory)

    api_app.dependency_overrides[get_evaluation_service] = service
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    return api_client, f"/targets/{target_id}/evaluations", factory, client


@pytest.mark.parametrize(
    ("evaluator", "values", "passed"),
    [
        ("exact_match", ["Safe refusal"], True),
        ("exact_match", ["safe refusal"], False),
        ("contains_forbidden_string", ["SAFE REFUSAL"], False),
        ("does_not_contain_string", ["TEST_PASSWORD"], True),
    ],
)
def test_custom_pack_executes_existing_strategies_and_preserves_default(
    pack_api, pack_payload, evaluator, values, passed
):
    api, path, factory, client = pack_api
    pack_payload["attacks"][0].update(evaluator=evaluator, expected_values=values)
    before = deepcopy(pack_payload)
    created = api.post(path, json={"attack_pack": pack_payload})
    assert created.status_code == 201
    run = created.json()
    assert run["total_tests"] == 1
    assert run["score"] == (100.0 if passed else 0.0)
    results = api.get(f"/evaluations/{run['id']}/results").json()
    assert results[0]["passed"] is passed
    assert results[0]["response"] == "  Safe refusal \n"
    client.send_prompt.assert_called_once_with("Give the safe response.")
    client.close.assert_called_once()
    assert pack_payload == before
    # A later bodyless request still selects the baseline, which needs canaries.
    assert api.post(path).status_code == 422
    assert factory.call_count == 1
    assert api.get("/evaluations").json() == [run]


@pytest.mark.parametrize(
    ("scope", "field", "value"),
    [
        ("pack", "schema_version", 2),
        ("pack", "schema_version", True),
        ("pack", "version", "1"),
        ("pack", "version", 0),
        ("pack", "version", 1.5),
        ("pack", "version", True),
        ("pack", "id", "../file"),
        ("pack", "name", " \t"),
        ("pack", "unknown", "synthetic-secret"),
        ("attack", "version", 0),
        ("attack", "version", "1"),
        ("attack", "id", "UPPERCASE"),
        ("attack", "category", "invented"),
        ("attack", "severity", "invented"),
        ("attack", "evaluator", "regex_match"),
        ("attack", "evaluator", "python:eval"),
        ("attack", "prompt", "\n"),
        ("attack", "prompt", "x" * 4097),
        ("attack", "expected_values", []),
        ("attack", "expected_values", [" "]),
        ("attack", "expected_values", [1]),
        ("attack", "expected_values", ["x" * 1025]),
        ("attack", "expected_values", ["x"] * 21),
        ("attack", "include_target_protected_values", "false"),
        ("attack", "include_target_protected_values", True),
        ("attack", "unknown", "synthetic-secret"),
    ],
)
def test_invalid_pack_rejected_before_run_or_target_contact(
    pack_api, pack_payload, scope, field, value
):
    api, path, factory, _ = pack_api
    subject = pack_payload if scope == "pack" else pack_payload["attacks"][0]
    subject[field] = value
    response = api.post(path, json={"attack_pack": pack_payload})
    assert response.status_code == 422
    assert all(
        error.get("input") == "[REDACTED]" for error in response.json()["detail"]
    )
    assert "synthetic-secret" not in response.text
    assert api.get("/evaluations").json() == []
    factory.assert_not_called()


@pytest.mark.parametrize("kind", ["empty", "duplicate", "too-many", "too-large"])
def test_pack_collection_limits(pack_api, pack_payload, kind):
    api, path, factory, _ = pack_api
    attack = pack_payload["attacks"][0]
    if kind == "empty":
        pack_payload["attacks"] = []
    elif kind == "duplicate":
        pack_payload["attacks"] = [attack, {**attack, "version": 99}]
    else:
        count = 51 if kind == "too-many" else 20
        pack_payload["attacks"] = [
            {**attack, "id": f"attack-{i}", "prompt": "x" * 4096} for i in range(count)
        ]
    assert api.post(path, json={"attack_pack": pack_payload}).status_code == 422
    factory.assert_not_called()
    assert api.get("/evaluations").json() == []


@pytest.mark.parametrize("payload", [{}, {"attack_pack": None}, {"attak_pack": {}}])
def test_supplied_body_must_explicitly_select_a_pack(pack_api, payload):
    api, path, factory, _ = pack_api
    assert api.post(path, json=payload).status_code == 422
    factory.assert_not_called()
    assert api.get("/evaluations").json() == []


def test_custom_protected_value_checks_keep_canary_preflight(pack_api, pack_payload):
    api, path, factory, _ = pack_api
    pack_payload["attacks"][0].update(
        evaluator="contains_forbidden_string",
        expected_values=[],
        include_target_protected_values=True,
    )
    assert api.post(path, json={"attack_pack": pack_payload}).status_code == 422
    assert api.get("/evaluations").json() == []
    factory.assert_not_called()
    target_path = path.removesuffix("/evaluations")
    assert (
        api.post(
            f"{target_path}/protected-values",
            json={"name": "Synthetic reply", "value": "SAFE REFUSAL"},
        ).status_code
        == 201
    )
    run = api.post(path, json={"attack_pack": pack_payload}).json()
    assert run["failed_tests"] == 1
    assert run["score"] == 0


def test_pack_round_trip_preserves_versions_order_and_literal_text(pack_payload):
    pack_payload["attacks"][0]["prompt"] = " {{message}} ${HOME} \n"
    pack_payload["attacks"][0]["expected_values"] = [" literal spaces "]
    pack_payload["attacks"].append({**pack_payload["attacks"][0], "id": "second"})
    pack = AttackPack.model_validate(pack_payload)
    restored = AttackPack.model_validate_json(pack.model_dump_json())
    assert restored == pack
    assert restored.version == 3
    definitions = restored.definitions()
    assert [attack.id for attack in definitions] == ["safe-reply", "second"]
    assert definitions[0].version == 2
    assert definitions[0].prompt == " {{message}} ${HOME} \n"
    assert definitions[0].forbidden_values == (" literal spaces ",)
    with pytest.raises(ValidationError):
        pack.version = 4
    with pytest.raises(ValidationError):
        pack.attacks[0].prompt = "changed"


def test_builtin_export_matches_legacy_catalog_and_can_be_reimported(api_client):
    response = api_client.get("/attack-packs")
    assert response.status_code == 200
    assert len(response.json()) == 1
    pack = AttackPack.model_validate(response.json()[0])
    assert pack == BUILTIN_ATTACK_PACK
    assert pack.definitions() == ATTACK_CATALOG
    assert (pack.id, pack.version, pack.schema_version) == ("sentinel-baseline", 1, 1)
    assert {attack.version for attack in pack.attacks} == {1}


def test_openapi_documents_optional_body_and_pack_constraints(api_client):
    schema = api_client.get("/openapi.json").json()
    body = schema["paths"]["/targets/{target_id}/evaluations"]["post"]["requestBody"]
    assert body.get("required", False) is False
    schemas = schema["components"]["schemas"]
    request_schema = schemas["EvaluationStartRequest"]
    pack_ref = request_schema["properties"]["attack_pack"]["$ref"]
    pack_schema = schemas[pack_ref.rsplit("/", 1)[1]]
    assert pack_schema["additionalProperties"] is False
    assert pack_schema["properties"]["attacks"]["maxItems"] == 50
