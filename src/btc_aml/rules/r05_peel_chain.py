from __future__ import annotations

from btc_aml.model import Alert, Transaction
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount, sum_eur
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class PeelChain(Rule):
    """Funds leave the address through a peel chain.

    In a peel chain a large balance is moved through a sequence of transactions, each
    paying a small amount to a destination and sending the large remainder on to a new
    address, which repeats the pattern. It is used to cash out stolen or illicit funds
    in small pieces while keeping the bulk moving. The rule starts from the address's
    own spends and follows the large output forward (one API call per hop).
    """

    rule_id = "R05_PEEL_CHAIN"
    name = "Peel chain"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_chain_length", "max_peel_ratio", "max_start_txs")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        spends = [tx for tx in ctx.profile.txs if address in tx.input_addresses]
        chains: list[list[Transaction]] = []
        seen: set[str] = set()
        for tx in reversed(spends[-self.params["max_start_txs"] :]):
            if tx.txid in seen or not self._is_peel(tx):
                continue
            chain = self._follow(ctx, tx)
            seen.update(t.txid for t in chain)
            if len(chain) >= self.params["min_chain_length"]:
                chains.append(chain)
        if not chains:
            return []

        first_hops = [chain[0] for chain in chains]
        amount = sum(tx.sent_by(address) for tx in first_hops)
        amount_eur = sum_eur(tx.to_eur(tx.sent_by(address)) for tx in first_hops)
        lengths = ", ".join(str(len(chain)) for chain in chains)
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(chains)} peel chain(s) of length {lengths} start from this address: "
                    f"each hop pays out at most {self.params['max_peel_ratio']:.0%} of the value "
                    f"and forwards the rest. Value entering the chains: "
                    f"{fmt_amount(amount, amount_eur)}."
                ),
                txids=[tx.txid for chain in chains for tx in chain],
                amount_sats=amount,
                amount_eur=amount_eur,
            )
        ]

    def _is_peel(self, tx: Transaction) -> bool:
        if tx.is_coinbase or len(tx.outputs) != 2 or tx.total_output_sats == 0:
            return False
        small = min(o.value_sats for o in tx.outputs)
        return 0 < small <= self.params["max_peel_ratio"] * tx.total_output_sats

    def _follow(self, ctx: AnalysisContext, start: Transaction) -> list[Transaction]:
        """Follow the large output hop by hop until the pattern breaks."""
        chain = [start]
        current = start
        while len(chain) < self.params["min_chain_length"]:
            large = max(current.outputs, key=lambda o: o.value_sats)
            spend = ctx.chain.get_outspends(current.txid)[large.index]
            if not spend.get("spent") or not spend.get("txid"):
                break
            current = Transaction.from_esplora(ctx.chain.get_tx(spend["txid"]))
            if not self._is_peel(current):
                break
            chain.append(current)
        return chain
