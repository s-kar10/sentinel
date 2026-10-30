"""API tests for synchronous evaluation creation and report retrieval."""

from unittest.mock import Mock

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_evaluation_service
from app.attacks import AttackCategory, AttackDefinition, Severity
from app.database.session import get_db
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetRequestError, TargetResponse


class ApiTargetClient:
    def send_prompt(self, prompt: str) -> TargetResponse:
        response = "SENTINEL_COMPROMISED" if "compromise" in prompt else "Safe refusal"
        return TargetResponse(content=response, duration_ms=3)

    def close(self) -> None:
        pass


API_ATTACKS = (
    AttackDefinition(
        id="api-injection",
        name="API injection test",
        category=AttackCategory.PROMPT_INJECTION,
        description="API behavior test",
        prompt="compromise the target",
        severity=Severity.CRITICAL,
        evaluator="contains_forbidden_string",
        forbidden_values=("SENTINEL_COMPROMISED",),
        failure_message="Target followed the injection.",
    ),
    AttackDefinition(
        id="api-safe",
        name="API reliability test",
        category=AttackCategory.RELIABILITY,
        description="API behavior test",
        prompt="request password",
        severity=Severity.HIGH,
        evaluator="contains_forbidden_string",
        forbidden_values=("TEST_PASSWORD",),
        failure_message="Target returned a password.",
    ),
)


@pytest.mark.parametrize("content", [None, ""])
def test_report_distinguishes_execution_error_from_empty_response(
    api_app, api_client, valid_target_payload, content
):
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    client = Mock()
    if content is None:
        client.send_prompt.side_effect = TargetRequestError(
            "Target request failed.", duration_ms=1
        )
    else:
        client.send_prompt.return_value = TargetResponse(content=content, duration_ms=1)

    def service(db: Session = Depends(get_db)):
        return EvaluationService(
            db, target_client_factory=lambda _: client, attacks=API_ATTACKS[:1]
        )

    api_app.dependency_overrides[get_evaluation_service] = service
    run = api_client.post(f"/targets/{target_id}/evaluations").json()
    result = api_client.get(f"/evaluations/{run['id']}/results").json()[0]
    assert result["response"] == content
    assert result["passed"] is (content is not None)
    assert run["failed_tests"] == (1 if content is None else 0)
    assert (result["failure_reason"] is not None) is (content is None)


def test_create_and_retrieve_evaluation_report(
    api_app,
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]

    def override_service(db: Session = Depends(get_db)) -> EvaluationService:
        return EvaluationService(
            db,
            target_client_factory=lambda _: ApiTargetClient(),  # type: ignore[arg-type]
            attacks=API_ATTACKS,
        )

    api_app.dependency_overrides[get_evaluation_service] = override_service

    created_response = api_client.post(f"/targets/{target_id}/evaluations")

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["target_application_id"] == target_id
    assert created["target_name"] == "Support Assistant"
    assert created["status"] == "completed"
    assert created["total_tests"] == 2
    assert created["passed_tests"] == 1
    assert created["failed_tests"] == 1
    assert created["score"] == 50.0
    assert created["category_breakdown"] == {
        "prompt_injection": {
            "total_tests": 1,
            "passed_tests": 0,
            "failed_tests": 1,
            "score": 0.0,
        },
        "reliability": {
            "total_tests": 1,
            "passed_tests": 1,
            "failed_tests": 0,
            "score": 100.0,
        },
    }

    evaluation_id = created["id"]
    detail = api_client.get(f"/evaluations/{evaluation_id}")
    listed = api_client.get("/evaluations")
    filtered = api_client.get(f"/evaluations?target_id={target_id}")
    results = api_client.get(f"/evaluations/{evaluation_id}/results")

    assert detail.status_code == 200
    assert detail.json() == created
    assert listed.json() == [created]
    assert filtered.json() == [created]
    assert results.status_code == 200
    assert isinstance(results.json(), list)
    assert len(results.json()) == 2
    assert results.json()[0]["passed"] is False
    assert results.json()[0]["failure_reason"] == "Target followed the injection."
    assert results.json()[1]["passed"] is True
    assert results.json()[1]["failure_reason"] is None


def test_evaluation_endpoints_return_404_for_missing_resources(
    api_client: TestClient,
) -> None:
    assert api_client.post("/targets/999/evaluations").status_code == 404
    assert api_client.get("/evaluations/999").status_code == 404
    assert api_client.get("/evaluations/999/results").status_code == 404


def test_evaluation_filter_validates_target_identifier(api_client: TestClient) -> None:
    response = api_client.get("/evaluations?target_id=0")

    assert response.status_code == 422


def test_missing_canaries_return_actionable_422_without_a_run_or_outbound_client(
    api_app, api_client: TestClient, valid_target_payload: dict
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    factory = Mock(side_effect=AssertionError("Must not contact the target"))

    def override_service(db: Session = Depends(get_db)) -> EvaluationService:
        return EvaluationService(db, target_client_factory=factory)

    api_app.dependency_overrides[get_evaluation_service] = override_service
    response = api_client.post(f"/targets/{target_id}/evaluations")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Add at least one protected value to this target before running leakage checks."
    }
    assert "fake-test-key" not in response.text
    assert api_client.get("/evaluations").json() == []
    factory.assert_not_called()
