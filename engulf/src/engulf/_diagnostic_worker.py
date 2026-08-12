from __future__ import annotations

import contextlib
import ctypes
import importlib
import io
import json
import logging
import resource
import sys
from pathlib import Path
from typing import Any

from engulf_api import (
    ActivePlugin,
    ApplicationMetadata,
    DependencyPosition,
    DiagnosticAPI,
    DiagnosticContribution,
    DiagnosticExtension,
    DiagnosticPlugin,
    DiagnosticRequest,
    ElevationRequirement,
    GoalRequirement,
    PluginDependency,
    PluginExecutionRecord,
    PluginMetadata,
    PluginSource,
    PluginSourceKind,
)


class _WorkerAPI(DiagnosticAPI):
    def __init__(
        self,
        active_plugins: tuple[ActivePlugin, ...],
        extensions: tuple[DiagnosticExtension, ...],
        executions: tuple[PluginExecutionRecord, ...],
        elevated: bool,
        logger: logging.Logger,
    ) -> None:
        self._active_plugins = active_plugins
        self._extensions = extensions
        self._executions = executions
        self._elevated = elevated
        self._logger = logger

    @property
    def active_plugins(self) -> tuple[ActivePlugin, ...]:
        return self._active_plugins

    @property
    def diagnostic_extensions(self) -> tuple[DiagnosticExtension, ...]:
        return self._extensions

    @property
    def plugin_executions(self) -> tuple[PluginExecutionRecord, ...]:
        return self._executions

    @property
    def elevated(self) -> bool:
        return self._elevated

    @property
    def logger(self) -> logging.Logger:
        return self._logger


def main() -> int:
    protocol = sys.stdout.buffer
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("invalid request protocol")
        limits = data["limits"]
        _apply_limits(limits)
        _install_seccomp()
        if data.get("probe") is True:
            protocol.write(b'{"version":1,"probe":"ok"}')
            protocol.flush()
            return 0
        request = _request(data["request"])
        plugins = tuple(_active_plugin(item) for item in data["active_plugins"])
        extensions = tuple(
            _diagnostic_extension(item) for item in data["diagnostic_extensions"]
        )
        plugins_by_id = {item.plugin_id: item for item in plugins}
        executions = tuple(
            PluginExecutionRecord(
                plugin=plugins_by_id[item["plugin_id"]],
                preprocess_position=item["preprocess_position"],
                postprocess_position=item["postprocess_position"],
            )
            for item in data["plugin_executions"]
        )
        log_buffer = io.StringIO()
        logger = logging.getLogger("engulf.diagnostic.worker")
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(log_buffer)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        api = _WorkerAPI(
            plugins, extensions, executions, bool(data["elevated"]), logger
        )
        direct_stdout = io.StringIO()
        direct_stderr = io.StringIO()
        diagnostic = _load_diagnostic(data["target"])
        with (
            contextlib.redirect_stdout(direct_stdout),
            contextlib.redirect_stderr(direct_stderr),
        ):
            contribution = diagnostic.diagnose(request, api)
        if not isinstance(contribution, DiagnosticContribution):
            raise TypeError("diagnose() must return DiagnosticContribution")
        logged = log_buffer.getvalue()
        stderr = contribution.stderr
        if logged:
            stderr += logged
        response = {
            "version": 1,
            "stdout": contribution.stdout,
            "stderr": stderr,
            "exit_code": contribution.exit_code,
            "direct_stdout": direct_stdout.getvalue(),
            "direct_stderr": direct_stderr.getvalue(),
        }
        encoded = json.dumps(
            response, separators=(",", ":"), ensure_ascii=True
        ).encode()
        if len(encoded) > int(limits["protocol_limit_bytes"]):
            raise ValueError("response exceeds protocol limit")
        protocol.write(encoded)
        protocol.flush()
        return 0
    except Exception as error:  # noqa: BLE001 - worker must convert every failure.
        # Failure details use the direct stderr pipe; the host treats the worker as
        # failed and never interprets this as a contribution.
        sys.stderr.write(
            f"diagnostic worker failure: {type(error).__name__}: {error}\n"
        )
        return 70


def _apply_limits(limits: dict[str, Any]) -> None:
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (int(limits["cpu_seconds"]), int(limits["cpu_seconds"])),
    )
    resource.setrlimit(
        resource.RLIMIT_AS,
        (int(limits["address_space_bytes"]), int(limits["address_space_bytes"])),
    )
    resource.setrlimit(
        resource.RLIMIT_NOFILE,
        (int(limits["file_descriptors"]), int(limits["file_descriptors"])),
    )
    resource.setrlimit(
        resource.RLIMIT_NPROC,
        (int(limits["child_processes"]), int(limits["child_processes"])),
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (int(limits["scratch_bytes"]), int(limits["scratch_bytes"])),
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _install_seccomp() -> None:
    """Install a deny-by-name second-stage filter before extension import."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    try:
        lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    except OSError as error:
        raise RuntimeError("libseccomp is unavailable") from error
    lib.seccomp_init.argtypes = (ctypes.c_uint32,)
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    )
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = (ctypes.c_void_p,)
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = (ctypes.c_void_p,)
    lib.seccomp_release.restype = None
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp_init failed")
    errno_action = 0x00050000 | 1  # SCMP_ACT_ERRNO(EPERM)
    try:
        for name in (
            b"clone",
            b"clone3",
            b"fork",
            b"vfork",
            b"socket",
            b"socketpair",
            b"connect",
            b"bind",
            b"listen",
            b"accept",
            b"accept4",
            b"kill",
            b"tkill",
            b"tgkill",
            b"pidfd_open",
            b"pidfd_send_signal",
            b"ptrace",
            b"mount",
            b"umount2",
            b"pivot_root",
            b"setns",
            b"unshare",
            b"bpf",
            b"keyctl",
            b"add_key",
            b"request_key",
            b"perf_event_open",
        ):
            number = lib.seccomp_syscall_resolve_name(name)
            if number >= 0 and lib.seccomp_rule_add(context, errno_action, number, 0):
                raise RuntimeError(f"failed to add seccomp rule for {name.decode()}")
        if lib.seccomp_load(context):
            raise RuntimeError("seccomp_load failed")
    finally:
        lib.seccomp_release(context)


def _load_diagnostic(target: str) -> DiagnosticPlugin:
    module_name, separator, attribute_path = target.partition(":")
    if not separator or not module_name or not attribute_path:
        raise ValueError("diagnostic target must use module:attribute syntax")
    exported: object = importlib.import_module(module_name)
    for component in attribute_path.split("."):
        exported = getattr(exported, component)
    if isinstance(exported, DiagnosticPlugin):
        return exported
    if callable(exported):
        exported = exported()
    if not isinstance(exported, DiagnosticPlugin):
        raise TypeError("diagnostic target must export DiagnosticPlugin or a factory")
    return exported


def _request(data: dict[str, Any]) -> DiagnosticRequest:
    return DiagnosticRequest(
        arguments=tuple(data["arguments"]),
        application=ApplicationMetadata(**data["application"]),
        goal=GoalRequirement(**data["goal"]),
    )


def _diagnostic_extension(data: dict[str, Any]) -> DiagnosticExtension:
    return DiagnosticExtension(
        diagnostic_id=data["diagnostic_id"],
        triggers=tuple(data["triggers"]),
        distribution=data["distribution"],
        version=data["version"],
        target=data["target"],
        available=data["available"],
        unavailable_reason=data["unavailable_reason"],
    )


def _active_plugin(data: dict[str, Any]) -> ActivePlugin:
    metadata_data = data["metadata"]
    dependencies = tuple(
        PluginDependency(
            item["plugin_id"],
            preprocess=(
                None
                if item["preprocess"] is None
                else DependencyPosition(item["preprocess"])
            ),
            postprocess=(
                None
                if item["postprocess"] is None
                else DependencyPosition(item["postprocess"])
            ),
        )
        for item in metadata_data["plugin_dependencies"]
    )
    metadata = PluginMetadata(
        plugin_id=metadata_data["plugin_id"],
        goal_requirement=GoalRequirement(**metadata_data["goal_requirement"]),
        priority=metadata_data["priority"],
        elevation_requirement=ElevationRequirement(
            metadata_data["elevation_requirement"]
        ),
        plugin_dependencies=dependencies,
        context_reads=frozenset(metadata_data["context_reads"]),
        context_writes=frozenset(metadata_data["context_writes"]),
    )
    source_data = data["source"]
    directory = source_data.get("directory")
    source = PluginSource(
        kind=PluginSourceKind(source_data["kind"]),
        target=source_data["target"],
        distribution_name=source_data.get("distribution_name"),
        distribution_version=source_data.get("distribution_version"),
        entry_point_group=source_data.get("entry_point_group"),
        entry_point_value=source_data.get("entry_point_value"),
        directory=None if directory is None else Path(directory),
    )
    return ActivePlugin(metadata=metadata, source=source)


if __name__ == "__main__":
    raise SystemExit(main())
