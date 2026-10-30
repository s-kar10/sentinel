"""Behavior tests for target request construction and response normalization."""

import json

import httpx
import pytest

from app.models import TargetApplication
from app.services.target_client import TargetClient, TargetRequestError


def make_target(**overrides) -> TargetApplication:
    values = {
        "name": "Nested target",
        "endpoint_url": "https://target.example.test/chat",
        "http_method": "POST",
        "api_key": "fake-api-key",
        "request_template": {"input": {"messages": [{"content": "unchanged"}]}},
        "prompt_field": "input.messages.0.content",
        "response_field": "data.choices.0.message.content",
    }
    values.update(overrides)
    return TargetApplication(**values)


def test_client_inserts_nested_prompt_extracts_response_and_attaches_bearer_key() -> (
    None
):
    target = make_target()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer fake-api-key"
        assert payload["input"]["messages"][0]["content"] == "attack prompt"
        return httpx.Response(
            200,
            json={"data": {"choices": [{"message": {"content": "safe answer"}}]}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = TargetClient(target, http_client=http_client)

    result = client.send_prompt("attack prompt")

    assert result.content == "safe answer"
    assert result.duration_ms >= 0
    assert target.request_template["input"]["messages"][0]["content"] == "unchanged"
    http_client.close()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(503), "Target returned HTTP 503."),
        (httpx.Response(200, text="not-json"), "Target returned malformed JSON."),
        (
            httpx.Response(200, json={"data": {}}),
            "The configured response field was not present in the target response.",
        ),
        (
            httpx.Response(
                200,
                json={
                    "data": {"choices": [{"message": {"content": {"unsafe": True}}}]}
                },
            ),
            "The configured response field did not contain text.",
        ),
    ],
)
def test_client_returns_stable_errors_for_bad_target_responses(
    response: httpx.Response,
    message: str,
) -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
    client = TargetClient(make_target(), http_client=http_client)

    with pytest.raises(
        TargetRequestError, match=f"^{message.replace('.', r'\.')}$"
    ) as exc_info:
        client.send_prompt("attack")

    assert exc_info.value.duration_ms >= 0
    http_client.close()


def test_client_sanitizes_timeout_and_connection_errors() -> None:
    errors = [
        (
            httpx.ReadTimeout("upstream details fake-api-key"),
            "Target request timed out.",
        ),
        (
            httpx.ConnectError("private host details fake-api-key"),
            "Target application could not be reached.",
        ),
    ]

    for error, expected in errors:

        def handler(request: httpx.Request, error=error):
            error.request = request
            raise error

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        client = TargetClient(make_target(), http_client=http_client)
        with pytest.raises(TargetRequestError) as exc_info:
            client.send_prompt("attack")
        assert str(exc_info.value) == expected
        assert "fake-api-key" not in str(exc_info.value)
        http_client.close()


def test_client_enforces_response_size_limit() -> None:
    response = httpx.Response(200, content=b"x" * 101)
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
    client = TargetClient(
        make_target(), http_client=http_client, max_response_bytes=100
    )

    with pytest.raises(TargetRequestError, match="exceeded the allowed size"):
        client.send_prompt("attack")

    http_client.close()
