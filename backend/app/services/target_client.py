"""HTTP adapter for calling configured target AI applications."""

import json
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx

from app.models import TargetApplication
from app.utils.json_paths import JsonPathError, get_path_value, with_path_value


@dataclass(frozen=True, slots=True)
class TargetResponse:
    """Normalized target response and measured request duration."""

    content: str | None
    duration_ms: int
    status_code: int | None = None
    document: Any = None
    value: Any = None
    has_document: bool = False
    has_value: bool = False
    error: str | None = None
    retryable: bool = False


class TargetRequestError(Exception):
    """A sanitized target failure that is safe to persist and return."""

    def __init__(
        self,
        message: str,
        *,
        duration_ms: int,
        observation: TargetResponse | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.duration_ms = duration_ms
        self.observation = observation or TargetResponse(
            None, duration_ms, error=message, retryable=retryable
        )


class TargetClient:
    """Build target requests and normalize untrusted HTTP responses."""

    def __init__(
        self,
        target: TargetApplication,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.target = target
        self.max_response_bytes = max_response_bytes
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send_prompt(self, prompt: str) -> TargetResponse:
        """Send one prompt, raising only sanitized, duration-aware errors."""

        started = monotonic()
        try:
            payload = with_path_value(
                self.target.request_template,
                self.target.prompt_field,
                prompt,
            )
        except JsonPathError as exc:
            raise TargetRequestError(
                "The configured prompt field is invalid.",
                duration_ms=self._elapsed_ms(started),
            ) from exc

        headers = {"Accept": "application/json"}
        if self.target.api_key:
            headers["Authorization"] = f"Bearer {self.target.api_key}"

        try:
            with self._client.stream(
                self.target.http_method,
                self.target.endpoint_url,
                json=payload,
                headers=headers,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise TargetRequestError(
                        f"Target returned HTTP {response.status_code}.",
                        duration_ms=self._elapsed_ms(started),
                        observation=TargetResponse(
                            None,
                            self._elapsed_ms(started),
                            status_code=response.status_code,
                            error="Non-success HTTP response.",
                            retryable=response.status_code == 429
                            or response.status_code >= 500,
                        ),
                    )

                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    if int(content_length) > self.max_response_bytes:
                        raise TargetRequestError(
                            "Target response exceeded the allowed size.",
                            duration_ms=self._elapsed_ms(started),
                        )

                response_bytes = bytearray()
                for chunk in response.iter_bytes():
                    response_bytes.extend(chunk)
                    if len(response_bytes) > self.max_response_bytes:
                        raise TargetRequestError(
                            "Target response exceeded the allowed size.",
                            duration_ms=self._elapsed_ms(started),
                        )
        except TargetRequestError:
            raise
        except httpx.TimeoutException as exc:
            raise TargetRequestError(
                "Target request timed out.",
                retryable=True,
                duration_ms=self._elapsed_ms(started),
            ) from exc
        except httpx.RequestError as exc:
            raise TargetRequestError(
                "Target application could not be reached.",
                retryable=True,
                duration_ms=self._elapsed_ms(started),
            ) from exc

        duration_ms = self._elapsed_ms(started)

        try:
            response_document = json.loads(
                response_bytes,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise TargetRequestError(
                "Target returned malformed JSON.",
                duration_ms=duration_ms,
                observation=TargetResponse(
                    None,
                    duration_ms,
                    status_code=response.status_code,
                    error="Malformed JSON.",
                ),
            ) from exc

        try:
            extracted = get_path_value(response_document, self.target.response_field)
        except JsonPathError as exc:
            raise TargetRequestError(
                "The configured response field was not present in the target response.",
                duration_ms=duration_ms,
                observation=TargetResponse(
                    None,
                    duration_ms,
                    status_code=response.status_code,
                    document=response_document,
                    has_document=True,
                    error="Missing response field.",
                ),
            ) from exc

        if not isinstance(extracted, str):
            raise TargetRequestError(
                "The configured response field did not contain text.",
                duration_ms=duration_ms,
                observation=TargetResponse(
                    None,
                    duration_ms,
                    status_code=response.status_code,
                    document=response_document,
                    value=extracted,
                    has_document=True,
                    has_value=True,
                    error="Response field is not text.",
                ),
            )
        return TargetResponse(
            content=extracted,
            duration_ms=duration_ms,
            status_code=response.status_code,
            document=response_document,
            value=extracted,
            has_document=True,
            has_value=True,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((monotonic() - started) * 1000))
