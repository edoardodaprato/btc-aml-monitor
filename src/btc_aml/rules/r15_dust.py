from __future__ import annotations

from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class DustReceived(Rule):
    """The address receives tiny unsolicited amounts ("dust") from many sources.

    Dusting attacks send minimal amounts to many addresses so that, when the victim
    later spends the dust together with other coins, the attacker can link the
    addresses (de-anonymisation or tracking). It signals that the address is being
    targeted or monitored; it says nothing about the owner's intent.
    """

    rule_id = "R15_DUST"
    name = "Dust received from many sources"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("max_dust_sats", "min_sources")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        dust_txs = [
            tx
            for tx in ctx.profile.txs
            if address not in tx.input_addresses
            and 0 < tx.received_by(address) <= self.params["max_dust_sats"]
        ]
        if len(dust_txs) < self.params["min_sources"]:
            return []
        amount = sum(tx.received_by(address) for tx in dust_txs)
        amount_eur = sum_eur(tx.to_eur(tx.received_by(address)) for tx in dust_txs)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"Received {len(dust_txs)} dust payments of at most "
                    f"{self.params['max_dust_sats']} sats each "
                    f"({fmt_amount(amount, amount_eur)} in total): possible dusting attack."
                ),
                txids=[tx.txid for tx in dust_txs],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]
