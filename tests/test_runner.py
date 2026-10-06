"""End-to-end test of address mode: input file -> CSV reports + audit log (offline)."""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from btc_aml.config import AppConfig
from btc_aml.data_sources.ofac import update_ofac_list
from btc_aml.reports.csv_export import ADDRESS_SCORES_COLUMNS, ALERTS_COLUMNS, TRANSACTIONS_COLUMNS
from btc_aml.runner import read_address_file, run_address_mode
from btc_aml.services import Services
from tests.conftest import FIXTURE_ADDRESS, FIXTURE_ADDRESS_TX_COUNT, FIXTURES, FakeEsplora


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def ofac(tmp_path: Path):
    xml = (FIXTURES / "ofac_sdn_sample.xml").read_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=xml))
    return update_ofac_list("https://ofac.test/SDN.XML", tmp_path / "ofac.json", transport)


def test_read_address_file_skips_comments_duplicates_and_invalid(tmp_path: Path) -> None:
    path = tmp_path / "in.txt"
    path.write_text(f"# demo\n\n{FIXTURE_ADDRESS}\nnot-an-address\n{FIXTURE_ADDRESS}\n")

    addresses, invalid = read_address_file(path)

    assert addresses == [FIXTURE_ADDRESS]
    assert invalid == {"not-an-address": "line 4: not a valid Bitcoin address"}


def test_address_mode_writes_reports_and_audit_log(
    app_config: AppConfig, fake_esplora: FakeEsplora, ofac, tmp_path: Path
) -> None:
    config = dataclasses.replace(app_config, output_dir=tmp_path / "output")
    input_path = tmp_path / "addresses.txt"
    input_path.write_text(f"{FIXTURE_ADDRESS}\nnot-an-address\n")

    with Services.from_config(config, transport=fake_esplora.transport()) as services:
        result = run_address_mode(input_path, config, services, ofac, labels=[])

    out = result.output_dir
    assert {p.name for p in out.iterdir()} == {
        "address_scores.csv",
        "alerts.csv",
        "transactions.csv",
        "audit_log.json",
        "run.log",
    }

    scores = read_csv(out / "address_scores.csv")
    assert tuple(scores[0]) == ADDRESS_SCORES_COLUMNS
    assert scores[0]["address"] == FIXTURE_ADDRESS
    assert scores[0]["tx_count"] == str(FIXTURE_ADDRESS_TX_COUNT)

    with (out / "alerts.csv").open(encoding="utf-8") as handle:
        assert tuple(next(csv.reader(handle))) == ALERTS_COLUMNS
    transactions = read_csv(out / "transactions.csv")
    assert tuple(transactions[0]) == TRANSACTIONS_COLUMNS
    assert len(transactions) == FIXTURE_ADDRESS_TX_COUNT

    audit = json.loads((out / "audit_log.json").read_text())
    assert audit["run_id"] == result.run_id
    assert audit["rules"]["config_hash"] == config.config_hash
    assert audit["sanctions_list"]["version"] == ofac.version
    assert audit["input"]["file"] == "addresses.txt"
    assert "not-an-address" in audit["results"]["addresses_skipped"]
    # Only file names are recorded, never absolute paths (privacy).
    assert str(tmp_path) not in (out / "audit_log.json").read_text()
