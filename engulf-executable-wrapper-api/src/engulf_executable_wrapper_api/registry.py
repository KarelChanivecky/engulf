from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
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
    binary_words: tuple[str, ...] | None = None
    binary_cursor_index: int | None = None
    cwd: str | None = None
    environment: tuple[tuple[str, str], ...] = ()

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


@dataclass(frozen=True, slots=True)
class CompletionMatch:
    """A serializable, side-effect-free selector for a completion slot.

    Matchers intentionally cover only the token facts that the wrapper already
    exposes. Arbitrary Python predicates remain supported as runtime slots, but
    cannot be compiled into the static layer.
    """

    kind: str
    values: tuple[str, ...] = ()
    index: int | None = None
    children: tuple[CompletionMatch, ...] = ()
    view: str = "wrapper"

    def __post_init__(self) -> None:
        if self.kind not in {
            "always",
            "words-prefix",
            "cursor-at",
            "current-prefix",
            "previous-is",
            "prior-any",
            "all",
            "any",
            "not",
        }:
            raise ValueError(f"unsupported completion matcher kind: {self.kind!r}")
        if self.view not in {"wrapper", "binary"}:
            raise ValueError("completion matcher view must be 'wrapper' or 'binary'")
        if self.kind in {"all", "any"} and not self.children:
            raise ValueError(f"{self.kind} matcher requires children")
        if self.kind == "not" and len(self.children) != 1:
            raise ValueError("not matcher requires exactly one child")
        if self.kind == "cursor-at" and (self.index is None or self.index < 0):
            raise ValueError("cursor-at matcher requires a nonnegative index")
        if self.kind == "current-prefix" and len(self.values) != 1:
            raise ValueError("current-prefix matcher requires exactly one value")
        if any(not isinstance(value, str) or "\0" in value for value in self.values):
            raise ValueError("completion matcher values must be text without NUL")

    def matches(self, context: CompletionContext) -> bool:
        words = context.words
        cursor = context.cursor_index
        if self.view == "binary":
            # The static matcher can only use a binary view when the caller has
            # supplied one explicitly. CompletionContext remains the legacy
            # wrapper view, so this conservative fallback prevents a false hit.
            if context.binary_words is not None:
                words = context.binary_words
            cursor = (
                context.binary_cursor_index
                if context.binary_cursor_index is not None
                else cursor
            )
        current = words[cursor] if 0 <= cursor < len(words) else ""
        previous = words[cursor - 1] if 0 < cursor <= len(words) else None
        if self.kind == "always":
            return True
        if self.kind == "words-prefix":
            return words[: len(self.values)] == self.values
        if self.kind == "cursor-at":
            return cursor == self.index
        if self.kind == "current-prefix":
            return current.startswith(self.values[0])
        if self.kind == "previous-is":
            return previous in self.values
        if self.kind == "prior-any":
            return bool(set(self.values).intersection(words[:cursor]))
        if self.kind == "all":
            return all(child.matches(context) for child in self.children)
        if self.kind == "any":
            return any(child.matches(context) for child in self.children)
        if self.kind == "not":
            return not self.children[0].matches(context)
        raise AssertionError(f"unhandled completion matcher: {self.kind}")

    def __and__(self, other: CompletionMatch) -> CompletionMatch:
        if not isinstance(other, CompletionMatch):
            return NotImplemented
        return CompletionMatch("all", children=(self, other))

    def __or__(self, other: CompletionMatch) -> CompletionMatch:
        if not isinstance(other, CompletionMatch):
            return NotImplemented
        return CompletionMatch("any", children=(self, other))

    def __invert__(self) -> CompletionMatch:
        return CompletionMatch("not", children=(self,))

    def __call__(self, context: CompletionContext) -> bool:
        """Preserve the legacy predicate-call shape for existing consumers."""
        return self.matches(context)


class Match:
    """Factories for the declarative portion of completion selectors."""

    @staticmethod
    def always() -> CompletionMatch:
        return CompletionMatch("always")

    @staticmethod
    def words_prefix(words: Iterable[str], *, view: str = "wrapper") -> CompletionMatch:
        return CompletionMatch("words-prefix", tuple(words), view=view)

    @staticmethod
    def cursor_at(index: int, *, view: str = "wrapper") -> CompletionMatch:
        return CompletionMatch("cursor-at", index=index, view=view)

    @staticmethod
    def current_prefix(prefix: str) -> CompletionMatch:
        return CompletionMatch("current-prefix", (prefix,))

    @staticmethod
    def previous_is(*words: str) -> CompletionMatch:
        return CompletionMatch("previous-is", tuple(words))

    @staticmethod
    def any_prior_word(words: Iterable[str]) -> CompletionMatch:
        return CompletionMatch("prior-any", tuple(words))


@dataclass(frozen=True, slots=True)
class RuntimeCompletion:
    """Bind a provider to a stable slot ID and optional declarative selector."""

    provider_id: str
    provider: CompletionCallable | CompletionProvider
    when: CompletionMatch | None = None

    def __post_init__(self) -> None:
        if not self.provider_id or "\0" in self.provider_id:
            raise ValueError("runtime completion provider_id must be nonempty")
        if not callable(self.provider) and not isinstance(
            self.provider, CompletionProvider
        ):
            raise TypeError(
                "runtime completion provider must be callable or implement complete()"
            )
        if self.when is not None and not isinstance(self.when, CompletionMatch):
            raise TypeError("runtime completion when must be a CompletionMatch or None")


Runtime = RuntimeCompletion


type CandidateLike = str | CompletionCandidate
type CompletionCallable = Callable[[CompletionContext], Iterable[CandidateLike]]
type CompletionPredicate = Callable[[CompletionContext], bool] | CompletionMatch


@runtime_checkable
class CompletionProvider(Protocol):
    def complete(self, context: CompletionContext) -> Iterable[CandidateLike]: ...


@dataclass(frozen=True, slots=True)
class OptionSpec:
    names: tuple[str, ...]
    takes_value: bool
    metavar: str | None
    description: str | None
    value_completer: CompletionCallable | CompletionProvider | RuntimeCompletion | None
    visible_to_binary_completion: bool
    suggest_assignment: bool
    repeatable: bool
    when: CompletionPredicate | None
    environment: str | None
    owner_id: str | None = None


class ArgumentRegistry:
    """Completion and optional environment-binding metadata for plugin options.

    Options without ``environment`` are never validated, consumed, or removed by
    the runtime wrapper.
    """

    def __init__(self) -> None:
        self._options: list[OptionSpec] = []
        self._option_names: dict[str, OptionSpec] = {}
        self._owner_id: str | None = None

    @contextmanager
    def owner(self, owner_id: str) -> Iterator[None]:
        """Attribute subsequent declarations to one setup participant."""
        if not owner_id:
            raise ValueError("completion owner_id must be nonempty")
        previous = self._owner_id
        self._owner_id = owner_id
        try:
            yield
        finally:
            self._owner_id = previous

    @property
    def options(self) -> tuple[OptionSpec, ...]:
        return tuple(self._options)

    def option(
        self,
        *names: str,
        takes_value: bool = False,
        metavar: str | None = None,
        description: str | None = None,
        value_completer: CompletionCallable
        | CompletionProvider
        | RuntimeCompletion
        | None = None,
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
        if (
            when is not None
            and not callable(when)
            and not isinstance(when, CompletionMatch)
        ):
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
            owner_id=self._owner_id,
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
    owner_id: str | None


@dataclass(frozen=True, slots=True)
class RegisteredCompletionProvider:
    provider: CompletionCallable | CompletionProvider
    owner_id: str | None
    provider_id: str
    when: CompletionMatch | None


class CompletionRegistry:
    def __init__(self) -> None:
        self._candidates: list[_RegisteredCandidate] = []
        self._providers: list[RegisteredCompletionProvider] = []
        self._owner_id: str | None = None
        self._next_provider_id: dict[str | None, int] = defaultdict(int)
        self._provider_ids: set[tuple[str | None, str]] = set()

    @contextmanager
    def owner(self, owner_id: str) -> Iterator[None]:
        if not owner_id:
            raise ValueError("completion owner_id must be nonempty")
        previous = self._owner_id
        self._owner_id = owner_id
        try:
            yield
        finally:
            self._owner_id = previous

    def candidate(
        self,
        value: str,
        *,
        description: str | None = None,
        when: CompletionPredicate | None = None,
    ) -> None:
        self._candidates.append(
            _RegisteredCandidate(
                CompletionCandidate(value, description), when, self._owner_id
            )
        )

    def provider(
        self,
        provider: CompletionCallable | CompletionProvider | RuntimeCompletion,
    ) -> None:
        runtime = provider if isinstance(provider, RuntimeCompletion) else None
        actual = runtime.provider if runtime is not None else provider
        if not callable(actual) and not isinstance(actual, CompletionProvider):
            raise TypeError(
                "completion provider must be callable or implement complete()"
            )
        owner_id = self._owner_id
        ordinal = self._next_provider_id[owner_id]
        self._next_provider_id[owner_id] += 1
        provider_id = (
            runtime.provider_id
            if runtime is not None
            else f"{owner_id or 'goal'}:provider:{ordinal}"
        )
        provider_key = (owner_id, provider_id)
        if provider_key in self._provider_ids:
            raise ValueError(f"completion provider already registered: {provider_id}")
        self._provider_ids.add(provider_key)
        self._providers.append(
            RegisteredCompletionProvider(
                actual,
                owner_id,
                provider_id,
                runtime.when if runtime is not None else None,
            )
        )

    @property
    def providers(self) -> tuple[CompletionCallable | CompletionProvider, ...]:
        return tuple(item.provider for item in self._providers)

    @property
    def provider_records(self) -> tuple[RegisteredCompletionProvider, ...]:
        return tuple(self._providers)

    @property
    def candidate_records(self) -> tuple[_RegisteredCandidate, ...]:
        return tuple(self._candidates)

    def static_candidates(
        self, context: CompletionContext
    ) -> list[CompletionCandidate]:
        """Return registered literal candidates matching a completion context."""
        result: list[CompletionCandidate] = []
        for registered in self._candidates:
            if registered.when is not None:
                matches = (
                    registered.when.matches(context)
                    if isinstance(registered.when, CompletionMatch)
                    else registered.when(context)
                )
                if not matches:
                    continue
            if registered.candidate.value.startswith(context.current):
                result.append(registered.candidate)
        return result


def invoke_provider(
    provider: CompletionCallable | CompletionProvider | RuntimeCompletion,
    context: CompletionContext,
) -> Iterable[CandidateLike]:
    if isinstance(provider, RuntimeCompletion):
        provider = provider.provider
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
