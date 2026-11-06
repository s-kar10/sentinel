"""Atomic submission and serialized, short queue transactions; no network under lock."""

import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from random import SystemRandom

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.attacks.packs import AttackPack
from app.core.config import get_settings
from app.judges.runtime import settings_snapshot
from app.models import EvaluationRun, EvaluationStatus, TargetApplication
from app.models.job import EvaluationJob, QueueControl
from app.services.errors import (
    ConflictError,
    InvalidTargetConfigurationError,
    ResourceNotFoundError,
)
from app.services.evaluation_service import EvaluationService
from app.services.provenance import canonical, redact

GLOBAL_CONCURRENCY = 2
DISPATCH_INTERVAL = 0.5
CASE_TIMEOUT = 60
LEASE_SECONDS = 75
RUN_TIMEOUT = 1800
MAX_ATTEMPTS = 3
RESULT_FIELDS = (
    "outcome_code",
    "passed",
    "response",
    "response_status",
    "observation_snapshot",
    "duration_ms",
    "assertion_results",
    "failure_reason",
)


@dataclass(frozen=True)
class Claim:
    run_id: int
    token: str
    payload: dict
    index: int
    timeout: float


def error_result(reason: str) -> dict:
    return dict(
        outcome_code="errored",
        passed=False,
        response=None,
        response_status=None,
        observation_snapshot={"error": reason},
        duration_ms=0,
        assertion_results=[],
        failure_reason=reason,
    )


class JobService:
    def __init__(self, db: Session, settings=None):
        self.db = db
        self.settings = settings or get_settings()
        self.evaluations = EvaluationService(
            db,
            target_client_factory=lambda _: None,
            judge_runtime=settings_snapshot(self.settings),
        )

    def _lock(self):
        # UPDATE locks a row in PostgreSQL and starts a write transaction in SQLite.
        # Every queue mutation takes this same lock; HTTP work never holds it.
        self.db.execute(
            update(QueueControl)
            .where(QueueControl.id == 1)
            .values(next_dispatch=QueueControl.next_dispatch)
        )
        self.db.expire_all()

    def submit(
        self,
        target_id: int,
        *,
        attack_pack: AttackPack | None = None,
        idempotency_key: str | None = None,
        versions: dict | None = None,
    ) -> EvaluationRun:
        self.evaluations._get_target(target_id)
        versions = {k: v for k, v in (versions or {}).items() if v is not None}
        request_digest = sha256(
            canonical(
                {
                    "target": target_id,
                    "pack": attack_pack.model_dump(mode="json")
                    if attack_pack
                    else None,
                    "versions": versions or {},
                }
            ).encode()
        ).hexdigest()
        key = (
            sha256(f"{target_id}:{idempotency_key}".encode()).hexdigest()
            if idempotency_key
            else None
        )
        self._lock()
        if key:
            existing = self.db.scalar(
                select(EvaluationJob).where(EvaluationJob.idempotency_key == key)
            )
            if existing:
                if existing.request_digest != request_digest:
                    self.db.rollback()
                    raise ConflictError(
                        "Idempotency key already used for a different request."
                    )
                run_id = existing.run_id
                self.db.commit()
                return self.evaluations.get_run(run_id)
        try:
            run, target, attacks, definitions, _ = self.evaluations.prepare(
                target_id, attack_pack=attack_pack
            )
            run.version_tags = redact(
                versions,
                [v.value for v in target.protected_values]
                + [
                    target.api_key or "",
                    self.evaluations.judge_runtime.get("api_key", ""),
                ],
            )
            if run.version_tags != versions:
                raise InvalidTargetConfigurationError(
                    "Version labels must not contain target credentials or protected values."
                )
            transport = {
                "timeout_seconds": self.settings.target_request_timeout_seconds,
                "max_response_bytes": self.settings.target_max_response_bytes,
            }
            policy = {
                "mode": "durable-queue-v1",
                "transport": transport,
                "case_timeout": CASE_TIMEOUT,
                "max_attempts": MAX_ATTEMPTS,
            }
            run.pack_snapshot = {**run.pack_snapshot, "execution_policy": policy}
            run.pack_digest = sha256(canonical(run.pack_snapshot).encode()).hexdigest()
            run.comparison_key = sha256(
                canonical(
                    {"configuration": run.comparison_key, "policy": policy}
                ).encode()
            ).hexdigest()
            target_config = {
                name: getattr(target, name)
                for name in (
                    "id",
                    "project_id",
                    "name",
                    "endpoint_url",
                    "http_method",
                    "api_key",
                    "request_template",
                    "prompt_field",
                    "response_field",
                )
            }
            payload = {
                "transport": transport,
                "target": target_config,
                "protected_values": [v.value for v in target.protected_values],
                "attacks": [asdict(a) for a in attacks],
                "definitions": definitions,
            }
            if any(
                spec["evaluator"] == "llm_judge"
                for specs in definitions
                for spec in specs
            ):
                payload["judge_runtime"] = dict(self.evaluations.judge_runtime)
                payload["target"]["id"] = target_id
            self.db.add(
                EvaluationJob(
                    run_id=run.id,
                    target_id=target_id,
                    idempotency_key=key,
                    request_digest=request_digest,
                    payload=payload,
                    deadline=time.time() + RUN_TIMEOUT,
                )
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.evaluations.get_run(run.id)

    def _terminal(self, job, run, status, now):
        job.state = "done"
        job.payload = None  # Remove copied credentials promptly on terminal state.
        job.token = None
        job.lease_until = 0
        run.status = status
        run.completed_at = datetime.fromtimestamp(now, timezone.utc)
        self.evaluations._apply_counts(run)

    def cancel(self, run_id: int) -> EvaluationRun:
        self._lock()
        run = self.evaluations.get_run(run_id)
        job = self.db.get(EvaluationJob, run_id)
        if job is None:
            self.db.rollback()
            raise ResourceNotFoundError("Queued evaluation not found.")
        if job.state != "done":
            self._terminal(job, run, EvaluationStatus.CANCELLED, time.time())
        self.db.commit()
        return run

    def _finish_case(self, job, run, result_data, now):
        result = run.results[job.cursor]
        for name in RESULT_FIELDS:
            setattr(result, name, result_data[name])
        result.attempt_count = job.attempts
        job.cursor += 1
        job.attempts = 0
        job.token = None
        job.lease_until = 0
        job.available_at = now
        job.state = "queued"
        self.evaluations._apply_counts(run)
        if job.cursor == len(run.results):
            self._terminal(job, run, EvaluationStatus.COMPLETED, now)

    def claim(self, *, now: float | None = None) -> Claim | None:
        now = time.time() if now is None else now
        self._lock()
        jobs = list(
            self.db.scalars(
                select(EvaluationJob)
                .where(EvaluationJob.state != "done")
                .order_by(EvaluationJob.available_at, EvaluationJob.run_id)
            )
        )
        for job in jobs:
            if not self._valid_owner(job):
                self._terminal(
                    job,
                    self.db.get(EvaluationRun, job.run_id),
                    EvaluationStatus.FAILED,
                    now,
                )
            elif job.deadline <= now:
                self._terminal(
                    job,
                    self.evaluations.get_run(job.run_id),
                    EvaluationStatus.FAILED,
                    now,
                )
            elif job.state == "leased" and job.lease_until <= now:
                if job.attempts >= MAX_ATTEMPTS:
                    self._finish_case(
                        job,
                        self.evaluations.get_run(job.run_id),
                        error_result("Worker lease expired; retry limit reached."),
                        now,
                    )
                else:
                    job.state = "queued"
                    job.token = None
                    job.lease_until = 0
                    job.available_at = now + self._backoff(job.attempts)
        active = [j for j in jobs if j.state == "leased"]
        control = self.db.get(QueueControl, 1)
        selected = None
        if len(active) < GLOBAL_CONCURRENCY and control.next_dispatch <= now:
            targets = {j.target_id for j in active}
            selected = next(
                (
                    j
                    for j in jobs
                    if j.state == "queued"
                    and j.available_at <= now
                    and j.target_id not in targets
                ),
                None,
            )
        claim = None
        if selected:
            selected.token = uuid.uuid4().hex
            selected.lease_until = now + LEASE_SECONDS
            selected.attempts += 1
            selected.state = "leased"
            control.next_dispatch = now + DISPATCH_INTERVAL
            run = self.evaluations.get_run(selected.run_id)
            run.status = EvaluationStatus.RUNNING
            run.started_at = run.started_at or datetime.fromtimestamp(now, timezone.utc)
            claim = Claim(
                selected.run_id,
                selected.token,
                selected.payload,
                selected.cursor,
                min(CASE_TIMEOUT, selected.deadline - now),
            )
        self.db.commit()
        return claim

    @staticmethod
    def _backoff(attempt):
        return min(2**attempt, 30) + SystemRandom().uniform(0, 1)

    def _valid_owner(self, job) -> bool:
        target = self.db.get(TargetApplication, job.target_id)
        run = self.db.get(EvaluationRun, job.run_id)
        payload = job.payload or {}
        frozen = payload.get("target", {})
        runtime = payload.get("judge_runtime", {})
        return bool(
            target
            and target.ownership
            and run
            and run.target_application_id == target.id
            and frozen.get("id") == target.id
            and frozen.get("project_id") == target.project_id
            and (
                not runtime
                or runtime.get("project_namespace")
                == target.ownership.project.cache_namespace
            )
        )

    def active(self, claim: Claim) -> bool:
        self.db.expire_all()
        job = self.db.get(EvaluationJob, claim.run_id)
        active = bool(
            job
            and self._valid_owner(job)
            and job.state == "leased"
            and job.token == claim.token
            and job.lease_until > time.time()
            and job.deadline > time.time()
        )
        self.db.rollback()
        return active

    def finish(
        self,
        claim: Claim,
        data: dict,
        *,
        retryable: bool = False,
        now: float | None = None,
    ) -> bool:
        now = time.time() if now is None else now
        self._lock()
        job = self.db.get(EvaluationJob, claim.run_id)
        if (
            not job
            or not self._valid_owner(job)
            or job.state != "leased"
            or job.token != claim.token
            or job.lease_until <= now
            or job.deadline <= now
        ):
            self.db.rollback()
            return False
        if retryable and job.attempts < MAX_ATTEMPTS:
            job.available_at = now + self._backoff(job.attempts)
            job.state = "queued"
            job.token = None
            job.lease_until = 0
        else:
            self._finish_case(job, self.evaluations.get_run(job.run_id), data, now)
        self.db.commit()
        return True
