"""Orchestration: from an address to its alerts."""

from __future__ import annotations

from dataclasses import dataclass, field

from btc_aml.address_profile import build_address_profile
from btc_aml.config import AppConfig
from btc_aml.graph.clustering import address_cluster
from btc_aml.graph.exposure import ExposureResult, compute_exposure
from btc_aml.model import AddressProfile, Alert
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.rules.registry import run_rules
from btc_aml.scoring.scorer import AddressScore, score_address
from btc_aml.screening import Screener
from btc_aml.services import Services

# Rules that need the (expensive) multi-hop exposure search.
EXPOSURE_RULES = frozenset({"R02_OFAC_INDIRECT", "R03_HIGH_RISK_CATEGORY", "R20_ROUND_TRIP"})


@dataclass
class AddressAnalysis:
    profile: AddressProfile
    alerts: list[Alert]
    score: AddressScore
    cluster: frozenset[str]
    exposure: ExposureResult | None
    rule_errors: dict[str, str] = field(default_factory=dict)


def analyze_address(
    address: str,
    services: Services,
    config: AppConfig,
    screener: Screener,
    rules: list[Rule],
) -> AddressAnalysis:
    profile = build_address_profile(address, services, config)
    cluster = address_cluster(address, profile.txs, config.coinjoin)
    exposure = None
    if any(rule.rule_id in EXPOSURE_RULES for rule in rules):
        exposure = compute_exposure(profile, cluster, screener, services.esplora, config.exposure)
    ctx = AnalysisContext(
        profile,
        screener,
        services.esplora,
        config.coinjoin,
        cluster=cluster,
        exposure=exposure,
        hop_decay=config.exposure.hop_decay,
    )
    result = run_rules(rules, ctx)
    score = score_address(address, result.alerts, config.rules, config.scoring)
    return AddressAnalysis(profile, result.alerts, score, cluster, exposure, result.errors)
