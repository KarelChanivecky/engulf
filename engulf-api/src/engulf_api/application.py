from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationMetadata:
    """Immutable identity and presentation metadata for the active application."""

    application_id: str
    display_name: str
    vendor: str
    product: str
    short_product_name: str
    version: str

    def __post_init__(self) -> None:
        for field, value in (
            ("application_id", self.application_id),
            ("display_name", self.display_name),
            ("vendor", self.vendor),
            ("product", self.product),
            ("short_product_name", self.short_product_name),
            ("version", self.version),
        ):
            _validate_metadata_text(value, field=field)


def _validate_metadata_text(value: object, *, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field} must be nonempty without surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} cannot contain control characters")


__all__ = ["ApplicationMetadata"]
