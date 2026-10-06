from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, exceeds_threshold, fmt_amount, fmt_time
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class DormantReactivation(Rule):
    """A long-dormant address suddenly moves a significant amount.

    Funds that sit untouched for a long time and then move can be proceeds of an old
    crime (e.g. a past hack or darknet market) being cashed out, or a change of control
    of the keys. Only gaps between analysed transactions are measured.
    """

    rule_id = "R11_DORMANT_REACTIVATION"
    name = "Dormant address reactivated"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("dormancy_days", "min_amount_eur", "min_amount_btc")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        alerts = []
        dated = [flow for flow in ctx.profile.flows if flow.tx.block_time is not None]
        min_gap = self.params["dormancy_days"] * 86_400
        for previous, current in zip(dated, dated[1:], strict=False):
            gap = current.tx.block_time - previous.tx.block_time  # type: ignore[operator]
            if gap < min_gap:
                continue
            significant, basis = exceeds_threshold(
                current.amount_sats,
                current.amount_eur,
                self.params["min_amount_eur"],
                self.params["min_amount_btc"],
            )
            if not significant:
                continue
            alerts.append(
                self.make_alert(
                    ctx,
                    explanation=(
                        f"Inactive for {gap // 86_400} days (last activity "
                        f"{fmt_time(previous.tx.block_time)}), then moved "
                        f"{fmt_amount(current.amount_sats, current.amount_eur)} "
                        f"({current.direction.value}) on {fmt_time(current.tx.block_time)}; "
                        f"{basis}."
                    ),
                    txids=[previous.tx.txid, current.tx.txid],
                    amount_sats=current.amount_sats,
                    amount_eur=current.amount_eur,
                )
            )
        return alerts
