"""Tests for CLI --allow-undocumented flag."""

from typer.testing import CliRunner

from dsm2emp.cli import app

runner = CliRunner()
# Force a wide terminal so Rich does not truncate the option column.
HELP_ENV = {"COLUMNS": "120"}


def test_cli_migrate_help_has_allow_undocumented() -> None:
    result = runner.invoke(app, ["migrate", "--help"], env=HELP_ENV)
    assert result.exit_code == 0
    assert "--allow-undocumented" in result.output


def test_cli_batch_help_has_allow_undocumented() -> None:
    result = runner.invoke(app, ["batch", "--help"], env=HELP_ENV)
    assert result.exit_code == 0
    assert "--allow-undocumented" in result.output
