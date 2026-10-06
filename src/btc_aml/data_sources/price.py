"""Historical BTC/EUR price from mempool.space.

mempool.space returns the closest *earlier* price point it has: hourly for recent
dates, weekly for older ones (e.g. 2015-2021), nothing before July 2010 (it answers
0). We ask for the transaction's UTC day and accept a price dated up to
``MAX_PRICE_AGE_DAYS`` before it; the date of the price actually used is kept for the
audit trail. When no acceptable price exists, or the service is unreachable, the
quote is None: rules then fall back to BTC thresholds and say so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import DataSourceError, HttpClient

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400
MAX_PRICE_AGE_DAYS = 7


@dataclass(frozen=True)
class PriceQuote:
    eur: float
    as_of: str  # ISO date of the price point used


class PriceService:
    """BTC/EUR price lookup with permanent caching."""

    def __init__(self, http: HttpClient, cache: Cache) -> None:
        self._http = http
        self._cache = cache

    def eur_quote(self, timestamp: int) -> PriceQuote | None:
        """BTC/EUR price for the UTC day of ``timestamp``, or None if unavailable."""
        day = timestamp - timestamp % SECONDS_PER_DAY
        cached = self._cache.get("price_eur", str(day))
        if cached is not None:
            return PriceQuote(**cached["quote"]) if cached["quote"] else None

        try:
            data = self._http.get_json(
                "/v1/historical-price",
                params={"currency": "EUR", "timestamp": day},
                primary_only=True,  # Blockstream has no price endpoint
            )
        except DataSourceError as exc:
            logger.warning("BTC/EUR price unavailable for %s: %s", day, exc)
            return None  # not cached: the service may be back later

        quote = _extract_quote(data, day)
        self._cache.put("price_eur", str(day), {"quote": quote.__dict__ if quote else None})
        return quote


def _extract_quote(data: dict[str, Any], day: int) -> PriceQuote | None:
    """Accept a positive price dated on the requested day or at most a week earlier."""
    prices = data.get("prices") or []
    if not prices:
        return None
    entry = prices[0]
    eur = entry.get("EUR") or 0
    price_time = entry.get("time", 0)
    age = day - price_time
    if eur <= 0 or not -SECONDS_PER_DAY < age <= MAX_PRICE_AGE_DAYS * SECONDS_PER_DAY:
        return None
    as_of = datetime.fromtimestamp(price_time, UTC).date().isoformat()
    return PriceQuote(eur=float(eur), as_of=as_of)
