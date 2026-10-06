"""Esplora API client (mempool.space / Blockstream) with local caching.

Only *confirmed* transactions are cached forever: an unconfirmed transaction can still
be replaced or dropped. Address histories are cached with a time-to-live, because new
transactions can arrive at any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import HttpClient

TXS_PER_PAGE = 25  # fixed page size of /address/:address/txs/chain


@dataclass(frozen=True)
class AddressHistory:
    """Confirmed transactions of an address, newest first."""

    address: str
    txs: list[dict[str, Any]]
    truncated: bool  # True if the history was cut at ``max_txs``


class EsploraClient:
    """Typed access to the Esplora endpoints used by the analysis."""

    def __init__(self, http: HttpClient, cache: Cache, address_ttl_hours: float) -> None:
        self._http = http
        self._cache = cache
        self._address_ttl_seconds = address_ttl_hours * 3600

    def get_tx(self, txid: str) -> dict[str, Any]:
        cached = self._cache.get("tx", txid)
        if cached is not None:
            return cached
        tx = self._http.get_json(f"/tx/{txid}")
        self._store_tx(tx)
        return tx

    def get_address_stats(self, address: str) -> dict[str, Any]:
        """Aggregated counters (tx count, funded/spent sums) for an address."""
        cached = self._cache.get("address", address, max_age_seconds=self._address_ttl_seconds)
        if cached is not None:
            return cached
        stats = self._http.get_json(f"/address/{address}")
        self._cache.put("address", address, stats)
        return stats

    def get_address_history(self, address: str, max_txs: int) -> AddressHistory:
        """Confirmed transactions of ``address`` (newest first), at most ``max_txs``."""
        key = f"{address}|{max_txs}"
        cached = self._cache.get("address_txs", key, max_age_seconds=self._address_ttl_seconds)
        if cached is not None:
            txs = [self.get_tx(txid) for txid in cached["txids"]]
            return AddressHistory(address, txs, cached["truncated"])

        txs, truncated = self._download_history(address, max_txs)
        for tx in txs:
            self._store_tx(tx)
        self._cache.put(
            "address_txs", key, {"txids": [tx["txid"] for tx in txs], "truncated": truncated}
        )
        return AddressHistory(address, txs, truncated)

    def _download_history(self, address: str, max_txs: int) -> tuple[list[dict[str, Any]], bool]:
        txs: list[dict[str, Any]] = []
        path = f"/address/{address}/txs/chain"
        while True:
            page = self._http.get_json(path)
            txs.extend(page)
            if len(page) < TXS_PER_PAGE:
                return txs[:max_txs], len(txs) > max_txs
            if len(txs) >= max_txs:
                return txs[:max_txs], True
            path = f"/address/{address}/txs/chain/{page[-1]['txid']}"

    def _store_tx(self, tx: dict[str, Any]) -> None:
        if tx.get("status", {}).get("confirmed"):
            self._cache.put("tx", tx["txid"], tx)
