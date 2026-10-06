"""Common interface for red-flag rules.

A rule receives an ``AnalysisContext`` (the address profile plus read-only access to
lists and blockchain data) and returns zero or more ``Alert`` objects. Each rule
declares its identity, its AML rationale (the class docstring) and its regulatory
reference, so an alert can always be traced back to *why* it exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol, TypeVar

from btc_aml.config import CoinJoinConfig, ConfigError, RuleConfig
from btc_aml.graph.exposure import ExposureResult
from btc_aml.model import AddressProfile, Alert, CounterpartyFlows, sats_to_btc
from btc_aml.screening import Screener, ScreeningHit

T = TypeVar("T")


class ChainReader(Protocol):
    """Read-only blockchain access for rules that look beyond the address history."""

    def get_tx(self, txid: str) -> dict[str, Any]: ...

    def get_outspends(self, txid: str) -> list[dict[str, Any]]: ...

    def get_block_median_fee_rate(self, block_hash: str) -> float | None: ...

    def get_address_stats(self, address: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AnalysisContext:
    profile: AddressProfile
    screener: Screener
    chain: ChainReader
    coinjoin: CoinJoinConfig
    cluster: frozenset[str] = frozenset()  # addresses of the same probable entity
    exposure: ExposureResult | None = None  # multi-hop exposure, if computed
    hop_decay: tuple[float, ...] = (1.0, 0.5, 0.25)


class Rule(ABC):
    """Base class: subclasses set the class attributes and implement ``evaluate``."""

    rule_id: ClassVar[str]
    name: ClassVar[str]
    regulatory_reference: ClassVar[str]
    required_params: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: RuleConfig) -> None:
        missing = [p for p in self.required_params if p not in config.params]
        if missing:
            raise ConfigError(f"{self.rule_id}: missing params {', '.join(missing)}")
        self.config = config
        self.params = config.params

    @classmethod
    def description(cls) -> str:
        """First paragraph of the class docstring: the AML rationale in plain words."""
        return (cls.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ")

    @abstractmethod
    def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
        """Return the alerts raised for ``ctx.profile.address`` (empty if none)."""

    def make_alert(
        self,
        ctx: AnalysisContext,
        *,
        explanation: str,
        txids: Iterable[str],
        amount_sats: int,
        amount_eur: float | None,
        hop_distance: int = 0,
        strength: float = 1.0,
    ) -> Alert:
        return Alert(
            rule_id=self.rule_id,
            rule_name=self.name,
            address=ctx.profile.address,
            severity=self.config.severity,
            regulatory_reference=self.regulatory_reference,
            explanation=explanation,
            evidence_txids=tuple(dict.fromkeys(txids)),  # unique, order preserved
            amount_sats=amount_sats,
            amount_eur=amount_eur,
            hop_distance=hop_distance,
            strength=strength,
        )


# --- helpers shared by several rules -------------------------------------------------


def fmt_btc(sats: int) -> str:
    return f"{sats_to_btc(sats):.8f} BTC"


def fmt_amount(sats: int, eur: float | None) -> str:
    """'0.50000000 BTC (25,000 EUR)' or '... (EUR n/a)'."""
    eur_text = f"{eur:,.0f} EUR" if eur is not None else "EUR n/a"
    return f"{fmt_btc(sats)} ({eur_text})"


def fmt_time(timestamp: int | None) -> str:
    if timestamp is None:
        return "unconfirmed"
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d %H:%M UTC")


def sum_eur(values: Iterable[float | None]) -> float | None:
    """Sum of EUR amounts, or None if any of them is unknown."""
    total = 0.0
    for value in values:
        if value is None:
            return None
        total += value
    return total


def exceeds_threshold(
    amount_sats: int, amount_eur: float | None, threshold_eur: float, threshold_btc: float
) -> tuple[bool, str]:
    """Compare in EUR when a price exists, otherwise fall back to BTC (and say so)."""
    if amount_eur is not None:
        return amount_eur >= threshold_eur, f"EUR threshold {threshold_eur:,.0f}"
    return (
        sats_to_btc(amount_sats) >= threshold_btc,
        f"BTC threshold {threshold_btc} (EUR price unavailable)",
    )


def densest_window(
    items: Sequence[T], window_seconds: float, time_of: Callable[[T], int | None]
) -> list[T]:
    """Largest group of items whose timestamps fit within ``window_seconds``.

    Items must be sorted by time; unconfirmed items (no timestamp) are ignored.
    """
    dated = [item for item in items if time_of(item) is not None]
    best: list[T] = []
    start = 0
    for end in range(len(dated)):
        while time_of(dated[end]) - time_of(dated[start]) > window_seconds:  # type: ignore[operator]
            start += 1
        if end - start + 1 > len(best):
            best = dated[start : end + 1]
    return best


def flagged_counterparties(
    ctx: AnalysisContext, categories: Iterable[str]
) -> list[tuple[CounterpartyFlows, list[ScreeningHit]]]:
    """Direct counterparties listed under any of ``categories``, largest exposure first."""
    wanted = set(categories)
    flagged = []
    for flows in ctx.profile.counterparties.values():
        hits = [hit for hit in ctx.screener.screen(flows.address) if hit.category in wanted]
        if hits:
            flagged.append((flows, hits))
    return sorted(flagged, key=lambda item: item[0].total_sats, reverse=True)


def describe_hits(hits: Iterable[ScreeningHit]) -> str:
    return "; ".join(f"[{hit.list_name}] {hit.category}: {hit.detail}" for hit in hits)
