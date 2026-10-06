"""Load and validate the YAML configuration (settings.yaml and rules.yaml).

Validation happens once, at startup, so that a typo in a threshold fails loudly
instead of silently producing a wrong risk score. The configuration hash is written
to the audit log of every run, so each alert can be traced back to the exact
parameters that produced it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SEVERITIES = ("low", "medium", "high", "severe")
MAX_HOPS_HARD_CAP = 3


class ConfigError(ValueError):
    """Raised when a configuration file is missing or invalid."""


@dataclass(frozen=True)
class DataSourceConfig:
    primary_url: str
    fallback_url: str
    timeout_seconds: float
    max_retries: int
    backoff_base_seconds: float
    requests_per_second: float


@dataclass(frozen=True)
class CacheConfig:
    path: Path
    address_ttl_hours: float


@dataclass(frozen=True)
class ExposureConfig:
    max_hops: int
    hop_decay: tuple[float, ...]
    max_tx_per_address: int
    max_addresses_per_hop: int
    max_analysis_seconds: int
    high_degree_threshold: int


@dataclass(frozen=True)
class CoinJoinConfig:
    min_equal_outputs: int
    min_distinct_inputs: int


@dataclass(frozen=True)
class RiskBand:
    name: str
    min: int
    max: int


@dataclass(frozen=True)
class ScoringConfig:
    bands: tuple[RiskBand, ...]
    sanctions_override_band: str


@dataclass(frozen=True)
class RuleConfig:
    rule_id: str
    enabled: bool
    weight: float
    severity: str
    params: dict[str, Any]


@dataclass(frozen=True)
class AppConfig:
    data_sources: DataSourceConfig
    cache: CacheConfig
    ofac_sdn_url: str
    ofac_local_path: Path
    fx_ecb_url: str
    fx_local_path: Path
    labels_path: Path
    exposure: ExposureConfig
    coinjoin: CoinJoinConfig
    max_blocks: int
    scoring: ScoringConfig
    output_dir: Path
    rules_version: str
    rules: dict[str, RuleConfig]
    config_hash: str


def load_config(config_dir: Path) -> AppConfig:
    """Read settings.yaml and rules.yaml from ``config_dir`` and validate them."""
    settings = _read_yaml(config_dir / "settings.yaml")
    rules_doc = _read_yaml(config_dir / "rules.yaml")
    try:
        return AppConfig(
            data_sources=DataSourceConfig(**_section(settings, "data_sources")),
            cache=_build_cache(_section(settings, "cache")),
            ofac_sdn_url=_section(settings, "ofac")["sdn_url"],
            ofac_local_path=Path(_section(settings, "ofac")["local_path"]),
            fx_ecb_url=_section(settings, "fx")["ecb_url"],
            fx_local_path=Path(_section(settings, "fx")["local_path"]),
            labels_path=Path(_section(settings, "labels")["path"]),
            exposure=_build_exposure(_section(settings, "exposure")),
            coinjoin=_build_coinjoin(_section(_section(settings, "heuristics"), "coinjoin")),
            max_blocks=_positive_int(_section(settings, "block_scan")["max_blocks"], "max_blocks"),
            scoring=_build_scoring(_section(settings, "scoring")),
            output_dir=Path(_section(settings, "output")["directory"]),
            rules_version=str(rules_doc.get("rules_version", "unversioned")),
            rules=_build_rules(_section(rules_doc, "rules")),
            config_hash=_hash_config(settings, rules_doc),
        )
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"Invalid or missing configuration key: {exc}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        content = yaml.safe_load(handle)
    if not isinstance(content, dict):
        raise ConfigError(f"Configuration file is empty or not a mapping: {path}")
    return content


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"Missing or invalid section '{name}'")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ConfigError(f"'{name}' must be a positive integer, got {value!r}")
    return value


def _build_cache(raw: dict[str, Any]) -> CacheConfig:
    ttl = raw["address_ttl_hours"]
    if not isinstance(ttl, (int, float)) or ttl < 0:
        raise ConfigError(f"'address_ttl_hours' must be a non-negative number, got {ttl!r}")
    return CacheConfig(path=Path(raw["path"]), address_ttl_hours=float(ttl))


def _build_exposure(raw: dict[str, Any]) -> ExposureConfig:
    max_hops = _positive_int(raw["max_hops"], "max_hops")
    if max_hops > MAX_HOPS_HARD_CAP:
        raise ConfigError(f"'max_hops' cannot exceed {MAX_HOPS_HARD_CAP}, got {max_hops}")
    decay = tuple(float(x) for x in raw["hop_decay"])
    if len(decay) < max_hops:
        raise ConfigError(f"'hop_decay' needs at least {max_hops} values, got {len(decay)}")
    if any(not 0 < d <= 1 for d in decay) or list(decay) != sorted(decay, reverse=True):
        raise ConfigError("'hop_decay' values must be in (0, 1] and non-increasing")
    return ExposureConfig(
        max_hops=max_hops,
        hop_decay=decay,
        max_tx_per_address=_positive_int(raw["max_tx_per_address"], "max_tx_per_address"),
        max_addresses_per_hop=_positive_int(raw["max_addresses_per_hop"], "max_addresses_per_hop"),
        max_analysis_seconds=_positive_int(raw["max_analysis_seconds"], "max_analysis_seconds"),
        high_degree_threshold=_positive_int(raw["high_degree_threshold"], "high_degree_threshold"),
    )


def _build_coinjoin(raw: dict[str, Any]) -> CoinJoinConfig:
    return CoinJoinConfig(
        min_equal_outputs=_positive_int(raw["min_equal_outputs"], "min_equal_outputs"),
        min_distinct_inputs=_positive_int(raw["min_distinct_inputs"], "min_distinct_inputs"),
    )


def _build_scoring(raw: dict[str, Any]) -> ScoringConfig:
    bands = tuple(RiskBand(**band) for band in raw["bands"])
    expected_min = 0
    for band in bands:
        if band.min != expected_min or band.max < band.min:
            raise ConfigError(f"Risk bands must cover 0-100 without gaps; check band '{band.name}'")
        expected_min = band.max + 1
    if expected_min != 101:
        raise ConfigError("Risk bands must end at 100")
    override = raw["sanctions_override_band"]
    if override not in {band.name for band in bands}:
        raise ConfigError(f"'sanctions_override_band' '{override}' is not a defined band")
    return ScoringConfig(bands=bands, sanctions_override_band=override)


def _build_rules(raw: dict[str, Any]) -> dict[str, RuleConfig]:
    rules = {}
    for rule_id, spec in raw.items():
        weight = spec["weight"]
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 100:
            raise ConfigError(f"{rule_id}: 'weight' must be between 0 and 100, got {weight!r}")
        if spec["severity"] not in SEVERITIES:
            raise ConfigError(f"{rule_id}: 'severity' must be one of {SEVERITIES}")
        rules[rule_id] = RuleConfig(
            rule_id=rule_id,
            enabled=bool(spec["enabled"]),
            weight=float(weight),
            severity=spec["severity"],
            params=dict(spec.get("params") or {}),
        )
    return rules


def _hash_config(*documents: dict[str, Any]) -> str:
    """Stable SHA-256 of the parsed configuration (ignores comments and key order)."""
    canonical = json.dumps(documents, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
