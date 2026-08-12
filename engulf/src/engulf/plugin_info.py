from __future__ import annotations

import re

from engulf_api import ActivePlugin, PluginSource, PluginSourceKind


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


__all__ = ["ActivePlugin", "PluginSource", "PluginSourceKind"]
