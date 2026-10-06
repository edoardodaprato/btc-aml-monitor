"""Address clustering with the common-input-ownership heuristic.

To spend coins, a wallet must sign every input of a transaction; so all input
addresses of a transaction are normally controlled by the same entity. Linking them
(and linking each detected change output to its sender) groups addresses into
clusters that approximate wallets. CoinJoin transactions are excluded: there the
inputs belong to different people by design, and merging them would be wrong.
"""

from __future__ import annotations

from collections.abc import Iterable

from btc_aml.config import CoinJoinConfig
from btc_aml.graph.change import detect_change
from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import Transaction


class UnionFind:
    """Disjoint sets of addresses (path compression + union by size)."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        self._size.setdefault(item, 1)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return
        if self._size[root_a] < self._size[root_b]:
            root_a, root_b = root_b, root_a
        self._parent[root_b] = root_a
        self._size[root_a] += self._size[root_b]

    def groups(self) -> list[set[str]]:
        result: dict[str, set[str]] = {}
        for item in self._parent:
            result.setdefault(self.find(item), set()).add(item)
        return list(result.values())


def cluster_transactions(txs: Iterable[Transaction], coinjoin: CoinJoinConfig) -> UnionFind:
    """Link co-spent inputs and detected change outputs of non-CoinJoin transactions."""
    clusters = UnionFind()
    for tx in txs:
        if tx.is_coinbase or detect_coinjoin(tx, coinjoin):
            continue
        inputs = sorted(tx.input_addresses)
        for address in inputs:
            clusters.union(inputs[0], address)
        change = detect_change(tx)
        if inputs and change and change.output.address:
            clusters.union(inputs[0], change.output.address)
    return clusters


def address_cluster(
    address: str, txs: Iterable[Transaction], coinjoin: CoinJoinConfig
) -> frozenset[str]:
    """Addresses probably controlled by the same entity as ``address``.

    Only transactions *spent* by the address are used: in a transaction where it merely
    receives, the inputs and the change belong to the sender, and a wrong change guess
    would wrongly merge the sender into the address's cluster.
    """
    spends = [tx for tx in txs if address in tx.input_addresses]
    clusters = cluster_transactions(spends, coinjoin)
    clusters.find(address)  # make sure the address itself is a member
    return frozenset(next(group for group in clusters.groups() if address in group))
