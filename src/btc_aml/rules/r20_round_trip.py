from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.indirect import path_text
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class RoundTrip(Rule):
    """Funds sent out by the address come back to it (or to its cluster) a few hops later.

    Circular flows have no economic purpose: they are used to create artificial
    transaction history, to simulate turnover, or to "clean" funds by passing them
    through intermediaries and back. Detected while following outgoing funds.
    """

    rule_id = "R20_ROUND_TRIP"
    name = "Round-trip (circular flow)"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_return_share",)

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        if ctx.exposure is None or not ctx.exposure.round_trips:
            return []
        trips = ctx.exposure.round_trips
        amount = sum(trip.amount_sats for trip in trips)
        share = amount / (ctx.profile.volume_sats or 1)
        if share < self.params["min_return_share"]:
            return []
        amount_eur = sum_eur(trip.amount_eur for trip in trips)
        shortest = min(trips, key=lambda trip: len(trip.path))
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(trips)} circular path(s) return funds to this address or its cluster; "
                    f"estimated {fmt_amount(amount, amount_eur)} ({share:.1%} of the analysed "
                    f"volume). Shortest: {path_text(shortest.path)}."
                ),
                txids=[txid for trip in trips for txid in trip.txids],
                amount_sats=amount,
                amount_eur=amount_eur,
                hop_distance=len(shortest.path) - 1,
            )
        ]
