"""End-to-end service tests for execution, persistence, and scoring."""

import json
from collections.abc import Callable
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.orm import Session

from app.attacks import AttackCategory, AttackDefinition, Severity, get_attack_catalog
from app.models import EvaluationStatus, ProtectedValue, TargetApplication
from app.services.errors import (
    EvaluationExecutionError,
    InvalidTargetConfigurationError,
)
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetClient, TargetRequestError, TargetResponse


class ScriptedTargetClient:
    """Small target-client substitute that preserves service-boundary behavior."""

    def __init__(self, responder: Callable[[str], str]) -> None:
        self.responder = responder
        self.closed = False

    def send_prompt(self, prompt: str) -> TargetResponse:
        return TargetResponse(content=self.responder(prompt), duration_ms=7)

    def close(self) -> None:
        self.closed = True


class FailingTargetClient:
    def send_prompt(self, _: str) -> TargetResponse:
        raise TargetRequestError("Target request timed out.", duration_ms=25)

    def close(self) -> None:
        pass


def persist_target(db: Session) -> TargetApplication:
    target = TargetApplication(
        name="Evaluation target",
        endpoint_url="https://target.example.test/chat",
        http_method="POST",
        request_template={"message": ""},
        prompt_field="message",
        response_field="response",
    )
    target.protected_values.append(
        ProtectedValue(name="Fake secret", value="TEST_SECRET_ABC123")
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def attack(
    attack_id: str,
    category: AttackCategory,
    forbidden: tuple[str, ...] = (),
    *,
    protected: bool = False,
) -> AttackDefinition:
    return AttackDefinition(
        id=attack_id,
        name=f"Test {attack_id}",
        category=category,
        description="Behavior test",
        prompt=f"prompt-{attack_id}",
        severity=Severity.HIGH,
        evaluator="contains_forbidden_string",
        forbidden_values=forbidden,
        include_target_protected_values=protected,
        failure_message=f"Failure {attack_id}",
    )


def test_evaluation_detects_injection_and_protected_value_and_calculates_score(
    db_session: Session,
) -> None:
    target = persist_target(db_session)
    attacks = (
        attack(
            "injection",
            AttackCategory.PROMPT_INJECTION,
            ("SENTINEL_COMPROMISED",),
        ),
        attack(
            "protected", AttackCategory.SENSITIVE_INFORMATION_LEAKAGE, protected=True
        ),
        attack("safe-one", AttackCategory.RELIABILITY, ("TEST_PASSWORD",)),
        attack("safe-two", AttackCategory.SYSTEM_PROMPT_LEAKAGE, protected=True),
    )
    responses = {
        "prompt-injection": "SENTINEL_COMPROMISED",
        "prompt-protected": "The value is TEST_SECRET_ABC123",
        "prompt-safe-one": "I cannot provide passwords.",
        "prompt-safe-two": "I cannot repeat private instructions.",
    }
    client = ScriptedTargetClient(responses.__getitem__)
    service = EvaluationService(
        db_session,
        target_client_factory=lambda _: client,  # type: ignore[arg-type]
        attacks=attacks,
    )

    run = service.start(target.id)

    assert client.closed is True
    assert run.status == EvaluationStatus.COMPLETED
    assert run.total_tests == 4
    assert run.passed_tests == 2
    assert run.failed_tests == 2
    assert run.score == 50.0
    assert len(run.results) == 4
    assert run.results[0].passed is False
    assert run.results[0].failure_reason == "Failure injection"
    assert run.results[1].passed is False
    assert run.results[1].failure_reason == "Failure protected"
    assert run.results[2].passed is True
    assert run.results[2].failure_reason is None
    assert run.category_breakdown["prompt_injection"]["score"] == 0.0
    assert run.category_breakdown["reliability"]["score"] == 100.0


def test_failed_target_requests_become_failed_results_without_aborting_run(
    db_session: Session,
) -> None:
    target = persist_target(db_session)
    attacks = (
        attack("one", AttackCategory.PROMPT_INJECTION, ("X",)),
        attack("two", AttackCategory.RELIABILITY, ("Y",)),
    )
    service = EvaluationService(
        db_session,
        target_client_factory=lambda _: FailingTargetClient(),  # type: ignore[arg-type]
        attacks=attacks,
    )

    run = service.start(target.id)

    assert run.status == EvaluationStatus.COMPLETED
    assert run.total_tests == 2
    assert run.passed_tests == 0
    assert run.failed_tests == 2
    assert run.score == 0.0
    assert all(result.response is None for result in run.results)
    assert all(result.duration_ms == 25 for result in run.results)
    assert {result.failure_reason for result in run.results} == {
        "Target request timed out."
    }


def test_unexpected_execution_failure_marks_created_run_failed(
    db_session: Session,
) -> None:
    target = persist_target(db_session)
    service = EvaluationService(
        db_session,
        target_client_factory=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
        attacks=(attack("one", AttackCategory.RELIABILITY, ("X",)),),
    )

    with pytest.raises(EvaluationExecutionError, match="could not be completed"):
        service.start(target.id)

    runs = service.list_runs()
    assert len(runs) == 1
    assert runs[0].status == EvaluationStatus.FAILED
    assert runs[0].started_at is not None
    assert runs[0].completed_at is not None


def test_catalog_has_two_attacks_in_each_required_category() -> None:
    catalog = get_attack_catalog()

    assert len(catalog) == 8
    counts = {
        category: sum(item.category == category for item in catalog)
        for category in AttackCategory
    }
    assert counts == {category: 2 for category in AttackCategory}
    assert len({item.id for item in catalog}) == len(catalog)


@pytest.mark.parametrize("canary", [None, "", " \t\n"])
def test_missing_or_blank_canaries_reject_run_before_persistence_or_client_creation(
    db_session: Session, canary: str | None
) -> None:
    target = persist_target(db_session)
    target.protected_values.clear()
    if canary is not None:
        # Simulate legacy/direct database writes that bypass API validation.
        target.protected_values.append(
            ProtectedValue(name="Legacy canary", value=canary)
        )
    db_session.commit()
    factory = Mock(side_effect=AssertionError("No target client should be constructed"))
    service = EvaluationService(db_session, target_client_factory=factory)

    with pytest.raises(
        InvalidTargetConfigurationError, match="Add at least one protected value"
    ):
        service.start(target.id)

    factory.assert_not_called()
    assert service.list_runs() == []


def test_fixed_string_attacks_do_not_require_target_canaries(
    db_session: Session,
) -> None:
    target = persist_target(db_session)
    target.protected_values.clear()
    db_session.commit()
    client = ScriptedTargetClient(lambda _: "Safe refusal")
    service = EvaluationService(
        db_session,
        target_client_factory=lambda _: client,  # type: ignore[arg-type]
        attacks=(attack("fixed", AttackCategory.RELIABILITY, ("TEST_PASSWORD",)),),
    )

    run = service.start(target.id)

    assert run.status == EvaluationStatus.COMPLETED
    assert run.passed_tests == 1
    assert run.score == 100.0


def test_bad_response_path_fails_one_case_and_preserves_other_results(
    db_session: Session,
) -> None:
    target = persist_target(db_session)
    target.response_field = "answers.²"
    db_session.commit()
    prompts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["message"]
        prompts.append(prompt)
        # '²' is a valid object key but cannot be used as a list index.
        answers = (
            ["untrusted response"] if prompt == "prompt-bad" else {"²": "Safe refusal"}
        )
        return httpx.Response(200, json={"answers": answers})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        service = EvaluationService(
            db_session,
            target_client_factory=lambda target: TargetClient(
                target, http_client=http_client
            ),
            attacks=tuple(
                attack(name, AttackCategory.RELIABILITY, ("TEST_PASSWORD",))
                for name in ("before", "bad", "after")
            ),
        )
        run = service.start(target.id)

    db_session.expire_all()
    saved = service.get_run(run.id)
    assert prompts == ["prompt-before", "prompt-bad", "prompt-after"]
    assert saved.status == EvaluationStatus.COMPLETED
    assert (saved.total_tests, saved.passed_tests, saved.failed_tests, saved.score) == (
        3,
        2,
        1,
        66.67,
    )
    assert [result.passed for result in saved.results] == [True, False, True]
    failed = saved.results[1]
    assert failed.response is None
    assert failed.duration_ms >= 0
    assert (
        failed.failure_reason
        == "The configured response field was not present in the target response."
    )
