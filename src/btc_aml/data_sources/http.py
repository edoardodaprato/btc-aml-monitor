"""HTTP layer shared by all public APIs: rate limiting, retries, backoff and fallback.

Public APIs are free but rate-limited, and occasionally unavailable. Every request:

1. waits so that we never exceed ``requests_per_second`` (we are a polite client);
2. is retried on network errors, HTTP 429 and HTTP 5xx with exponential backoff
   (honouring the ``Retry-After`` header when the server sends one);
3. falls back to the secondary Esplora API if the primary keeps failing.

Requests the server explicitly rejects (HTTP 400/404, e.g. an invalid address) are
not retried: asking again, or asking another server, would not change the answer.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from btc_aml import __version__
from btc_aml.config import DataSourceConfig

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class DataSourceError(RuntimeError):
    """All configured sources failed to answer a request."""


class RequestRejectedError(DataSourceError):
    """The server answered with a definitive client error (e.g. 400 or 404)."""

    def __init__(self, url: str, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code} for {url}: {detail}")
        self.status_code = status_code


class HttpClient:
    """Polite JSON/text client with automatic failover between two Esplora APIs."""

    def __init__(
        self,
        config: DataSourceConfig,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            transport=transport,
            headers={"User-Agent": f"btc-aml-monitor/{__version__}"},
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._min_interval = 1.0 / config.requests_per_second
        self._next_request_at = 0.0
        self.requests_by_source: Counter[str] = Counter()

    def get_json(
        self, path: str, params: dict[str, Any] | None = None, *, primary_only: bool = False
    ) -> Any:
        return self._get(path, params, primary_only).json()

    def get_text(self, path: str, *, primary_only: bool = False) -> str:
        return self._get(path, None, primary_only).text.strip()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None, primary_only: bool) -> httpx.Response:
        bases = [self._config.primary_url]
        if not primary_only:
            bases.append(self._config.fallback_url)

        errors = []
        for base in bases:
            try:
                response = self._get_with_retries(base + path, params)
            except RequestRejectedError:
                raise
            except DataSourceError as exc:
                logger.warning("Source %s failed: %s", _host(base), exc)
                errors.append(str(exc))
                continue
            self.requests_by_source[_host(base)] += 1
            return response
        raise DataSourceError(f"All data sources failed for {path}: {'; '.join(errors)}")

    def _get_with_retries(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        last_error = ""
        for attempt in range(self._config.max_retries + 1):
            self._throttle()
            retry_after = None
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in _RETRYABLE_STATUS:
                    raise RequestRejectedError(url, response.status_code, response.text[:200])
                last_error = f"HTTP {response.status_code}"
                retry_after = _parse_retry_after(response)

            if attempt < self._config.max_retries:
                delay = retry_after or self._config.backoff_base_seconds * 2**attempt
                logger.info("Retrying %s in %.1fs (%s)", url, delay, last_error)
                self._sleep(delay)
        raise DataSourceError(
            f"{url} failed after {self._config.max_retries + 1} attempts: {last_error}"
        )

    def _throttle(self) -> None:
        now = self._monotonic()
        if now < self._next_request_at:
            self._sleep(self._next_request_at - now)
            now = self._next_request_at
        self._next_request_at = now + self._min_interval


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


def _host(base_url: str) -> str:
    return urlparse(base_url).netloc
