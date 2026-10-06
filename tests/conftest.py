"""Shared pytest fixtures.

Tests never touch the network: ``FakeEsplora`` serves the real API responses saved
under ``tests/fixtures`` through an in-memory httpx transport.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import httpx
import pytest

from btc_aml.config import AppConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

FIXTURE_TXID = "7a86eb72b432ce2440aca3d8c71a4a5ec92645e4678ccb211c0ce41d882753ee"
FIXTURE_ADDRESS = "bc1q0kuxrryekd8tdh8rt7dclzafq9wptp68s8h037"  # 41 confirmed txs
FIXTURE_ADDRESS_TX_COUNT = 41


def load_fixture(relative_path: str):
    return json.loads((FIXTURES / relative_path).read_text())


class FakeEsplora:
    """Routes Esplora/price requests to saved fixtures and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, object] = {}
        self.fail_status: int | None = None  # set to simulate an outage
        for path in (FIXTURES / "esplora").glob("*.json"):
            self._register(path.stem, json.loads(path.read_text()))
        self._price_tx = load_fixture("price_tx.json")
        self._price_2010 = load_fixture("price_2010.json")

    def _register(self, stem: str, body: object) -> None:
        if stem.startswith("tx_"):
            self.routes[f"/api/tx/{stem[3:]}"] = body
        elif stem.endswith("_chain_p1"):
            address = stem.removeprefix("address_").removesuffix("_chain_p1")
            self.routes[f"/api/address/{address}/txs/chain"] = body
        elif stem.endswith("_chain_p2"):
            address = stem.removeprefix("address_").removesuffix("_chain_p2")
            first_page = load_fixture(f"esplora/address_{address}_chain_p1.json")
            self.routes[f"/api/address/{address}/txs/chain/{first_page[-1]['txid']}"] = body
        elif stem.startswith("address_"):
            self.routes[f"/api/address/{stem[8:]}"] = body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_status is not None:
            return httpx.Response(self.fail_status)
        path = request.url.path
        if path == "/api/v1/historical-price":
            day = int(request.url.params["timestamp"])
            body = (
                self._price_tx if day == self._price_tx["prices"][0]["time"] else self._price_2010
            )
            return httpx.Response(200, json=body)
        if path in self.routes:
            return httpx.Response(200, json=self.routes[path])
        return httpx.Response(404, text="Not found")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A writable copy of the project's default config folder."""
    target = tmp_path / "config"
    shutil.copytree(PROJECT_ROOT / "config", target)
    return target


@pytest.fixture
def app_config(config_dir: Path, tmp_path: Path) -> AppConfig:
    """Default configuration with a temporary cache and no real waiting between requests."""
    config = load_config(config_dir)
    cache = dataclasses.replace(config.cache, path=tmp_path / "cache.sqlite")
    sources = dataclasses.replace(
        config.data_sources, backoff_base_seconds=0, requests_per_second=1_000_000
    )
    return dataclasses.replace(config, cache=cache, data_sources=sources)


@pytest.fixture
def fake_esplora() -> FakeEsplora:
    return FakeEsplora()
