from __future__ import annotations

from btc_aml.graph.change import detect_change
from btc_aml.model import Alert, Transaction, TxOutput
from btc_aml.rules.base import AnalysisContext, Rule, fmt_amount
from btc_aml.rules.references import EBA_CASP, FATF_PATTERNS


class AddressHopping(Rule):
    """Funds sent by the address are moved quickly through a chain of single-use addresses.

    Each intermediate address receives the funds once and forwards almost all of them
    within hours to another fresh address. This "hopping" adds distance between the
    funds and their origin without any economic reason: a classic layering technique.
    Followed forward from the address's own spends (a few API calls per hop).
    """

    rule_id = "R17_ADDRESS_HOPPING"
    name = "Address hopping (layering)"
    regulatory_reference = f"{FATF_PATTERNS}; {EBA_CASP}"
    required_params = ("min_hops", "max_hold_hours", "min_forward_ratio", "max_start_txs")

    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        address = ctx.profile.address
        spends = [tx for tx in ctx.profile.txs if address in tx.input_addresses]
        chains = []
        for tx in reversed(spends[-self.params["max_start_txs"] :]):
            payment = self._payment_output(tx, ctx.cluster)
            if payment is not None:
                chain = self._follow(ctx, tx, payment)
                if len(chain) - 1 >= self.params["min_hops"]:
                    chains.append(chain)
        if not chains:
            return []

        amount = sum(chain[0].sent_by(address) for chain in chains)
        hops = ", ".join(str(len(chain) - 1) for chain in chains)
        first = chains[0][0]
        return [
            self.make_alert(
                ctx,
                explanation=(
                    f"{len(chains)} outgoing payment(s) moved through chains of fresh single-use "
                    f"addresses ({hops} hops), each forwarding at least "
                    f"{self.params['min_forward_ratio']:.0%} within "
                    f"{self.params['max_hold_hours']}h. "
                    f"Value sent into the chains: {fmt_amount(amount, first.to_eur(amount))}."
                ),
                txids=[tx.txid for chain in chains for tx in chain],
                amount_sats=amount,
                amount_eur=first.to_eur(amount),
                hop_distance=max(len(chain) - 1 for chain in chains),
            )
        ]

    @staticmethod
    def _payment_output(tx: Transaction, own: frozenset[str]) -> TxOutput | None:
        """Largest output that is neither change nor one of our own addresses."""
        change = detect_change(tx)
        candidates = [
            o
            for o in tx.outputs
            if o.address and o.address not in own and (change is None or o is not change.output)
        ]
        return max(candidates, key=lambda o: o.value_sats, default=None)

    def _follow(
        self, ctx: AnalysisContext, start: Transaction, output: TxOutput
    ) -> list[Transaction]:
        chain = [start]
        current, received = start, output
        while len(chain) - 1 < self.params["min_hops"]:
            stats = ctx.chain.get_address_stats(received.address)["chain_stats"]  # type: ignore[arg-type]
            if stats["tx_count"] != 2:  # single use: funded once, spent once
                break
            spend = ctx.chain.get_outspends(current.txid)[received.index]
            if not spend.get("spent") or not spend.get("txid"):
                break
            nxt = Transaction.from_esplora(ctx.chain.get_tx(spend["txid"]))
            if not self._is_quick_forward(current, nxt, received):
                break
            chain.append(nxt)
            current, received = nxt, max(nxt.outputs, key=lambda o: o.value_sats)
            if received.address is None:
                break
        return chain

    def _is_quick_forward(
        self, previous: Transaction, nxt: Transaction, received: TxOutput
    ) -> bool:
        if previous.block_time is None or nxt.block_time is None:
            return False
        held = nxt.block_time - previous.block_time
        forwarded = max(o.value_sats for o in nxt.outputs)
        return (
            held <= self.params["max_hold_hours"] * 3600
            and forwarded >= self.params["min_forward_ratio"] * received.value_sats
        )
