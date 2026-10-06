from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import (
    AnalysisContext,
    Rule,
    describe_hits,
    flagged_counterparties,
    fmt_amount,
)
from btc_aml.rules.references import EBA_CASP, FATF_ANONYMITY, FATF_SOURCE_OF_FUNDS


class HighRiskCategoryExposure(Rule):
    """The address is labelled, or transacted directly with an address labelled, as high risk.

    Funds coming from (or going to) mixers, darknet markets, ransomware or scams are a
    classic source-of-funds red flag. Exposure below ``min_exposure_share`` of the
    address volume is ignored to avoid alerting on negligible amounts.
    """

    rule_id = "R03_HIGH_RISK_CATEGORY"
    name = "Exposure to high-risk category"
    regulatory_reference = f"{FATF_SOURCE_OF_FUNDS}; {FATF_ANONYMITY}; {EBA_CASP}"
    required_params = ("categories", "min_exposure_share")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        categories = set(self.params["categories"])
        profile = ctx.profile
        alerts = []

        own_hits = [h for h in ctx.screener.screen(profile.address) if h.category in categories]
        if own_hits:
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=f"The address itself is labelled: {describe_hits(own_hits)}.",
                    txids=[tx.txid for tx in profile.txs],
                    amount_sats=profile.volume_sats,
                    amount_eur=None,
                    hop_distance=0,
                )
            )

        volume = profile.volume_sats or 1
        for flows, hits in flagged_counterparties(ctx, categories):
            share = flows.total_sats / volume
            if share < self.params["min_exposure_share"]:
                continue
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=(
                        f"Direct transactions with {flows.address} ({describe_hits(hits)}): "
                        f"{fmt_amount(flows.total_sats, flows.total_eur)}, "
                        f"{share:.1%} of the analysed volume, in {len(flows.txids)} transaction(s)."
                    ),
                    txids=flows.txids,
                    amount_sats=flows.total_sats,
                    amount_eur=flows.total_eur,
                    hop_distance=1,
                )
            )
        return alerts
