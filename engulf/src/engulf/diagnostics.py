from __future__ import annotations

import itertools
import logging
import re
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from types import MappingProxyType, TracebackType
from typing import Self, cast

from engulf_api import (
    ApplicationMetadata,
    PluginLogger,
    PluginPhaseError,
    RegistrationAPI,
    validate_global_identifier,
)

type LogLevel = int | str
type _ExcInfo = (
    bool
    | BaseException
    | tuple[type[BaseException], BaseException, TracebackType | None]
    | None
)
type _Guard = Callable[[], None]

_DISPLAY_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_OFF_LEVEL = 2**31 - 1
_LEVELS = MappingProxyType(
    {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "OFF": _OFF_LEVEL,
    }
)
LOG_LEVEL_NAMES = tuple(_LEVELS)


class LoggingArgumentError(ValueError):
    """A reserved logging control argument is malformed."""


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Application logging defaults and output handlers."""

    default_level: LogLevel = "WARNING"
    plugin_levels: Mapping[str, LogLevel] = field(default_factory=dict)
    handlers: tuple[logging.Handler, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "default_level",
            _normalize_level(self.default_level, label="default log level"),
        )
        object.__setattr__(
            self,
            "plugin_levels",
            _normalize_plugin_levels(self.plugin_levels, label="plugin log levels"),
        )
        if self.handlers is None:
            return
        try:
            handlers = tuple(self.handlers)
        except TypeError as error:
            raise TypeError(
                "logging handlers must be an iterable of Handler values"
            ) from error
        if not handlers:
            raise ValueError("logging handlers cannot be empty")
        if any(not isinstance(handler, logging.Handler) for handler in handlers):
            raise TypeError("logging handlers must contain only Handler values")
        object.__setattr__(self, "handlers", handlers)


@dataclass(frozen=True, slots=True)
class LogLevelOverrides:
    """Optional default and per-plugin levels for one invocation."""

    default_level: LogLevel | None = None
    plugin_levels: Mapping[str, LogLevel] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_level is not None:
            object.__setattr__(
                self,
                "default_level",
                _normalize_level(
                    self.default_level, label="default log level override"
                ),
            )
        object.__setattr__(
            self,
            "plugin_levels",
            _normalize_plugin_levels(
                self.plugin_levels,
                label="plugin log level overrides",
            ),
        )


@dataclass(frozen=True, slots=True)
class ParsedLoggingArguments:
    arguments: tuple[str, ...]
    overrides: LogLevelOverrides


def validate_display_name(display_name: str) -> str:
    if not isinstance(display_name, str):
        raise TypeError("display_name must be a string")
    if not _DISPLAY_NAME_PATTERN.fullmatch(display_name):
        raise ValueError(
            "display_name must contain lowercase ASCII letters, digits, or internal "
            "hyphens, and must begin and end with a letter or digit"
        )
    return display_name


def logging_option_names(display_name: str) -> tuple[str, str]:
    return (
        f"--{display_name}-log-level",
        f"--{display_name}-plugin-log-level",
    )


def parse_logging_arguments(
    args: tuple[str, ...],
    *,
    display_name: str,
    plugin_ids: frozenset[str],
) -> ParsedLoggingArguments:
    global_option, plugin_option = logging_option_names(display_name)
    application_args: list[str] = []
    global_level: int | None = None
    plugin_levels: dict[str, int] = {}
    index = 0

    while index < len(args):
        argument = args[index]
        if argument == "--":
            application_args.extend(args[index:])
            break

        option: str | None = None
        value: str | None = None
        if argument in {global_option, plugin_option}:
            option = argument
            if index + 1 >= len(args) or args[index + 1] == "--":
                raise LoggingArgumentError(f"missing value for {option}")
            value = args[index + 1]
            index += 2
        elif argument.startswith(global_option + "="):
            option = global_option
            value = argument.removeprefix(global_option + "=")
            index += 1
        elif argument.startswith(plugin_option + "="):
            option = plugin_option
            value = argument.removeprefix(plugin_option + "=")
            index += 1
        else:
            application_args.append(argument)
            index += 1
            continue

        if not value:
            raise LoggingArgumentError(f"missing value for {option}")
        if option == global_option:
            global_level = _normalize_cli_level(value, option=option)
            continue

        plugin_id, separator, level_name = value.partition("=")
        if not separator or not plugin_id or not level_name:
            raise LoggingArgumentError(f"{plugin_option} requires PLUGIN_ID=LEVEL")
        if plugin_id not in plugin_ids:
            raise LoggingArgumentError(f"unknown plugin ID for logging: {plugin_id}")
        plugin_levels[plugin_id] = _normalize_cli_level(
            level_name,
            option=plugin_option,
        )

    return ParsedLoggingArguments(
        tuple(application_args),
        LogLevelOverrides(global_level, plugin_levels),
    )


class DiagnosticsManager:
    """Creates isolated setup and invocation logging sessions for one application."""

    def __init__(
        self,
        *,
        application_id: str,
        display_name: str,
        plugin_ids: tuple[str, ...],
        config: LoggingConfig,
    ) -> None:
        self.application_id = application_id
        self.display_name = display_name
        self.plugin_ids = plugin_ids
        self._plugin_id_set = frozenset(plugin_ids)
        self._config = config
        _validate_known_plugins(
            config.plugin_levels,
            self._plugin_id_set,
            label="logging configuration",
        )
        self._call_ids = itertools.count(1)

    def session(
        self,
        *overrides: LogLevelOverrides,
    ) -> DiagnosticsSession:
        self.validate_overrides(*overrides)
        core_level = cast(int, self._config.default_level)
        plugin_levels = {plugin_id: core_level for plugin_id in self.plugin_ids}
        plugin_levels.update(
            {key: cast(int, value) for key, value in self._config.plugin_levels.items()}
        )

        for layer in overrides:
            if layer.default_level is not None:
                core_level = cast(int, layer.default_level)
                plugin_levels = {plugin_id: core_level for plugin_id in self.plugin_ids}
            plugin_levels.update(
                {key: cast(int, value) for key, value in layer.plugin_levels.items()}
            )

        return DiagnosticsSession(
            application_id=self.application_id,
            display_name=self.display_name,
            call_id=next(self._call_ids),
            core_level=core_level,
            plugin_levels=plugin_levels,
            configured_handlers=self._config.handlers,
        )

    def validate_overrides(self, *overrides: LogLevelOverrides) -> None:
        for layer in overrides:
            _validate_known_plugins(
                layer.plugin_levels,
                self._plugin_id_set,
                label="log level overrides",
            )


class DiagnosticsSession(AbstractContextManager["DiagnosticsSession"]):
    def __init__(
        self,
        *,
        application_id: str,
        display_name: str,
        call_id: int,
        core_level: int,
        plugin_levels: Mapping[str, int],
        configured_handlers: tuple[logging.Handler, ...] | None,
    ) -> None:
        self._application_id = application_id
        self._display_name = display_name
        self._call_id = call_id
        self._core_level = core_level
        self._plugin_levels = plugin_levels
        self._configured_handlers = configured_handlers
        self._owned_handler: logging.Handler | None = None
        self._dispatcher: _DispatchHandler | None = None
        self._core: logging.Logger | None = None
        self._plugins: dict[str, logging.Logger] = {}
        self._entered = False

    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError("a diagnostics session can be entered only once")
        self._entered = True
        targets = self._configured_handlers
        if targets is None:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(_default_formatter())
            self._owned_handler = handler
            targets = (handler,)
        self._dispatcher = _DispatchHandler(targets, self._display_name)
        self._core = self._create_logger("core", None, self._core_level)
        self._plugins = {
            plugin_id: self._create_logger(plugin_id, plugin_id, level)
            for plugin_id, level in self._plugin_levels.items()
        }
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        loggers = [logger for logger in (self._core, *self._plugins.values()) if logger]
        dispatcher = self._dispatcher
        if dispatcher is not None:
            for logger in loggers:
                logger.removeHandler(dispatcher)
        for handler in self._configured_handlers or ():
            try:
                handler.flush()
            except Exception as error:  # noqa: BLE001 - logging cannot fail a call.
                _write_handler_fallback(self._display_name, error)
        if self._owned_handler is not None:
            try:
                self._owned_handler.flush()
            finally:
                self._owned_handler.close()
        self._dispatcher = None
        self._core = None
        self._plugins.clear()

    @property
    def core(self) -> logging.Logger:
        if self._core is None:
            raise RuntimeError("diagnostics session is not active")
        return self._core

    def plugin_logger(self, plugin_id: str) -> logging.Logger:
        try:
            return self._plugins[plugin_id]
        except KeyError as error:
            raise RuntimeError(
                f"no diagnostics channel for plugin {plugin_id}"
            ) from error

    def failure(
        self,
        message: str,
        *,
        plugin_id: str | None = None,
        phase: str = "runtime",
        error: BaseException | None = None,
    ) -> None:
        logger = self.core if plugin_id is None else self.plugin_logger(plugin_id)
        extra = {"engulf_mandatory": True, "engulf_phase": phase}
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            "",
            0,
            message,
            (),
            None,
            extra=extra,
        )
        logger.handle(record)
        if error is not None:
            logger.debug(
                "exception details for %s",
                message,
                exc_info=(type(error), error, error.__traceback__),
                extra={"engulf_phase": phase},
            )

    def _create_logger(
        self,
        component: str,
        plugin_id: str | None,
        level: int,
    ) -> logging.Logger:
        dispatcher = self._dispatcher
        if dispatcher is None:
            raise RuntimeError("diagnostics session is not active")
        suffix = "core" if plugin_id is None else f"plugin.{plugin_id}"
        # Direct instances keep handlers and levels isolated from the process-global
        # logger registry used by unrelated applications.
        logger = _SessionLogger(
            f"engulf.{self._display_name}.{suffix}",
            level,
            off=level == _OFF_LEVEL,
        )
        logger.propagate = False
        logger.addHandler(dispatcher)
        logger.addFilter(
            _MetadataFilter(
                application_id=self._application_id,
                display_name=self._display_name,
                plugin_id=plugin_id,
                component=component,
                call_id=self._call_id,
            )
        )
        return logger


class RuntimeDiagnosticsAPI(RegistrationAPI):
    """Logging and elevation capabilities for registration callbacks."""

    def __init__(
        self,
        plugin_id: str,
        logger: logging.Logger,
        *,
        application: ApplicationMetadata,
        elevated: bool,
    ) -> None:
        if not isinstance(application, ApplicationMetadata):
            raise TypeError("application must be ApplicationMetadata")
        if type(elevated) is not bool:
            raise TypeError("elevated must be a boolean")
        self._plugin_id = plugin_id
        self._logger = logger
        self._application = application
        self._elevated = elevated
        self._phase: str | None = None
        self._activation_id = 0
        self._closed = False

    def activate(self, phase: str) -> None:
        if self._closed:
            raise PluginPhaseError(f"diagnostics API for {self._plugin_id} is closed")
        if self._phase is not None:
            raise PluginPhaseError(
                f"diagnostics API for {self._plugin_id} is already active"
            )
        self._activation_id += 1
        self._phase = phase

    def deactivate(self) -> None:
        if not self._closed:
            self._phase = None

    def close(self) -> None:
        self._phase = None
        self._closed = True

    @property
    def logger(self) -> PluginLogger:
        if self._phase is None or self._closed:
            raise PluginPhaseError("logger is unavailable outside an active callback")
        activation_id = self._activation_id
        phase = self._phase
        return guarded_plugin_logger(
            self._logger,
            lambda: self._require_activation(activation_id),
            phase,
        )

    @property
    def application(self) -> ApplicationMetadata:
        self._require_activation(self._activation_id)
        return self._application

    @property
    def elevated(self) -> bool:
        self._require_activation(self._activation_id)
        return self._elevated

    def _require_activation(self, activation_id: int) -> None:
        if self._closed or self._phase is None or activation_id != self._activation_id:
            raise PluginPhaseError("plugin logger belongs to an inactive callback")


def guarded_plugin_logger(
    logger: logging.Logger,
    guard: _Guard,
    phase: str,
) -> PluginLogger:
    return cast(PluginLogger, _GuardedPluginLogger(logger, guard, phase))


class _GuardedPluginLogger:
    def __init__(self, logger: logging.Logger, guard: _Guard, phase: str) -> None:
        self._logger = logger
        self._guard = guard
        self._phase = phase

    @property
    def name(self) -> str:
        self._guard()
        return self._logger.name

    def isEnabledFor(self, level: int) -> bool:
        self._guard()
        return self._logger.isEnabledFor(level)

    def debug(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.debug(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def info(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.info(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def warning(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.warning(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def error(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.error(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def exception(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = True,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.exception(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def critical(
        self,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.critical(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def log(
        self,
        level: int,
        msg: object,
        *args: object,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        self._guard()
        self._logger.log(
            level,
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
            extra=self._extra(extra),
        )

    def _extra(self, extra: Mapping[str, object] | None) -> dict[str, object]:
        values = (
            {}
            if extra is None
            else {
                key: value
                for key, value in extra.items()
                if not key.startswith("engulf_")
            }
        )
        values["engulf_phase"] = self._phase
        return values


class _SessionLogger(logging.Logger):
    """A session-local logger unaffected by process-global logging.disable()."""

    def __init__(self, name: str, level: int, *, off: bool) -> None:
        super().__init__(name, level)
        self._off = off

    def isEnabledFor(self, level: int) -> bool:
        if self.disabled or self._off:
            return False
        return level >= self.getEffectiveLevel()


@dataclass(frozen=True, slots=True)
class _MetadataFilter(logging.Filter):
    application_id: str
    display_name: str
    plugin_id: str | None
    component: str
    call_id: int

    def filter(self, record: logging.LogRecord) -> bool:
        record.engulf_application_id = self.application_id
        record.engulf_display_name = self.display_name
        record.engulf_plugin_id = self.plugin_id
        record.engulf_component = self.component
        record.engulf_call_id = self.call_id
        if not hasattr(record, "engulf_phase"):
            record.engulf_phase = "runtime"
        return True


class _DispatchHandler(logging.Handler):
    def __init__(
        self,
        targets: tuple[logging.Handler, ...],
        display_name: str,
    ) -> None:
        super().__init__(logging.NOTSET)
        self._targets = targets
        self._display_name = display_name
        self._reported_failure = False

    def emit(self, record: logging.LogRecord) -> None:
        mandatory = bool(getattr(record, "engulf_mandatory", False))
        delivered = False
        for target in self._targets:
            if not mandatory and record.levelno < target.level:
                continue
            try:
                delivered = bool(target.handle(record)) or delivered
            except Exception as error:  # noqa: BLE001 - logging cannot fail a call.
                if not self._reported_failure:
                    self._reported_failure = True
                    _write_handler_fallback(self._display_name, error)
        if mandatory and not delivered:
            _write_mandatory_fallback(self._display_name, record)


def _to_utc(timestamp: float | None) -> time.struct_time:
    return time.gmtime() if timestamp is None else time.gmtime(timestamp)


class _UTCFormatter(logging.Formatter):
    converter = staticmethod(_to_utc)


def _default_formatter() -> logging.Formatter:
    return _UTCFormatter(
        "%(asctime)s.%(msecs)03dZ %(engulf_display_name)s[%(engulf_component)s] "
        "%(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _normalize_level(level: LogLevel, *, label: str) -> int:
    if isinstance(level, bool):
        raise TypeError(f"{label} must be a level name or nonnegative integer")
    if isinstance(level, int):
        if level < 0:
            raise ValueError(f"{label} cannot be negative")
        return level
    if not isinstance(level, str):
        raise TypeError(f"{label} must be a level name or nonnegative integer")
    normalized = _LEVELS.get(level.upper())
    if normalized is None:
        raise ValueError(f"{label} must be one of {', '.join(LOG_LEVEL_NAMES)}")
    return normalized


def _normalize_cli_level(value: str, *, option: str) -> int:
    try:
        return _normalize_level(value, label=f"value for {option}")
    except (TypeError, ValueError) as error:
        raise LoggingArgumentError(str(error)) from error


def _normalize_plugin_levels(
    levels: Mapping[str, LogLevel],
    *,
    label: str,
) -> Mapping[str, int]:
    if not isinstance(levels, Mapping):
        raise TypeError(f"{label} must be a mapping")
    normalized: dict[str, int] = {}
    for plugin_id, level in levels.items():
        validate_global_identifier(plugin_id, label=f"plugin ID in {label}")
        normalized[plugin_id] = _normalize_level(
            level,
            label=f"level for plugin {plugin_id}",
        )
    return MappingProxyType(normalized)


def _validate_known_plugins(
    levels: Mapping[str, LogLevel],
    plugin_ids: frozenset[str],
    *,
    label: str,
) -> None:
    unknown = sorted(set(levels) - plugin_ids)
    if unknown:
        raise ValueError(f"{label} references unknown plugin ID: {unknown[0]}")


def _write_handler_fallback(display_name: str, error: Exception) -> None:
    stream = sys.__stderr__
    if stream is None:
        return
    try:
        stream.write(f"{display_name}[core] ERROR: logging handler failed: {error}\n")
        stream.flush()
    except Exception:  # noqa: BLE001 - no safe diagnostics path remains.
        return


def _write_mandatory_fallback(
    display_name: str,
    record: logging.LogRecord,
) -> None:
    stream = sys.__stderr__
    if stream is None:
        return
    component = getattr(record, "engulf_component", "core")
    try:
        stream.write(
            f"{display_name}[{component}] {record.levelname}: {record.getMessage()}\n"
        )
        stream.flush()
    except Exception:  # noqa: BLE001 - no safe diagnostics path remains.
        return
