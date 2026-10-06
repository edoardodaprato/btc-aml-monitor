"""Normalised data model used by rules, scoring and reports.

Esplora JSON is converted once into these immutable objects, so that rules work on
clear concepts (inputs, outputs, flows in satoshis and EUR) instead of raw API fields.

Bitcoin has no "accounts": a transaction consumes inputs and creates outputs. The
amount an address *sent* in a transaction is the value of its inputs minus any change
returned to it; the amount it *received* is the value of the outputs paid to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Any

SATS_PER_BTC = 100_000_000


def sats_to_btc(sats: int) -> float:
    return sats / SATS_PER_BTC


@dataclass(frozen=True)
class TxInput:
    address: str | None  # None for coinbase or non-standard scripts
    value_sats: int
    prev_txid: str
    prev_vout: int


@dataclass(frozen=True)
class TxOutput:
    address: str | None  # None for OP_RETURN and non-standard scripts
    value_sats: int
    index: int


@dataclass(frozen=True)
class Transaction:
    txid: str
    block_height: int | None
    block_hash: str | None
    block_time: int | None  # unix seconds; None if unconfirmed
    inputs: tuple[TxInput, ...]
    outputs: tuple[TxOutput, ...]
    fee_sats: int
    vsize: float
    is_coinbase: bool
    eur_price: float | None = None  # BTC/EUR on the block day, if available
    eur_price_date: str | None = None  # date of the price point actually used
    eur_price_source: str | None = None

    @classmethod
    def from_esplora(
        cls,
        raw: dict[str, Any],
        eur_price: float | None = None,
        eur_price_date: str | None = None,
        eur_price_source: str | None = None,
    ) -> Transaction:
        status = raw.get("status", {})
        is_coinbase = any(vin.get("is_coinbase") for vin in raw["vin"])
        inputs = tuple(
            TxInput(
                address=(vin.get("prevout") or {}).get("scriptpubkey_address"),
                value_sats=(vin.get("prevout") or {}).get("value", 0),
                prev_txid=vin["txid"],
                prev_vout=vin["vout"],
            )
            for vin in raw["vin"]
        )
        outputs = tuple(
            TxOutput(address=out.get("scriptpubkey_address"), value_sats=out["value"], index=i)
            for i, out in enumerate(raw["vout"])
        )
        return cls(
            txid=raw["txid"],
            block_height=status.get("block_height"),
            block_hash=status.get("block_hash"),
            block_time=status.get("block_time"),
            inputs=inputs,
            outputs=outputs,
            fee_sats=raw.get("fee", 0),
            vsize=raw.get("weight", 0) / 4,
            is_coinbase=is_coinbase,
            eur_price=eur_price,
            eur_price_date=eur_price_date,
            eur_price_source=eur_price_source,
        )

    @property
    def total_input_sats(self) -> int:
        return sum(i.value_sats for i in self.inputs)

    @property
    def total_output_sats(self) -> int:
        return sum(o.value_sats for o in self.outputs)

    @property
    def input_addresses(self) -> set[str]:
        return {i.address for i in self.inputs if i.address}

    @property
    def output_addresses(self) -> set[str]:
        return {o.address for o in self.outputs if o.address}

    @property
    def fee_rate(self) -> float:
        """Fee in sat/vB."""
        return self.fee_sats / self.vsize if self.vsize else 0.0

    def sent_by(self, address: str) -> int:
        return sum(i.value_sats for i in self.inputs if i.address == address)

    def received_by(self, address: str) -> int:
        return sum(o.value_sats for o in self.outputs if o.address == address)

    def net_flow(self, address: str) -> int:
        """Positive if the address gained value in this transaction, negative if it lost."""
        return self.received_by(address) - self.sent_by(address)

    def flow_between(self, source: str, destination: str) -> int:
        """Estimated value moved from ``source`` to ``destination`` in this transaction.

        Bitcoin does not link specific inputs to specific outputs, so the value paid to
        ``destination`` is attributed pro rata to the share of inputs owned by
        ``source`` (the "haircut" method used in exposure analysis).
        """
        total_in = self.total_input_sats
        if total_in == 0:
            return 0
        return round(self.received_by(destination) * self.sent_by(source) / total_in)

    def to_eur(self, sats: int) -> float | None:
        return None if self.eur_price is None else sats_to_btc(sats) * self.eur_price


class Direction(Enum):
    IN = "in"
    OUT = "out"


@dataclass(frozen=True)
class Flow:
    """What one transaction meant for the analysed address."""

    tx: Transaction
    direction: Direction
    amount_sats: int  # net amount: change returned to the address is excluded

    @property
    def amount_eur(self) -> float | None:
        return self.tx.to_eur(self.amount_sats)


@dataclass(frozen=True)
class AddressProfile:
    """An address and its analysed transaction history (oldest first)."""

    address: str
    txs: tuple[Transaction, ...]
    tx_count_total: int  # full on-chain count, may exceed len(txs)
    total_received_sats: int  # full history, from the API counters
    total_sent_sats: int
    truncated: bool  # True if older transactions were not downloaded

    @property
    def balance_sats(self) -> int:
        return self.total_received_sats - self.total_sent_sats

    @property
    def first_seen(self) -> int | None:
        """Time of the oldest *analysed* transaction (older ones exist if truncated)."""
        return self.txs[0].block_time if self.txs else None

    @property
    def last_seen(self) -> int | None:
        return self.txs[-1].block_time if self.txs else None

    @cached_property
    def flows(self) -> list[Flow]:
        """One flow per transaction, oldest first; self-transfers (net 0) are skipped."""
        result = []
        for tx in self.txs:
            net = tx.net_flow(self.address)
            if net > 0:
                result.append(Flow(tx, Direction.IN, net))
            elif net < 0:
                result.append(Flow(tx, Direction.OUT, -net))
        return result

    @property
    def volume_sats(self) -> int:
        """Total value moved (in + out) in the analysed transactions."""
        return sum(flow.amount_sats for flow in self.flows)

    def balance_timeline(self) -> list[tuple[Transaction, int]]:
        """Balance after each analysed transaction.

        The starting balance is reconstructed backwards from the current balance, so
        the timeline is exact even when the oldest transactions were not downloaded.
        """
        net_total = sum(tx.net_flow(self.address) for tx in self.txs)  # = in - out
        balance = self.balance_sats - net_total
        timeline = []
        for tx in self.txs:
            balance += tx.net_flow(self.address)
            timeline.append((tx, balance))
        return timeline

    @cached_property
    def counterparties(self) -> dict[str, CounterpartyFlows]:
        """Addresses that sent value to, or received value from, the analysed address."""
        result: dict[str, CounterpartyFlows] = {}
        for tx in self.txs:
            for source in tx.input_addresses - {self.address}:
                received = tx.flow_between(source, self.address)
                if received:
                    result.setdefault(source, CounterpartyFlows(source)).add_in(tx, received)
            for destination in tx.output_addresses - {self.address}:
                sent = tx.flow_between(self.address, destination)
                if sent:
                    result.setdefault(destination, CounterpartyFlows(destination)).add_out(tx, sent)
        return result


@dataclass
class CounterpartyFlows:
    """Value exchanged between the analysed address and one counterparty."""

    address: str
    received_from_sats: int = 0  # counterparty -> analysed address
    sent_to_sats: int = 0  # analysed address -> counterparty
    received_from_eur: float | None = 0.0
    sent_to_eur: float | None = 0.0
    txids: list[str] = field(default_factory=list)

    def add_in(self, tx: Transaction, sats: int) -> None:
        self.received_from_sats += sats
        self.received_from_eur = _add_eur(self.received_from_eur, tx.to_eur(sats))
        self._add_txid(tx.txid)

    def add_out(self, tx: Transaction, sats: int) -> None:
        self.sent_to_sats += sats
        self.sent_to_eur = _add_eur(self.sent_to_eur, tx.to_eur(sats))
        self._add_txid(tx.txid)

    @property
    def total_sats(self) -> int:
        return self.received_from_sats + self.sent_to_sats

    @property
    def total_eur(self) -> float | None:
        if self.received_from_eur is None or self.sent_to_eur is None:
            return None
        return self.received_from_eur + self.sent_to_eur

    def _add_txid(self, txid: str) -> None:
        if txid not in self.txids:
            self.txids.append(txid)


def _add_eur(total: float | None, amount: float | None) -> float | None:
    """EUR totals become None (unknown) as soon as one component has no price."""
    if total is None or amount is None:
        return None
    return total + amount


@dataclass(frozen=True)
class Alert:
    """One red flag raised by one rule on one address, with its evidence.

    ``strength`` (0-1) scales the rule weight in the score: 1.0 for a direct finding,
    lower for indirect exposure (hop decay). ``hop_distance`` is 0 when the finding is
    about the address itself, 1 for a direct counterparty, 2+ for indirect exposure.
    """

    rule_id: str
    rule_name: str
    address: str
    severity: str
    regulatory_reference: str
    explanation: str
    evidence_txids: tuple[str, ...]
    amount_sats: int
    amount_eur: float | None
    hop_distance: int = 0
    strength: float = 1.0
