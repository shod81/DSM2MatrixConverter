"""Tests for the CLI --allow-undocumented flag.

The options are asserted on the command objects rather than on the rendered
help text: Rich's layout depends on the terminal width and on the installed
Typer version, which made a text-based assertion flaky in CI.
"""

from typing import Any

import typer

from dsm2emp.cli import app


def _option_flags(command_name: str) -> set[str]:
    root: Any = typer.main.get_command(app)
    command: Any = root.commands[command_name]
    return {opt for param in command.params for opt in getattr(param, "opts", [])}


def test_cli_migrate_has_allow_undocumented() -> None:
    assert "--allow-undocumented" in _option_flags("migrate")


def test_cli_batch_has_allow_undocumented() -> None:
    assert "--allow-undocumented" in _option_flags("batch")
