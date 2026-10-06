"""One positive and one negative scenario per red-flag rule (synthetic data, offline)."""

from __future__ import annotations

import pytest

from btc_aml.model import Transaction
from btc_aml.rules.r01_ofac_direct import OfacDirectExposure
from btc_aml.rules.r03_high_risk_category import HighRiskCategoryExposure
from btc_aml.rules.r04_coinjoin import CoinJoinParticipation
from btc_aml.rules.r05_peel_chain import PeelChain
from btc_aml.rules.r06_structuring import Structuring
from btc_aml.rules.r07_pass_through import PassThrough
from btc_aml.rules.r08_fan_in import FanIn
from btc_aml.rules.r09_fan_out import FanOut
from btc_aml.rules.r10_high_velocity import HighVelocity
from btc_aml.rules.r11_dormant_reactivation import DormantReactivation
from btc_aml.rules.r12_new_address_high_volume import NewAddressHighVolume
from btc_aml.rules.r13_round_amounts import RoundAmounts
from btc_aml.rules.r14_large_transaction import LargeTransaction
from btc_aml.rules.r15_dust import DustReceived
from btc_aml.rules.r16_consolidation import Consolidation
from btc_aml.rules.r18_post_coinjoin_consolidation import PostCoinJoinConsolidation
from btc_aml.rules.r19_co_spending_flagged import CoSpendingWithFlaggedAddress
from btc_aml.rules.r21_anomalous_fee import AnomalousFee
from tests.rule_helpers import (
    BTC,
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

A = "A"  # the analysed address


def coinjoin_raw(n: int = 6, value: int = 10_000_000, time: int = T0) -> dict:
    inputs = [(f"cj_in_{i}", value + 5_000) for i in range(n)]
    outputs = [(f"cj_out_{i}", value) for i in range(n)]
    return raw_tx(inputs, outputs, time)


# --- R01 / R03 / R19: list screening --------------------------------------------------


def test_r01_direct_payment_from_sanctioned_address() -> None:
    t = tx([("SANCTIONED", 2 * BTC)], [(A, BTC), ("SANCTIONED", BTC - 1_000)])
    alerts = make_rule(OfacDirectExposure).evaluate(
        context(profile(A, [t]), screener(sanctioned=("SANCTIONED",)))
    )

    assert len(alerts) == 1
    assert alerts[0].hop_distance == 1
    assert alerts[0].amount_sats == BTC
    assert "TEST ENTITY" in alerts[0].explanation


def test_r01_address_itself_sanctioned() -> None:
    t = tx([("x", BTC)], [(A, BTC - 1_000)])
    alerts = make_rule(OfacDirectExposure).evaluate(
        context(profile(A, [t]), screener(sanctioned=(A,)))
    )

    assert [a.hop_distance for a in alerts] == [0]


def test_r01_no_exposure() -> None:
    t = tx([("clean", BTC)], [(A, BTC - 1_000)])
    assert make_rule(OfacDirectExposure).evaluate(context(profile(A, [t]))) == []


def test_r03_counterparty_labelled_mixer() -> None:
    t = tx([(A, BTC)], [("MIXER", BTC - 1_000)])
    alerts = make_rule(HighRiskCategoryExposure).evaluate(
        context(profile(A, [t]), screener(labels={"MIXER": "mixer"}))
    )

    assert len(alerts) == 1
    assert "mixer" in alerts[0].explanation


def test_r03_ignores_negligible_exposure_and_low_risk_categories() -> None:
    big = tx([("x", 100 * BTC)], [(A, 100 * BTC - 1_000)])
    tiny = tx([(A, 10_000)], [("MIXER", 9_000)], time=T0 + DAY)
    exchange = tx([(A, BTC)], [("EXCHANGE", BTC - 1_000)], time=T0 + 2 * DAY)
    scr = screener(labels={"MIXER": "mixer", "EXCHANGE": "exchange"})

    assert (
        make_rule(HighRiskCategoryExposure).evaluate(
            context(profile(A, [big, tiny, exchange]), scr)
        )
        == []
    )


def test_r19_co_spending_with_sanctioned_address() -> None:
    t = tx([(A, BTC), ("SANCTIONED", BTC)], [("dest", 2 * BTC - 1_000)])
    alerts = make_rule(CoSpendingWithFlaggedAddress).evaluate(
        context(profile(A, [t]), screener(sanctioned=("SANCTIONED",)))
    )

    assert len(alerts) == 1
    assert "common-input-ownership" in alerts[0].explanation


def test_r19_ignores_coinjoin_co_spending() -> None:
    raw = coinjoin_raw()
    raw["vin"][0]["prevout"]["scriptpubkey_address"] = A
    raw["vin"][1]["prevout"]["scriptpubkey_address"] = "SANCTIONED"
    t = Transaction.from_esplora(raw, 50_000.0)
    assert (
        make_rule(CoSpendingWithFlaggedAddress).evaluate(
            context(profile(A, [t]), screener(sanctioned=("SANCTIONED",)))
        )
        == []
    )


# --- R04 / R05 / R18: obfuscation -----------------------------------------------------


def test_r04_equal_output_coinjoin() -> None:
    raw = coinjoin_raw()
    raw["vout"][0]["scriptpubkey_address"] = A
    alerts = make_rule(CoinJoinParticipation).evaluate(
        context(profile(A, [Transaction.from_esplora(raw, 50_000.0)]))
    )

    assert len(alerts) == 1
    assert "equal-output" in alerts[0].explanation


def test_r04_whirlpool_pattern() -> None:
    t = tx(
        [(A, 1_000_500)] + [(f"in{i}", 1_000_500) for i in range(4)],
        [(f"out{i}", 1_000_000) for i in range(5)],
    )
    alerts = make_rule(CoinJoinParticipation).evaluate(context(profile(A, [t])))

    assert "Whirlpool" in alerts[0].explanation


def test_r04_ordinary_payment_is_not_coinjoin() -> None:
    t = tx([(A, BTC)], [("shop", 30_000_000), ("change", 69_999_000)])
    assert make_rule(CoinJoinParticipation).evaluate(context(profile(A, [t]))) == []


def build_peel_chain(chain: FakeChain, hops: int) -> list[dict]:
    """A spends 10 BTC; every hop pays 0.1 BTC out and forwards the rest."""
    raws = []
    owner, value = A, 10 * BTC
    for hop in range(hops):
        forward = value - 10_000_000 - 1_000
        raw = chain.add(
            raw_tx(
                [(owner, value)],
                [(f"payee{hop}", 10_000_000), (f"next{hop}", forward)],
                time=T0 + hop * HOUR,
            )
        )
        if raws:
            chain.outspends[raws[-1]["txid"]] = [
                {"spent": False},
                {"spent": True, "txid": raw["txid"]},
            ]
        raws.append(raw)
        owner, value = f"next{hop}", forward
    return raws


def test_r05_peel_chain_followed_forward() -> None:
    chain = FakeChain()
    raws = build_peel_chain(chain, hops=4)
    prof = profile(A, [Transaction.from_esplora(raws[0], 50_000.0)])
    alerts = make_rule(PeelChain).evaluate(context(prof, chain=chain))

    assert len(alerts) == 1
    assert len(alerts[0].evidence_txids) == 4


def test_r05_short_chain_is_not_flagged() -> None:
    chain = FakeChain()
    raws = build_peel_chain(chain, hops=2)
    prof = profile(A, [Transaction.from_esplora(raws[0], 50_000.0)])
    assert make_rule(PeelChain).evaluate(context(prof, chain=chain)) == []


def test_r18_merging_coinjoin_outputs() -> None:
    chain = FakeChain()
    cj1, cj2 = chain.add(coinjoin_raw()), chain.add(coinjoin_raw())
    raw = raw_tx([(A, 10_000_000), (A, 10_000_000)], [("exchange", 19_999_000)])
    raw["vin"][0]["txid"], raw["vin"][1]["txid"] = cj1["txid"], cj2["txid"]
    alerts = make_rule(PostCoinJoinConsolidation).evaluate(
        context(profile(A, [Transaction.from_esplora(raw, 50_000.0)]), chain=chain)
    )

    assert len(alerts) == 1
    assert "2 mixed inputs" in alerts[0].explanation


def test_r18_ordinary_inputs() -> None:
    chain = FakeChain()
    p1, p2 = (
        chain.add(raw_tx([("x", BTC)], [(A, BTC)])),
        chain.add(raw_tx([("y", BTC)], [(A, BTC)])),
    )
    raw = raw_tx([(A, BTC), (A, BTC)], [("dest", 2 * BTC - 1_000)])
    raw["vin"][0]["txid"], raw["vin"][1]["txid"] = p1["txid"], p2["txid"]
    prof = profile(A, [Transaction.from_esplora(raw, 50_000.0)])
    assert make_rule(PostCoinJoinConsolidation).evaluate(context(prof, chain=chain)) == []


# --- R06 - R10: behaviour ------------------------------------------------------------

EUR_950 = int(950 / 50_000 * BTC)  # 950 EUR at the default 50,000 EUR/BTC


def test_r06_structuring_below_1000_eur() -> None:
    txs = [tx([(f"s{i}", EUR_950 + 1_000)], [(A, EUR_950)], time=T0 + i * HOUR) for i in range(3)]
    alerts = make_rule(Structuring).evaluate(context(profile(A, txs)))

    assert len(alerts) == 1
    assert "1,000 EUR threshold" in alerts[0].explanation


def test_r06_spread_out_amounts_are_not_structuring() -> None:
    txs = [
        tx([(f"s{i}", EUR_950 + 1_000)], [(A, EUR_950)], time=T0 + i * 10 * DAY) for i in range(3)
    ]
    assert make_rule(Structuring).evaluate(context(profile(A, txs))) == []


def test_r07_pass_through_episodes() -> None:
    txs = []
    for i in range(2):
        start = T0 + i * 5 * DAY
        txs.append(tx([(f"src{i}", BTC + 1_000)], [(A, BTC)], time=start))
        txs.append(tx([(A, BTC)], [(f"dst{i}", BTC - 1_000)], time=start + 2 * HOUR))
    alerts = make_rule(PassThrough).evaluate(context(profile(A, txs)))

    assert len(alerts) == 1
    assert "2 episode(s)" in alerts[0].explanation


def test_r07_funds_held_for_days() -> None:
    txs = [
        tx([("src", BTC + 1_000)], [(A, BTC)], time=T0),
        tx([(A, BTC)], [("dst", BTC - 1_000)], time=T0 + 3 * DAY),
        tx([("src", BTC + 1_000)], [(A, BTC)], time=T0 + 10 * DAY),
        tx([(A, BTC)], [("dst", BTC - 1_000)], time=T0 + 13 * DAY),
    ]
    assert make_rule(PassThrough).evaluate(context(profile(A, txs))) == []


@pytest.mark.parametrize(("senders", "expected"), [(20, 1), (19, 0)])
def test_r08_fan_in(senders: int, expected: int) -> None:
    txs = [tx([(f"s{i}", 101_000)], [(A, 100_000)], time=T0 + i * 60) for i in range(senders)]
    assert len(make_rule(FanIn).evaluate(context(profile(A, txs)))) == expected


def test_r09_fan_out_in_one_batch() -> None:
    t = tx([(A, 30 * BTC)], [(f"r{i}", BTC) for i in range(25)] + [(A, 5 * BTC - 1_000)])
    alerts = make_rule(FanOut).evaluate(context(profile(A, [t])))

    assert "25 distinct recipient" in alerts[0].explanation


def test_r10_high_velocity() -> None:
    txs = [tx([(f"s{i}", 11_000)], [(A, 10_000)], time=T0 + i * 60) for i in range(51)]
    alerts = make_rule(HighVelocity).evaluate(context(profile(A, txs)))

    assert "peak 51" in alerts[0].explanation


def test_r10_normal_activity() -> None:
    txs = [tx([(f"s{i}", 11_000)], [(A, 10_000)], time=T0 + i * HOUR) for i in range(10)]
    assert make_rule(HighVelocity).evaluate(context(profile(A, txs))) == []


# --- R11 - R16, R21: amounts and timing ----------------------------------------------


def test_r11_dormant_address_reactivated() -> None:
    txs = [
        tx([("src", BTC + 1_000)], [(A, BTC)], time=T0),
        tx([(A, BTC)], [("dst", BTC - 1_000)], time=T0 + 400 * DAY),
    ]
    alerts = make_rule(DormantReactivation).evaluate(context(profile(A, txs)))

    assert "Inactive for 400 days" in alerts[0].explanation


def test_r11_small_move_after_dormancy_is_ignored() -> None:
    txs = [
        tx([("src", BTC)], [(A, 10_000)], time=T0),
        tx([(A, 10_000)], [("dst", 9_000)], time=T0 + 400 * DAY),
    ]
    assert make_rule(DormantReactivation).evaluate(context(profile(A, txs))) == []


def test_r12_new_address_receiving_large_amount() -> None:
    t = tx([("src", 2 * BTC + 1_000)], [(A, 2 * BTC)])
    alerts = make_rule(NewAddressHighVolume).evaluate(context(profile(A, [t])))

    assert len(alerts) == 1


def test_r12_skipped_when_history_truncated() -> None:
    t = tx([("src", 2 * BTC + 1_000)], [(A, 2 * BTC)])
    assert make_rule(NewAddressHighVolume).evaluate(context(profile(A, [t], truncated=True))) == []


def test_r13_round_amounts() -> None:
    txs = [tx([(f"s{i}", BTC // 10 + 500)], [(A, BTC // 10)], time=T0 + i * DAY) for i in range(3)]
    assert len(make_rule(RoundAmounts).evaluate(context(profile(A, txs)))) == 1


def test_r13_non_round_amounts() -> None:
    txs = [tx([(f"s{i}", 12_345_678)], [(A, 12_344_678)], time=T0 + i * DAY) for i in range(3)]
    assert make_rule(RoundAmounts).evaluate(context(profile(A, txs))) == []


def test_r14_large_transaction_falls_back_to_btc_without_price() -> None:
    t = tx([("src", 3 * BTC)], [(A, 3 * BTC - 1_000)], price=None)
    alerts = make_rule(LargeTransaction).evaluate(context(profile(A, [t])))

    assert "EUR price unavailable" in alerts[0].explanation
    assert alerts[0].amount_eur is None


def test_r14_small_transaction() -> None:
    t = tx([("src", BTC)], [(A, BTC - 1_000)])  # 50,000 EUR < 100,000
    assert make_rule(LargeTransaction).evaluate(context(profile(A, [t]))) == []


def test_r15_dust_from_many_sources() -> None:
    txs = [tx([(f"d{i}", 10_000)], [(A, 546), (f"d{i}", 9_000)], time=T0 + i) for i in range(5)]
    assert "dusting" in make_rule(DustReceived).evaluate(context(profile(A, txs)))[0].explanation


def test_r15_normal_payments_are_not_dust() -> None:
    txs = [tx([(f"s{i}", 60_000)], [(A, 50_000)], time=T0 + i) for i in range(5)]
    assert make_rule(DustReceived).evaluate(context(profile(A, txs))) == []


def test_r16_consolidation_of_small_inputs() -> None:
    t = tx([(f"small{i}", 500_000) for i in range(20)], [(A, 9_990_000)])
    assert len(make_rule(Consolidation).evaluate(context(profile(A, [t])))) == 1


def test_r16_few_inputs() -> None:
    t = tx([(f"small{i}", 500_000) for i in range(5)], [(A, 2_490_000)])
    assert make_rule(Consolidation).evaluate(context(profile(A, [t]))) == []


def test_r21_fee_far_above_block_median() -> None:
    chain = FakeChain()
    chain.median_fee["block"] = 2.0
    t = tx([(A, BTC)], [("dst", BTC - 100_000)], fee=100_000, weight=1_000)  # 400 sat/vB
    alerts = make_rule(AnomalousFee).evaluate(context(profile(A, [t]), chain=chain))

    assert "400.0 sat/vB vs median 2.0" in alerts[0].explanation


def test_r21_skips_when_median_unavailable() -> None:
    t = tx([(A, BTC)], [("dst", BTC - 100_000)], fee=100_000, weight=1_000)
    assert make_rule(AnomalousFee).evaluate(context(profile(A, [t]))) == []
