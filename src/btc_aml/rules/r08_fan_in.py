from __future__ import annotations

from btc_aml.model import Alert, Direction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.fan_in_out import busiest_window, flows_in_direction
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class FanIn(Rule):
    """Many different senders pay the address within a short time.

    Funds from many unrelated sources converging on one address can indicate collection
    of proceeds (scam victims, ransomware payments) or pooling before layering.
    Legitimate services (merchants, exchanges) also show this pattern, so the alert
    must be read together with the address context.
    """

    rule_id = "R08_FAN_IN"
    name = "Fan-in (many senders)"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_senders", "window_hours")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        incoming = flows_in_direction(ctx.profile.flows, Direction.IN)
        window, senders = busiest_window(
            incoming,
            self.params["window_hours"] * 3600,
            lambda flow: flow.tx.input_addresses - {address},
        )
        if senders < self.params["min_senders"]:
            return []
        amount = sum(flow.amount_sats for flow in window)
        amount_eur = sum_eur(flow.amount_eur for flow in window)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{senders} distinct sending addresses within {self.params['window_hours']}h "
                    f"({len(window)} transactions, {fmt_amount(amount, amount_eur)} received)."
                ),
                txids=[flow.tx.txid for flow in window],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
