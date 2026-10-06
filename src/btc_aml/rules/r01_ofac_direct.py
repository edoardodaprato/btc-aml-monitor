from __future__ import annotations

from btc_aml.model import Alert, Direction
from btc_aml.rules.base import (
    AnalysisContext,
    Rule,
    describe_hits,
    flagged_counterparties,
    fmt_amount,
    fmt_btc,
    sum_eur,
)
from btc_aml.rules.references import FATF_SOURCE_OF_FUNDS, SANCTIONS


class OfacDirectExposure(Rule):
    """The address is itself sanctioned, or exchanged funds directly with a sanctioned address.

    Any direct transaction with a designated person or entity is a potential sanctions
    breach: it must be escalated regardless of the amount, which is why this rule always
    places the address in the highest risk band.
    """

    rule_id = "R01_OFAC_DIRECT"
    name = "Direct exposure to sanctioned address"
    regulatory_reference = f"{SANCTIONS}; {FATF_SOURCE_OF_FUNDS}"

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        alerts = []
        profile = ctx.profile
        own_hits = [h for h in ctx.screener.screen(profile.address) if h.category == "sanctioned"]
        if own_hits:
            inflows = [flow for flow in profile.flows if flow.direction is Direction.IN]
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=f"The address itself is sanctioned: {describe_hits(own_hits)}.",
                    txids=[flow.tx.txid for flow in inflows],
                    amount_sats=profile.total_received_sats,
                    amount_eur=sum_eur(flow.amount_eur for flow in inflows),
                    hop_distance=0,
                )
            )

        for flows, hits in flagged_counterparties(ctx, ["sanctioned"]):
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=(
                        f"Direct transactions with sanctioned address {flows.address} "
                        f"({describe_hits(hits)}): received {fmt_btc(flows.received_from_sats)}, "
                        f"sent {fmt_btc(flows.sent_to_sats)}; total "
                        f"{fmt_amount(flows.total_sats, flows.total_eur)} "
                        f"in {len(flows.txids)} transaction(s)."
                    ),
                    txids=flows.txids,
                    amount_sats=flows.total_sats,
                    amount_eur=flows.total_eur,
                    hop_distance=1,
                )
            )
        return alerts
