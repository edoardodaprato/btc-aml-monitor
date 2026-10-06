from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, densest_window, fmt_amount, fmt_time, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_SIZE_FREQUENCY, TFR


class Structuring(Rule):
    """Repeated amounts just below a reporting or due-diligence threshold in a short time.

    Splitting a large amount into several transfers each slightly below a threshold
    (e.g. 1,000 EUR, the EU Travel Rule threshold for self-hosted address verification,
    or 10,000 EUR) is a textbook attempt to avoid controls. Only transactions with a
    known EUR price are considered, because the thresholds are defined in EUR.
    """

    rule_id = "R06_STRUCTURING"
    name = "Structuring below thresholds"
    regulatory_reference = f"{FATF_SIZE_FREQUENCY}; {EBA_CASP}; {TFR}"
    required_params = ("thresholds_eur", "margin_pct", "min_occurrences", "window_hours")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        alerts = []
        priced = [flow for flow in ctx.profile.flows if flow.amount_eur is not None]
        for threshold in self.params["thresholds_eur"]:
            floor = threshold * (1 - self.params["margin_pct"] / 100)
            near = [flow for flow in priced if floor <= flow.amount_eur < threshold]  # type: ignore[operator]
            cluster = densest_window(
                near, self.params["window_hours"] * 3600, lambda flow: flow.tx.block_time
            )
            if len(cluster) < self.params["min_occurrences"]:
                continue
            amount = sum(flow.amount_sats for flow in cluster)
            amount_eur = sum_eur(flow.amount_eur for flow in cluster)
            period = f"{fmt_time(cluster[0].tx.block_time)} - {fmt_time(cluster[-1].tx.block_time)}"
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=(
                        f"{len(cluster)} transfers between {floor:,.0f} and {threshold:,.0f} EUR "
                        f"within {self.params['window_hours']}h "
                        f"({period}), "
                        f"total {fmt_amount(amount, amount_eur)}: possible structuring below "
                        f"the {threshold:,.0f} EUR threshold."
                    ),
                    txids=[flow.tx.txid for flow in cluster],
                    amount_sats=amount,
                    amount_eur=amount_eur,
                )
            )
        return alerts
