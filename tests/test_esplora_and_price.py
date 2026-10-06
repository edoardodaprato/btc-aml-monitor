"""Tests for the Esplora client and the BTC/EUR price service (offline fixtures)."""

from __future__ import annotations

from btc_aml.config import AppConfig
from btc_aml.data_sources.ecb import EcbRates
from btc_aml.data_sources.price import SOURCE_MEMPOOL_EUR, PriceQuote, quote_from_point
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
    weekly = {"time": 1_444_867_200, "EUR": 235.1, "USD": 266.5}

    assert quote_from_point(weekly, day, fx=None) == PriceQuote(
        235.1, "2015-10-15", SOURCE_MEMPOOL_EUR
    )


def test_price_point_older_than_a_week_is_rejected() -> None:
    day = 1_445_212_800
    stale = {"time": day - 8 * 86_400, "EUR": 235.1, "USD": 266.5}

    assert quote_from_point(stale, day, fx=None) is None


# Real ECB reference rates (USD per 1 EUR) around a mempool.space EUR gap.
ECB_RATES = EcbRates(
    usd_per_eur={"2022-03-07": 1.0895, "2022-03-08": 1.0892, "2022-04-21": 1.0887},
    downloaded_at="2026-10-06T00:00:00+00:00",
    sha256="0" * 64,
    source_url="test",
)
GAP_DAY = 1_650_585_600  # 2022-04-22: mempool.space answers a 2022-04-21 point, EUR = -1
GAP_POINT = {"time": 1_650_546_000, "EUR": -1, "USD": 40_419}


def test_missing_eur_is_derived_from_usd_and_ecb_rate() -> None:
    quote = quote_from_point(GAP_POINT, GAP_DAY, ECB_RATES)

    assert quote is not None
    assert quote.eur == round(40_419 / 1.0887, 2)
    assert quote.source == "mempool.space USD / ECB EUR-USD (2022-04-21)"


def test_missing_eur_without_ecb_rates_is_unavailable() -> None:
    assert quote_from_point(GAP_POINT, GAP_DAY, fx=None) is None


def test_ecb_rate_falls_back_to_previous_business_day() -> None:
    from datetime import date

    assert ECB_RATES.rate_on(date(2022, 3, 9)) == (1.0892, "2022-03-08")
    assert ECB_RATES.rate_on(date(2022, 3, 30)) is None  # older than 7 days
