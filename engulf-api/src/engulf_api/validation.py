from __future__ import annotations


def validate_exit_code(value: object, *, label: str = "exit_code") -> int:
    """Return an exact process exit code from 0 through 255."""
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{label} must be an integer from 0 through 255")
    return value
