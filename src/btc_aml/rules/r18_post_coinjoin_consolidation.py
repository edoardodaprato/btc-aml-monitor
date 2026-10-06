from __future__ import annotations

from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import Alert, Transaction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_ANONYMITY


class PostCoinJoinConsolidation(Rule):
    """Several CoinJoin outputs are merged in one transaction involving the address.

    After mixing, coins are usually spent separately to preserve privacy. Merging many
    freshly mixed outputs into one transaction is typical of someone gathering mixed
    funds before depositing them at an exchange. The previous transaction of each input
    is downloaded to check whether it was a CoinJoin (capped for API cost).
    """

    rule_id = "R18_POST_COINJOIN_CONSOLIDATION"
    name = "Post-CoinJoin consolidation"
    regulatory_reference = f"{FATF_ANONYMITY}; {EBA_CASP}"
    required_params = ("min_coinjoin_inputs", "max_txs_checked", "max_inputs_checked")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        min_cj = self.params["min_coinjoin_inputs"]
        candidates = [
            tx
            for tx in ctx.profile.txs
            if len(tx.inputs) >= min_cj and not detect_coinjoin(tx, ctx.coinjoin)
        ][-self.params["max_txs_checked"] :]

        matches: list[tuple[Transaction, int]] = []
        for tx in candidates:
            mixed_inputs = self._count_coinjoin_inputs(ctx, tx)
            if mixed_inputs >= min_cj:
                matches.append((tx, mixed_inputs))
        if not matches:
            return []

        address = ctx.profile.address
        amounts = [tx.sent_by(address) or tx.received_by(address) for tx, _ in matches]
        amount_eur = sum_eur(tx.to_eur(a) for (tx, _), a in zip(matches, amounts, strict=True))
        details = ", ".join(f"{tx.txid[:12]}... ({n} mixed inputs)" for tx, n in matches)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(matches)} transaction(s) merge outputs of CoinJoin transactions: "
                    f"{details}. Value involving this address: "
                    f"{fmt_amount(sum(amounts), amount_eur)}."
                ),
                txids=[tx.txid for tx, _ in matches],
                amount_sats=sum(amounts),
                amount_eur=amount_eur,
            )
        ]

    def _count_coinjoin_inputs(self, ctx: AnalysisContext, tx: Transaction) -> int:
        count = 0
        for tx_input in tx.inputs[: self.params["max_inputs_checked"]]:
            previous = Transaction.from_esplora(ctx.chain.get_tx(tx_input.prev_txid))
            if detect_coinjoin(previous, ctx.coinjoin):
                count += 1
        return count
