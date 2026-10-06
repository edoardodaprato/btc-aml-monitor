"""Explainable risk score.

* Each rule contributes at most once: ``weight x strength`` of its strongest alert.
  Ten large transactions are one red flag ("large transactions"), not ten.
* The score is the sum of contributions, capped at 100.
* Direct sanctions exposure (R01) always yields the override band (Severe by default),
  whatever the other factors: the score is raised to that band's minimum if needed.
* The result lists every contribution, so the score can always be explained.
"""

from __future__ import annotations

from dataclasses import dataclass

from btc_aml.config import RuleConfig, ScoringConfig
from btc_aml.model import Alert

MAX_SCORE = 100
SANCTIONS_OVERRIDE_RULES = frozenset({"R01_OFAC_DIRECT"})


@dataclass(frozen=True)
class RuleContribution:
    rule_id: str
    points: float
    alert: Alert  # the strongest alert of the rule, which carries the points


@dataclass(frozen=True)
class AddressScore:
    address: str
    score: int
    band: str
    contributions: tuple[RuleContribution, ...]  # largest first
    sanctions_override: bool

    @property
    def rules_triggered(self) -> tuple[str, ...]:
        return tuple(c.rule_id for c in self.contributions)

    def explanation(self) -> str:
        if not self.contributions:
            return "No rule triggered."
        parts = [f"{c.rule_id} +{c.points:.0f}" for c in self.contributions]
        raw = sum(c.points for c in self.contributions)
        text = " | ".join(parts)
        if raw > MAX_SCORE:
            text += f" (sum {raw:.0f} capped at {MAX_SCORE})"
        if self.sanctions_override:
            text += f" | direct sanctions exposure: band forced to {self.band}"
        return text

    def contribution_of(self, alert: Alert) -> float:
        """Points carried by ``alert`` (0 for non-strongest alerts of the same rule)."""
        for contribution in self.contributions:
            if contribution.alert is alert:
                return contribution.points
        return 0.0


def score_address(
    address: str, alerts: list[Alert], rules: dict[str, RuleConfig], scoring: ScoringConfig
) -> AddressScore:
    strongest: dict[str, Alert] = {}
    for alert in alerts:
        current = strongest.get(alert.rule_id)
        if current is None or alert.strength > current.strength:
            strongest[alert.rule_id] = alert

    contributions = sorted(
        (
            RuleContribution(rule_id, rules[rule_id].weight * alert.strength, alert)
            for rule_id, alert in strongest.items()
        ),
        key=lambda c: (-c.points, c.rule_id),
    )
    score = min(MAX_SCORE, round(sum(c.points for c in contributions)))

    override = bool(SANCTIONS_OVERRIDE_RULES & strongest.keys())
    if override:
        override_band = next(b for b in scoring.bands if b.name == scoring.sanctions_override_band)
        score = max(score, override_band.min)

    return AddressScore(
        address=address,
        score=score,
        band=band_for(score, scoring),
        contributions=tuple(contributions),
        sanctions_override=override,
    )


def band_for(score: int, scoring: ScoringConfig) -> str:
    for band in scoring.bands:
        if band.min <= score <= band.max:
            return band.name
    raise ValueError(f"Score {score} outside configured bands")  # bands are validated at load
