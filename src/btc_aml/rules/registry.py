"""Registry of implemented rules and the engine that runs them.

The configuration and the code must agree exactly: a rule configured but not
implemented, or implemented but not configured, stops the program at startup.
A rule that fails at run time (e.g. an API outage) does not stop the analysis: the
failure is recorded so the report states which rules could not be evaluated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from btc_aml.config import AppConfig, ConfigError
from btc_aml.data_sources.http import DataSourceError
from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.rules.r01_ofac_direct import OfacDirectExposure
from btc_aml.rules.r02_ofac_indirect import OfacIndirectExposure
from btc_aml.rules.r03_high_risk_category import HighRiskCategoryExposure
from btc_aml.rules.r04_coinjoin import CoinJoinParticipation
from btc_aml.rules.r05_peel_chain import PeelChain
from btc_aml.rules.r06_structuring import Structuring
from btc_aml.rules.r07_pass_through import PassThrough
from btc_aml.rules.r08_fan_in import FanIn
from btc_aml.rules.r09_fan_out import FanOut
from btc_aml.rules.r10_high_velocity import HighVelocity
from btc_aml.rules.r11_dormant_reactivation import DormantReactivation
from btc_aml.rules.r12_new_address_high_volume import NewAddressHighVolume
from btc_aml.rules.r13_round_amounts import RoundAmounts
from btc_aml.rules.r14_large_transaction import LargeTransaction
from btc_aml.rules.r15_dust import DustReceived
from btc_aml.rules.r16_consolidation import Consolidation
from btc_aml.rules.r17_address_hopping import AddressHopping
from btc_aml.rules.r18_post_coinjoin_consolidation import PostCoinJoinConsolidation
from btc_aml.rules.r19_co_spending_flagged import CoSpendingWithFlaggedAddress
from btc_aml.rules.r20_round_trip import RoundTrip
from btc_aml.rules.r21_anomalous_fee import AnomalousFee

logger = logging.getLogger(__name__)

ALL_RULES: tuple[type[Rule], ...] = (
    OfacDirectExposure,
    OfacIndirectExposure,
    HighRiskCategoryExposure,
    CoinJoinParticipation,
    PeelChain,
    Structuring,
    PassThrough,
    FanIn,
    FanOut,
    HighVelocity,
    DormantReactivation,
    NewAddressHighVolume,
    RoundAmounts,
    LargeTransaction,
    DustReceived,
    Consolidation,
    AddressHopping,
    PostCoinJoinConsolidation,
    CoSpendingWithFlaggedAddress,
    RoundTrip,
    AnomalousFee,
)


@dataclass
class RuleRunResult:
    alerts: list[Alert] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # rule_id -> reason


def build_rules(config: AppConfig) -> list[Rule]:
    """Instantiate every enabled rule, checking that config and code match."""
    implemented = {cls.rule_id: cls for cls in ALL_RULES}
    not_implemented = sorted(set(config.rules) - implemented.keys())
    not_configured = sorted(implemented.keys() - set(config.rules))
    if not_implemented:
        raise ConfigError(f"Rules configured but not implemented: {', '.join(not_implemented)}")
    if not_configured:
        raise ConfigError(
            f"Rules implemented but missing from rules.yaml: {', '.join(not_configured)}"
        )
    return [implemented[rule_id](rc) for rule_id, rc in config.rules.items() if rc.enabled]


def run_rules(rules: list[Rule], ctx: AnalysisContext) -> RuleRunResult:
    result = RuleRunResult()
    for rule in rules:
        try:
            result.alerts.extend(rule.evaluate(ctx))
        except DataSourceError as exc:
            logger.warning("%s could not be evaluated: %s", rule.rule_id, exc)
            result.errors[rule.rule_id] = str(exc)
    return result
