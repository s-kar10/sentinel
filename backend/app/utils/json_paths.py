"""Safe traversal of simple dot-delimited JSON paths.

Only dictionary keys and numeric list indexes are supported. This intentionally
does not implement expressions, wildcards, or evaluation of arbitrary code.
"""

from copy import deepcopy
from typing import Any


class JsonPathError(ValueError):
    """Raised when a configured path cannot be traversed safely."""


def _segments(path: str) -> list[str]:
    segments = path.split(".")
    if not path or any(not segment for segment in segments):
        raise JsonPathError("Path must contain non-empty dot-delimited segments.")
    return segments


def validate_path_syntax(path: str) -> str:
    """Validate the supported dot-path grammar without traversing a document."""

    _segments(path)
    return path


def _list_index(segment: str, length: int) -> int:
    """Normalize invalid indexes to the same error used by all path traversal."""

    if not segment.isdigit():
        raise JsonPathError(f"Path segment '{segment}' is not a list index.")
    try:
        # Some Unicode digits (e.g. ²) pass isdigit() but cannot be converted.
        # Python may also reject exceptionally long integer strings.
        index = int(segment)
    except ValueError as exc:
        raise JsonPathError(
            "Path segment cannot be converted to a list index."
        ) from exc
    if index >= length:
        raise JsonPathError(f"List index '{segment}' is out of range.")
    return index


def get_path_value(document: Any, path: str) -> Any:
    """Read a value from dictionaries/lists using a deterministic dot path."""

    current = document
    for segment in _segments(path):
        if isinstance(current, dict):
            if segment not in current:
                raise JsonPathError(f"Path segment '{segment}' does not exist.")
            current = current[segment]
        elif isinstance(current, list):
            current = current[_list_index(segment, len(current))]
        else:
            raise JsonPathError(f"Cannot traverse path segment '{segment}'.")
    return current


def with_path_value(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Return a deep copy with the value at an existing JSON path replaced."""

    copied = deepcopy(document)
    segments = _segments(path)
    current: Any = copied

    for segment in segments[:-1]:
        if isinstance(current, dict):
            if segment not in current:
                raise JsonPathError(f"Path segment '{segment}' does not exist.")
            current = current[segment]
        elif isinstance(current, list):
            current = current[_list_index(segment, len(current))]
        else:
            raise JsonPathError(f"Cannot traverse path segment '{segment}'.")

    final_segment = segments[-1]
    if isinstance(current, dict):
        if final_segment not in current:
            raise JsonPathError(f"Path segment '{final_segment}' does not exist.")
        current[final_segment] = value
    elif isinstance(current, list):
        current[_list_index(final_segment, len(current))] = value
    else:
        raise JsonPathError(f"Cannot set path segment '{final_segment}'.")

    return copied
