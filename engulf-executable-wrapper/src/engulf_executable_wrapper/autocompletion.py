"""Runtime evaluator for the compiled executable-wrapper completion schema."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path

from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompiledOption,
    CompletionCallable,
    CompletionCandidate,
    CompletionContext,
    CompletionManifest,
    CompletionMatch,
    CompletionProvider,
    CompletionRegistry,
    RuntimeCompletion,
    build_manifest,
    invoke_provider,
    manifest_from_json,
    normalize_candidate,
)

RuntimePredicate = Callable[[CompletionContext], bool]


def completion_environment_fingerprint(records: Mapping[str, object]) -> str:
    """Return a stable digest for the installed plugin metadata used to compile."""
    payload = json.dumps(
        records, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CompletionArtifactStore:
    """Publish and load a manifest only when its environment fingerprint matches."""

    def load(self, path: str | Path, *, fingerprint: str) -> CompletionManifest | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("fingerprint") != fingerprint:
            return None
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            return None
        try:
            restored = manifest_from_json(manifest)
        except (TypeError, ValueError, KeyError, IndexError):
            return None
        source = payload.get("source")
        if source is not None and source != restored.generated_python():
            return None
        return restored

    def publish(
        self,
        path: str | Path,
        manifest: CompletionManifest,
        *,
        fingerprint: str,
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "fingerprint": fingerprint,
                "manifest": manifest.to_dict(),
                "source": manifest.generated_python(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


class CompiledCompletion:
    """A manifest paired with the live bindings for its runtime slots.

    The manifest is safe to serialize. The bindings deliberately remain local to
    the process that collected them; arbitrary plugin callables are never written
    into generated source.
    """

    def __init__(
        self,
        manifest: CompletionManifest,
        providers: Mapping[str, CompletionCallable | CompletionProvider],
        predicates: Mapping[str, RuntimePredicate],
    ) -> None:
        self.manifest = manifest
        self._providers = dict(providers)
        self._predicates = dict(predicates)
        self._slots = {slot.slot_id: slot for slot in manifest.slots}

    @classmethod
    def from_registries(
        cls,
        arguments: ArgumentRegistry,
        completions: CompletionRegistry,
        *,
        dependencies: Mapping[str, Iterable[str]] | None = None,
        preprocess_order: Iterable[str] = (),
        postprocess_order: Iterable[str] = (),
        generation: str | None = None,
    ) -> CompiledCompletion:
        manifest = build_manifest(
            arguments,
            completions,
            generation=generation or "pending",
            dependencies={} if dependencies is None else dependencies,
            preprocess_order=preprocess_order,
            postprocess_order=postprocess_order,
        )
        providers, predicates = _bind_slots(arguments, completions, manifest)
        if generation is None:
            digest = hashlib.sha256(manifest.to_json().encode("utf-8")).hexdigest()
            manifest = replace(manifest, generation=digest)
        return cls(manifest, providers, predicates)

    @classmethod
    def from_manifest(
        cls,
        manifest: CompletionManifest | str,
        providers: Mapping[str, CompletionCallable | CompletionProvider],
        predicates: Mapping[str, RuntimePredicate] | None = None,
    ) -> CompiledCompletion:
        return cls(
            manifest_from_json(manifest) if isinstance(manifest, str) else manifest,
            providers,
            {} if predicates is None else predicates,
        )

    def generated_python(self) -> str:
        return self.manifest.generated_python()

    def write_artifact(self, path: str | Path) -> None:
        """Write only the immutable schema; callers own atomic publication."""
        target = Path(path)
        target.write_text(self.manifest.to_json() + "\n", encoding="utf-8")

    def runtime_closure(self, owners: Iterable[str]) -> tuple[str, ...]:
        return self.manifest.runtime_closure(owners)

    def runtime_owners(self, context: CompletionContext) -> frozenset[str]:
        """Return plugin owners whose runtime slots can affect this request.

        This is deliberately a manifest-only operation.  It is used before any
        plugin endpoint is materialized so a completion request can activate
        only matched owners and their mandatory dependency closure.
        """
        owners: set[str] = set()
        option_by_slot = {
            option.value_slot: option
            for option in self.manifest.options
            if option.value_slot is not None
        }
        for slot in self.manifest.slots:
            if slot.owner_id is None:
                continue
            if slot.kind == "predicate" and _predicate_slot_requested(
                slot.slot_id, self.manifest
            ):
                owners.add(slot.owner_id)
                continue
            if slot.slot_id in option_by_slot:
                option = option_by_slot[slot.slot_id]
                if not _option_value_requested(option, context):
                    continue
            elif not _provider_slot_requested(slot.slot_id, self.manifest, context):
                continue
            if slot.matcher is None or slot.matcher.matches(context):
                owners.add(slot.owner_id)
        return frozenset(owners)

    def candidates(
        self,
        context: CompletionContext,
    ) -> tuple[CompletionCandidate, ...]:
        """Evaluate wrapper-owned options, static entries, and matching slots."""
        result: list[CompletionCandidate] = []
        options = self.manifest.options
        current = context.current

        assignment = _find_assignment(options, current)
        if assignment is not None:
            option, name, value = assignment
            if option.value_slot is not None:
                value_context = _context_with_current(context, value)
                result.extend(
                    CompletionCandidate(
                        f"{name}={candidate.value}", candidate.description
                    )
                    for candidate in self._provider_candidates(
                        option.value_slot, value_context
                    )
                    if candidate.value.startswith(value)
                )
            return _deduplicate(result, current)

        previous = _find_exact(options, context.previous or "")
        if previous is not None and previous.takes_value:
            if previous.value_slot is not None:
                result.extend(self._provider_candidates(previous.value_slot, context))
            return _deduplicate(result, current)

        prior_words = context.words[: max(0, context.cursor_index)]
        if "--" not in prior_words:
            for option in options:
                if not self._option_visible(option, context):
                    continue
                if not option.repeatable and _option_was_used(
                    option.names, prior_words
                ):
                    continue
                for name in option.names:
                    if name.startswith(current):
                        suffix = (
                            "="
                            if option.takes_value
                            and option.suggest_assignment
                            and name.startswith("--")
                            else ""
                        )
                        result.append(
                            CompletionCandidate(name + suffix, option.description)
                        )

        for candidate in self.manifest.candidates:
            if self._candidate_visible(
                candidate.when_matcher, candidate.when_slot, context
            ) and candidate.value.startswith(current):
                result.append(
                    CompletionCandidate(candidate.value, candidate.description)
                )

        for provider in self.manifest.providers:
            if provider.matcher is not None and not provider.matcher.matches(context):
                continue
            result.extend(self._provider_candidates(provider.slot_id, context))
        return _deduplicate(result, current)

    def _option_visible(
        self, option: CompiledOption, context: CompletionContext
    ) -> bool:
        return self._candidate_visible(option.when_matcher, option.when_slot, context)

    def _candidate_visible(
        self,
        matcher: CompletionMatch | None,
        slot_id: str | None,
        context: CompletionContext,
    ) -> bool:
        if matcher is not None and not matcher.matches(context):
            return False
        if slot_id is not None:
            predicate = self._predicates.get(slot_id)
            if predicate is None:
                return False
            return bool(predicate(context))
        return True

    def _provider_candidates(
        self, slot_id: str, context: CompletionContext
    ) -> list[CompletionCandidate]:
        provider = self._providers.get(slot_id)
        if provider is None:
            return []
        slot = self._slots.get(slot_id)
        if (
            slot is not None
            and slot.matcher is not None
            and not slot.matcher.matches(context)
        ):
            return []
        return [
            normalize_candidate(item) for item in invoke_provider(provider, context)
        ]


def compile_completion(
    arguments: ArgumentRegistry,
    completions: CompletionRegistry,
    **kwargs: object,
) -> CompiledCompletion:
    """Convenience entry point used by goals and standalone generators."""
    return CompiledCompletion.from_registries(arguments, completions, **kwargs)  # type: ignore[arg-type]


def _bind_slots(
    arguments: ArgumentRegistry,
    completions: CompletionRegistry,
    manifest: CompletionManifest,
) -> tuple[
    dict[str, CompletionCallable | CompletionProvider], dict[str, RuntimePredicate]
]:
    providers: dict[str, CompletionCallable | CompletionProvider] = {}
    predicates: dict[str, RuntimePredicate] = {}
    for option_spec, compiled_option in zip(
        arguments.options, manifest.options, strict=True
    ):
        if option_spec.value_completer is not None:
            if compiled_option.value_slot is None:
                raise RuntimeError("completion manifest lost option provider slot")
            provider = (
                option_spec.value_completer.provider
                if isinstance(option_spec.value_completer, RuntimeCompletion)
                else option_spec.value_completer
            )
            providers[compiled_option.value_slot] = provider
        if option_spec.when is not None and not isinstance(
            option_spec.when, CompletionMatch
        ):
            if compiled_option.when_slot is None:
                raise RuntimeError("completion manifest lost option predicate slot")
            predicates[compiled_option.when_slot] = option_spec.when

    for candidate_record, compiled_candidate in zip(
        completions.candidate_records, manifest.candidates, strict=True
    ):
        if candidate_record.when is not None and not isinstance(
            candidate_record.when, CompletionMatch
        ):
            if compiled_candidate.when_slot is None:
                raise RuntimeError("completion manifest lost candidate predicate slot")
            predicates[compiled_candidate.when_slot] = candidate_record.when

    for provider_record, compiled_provider in zip(
        completions.provider_records, manifest.providers, strict=True
    ):
        providers[compiled_provider.slot_id] = provider_record.provider
    return providers, predicates


def _find_exact(
    options: tuple[CompiledOption, ...], word: str
) -> CompiledOption | None:
    for option in options:
        if word in option.names:
            return option
    return None


def _option_value_requested(option: CompiledOption, context: CompletionContext) -> bool:
    if _find_assignment((option,), context.current) is not None:
        return True
    return context.previous in option.names


def _provider_slot_requested(
    slot_id: str,
    manifest: CompletionManifest,
    context: CompletionContext,
) -> bool:
    return any(
        provider.slot_id == slot_id
        and (provider.matcher is None or provider.matcher.matches(context))
        for provider in manifest.providers
    )


def _predicate_slot_requested(
    slot_id: str,
    manifest: CompletionManifest,
) -> bool:
    return any(option.when_slot == slot_id for option in manifest.options) or any(
        candidate.when_slot == slot_id for candidate in manifest.candidates
    )


def _find_assignment(
    options: tuple[CompiledOption, ...], word: str
) -> tuple[CompiledOption, str, str] | None:
    if "=" not in word:
        return None
    name, value = word.split("=", 1)
    option = _find_exact(options, name)
    if option is None or not option.takes_value:
        return None
    return option, name, value


def _context_with_current(
    context: CompletionContext, current: str
) -> CompletionContext:
    words = list(context.words)
    while len(words) <= context.cursor_index:
        words.append("")
    words[context.cursor_index] = current
    return replace(context, words=tuple(words))


def _option_was_used(names: tuple[str, ...], words: tuple[str, ...]) -> bool:
    return any(word in names or word.split("=", 1)[0] in names for word in words)


def _deduplicate(
    candidates: Iterable[CompletionCandidate], current: str
) -> tuple[CompletionCandidate, ...]:
    result: list[CompletionCandidate] = []
    positions: dict[str, int] = {}
    for candidate in candidates:
        if not candidate.value.startswith(current):
            continue
        position = positions.get(candidate.value)
        if position is None:
            positions[candidate.value] = len(result)
            result.append(candidate)
        elif result[position].description is None and candidate.description is not None:
            result[position] = candidate
    return tuple(result)
