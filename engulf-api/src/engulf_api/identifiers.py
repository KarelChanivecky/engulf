from __future__ import annotations

import re

_segment = r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?"
_global_identifier_pattern = re.compile(rf"^{_segment}(?:\.{_segment})+$")


def validate_global_identifier(value: object, *, label: str) -> str:
    """Validate a lowercase, globally qualified plugin or context identifier."""
    if not isinstance(value, str) or not _global_identifier_pattern.fullmatch(value):
        raise ValueError(
            f"{label} must be a lowercase, dot-qualified identifier such as "
            "'com.example.name'"
        )
    return value
