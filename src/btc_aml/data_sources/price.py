"""Historical BTC/EUR price from mempool.space, at daily granularity.

Amounts are converted to EUR using the price of the transaction's day (UTC). When no
price exists (mempool.space has no data before mid-2010 and returns 0) or the service
is unreachable, ``eur_price`` returns None: rules then fall back to BTC thresholds and
the alert states that the EUR value is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import DataSourceError, HttpClient

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400


class PriceService:
    """BTC/EUR daily price lookup with permanent caching."""

    def __init__(self, http: HttpClient, cache: Cache) -> None:
        self._http = http
        self._cache = cache

    def eur_price(self, timestamp: int) -> float | None:
        """BTC/EUR price on the UTC day of ``timestamp``, or None if unavailable."""
        day = timestamp - timestamp % SECONDS_PER_DAY
        cached = self._cache.get("price_eur", str(day))
        if cached is not None:
            return cached["eur"]

        try:
            data = self._http.get_json(
                "/v1/historical-price",
                params={"currency": "EUR", "timestamp": day},
                primary_only=True,  # Blockstream has no price endpoint
            )
        except DataSourceError as exc:
            logger.warning("BTC/EUR price unavailable for %s: %s", day, exc)
            return None  # not cached: the service may be back later

        price = _extract_price(data, day)
        self._cache.put("price_eur", str(day), {"eur": price})
        return price


def _extract_price(data: dict[str, Any], day: int) -> float | None:
    """Accept the answer only if it is a positive price for the requested day."""
    prices = data.get("prices") or []
    if not prices:
        return None
    entry = prices[0]
    eur = entry.get("EUR") or 0
    if eur <= 0 or abs(entry.get("time", 0) - day) >= SECONDS_PER_DAY:
        return None
    return float(eur)
