from __future__ import annotations

import argparse
from pathlib import Path
from typing import Never

from cryptography.fernet import Fernet, InvalidToken
from engulf_api import (
    Goal,
    GoalAPI,
    GoalContract,
    GoalRequirement,
    GoalResult,
    GoalSetupAPI,
    Invocation,
    Plugin,
)

ENCRYPTION_REQUIREMENT = GoalRequirement("org.engulf.example.encryption", 1)


class EncryptionPlugin(Plugin):
    """Extension point for plugins written specifically for this example goal."""

    goal_requirement = ENCRYPTION_REQUIREMENT


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(message)


class EncryptionGoal(Goal[Path]):
    """Generate keys and encrypt or decrypt files entirely in application code."""

    _contract = GoalContract(ENCRYPTION_REQUIREMENT, EncryptionPlugin)

    def __init__(self) -> None:
        self._display_name: str | None = None

    @property
    def contract(self) -> GoalContract:
        return self._contract

    def setup(self, api: GoalSetupAPI) -> None:
        self._display_name = api.display_name

    def achieve(
        self,
        invocation: Invocation,
        api: GoalAPI,
    ) -> GoalResult[Path]:
        assert self._display_name is not None
        try:
            arguments = _parser(self._display_name).parse_args(invocation.arguments)
        except ValueError as error:
            api.logger.error("invalid arguments: %s", error)
            return GoalResult.rejected(2, error=str(error))

        output = Path(arguments.output).expanduser()
        try:
            if arguments.command == "generate-key":
                output.write_bytes(Fernet.generate_key())
                output.chmod(0o600)
            else:
                key = Path(arguments.key).expanduser().read_bytes()
                payload = Path(arguments.input).expanduser().read_bytes()
                cipher = Fernet(key)
                transformed = (
                    cipher.encrypt(payload)
                    if arguments.command == "encrypt"
                    else cipher.decrypt(payload)
                )
                output.write_bytes(transformed)
        except (InvalidToken, OSError, ValueError) as error:
            api.logger.error("%s failed: %s", arguments.command, error)
            return GoalResult.failed(1, error=str(error))

        api.logger.info("wrote %s", output)
        return GoalResult.completed(output)


def _parser(display_name: str) -> _Parser:
    parser = _Parser(prog=display_name)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate-key")
    generate.add_argument("output")

    for name in ("encrypt", "decrypt"):
        command = commands.add_parser(name)
        command.add_argument("--key", required=True)
        command.add_argument("input")
        command.add_argument("output")
    return parser
