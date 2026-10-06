from __future__ import annotations

from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, describe_hits, fmt_amount
from btc_aml.rules.references import EBA_CASP, FATF_SOURCE_OF_FUNDS, SANCTIONS


class CoSpendingWithFlaggedAddress(Rule):
    """The address spent funds together with a sanctioned or high-risk address.

    Under the common-input-ownership heuristic, all inputs of a transaction are usually
    controlled by the same wallet. If the analysed address signs a transaction together
    with a flagged address, the two are probably the same entity, even if they never
    sent funds to each other. CoinJoin transactions are excluded because there the
    heuristic does not hold (inputs belong to different users by design).
    """

    rule_id = "R19_CO_SPENDING_FLAGGED"
    name = "Co-spending with flagged address"
    regulatory_reference = f"{SANCTIONS}; {FATF_SOURCE_OF_FUNDS}; {EBA_CASP}"
    required_params = ("categories",)

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        categories = set(self.params["categories"])
        address = ctx.profile.address
        alerts = []
        for tx in ctx.profile.txs:
            if address not in tx.input_addresses or detect_coinjoin(tx, ctx.coinjoin):
                continue
            for co_spender in sorted(tx.input_addresses - {address}):
                hits = [h for h in ctx.screener.screen(co_spender) if h.category in categories]
                if not hits:
                    continue
                spent = tx.sent_by(address)
                alerts.append(
                    self.make_alert(
                        ctx,
                        explanation=(
                            f"Transaction {tx.txid} spends inputs of this address together with "
                            f"inputs of {co_spender} ({describe_hits(hits)}): likely the same "
                            f"wallet (common-input-ownership heuristic). Value spent by this "
                            f"address: {fmt_amount(spent, tx.to_eur(spent))}."
                        ),
                        txids=[tx.txid],
                        amount_sats=spent,
                        amount_eur=tx.to_eur(spent),
                        hop_distance=0,
                    )
                )
        return alerts
