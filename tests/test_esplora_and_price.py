"""Tests for the Esplora client and the BTC/EUR price service (offline fixtures)."""

from __future__ import annotations

from btc_aml.config import AppConfig
from btc_aml.data_sources.price import PriceQuote, _extract_quote
from btc_aml.services import Services
from tests.conftest import (
    FIXTURE_ADDRESS,
    FIXTURE_ADDRESS_TX_COUNT,
    FIXTURE_TXID,
    FakeEsplora,
    load_fixture,
)


def test_get_tx_is_cached(app_config: AppConfig, fake_esplora: FakeEsplora) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        first = services.esplora.get_tx(FIXTURE_TXID)
        second = services.esplora.get_tx(FIXTURE_TXID)

    assert first == second
    assert first["txid"] == FIXTURE_TXID
    assert len(fake_esplora.requests) == 1


def test_unconfirmed_tx_is_not_cached(app_config: AppConfig, fake_esplora: FakeEsplora) -> None:
    unconfirmed = dict(load_fixture(f"esplora/tx_{FIXTURE_TXID}.json"), status={"confirmed": False})
    fake_esplora.routes[f"/api/tx/{FIXTURE_TXID}"] = unconfirmed

    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        services.esplora.get_tx(FIXTURE_TXID)
        services.esplora.get_tx(FIXTURE_TXID)

    assert len(fake_esplora.requests) == 2


def test_address_history_follows_pagination(
    app_config: AppConfig, fake_esplora: FakeEsplora
) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        history = services.esplora.get_address_history(FIXTURE_ADDRESS, max_txs=200)

    assert len(history.txs) == FIXTURE_ADDRESS_TX_COUNT
    assert not history.truncated
    assert len(fake_esplora.requests) == 2  # two pages of 25 + 16


def test_address_history_is_truncated_at_limit(
    app_config: AppConfig, fake_esplora: FakeEsplora
) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        history = services.esplora.get_address_history(FIXTURE_ADDRESS, max_txs=10)

    assert len(history.txs) == 10
    assert history.truncated
    assert len(fake_esplora.requests) == 1  # no need for the second page


def test_address_history_second_call_uses_cache(
    app_config: AppConfig, fake_esplora: FakeEsplora
) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        services.esplora.get_address_history(FIXTURE_ADDRESS, max_txs=200)
        cached = services.esplora.get_address_history(FIXTURE_ADDRESS, max_txs=200)

    assert len(cached.txs) == FIXTURE_ADDRESS_TX_COUNT
    assert len(fake_esplora.requests) == 2


def test_eur_price_for_transaction_day(app_config: AppConfig, fake_esplora: FakeEsplora) -> None:
    block_time = load_fixture(f"esplora/tx_{FIXTURE_TXID}.json")["status"]["block_time"]
    expected = load_fixture("price_tx.json")["prices"][0]["EUR"]

    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        assert services.prices.eur_quote(block_time).eur == expected
        assert services.prices.eur_quote(block_time + 60).eur == expected  # same day -> cache

    assert len(fake_esplora.requests) == 1


def test_eur_price_before_2010_is_unavailable(
    app_config: AppConfig, fake_esplora: FakeEsplora
) -> None:
    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        # 2010-05-22 (the "pizza" day): API answers EUR=0 for another date.
        assert services.prices.eur_quote(1_274_552_000) is None


def test_eur_price_failure_returns_none_and_is_not_cached(
    app_config: AppConfig, fake_esplora: FakeEsplora
) -> None:
    fake_esplora.fail_status = 503

    with Services.from_config(app_config, transport=fake_esplora.transport()) as services:
        assert services.prices.eur_quote(1_785_256_412) is None
        assert services.cache.stats() == {}


def test_weekly_price_point_up_to_seven_days_old_is_accepted() -> None:
    day = 1_445_212_800  # 2015-10-19: mempool.space answers with the 2015-10-15 price
    weekly = {"prices": [{"time": 1_444_867_200, "EUR": 235.1}]}

    quote = _extract_quote(weekly, day)

    assert quote == PriceQuote(eur=235.1, as_of="2015-10-15")


def test_price_point_older_than_a_week_is_rejected() -> None:
    day = 1_445_212_800
    stale = {"prices": [{"time": day - 8 * 86_400, "EUR": 235.1}]}

    assert _extract_quote(stale, day) is None
