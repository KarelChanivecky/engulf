from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any

from engulf_api import (
    ActivePlugin,
    DiagnosticContribution,
    DiagnosticExtension,
    DiagnosticRequest,
    GoalRequirement,
    PluginExecutionRecord,
    validate_global_identifier,
)

from .plugin_info import _normalize_distribution_name
from .plugin_loader import PluginLoadError

DIAGNOSTIC_API_MAJOR = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticIsolationConfig:
    wall_timeout_seconds: float = 5.0
    cpu_seconds: int = 2
    address_space_bytes: int = 256 * 1024 * 1024
    child_processes: int = 1
    file_descriptors: int = 64
    scratch_bytes: int = 16 * 1024 * 1024
    protocol_limit_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if (
            isinstance(self.wall_timeout_seconds, bool)
            or not isinstance(self.wall_timeout_seconds, (int, float))
            or self.wall_timeout_seconds <= 0
        ):
            raise ValueError("diagnostic wall timeout must be positive")
        for field in (
            "cpu_seconds",
            "address_space_bytes",
            "child_processes",
            "file_descriptors",
            "scratch_bytes",
            "protocol_limit_bytes",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                raise ValueError(f"diagnostic {field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class _DiscoveredDiagnostic:
    descriptor: DiagnosticExtension
    entry_point: EntryPoint


@dataclass(frozen=True, slots=True)
class DiagnosticDiscovery:
    diagnostics: tuple[_DiscoveredDiagnostic, ...]
    isolation_available: bool
    unavailable_reason: str | None

    @property
    def descriptors(self) -> tuple[DiagnosticExtension, ...]:
        return tuple(item.descriptor for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class DiagnosticRunFailure:
    diagnostic_id: str
    message: str


@dataclass(frozen=True, slots=True)
class _ProcessOutput:
    returncode: int
    stdout: bytes
    stderr: bytes


def diagnostic_entry_point_group(goal_id: str, goal_api_major: int) -> str:
    validated = validate_global_identifier(goal_id, label="goal_id")
    if type(goal_api_major) is not int or goal_api_major < 1:
        raise ValueError("goal API major must be a positive integer")
    normalized = re.sub(r"[-_.]+", "_", validated)
    return (
        f"engulf.diagnostics.v{DIAGNOSTIC_API_MAJOR}.goal."
        f"v{goal_api_major}.{normalized}"
    )


def diagnostic_trigger_entry_point_group(goal_id: str, goal_api_major: int) -> str:
    return (
        diagnostic_entry_point_group(goal_id, goal_api_major)
        + ".triggers.before_separator"
    )


def discover_diagnostics(
    requirement: GoalRequirement,
    config: DiagnosticIsolationConfig,
    *,
    discover_installed: bool,
) -> DiagnosticDiscovery:
    if not discover_installed:
        return DiagnosticDiscovery((), False, "installed discovery is disabled")
    catalog_group = diagnostic_entry_point_group(
        requirement.goal_id, requirement.api_major
    )
    trigger_group = diagnostic_trigger_entry_point_group(
        requirement.goal_id, requirement.api_major
    )
    catalog = _catalog(catalog_group, identifiers=True)
    triggers = _catalog(trigger_group, identifiers=False)
    if not catalog and not triggers:
        return DiagnosticDiscovery((), False, None)

    triggers_by_source: dict[tuple[str, str, str], list[str]] = {}
    seen_triggers: set[str] = set()
    for trigger, declaration in triggers.items():
        _validate_trigger(trigger)
        if trigger in seen_triggers:
            raise PluginLoadError(f"duplicate diagnostic trigger {trigger!r}")
        seen_triggers.add(trigger)
        triggers_by_source.setdefault(_source_key(declaration), []).append(trigger)

    available, reason = _isolation_available(config, next(iter(catalog.values())))
    discovered: list[_DiscoveredDiagnostic] = []
    catalog_sources: set[tuple[str, str, str]] = set()
    for diagnostic_id, declaration in catalog.items():
        source = _source_key(declaration)
        catalog_sources.add(source)
        descriptor = DiagnosticExtension(
            diagnostic_id=diagnostic_id,
            triggers=tuple(sorted(triggers_by_source.get(source, ()))),
            distribution=source[0],
            version=source[1],
            target=declaration.value,
            available=available,
            unavailable_reason=None if available else reason,
        )
        discovered.append(_DiscoveredDiagnostic(descriptor, declaration))
    unmatched = set(triggers_by_source) - catalog_sources
    if unmatched:
        raise PluginLoadError(
            "diagnostic trigger declaration does not match a diagnostic catalog entry"
        )
    discovered.sort(
        key=lambda item: (
            _normalize_distribution_name(item.descriptor.distribution),
            item.descriptor.diagnostic_id,
        )
    )
    return DiagnosticDiscovery(tuple(discovered), available, reason)


def matching_diagnostics(
    discovery: DiagnosticDiscovery, arguments: tuple[str, ...]
) -> tuple[_DiscoveredDiagnostic, ...]:
    before_separator = (
        arguments[: arguments.index("--")] if "--" in arguments else arguments
    )
    present = frozenset(before_separator)
    return tuple(
        item
        for item in discovery.diagnostics
        if present.intersection(item.descriptor.triggers)
    )


class BubblewrapDiagnosticRunner:
    def __init__(self, config: DiagnosticIsolationConfig) -> None:
        self._config = config

    def run(
        self,
        diagnostic: _DiscoveredDiagnostic,
        request: DiagnosticRequest,
        active_plugins: tuple[ActivePlugin, ...],
        plugin_executions: tuple[PluginExecutionRecord, ...],
        diagnostic_extensions: tuple[DiagnosticExtension, ...],
        elevated: bool,
    ) -> DiagnosticContribution:
        payload = _encode_request(
            diagnostic,
            request,
            active_plugins,
            plugin_executions,
            diagnostic_extensions,
            elevated,
            self._config,
        )
        command = _bubblewrap_command(diagnostic.entry_point, self._config)
        limit = self._config.protocol_limit_bytes
        try:
            completed = _run_bounded(
                command,
                payload,
                timeout=self._config.wall_timeout_seconds,
                limit=limit,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("diagnostic exceeded its wall timeout") from error
        if completed.stderr:
            detail = completed.stderr.decode("utf-8", "replace")[:512]
            raise RuntimeError(
                f"diagnostic worker produced unexpected direct stderr: {detail!r}"
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"diagnostic isolation worker exited with status {completed.returncode}"
            )
        return _decode_response(completed.stdout, limit=limit)


def _catalog(group: str, *, identifiers: bool) -> dict[str, EntryPoint]:
    try:
        entries = entry_points(group=group)
    except Exception as error:
        raise PluginLoadError(
            f"failed to discover diagnostics in entry-point group {group!r}"
        ) from error
    result: dict[str, EntryPoint] = {}
    for item in entries:
        name = item.name
        if identifiers:
            try:
                validate_global_identifier(name, label=f"entry-point name in {group!r}")
            except (TypeError, ValueError) as error:
                raise PluginLoadError(str(error)) from error
        if name in result:
            raise PluginLoadError(f"duplicate entry-point name {name!r} in {group!r}")
        result[name] = item
    return result


def _validate_trigger(trigger: str) -> None:
    if (
        not isinstance(trigger, str)
        or not trigger.startswith("--")
        or trigger == "--"
        or "=" in trigger
        or any(character.isspace() or ord(character) < 33 for character in trigger)
    ):
        raise PluginLoadError(
            f"diagnostic trigger {trigger!r} must be an exact -- option"
        )


def _source_key(entry_point: EntryPoint) -> tuple[str, str, str]:
    distribution = entry_point.dist
    name = "unknown-distribution" if distribution is None else distribution.name
    version = "unknown" if distribution is None else distribution.version
    return name or "unknown-distribution", version or "unknown", entry_point.value


def _isolation_available(
    config: DiagnosticIsolationConfig,
    entry_point: EntryPoint,
) -> tuple[bool, str | None]:
    if sys.platform != "linux":
        return False, "isolated diagnostics require Linux"
    if shutil.which("bwrap") is None:
        return False, "Bubblewrap is not installed"
    if shutil.which("unshare") is None:
        return False, "unshare is not installed"
    probe = json.dumps(
        {"version": 1, "probe": True, "limits": asdict(config)},
        separators=(",", ":"),
    ).encode()
    try:
        result = _run_bounded(
            _bubblewrap_command(entry_point, config),
            probe,
            timeout=min(2.0, config.wall_timeout_seconds),
            limit=config.protocol_limit_bytes,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Bubblewrap probe failed: {error}"
    if result.returncode or result.stderr:
        detail = result.stderr.decode("utf-8", "replace").strip()
        return False, f"Bubblewrap isolation unavailable: {detail or result.returncode}"
    try:
        response = json.loads(result.stdout)
    except UnicodeDecodeError, json.JSONDecodeError:
        return False, "Bubblewrap isolation probe returned malformed output"
    if response != {"version": 1, "probe": "ok"}:
        return False, "Bubblewrap isolation probe returned an invalid response"
    return True, None


def _run_bounded(
    command: list[str],
    payload: bytes,
    *,
    timeout: float,
    limit: int,
) -> _ProcessOutput:
    """Run one worker while bounding both protocol pipes in host memory."""
    prepared_command, mount_fds = _open_readonly_mount_sources(command)
    try:
        process = subprocess.Popen(
            prepared_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={},
            pass_fds=mount_fds,
        )
    finally:
        for descriptor in mount_fds:
            os.close(descriptor)
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise RuntimeError("failed to create diagnostic protocol pipes")
    selector = selectors.DefaultSelector()
    input_fd = process.stdin.fileno()
    output_fd = process.stdout.fileno()
    error_fd = process.stderr.fileno()
    for descriptor in (input_fd, output_fd, error_fd):
        os.set_blocking(descriptor, False)
    selector.register(input_fd, selectors.EVENT_WRITE, "input")
    selector.register(output_fd, selectors.EVENT_READ, "stdout")
    selector.register(error_fd, selectors.EVENT_READ, "stderr")
    sent = 0
    output = bytearray()
    error_output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            events = selector.select(remaining)
            if not events:
                raise subprocess.TimeoutExpired(command, timeout)
            for key, _ in events:
                descriptor = key.fd
                if key.data == "input":
                    try:
                        written = os.write(descriptor, payload[sent : sent + 65536])
                    except BrokenPipeError:
                        written = 0
                        sent = len(payload)
                    sent += written
                    if sent >= len(payload):
                        selector.unregister(descriptor)
                        process.stdin.close()
                    continue
                try:
                    chunk = os.read(descriptor, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(descriptor)
                    if key.data == "stdout":
                        process.stdout.close()
                    else:
                        process.stderr.close()
                    continue
                destination = output if key.data == "stdout" else error_output
                destination.extend(chunk)
                if len(destination) > limit:
                    raise RuntimeError(
                        "diagnostic produced excessive direct or protocol output"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        returncode = process.wait(timeout=remaining)
        return _ProcessOutput(returncode, bytes(output), bytes(error_output))
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def _open_readonly_mount_sources(
    command: list[str],
) -> tuple[list[str], tuple[int, ...]]:
    """Open bind sources before user-namespace mappings restrict traversal."""
    prepared = list(command)
    descriptors: list[int] = []
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC
    for index, argument in enumerate(command[:-2]):
        if argument != "--ro-bind":
            continue
        source_index = index + 1
        descriptor = os.open(command[source_index], flags)
        descriptors.append(descriptor)
        prepared[source_index] = f"/proc/self/fd/{descriptor}"
    return prepared, tuple(descriptors)


def _bubblewrap_command(
    entry_point: EntryPoint,
    config: DiagnosticIsolationConfig,
) -> list[str]:
    executable = shutil.which("bwrap")
    if executable is None:
        raise RuntimeError("Bubblewrap is not installed")
    unshare_executable = shutil.which("unshare")
    if unshare_executable is None:
        raise RuntimeError("unshare is not installed")
    runtime_source = Path(__file__).resolve().parent.parent
    api_source = Path(__file__).resolve().parents[3] / "engulf-api" / "src"
    mounts = [runtime_source]
    if api_source.is_dir():
        mounts.append(api_source)
    distribution = entry_point.dist
    if distribution is not None:
        location = Path(str(distribution.locate_file(""))).resolve()
        if location.is_dir():
            mounts.append(location)
    unique_mounts = tuple(dict.fromkeys(path for path in mounts if path.is_dir()))
    sandbox_mounts = tuple(
        (source, f"/opt/engulf-extension-{index}")
        for index, source in enumerate(unique_mounts)
    )
    python_path = ":".join(destination for _, destination in sandbox_mounts)
    command = [
        unshare_executable,
        "--user",
        "--map-root-user",
        "--net",
        "--",
        executable,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--disable-userns",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
        *_runtime_link_arguments(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--size",
        str(config.scratch_bytes),
        "--tmpfs",
        "/scratch",
        "--symlink",
        "/scratch",
        "/tmp",
        "--dir",
        "/opt",
        "--chdir",
        "/scratch",
        "--setenv",
        "PYTHONPATH",
        python_path,
        "--setenv",
        "PYTHONHASHSEED",
        "0",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "TMPDIR",
        "/scratch",
    ]
    for source, destination in sandbox_mounts:
        command.extend(("--ro-bind", str(source), destination))
    base_python = getattr(sys, "_base_executable", None) or "/usr/bin/python3.14"
    command.extend((base_python, "-s", "-m", "engulf._diagnostic_worker"))
    return command


def _runtime_link_arguments() -> list[str]:
    """Expose ELF loader paths without making host library trees writable."""
    arguments: list[str] = []
    for path in (Path("/lib"), Path("/lib64")):
        if path.is_symlink():
            arguments.extend(("--symlink", os.readlink(path), str(path)))
        elif path.is_dir():
            arguments.extend(("--ro-bind", str(path), str(path)))
    return arguments


def _encode_request(
    diagnostic: _DiscoveredDiagnostic,
    request: DiagnosticRequest,
    active_plugins: tuple[ActivePlugin, ...],
    plugin_executions: tuple[PluginExecutionRecord, ...],
    extensions: tuple[DiagnosticExtension, ...],
    elevated: bool,
    config: DiagnosticIsolationConfig,
) -> bytes:
    def source(plugin: ActivePlugin) -> dict[str, Any]:
        value = asdict(plugin.source)
        value["kind"] = plugin.source.kind.value
        if plugin.source.directory is not None:
            value["directory"] = str(plugin.source.directory)
        return value

    data = {
        "version": 1,
        "target": diagnostic.descriptor.target,
        "request": {
            "arguments": request.arguments,
            "application": asdict(request.application),
            "goal": asdict(request.goal),
        },
        "active_plugins": [
            {"metadata": _metadata_dict(item), "source": source(item)}
            for item in active_plugins
        ],
        "plugin_executions": [
            {
                "plugin_id": item.plugin_id,
                "preprocess_position": item.preprocess_position,
                "postprocess_position": item.postprocess_position,
            }
            for item in plugin_executions
        ],
        "diagnostic_extensions": [asdict(item) for item in extensions],
        "elevated": elevated,
        "limits": asdict(config),
    }
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode()
    if len(encoded) > config.protocol_limit_bytes:
        raise RuntimeError("diagnostic request exceeds the protocol limit")
    return encoded


def _metadata_dict(plugin: ActivePlugin) -> dict[str, Any]:
    metadata = plugin.metadata
    return {
        "plugin_id": metadata.plugin_id,
        "goal_requirement": asdict(metadata.goal_requirement),
        "priority": metadata.priority,
        "elevation_requirement": metadata.elevation_requirement.value,
        "plugin_dependencies": [
            {
                "plugin_id": item.plugin_id,
                "preprocess": None
                if item.preprocess is None
                else item.preprocess.value,
                "postprocess": None
                if item.postprocess is None
                else item.postprocess.value,
            }
            for item in metadata.plugin_dependencies
        ],
        "context_reads": sorted(metadata.context_reads),
        "context_writes": sorted(metadata.context_writes),
    }


def _decode_response(payload: bytes, *, limit: int) -> DiagnosticContribution:
    if not payload or len(payload) > limit:
        raise RuntimeError("diagnostic returned an empty or oversized response")
    try:
        response = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("diagnostic returned malformed JSON") from error
    if not isinstance(response, dict) or set(response) != {
        "version",
        "stdout",
        "stderr",
        "exit_code",
        "direct_stdout",
        "direct_stderr",
    }:
        raise RuntimeError("diagnostic returned an invalid protocol object")
    if response["version"] != 1:
        raise RuntimeError("diagnostic returned an unsupported protocol version")
    if response["direct_stdout"] or response["direct_stderr"]:
        raise RuntimeError("diagnostic wrote unexpected direct output")
    contribution = DiagnosticContribution(
        stdout=response["stdout"],
        stderr=response["stderr"],
        exit_code=response["exit_code"],
    )
    for text in (contribution.stdout, contribution.stderr):
        if any(ord(character) < 32 and character not in "\n\t" for character in text):
            raise RuntimeError("diagnostic output contains control characters")
    if len(contribution.stdout.encode()) + len(contribution.stderr.encode()) > limit:
        raise RuntimeError("diagnostic contribution exceeds the output limit")
    return contribution


__all__ = [
    "BubblewrapDiagnosticRunner",
    "DiagnosticDiscovery",
    "DiagnosticIsolationConfig",
    "DiagnosticRunFailure",
    "diagnostic_entry_point_group",
    "diagnostic_trigger_entry_point_group",
    "discover_diagnostics",
    "matching_diagnostics",
]
