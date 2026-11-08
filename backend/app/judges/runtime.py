"""Provider-neutral execution, deadlines, usage accounting and versioned caching."""

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from random import SystemRandom

from app.evaluators.contracts import AssertionOutcome, Outcome
from app.judges import cache
from app.judges.contracts import (
    POLICY_VERSION,
    SYSTEM_INSTRUCTIONS,
    JudgeConfig,
    Judgment,
    ProviderResult,
)

_context: ContextVar[dict | None] = ContextVar("judge_context", default=None)


def settings_snapshot(settings) -> dict:
    return {
        "enabled": settings.judge_enabled,
        "provider": "openai",
        "model": settings.judge_model,
        "api_key": settings.openai_api_key.get_secret_value()
        if settings.openai_api_key and settings.auth_mode == "local"
        else "",
        "endpoint": "https://api.openai.com/v1/responses",
        "timeout": settings.judge_timeout_seconds,
        "cache_path": str(Path(settings.judge_cache_path).resolve())
        if settings.judge_cache_path
        else "",
        "input_price": settings.judge_input_usd_per_million,
        "output_price": settings.judge_output_usd_per_million,
        "price_version": settings.judge_price_version,
        "policy_version": POLICY_VERSION,
    }


def public_policy(runtime: dict) -> dict:
    return {
        key: value
        for key, value in runtime.items()
        if key
        not in {
            "api_key",
            "endpoint",
            "cache_path",
            "project_namespace",
            "credential_id",
            "credential_version",
            "credential_project_id",
            "credential_source",
        }
    }


@contextmanager
def judge_context(runtime: dict, secrets: list[str], scope: str, prompt: str):
    token = _context.set(
        dict(runtime=runtime, secrets=secrets, scope=scope, prompt=prompt)
    )
    try:
        yield
    finally:
        _context.reset(token)


def call_provider(
    provider: str, request: dict, runtime: dict, timeout: float
) -> ProviderResult:
    child = subprocess.Popen(
        [sys.executable, "-m", "app.judges.provider_worker"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        # Inherit the case process group so cancellation also kills provider work.
    )
    try:
        output, _ = child.communicate(
            json.dumps(
                {
                    "provider": provider,
                    "request": request,
                    "runtime": {**runtime, "timeout": min(timeout, runtime["timeout"])},
                }
            ).encode(),
            timeout=timeout,
        )
        if child.returncode != 0 or len(output) > 8192:
            return ProviderResult(error="judge_worker_failed")
        return ProviderResult.model_validate_json(output)
    except subprocess.TimeoutExpired:
        return ProviderResult(error="judge_timeout")
    except (ValueError, TypeError):
        return ProviderResult(error="judge_invalid_response")
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate()


def evaluate(observation, config: JudgeConfig, _protected) -> AssertionOutcome:
    from app.services.provenance import canonical, redact

    context = _context.get()
    if not context or not context["runtime"].get("enabled"):
        return AssertionOutcome(Outcome.ERRORED, "judge_disabled")
    runtime = context["runtime"]
    if config.provider != runtime["provider"] or config.model != runtime["model"]:
        return AssertionOutcome(Outcome.ERRORED, "judge_configuration_mismatch")
    if not runtime["api_key"]:
        return AssertionOutcome(Outcome.ERRORED, "judge_credentials_missing")
    if (
        observation.content is None
        or observation.error
        or observation.status_code is None
        or not 200 <= observation.status_code < 300
    ):
        return AssertionOutcome(Outcome.ERRORED, "judge_target_unavailable")
    if len(observation.content.encode()) > 16_384:
        return AssertionOutcome(Outcome.ERRORED, "judge_input_limit")
    secrets = context["secrets"] + [runtime["api_key"]]
    request = {
        "model": config.model,
        "instructions": redact(
            SYSTEM_INSTRUCTIONS
            + "\n"
            + config.instructions
            + "\nRubric:\n"
            + config.rubric,
            secrets,
        ),
        "input": canonical(
            {
                "target_prompt": redact(context["prompt"], secrets),
                "target_response": redact(observation.content, secrets),
            }
        ),
    }
    # Credential and endpoint changes cannot reuse another account/provider's cache.
    key = sha256(
        canonical(
            {
                "scope": context["scope"],
                "config": config.model_dump(),
                "request": request,
                "runtime": runtime,
            }
        ).encode()
    ).hexdigest()
    started = time.monotonic()
    base = {
        "provider": config.provider,
        "model": config.model,
        "model_version": config.model_version,
        "prompt_version": config.prompt_version,
        "rubric_version": config.rubric_version,
        "policy_version": POLICY_VERSION,
        "pass_score": config.pass_score,
        "price_version": runtime["price_version"],
    }
    cached = cache.access(runtime["cache_path"], key) if config.cache else None
    if cached:
        try:
            judgment = Judgment.model_validate(cached["judgment"])
            return _outcome(
                judgment,
                config,
                {
                    **base,
                    "cache_hit": True,
                    "attempts": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "usage_complete": True,
                    "estimated_cost_usd": 0,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "source": cached["source"],
                },
            )
        except (ValueError, KeyError, TypeError):
            pass
    input_tokens = output_tokens = 0
    usage_complete = True
    attempts = 0
    result = ProviderResult(error="judge_timeout")
    for attempt in range(2):
        remaining = runtime["timeout"] - (time.monotonic() - started)
        if remaining <= 0:
            break
        attempts += 1
        result = call_provider(config.provider, request, runtime, remaining)
        input_tokens += result.input_tokens or 0
        output_tokens += result.output_tokens or 0
        usage_complete &= (
            result.input_tokens is not None and result.output_tokens is not None
        )
        if not result.retryable or attempt == 1:
            break
        time.sleep(
            min(
                0.2 + SystemRandom().uniform(0, 0.2),
                max(0, runtime["timeout"] - (time.monotonic() - started)),
            )
        )
    cost = None
    if (
        usage_complete
        and runtime["input_price"] is not None
        and runtime["output_price"] is not None
    ):
        cost = round(
            (
                input_tokens * runtime["input_price"]
                + output_tokens * runtime["output_price"]
            )
            / 1_000_000,
            10,
        )
    evidence = {
        **base,
        "cache_hit": False,
        "attempts": attempts,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage_complete": usage_complete,
        "estimated_cost_usd": cost,
        "resolved_model": result.resolved_model,
        "latency_ms": round((time.monotonic() - started) * 1000),
    }
    if result.error or result.judgment is None:
        return AssertionOutcome(
            Outcome.ERRORED,
            result.error or "judge_invalid_output",
            redact(evidence, secrets),
        )
    judgment = Judgment(
        score=result.judgment.score,
        explanation=redact(result.judgment.explanation, secrets)[:1000],
    )
    evidence = redact(evidence, secrets)
    if config.cache:
        cache.access(
            runtime["cache_path"],
            key,
            {"judgment": judgment.model_dump(), "source": evidence},
        )
    return _outcome(judgment, config, evidence)


def _outcome(judgment, config, evidence):
    return AssertionOutcome(
        Outcome.PASSED if judgment.score >= config.pass_score else Outcome.FAILED,
        "judge_scored",
        {**evidence, **judgment.model_dump()},
    )
