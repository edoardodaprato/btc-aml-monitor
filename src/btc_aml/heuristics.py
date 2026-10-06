"""Blockchain heuristics shared by several rules.

Heuristics are educated guesses, not facts: every alert that relies on one says so in
its explanation, and the README lists their known false positives.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from btc_aml.config import CoinJoinConfig
from btc_aml.model import Transaction

# Samourai Whirlpool pool denominations (0.001, 0.01, 0.05, 0.5 BTC). A Whirlpool mix has
# 5 inputs and 5 outputs of exactly the pool denomination. The coordinator was seized in
# April 2024, but historical mixes remain relevant for retrospective analysis.
WHIRLPOOL_DENOMINATIONS = frozenset({100_000, 1_000_000, 5_000_000, 50_000_000})
WHIRLPOOL_PARTICIPANTS = 5


@dataclass(frozen=True)
class CoinJoinMatch:
    kind: str  # "Whirlpool" or "equal-output (Wasabi/JoinMarket-style)"
    equal_outputs: int
    denomination_sats: int


def detect_coinjoin(tx: Transaction, config: CoinJoinConfig) -> CoinJoinMatch | None:
    """Recognise CoinJoin transactions from their output structure.

    A CoinJoin merges coins of several users into one transaction that pays many
    outputs of the *same* value, so that no one can tell which output belongs to whom.
    """
    if tx.is_coinbase or not tx.outputs:
        return None
    output_values = Counter(o.value_sats for o in tx.outputs if o.value_sats)
    if not output_values:
        return None
    denomination, count = output_values.most_common(1)[0]

    if (
        len(tx.inputs) == len(tx.outputs) == WHIRLPOOL_PARTICIPANTS
        and count == WHIRLPOOL_PARTICIPANTS
        and denomination in WHIRLPOOL_DENOMINATIONS
    ):
        return CoinJoinMatch("Whirlpool", count, denomination)

    distinct_inputs = len(tx.input_addresses)
    if count >= config.min_equal_outputs and distinct_inputs >= config.min_distinct_inputs:
        return CoinJoinMatch("equal-output (Wasabi/JoinMarket-style)", count, denomination)
    return None
