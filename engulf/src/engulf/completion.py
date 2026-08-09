from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
import traceback
from collections.abc import Iterable
from pathlib import Path

from engulf_api import (
    ArgumentRegistry,
    CompletionCallable,
    CompletionCandidate,
    CompletionContext,
    CompletionProvider,
    Shell,
    invoke_provider,
    normalize_candidate,
)

from .wrapper import FRAMEWORK_ERROR_EXIT, Engulf


def handle_internal_protocol(engulf: Engulf, argv: tuple[str, ...]) -> int:
    action = os.environ.get("ENGULF_INTERNAL_ACTION")
    try:
        if action == "describe":
            json.dump(
                {
                    "binary": engulf.binary,
                    "completion_service": Path(engulf.binary).name,
                },
                sys.stdout,
            )
            sys.stdout.write("\n")
            return 0

        shell = Shell(os.environ["ENGULF_INTERNAL_SHELL"])
        cursor_index = int(os.environ["ENGULF_INTERNAL_CWORD"])
        words = _ensure_current_word(argv, cursor_index)

        if action == "normalize":
            normalized, normalized_cursor = normalize_for_binary(
                engulf.arguments, words, cursor_index
            )
            _write_nul_records((str(normalized_cursor), *normalized))
            return 0

        if action == "complete":
            context = CompletionContext(
                shell=shell,
                wrapper_command=os.environ.get("ENGULF_INTERNAL_WRAPPER_COMMAND", ""),
                binary=engulf.binary,
                words=words,
                cursor_index=cursor_index,
            )
            native_available = os.environ.get("ENGULF_INTERNAL_NATIVE") == "1"
            candidates = collect_candidates(
                engulf,
                context,
                include_binary_provider=not native_available,
            )
            _write_nul_records(candidate.value for candidate in candidates)
            return 0

        raise ValueError(f"unsupported internal action: {action!r}")
    except Exception as error:  # noqa: BLE001 - completion must not leak plugin failures.
        if os.environ.get("ENGULF_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            print(f"engulf: completion failed: {error}", file=sys.stderr)
        return FRAMEWORK_ERROR_EXIT


def collect_candidates(
    engulf: Engulf,
    context: CompletionContext,
    *,
    include_binary_provider: bool,
) -> tuple[CompletionCandidate, ...]:
    candidates: list[CompletionCandidate] = []

    if include_binary_provider and engulf.completion_provider is not None:
        candidates.extend(_provider_candidates(engulf.completion_provider, context))

    candidates.extend(_argument_candidates(engulf.arguments, context))
    candidates.extend(engulf.completions.static_candidates(context))
    for provider in engulf.completions.providers:
        candidates.extend(_provider_candidates(provider, context))

    deduplicated: list[CompletionCandidate] = []
    positions: dict[str, int] = {}
    for candidate in candidates:
        if not candidate.value.startswith(context.current):
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
    for spec in registry.options:
        if not spec.repeatable and _option_was_used(spec.names, prior_words):
            continue
        for name in spec.names:
            if name.startswith(current):
                suffix = "=" if spec.takes_value and name.startswith("--") else ""
                result.append(CompletionCandidate(name + suffix, spec.description))
    return result


def _provider_candidates(
    provider: CompletionCallable | CompletionProvider,
    context: CompletionContext,
) -> list[CompletionCandidate]:
    return [
        normalize_candidate(candidate)
        for candidate in invoke_provider(provider, context)
    ]


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
    hidden: set[int] = set()
    index = 0
    while index < len(words):
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
    return tuple(normalized), normalized_cursor


def render_completion_script(
    shell: Shell,
    wrapper_command: str,
    binary_service: str,
) -> str:
    if not wrapper_command or "\0" in wrapper_command:
        raise ValueError(
            "wrapper command must be a non-empty string without NUL characters"
        )
    if not binary_service or "\0" in binary_service:
        raise ValueError(
            "binary service must be a non-empty string without NUL characters"
        )
    if shell is Shell.BASH:
        return _render_bash(wrapper_command, binary_service)
    if shell is Shell.ZSH:
        return _render_zsh(wrapper_command, binary_service)
    raise ValueError(f"unsupported shell: {shell}")


def _render_bash(wrapper_command: str, binary_service: str) -> str:
    suffix = _identifier_suffix(wrapper_command)
    function_name = f"_engulf_complete_{suffix}"
    wrapper_literal = shlex.quote(wrapper_command)
    binary_literal = shlex.quote(binary_service)
    command_literal = shlex.quote(wrapper_command)
    return f"""# Generated by engulf-completion. Source this file after the wrapped command's completion.
{function_name}() {{
    local _engulf_wrapper={wrapper_literal}
    local _engulf_binary={binary_literal}
    local _engulf_arg_index=$((COMP_CWORD - 1))
    local -a _engulf_args=("${{COMP_WORDS[@]:1}}")
    if (( _engulf_arg_index >= ${{#_engulf_args[@]}} )); then
        _engulf_args+=("")
    fi

    local -a _engulf_normalized=()
    mapfile -d '' -t _engulf_normalized < <(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=normalize \\
            ENGULF_INTERNAL_SHELL=bash ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
    )
    local _engulf_normalized_index=${{_engulf_normalized[0]:-$_engulf_arg_index}}
    local -a _engulf_binary_args=("${{_engulf_normalized[@]:1}}")
    if (( ${{#_engulf_normalized[@]}} == 0 )); then
        _engulf_binary_args=("${{_engulf_args[@]}}")
    fi

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

    local _engulf_native=0
    local -a _engulf_native_replies=()
    if [[ -n $_engulf_base_function ]] && declare -F "$_engulf_base_function" >/dev/null; then
        local -a _engulf_saved_words=("${{COMP_WORDS[@]}}")
        local _engulf_saved_cword=$COMP_CWORD
        local _engulf_saved_line=$COMP_LINE
        local _engulf_saved_point=$COMP_POINT
        COMP_WORDS=("$_engulf_binary" "${{_engulf_binary_args[@]}}")
        COMP_CWORD=$((_engulf_normalized_index + 1))
        printf -v COMP_LINE '%q ' "${{COMP_WORDS[@]}}"
        COMP_LINE=${{COMP_LINE% }}
        COMP_POINT=${{#COMP_LINE}}
        COMPREPLY=()
        "$_engulf_base_function" "$_engulf_binary" \\
            "${{COMP_WORDS[COMP_CWORD]-}}" "${{COMP_WORDS[COMP_CWORD-1]-}}" || true
        _engulf_native_replies=("${{COMPREPLY[@]}}")
        COMP_WORDS=("${{_engulf_saved_words[@]}}")
        COMP_CWORD=$_engulf_saved_cword
        COMP_LINE=$_engulf_saved_line
        COMP_POINT=$_engulf_saved_point
        _engulf_native=1
        local _engulf_option
        for _engulf_option in bashdefault default dirnames filenames noquote nosort nospace plusdirs; do
            if [[ " $_engulf_spec " == *" -o $_engulf_option "* ]]; then
                compopt -o "$_engulf_option" 2>/dev/null || true
            fi
        done
    fi

    local -a _engulf_extra=()
    mapfile -d '' -t _engulf_extra < <(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=complete \\
            ENGULF_INTERNAL_SHELL=bash ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_NATIVE="$_engulf_native" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
    )

    COMPREPLY=()
    local -A _engulf_seen=()
    local _engulf_candidate
    for _engulf_candidate in "${{_engulf_native_replies[@]}}" "${{_engulf_extra[@]}}"; do
        [[ -n $_engulf_candidate ]] || continue
        [[ -n ${{_engulf_seen["$_engulf_candidate"]+present}} ]] && continue
        _engulf_seen["$_engulf_candidate"]=1
        COMPREPLY+=("$_engulf_candidate")
    done
}}

complete -F {function_name} {command_literal}
"""


def _render_zsh(wrapper_command: str, binary_service: str) -> str:
    suffix = _identifier_suffix(wrapper_command)
    helper_name = f"_engulf_complete_{suffix}"
    wrapper_literal = shlex.quote(wrapper_command)
    binary_literal = shlex.quote(binary_service)
    command_literal = shlex.quote(wrapper_command)
    return f"""#compdef {command_literal}
# Generated by engulf-completion. Load with compinit or source after compinit.
{helper_name}() {{
    local _engulf_wrapper={wrapper_literal}
    local _engulf_binary={binary_literal}
    local _engulf_arg_index=$((CURRENT - 2))
    local -a _engulf_args
    _engulf_args=("${{(@)words[2,-1]}}")
    if (( _engulf_arg_index >= ${{#_engulf_args}} )); then
        _engulf_args+=("")
    fi

    local -a _engulf_normalized
    _engulf_normalized=("${{(@0)$(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=normalize \\
            ENGULF_INTERNAL_SHELL=zsh ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
        )}}")
    if (( ${{#_engulf_normalized}} )) && [[ -z ${{_engulf_normalized[-1]}} ]]; then
        _engulf_normalized[-1]=()
    fi
    local _engulf_normalized_index=${{_engulf_normalized[1]:-$_engulf_arg_index}}
    local -a _engulf_binary_args
    _engulf_binary_args=("${{(@)_engulf_normalized[2,-1]}}")
    if (( ${{#_engulf_normalized}} == 0 )); then
        _engulf_binary_args=("${{_engulf_args[@]}}")
    fi

    local _engulf_native=0
    local _engulf_base_function=""
    if (( $+_comps )); then
        _engulf_base_function=${{_comps[$_engulf_binary]-}}
    fi
    if [[ -n $_engulf_base_function && $_engulf_base_function != {helper_name} ]]; then
        (( $+functions[$_engulf_base_function] )) || autoload -Uz "$_engulf_base_function"
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
        _engulf_native=1
    fi

    local -a _engulf_extra
    _engulf_extra=("${{(@0)$(
        command env ENGULF_INTERNAL_PROTOCOL=1 ENGULF_INTERNAL_ACTION=complete \\
            ENGULF_INTERNAL_SHELL=zsh ENGULF_INTERNAL_CWORD="$_engulf_arg_index" \\
            ENGULF_INTERNAL_NATIVE="$_engulf_native" \\
            ENGULF_INTERNAL_WRAPPER_COMMAND="$_engulf_wrapper" \\
            "$_engulf_wrapper" "${{_engulf_args[@]}}" 2>/dev/null
        )}}")
    if (( ${{#_engulf_extra}} )) && [[ -z ${{_engulf_extra[-1]}} ]]; then
        _engulf_extra[-1]=()
    fi
    (( ${{#_engulf_extra}} )) && compadd -- "${{_engulf_extra[@]}}"
}}

if [[ -n ${{CURRENT-}} ]] && (( ${{#words}} )); then
    {helper_name} "$@"
elif (( $+functions[compdef] )); then
    compdef {helper_name} {command_literal}
fi
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
