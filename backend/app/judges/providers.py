"""Small replaceable adapters. Exceptions and provider error bodies never escape."""

import json

import httpx
from pydantic import ValidationError

from app.judges.contracts import JudgeProvider, Judgment, ProviderResult


class OpenAIProvider:
    def evaluate(self, request: dict, runtime: dict) -> ProviderResult:
        body = {
            "model": request["model"],
            "instructions": request["instructions"],
            "input": [{"role": "user", "content": request["input"]}],
            "store": False,
            "max_output_tokens": 512,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sentinel_judgment",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "score": {"type": "integer"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["score", "explanation"],
                    },
                }
            },
        }
        try:
            with httpx.Client(
                timeout=runtime["timeout"], trust_env=False, follow_redirects=False
            ) as client:
                with client.stream(
                    "POST",
                    runtime["endpoint"],
                    json=body,
                    headers={"Authorization": f"Bearer {runtime['api_key']}"},
                ) as response:
                    if response.status_code != 200:
                        return ProviderResult(
                            error="judge_http_error",
                            retryable=response.status_code == 429
                            or response.status_code >= 500,
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65_536:
                            return ProviderResult(error="judge_response_limit")
            document = json.loads(raw)
            usage = document.get("usage") or {}
            # Preserve valid usage even when the model refuses or produces invalid output.
            metadata = {}
            for name in ("input_tokens", "output_tokens"):
                value = usage.get(name)
                if type(value) is int and value >= 0:
                    metadata[name] = value
            model = document.get("model")
            if isinstance(model, str) and len(model) <= 200:
                metadata["resolved_model"] = model
            if document.get("status") != "completed":
                return ProviderResult(error="judge_incomplete", **metadata)
            content = [
                part
                for item in document.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
            ]
            if any(part.get("type") == "refusal" for part in content):
                return ProviderResult(error="judge_refused", **metadata)
            texts = [
                part.get("text")
                for part in content
                if part.get("type") == "output_text"
            ]
            try:
                if len(texts) != 1:
                    raise ValueError
                judgment = Judgment.model_validate_json(texts[0])
            except (ValidationError, ValueError, TypeError):
                return ProviderResult(error="judge_invalid_output", **metadata)
            return ProviderResult(judgment=judgment, **metadata)
        except (httpx.TimeoutException, httpx.NetworkError):
            return ProviderResult(error="judge_transport_error", retryable=True)
        except Exception:
            return ProviderResult(error="judge_invalid_response")


PROVIDERS: dict[str, JudgeProvider] = {"openai": OpenAIProvider()}
