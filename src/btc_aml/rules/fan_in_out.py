"""Shared logic for the fan-in (R08) and fan-out (R09) rules."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from btc_aml.model import Direction, Flow


def busiest_window(
    flows: list[Flow], window_seconds: float, parties_of: Callable[[Flow], set[str]]
) -> tuple[list[Flow], int]:
    """Window with the most *distinct* counterparties; returns (flows, distinct count)."""
    dated = [flow for flow in flows if flow.tx.block_time is not None]
    best: tuple[list[Flow], int] = ([], 0)
    counts: Counter[str] = Counter()
    start = 0
    for end, flow in enumerate(dated):
        counts.update(parties_of(flow))
        while flow.tx.block_time - dated[start].tx.block_time > window_seconds:  # type: ignore[operator]
            counts.subtract(parties_of(dated[start]))
            start += 1
        distinct = sum(1 for count in counts.values() if count > 0)
        if distinct > best[1]:
            best = (dated[start : end + 1], distinct)
    return best


def flows_in_direction(flows: list[Flow], direction: Direction) -> list[Flow]:
    return [flow for flow in flows if flow.direction is direction]
