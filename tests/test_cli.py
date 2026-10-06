"""Tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from btc_aml import __version__
from btc_aml.cli import app
from btc_aml.services import Services
from tests.conftest import FIXTURE_TXID, FakeEsplora

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


def test_fetch_tx_prints_summary_offline(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEsplora()
    original = Services.from_config
    monkeypatch.setattr(
        "btc_aml.cli.Services.from_config",
        lambda config: original(config, transport=fake.transport()),
    )
    monkeypatch.chdir(tmp_path)  # the relative cache path lands in the temp folder

    result = runner.invoke(app, ["fetch-tx", FIXTURE_TXID, "--config-dir", str(config_dir)])

    assert result.exit_code == 0, result.output
    assert "confirmed in block 960000" in result.output
    assert "BTC/EUR:      56,025" in result.output
