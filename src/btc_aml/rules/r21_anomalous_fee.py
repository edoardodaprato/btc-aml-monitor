from __future__ import annotations

from btc_aml.model import Alert, Transaction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class AnomalousFee(Rule):
    """The address pays fees far above what the rest of the block paid.

    Overpaying fees by an order of magnitude buys speed: it can signal urgency to move
    funds before they are frozen or traced (e.g. right after a hack). It can also be a
    wallet misconfiguration, so the weight is low. Block fee statistics come from
    mempool.space only; if they are unavailable the transaction is skipped.
    """

    rule_id = "R21_ANOMALOUS_FEE"
    name = "Anomalously high fee"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_fee_multiple", "min_fee_sats", "max_txs_checked")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        paid = [
            tx
            for tx in ctx.profile.txs
            if address in tx.input_addresses
            and tx.block_hash
            and tx.fee_sats >= self.params["min_fee_sats"]
        ][-self.params["max_txs_checked"] :]

        anomalies: list[tuple[Transaction, float, float]] = []
        for tx in paid:
            median = ctx.chain.get_block_median_fee_rate(tx.block_hash)  # type: ignore[arg-type]
            if median and tx.fee_rate >= self.params["min_fee_multiple"] * median:
                anomalies.append((tx, tx.fee_rate, median))
        if not anomalies:
            return []

        fees = sum(tx.fee_sats for tx, _, _ in anomalies)
        fees_eur = sum_eur(tx.to_eur(tx.fee_sats) for tx, _, _ in anomalies)
        worst_tx, worst_rate, worst_median = max(anomalies, key=lambda a: a[1] / a[2])
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(anomalies)} transaction(s) paid at least "
                    f"{self.params['min_fee_multiple']}x the block median fee rate; worst "
                    f"{worst_rate:.1f} sat/vB vs median {worst_median:.1f} in {worst_tx.txid}. "
                    f"Total fees {fmt_amount(fees, fees_eur)}."
                ),
                txids=[tx.txid for tx, _, _ in anomalies],
                amount_sats=fees,
                amount_eur=fees_eur,
            )
        ]
