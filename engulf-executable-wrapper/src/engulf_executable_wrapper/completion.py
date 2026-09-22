from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from collections.abc import Iterable
from pathlib import Path

from engulf_executable_wrapper_api import (
    ArgumentRegistry,
    CompletionCallable,
    CompletionCandidate,
    CompletionContext,
    CompletionMatch,
    CompletionPredicate,
    CompletionProvider,
    RuntimeCompletion,
    Shell,
    invoke_provider,
    normalize_candidate,
)

from .goal import ExecutableWrapperGoal


def handle_internal_protocol(
    goal: ExecutableWrapperGoal,
    argv: tuple[str, ...],
) -> int:
    action = os.environ.get("ENGULF_INTERNAL_ACTION")
    if action == "describe":
        json.dump(
            {
                "executable": goal.executable,
                "completion_service": Path(goal.executable).name,
                "completion_source": (
                    goal.executable if goal.source_completion else None
                ),
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return 0

    shell = Shell(os.environ["ENGULF_INTERNAL_SHELL"])
    cursor_index = int(os.environ["ENGULF_INTERNAL_CWORD"])
    words = _ensure_current_word(argv, cursor_index)

    if action == "normalize":
        normalized, normalized_cursor, current_hidden = _normalize_for_binary(
            goal.arguments, words, cursor_index
        )
        protocol_cursor = -1 if current_hidden else normalized_cursor
        _write_nul_records((str(protocol_cursor), *normalized))
        return 0

    if action == "complete":
        normalized, normalized_cursor, _ = _normalize_for_binary(
            goal.arguments, words, cursor_index
        )
        context = _completion_context(
            shell,
            goal,
            words,
            cursor_index,
            binary_words=normalized,
            binary_cursor_index=normalized_cursor,
        )
        native_available = os.environ.get("ENGULF_INTERNAL_NATIVE") == "1"
        candidates = collect_candidates(
            goal,
            context,
            include_binary_provider=not native_available,
        )
        _write_nul_records(candidate.value for candidate in candidates)
        return 0

    if action == "complete-context":
        normalized, normalized_cursor, current_hidden = _normalize_for_binary(
            goal.arguments, words, cursor_index
        )
        context = _completion_context(
            shell,
            goal,
            words,
            cursor_index,
            binary_words=normalized,
            binary_cursor_index=normalized_cursor,
        )
        binary_candidates, wrapper_candidates = _candidate_groups(goal, context)
        protocol_cursor = -1 if current_hidden else normalized_cursor
        _write_context_records(
            protocol_cursor,
            normalized,
            wrapper_candidates,
            binary_candidates,
        )
        return 0

    raise ValueError(f"unsupported internal action: {action!r}")


def _completion_context(
    shell: Shell,
    goal: ExecutableWrapperGoal,
    words: tuple[str, ...],
    cursor_index: int,
    *,
    binary_words: tuple[str, ...] | None = None,
    binary_cursor_index: int | None = None,
) -> CompletionContext:
    return CompletionContext(
        shell=shell,
        wrapper_command=os.environ.get("ENGULF_INTERNAL_WRAPPER_COMMAND", ""),
        binary=goal.executable,
        words=words,
        cursor_index=cursor_index,
        binary_words=binary_words,
        binary_cursor_index=binary_cursor_index,
        cwd=os.getcwd(),
        environment=tuple(sorted(os.environ.items())),
    )


def completion_context_for_request(
    goal: ExecutableWrapperGoal,
    argv: tuple[str, ...],
) -> CompletionContext:
    """Build the immutable provider context for the current internal request."""
    shell = Shell(os.environ["ENGULF_INTERNAL_SHELL"])
    cursor_index = int(os.environ["ENGULF_INTERNAL_CWORD"])
    words = _ensure_current_word(argv, cursor_index)
    normalized, normalized_cursor, _ = _normalize_for_binary(
        goal.arguments, words, cursor_index
    )
    return _completion_context(
        shell,
        goal,
        words,
        cursor_index,
        binary_words=normalized,
        binary_cursor_index=normalized_cursor,
    )


def collect_candidates(
    goal: ExecutableWrapperGoal,
    context: CompletionContext,
    *,
    include_binary_provider: bool,
) -> tuple[CompletionCandidate, ...]:
    binary_candidates, wrapper_candidates = _candidate_groups(goal, context)
    candidates = (
        (binary_candidates + wrapper_candidates)
        if include_binary_provider
        else wrapper_candidates
    )
    return _deduplicate_candidates(candidates, context.current)


def _candidate_groups(
    goal: ExecutableWrapperGoal,
    context: CompletionContext,
) -> tuple[tuple[CompletionCandidate, ...], tuple[CompletionCandidate, ...]]:
    binary_candidates: list[CompletionCandidate] = []
    current_hidden = context.cursor_index in _hidden_binary_indexes(
        goal.arguments, context.words
    )
    if not current_hidden and goal.completion_provider is not None:
        binary_candidates.extend(
            _provider_candidates(goal.completion_provider, context)
        )

    compiled = goal.compiled_completion
    if compiled is not None:
        wrapper_candidates = list(compiled.candidates(context))
    else:
        wrapper_candidates = _argument_candidates(goal.arguments, context)
        wrapper_candidates.extend(goal.completions.static_candidates(context))
        for record in goal.completions.provider_records:
            wrapper_candidates.extend(
                _provider_candidates(
                    RuntimeCompletion(record.provider_id, record.provider, record.when),
                    context,
                )
            )

    return (
        tuple(
            candidate
            for candidate in binary_candidates
            if candidate.value.startswith(context.current)
        ),
        tuple(
            candidate
            for candidate in wrapper_candidates
            if candidate.value.startswith(context.current)
        ),
    )


def _deduplicate_candidates(
    candidates: Iterable[CompletionCandidate],
    current: str,
) -> tuple[CompletionCandidate, ...]:
    deduplicated: list[CompletionCandidate] = []
    positions: dict[str, int] = {}
    for candidate in candidates:
        if not candidate.value.startswith(current):
            continue
        existing = positions.get(candidate.value)
        if existing is None:
            positions[candidate.value] = len(deduplicated)
            deduplicated.append(candidate)
        elif (
            deduplicated[existing].description is None
            and candidate.description is not None
        ):
            deduplicated[existing] = candidate
    return tuple(deduplicated)


def _argument_candidates(
    registry: ArgumentRegistry,
    context: CompletionContext,
) -> list[CompletionCandidate]:
    current = context.current
    assignment = registry.find_assignment(current)
    if assignment is not None:
        spec, name, value = assignment
        if spec.value_completer is None:
            return []
        value_context = _context_with_current(context, value)
        return [
            CompletionCandidate(f"{name}={candidate.value}", candidate.description)
            for candidate in _provider_candidates(spec.value_completer, value_context)
            if candidate.value.startswith(value)
        ]

    previous_spec = registry.find_exact(context.previous or "")
    if previous_spec is not None and previous_spec.takes_value:
        if previous_spec.value_completer is None:
            return []
        return _provider_candidates(previous_spec.value_completer, context)

    result: list[CompletionCandidate] = []
    prior_words = context.words[: max(0, context.cursor_index)]
    if "--" in prior_words:
        return result
    for spec in registry.options:
        if spec.when is not None and not _matches_predicate(spec.when, context):
            continue
        if not spec.repeatable and _option_was_used(spec.names, prior_words):
            continue
        for name in spec.names:
            if name.startswith(current):
                suffix = (
                    "="
                    if spec.takes_value
                    and spec.suggest_assignment
                    and name.startswith("--")
                    else ""
                )
                result.append(CompletionCandidate(name + suffix, spec.description))
    return result


def _provider_candidates(
    provider: CompletionCallable | CompletionProvider | RuntimeCompletion,
    context: CompletionContext,
) -> list[CompletionCandidate]:
    if isinstance(provider, RuntimeCompletion):
        if provider.when is not None and not provider.when.matches(context):
            return []
        provider = provider.provider
    return [
        normalize_candidate(candidate)
        for candidate in invoke_provider(provider, context)
    ]


def _matches_predicate(
    predicate: CompletionPredicate,
    context: CompletionContext,
) -> bool:
    if isinstance(predicate, CompletionMatch):
        return predicate.matches(context)
    return bool(predicate(context))


def _context_with_current(
    context: CompletionContext, current: str
) -> CompletionContext:
    words = list(context.words)
    while len(words) <= context.cursor_index:
        words.append("")
    words[context.cursor_index] = current
    return CompletionContext(
        context.shell,
        context.wrapper_command,
        context.binary,
        tuple(words),
        context.cursor_index,
        context.binary_words,
        context.binary_cursor_index,
        context.cwd,
        context.environment,
    )


def _option_was_used(names: tuple[str, ...], words: tuple[str, ...]) -> bool:
    for word in words:
        if word in names:
            return True
        if "=" in word and word.split("=", 1)[0] in names:
            return True
    return False


def normalize_for_binary(
    registry: ArgumentRegistry,
    words: tuple[str, ...],
    cursor_index: int,
) -> tuple[tuple[str, ...], int]:
    normalized, normalized_cursor, _current_hidden = _normalize_for_binary(
        registry, words, cursor_index
    )
    return normalized, normalized_cursor


def _normalize_for_binary(
    registry: ArgumentRegistry,
    words: tuple[str, ...],
    cursor_index: int,
) -> tuple[tuple[str, ...], int, bool]:
    hidden = _hidden_binary_indexes(registry, words)
    current_hidden = cursor_index in hidden

    normalized: list[str] = []
    normalized_cursor: int | None = None
    for original_index, word in enumerate(words):
        if original_index in hidden:
            if original_index == cursor_index:
                normalized_cursor = len(normalized)
                normalized.append("")
            continue
        normalized.append(word)
        if original_index == cursor_index:
            normalized_cursor = len(normalized) - 1

    if normalized_cursor is None:
        normalized_cursor = sum(
            1 for index in range(cursor_index) if index not in hidden
        )
        normalized.insert(min(normalized_cursor, len(normalized)), "")
    return tuple(normalized), normalized_cursor, current_hidden


def _hidden_binary_indexes(
    registry: ArgumentRegistry,
    words: tuple[str, ...],
) -> frozenset[int]:
    hidden: set[int] = set()
    index = 0
    while index < len(words):
        if words[index] == "--":
            break
        assignment = registry.find_assignment(words[index])
        if assignment is not None:
            spec, _, _ = assignment
            if not spec.visible_to_binary_completion:
                hidden.add(index)
            index += 1
            continue

        exact_spec = registry.find_exact(words[index])
        if exact_spec is None or exact_spec.visible_to_binary_completion:
            index += 1
            continue

        hidden.add(index)
        if exact_spec.takes_value and index + 1 < len(words):
            hidden.add(index + 1)
            index += 2
        else:
            index += 1
    return frozenset(hidden)


def render_completion_script(
    shell: Shell,
    wrapper_command: str,
    binary_service: str,
    *,
    completion_source: str | None = None,
) -> str:
    if not wrapper_command or "\0" in wrapper_command:
        raise ValueError(
            "wrapper command must be a non-empty string without NUL characters"
        )
    if not binary_service or "\0" in binary_service:
        raise ValueError(
            "binary service must be a non-empty string without NUL characters"
        )
    if completion_source is not None:
        if not isinstance(completion_source, str):
            raise TypeError("completion source must be a string or None")
        if not completion_source or "\0" in completion_source:
            raise ValueError(
                "completion source must be non-empty and contain no NUL characters"
            )
    if shell is Shell.BASH:
        return _render_bash(wrapper_command, binary_service, completion_source)
    if shell is Shell.ZSH:
        return _render_zsh(wrapper_command, binary_service, completion_source)
    if shell is Shell.FISH:
        return _render_fish(wrapper_command, binary_service, completion_source)
    raise ValueError(f"unsupported shell: {shell}")


def _render_bash(
    wrapper_command: str,
    binary_service: str,
    completion_source: str | None,
) -> str:
    suffix = _identifier_suffix(wrapper_command)
    function_name = f"_engulf_complete_{suffix}"
    source_marker = f"_engulf_source_attempted_{suffix}"
    wrapper_literal = shlex.quote(wrapper_command)
    binary_literal = shlex.quote(binary_service)
    source_literal = shlex.quote(completion_source or "")
    command_literal = shlex.quote(wrapper_command)
    return f"""# Generated by engulf-completion. Existing wrapped-command completion is preferred.
{source_marker}=0
{function_name}() {{
    local _engulf_wrapper={wrapper_literal}
    local _engulf_binary={binary_literal}
    local _engulf_completion_source={source_literal}
    local _engulf_arg_index
    local -a _engulf_args
    local _engulf_current=""
    local _engulf_cword=$COMP_CWORD
    local -a _engulf_words=()
    if declare -F _get_comp_words_by_ref >/dev/null \
            && _get_comp_words_by_ref -n = -c _engulf_current \
                -i _engulf_cword -w _engulf_words; then
        _engulf_arg_index=$((_engulf_cword - 1))
        _engulf_args=("${{_engulf_words[@]:1}}")
    else
        local _engulf_raw_index=$((COMP_CWORD - 1))
        local -a _engulf_raw_args=("${{COMP_WORDS[@]:1}}")
        local _engulf_index
        local _engulf_join_next=0
        _engulf_args=()
        _engulf_arg_index=0
        for ((_engulf_index = 0; \
                _engulf_index < ${{#_engulf_raw_args[@]}}; \
                _engulf_index++)); do
            local _engulf_word=${{_engulf_raw_args[_engulf_index]}}
            if [[ $_engulf_word == = && ${{#_engulf_args[@]}} -gt 0 ]]; then
                _engulf_args[-1]+="="
                _engulf_join_next=1
            elif (( _engulf_join_next )); then
                _engulf_args[-1]+=$_engulf_word
                _engulf_join_next=0
            else
                _engulf_args+=("$_engulf_word")
            fi
            if (( _engulf_index == _engulf_raw_index )); then
                _engulf_arg_index=$((${{#_engulf_args[@]}} - 1))
            fi
        done
    fi
    if (( _engulf_arg_index >= ${{#_engulf_args[@]}} )); then
        _engulf_args+=("")
    fi
    local _engulf_raw_current=${{COMP_WORDS[COMP_CWORD]-}}
    local _engulf_logical_current=${{_engulf_args[_engulf_arg_index]-}}
    local _engulf_reply_prefix=""
    if [[ $_engulf_raw_current == = ]]; then
        _engulf_reply_prefix=$_engulf_logical_current
    elif [[ -n $_engulf_raw_current \
            && $_engulf_logical_current != "$_engulf_raw_current" \
            && $_engulf_logical_current == *"$_engulf_raw_current" ]]; then
        _engulf_reply_prefix=${{_engulf_logical_current%"$_engulf_raw_current"}}
    fi

    local -a _engulf_context=()
    mapfile -d '' -t _engulf_context < <(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=complete-context \\
            ENGULF_INTERNAL_SHELL=bash ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
    )
    local _engulf_context_index=0
    local _engulf_normalized_index=${{_engulf_context[_engulf_context_index]:-$_engulf_arg_index}}
    ((_engulf_context_index++))
    local _engulf_normalized_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_binary_args=()
    local _engulf_index
    for ((_engulf_index = 0; _engulf_index < _engulf_normalized_count; _engulf_index++)); do
        _engulf_binary_args+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done
    local _engulf_wrapper_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_extra=()
    for ((_engulf_index = 0; _engulf_index < _engulf_wrapper_count; _engulf_index++)); do
        _engulf_extra+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done
    local _engulf_binary_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_binary_candidates=()
    for ((_engulf_index = 0; _engulf_index < _engulf_binary_count; _engulf_index++)); do
        _engulf_binary_candidates+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done

    local _engulf_spec=""
    local _engulf_base_function=""
    if ! _engulf_spec=$(complete -p "$_engulf_binary" 2>/dev/null); then
        if declare -F _completion_loader >/dev/null; then
            _completion_loader "$_engulf_binary" >/dev/null 2>&1 || true
            _engulf_spec=$(complete -p "$_engulf_binary" 2>/dev/null) || true
        fi
    fi
    if [[ $_engulf_spec =~ (^|[[:space:]])-F[[:space:]]+([_[:alnum:]:-]+)($|[[:space:]]) ]]; then
        _engulf_base_function=${{BASH_REMATCH[2]}}
    fi

    local _engulf_has_native=0
    if [[ -n $_engulf_base_function && $_engulf_base_function != _minimal ]] \
            && declare -F "$_engulf_base_function" >/dev/null; then
        _engulf_has_native=1
    fi
    if (( ! _engulf_has_native && ! {source_marker} )) \
            && [[ -n $_engulf_completion_source ]] \
            && command -v "$_engulf_completion_source" >/dev/null 2>&1; then
        {source_marker}=1
        builtin source <(
            command "$_engulf_completion_source" completion bash 2>/dev/null
        ) >/dev/null 2>&1 || true
        _engulf_spec=$(complete -p "$_engulf_binary" 2>/dev/null) || true
        _engulf_base_function=""
        if [[ $_engulf_spec =~ (^|[[:space:]])-F[[:space:]]+([_[:alnum:]:-]+)($|[[:space:]]) ]]; then
            _engulf_base_function=${{BASH_REMATCH[2]}}
        fi
        if [[ -n $_engulf_base_function && $_engulf_base_function != _minimal ]] \
                && declare -F "$_engulf_base_function" >/dev/null; then
            _engulf_has_native=1
        fi
    fi

    local _engulf_native=0
    local -a _engulf_native_replies=()
    (( _engulf_has_native )) && _engulf_native=1
    if (( _engulf_has_native && _engulf_normalized_index >= 0 )); then
        local -a _engulf_saved_words=("${{COMP_WORDS[@]}}")
        local _engulf_saved_cword=$COMP_CWORD
        local _engulf_saved_line=$COMP_LINE
        local _engulf_saved_point=$COMP_POINT
        COMP_WORDS=("$_engulf_binary" "${{_engulf_binary_args[@]}}")
        COMP_CWORD=$((_engulf_normalized_index + 1))
        local -a _engulf_line_words=("${{COMP_WORDS[@]:0:COMP_CWORD}}")
        printf -v COMP_LINE '%q ' "${{_engulf_line_words[@]}}"
        if [[ -n ${{COMP_WORDS[COMP_CWORD]-}} ]]; then
            local _engulf_quoted_current
            printf -v _engulf_quoted_current '%q' "${{COMP_WORDS[COMP_CWORD]}}"
            COMP_LINE+=$_engulf_quoted_current
        fi
        COMP_POINT=${{#COMP_LINE}}
        COMPREPLY=()
        "$_engulf_base_function" "$_engulf_binary" \\
            "${{COMP_WORDS[COMP_CWORD]-}}" "${{COMP_WORDS[COMP_CWORD-1]-}}" || true
        _engulf_native_replies=("${{COMPREPLY[@]}}")
        COMP_WORDS=("${{_engulf_saved_words[@]}}")
        COMP_CWORD=$_engulf_saved_cword
        COMP_LINE=$_engulf_saved_line
        COMP_POINT=$_engulf_saved_point
        local _engulf_option
        for _engulf_option in bashdefault default dirnames filenames noquote nosort nospace plusdirs; do
            if [[ " $_engulf_spec " == *" -o $_engulf_option "* ]]; then
                compopt -o "$_engulf_option" 2>/dev/null || true
            fi
        done
    fi

    if [[ -n $_engulf_reply_prefix ]]; then
        local _engulf_extra_index
        local _engulf_candidate_array
        for _engulf_candidate_array in _engulf_extra _engulf_binary_candidates; do
            local -n _engulf_candidates_ref=$_engulf_candidate_array
            for ((_engulf_index = 0; _engulf_index < ${{#_engulf_candidates_ref[@]}}; _engulf_index++)); do
                if [[ ${{_engulf_candidates_ref[_engulf_index]}} == "$_engulf_reply_prefix"* ]]; then
                    _engulf_candidates_ref[_engulf_index]=${{_engulf_candidates_ref[_engulf_index]#"$_engulf_reply_prefix"}}
                fi
            done
        done
    fi

    COMPREPLY=()
    local -A _engulf_seen=()
    local _engulf_candidate
    local -a _engulf_candidates=()
    if (( ! _engulf_has_native )); then
        _engulf_candidates+=("${{_engulf_binary_candidates[@]}}")
    fi
    _engulf_candidates+=("${{_engulf_extra[@]}}")
    for _engulf_candidate in "${{_engulf_native_replies[@]}}" "${{_engulf_candidates[@]}}"; do
        [[ -n $_engulf_candidate ]] || continue
        [[ -n ${{_engulf_seen["$_engulf_candidate"]+present}} ]] && continue
        _engulf_seen["$_engulf_candidate"]=1
        COMPREPLY+=("$_engulf_candidate")
    done
    if (( ${{#COMPREPLY[@]}} )); then
        local _engulf_continues=1
        for _engulf_candidate in "${{COMPREPLY[@]}}"; do
            if [[ $_engulf_candidate != *= && $_engulf_candidate != */ ]]; then
                _engulf_continues=0
                break
            fi
        done
        if (( _engulf_continues )); then
            compopt -o nospace 2>/dev/null || true
        elif (( ${{#_engulf_candidates[@]}} )); then
            compopt +o nospace 2>/dev/null || true
        fi
    fi
}}

complete -F {function_name} {command_literal}
"""


def _render_zsh(
    wrapper_command: str,
    binary_service: str,
    completion_source: str | None,
) -> str:
    suffix = _identifier_suffix(wrapper_command)
    helper_name = f"_engulf_complete_{suffix}"
    source_marker = f"_engulf_source_attempted_{suffix}"
    wrapper_literal = shlex.quote(wrapper_command)
    binary_literal = shlex.quote(binary_service)
    source_literal = shlex.quote(completion_source or "")
    command_literal = shlex.quote(wrapper_command)
    return f"""#compdef {command_literal}
# Generated by engulf-completion. Load with compinit or source after compinit.
(( $+parameters[{source_marker}] )) || typeset -g {source_marker}=0
{helper_name}() {{
    local _engulf_wrapper={wrapper_literal}
    local _engulf_binary={binary_literal}
    local _engulf_completion_source={source_literal}
    local _engulf_arg_index=$((CURRENT - 2))
    local -a _engulf_args
    _engulf_args=("${{(@)words[2,-1]}}")
    if (( _engulf_arg_index >= ${{#_engulf_args}} )); then
        _engulf_args+=("")
    fi

    local -a _engulf_context
    _engulf_context=("${{(@0)$(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=complete-context \\
            ENGULF_INTERNAL_SHELL=zsh ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
        )}}")
    local _engulf_context_index=1
    local _engulf_normalized_index=${{_engulf_context[_engulf_context_index]:-$_engulf_arg_index}}
    ((_engulf_context_index++))
    local _engulf_normalized_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_binary_args
    local _engulf_index
    for ((_engulf_index = 0; _engulf_index < _engulf_normalized_count; _engulf_index++)); do
        _engulf_binary_args+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done
    local _engulf_wrapper_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_extra
    for ((_engulf_index = 0; _engulf_index < _engulf_wrapper_count; _engulf_index++)); do
        _engulf_extra+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done
    local _engulf_binary_count=${{_engulf_context[_engulf_context_index]:-0}}
    ((_engulf_context_index++))
    local -a _engulf_binary_candidates
    for ((_engulf_index = 0; _engulf_index < _engulf_binary_count; _engulf_index++)); do
        _engulf_binary_candidates+=("${{_engulf_context[_engulf_context_index]}}")
        ((_engulf_context_index++))
    done

    local _engulf_native=0
    local _engulf_base_function=""
    if (( $+_comps )); then
        _engulf_base_function=${{_comps[$_engulf_binary]-}}
    fi
    local _engulf_has_native=0
    if [[ -n $_engulf_base_function && $_engulf_base_function != {helper_name} ]]; then
        (( $+functions[$_engulf_base_function] )) \
            || autoload -Uz "$_engulf_base_function" 2>/dev/null || true
        (( $+functions[$_engulf_base_function] )) && _engulf_has_native=1
    fi
    if (( ! _engulf_has_native && ! {source_marker} )) \
            && [[ -n $_engulf_completion_source ]] \
            && command -v "$_engulf_completion_source" >/dev/null 2>&1; then
        {source_marker}=1
        source <(
            command "$_engulf_completion_source" completion zsh 2>/dev/null
        ) >/dev/null 2>&1 || true
        _engulf_base_function=""
        if (( $+_comps )); then
            _engulf_base_function=${{_comps[$_engulf_binary]-}}
        fi
        if [[ -n $_engulf_base_function && $_engulf_base_function != {helper_name} ]]; then
            (( $+functions[$_engulf_base_function] )) \
                || autoload -Uz "$_engulf_base_function" 2>/dev/null || true
            (( $+functions[$_engulf_base_function] )) && _engulf_has_native=1
        fi
    fi
    (( _engulf_has_native )) && _engulf_native=1
    if (( _engulf_has_native && _engulf_normalized_index >= 0 )); then
        local -a _engulf_saved_words=("${{words[@]}}")
        local _engulf_saved_current=$CURRENT
        local _engulf_saved_service=${{service-}}
        words=("$_engulf_binary" "${{_engulf_binary_args[@]}}")
        CURRENT=$((_engulf_normalized_index + 2))
        service=$_engulf_binary
        "$_engulf_base_function" || true
        words=("${{_engulf_saved_words[@]}}")
        CURRENT=$_engulf_saved_current
        service=$_engulf_saved_service
    fi

    local -a _engulf_candidates
    (( ! _engulf_has_native )) && _engulf_candidates=("${{_engulf_binary_candidates[@]}}")
    _engulf_candidates+=("${{_engulf_extra[@]}}")
    (( ${{#_engulf_candidates}} )) && compadd -- "${{_engulf_candidates[@]}}"
}}

if [[ -n ${{CURRENT-}} ]] && (( ${{#words}} )); then
    {helper_name} "$@"
elif (( $+functions[compdef] )); then
    compdef {helper_name} {command_literal}
fi
"""


def _render_fish(
    wrapper_command: str,
    binary_service: str,
    completion_source: str | None,
) -> str:
    suffix = _identifier_suffix(wrapper_command)
    helper_name = f"__engulf_complete_{suffix}"
    source_marker = f"__engulf_source_attempted_{suffix}"
    wrapper_literal = shlex.quote(wrapper_command)
    binary_literal = shlex.quote(binary_service)
    source_literal = shlex.quote(completion_source or "")
    command_literal = shlex.quote(wrapper_command)
    return f"""# Generated by engulf-completion for fish.
set -g {source_marker} 0
function {helper_name}
    set -l _engulf_wrapper {wrapper_literal}
    set -l _engulf_binary {binary_literal}
    set -l _engulf_completion_source {source_literal}
    set -l _engulf_tokens (commandline -opc)
    set -l _engulf_args $_engulf_tokens[2..-1]
    set -l _engulf_current (commandline -ct)
    if test (count $_engulf_current) -gt 0
        set -a _engulf_args $_engulf_current
    else
        set -a _engulf_args ''
    end
    set -l _engulf_arg_index (math (count $_engulf_args) - 1)

    set -l _engulf_context (command env ENGULF_INTERNAL_PROTOCOL=1 \
        ENGULF_INTERNAL_ACTION=complete-context ENGULF_INTERNAL_SHELL=fish \
        ENGULF_INTERNAL_CWORD=$_engulf_arg_index \
        ENGULF_INTERNAL_WRAPPER_COMMAND=$_engulf_wrapper \
        $_engulf_wrapper $_engulf_args 2>/dev/null | string split0)
    set -l _engulf_context_index 1
    set -l _engulf_normalized_index $_engulf_context[$_engulf_context_index]
    set _engulf_context_index (math $_engulf_context_index + 1)
    set -l _engulf_normalized_count $_engulf_context[$_engulf_context_index]
    set _engulf_context_index (math $_engulf_context_index + 1)
    set -l _engulf_binary_args
    set -l _engulf_index 0
    while test $_engulf_index -lt $_engulf_normalized_count
        set -a _engulf_binary_args $_engulf_context[$_engulf_context_index]
        set _engulf_context_index (math $_engulf_context_index + 1)
        set _engulf_index (math $_engulf_index + 1)
    end
    set -l _engulf_wrapper_count $_engulf_context[$_engulf_context_index]
    set _engulf_context_index (math $_engulf_context_index + 1)
    set -l _engulf_extra
    set _engulf_index 0
    while test $_engulf_index -lt $_engulf_wrapper_count
        set -a _engulf_extra $_engulf_context[$_engulf_context_index]
        set _engulf_context_index (math $_engulf_context_index + 1)
        set _engulf_index (math $_engulf_index + 1)
    end
    set -l _engulf_binary_count $_engulf_context[$_engulf_context_index]
    set _engulf_context_index (math $_engulf_context_index + 1)
    set -l _engulf_binary_candidates
    set _engulf_index 0
    while test $_engulf_index -lt $_engulf_binary_count
        set -a _engulf_binary_candidates $_engulf_context[$_engulf_context_index]
        set _engulf_context_index (math $_engulf_context_index + 1)
        set _engulf_index (math $_engulf_index + 1)
    end

    set -l _engulf_native 0
    set -l _engulf_native_replies
    if type -q $_engulf_binary
        set -l _engulf_line (string join ' ' (string escape -- $_engulf_binary $_engulf_binary_args))
        if test $_engulf_normalized_index -ge 0
            set _engulf_native_replies (complete -C "$_engulf_line" 2>/dev/null)
        end
        set -l _engulf_native_spec (complete -c $_engulf_binary 2>/dev/null)
        if test (count $_engulf_native_spec) -eq 0; \
                and test ${source_marker} -eq 0; \
                and test -n "$_engulf_completion_source"; \
                and type -q $_engulf_completion_source
            set -g {source_marker} 1
            command $_engulf_completion_source completion fish 2>/dev/null \
                | source 2>/dev/null
            set _engulf_native_spec (complete -c $_engulf_binary 2>/dev/null)
            if test $_engulf_normalized_index -ge 0
                set _engulf_native_replies (complete -C "$_engulf_line" 2>/dev/null)
            end
        end
        if test (count $_engulf_native_spec) -gt 0
            set _engulf_native 1
        end
    end

    if test (count $_engulf_native_replies) -gt 0
        printf '%s\\n' $_engulf_native_replies
    end
    if test $_engulf_native -eq 0
        printf '%s\\n' $_engulf_binary_candidates
    end
    printf '%s\\n' $_engulf_extra
end

complete -c {command_literal} -f -a '({helper_name})'
"""


def _identifier_suffix(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _ensure_current_word(words: tuple[str, ...], cursor_index: int) -> tuple[str, ...]:
    if cursor_index < 0:
        raise ValueError("completion cursor index cannot be negative")
    expanded = list(words)
    while len(expanded) <= cursor_index:
        expanded.append("")
    return tuple(expanded)


def _write_nul_records(records: Iterable[str]) -> None:
    output = sys.stdout.buffer
    for record in records:
        if not isinstance(record, str):
            raise TypeError("internal completion records must be strings")
        output.write(os.fsencode(record))
        output.write(b"\0")
    output.flush()


def _write_context_records(
    normalized_cursor: int,
    normalized: tuple[str, ...],
    wrapper_candidates: tuple[CompletionCandidate, ...],
    binary_candidates: tuple[CompletionCandidate, ...],
) -> None:
    records = (
        str(normalized_cursor),
        str(len(normalized)),
        *normalized,
        str(len(wrapper_candidates)),
        *(candidate.value for candidate in wrapper_candidates),
        str(len(binary_candidates)),
        *(candidate.value for candidate in binary_candidates),
        "ENGULF_CONTEXT_END",
    )
    _write_nul_records(records)
