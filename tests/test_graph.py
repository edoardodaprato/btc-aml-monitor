"""Tests for change detection, clustering, multi-hop exposure and the rules built on them."""

from __future__ import annotations

import dataclasses
from typing import Any

from btc_aml.config import ExposureConfig
from btc_aml.data_sources.esplora import AddressHistory
from btc_aml.graph.change import detect_change
from btc_aml.graph.clustering import address_cluster
from btc_aml.graph.exposure import compute_exposure
from btc_aml.model import Direction, Transaction
from btc_aml.rules.r02_ofac_indirect import OfacIndirectExposure
from btc_aml.rules.r17_address_hopping import AddressHopping
from btc_aml.rules.r20_round_trip import RoundTrip
from tests.rule_helpers import (
    BTC,
    COINJOIN,
    DAY,
    HOUR,
    T0,
    FakeChain,
    context,
    make_rule,
    profile,
    raw_tx,
    screener,
    tx,
)

A = "A"
EXPOSURE = ExposureConfig(
    max_hops=2,
    hop_decay=(1.0, 0.5, 0.25),
    max_tx_per_address=200,
    max_tx_per_expanded_address=50,
    max_addresses_per_hop=20,
    min_carried_share=0.001,
    max_analysis_seconds=600,
    high_degree_threshold=1000,
)


def typed_raw(inputs, outputs, input_type="v0_p2wpkh", output_types=None, **kwargs) -> dict:
    raw = raw_tx(inputs, outputs, **kwargs)
    for vin in raw["vin"]:
        vin["prevout"]["scriptpubkey_type"] = input_type
    for vout, script_type in zip(raw["vout"], output_types or [], strict=False):
        vout["scriptpubkey_type"] = script_type
    return raw


# --- change detection ------------------------------------------------------------------


def test_change_by_address_reuse() -> None:
    t = tx([(A, BTC)], [("shop", 30_000_000), (A, 69_999_000)])
    guess = detect_change(t)
    assert (guess.output.address, guess.heuristic) == (A, "address reuse")


def test_change_by_script_type() -> None:
    raw = typed_raw(
        [(A, BTC)],
        [("shop", 30_000_000), ("fresh", 69_999_000)],
        output_types=["p2pkh", "v0_p2wpkh"],
    )
    guess = detect_change(Transaction.from_esplora(raw))
    assert (guess.output.address, guess.heuristic) == ("fresh", "script type matches inputs")


def test_change_by_non_round_amount() -> None:
    t = tx([(A, BTC)], [("shop", 25_000_000), ("fresh", 74_987_654)])
    assert detect_change(t).output.address == "fresh"


def test_ambiguous_change_is_not_guessed() -> None:
    t = tx([(A, BTC)], [("x", 31_234_567), ("y", 68_764_433)])
    assert detect_change(t) is None


# --- clustering ------------------------------------------------------------------------


def test_cluster_links_co_spent_inputs_and_change() -> None:
    spend = tx([(A, BTC), ("B", BTC)], [("shop", 50_000_000), ("C", 149_987_654)])
    cluster = address_cluster(A, [spend], COINJOIN)
    assert cluster == {"A", "B", "C"}


def test_cluster_ignores_coinjoin_and_received_payments() -> None:
    coinjoin = Transaction.from_esplora(
        raw_tx(
            [(A, 10_000_500)] + [(f"u{i}", 10_000_500) for i in range(5)],
            [(f"o{i}", 10_000_000) for i in range(6)],
        )
    )
    received = tx(
        [("payer", BTC), ("payer2", BTC)], [(A, 12_345_678), ("payer_change", 187_653_322)]
    )
    assert address_cluster(A, [coinjoin, received], COINJOIN) == {A}


# --- multi-hop exposure ----------------------------------------------------------------


class FakeSource:
    def __init__(self) -> None:
        self.histories: dict[str, list[dict[str, Any]]] = {}
        self.tx_counts: dict[str, int] = {}

    def add(self, raw: dict[str, Any]) -> Transaction:
        for address in {v["prevout"]["scriptpubkey_address"] for v in raw["vin"]} | {
            o["scriptpubkey_address"] for o in raw["vout"]
        }:
            self.histories.setdefault(address, []).append(raw)
        return Transaction.from_esplora(raw, 50_000.0)

    def get_address_stats(self, address: str) -> dict[str, Any]:
        count = self.tx_counts.get(address, len(self.histories.get(address, [])))
        return {"chain_stats": {"tx_count": count}}

    def get_address_history(self, address: str, max_txs: int) -> AddressHistory:
        return AddressHistory(address, self.histories.get(address, [])[:max_txs], False)


def indirect_scenario(sanctioned_pays_before: bool = True):
    """SANCTIONED -> C (1 BTC) and CLEAN -> C (3 BTC); then C -> A (2 BTC)."""
    source = FakeSource()
    t_sanctioned = T0 if sanctioned_pays_before else T0 + 10 * DAY
    source.add(raw_tx([("SANCTIONED", BTC + 1_000)], [("C", BTC)], time=t_sanctioned))
    source.add(raw_tx([("CLEAN", 3 * BTC + 1_000)], [("C", 3 * BTC)], time=T0 + HOUR))
    payment = source.add(raw_tx([("C", 2 * BTC + 1_000)], [(A, 2 * BTC)], time=T0 + DAY))
    return source, profile(A, [payment])


def test_indirect_sanctions_exposure_is_attributed_pro_rata() -> None:
    source, prof = indirect_scenario()
    result = compute_exposure(prof, frozenset({A}), screener(("SANCTIONED",)), source, EXPOSURE)

    [hit] = result.hits
    assert (hit.address, hit.hop, hit.direction) == ("SANCTIONED", 2, Direction.IN)
    assert hit.amount_sats == BTC // 2  # C got 25% of its inflows from SANCTIONED; 25% x 2 BTC
    assert hit.path == (A, "C", "SANCTIONED")


def test_funds_received_after_the_payment_do_not_count() -> None:
    source, prof = indirect_scenario(sanctioned_pays_before=False)
    result = compute_exposure(prof, frozenset({A}), screener(("SANCTIONED",)), source, EXPOSURE)
    assert result.hits == []


def test_high_degree_counterparty_is_not_expanded() -> None:
    source, prof = indirect_scenario()
    source.tx_counts["C"] = 5_000
    result = compute_exposure(prof, frozenset({A}), screener(("SANCTIONED",)), source, EXPOSURE)

    assert result.hits == []
    assert result.high_degree_nodes == {"C"}


def test_round_trip_is_detected() -> None:
    source = FakeSource()
    out = source.add(raw_tx([(A, 2 * BTC)], [("C", 2 * BTC - 1_000)], time=T0))
    back = source.add(raw_tx([("C", 2 * BTC - 1_000)], [(A, 2 * BTC - 2_000)], time=T0 + HOUR))
    result = compute_exposure(profile(A, [out, back]), frozenset({A}), screener(), source, EXPOSURE)

    assert [trip.path for trip in result.round_trips] == [(A, "C", A)]


def test_per_hop_cap_marks_result_incomplete() -> None:
    source = FakeSource()
    payments = [
        source.add(raw_tx([(f"P{i}", BTC + 1_000)], [(A, BTC)], time=T0 + i)) for i in range(3)
    ]
    config = dataclasses.replace(EXPOSURE, max_addresses_per_hop=2)
    result = compute_exposure(profile(A, payments), frozenset({A}), screener(), source, config)

    assert not result.complete
    assert "expanded 2 of 3" in result.notes[0]


def test_time_budget_stops_the_search() -> None:
    source, prof = indirect_scenario()
    ticks = iter([0.0, 10_000.0])
    result = compute_exposure(
        prof, frozenset({A}), screener(("SANCTIONED",)), source, EXPOSURE, clock=lambda: next(ticks)
    )
    assert not result.complete
    assert "time budget" in result.notes[0]


# --- rules on top of the graph ---------------------------------------------------------


def test_r02_alert_has_decayed_strength() -> None:
    source, prof = indirect_scenario()
    scr = screener(("SANCTIONED",))
    exposure = compute_exposure(prof, frozenset({A}), scr, source, EXPOSURE)
    ctx = dataclasses.replace(context(prof, scr), exposure=exposure)

    [alert] = make_rule(OfacIndirectExposure).evaluate(ctx)

    assert (alert.hop_distance, alert.strength) == (2, 0.5)
    assert "2 hops away" in alert.explanation


def test_r20_round_trip_alert() -> None:
    source = FakeSource()
    out = source.add(raw_tx([(A, 2 * BTC)], [("C", 2 * BTC - 1_000)], time=T0))
    back = source.add(raw_tx([("C", 2 * BTC - 1_000)], [(A, 2 * BTC - 2_000)], time=T0 + HOUR))
    prof = profile(A, [out, back])
    exposure = compute_exposure(prof, frozenset({A}), screener(), source, EXPOSURE)

    [alert] = make_rule(RoundTrip).evaluate(dataclasses.replace(context(prof), exposure=exposure))
    assert "circular path" in alert.explanation


def build_hops(chain: FakeChain, hops: int) -> Transaction:
    """A pays H0; each Hi forwards 99% to H(i+1) one hour later."""
    value = 5 * BTC
    first = chain.add(raw_tx([(A, value + 10_000)], [("H0", value), (A, 9_000)], time=T0))
    previous, holder = first, "H0"
    for i in range(hops):
        value -= 50_000
        raw = chain.add(
            raw_tx([(holder, value + 50_000)], [(f"H{i + 1}", value)], time=T0 + (i + 1) * HOUR)
        )
        index = 0
        chain.outspends[previous["txid"]] = [{"spent": False}] * len(previous["vout"])
        chain.outspends[previous["txid"]][index] = {"spent": True, "txid": raw["txid"]}
        previous, holder = raw, f"H{i + 1}"
    return Transaction.from_esplora(first, 50_000.0)


def test_r17_chain_of_single_use_addresses() -> None:
    chain = FakeChain()
    start = build_hops(chain, hops=3)
    ctx = dataclasses.replace(context(profile(A, [start]), chain=chain), cluster=frozenset({A}))

    [alert] = make_rule(AddressHopping).evaluate(ctx)
    assert "3 hops" in alert.explanation


def test_r17_reused_intermediate_breaks_the_chain() -> None:
    chain = FakeChain()
    start = build_hops(chain, hops=3)
    chain.tx_counts["H1"] = 40  # an address with history is not a single-use hop
    ctx = dataclasses.replace(context(profile(A, [start]), chain=chain), cluster=frozenset({A}))

    assert make_rule(AddressHopping).evaluate(ctx) == []
