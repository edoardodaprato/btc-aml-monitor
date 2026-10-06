"""Tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from btc_aml import __version__
from btc_aml.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_show_config_lists_all_rules(config_dir: Path) -> None:
    result = runner.invoke(app, ["show-config", "--config-dir", str(config_dir)])

    assert result.exit_code == 0
    assert "Configuration OK" in result.output
    assert "R01_OFAC_DIRECT" in result.output
    assert "R16_CONSOLIDATION" in result.output


def test_show_config_reports_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["show-config", "--config-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Configuration error" in result.output
