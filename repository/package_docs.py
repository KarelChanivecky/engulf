from __future__ import annotations

import fcntl
import html
import os
import re
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote

import bleach
import markdown

MAX_METADATA_BYTES = 8 * 1024 * 1024
NORMALIZE_PATTERN = re.compile(r"[-_.]+")
METADATA_ERRORS = (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile)
MARKDOWN_TAGS = frozenset(bleach.sanitizer.ALLOWED_TAGS).union(
    {
        "blockquote",
        "br",
        "code",
        "dd",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "p",
        "pre",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
    }
)
MARKDOWN_ATTRIBUTES = {
    "a": ("href", "title"),
    "code": ("class",),
    "th": ("align",),
    "td": ("align",),
}


@dataclass(frozen=True)
class DistributionMetadata:
    filename: str
    name: str
    version: str
    summary: str
    description: str
    description_content_type: str
    requires_python: str
    dependencies: tuple[str, ...]
    project_urls: tuple[tuple[str, str], ...]
    modified_ns: int


def normalize_project(name: str) -> str:
    return NORMALIZE_PATTERN.sub("-", name).lower()


def _metadata_bytes(path: Path) -> bytes:
    if path.suffix in (".whl", ".zip"):
        with zipfile.ZipFile(path) as archive:
            candidates = tuple(
                member
                for member in archive.infolist()
                if member.filename.endswith((".dist-info/METADATA", "/PKG-INFO"))
                and not member.is_dir()
                and member.file_size <= MAX_METADATA_BYTES
            )
            if not candidates:
                raise ValueError("distribution contains no readable metadata")
            return archive.read(min(candidates, key=lambda item: len(item.filename)))
    if path.name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        with tarfile.open(path, mode="r:*") as archive:
            candidates = tuple(
                member
                for member in archive.getmembers()
                if member.isfile()
                and member.name.endswith("/PKG-INFO")
                and member.size <= MAX_METADATA_BYTES
            )
            if not candidates:
                raise ValueError("distribution contains no readable metadata")
            selected = min(candidates, key=lambda item: len(item.name))
            extracted = archive.extractfile(selected)
            if extracted is None:
                raise ValueError("distribution metadata is unreadable")
            return extracted.read(MAX_METADATA_BYTES + 1)
    raise ValueError("unsupported distribution format")


def read_distribution_metadata(path: Path) -> DistributionMetadata:
    raw = _metadata_bytes(path)
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("distribution metadata is too large")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    name = str(message.get("Name", "")).strip()
    version = str(message.get("Version", "")).strip()
    if not name or not version:
        raise ValueError("distribution metadata has no name or version")
    payload = message.get_payload()
    description = payload if isinstance(payload, str) else ""
    project_urls: list[tuple[str, str]] = []
    for field in message.get_all("Project-URL", []):
        label, separator, url = str(field).partition(",")
        if separator and url.strip().startswith(("https://", "http://")):
            project_urls.append((label.strip(), url.strip()))
    return DistributionMetadata(
        filename=path.name,
        name=name,
        version=version,
        summary=str(message.get("Summary", "")).strip(),
        description=description.strip(),
        description_content_type=str(
            message.get("Description-Content-Type", "text/plain")
        ).strip(),
        requires_python=str(message.get("Requires-Python", "")).strip(),
        dependencies=tuple(
            str(value) for value in message.get_all("Requires-Dist", [])
        ),
        project_urls=tuple(project_urls),
        modified_ns=path.stat().st_mtime_ns,
    )


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>
body {{ font: 16px/1.5 system-ui,sans-serif; margin: 2rem auto; max-width: 72rem; padding: 0 1rem; color: #202124; }}
a {{ color: #0759a5; }} code,pre {{ background: #f5f5f5; }}
pre {{ border: 1px solid #ddd; overflow-wrap: anywhere; padding: 1rem; white-space: pre-wrap; }}
table {{ border-collapse: collapse; width: 100%; }} th,td {{ border-bottom: 1px solid #ddd; padding: .5rem; text-align: left; }}
</style></head><body>{body}</body></html>
"""


def render_description(description: str, content_type: str) -> str:
    if not description:
        return "<p>No package description was provided.</p>"
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type != "text/markdown":
        return f"<pre>{html.escape(description)}</pre>"
    rendered = markdown.markdown(
        description,
        extensions=("fenced_code", "sane_lists", "tables"),
        output_format="html",
    )
    return bleach.clean(
        rendered,
        tags=MARKDOWN_TAGS,
        attributes=MARKDOWN_ATTRIBUTES,
        protocols=("http", "https", "mailto"),
        strip=True,
    )


def _project_page(records: tuple[DistributionMetadata, ...]) -> str:
    latest = max(records, key=lambda item: item.modified_ns)
    versions = sorted({record.version for record in records}, reverse=True)
    artifacts = "".join(
        f'<li><a href="/packages/{quote(record.filename)}">{html.escape(record.filename)}</a></li>'
        for record in sorted(records, key=lambda item: item.filename)
    )
    links = "".join(
        f'<li><a href="{html.escape(url, quote=True)}">{html.escape(label)}</a></li>'
        for label, url in latest.project_urls
    )
    dependencies = "".join(
        f"<li><code>{html.escape(dependency)}</code></li>"
        for dependency in latest.dependencies
    )
    body = f"""
<nav><a href="/docs/">Engulf documentation</a> · <a href="/docs/packages/">Uploaded packages</a></nav>
<h1>{html.escape(latest.name)}</h1><p>{html.escape(latest.summary)}</p>
<dl><dt>Versions</dt><dd>{html.escape(", ".join(versions))}</dd>
<dt>Requires Python</dt><dd>{html.escape(latest.requires_python or "Not specified")}</dd>
<dt>Description format</dt><dd>{html.escape(latest.description_content_type)}</dd></dl>
{f"<h2>Project links</h2><ul>{links}</ul>" if links else ""}
{f"<h2>Dependencies</h2><ul>{dependencies}</ul>" if dependencies else ""}
<h2>Distribution files</h2><ul>{artifacts}</ul>
<h2>Package description</h2><section class="package-description">
{render_description(latest.description, latest.description_content_type)}
</section>
"""
    return _page(f"{latest.name} package documentation", body)


def _index_page(
    projects: dict[str, tuple[DistributionMetadata, ...]], failures: tuple[str, ...]
) -> str:
    rows = "".join(
        f'<tr><td><a href="/docs/packages/{quote(project)}/">{html.escape(records[0].name)}</a></td>'
        f"<td>{html.escape(', '.join(sorted({item.version for item in records}, reverse=True)))}</td>"
        f"<td>{html.escape(max(records, key=lambda item: item.modified_ns).summary)}</td></tr>"
        for project, records in sorted(projects.items())
    )
    failure_note = (
        f"<p>{len(failures)} artifact(s) had no readable Python package metadata.</p>"
        if failures
        else ""
    )
    return _page(
        "Uploaded package documentation",
        f"""<nav><a href="/docs/">Engulf documentation</a> · <a href="/">Package repository</a></nav>
<h1>Uploaded package documentation</h1>
<p>Generated automatically from metadata embedded in uploaded wheels and source distributions.</p>
{failure_note}<table><thead><tr><th>Package</th><th>Versions</th><th>Summary</th></tr></thead><tbody>{rows}</tbody></table>""",
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def refresh_package_documentation(packages: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".refresh.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        grouped: dict[str, list[DistributionMetadata]] = {}
        failures: list[str] = []
        for artifact in sorted(packages.iterdir()):
            if not artifact.is_file() or artifact.name.endswith(".asc"):
                continue
            try:
                metadata = read_distribution_metadata(artifact)
            except METADATA_ERRORS:
                failures.append(artifact.name)
                continue
            grouped.setdefault(normalize_project(metadata.name), []).append(metadata)
        projects = {project: tuple(records) for project, records in grouped.items()}
        for project, records in projects.items():
            _atomic_write(output / project / "index.html", _project_page(records))
        _atomic_write(output / "index.html", _index_page(projects, tuple(failures)))


def is_successful_package_upload(
    *, method: str, path: str, status_code: int, action: str | None
) -> bool:
    return (
        method == "POST"
        and path == "/"
        and 200 <= status_code < 300
        and action == "file_upload"
    )
