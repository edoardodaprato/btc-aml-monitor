"""Helpers for rules based on multi-hop exposure."""

from __future__ import annotations

from collections.abc import Iterable

from btc_aml.graph.exposure import ExposureHit
from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule, describe_hits, fmt_amount, sum_eur


def group_exposure_hits(hits: Iterable[ExposureHit]) -> list[list[ExposureHit]]:
    """Group hits by listed address (one address can be reached by several paths)."""
    groups: dict[str, list[ExposureHit]] = {}
    for hit in hits:
        groups.setdefault(hit.address, []).append(hit)
    return sorted(groups.values(), key=lambda g: -sum(h.amount_sats for h in g))


def path_text(path: tuple[str, ...]) -> str:
    """'bc1qabc... -> 1XyZ... -> 3Def...' with shortened addresses."""
    return " -> ".join(f"{address[:10]}..." for address in path)


def indirect_alerts(rule: Rule, ctx: AnalysisContext, categories: set[str]) -> list[Alert]:
    """One alert per listed address reached at hop >= 2, strength decayed by its closest hop."""
    if ctx.exposure is None:
        return []
    hits = [h for h in ctx.exposure.hits if any(s.category in categories for s in h.hits)]
    volume = ctx.profile.volume_sats or 1
    alerts = []
    for group in group_exposure_hits(hits):
        amount = sum(h.amount_sats for h in group)
        share = amount / volume
        if share < rule.params["min_exposure_share"]:
            continue
        closest = min(group, key=lambda h: h.hop)
        directions = sorted({h.direction.value for h in group})
        decay = ctx.hop_decay[closest.hop - 1]
        listed = describe_hits(s for s in closest.hits if s.category in categories)
        alerts.append(
            rule.make_alert(
                ctx,
                explanation=(
                    f"{closest.address} ({listed}) is {closest.hop} hops "
                    f"away ({'/'.join(directions)}): estimated "
                    f"{fmt_amount(amount, sum_eur(h.amount_eur for h in group))}, "
                    f"{share:.1%} of the analysed volume, via {path_text(closest.path)}. "
                    f"Pro-rata attribution; weight decayed to {decay:.0%}."
                ),
                txids=[txid for h in group for txid in h.txids],
                amount_sats=amount,
                amount_eur=sum_eur(h.amount_eur for h in group),
                hop_distance=closest.hop,
                strength=decay,
            )
        )
    return alerts
