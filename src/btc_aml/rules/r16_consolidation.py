from __future__ import annotations

from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import SATS_PER_BTC, Alert
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class Consolidation(Rule):
    """Many small inputs are merged into one transaction involving the address.

    Collecting many small amounts into one is how proceeds of many small crimes (scam
    payments, ransomware, mule deposits) are aggregated before moving on. Exchanges
    also consolidate deposits, so the alert must be read with the address context.
    CoinJoin transactions are excluded (they have many inputs by design).
    """

    rule_id = "R16_CONSOLIDATION"
    name = "Consolidation of many small inputs"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_inputs", "max_input_btc")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        max_input = round(self.params["max_input_btc"] * SATS_PER_BTC)
        address = ctx.profile.address
        matches = []
        for tx in ctx.profile.txs:
            small = sum(1 for i in tx.inputs if 0 < i.value_sats <= max_input)
            if small >= self.params["min_inputs"] and not detect_coinjoin(tx, ctx.coinjoin):
                matches.append((tx, small))
        if not matches:
            return []

        amounts = [tx.sent_by(address) or tx.received_by(address) for tx, _ in matches]
        amount_eur = sum_eur(tx.to_eur(a) for (tx, _), a in zip(matches, amounts, strict=True))
        largest_tx, largest_count = max(matches, key=lambda item: item[1])
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(matches)} transaction(s) merge at least {self.params['min_inputs']} "
                    f"inputs of at most {self.params['max_input_btc']} BTC each (largest: "
                    f"{largest_count} small inputs in {largest_tx.txid}); value involving this "
                    f"address {fmt_amount(sum(amounts), amount_eur)}."
                ),
                txids=[tx.txid for tx, _ in matches],
                amount_sats=sum(amounts),
                amount_eur=amount_eur,
            )
        ]
