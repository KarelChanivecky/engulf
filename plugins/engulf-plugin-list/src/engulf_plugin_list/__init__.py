from __future__ import annotations

from collections.abc import Sequence

from engulf_api import (
    DiagnosticAPI,
    DiagnosticContribution,
    DiagnosticPlugin,
    DiagnosticRequest,
    PluginSource,
    PluginSourceKind,
)


class PluginListDiagnostic(DiagnosticPlugin):
    def diagnose(
        self,
        request: DiagnosticRequest,
        api: DiagnosticAPI,
    ) -> DiagnosticContribution:
        del request
        normal_rows = []
        for record in api.plugin_executions:
            metadata = record.metadata
            normal_rows.append(
                (
                    str(record.preprocess_position),
                    str(record.postprocess_position),
                    str(metadata.priority),
                    metadata.elevation_requirement.value,
                    metadata.plugin_id,
                    _source(record.source),
                )
            )
        diagnostic_rows = [
            (
                extension.diagnostic_id,
                ", ".join(extension.triggers) or "-",
                extension.distribution,
                extension.version,
                _availability(extension.available),
            )
            for extension in api.diagnostic_extensions
        ]
        output = "Normal goal plugins\n"
        output += _table(
            ("PRE", "POST", "PRIORITY", "ELEVATION", "PLUGIN ID", "SOURCE"),
            normal_rows,
        )
        output += "\nDiagnostic extensions\n"
        output += _table(
            (
                "DIAGNOSTIC ID",
                "TRIGGERS",
                "DISTRIBUTION",
                "VERSION",
                "AVAILABLE",
            ),
            diagnostic_rows,
        )
        return DiagnosticContribution(stdout=output)


def _availability(available: bool | None) -> str:
    if available is None:
        return "not checked"
    return "yes" if available else "no"


def _source(source: PluginSource) -> str:
    if source.kind is PluginSourceKind.INSTALLED:
        distribution = source.distribution_name or "unknown-distribution"
        version = source.distribution_version or "unknown"
        return f"installed {distribution}=={version} ({source.target})"
    if source.kind is PluginSourceKind.DIRECTORY:
        return f"directory {source.directory} ({source.target})"
    return f"direct {source.target}"


def _table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        ).rstrip()

    lines = [render(headers), render(tuple("-" * width for width in widths))]
    lines.extend(render(row) for row in rows)
    if not rows:
        lines.append("(none)")
    return "\n".join(lines) + "\n"


diagnostic = PluginListDiagnostic()

__all__ = ["PluginListDiagnostic", "diagnostic"]
