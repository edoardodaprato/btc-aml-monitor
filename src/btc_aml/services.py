"""Wire the data-source objects together from the configuration."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from btc_aml.config import AppConfig
from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.ecb import EcbRates, load_ecb_rates
from btc_aml.data_sources.esplora import EsploraClient
from btc_aml.data_sources.http import HttpClient
from btc_aml.data_sources.price import PriceService


@dataclass
class Services:
    """Everything an analysis needs to read blockchain and price data."""

    cache: Cache
    http: HttpClient
    esplora: EsploraClient
    prices: PriceService
    fx: EcbRates | None

    @classmethod
    def from_config(
        cls, config: AppConfig, transport: httpx.BaseTransport | None = None
    ) -> Services:
        """Build the services; ``transport`` lets tests replace the network."""
        cache = Cache(config.cache.path)
        http = HttpClient(config.data_sources, transport=transport)
        fx = load_ecb_rates(config.fx_local_path)
        return cls(
            cache=cache,
            http=http,
            esplora=EsploraClient(http, cache, config.cache.address_ttl_hours),
            prices=PriceService(http, cache, fx),
            fx=fx,
        )

    def close(self) -> None:
        self.http.close()
        self.cache.close()

    def __enter__(self) -> Services:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
