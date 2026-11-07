"""Tests for DSM2Empirum CLI."""

from typer.testing import CliRunner

from dsm2emp import __version__
from dsm2emp.cli import app

runner = CliRunner()


def test_cli_version() -> None:
    """Test that --version displays version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_selftest() -> None:
    """Test the selftest command."""
    result = runner.invoke(app, ["selftest"])
    assert result.exit_code == 0
    assert "self-test: OK" in result.stdout
