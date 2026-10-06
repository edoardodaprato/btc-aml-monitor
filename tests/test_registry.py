"""Tests for the rule registry and the rule engine."""

from __future__ import annotations

import dataclasses

import pytest

from btc_aml.config import AppConfig, ConfigError
from btc_aml.data_sources.http import DataSourceError
from btc_aml.model import Alert
from btc_aml.rules.base import AnalysisContext, Rule
from btc_aml.rules.registry import ALL_RULES, build_rules, run_rules
from tests.rule_helpers import context, profile


def test_every_configured_rule_is_built(app_config: AppConfig) -> None:
    rules = build_rules(app_config)

    assert {rule.rule_id for rule in rules} == set(app_config.rules)
    assert all(rule.description() for rule in rules)  # every rule explains its AML logic


def test_disabled_rule_is_skipped(app_config: AppConfig) -> None:
    rules = dict(app_config.rules)
    rules["R15_DUST"] = dataclasses.replace(rules["R15_DUST"], enabled=False)

    built = build_rules(dataclasses.replace(app_config, rules=rules))

    assert "R15_DUST" not in {rule.rule_id for rule in built}


def test_configured_but_unknown_rule_is_rejected(app_config: AppConfig) -> None:
    rules = dict(app_config.rules)
    rules["R99_UNKNOWN"] = rules["R15_DUST"]

    with pytest.raises(ConfigError, match="R99_UNKNOWN"):
        build_rules(dataclasses.replace(app_config, rules=rules))


def test_missing_rule_parameter_is_rejected(app_config: AppConfig) -> None:
    rules = dict(app_config.rules)
    rules["R15_DUST"] = dataclasses.replace(rules["R15_DUST"], params={})

    with pytest.raises(ConfigError, match="R15_DUST: missing params"):
        build_rules(dataclasses.replace(app_config, rules=rules))


def test_rule_ids_are_unique() -> None:
    ids = [cls.rule_id for cls in ALL_RULES]
    assert len(ids) == len(set(ids))


def test_failing_rule_is_recorded_and_others_still_run(app_config: AppConfig) -> None:
    class Broken(Rule):
        """Always fails."""

        rule_id = "BROKEN"
        name = "broken"
        regulatory_reference = "n/a"

        def evaluate(self, ctx: AnalysisContext) -> list[Alert]:
            raise DataSourceError("API down")

    broken = Broken(app_config.rules["R15_DUST"])
    working = build_rules(app_config)

    result = run_rules([broken, *working], context(profile("A", [])))

    assert result.errors == {"BROKEN": "API down"}
    assert result.alerts == []
