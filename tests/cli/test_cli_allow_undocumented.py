"""Tests for CLI --allow-undocumented flag."""

from typer.testing import CliRunner

from dsm2emp.cli import app

runner = CliRunner()


def test_cli_migrate_help_has_allow_undocumented() -> None:
    result = runner.invoke(app, ["migrate", "--help"])
    assert result.exit_code == 0
    assert "--allow-undocumented" in result.output


def test_cli_batch_help_has_allow_undocumented() -> None:
    result = runner.invoke(app, ["batch", "--help"])
    assert result.exit_code == 0
    assert "--allow-undocumented" in result.output
