"""Tests for block-scan mode: single-transaction checks, block clustering, runner (offline)."""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from btc_aml.block_scan import BlockInfo, BlockScanner
from btc_aml.config import AppConfig
from btc_aml.data_sources.price import PriceQuote
from btc_aml.reports.csv_export import BLOCK_ALERTS_COLUMNS, BLOCKS_COLUMNS
from btc_aml.runner import BlockRangeError, run_block_mode
from btc_aml.services import Services
from tests.rule_helpers import BTC, T0, ofac_list, raw_tx, screener

BLOCK = BlockInfo(
    height=800_000,
    block_hash="blockhash",
    timestamp=T0,
    tx_count=0,
    median_fee_rate=5.0,
    price=PriceQuote(50_000.0, "2023-11-14", "test"),
)


def coinbase(value: int = 625_000_000) -> dict[str, Any]:
    raw = raw_tx([("unused", 0)], [("miner", value)])
    raw["vin"] = [{"txid": "0" * 64, "vout": 4294967295, "is_coinbase": True, "prevout": None}]
    return raw


def scan(config: AppConfig, txs: list[dict[str, Any]], **screen: Any):
    return BlockScanner(config, screener(**screen)).scan(BLOCK, [coinbase(), *txs])


def rule_ids(report) -> list[str]:
    return sorted(f.rule_id for f in report.findings)


def test_ordinary_payment_raises_nothing(app_config: AppConfig) -> None:
    report = scan(app_config, [raw_tx([("A", BTC)], [("shop", 30_000_000), ("A", 69_999_000)])])
    assert report.findings == []
    assert len(report.txs) == 2


def test_sanctioned_recipient_is_flagged(app_config: AppConfig) -> None:
    payment = raw_tx([("A", BTC)], [("SANCTIONED", 30_000_000), ("A", 69_999_000)])
    report = scan(app_config, [payment], sanctioned=("SANCTIONED",))

    [finding] = report.findings
    assert finding.rule_id == "R01_OFAC_DIRECT"
    assert finding.addresses == ("SANCTIONED",)
    assert finding.amount_eur == pytest.approx(15_000)
    assert "receives" in finding.explanation
    assert report.addresses_for_review == {"SANCTIONED"}


def test_labelled_address_is_flagged_by_category(app_config: AppConfig) -> None:
    payment = raw_tx([("MIXER", BTC)], [("B", 99_999_000)])
    report = scan(app_config, [payment], labels={"MIXER": "mixer"})
    assert rule_ids(report) == ["R03_HIGH_RISK_CATEGORY"]


def test_coinjoin_is_flagged_and_not_treated_as_fan_out_or_consolidation(
    app_config: AppConfig,
) -> None:
    mix = raw_tx(
        [(f"u{i}", 1_000_500) for i in range(25)], [(f"o{i}", 1_000_000) for i in range(25)]
    )
    assert rule_ids(scan(app_config, [mix])) == ["R04_COINJOIN"]


def test_fan_out_to_many_recipients(app_config: AppConfig) -> None:
    batch = raw_tx([("A", 30 * BTC)], [(f"r{i}", BTC + i) for i in range(20)])
    report = scan(app_config, [batch])
    assert "R09_FAN_OUT" in rule_ids(report)


def test_large_transaction_excludes_change(app_config: AppConfig) -> None:
    big = raw_tx([("A", 3 * BTC)], [("shop", 250_000_000), ("fresh", 49_987_654)])
    small = raw_tx([("B", 3 * BTC)], [("shop", 150_000_000), ("fresh", 149_987_654)])
    report = scan(app_config, [big, small])

    [finding] = report.findings
    assert finding.rule_id == "R14_LARGE_TRANSACTION"
    assert finding.amount_sats == 250_000_000
    assert "excluding change" in finding.explanation


def test_consolidation_of_small_inputs(app_config: AppConfig) -> None:
    sweep = raw_tx([(f"s{i}", 500_000) for i in range(20)], [("vault", 9_990_000)])
    assert rule_ids(scan(app_config, [sweep])) == ["R16_CONSOLIDATION"]


def test_anomalous_fee_against_block_median(app_config: AppConfig) -> None:
    rushed = raw_tx([("A", BTC)], [("B", 99_900_000)], fee=100_000)  # 400 sat/vB vs 5
    [finding] = scan(app_config, [rushed]).findings
    assert finding.rule_id == "R21_ANOMALOUS_FEE"
    assert "80x" in finding.explanation


def test_block_clustering_links_addresses_to_a_sanctioned_one(app_config: AppConfig) -> None:
    # SANCTIONED and X spend together; X and Y spend together in another transaction.
    first = raw_tx([("SANCTIONED", BTC), ("X", BTC)], [("shop", 199_999_000)])
    second = raw_tx([("X", BTC), ("Y", BTC)], [("shop2", 199_999_000)])
    report = scan(app_config, [first, second], sanctioned=("SANCTIONED",))

    [co_spend] = [f for f in report.findings if f.rule_id == "R19_CO_SPENDING_FLAGGED"]
    assert co_spend.addresses == ("X", "Y")
    assert set(co_spend.txids) == {first["txid"], second["txid"]}
    assert report.addresses_for_review == {"SANCTIONED", "X", "Y"}


def test_disabled_rule_is_not_applied(app_config: AppConfig) -> None:
    rules = dict(app_config.rules)
    rules["R16_CONSOLIDATION"] = dataclasses.replace(rules["R16_CONSOLIDATION"], enabled=False)
    config = dataclasses.replace(app_config, rules=rules)
    sweep = raw_tx([(f"s{i}", 500_000) for i in range(20)], [("vault", 9_990_000)])

    scanner = BlockScanner(config, screener())
    assert scanner.scan(BLOCK, [sweep]).findings == []
    assert "R16_CONSOLIDATION" not in scanner.enabled_rules


# --- runner and API client --------------------------------------------------------------


class FakeChainApi:
    """Serves a two-block chain through the Esplora block endpoints."""

    def __init__(self, txs_per_block: int = 30) -> None:
        self.requests: list[str] = []
        self.blocks: dict[int, list[dict[str, Any]]] = {}
        for height in (100, 101):
            txs = [coinbase()] + [
                raw_tx([(f"a{height}_{i}", BTC)], [(f"b{height}_{i}", 99_999_000)])
                for i in range(txs_per_block - 1)
            ]
            self.blocks[height] = txs

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        self.requests.append(path)
        if path == "/blocks/tip/height":
            return httpx.Response(200, text="101")
        if path.startswith("/block-height/"):
            height = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, text=f"hash{height}") if height in self.blocks else _404()
        if path.startswith("/v1/block/"):
            return httpx.Response(200, json={"extras": {"feeRange": [1, 2, 3, 4, 5, 6, 7]}})
        if path.startswith("/block/hash"):
            parts = path.split("/")
            height = int(parts[2].removeprefix("hash"))
            txs = self.blocks[height]
            if len(parts) == 3:
                return httpx.Response(
                    200, json={"height": height, "timestamp": T0, "tx_count": len(txs)}
                )
            start = int(parts[4])
            return httpx.Response(200, json=txs[start : start + 25])
        if path == "/v1/historical-price":
            return httpx.Response(200, json={"prices": [{"time": T0, "EUR": 50_000, "USD": 0}]})
        return _404()


def _404() -> httpx.Response:
    return httpx.Response(404, text="Not found")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def block_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
    return dataclasses.replace(app_config, output_dir=tmp_path / "output")


def test_block_txs_are_paginated_and_cached(block_config: AppConfig) -> None:
    api = FakeChainApi(txs_per_block=30)
    transport = httpx.MockTransport(api.handler)
    with Services.from_config(block_config, transport=transport) as services:
        first = services.esplora.get_block_txs("hash100", 30)
        second = services.esplora.get_block_txs("hash100", 30)

    assert [tx["txid"] for tx in first] == [tx["txid"] for tx in api.blocks[100]]
    assert first == second
    assert api.requests == ["/block/hash100/txs/0", "/block/hash100/txs/25"]


def test_block_mode_writes_reports_and_audit_log(block_config: AppConfig) -> None:
    api = FakeChainApi()
    with Services.from_config(block_config, transport=httpx.MockTransport(api.handler)) as services:
        result = run_block_mode(100, 101, block_config, services, ofac_list(), labels=[])

    out = result.output_dir
    assert {p.name for p in out.iterdir()} == {
        "blocks.csv",
        "block_alerts.csv",
        "addresses_for_review.txt",
        "audit_log.json",
        "run.log",
    }
    blocks = read_csv(out / "blocks.csv")
    assert tuple(blocks[0]) == BLOCKS_COLUMNS
    assert [(b["block_height"], b["tx_count"], b["median_fee_rate_sat_vb"]) for b in blocks] == [
        ("100", "30", "4.00"),
        ("101", "30", "4.00"),
    ]
    with (out / "block_alerts.csv").open(encoding="utf-8") as handle:
        assert tuple(next(csv.reader(handle))) == BLOCK_ALERTS_COLUMNS

    audit = json.loads((out / "audit_log.json").read_text())
    assert audit["mode"] == "blocks"
    assert audit["results"]["blocks_scanned"] == [100, 101]
    assert audit["results"]["transactions_scanned"] == 60
    assert "R01_OFAC_DIRECT" in audit["results"]["rules_applied"]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [(5, 4, "Invalid block range"), (0, 10, "limit is 10"), (101, 102, "does not exist yet")],
)
def test_invalid_block_ranges_are_rejected(
    block_config: AppConfig, start: int, end: int, message: str
) -> None:
    transport = httpx.MockTransport(FakeChainApi().handler)
    with (
        Services.from_config(block_config, transport=transport) as services,
        pytest.raises(BlockRangeError, match=message),
    ):
        run_block_mode(start, end, block_config, services, ofac_list(), labels=[])


def test_large_cluster_is_flagged_as_likely_custodial(app_config: AppConfig) -> None:
    sweep = raw_tx(
        [("SANCTIONED", BTC)] + [(f"d{i:02d}", BTC) for i in range(60)], [("hot", 60 * BTC)]
    )
    report = scan(app_config, [sweep], sanctioned=("SANCTIONED",))

    [co_spend] = [f for f in report.findings if f.rule_id == "R19_CO_SPENDING_FLAGGED"]
    assert "custodial service" in co_spend.explanation
    assert report.addresses_for_review == {"SANCTIONED"}
    assert len(report.large_cluster_addresses) == 60
