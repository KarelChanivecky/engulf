"""Portable completion schema and runtime-slot descriptors.

The module deliberately contains no plugin loading or filesystem behavior. It
turns the existing wrapper registries into immutable data that a runtime engine
can evaluate, persist, or lower to generated Python. Arbitrary callbacks are
represented by stable slots and are never pickled into the schema.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .registry import (
    ArgumentRegistry,
    CompletionMatch,
    CompletionRegistry,
    RuntimeCompletion,
)

AUTOCOMPLETION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CompletionSlot:
    slot_id: str
    owner_id: str | None
    kind: str
    provider_id: str
    matcher: CompletionMatch | None = None

    def __post_init__(self) -> None:
        if not self.slot_id or "\0" in self.slot_id:
            raise ValueError("completion slot_id must be nonempty")
        if self.kind not in {"provider", "predicate"}:
            raise ValueError("completion slot kind must be provider or predicate")
        if not self.provider_id or "\0" in self.provider_id:
            raise ValueError("completion slot provider_id must be nonempty")


@dataclass(frozen=True, slots=True)
class CompiledOption:
    names: tuple[str, ...]
    takes_value: bool
    description: str | None
    visible_to_binary_completion: bool
    suggest_assignment: bool
    repeatable: bool
    environment: str | None
    owner_id: str | None
    value_slot: str | None
    when_matcher: CompletionMatch | None
    when_slot: str | None


@dataclass(frozen=True, slots=True)
class CompiledCandidate:
    value: str
    description: str | None
    owner_id: str | None
    when_matcher: CompletionMatch | None
    when_slot: str | None


@dataclass(frozen=True, slots=True)
class CompiledProvider:
    slot_id: str
    owner_id: str | None
    provider_id: str
    matcher: CompletionMatch | None


@dataclass(frozen=True, slots=True)
class CompletionManifest:
    """Immutable generated completion schema.

    ``dependencies`` is a presence graph, while the two order tuples are the
    already-resolved Engulf phase orders. The distinction matters for dependencies
    whose edge is ``after`` or ``none`` in preprocessing.
    """

    generation: str
    options: tuple[CompiledOption, ...]
    candidates: tuple[CompiledCandidate, ...]
    providers: tuple[CompiledProvider, ...]
    slots: tuple[CompletionSlot, ...]
    dependencies: tuple[tuple[str, tuple[str, ...]], ...] = ()
    preprocess_order: tuple[str, ...] = ()
    postprocess_order: tuple[str, ...] = ()
    schema_version: int = AUTOCOMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTOCOMPLETION_SCHEMA_VERSION:
            raise ValueError("unsupported completion schema version")
        if not self.generation or "\0" in self.generation:
            raise ValueError("completion generation must be nonempty")
        slot_ids = [slot.slot_id for slot in self.slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("completion slot IDs must be unique")

    @property
    def dependency_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.dependencies)

    def runtime_closure(self, owners: Iterable[str]) -> tuple[str, ...]:
        """Return the mandatory dependency closure in preprocessing order."""
        dependencies = self.dependency_map
        active = set(owners)
        pending = list(active)
        while pending:
            owner = pending.pop()
            for dependency in dependencies.get(owner, ()):
                if dependency not in active:
                    active.add(dependency)
                    pending.append(dependency)
        order = self.preprocess_order or tuple(sorted(active))
        if self.preprocess_order and not active.issubset(order):
            missing = ", ".join(sorted(active.difference(order)))
            raise ValueError(f"preprocess order omits runtime owners: {missing}")
        return tuple(plugin_id for plugin_id in order if plugin_id in active)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "options": [_option_to_dict(option) for option in self.options],
            "candidates": [
                _candidate_to_dict(candidate) for candidate in self.candidates
            ],
            "providers": [_provider_to_dict(provider) for provider in self.providers],
            "slots": [_slot_to_dict(slot) for slot in self.slots],
            "dependencies": [
                [owner, *dependencies] for owner, dependencies in self.dependencies
            ],
            "preprocess_order": list(self.preprocess_order),
            "postprocess_order": list(self.postprocess_order),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def generated_python(self) -> str:
        """Return deterministic source that embeds only validated data."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return (
            "# Generated by engulf autocompletion; do not edit.\n"
            "from engulf_executable_wrapper_api.autocompletion import "
            "manifest_from_json\n"
            f"MANIFEST = manifest_from_json({payload!r})\n"
        )


def manifest_from_json(value: str | Mapping[str, Any]) -> CompletionManifest:
    data: Mapping[str, Any] = json.loads(value) if isinstance(value, str) else value
    return CompletionManifest(
        generation=_string(data, "generation"),
        options=tuple(_option_from_dict(item) for item in _sequence(data, "options")),
        candidates=tuple(
            _candidate_from_dict(item) for item in _sequence(data, "candidates")
        ),
        providers=tuple(
            _provider_from_dict(item) for item in _sequence(data, "providers")
        ),
        slots=tuple(_slot_from_dict(item) for item in _sequence(data, "slots")),
        dependencies=_dependency_pairs(data),
        preprocess_order=tuple(_strings(data, "preprocess_order")),
        postprocess_order=tuple(_strings(data, "postprocess_order")),
        schema_version=int(data.get("schema_version", AUTOCOMPLETION_SCHEMA_VERSION)),
    )


def build_manifest(
    arguments: ArgumentRegistry,
    completions: CompletionRegistry,
    *,
    generation: str,
    dependencies: Mapping[str, Iterable[str]] | None = None,
    preprocess_order: Iterable[str] = (),
    postprocess_order: Iterable[str] = (),
) -> CompletionManifest:
    """Lower existing registries into a stable schema and runtime slots."""
    slots: list[CompletionSlot] = []
    options: list[CompiledOption] = []
    candidates: list[CompiledCandidate] = []
    providers: list[CompiledProvider] = []
    predicate_counter: dict[str | None, int] = {}
    provider_keys: set[tuple[str | None, str]] = set()

    def slot_for(
        owner_id: str | None,
        kind: str,
        provider_id: str,
        matcher: CompletionMatch | None,
    ) -> str:
        if kind == "predicate":
            ordinal = predicate_counter.get(owner_id, 0)
            predicate_counter[owner_id] = ordinal + 1
            slot_id = f"{owner_id or 'goal'}:predicate:{ordinal}"
        else:
            provider_key = (owner_id, provider_id)
            if provider_key in provider_keys:
                raise ValueError(
                    "completion provider ID already registered for owner: "
                    f"{provider_id}"
                )
            provider_keys.add(provider_key)
            slot_id = f"{owner_id or 'goal'}:{provider_id}"
        if any(existing.slot_id == slot_id for existing in slots):
            suffix = 1
            base = slot_id
            while any(existing.slot_id == f"{base}:{suffix}" for existing in slots):
                suffix += 1
            slot_id = f"{base}:{suffix}"
        slots.append(CompletionSlot(slot_id, owner_id, kind, provider_id, matcher))
        return slot_id

    for option_index, option in enumerate(arguments.options):
        value_slot: str | None = None
        if option.value_completer is not None:
            if isinstance(option.value_completer, RuntimeCompletion):
                provider_id = option.value_completer.provider_id
                matcher = option.value_completer.when
            else:
                provider_id = f"option:{option_index}:value"
                matcher = None
            value_slot = slot_for(option.owner_id, "provider", provider_id, matcher)
        when_matcher: CompletionMatch | None = (
            option.when if isinstance(option.when, CompletionMatch) else None
        )
        when_slot = None
        if option.when is not None and when_matcher is None:
            when_slot = slot_for(
                option.owner_id,
                "predicate",
                f"option:{option_index}:when",
                None,
            )
        options.append(
            CompiledOption(
                option.names,
                option.takes_value,
                option.description,
                option.visible_to_binary_completion,
                option.suggest_assignment,
                option.repeatable,
                option.environment,
                option.owner_id,
                value_slot,
                when_matcher,
                when_slot,
            )
        )

    for candidate_index, registered in enumerate(completions.candidate_records):
        matcher = (
            registered.when if isinstance(registered.when, CompletionMatch) else None
        )
        when_slot = None
        if registered.when is not None and matcher is None:
            when_slot = slot_for(
                registered.owner_id,
                "predicate",
                f"candidate:{candidate_index}:when",
                None,
            )
        candidates.append(
            CompiledCandidate(
                registered.candidate.value,
                registered.candidate.description,
                registered.owner_id,
                matcher,
                when_slot,
            )
        )

    for provider in completions.provider_records:
        matcher = provider.when
        slot_id = slot_for(provider.owner_id, "provider", provider.provider_id, matcher)
        providers.append(
            CompiledProvider(slot_id, provider.owner_id, provider.provider_id, matcher)
        )

    dependency_items = tuple(
        (owner, tuple(dict.fromkeys(values)))
        for owner, values in sorted((dependencies or {}).items())
    )
    return CompletionManifest(
        generation=generation,
        options=tuple(options),
        candidates=tuple(candidates),
        providers=tuple(providers),
        slots=tuple(slots),
        dependencies=dependency_items,
        preprocess_order=tuple(preprocess_order),
        postprocess_order=tuple(postprocess_order),
    )


def _match_to_dict(matcher: CompletionMatch | None) -> dict[str, Any] | None:
    if matcher is None:
        return None
    return {
        "kind": matcher.kind,
        "values": list(matcher.values),
        "index": matcher.index,
        "children": [_match_to_dict(child) for child in matcher.children],
        "view": matcher.view,
    }


def _match_from_dict(value: Any) -> CompletionMatch | None:
    if value is None:
        return None
    item = _mapping(value)
    children: list[CompletionMatch] = []
    for child in _sequence(item, "children"):
        parsed = _match_from_dict(child)
        if parsed is not None:
            children.append(parsed)
    return CompletionMatch(
        _string(item, "kind"),
        tuple(_strings(item, "values")),
        None if item.get("index") is None else int(item["index"]),
        tuple(children),
        str(item.get("view", "wrapper")),
    )


def _option_to_dict(option: CompiledOption) -> dict[str, Any]:
    return (
        {**option.__dict__}
        if hasattr(option, "__dict__")
        else {
            "names": list(option.names),
            "takes_value": option.takes_value,
            "description": option.description,
            "visible_to_binary_completion": option.visible_to_binary_completion,
            "suggest_assignment": option.suggest_assignment,
            "repeatable": option.repeatable,
            "environment": option.environment,
            "owner_id": option.owner_id,
            "value_slot": option.value_slot,
            "when_matcher": _match_to_dict(option.when_matcher),
            "when_slot": option.when_slot,
        }
    )


def _option_from_dict(item: Any) -> CompiledOption:
    data = _mapping(item)
    return CompiledOption(
        tuple(_strings(data, "names")),
        bool(data["takes_value"]),
        None if data.get("description") is None else str(data["description"]),
        bool(data["visible_to_binary_completion"]),
        bool(data["suggest_assignment"]),
        bool(data["repeatable"]),
        None if data.get("environment") is None else str(data["environment"]),
        None if data.get("owner_id") is None else str(data["owner_id"]),
        None if data.get("value_slot") is None else str(data["value_slot"]),
        _match_from_dict(data.get("when_matcher")),
        None if data.get("when_slot") is None else str(data["when_slot"]),
    )


def _candidate_to_dict(candidate: CompiledCandidate) -> dict[str, Any]:
    return {
        "value": candidate.value,
        "description": candidate.description,
        "owner_id": candidate.owner_id,
        "when_matcher": _match_to_dict(candidate.when_matcher),
        "when_slot": candidate.when_slot,
    }


def _candidate_from_dict(item: Any) -> CompiledCandidate:
    data = _mapping(item)
    return CompiledCandidate(
        _string(data, "value"),
        None if data.get("description") is None else str(data["description"]),
        None if data.get("owner_id") is None else str(data["owner_id"]),
        _match_from_dict(data.get("when_matcher")),
        None if data.get("when_slot") is None else str(data["when_slot"]),
    )


def _provider_to_dict(provider: CompiledProvider) -> dict[str, Any]:
    return {
        "slot_id": provider.slot_id,
        "owner_id": provider.owner_id,
        "provider_id": provider.provider_id,
        "matcher": _match_to_dict(provider.matcher),
    }


def _provider_from_dict(item: Any) -> CompiledProvider:
    data = _mapping(item)
    return CompiledProvider(
        _string(data, "slot_id"),
        None if data.get("owner_id") is None else str(data["owner_id"]),
        _string(data, "provider_id"),
        _match_from_dict(data.get("matcher")),
    )


def _slot_to_dict(slot: CompletionSlot) -> dict[str, Any]:
    return {
        "slot_id": slot.slot_id,
        "owner_id": slot.owner_id,
        "kind": slot.kind,
        "provider_id": slot.provider_id,
        "matcher": _match_to_dict(slot.matcher),
    }


def _slot_from_dict(item: Any) -> CompletionSlot:
    data = _mapping(item)
    return CompletionSlot(
        _string(data, "slot_id"),
        None if data.get("owner_id") is None else str(data["owner_id"]),
        _string(data, "kind"),
        _string(data, "provider_id"),
        _match_from_dict(data.get("matcher")),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("completion manifest records must be mappings")
    return value


def _sequence(data: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    value = data.get(key, ())
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError(f"completion manifest field {key!r} must be a sequence")
    return tuple(value)


def _strings(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(_string_value(value) for value in _sequence(data, key))


def _string(data: Mapping[str, Any], key: str) -> str:
    return _string_value(data[key])


def _string_value(value: Any) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise TypeError("completion manifest string fields must be nonempty text")
    return value


def _string_pair(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError("completion dependency records must be sequences")
    return tuple(_string_value(item) for item in value)


def _dependency_pairs(
    data: Mapping[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    pairs: list[tuple[str, tuple[str, ...]]] = []
    for item in _sequence(data, "dependencies"):
        values = _string_pair(item)
        if not values:
            raise TypeError("completion dependency records cannot be empty")
        pairs.append((values[0], tuple(values[1:])))
    return tuple(pairs)
