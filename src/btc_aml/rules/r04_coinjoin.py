from __future__ import annotations

from collections import Counter

from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_ANONYMITY


class CoinJoinParticipation(Rule):
    """The address took part in CoinJoin transactions.

    CoinJoin mixes coins of many users so that the link between sender and recipient is
    broken. Using it is not illegal, but it deliberately hides the source of funds,
    which FATF lists among anonymity-enhancing red flags. Detection is structural
    (many equal outputs, or the Whirlpool 5x5 pattern) and can miss newer protocols.
    """

    rule_id = "R04_COINJOIN"
    name = "CoinJoin participation"
    regulatory_reference = f"{FATF_ANONYMITY}; {EBA_CASP}"

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        involved = []
        kinds: Counter[str] = Counter()
        for tx in ctx.profile.txs:
            match = detect_coinjoin(tx, ctx.coinjoin)
            if match and (address in tx.input_addresses or address in tx.output_addresses):
                involved.append(tx)
                kinds[match.kind] += 1
        if not involved:
            return []

        amounts = [tx.sent_by(address) or tx.received_by(address) for tx in involved]
        amount_eur = sum_eur(tx.to_eur(a) for tx, a in zip(involved, amounts, strict=True))
        kinds_text = ", ".join(f"{count} {kind}" for kind, count in kinds.most_common())
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"Participated in {len(involved)} CoinJoin transaction(s) ({kinds_text}) "
                    f"for {fmt_amount(sum(amounts), amount_eur)}."
                ),
                txids=[tx.txid for tx in involved],
                amount_sats=sum(amounts),
                amount_eur=amount_eur,
            )
        ]
