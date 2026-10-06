"""Tests for retries, backoff, rate limiting and fallback."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from btc_aml.config import DataSourceConfig
from btc_aml.data_sources.http import DataSourceError, HttpClient, RequestRejectedError

CONFIG = DataSourceConfig(
    primary_url="https://primary.test/api",
    fallback_url="https://fallback.test/api",
    timeout_seconds=5,
    max_retries=2,
    backoff_base_seconds=1.0,
    requests_per_second=2.0,
)


class FakeTime:
    """Deterministic clock: sleeping just advances time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[HttpClient, FakeTime]:
    fake_time = FakeTime()
    client = HttpClient(
        CONFIG,
        transport=httpx.MockTransport(handler),
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
    )
    return client, fake_time


def test_success_on_primary() -> None:
    client, _ = make_client(lambda request: httpx.Response(200, json={"ok": True}))

    assert client.get_json("/x") == {"ok": True}
    assert client.requests_by_source == {"primary.test": 1}


def test_retries_with_exponential_backoff_then_succeeds() -> None:
    answers = iter([503, 503, 200])
    client, fake_time = make_client(lambda request: httpx.Response(next(answers), json={}))

    client.get_json("/x")

    # Backoff waits of 1s then 2s (the 0.5s rate-limit gap is absorbed by them).
    assert [s for s in fake_time.sleeps if s >= 1] == [1.0, 2.0]


def test_falls_back_when_primary_keeps_failing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary.test":
            raise httpx.ConnectError("primary down")
        return httpx.Response(200, json={"from": "fallback"})

    client, _ = make_client(handler)

    assert client.get_json("/x") == {"from": "fallback"}
    assert client.requests_by_source == {"fallback.test": 1}


def test_all_sources_failing_raises() -> None:
    client, _ = make_client(lambda request: httpx.Response(500))

    with pytest.raises(DataSourceError, match="All data sources failed"):
        client.get_json("/x")


def test_client_error_is_not_retried_nor_sent_to_fallback() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, text="Invalid Bitcoin address")

    client, _ = make_client(handler)

    with pytest.raises(RequestRejectedError) as excinfo:
        client.get_json("/address/not-an-address")
    assert excinfo.value.status_code == 400
    assert len(calls) == 1


def test_retry_after_header_is_honoured() -> None:
    answers = iter(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})]
    )
    client, fake_time = make_client(lambda request: next(answers))

    client.get_json("/x")

    assert 7.0 in fake_time.sleeps


def test_primary_only_skips_fallback() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(500)

    client, _ = make_client(handler)

    with pytest.raises(DataSourceError):
        client.get_json("/v1/historical-price", primary_only=True)
    assert set(hosts) == {"primary.test"}


def test_rate_limit_spaces_requests() -> None:
    client, fake_time = make_client(lambda request: httpx.Response(200, json={}))

    for _ in range(3):
        client.get_json("/x")

    # 2 requests/second -> each request after the first waits 0.5s.
    assert fake_time.sleeps == [0.5, 0.5]
