from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from btc_aml.model import Alert, Transaction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_SIZE_FREQUENCY


class HighVelocity(Rule):
    """The address makes an unusually high number of transactions per day.

    A burst of activity, well above what an individual wallet does, may indicate
    automated movement of funds (layering scripts, mule networks) or an undisclosed
    service. Days are counted in UTC.
    """

    rule_id = "R10_HIGH_VELOCITY"
    name = "High transaction velocity"
    regulatory_reference = f"{FATF_SIZE_FREQUENCY}; {EBA_CASP}"
    required_params = ("max_tx_per_day",)

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        by_day: dict[str, list[Transaction]] = defaultdict(list)
        for tx in ctx.profile.txs:
            if tx.block_time is not None:
                day = datetime.fromtimestamp(tx.block_time, UTC).date().isoformat()
                by_day[day].append(tx)

        limit = self.params["max_tx_per_day"]
        busy = {day: txs for day, txs in by_day.items() if len(txs) > limit}
        if not busy:
            return []

        address = ctx.profile.address
        peak_day, peak_txs = max(busy.items(), key=lambda item: len(item[1]))
        amounts = [abs(tx.net_flow(address)) for tx in peak_txs]
        amount_eur = sum_eur(tx.to_eur(a) for tx, a in zip(peak_txs, amounts, strict=True))
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(busy)} day(s) with more than {limit} transactions; peak "
                    f"{len(peak_txs)} on {peak_day} ({fmt_amount(sum(amounts), amount_eur)} moved)."
                ),
                txids=[tx.txid for tx in peak_txs],
                amount_sats=sum(amounts),
                amount_eur=amount_eur,
            )
        ]
