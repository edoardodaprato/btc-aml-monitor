# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-06

### Added
- Project skeleton (`src/` layout, `pyproject.toml`, MIT license).
- YAML configuration: `config/settings.yaml` (data sources, rate limits, exposure limits, risk bands) and `config/rules.yaml` (16 red-flag rules with weights, severities and thresholds).
- Configuration validation with clear error messages and a stable configuration hash for the audit trail.
- CLI `btc-aml` with `--version` and `show-config`.
- Offline test suite (pytest) and GitHub Actions CI on Python 3.11 and 3.12, with ruff lint.
- `.gitignore` excluding virtual environment, caches, downloaded lists, outputs, logs and secrets.
