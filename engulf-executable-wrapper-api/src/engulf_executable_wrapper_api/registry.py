from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Shell(StrEnum):
    BASH = "bash"
    ZSH = "zsh"
    FISH = "fish"


@dataclass(frozen=True, slots=True)
class CompletionCandidate:
    value: str
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("completion candidate value cannot be empty")
        if "\0" in self.value:
            raise ValueError("completion candidate cannot contain NUL characters")


@dataclass(frozen=True, slots=True)
class CompletionContext:
    shell: Shell
    wrapper_command: str
    binary: str
    words: tuple[str, ...]
    cursor_index: int

    @property
    def current(self) -> str:
        if 0 <= self.cursor_index < len(self.words):
            return self.words[self.cursor_index]
        return ""

    @property
    def previous(self) -> str | None:
        if self.cursor_index > 0 and self.cursor_index <= len(self.words):
            return self.words[self.cursor_index - 1]
        return None


type CandidateLike = str | CompletionCandidate
type CompletionCallable = Callable[[CompletionContext], Iterable[CandidateLike]]
type CompletionPredicate = Callable[[CompletionContext], bool]


@runtime_checkable
class CompletionProvider(Protocol):
    def complete(self, context: CompletionContext) -> Iterable[CandidateLike]: ...


@dataclass(frozen=True, slots=True)
class OptionSpec:
    names: tuple[str, ...]
    takes_value: bool
    metavar: str | None
    description: str | None
    value_completer: CompletionCallable | CompletionProvider | None
    visible_to_binary_completion: bool
    suggest_assignment: bool
    repeatable: bool
    when: CompletionPredicate | None
    environment: str | None


class ArgumentRegistry:
    """Completion and optional environment-binding metadata for plugin options.

    Options without ``environment`` are never validated, consumed, or removed by
    the runtime wrapper.
    """

    def __init__(self) -> None:
        self._options: list[OptionSpec] = []
        self._option_names: dict[str, OptionSpec] = {}

    @property
    def options(self) -> tuple[OptionSpec, ...]:
        return tuple(self._options)

    def option(
        self,
        *names: str,
        takes_value: bool = False,
        metavar: str | None = None,
        description: str | None = None,
        value_completer: CompletionCallable | CompletionProvider | None = None,
        visible_to_binary_completion: bool = False,
        suggest_assignment: bool = True,
        repeatable: bool = False,
        when: CompletionPredicate | None = None,
        environment: str | None = None,
    ) -> OptionSpec:
        if not names:
            raise ValueError("an option requires at least one name")
        if any(not isinstance(name, str) or not name.startswith("-") for name in names):
            raise ValueError("option names must be strings beginning with '-'")
        if len(set(names)) != len(names):
            raise ValueError("option names must be unique")
        collisions = [name for name in names if name in self._option_names]
        if collisions:
            raise ValueError(f"option already registered: {collisions[0]}")
        if value_completer is not None and not takes_value:
            raise ValueError("value_completer requires takes_value=True")
        if when is not None and not callable(when):
            raise TypeError("when must be callable or None")
        if environment is not None and _ENVIRONMENT_NAME.fullmatch(environment) is None:
            raise ValueError("environment must be a shell-style variable name or None")

        spec = OptionSpec(
            names=tuple(names),
            takes_value=takes_value,
            metavar=metavar,
            description=description,
            value_completer=value_completer,
            visible_to_binary_completion=visible_to_binary_completion,
            suggest_assignment=suggest_assignment,
            repeatable=repeatable,
            when=when,
            environment=environment,
        )
        self._options.append(spec)
        for name in names:
            self._option_names[name] = spec
        return spec

    def find_exact(self, word: str) -> OptionSpec | None:
        """Return the option registered for an exact argument, if any."""
        return self._option_names.get(word)

    def find_assignment(self, word: str) -> tuple[OptionSpec, str, str] | None:
        """Resolve a registered ``--option=value`` argument."""
        if "=" not in word:
            return None
        name, value = word.split("=", 1)
        spec = self._option_names.get(name)
        if spec is None or not spec.takes_value:
            return None
        return spec, name, value


@dataclass(frozen=True, slots=True)
class _RegisteredCandidate:
    candidate: CompletionCandidate
    when: CompletionPredicate | None


class CompletionRegistry:
    def __init__(self) -> None:
        self._candidates: list[_RegisteredCandidate] = []
        self._providers: list[CompletionCallable | CompletionProvider] = []

    def candidate(
        self,
        value: str,
        *,
        description: str | None = None,
        when: CompletionPredicate | None = None,
    ) -> None:
        self._candidates.append(
            _RegisteredCandidate(CompletionCandidate(value, description), when)
        )

    def provider(self, provider: CompletionCallable | CompletionProvider) -> None:
        if not callable(provider) and not isinstance(provider, CompletionProvider):
            raise TypeError(
                "completion provider must be callable or implement complete()"
            )
        self._providers.append(provider)

    @property
    def providers(self) -> tuple[CompletionCallable | CompletionProvider, ...]:
        return tuple(self._providers)

    def static_candidates(
        self, context: CompletionContext
    ) -> list[CompletionCandidate]:
        """Return registered literal candidates matching a completion context."""
        result: list[CompletionCandidate] = []
        for registered in self._candidates:
            if registered.when is not None and not registered.when(context):
                continue
            if registered.candidate.value.startswith(context.current):
                result.append(registered.candidate)
        return result


def invoke_provider(
    provider: CompletionCallable | CompletionProvider,
    context: CompletionContext,
) -> Iterable[CandidateLike]:
    if isinstance(provider, CompletionProvider):
        return provider.complete(context)
    return provider(context)


def normalize_candidate(candidate: CandidateLike) -> CompletionCandidate:
    if isinstance(candidate, CompletionCandidate):
        return candidate
    if not isinstance(candidate, str):
        raise TypeError(
            "completion providers must return strings or CompletionCandidate objects"
        )
    return CompletionCandidate(candidate)
