"""Tests for the SQLite cache."""

from __future__ import annotations

from pathlib import Path

from btc_aml.data_sources.cache import Cache


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_roundtrip_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "cache.sqlite"
    with Cache(path) as cache:
        cache.put("tx", "abc", {"value": 42})

    with Cache(path) as reopened:
        assert reopened.get("tx", "abc") == {"value": 42}


def test_missing_key_returns_none() -> None:
    with Cache(Path(":memory:")) as cache:
        assert cache.get("tx", "missing") is None


def test_namespaces_are_isolated() -> None:
    with Cache(Path(":memory:")) as cache:
        cache.put("tx", "same-key", "a transaction")
        cache.put("address", "same-key", "an address")

        assert cache.get("tx", "same-key") == "a transaction"
        assert cache.get("address", "same-key") == "an address"


def test_max_age_expires_mutable_entries() -> None:
    clock = FakeClock()
    with Cache(Path(":memory:"), clock=clock) as cache:
        cache.put("address", "bc1q", {"tx_count": 1})
        clock.now += 3600

        assert cache.get("address", "bc1q", max_age_seconds=7200) == {"tx_count": 1}
        assert cache.get("address", "bc1q", max_age_seconds=1800) is None
        assert cache.get("address", "bc1q") == {"tx_count": 1}  # no limit -> still there


def test_put_replaces_and_refreshes_timestamp() -> None:
    clock = FakeClock()
    with Cache(Path(":memory:"), clock=clock) as cache:
        cache.put("address", "bc1q", {"tx_count": 1})
        clock.now += 3600
        cache.put("address", "bc1q", {"tx_count": 2})

        assert cache.get("address", "bc1q", max_age_seconds=60) == {"tx_count": 2}


def test_stats_counts_per_namespace() -> None:
    with Cache(Path(":memory:")) as cache:
        cache.put("tx", "a", 1)
        cache.put("tx", "b", 2)
        cache.put("price_point", "0", {"EUR": None})

        assert cache.stats() == {"price_point": 1, "tx": 2}
