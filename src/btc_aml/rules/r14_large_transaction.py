from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, exceeds_threshold, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_SIZE_FREQUENCY


class LargeTransaction(Rule):
    """A single transaction moves a large amount.

    High-value transfers carry higher inherent ML/TF risk and normally trigger enhanced
    scrutiny of the source of funds. The EUR threshold is used when a price exists,
    otherwise the BTC threshold (the explanation states which one applied).
    """

    rule_id = "R14_LARGE_TRANSACTION"
    name = "Large single transaction"
    regulatory_reference = f"{FATF_SIZE_FREQUENCY}; {EBA_CASP}"
    required_params = ("threshold_eur", "threshold_btc")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        large = []
        bases = set()
        for flow in ctx.profile.flows:
            hit, basis = exceeds_threshold(
                flow.amount_sats,
                flow.amount_eur,
                self.params["threshold_eur"],
                self.params["threshold_btc"],
            )
            if hit:
                large.append(flow)
                bases.add(basis)
        if not large:
            return []
        biggest = max(large, key=lambda flow: flow.amount_sats)
        amount = sum(flow.amount_sats for flow in large)
        amount_eur = sum_eur(flow.amount_eur for flow in large)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(large)} transaction(s) above threshold ({'; '.join(sorted(bases))}); "
                    f"largest {fmt_amount(biggest.amount_sats, biggest.amount_eur)} "
                    f"({biggest.direction.value}) in {biggest.tx.txid}."
                ),
                txids=[flow.tx.txid for flow in large],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
