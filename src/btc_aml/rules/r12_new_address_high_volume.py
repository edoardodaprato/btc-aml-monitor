from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, exceeds_threshold, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class NewAddressHighVolume(Rule):
    """A newly created address moves a large volume in its very first transactions.

    FATF flags new relationships that start with large deposits. On-chain, a fresh
    address that immediately handles high value suggests a disposable address created
    to move funds once. Skipped when the history is truncated (the address is then not
    new by definition).
    """

    rule_id = "R12_NEW_ADDRESS_HIGH_VOLUME"
    name = "New address with high volume"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("first_n_tx", "max_age_days", "min_volume_eur", "min_volume_btc")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        profile = ctx.profile
        if profile.truncated or profile.first_seen is None:
            return []
        deadline = profile.first_seen + self.params["max_age_days"] * 86_400
        early = [
            flow
            for flow in profile.flows[: self.params["first_n_tx"]]
            if flow.tx.block_time is not None and flow.tx.block_time <= deadline
        ]
        amount = sum(flow.amount_sats for flow in early)
        amount_eur = sum_eur(flow.amount_eur for flow in early)
        high, basis = exceeds_threshold(
            amount, amount_eur, self.params["min_volume_eur"], self.params["min_volume_btc"]
        )
        if not early or not high:
            return []
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"First {len(early)} transaction(s), within {self.params['max_age_days']} days "
                    f"of first use, moved {fmt_amount(amount, amount_eur)}; {basis}."
                ),
                txids=[flow.tx.txid for flow in early],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
