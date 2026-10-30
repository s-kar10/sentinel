"""Tests for safe nested request/response path handling."""

import pytest

from app.utils.json_paths import JsonPathError, get_path_value, with_path_value


def test_nested_dict_and_list_paths_are_supported_without_mutating_template() -> None:
    template = {"payload": {"messages": [{"role": "user", "content": "original"}]}}

    request_body = with_path_value(
        template,
        "payload.messages.0.content",
        "adversarial prompt",
    )

    assert (
        get_path_value(request_body, "payload.messages.0.content")
        == "adversarial prompt"
    )
    assert get_path_value(template, "payload.messages.0.content") == "original"


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".payload",
        "payload..content",
        "payload.messages.first",
        "payload.messages.9",
    ],
)
def test_invalid_paths_raise_safe_errors(path: str) -> None:
    document = {"payload": {"messages": [{"content": ""}]}}

    with pytest.raises(JsonPathError):
        with_path_value(document, path, "prompt")


@pytest.mark.parametrize(
    "segment",
    ["²", "①", "-1", "first", "9", pytest.param("9" * 5000, id="oversized-integer")],
)
@pytest.mark.parametrize("nested", [False, True])
def test_invalid_list_indexes_raise_domain_errors_for_reads_and_writes(
    segment: str, nested: bool
) -> None:
    document = {"items": [{"content": "original"}] if nested else ["original"]}
    path = f"items.{segment}" + (".content" if nested else "")

    with pytest.raises(JsonPathError):
        get_path_value(document, path)
    with pytest.raises(JsonPathError):
        with_path_value(document, path, "replacement")

    assert document == {"items": [{"content": "original"}] if nested else ["original"]}


def test_unicode_dictionary_keys_and_convertible_decimal_indexes_still_work() -> None:
    document = {"items": [{"²": "original"}]}

    updated = with_path_value(document, "items.٠.²", "replacement")

    assert get_path_value(updated, "items.٠.²") == "replacement"
    assert get_path_value(document, "items.0.²") == "original"
