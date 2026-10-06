"""Orchestration: from an address to its alerts."""

from __future__ import annotations

from dataclasses import dataclass, field

from btc_aml.address_profile import build_address_profile
from btc_aml.config import AppConfig
from btc_aml.model import AddressProfile, Alert
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.rules.registry import run_rules
from btc_aml.screening import Screener
from btc_aml.services import Services


@dataclass
class AddressAnalysis:
    profile: AddressProfile
    alerts: list[Alert]
    rule_errors: dict[str, str] = field(default_factory=dict)


def analyze_address(
    address: str,
    services: Services,
    config: AppConfig,
    screener: Screener,
    rules: list[Rule],
) -> AddressAnalysis:
    profile = build_address_profile(address, services, config)
    ctx = AnalysisContext(profile, screener, services.esplora, config.coinjoin)
    result = run_rules(rules, ctx)
    return AddressAnalysis(profile, result.alerts, result.errors)
