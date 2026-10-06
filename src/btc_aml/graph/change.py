"""Change-output detection.

When a wallet spends a coin larger than the payment, the remainder ("change") goes
back to the sender, often to a brand-new address. Recognising change matters for AML:
the change address is the *sender's own* address, not a counterparty, and exposure
must keep following it. The heuristics below are applied in order of reliability and
return a guess only when it is unambiguous; otherwise no output is treated as change.
"""

from __future__ import annotations

from dataclasses import dataclass

from btc_aml.model import Transaction, TxOutput

ROUND_UNIT_SATS = 100_000  # 0.001 BTC: payments are often round, change rarely is


@dataclass(frozen=True)
class ChangeGuess:
    output: TxOutput
    heuristic: str


def detect_change(tx: Transaction) -> ChangeGuess | None:
    """Guess which output of ``tx`` is change, or None if unclear."""
    if tx.is_coinbase or len(tx.outputs) < 2:
        return None
    for heuristic in (_address_reuse, _script_type_match, _non_round_amount):
        guess = heuristic(tx)
        if guess is not None:
            return guess
    return None


def _address_reuse(tx: Transaction) -> ChangeGuess | None:
    """An output paying back to one of the input addresses is change."""
    reused = [o for o in tx.outputs if o.address and o.address in tx.input_addresses]
    return ChangeGuess(reused[0], "address reuse") if len(reused) == 1 else None


def _script_type_match(tx: Transaction) -> ChangeGuess | None:
    """Wallets create change with the same script type as the coins they spend."""
    input_types = {i.script_type for i in tx.inputs}
    if len(input_types) != 1 or None in input_types:
        return None
    matching = [o for o in tx.outputs if o.script_type in input_types]
    if len(matching) == 1 and len(tx.outputs) > 1:
        return ChangeGuess(matching[0], "script type matches inputs")
    return None


def _non_round_amount(tx: Transaction) -> ChangeGuess | None:
    """With one round output (the payment), the only non-round output is the change."""
    non_round = [o for o in tx.outputs if o.value_sats % ROUND_UNIT_SATS]
    has_round_payment = len(non_round) == len(tx.outputs) - 1
    return ChangeGuess(non_round[0], "non-round amount") if has_round_payment else None
