"""Multi-hop exposure: where did the funds come from, where did they go?

Starting from the analysed address, funds are followed hop by hop, in both directions:

* **incoming** (source of funds): who paid the counterparties that paid us;
* **outgoing** (destination of funds): whom the counterparties we paid paid next.

At each hop the value is attributed pro rata ("haircut"): if a counterparty received
10% of its inflows from address X before paying us, 10% of what it paid us is treated
as coming from X. Time order is respected: for incoming exposure only flows that
happened *before* the counterparty paid us count, for outgoing only flows *after* we
paid it.

The search is bounded, because a naive expansion explodes after two hops:

* at most ``max_hops`` hops (default 2, hard cap 3);
* at most ``max_addresses_per_hop`` addresses expanded per hop, largest flows first;
* at most ``max_tx_per_expanded_address`` transactions downloaded per expanded address;
* addresses with more than ``high_degree_threshold`` transactions (exchanges and other
  services) are *not* expanded: they are recorded as "high-degree nodes" and treated as
  entities, because pro-rata attribution through a service's pooled wallet is meaningless;
* a time budget (``max_analysis_seconds``) per analysed address.

When a limit (or an API error) stops the search early, the result says so
(``complete`` and ``notes``) and the reports carry that note.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from btc_aml.config import ExposureConfig
from btc_aml.data_sources.esplora import AddressHistory
from btc_aml.data_sources.http import DataSourceError
from btc_aml.graph.change import detect_change
from btc_aml.model import AddressProfile, Direction, Transaction
from btc_aml.screening import Screener, ScreeningHit


class AddressSource(Protocol):
    def get_address_stats(self, address: str) -> dict[str, Any]: ...

    def get_address_history(self, address: str, max_txs: int) -> AddressHistory: ...


@dataclass(frozen=True)
class ExposureHit:
    """A listed address reached through the transaction graph."""

    address: str
    hop: int  # 2 = counterparty of a counterparty
    direction: Direction  # IN: funds came from it; OUT: funds went to it
    amount_sats: int  # estimated share of the analysed address's flows
    amount_eur: float | None
    path: tuple[str, ...]  # analysed address ... listed address
    txids: tuple[str, ...]
    hits: tuple[ScreeningHit, ...]


@dataclass(frozen=True)
class RoundTrip:
    """Funds that left the analysed address (or its cluster) and came back."""

    path: tuple[str, ...]
    amount_sats: int
    amount_eur: float | None
    txids: tuple[str, ...]


@dataclass
class ExposureResult:
    hits: list[ExposureHit] = field(default_factory=list)
    round_trips: list[RoundTrip] = field(default_factory=list)
    high_degree_nodes: set[str] = field(default_factory=set)
    expanded: int = 0
    complete: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Edge:
    """A unit of work: value carried to ``address`` along ``path``."""

    address: str
    direction: Direction
    hop: int
    path: tuple[str, ...]
    sats: int
    eur: float | None
    txids: tuple[str, ...]
    time_bound: int  # IN: latest time that counts; OUT: earliest time that counts


def compute_exposure(
    profile: AddressProfile,
    cluster: frozenset[str],
    screener: Screener,
    source: AddressSource,
    config: ExposureConfig,
    clock: Callable[[], float] = time.monotonic,
) -> ExposureResult:
    result = ExposureResult()
    deadline = clock() + config.max_analysis_seconds
    min_sats = max(1, int(profile.volume_sats * config.min_carried_share))
    frontier = _seed_edges(profile, cluster)
    expanded: set[tuple[str, Direction]] = set()

    for hop in range(1, config.max_hops):
        frontier = [e for e in frontier if e.sats >= min_sats]
        frontier.sort(key=lambda e: e.sats, reverse=True)
        if len(frontier) > config.max_addresses_per_hop:
            result.complete = False
            result.notes.append(
                f"hop {hop}: expanded {config.max_addresses_per_hop} of {len(frontier)} "
                "addresses (largest flows first)"
            )
            frontier = frontier[: config.max_addresses_per_hop]

        next_frontier: list[_Edge] = []
        for edge in frontier:
            if clock() > deadline:
                result.complete = False
                result.notes.append(f"time budget of {config.max_analysis_seconds}s reached")
                return result
            if (edge.address, edge.direction) in expanded:
                continue
            expanded.add((edge.address, edge.direction))
            try:
                next_frontier.extend(
                    _expand(edge, profile.address, cluster, screener, source, config, result)
                )
            except DataSourceError as exc:
                result.complete = False
                result.notes.append(f"{edge.address} not expanded: {exc}")
        frontier = next_frontier
    return result


def _seed_edges(profile: AddressProfile, cluster: frozenset[str]) -> list[_Edge]:
    """Hop-1 counterparties (direct exposure is screened by the direct rules)."""
    edges = []
    for flows in profile.counterparties.values():
        if flows.address in cluster:
            continue  # our own change or co-spending address, not a counterparty
        txs = [tx for tx in profile.txs if tx.txid in flows.txids and tx.block_time]
        if flows.received_from_sats and txs:
            edges.append(
                _Edge(
                    flows.address,
                    Direction.IN,
                    1,
                    (profile.address, flows.address),
                    flows.received_from_sats,
                    flows.received_from_eur,
                    tuple(flows.txids),
                    max(tx.block_time for tx in txs),  # type: ignore[type-var]
                )
            )
        if flows.sent_to_sats and txs:
            edges.append(
                _Edge(
                    flows.address,
                    Direction.OUT,
                    1,
                    (profile.address, flows.address),
                    flows.sent_to_sats,
                    flows.sent_to_eur,
                    tuple(flows.txids),
                    min(tx.block_time for tx in txs),  # type: ignore[type-var]
                )
            )
    return edges


def _expand(
    edge: _Edge,
    origin: str,
    cluster: frozenset[str],
    screener: Screener,
    source: AddressSource,
    config: ExposureConfig,
    result: ExposureResult,
) -> list[_Edge]:
    """Follow the funds one hop further from ``edge.address``."""
    stats = source.get_address_stats(edge.address)["chain_stats"]
    if stats["tx_count"] > config.high_degree_threshold:
        result.high_degree_nodes.add(edge.address)
        return []

    history = source.get_address_history(edge.address, config.max_tx_per_expanded_address)
    result.expanded += 1
    node = edge.address
    txs = [Transaction.from_esplora(raw) for raw in history.txs]
    flows = _flows_in_window(node, txs, edge)
    total = sum(amount for amount, _, _ in flows.values())
    if total == 0:
        return []

    edges = []
    for other, (amount, txids, bound) in flows.items():
        share = amount / total
        carried = round(edge.sats * share)
        eur = None if edge.eur is None else edge.eur * share
        path = (*edge.path, other)
        all_txids = (*edge.txids, *txids)
        if other == origin or other in cluster:
            if edge.direction is Direction.OUT:
                result.round_trips.append(RoundTrip(path, carried, eur, all_txids))
            continue
        hop = edge.hop + 1
        hits = tuple(screener.screen(other))
        if hits:
            result.hits.append(
                ExposureHit(other, hop, edge.direction, carried, eur, path, all_txids, hits)
            )
        edges.append(_Edge(other, edge.direction, hop, path, carried, eur, all_txids, bound))
    return edges


def _flows_in_window(
    node: str, txs: list[Transaction], edge: _Edge
) -> dict[str, tuple[int, list[str], int]]:
    """Counterparties of ``node`` in the relevant direction and time window.

    Returns {address: (value, txids, time bound for the next hop)}.
    """
    flows: dict[str, tuple[int, list[str], int]] = {}
    for tx in txs:
        if tx.block_time is None:
            continue
        spends = node in tx.input_addresses
        if edge.direction is Direction.IN and not spends and tx.block_time <= edge.time_bound:
            pairs = [(src, tx.flow_between(src, node)) for src in tx.input_addresses]
            pick_bound = max
        elif edge.direction is Direction.OUT and spends and tx.block_time >= edge.time_bound:
            change = detect_change(tx)
            own = {node, change.output.address if change else None}
            pairs = [(dst, tx.flow_between(node, dst)) for dst in tx.output_addresses - own]
            pick_bound = min
        else:
            continue
        for other, amount in pairs:
            if amount <= 0:
                continue
            value, txids, bound = flows.get(other, (0, [], tx.block_time))
            flows[other] = (value + amount, [*txids, tx.txid], pick_bound(bound, tx.block_time))
    return flows
