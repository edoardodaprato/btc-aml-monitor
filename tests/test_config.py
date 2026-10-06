"""Tests for configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from btc_aml.config import ConfigError, load_config


def _edit_yaml(path: Path, edit) -> None:
    document = yaml.safe_load(path.read_text())
    edit(document)
    path.write_text(yaml.safe_dump(document))


def test_default_config_is_valid(config_dir: Path) -> None:
    config = load_config(config_dir)

    assert config.exposure.max_hops == 2
    assert config.scoring.sanctions_override_band == "Severe"
    assert len(config.rules) == 21
    assert config.rules["R01_OFAC_DIRECT"].weight == 100


def test_config_hash_ignores_comments_but_tracks_values(config_dir: Path) -> None:
    rules_file = config_dir / "rules.yaml"
    original_hash = load_config(config_dir).config_hash

    rules_file.write_text("# extra comment\n" + rules_file.read_text())
    assert load_config(config_dir).config_hash == original_hash

    _edit_yaml(rules_file, lambda d: d["rules"]["R10_HIGH_VELOCITY"].update(weight=11))
    assert load_config(config_dir).config_hash != original_hash


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path)


def test_max_hops_above_hard_cap_is_rejected(config_dir: Path) -> None:
    _edit_yaml(config_dir / "settings.yaml", lambda d: d["exposure"].update(max_hops=4))

    with pytest.raises(ConfigError, match="cannot exceed 3"):
        load_config(config_dir)


def test_increasing_hop_decay_is_rejected(config_dir: Path) -> None:
    _edit_yaml(config_dir / "settings.yaml", lambda d: d["exposure"].update(hop_decay=[0.5, 1.0]))

    with pytest.raises(ConfigError, match="non-increasing"):
        load_config(config_dir)


def test_gap_in_risk_bands_is_rejected(config_dir: Path) -> None:
    _edit_yaml(config_dir / "settings.yaml", lambda d: d["scoring"]["bands"][1].update(min=30))

    with pytest.raises(ConfigError, match="without gaps"):
        load_config(config_dir)


def test_rule_weight_out_of_range_is_rejected(config_dir: Path) -> None:
    _edit_yaml(
        config_dir / "rules.yaml", lambda d: d["rules"]["R14_LARGE_TRANSACTION"].update(weight=150)
    )

    with pytest.raises(ConfigError, match="R14_LARGE_TRANSACTION"):
        load_config(config_dir)


def test_unknown_severity_is_rejected(config_dir: Path) -> None:
    _edit_yaml(config_dir / "rules.yaml", lambda d: d["rules"]["R15_DUST"].update(severity="huge"))

    with pytest.raises(ConfigError, match="severity"):
        load_config(config_dir)
