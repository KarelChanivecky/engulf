from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from engulf_executable_wrapper_api import Shell

from .completion import render_completion_script


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engulf-completion",
        description="Generate shell completion for an Engulf-based wrapper.",
    )
    parser.add_argument("shell", choices=[shell.value for shell in Shell])
    parser.add_argument("wrapper", help="Wrapper command name or path")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write to this file instead of standard output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = os.environ.copy()
    environment.update(
        {
            "ENGULF_INTERNAL_PROTOCOL": "1",
            "ENGULF_INTERNAL_ACTION": "describe",
        }
    )
    try:
        result = subprocess.run(
            [args.wrapper],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        print(f"engulf-completion: cannot run {args.wrapper}: {error}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        print(
            f"engulf-completion: wrapper inspection failed: {detail}", file=sys.stderr
        )
        return 1
    try:
        description = json.loads(result.stdout)
        if not isinstance(description, dict):
            raise TypeError("wrapper description must be a JSON object")
        binary_service = description["completion_service"]
        if not isinstance(binary_service, str):
            raise TypeError("completion_service must be a string")
        if not binary_service or "\0" in binary_service:
            raise ValueError("completion_service must be nonempty and contain no NUL")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(
            f"engulf-completion: invalid wrapper description: {error}", file=sys.stderr
        )
        return 1

    script = render_completion_script(Shell(args.shell), args.wrapper, binary_service)
    if args.output is None:
        sys.stdout.write(script)
    else:
        args.output.write_text(script, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
