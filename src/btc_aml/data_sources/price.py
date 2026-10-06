"""Historical BTC/EUR price from mempool.space, with an ECB-based fallback.

mempool.space returns the closest *earlier* price point it has: hourly for recent
dates, weekly for older ones (e.g. 2015-2021), nothing before July 2010 (it answers
0). We ask for the transaction's UTC day and accept a point dated up to
``MAX_PRICE_AGE_DAYS`` before it.

Some points have a USD price but no EUR price (EUR = -1). When ECB rates are loaded,
the EUR price is then derived as USD price / ECB EUR-USD reference rate. Every quote
states its date and source, so each EUR amount in the reports can be audited. When no
price can be determined the quote is None and rules fall back to BTC thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.ecb import EcbRates
from btc_aml.data_sources.http import DataSourceError, HttpClient

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400
MAX_PRICE_AGE_DAYS = 7
SOURCE_MEMPOOL_EUR = "mempool.space EUR"
SOURCE_MEMPOOL_USD_ECB = "mempool.space USD / ECB EUR-USD"


@dataclass(frozen=True)
class PriceQuote:
    eur: float
    as_of: str  # ISO date of the price point used
    source: str


class PriceService:
    """BTC/EUR price lookup. Raw price points are cached forever."""

    def __init__(self, http: HttpClient, cache: Cache, fx: EcbRates | None = None) -> None:
        self._http = http
        self._cache = cache
        self._fx = fx

    def eur_quote(self, timestamp: int) -> PriceQuote | None:
        """BTC/EUR price for the UTC day of ``timestamp``, or None if unavailable."""
        day = timestamp - timestamp % SECONDS_PER_DAY
        point = self._price_point(day)
        if point is None:
            return None
        return quote_from_point(point, day, self._fx)

    def _price_point(self, day: int) -> dict[str, Any] | None:
        cached = self._cache.get("price_point", str(day))
        if cached is not None:
            return cached
        try:
            data = self._http.get_json(
                "/v1/historical-price",
                params={"currency": "EUR", "timestamp": day},
                primary_only=True,  # Blockstream has no price endpoint
            )
        except DataSourceError as exc:
            logger.warning("BTC price unavailable for %s: %s", day, exc)
            return None  # not cached: the service may be back later
        prices = data.get("prices") or [{}]
        point = {key: prices[0].get(key) for key in ("time", "EUR", "USD")}
        self._cache.put("price_point", str(day), point)
        return point


def quote_from_point(point: dict[str, Any], day: int, fx: EcbRates | None) -> PriceQuote | None:
    """Turn a raw price point into a quote, if it is recent enough and usable."""
    price_time = point.get("time") or 0
    age = day - price_time
    if not -SECONDS_PER_DAY < age <= MAX_PRICE_AGE_DAYS * SECONDS_PER_DAY:
        return None
    price_date = datetime.fromtimestamp(price_time, UTC).date()

    eur = point.get("EUR") or 0
    if eur > 0:
        return PriceQuote(float(eur), price_date.isoformat(), SOURCE_MEMPOOL_EUR)

    usd = point.get("USD") or 0
    rate = fx.rate_on(price_date) if fx and usd > 0 else None
    if rate is None:
        return None
    usd_per_eur, rate_date = rate
    return PriceQuote(
        round(usd / usd_per_eur, 2),
        price_date.isoformat(),
        f"{SOURCE_MEMPOOL_USD_ECB} ({rate_date})",
    )
