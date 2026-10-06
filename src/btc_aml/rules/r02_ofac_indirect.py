from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.rules.indirect import indirect_alerts
from btc_aml.rules.references import FATF_SOURCE_OF_FUNDS, SANCTIONS


class OfacIndirectExposure(Rule):
    """Funds reached the address from, or went to, a sanctioned address within N hops.

    Sanctioned actors rarely pay their counterparties directly: funds are routed through
    intermediate addresses. Following the flows hop by hop (with pro-rata attribution)
    reveals this indirect exposure. Its weight in the score decays with distance
    (``hop_decay``), because each intermediary weakens the link.
    """

    rule_id = "R02_OFAC_INDIRECT"
    name = "Indirect exposure to sanctioned address"
    regulatory_reference = f"{SANCTIONS}; {FATF_SOURCE_OF_FUNDS}"
    required_params = ("min_exposure_share",)

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        return indirect_alerts(self, ctx, {"sanctioned"})
