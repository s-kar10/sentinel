"""Synchronous orchestration of an evaluation run."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from platform import python_version

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.attacks import AttackDefinition, get_attack_catalog
from app.attacks.packs import AttackPack
from app.core.config import get_settings
from app.evaluators.contracts import aggregate
from app.evaluators.engine import AssertionRegistry, evaluate_assertion, registry
from app.evaluators.metrics import SCORING_VERSION, WEIGHTS
from app.evaluators.strategies import MAX_JSON_DEPTH
from app.judges.runtime import judge_context, public_policy, settings_snapshot
from app.models import EvaluationRun, EvaluationStatus, TargetApplication, TestResult
from app.services.errors import (
    EvaluationExecutionError,
    InvalidTargetConfigurationError,
    ResourceNotFoundError,
)
from app.services.provenance import (
    assertion_definitions,
    attack_snapshot,
    canonical,
    redact,
)
from app.services.target_client import TargetClient, TargetRequestError

TargetClientFactory = Callable[[TargetApplication], TargetClient]


class EvaluationService:
    """Execute catalog attacks and persist every observation as it occurs."""

    def __init__(
        self,
        db: Session,
        *,
        target_client_factory: TargetClientFactory,
        attacks: Sequence[AttackDefinition] | None = None,
        evaluator_registry: AssertionRegistry = registry,
        judge_runtime: dict | None = None,
    ) -> None:
        self.db = db
        self.target_client_factory = target_client_factory
        self.attacks = tuple(attacks if attacks is not None else get_attack_catalog())
        self.evaluator_registry = evaluator_registry
        self.judge_runtime = (
            judge_runtime
            if judge_runtime is not None
            else settings_snapshot(get_settings())
        )

    def start(
        self, target_id: int, *, attack_pack: AttackPack | None = None
    ) -> EvaluationRun:
        """Create and fully execute a run, recording target failures per test."""

        run, target, attacks, definitions, secrets = self.prepare(
            target_id, attack_pack=attack_pack
        )
        self.db.commit()

        run.status = EvaluationStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        self.db.commit()

        client: TargetClient | None = None
        try:
            client = self.target_client_factory(target)
            for attack, specs, result in zip(attacks, definitions, run.results):
                self._execute_attack(result, client, attack, target, specs, secrets)
                # Persist each observation so partial evidence survives a later failure.
                self.db.commit()

            self._complete_run(run)
            self.db.commit()
            return self.get_run(run.id)
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.get(EvaluationRun, run.id)
            if failed_run is not None:
                failed_run.status = EvaluationStatus.FAILED
                failed_run.completed_at = datetime.now(timezone.utc)
                self.db.refresh(failed_run, attribute_names=["results"])
                self._apply_counts(failed_run)
                self.db.commit()
            raise EvaluationExecutionError(
                "Evaluation could not be completed."
            ) from exc
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    # Closing a transport must not rewrite a successfully persisted run.
                    pass

    def prepare(self, target_id: int, *, attack_pack: AttackPack | None = None):
        """Validate and stage immutable planned results in the caller's transaction."""
        target = self._get_target(target_id)
        attacks = attack_pack.definitions() if attack_pack is not None else self.attacks
        try:
            definitions = [
                assertion_definitions(attack, self.evaluator_registry)
                for attack in attacks
            ]
        except (ValueError, TypeError, KeyError):
            raise InvalidTargetConfigurationError(
                "Invalid evaluator configuration."
            ) from None
        # Validate before creating a run or a client: missing coverage must not
        # become a passing score or trigger any outbound requests.
        if any(
            spec["config"].get("include_target_protected_values")
            for specs in definitions
            for spec in specs
        ):
            if not any(value.value.strip() for value in target.protected_values):
                raise InvalidTargetConfigurationError(
                    "Add at least one protected value to this target before running leakage checks."
                )
        has_judge = any(
            spec["evaluator"] == "llm_judge" for specs in definitions for spec in specs
        )
        if has_judge:
            if not self.judge_runtime["enabled"] or not self.judge_runtime["api_key"]:
                raise InvalidTargetConfigurationError(
                    "Semantic judging requires JUDGE_ENABLED and OPENAI_API_KEY on the server."
                )
            if any(
                spec["config"]["provider"] != self.judge_runtime["provider"]
                or spec["config"]["model"] != self.judge_runtime["model"]
                for specs in definitions
                for spec in specs
                if spec["evaluator"] == "llm_judge"
            ):
                raise InvalidTargetConfigurationError(
                    "Judge provider/model must match the server's configured judge model."
                )
        secrets = [value.value for value in target.protected_values] + [
            target.api_key or "",
            self.judge_runtime.get("api_key", ""),
        ]
        snapshots = [
            redact(attack_snapshot(attack, specs), secrets)
            for attack, specs in zip(attacks, definitions)
        ]
        snapshot = {
            "id": attack_pack.id
            if attack_pack
            else "sentinel-baseline"
            if attacks == get_attack_catalog()
            else "internal-suite",
            "version": attack_pack.version if attack_pack else 1,
            "schema_version": attack_pack.schema_version if attack_pack else 1,
            "attacks": snapshots,
            "severity_weights": WEIGHTS,
            "redaction_policy": "known-target-secrets-v1",
            "runtime": {
                "python": python_version(),
                "jsonschema": version("jsonschema"),
                "json_depth_limit": MAX_JSON_DEPTH,
            },
            "protected_value_count": len(target.protected_values),
            "target_mapping": {
                "prompt_field": target.prompt_field,
                "response_field": target.response_field,
            },
        }
        if has_judge:
            snapshot["judge_policy"] = public_policy(self.judge_runtime)
        snapshot = redact(snapshot, secrets)
        # Scoring constants are structural metadata, not user-supplied text.
        snapshot["severity_weights"] = dict(WEIGHTS)
        run = EvaluationRun(
            target_application=target,
            status=EvaluationStatus.PENDING,
            total_tests=len(attacks),
            engine_version="2.0",
            scoring_version=SCORING_VERSION,
            comparison_key=sha256(
                canonical(
                    {
                        "pack": {
                            "id": attack_pack.id
                            if attack_pack
                            else "sentinel-baseline",
                            "version": attack_pack.version if attack_pack else 1,
                        },
                        "attacks": [
                            attack_snapshot(attack, specs)
                            for attack, specs in zip(attacks, definitions)
                        ],
                        "target": {
                            name: getattr(target, name)
                            for name in (
                                "endpoint_url",
                                "api_key",
                                "request_template",
                                "prompt_field",
                                "response_field",
                            )
                        },
                        "protected_values": sorted(
                            v.value for v in target.protected_values
                        ),
                        "engine": "2.0",
                        "scoring": SCORING_VERSION,
                        "runtime": {
                            "python": python_version(),
                            "jsonschema": version("jsonschema"),
                            "json_depth_limit": MAX_JSON_DEPTH,
                        },
                    }
                ).encode()
            ).hexdigest(),
            pack_snapshot=snapshot,
            pack_digest=sha256(canonical(snapshot).encode()).hexdigest(),
        )
        run.results = [
            TestResult(
                test_name=redact(attack.name, secrets),
                category=attack.category.value,
                severity=attack.severity.value,
                prompt=redact(attack.prompt, secrets),
                passed=False,
                duration_ms=0,
                outcome_code="untested",
                provenance=saved,
                assertion_results=[],
            )
            for attack, saved in zip(attacks, snapshots)
        ]
        if has_judge:
            run.comparison_key = sha256(
                canonical(
                    {
                        "configuration": run.comparison_key,
                        "judge_policy": public_policy(self.judge_runtime),
                        "endpoint": self.judge_runtime["endpoint"],
                    }
                ).encode()
            ).hexdigest()
        self.db.add(run)
        self.db.flush()

        return run, target, attacks, definitions, secrets

    def list_runs(self, *, target_id: int | None = None) -> list[EvaluationRun]:
        statement = (
            select(EvaluationRun)
            .options(
                selectinload(EvaluationRun.target_application),
                selectinload(EvaluationRun.results),
            )
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        )
        if target_id is not None:
            statement = statement.where(
                EvaluationRun.target_application_id == target_id
            )
        return list(self.db.scalars(statement).all())

    def get_run(self, evaluation_id: int) -> EvaluationRun:
        statement = (
            select(EvaluationRun)
            .where(EvaluationRun.id == evaluation_id)
            .options(
                selectinload(EvaluationRun.target_application),
                selectinload(EvaluationRun.results),
            )
        )
        run = self.db.scalar(statement)
        if run is None:
            raise ResourceNotFoundError("Evaluation run not found.")
        return run

    def get_results(self, evaluation_id: int) -> list[TestResult]:
        run = self.get_run(evaluation_id)
        return list(run.results)

    def _get_target(self, target_id: int) -> TargetApplication:
        statement = (
            select(TargetApplication)
            .where(TargetApplication.id == target_id)
            .options(selectinload(TargetApplication.protected_values))
        )
        target = self.db.scalar(statement)
        if target is None:
            raise ResourceNotFoundError("Target application not found.")
        return target

    def _execute_attack(
        self,
        result: TestResult,
        client: TargetClient,
        attack: AttackDefinition,
        target: TargetApplication,
        specs: list[dict],
        secrets: list[str],
    ) -> bool:
        transport_error = None
        try:
            observation = client.send_prompt(attack.prompt)
        except TargetRequestError as exc:
            observation = exc.observation
            transport_error = str(exc)

        protected = tuple(
            value.value for value in target.protected_values if value.value.strip()
        )
        assertions = []
        for index, spec in enumerate(specs):
            with judge_context(
                self.judge_runtime, secrets, str(target.id), attack.prompt
            ):
                outcome = evaluate_assertion(
                    spec, observation, protected, self.evaluator_registry
                )
            assertions.append(
                {
                    "index": index,
                    "evaluator": spec["evaluator"],
                    "version": spec["version"],
                    "outcome": outcome.outcome.value,
                    "code": outcome.code,
                    "evidence": outcome.evidence,
                }
            )
        state = aggregate([item["outcome"] for item in assertions])
        result.outcome_code = state
        result.passed = state == "passed"
        result.response = redact(observation.content, secrets)
        result.response_status = observation.status_code
        result.observation_snapshot = redact(
            {
                "has_document": observation.has_document,
                "document": observation.document,
                "has_value": observation.has_value,
                "error": observation.error,
            },
            secrets,
        )
        result.duration_ms = observation.duration_ms
        result.assertion_results = redact(assertions, secrets)
        reason = None
        if state == "failed":
            reason = attack.failure_message
        elif state == "errored":
            reason = transport_error or "One or more assertions could not be evaluated."
        elif state == "not_applicable":
            reason = "No assertions applied to this response status."
        result.failure_reason = redact(reason, secrets)
        return observation.retryable and state == "errored"

    def _complete_run(self, run: EvaluationRun) -> None:
        self.db.refresh(run, attribute_names=["results"])
        run.status = EvaluationStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        self._apply_counts(run)

    @staticmethod
    def _apply_counts(run: EvaluationRun) -> None:
        run.total_tests = len(run.results)
        run.passed_tests = sum(result.passed for result in run.results)
        run.failed_tests = run.total_tests - run.passed_tests
        run.score = (
            round((run.passed_tests / run.total_tests) * 100, 2)
            if run.total_tests
            else 0.0
        )
