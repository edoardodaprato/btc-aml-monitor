from __future__ import annotations

from btc_aml.model import Alert, Direction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.fan_in_out import busiest_window, flows_in_direction
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class FanOut(Rule):
    """The address distributes funds to many different recipients within a short time.

    Dispersing funds to many addresses is a layering technique (splitting proceeds
    across mules or wallets). Exchange and payroll batch payouts look the same, so the
    alert must be read together with the address context.
    """

    rule_id = "R09_FAN_OUT"
    name = "Fan-out (many recipients)"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_recipients", "window_hours")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        outgoing = flows_in_direction(ctx.profile.flows, Direction.OUT)
        window, recipients = busiest_window(
            outgoing,
            self.params["window_hours"] * 3600,
            lambda flow: flow.tx.output_addresses - {address},
        )
        if recipients < self.params["min_recipients"]:
            return []
        amount = sum(flow.amount_sats for flow in window)
        amount_eur = sum_eur(flow.amount_eur for flow in window)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{recipients} distinct recipient addresses within "
                    f"{self.params['window_hours']}h ({len(window)} transactions, "
                    f"{fmt_amount(amount, amount_eur)} sent)."
                ),
                txids=[flow.tx.txid for flow in window],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
