from __future__ import annotations

from btc_aml.model import Alert, Transaction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class PassThrough(Rule):
    """Funds are received and sent on quickly, leaving the balance close to where it was.

    An address that only "passes through" funds, without holding them, behaves like a
    transit or money-mule account: a typical layering step. A single quick in-and-out
    is common in normal wallets, so the rule requires ``min_episodes`` episodes.
    """

    rule_id = "R07_PASS_THROUGH"
    name = "Pass-through (rapid in and out)"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("max_holding_hours", "max_residual_pct", "min_episodes")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        episodes = self._find_episodes(ctx)
        if len(episodes) < self.params["min_episodes"]:
            return []

        address = ctx.profile.address
        receipts = [episode[0] for episode in episodes]
        amount = sum(tx.received_by(address) for tx in receipts)
        amount_eur = sum_eur(tx.to_eur(tx.received_by(address)) for tx in receipts)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(episodes)} episode(s) in which funds received were sent on within "
                    f"{self.params['max_holding_hours']}h, leaving at most "
                    f"{self.params['max_residual_pct']}% of the amount received. "
                    f"Value passed through: {fmt_amount(amount, amount_eur)}."
                ),
                txids=[tx.txid for episode in episodes for tx in episode],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]

    def _find_episodes(self, ctx: AnalysisContext) -> list[list[Transaction]]:
        address = ctx.profile.address
        timeline = ctx.profile.balance_timeline()
        window = self.params["max_holding_hours"] * 3600
        episodes = []
        i = 0
        while i < len(timeline):
            tx, balance_after = timeline[i]
            received = tx.net_flow(address)
            if received <= 0 or tx.block_time is None:
                i += 1
                continue
            balance_before = balance_after - received
            limit = balance_before + received * self.params["max_residual_pct"] / 100
            end = self._drained_at(timeline, i, tx.block_time + window, limit)
            if end is None:
                i += 1
                continue
            episodes.append([t for t, _ in timeline[i : end + 1]])
            i = end + 1
        return episodes

    @staticmethod
    def _drained_at(
        timeline: list[tuple[Transaction, int]], start: int, deadline: int, limit: float
    ) -> int | None:
        """Index of the first later transaction that brings the balance down to ``limit``."""
        for j in range(start + 1, len(timeline)):
            tx, balance = timeline[j]
            if tx.block_time is None or tx.block_time > deadline:
                return None
            if balance <= limit:
                return j
        return None
