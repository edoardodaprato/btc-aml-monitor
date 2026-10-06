from __future__ import annotations

from btc_aml.model import SATS_PER_BTC, Alert
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class RoundAmounts(Rule):
    """The address repeatedly sends or receives round BTC amounts.

    Ordinary payments rarely land on exact round figures; repeated round transfers
    (e.g. exactly 0.1 or 1 BTC) are typical of OTC deals, pre-agreed payments between
    criminals or manual layering. Amounts are net of change returned to the address.
    """

    rule_id = "R13_ROUND_AMOUNTS"
    name = "Repeated round amounts"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("round_units_btc", "min_occurrences")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        units = [round(unit * SATS_PER_BTC) for unit in self.params["round_units_btc"]]
        round_flows = [
            flow
            for flow in ctx.profile.flows
            if any(flow.amount_sats >= u and flow.amount_sats % u == 0 for u in units)
        ]
        if len(round_flows) < self.params["min_occurrences"]:
            return []
        amount = sum(flow.amount_sats for flow in round_flows)
        amount_eur = sum_eur(flow.amount_eur for flow in round_flows)
        units_text = ", ".join(f"{u} BTC" for u in self.params["round_units_btc"])
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(round_flows)} transfers are exact multiples of {units_text}, "
                    f"total {fmt_amount(amount, amount_eur)}."
                ),
                txids=[flow.tx.txid for flow in round_flows],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
