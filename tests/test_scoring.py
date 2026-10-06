"""Tests for the explainable risk score."""

from __future__ import annotations

import dataclasses

from btc_aml.config import AppConfig
from btc_aml.model import Alert
from btc_aml.scoring.scorer import band_for, score_address


def alert(rule_id: str, strength: float = 1.0) -> Alert:
    return Alert(
        rule_id=rule_id,
        rule_name=rule_id,
        address="A",
        severity="medium",
        regulatory_reference="ref",
        explanation="test",
        evidence_txids=("tx",),
        amount_sats=1,
        amount_eur=None,
        strength=strength,
    )


def test_no_alerts_is_low(app_config: AppConfig) -> None:
    result = score_address("A", [], app_config.rules, app_config.scoring)

    assert (result.score, result.band) == (0, "Low")
    assert result.explanation() == "No rule triggered."


def test_weighted_sum_and_explanation(app_config: AppConfig) -> None:
    alerts = [alert("R14_LARGE_TRANSACTION"), alert("R07_PASS_THROUGH")]  # 15 + 20

    result = score_address("A", alerts, app_config.rules, app_config.scoring)

    assert (result.score, result.band) == (35, "Medium")
    assert result.explanation() == "R07_PASS_THROUGH +20 | R14_LARGE_TRANSACTION +15"


def test_same_rule_counts_once_using_strongest_alert(app_config: AppConfig) -> None:
    weak, strong = alert("R03_HIGH_RISK_CATEGORY", 0.5), alert("R03_HIGH_RISK_CATEGORY", 1.0)

    result = score_address("A", [weak, strong, weak], app_config.rules, app_config.scoring)

    assert result.score == 40
    assert result.contribution_of(strong) == 40
    assert result.contribution_of(weak) == 0


def test_strength_scales_weight(app_config: AppConfig) -> None:
    result = score_address(
        "A", [alert("R03_HIGH_RISK_CATEGORY", 0.25)], app_config.rules, app_config.scoring
    )
    assert result.score == 10


def test_score_is_capped_at_100(app_config: AppConfig) -> None:
    alerts = [
        alert("R19_CO_SPENDING_FLAGGED"),
        alert("R03_HIGH_RISK_CATEGORY"),
        alert("R06_STRUCTURING"),
    ]

    result = score_address("A", alerts, app_config.rules, app_config.scoring)

    assert result.score == 100
    assert "capped at 100" in result.explanation()


def test_direct_sanctions_exposure_forces_severe(app_config: AppConfig) -> None:
    rules = dict(app_config.rules)
    # Even if a compliance team lowered the R01 weight, the band stays Severe.
    rules["R01_OFAC_DIRECT"] = dataclasses.replace(rules["R01_OFAC_DIRECT"], weight=10)

    result = score_address("A", [alert("R01_OFAC_DIRECT")], rules, app_config.scoring)

    assert result.sanctions_override
    assert (result.score, result.band) == (75, "Severe")
    assert "band forced to Severe" in result.explanation()


def test_band_boundaries(app_config: AppConfig) -> None:
    expected = {0: "Low", 24: "Low", 25: "Medium", 49: "Medium", 50: "High", 74: "High"}
    for score, band in {**expected, 75: "Severe", 100: "Severe"}.items():
        assert band_for(score, app_config.scoring) == band
