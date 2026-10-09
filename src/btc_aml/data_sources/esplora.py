"""Esplora API client (mempool.space / Blockstream) with local caching.

Only *confirmed* transactions are cached forever: an unconfirmed transaction can still
be replaced or dropped. Address histories are cached with a time-to-live, because new
transactions can arrive at any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import DataSourceError, HttpClient

TXS_PER_PAGE = 25  # fixed page size of /address/:address/txs/chain and /block/:hash/txs


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

    def get_outspends(self, txid: str) -> list[dict[str, Any]]:
        """For each output of ``txid``: whether it is spent, and by which transaction."""
        cached = self._cache.get("outspends", txid, max_age_seconds=self._address_ttl_seconds)
        if cached is not None:
            return cached
        outspends = self._http.get_json(f"/tx/{txid}/outspends")
        self._cache.put("outspends", txid, outspends)
        return outspends

    def get_block_median_fee_rate(self, block_hash: str) -> float | None:
        """Median fee rate (sat/vB) of a block, or None if unavailable.

        Only mempool.space publishes block fee statistics (``extras.feeRange`` holds the
        min, 10th, 25th, 50th, 75th, 90th percentiles and max); there is no fallback.
        """
        cached = self._cache.get("block_fee", block_hash)
        if cached is not None:
            return cached["median"]
        try:
            block = self._http.get_json(f"/v1/block/{block_hash}", primary_only=True)
        except DataSourceError:
            return None
        fee_range = block.get("extras", {}).get("feeRange") or []
        median = float(fee_range[3]) if len(fee_range) == 7 else None
        self._cache.put("block_fee", block_hash, {"median": median})
        return median

    def get_tip_height(self) -> int:
        """Height of the latest block (never cached: it changes every ~10 minutes)."""
        return int(self._http.get_text("/blocks/tip/height"))

    def get_block_hash(self, height: int) -> str:
        """Hash of the block at ``height`` in the current best chain.

        Cached with the address time-to-live: the most recent blocks can still be
        replaced by a chain reorganisation, so the mapping is not permanent.
        """
        key = str(height)
        cached = self._cache.get("block_hash", key, max_age_seconds=self._address_ttl_seconds)
        if cached is not None:
            return cached["hash"]
        block_hash = self._http.get_text(f"/block-height/{height}")
        self._cache.put("block_hash", key, {"hash": block_hash})
        return block_hash

    def get_block(self, block_hash: str) -> dict[str, Any]:
        """Block header data (height, timestamp, tx_count); immutable, cached forever."""
        cached = self._cache.get("block", block_hash)
        if cached is not None:
            return cached
        block = self._http.get_json(f"/block/{block_hash}")
        self._cache.put("block", block_hash, block)
        return block

    def get_block_txs(self, block_hash: str, tx_count: int) -> list[dict[str, Any]]:
        """Every transaction of a block, in block order (one request per 25 transactions).

        A full block holds 2,000-5,000 transactions, i.e. 80-200 requests: slow on a
        public API, but done only once thanks to the cache.
        """
        cached = self._cache.get("block_txs", block_hash)
        if cached is not None:
            return [self.get_tx(txid) for txid in cached["txids"]]
        txs: list[dict[str, Any]] = []
        for start in range(0, tx_count, TXS_PER_PAGE):
            txs.extend(self._http.get_json(f"/block/{block_hash}/txs/{start}"))
        for tx in txs:
            self._store_tx(tx)
        self._cache.put("block_txs", block_hash, {"txids": [tx["txid"] for tx in txs]})
        return txs

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
