"""Builders for synthetic transactions used in rule tests.

Addresses here are placeholder strings ("A", "sender_1"...), not real Bitcoin addresses:
rules do not validate formats, and fictitious data must never look like a real attribution.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from btc_aml.config import CoinJoinConfig, load_config
from btc_aml.data_sources.labels import Label
from btc_aml.data_sources.ofac import OfacList, SanctionedAddress
from btc_aml.model import AddressProfile, Transaction
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.screening import Screener

PROJECT_CONFIG = Path(__file__).resolve().parent.parent / "config"
T0 = 1_700_000_000  # 2023-11-14
HOUR = 3600
DAY = 86_400
BTC = 100_000_000
PRICE = 50_000.0  # EUR per BTC used by default in synthetic transactions
COINJOIN = CoinJoinConfig(min_equal_outputs=5, min_distinct_inputs=5)

_counter = iter(range(1, 1_000_000))


def raw_tx(
    inputs: list[tuple[str, int]],
    outputs: list[tuple[str, int]],
    time: int = T0,
    txid: str | None = None,
    fee: int = 1_000,
    weight: int = 1_000,
    block_hash: str = "block",
) -> dict[str, Any]:
    """Esplora-shaped JSON for a confirmed transaction."""
    txid = txid or f"tx{next(_counter):06d}"
    return {
        "txid": txid,
        "vin": [
            {
                "txid": f"prev_{txid}_{i}",
                "vout": 0,
                "prevout": {"scriptpubkey_address": address, "value": value},
            }
            for i, (address, value) in enumerate(inputs)
        ],
        "vout": [{"scriptpubkey_address": address, "value": value} for address, value in outputs],
        "fee": fee,
        "weight": weight,
        "status": {
            "confirmed": True,
            "block_height": 800_000 + (time - T0) // 600,
            "block_hash": block_hash,
            "block_time": time,
        },
    }


def tx(
    inputs: list[tuple[str, int]],
    outputs: list[tuple[str, int]],
    time: int = T0,
    price: float | None = PRICE,
    **kwargs: Any,
) -> Transaction:
    return Transaction.from_esplora(raw_tx(inputs, outputs, time, **kwargs), price)


def profile(address: str, txs: list[Transaction], truncated: bool = False) -> AddressProfile:
    ordered = sorted(txs, key=lambda t: (t.block_time or 0, t.txid))
    return AddressProfile(
        address=address,
        txs=tuple(ordered),
        tx_count_total=len(txs),
        total_received_sats=sum(t.received_by(address) for t in txs),
        total_sent_sats=sum(t.sent_by(address) for t in txs),
        truncated=truncated,
    )


def screener(sanctioned: tuple[str, ...] = (), labels: dict[str, str] | None = None) -> Screener:
    ofac = OfacList(
        publish_date="2026-01-01",
        downloaded_at="2026-01-01T00:00:00+00:00",
        source_url="test",
        sha256="0" * 64,
        record_count=len(sanctioned),
        addresses={
            a: (SanctionedAddress(a, "1", "TEST ENTITY", ("TEST-PROGRAM",)),) for a in sanctioned
        },
    )
    label_list = [
        Label(address, category, "test fixture", "2026-01-01")
        for address, category in (labels or {}).items()
    ]
    return Screener(ofac, label_list)


class FakeChain:
    """ChainReader backed by dictionaries."""

    def __init__(self) -> None:
        self.txs: dict[str, dict[str, Any]] = {}
        self.outspends: dict[str, list[dict[str, Any]]] = {}
        self.median_fee: dict[str, float | None] = {}

    def add(self, raw: dict[str, Any]) -> dict[str, Any]:
        self.txs[raw["txid"]] = raw
        return raw

    def get_tx(self, txid: str) -> dict[str, Any]:
        return self.txs[txid]

    def get_outspends(self, txid: str) -> list[dict[str, Any]]:
        return self.outspends.get(txid, [{"spent": False}] * len(self.txs[txid]["vout"]))

    def get_block_median_fee_rate(self, block_hash: str) -> float | None:
        return self.median_fee.get(block_hash)


def context(
    prof: AddressProfile, scr: Screener | None = None, chain: FakeChain | None = None
) -> AnalysisContext:
    return AnalysisContext(prof, scr or screener(), chain or FakeChain(), COINJOIN)


def make_rule(rule_cls: type[Rule], **param_overrides: Any) -> Rule:
    """The rule with its default parameters from config/rules.yaml, optionally overridden."""
    base = load_config(PROJECT_CONFIG).rules[rule_cls.rule_id]
    return rule_cls(dataclasses.replace(base, params={**base.params, **param_overrides}))
