# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Project website (`site/`), published to GitHub Pages by the `pages` workflow: https://edoardodaprato.github.io/btc-aml-monitor/

## [1.0.1] - 2026-10-10

### Changed
- User guide translated to English: `docs/GUIDA.md` is now `docs/GUIDE.md`. The scoring paragraph now states that each rule contributes its weight times the strength of its strongest alert.

## [1.0.0] - 2026-10-10

### Added
- `examples/address_mode` and `examples/block_scan`: real reports from the demo addresses and from block 733459, with third-party addresses redacted (only OFAC-listed and demo addresses are kept).
- `scripts/build_examples.py`: reproducible copy-and-redact of a run into `examples/`.
- README: feature list, Mermaid architecture diagram, scoring summary, example output, known limitations versus commercial tools, development notes.
- User guide: published examples and limitations (sections 9 and 10).

### Changed
- First stable release: the CLI commands, configuration files and report columns are now considered stable.

## [0.10.0] - 2026-10-10

### Added
- Block-scan mode: `scan-blocks <start> [end]` checks every transaction of a block range (at most `block_scan.max_blocks`, default 10). Blocks are read page by page (25 transactions per request) and cached.
- Single-transaction checks reusing the thresholds of `rules.yaml`: sanctioned (R01) or labelled (R03) addresses, CoinJoin (R04), fan-out (R09), large transfers excluding change (R14), consolidation (R16), anomalous fee against the block median (R21).
- Common-input and change clustering across the whole block (R19): addresses linked to a listed address are reported; clusters above 50 addresses are marked as a likely custodial service.
- Reports: `blocks.csv`, `block_alerts.csv`, `addresses_for_review.txt` (ready for `scan-addresses`; large-cluster members commented out) and an audit log with mode `blocks`.

## [0.9.0] - 2026-10-06

### Added
- Change-output detection (address reuse, script type, non-round amount; only unambiguous guesses).
- Common-input-ownership clustering with union-find, excluding CoinJoin transactions and transactions where the address only receives.
- Multi-hop exposure in both directions (source and destination of funds) with pro-rata attribution, time ordering, hop decay, per-hop and per-address caps, pruning of negligible flows, a time budget and high-degree nodes treated as entities. Incomplete searches are reported.
- R02 indirect sanctions exposure, R03 extended to indirect high-risk exposure, R17 address hopping, R20 round-trip: all 21 rules are now active.
- `address_scores.csv`: cluster size, expanded counterparties, exposure completeness, high-degree counterparties, notes; audit log lists incomplete exposures.

### Changed
- Default `max_addresses_per_hop` lowered from 50 to 20 and new `max_tx_per_expanded_address` (50) to keep an analysis within a few minutes on public APIs.

## [0.8.1] - 2026-10-06

### Added
- `update-fx`: official ECB EUR/USD reference rates. When mempool.space has a USD price but no EUR price for a day, EUR is derived as USD price / ECB rate (latest fixing within 7 days).
- `transactions.csv` reports the source of each EUR price (`btc_eur_price_source`); the audit log records the ECB rates version.

## [0.8.0] - 2026-10-06

### Added
- Address mode: `scan-addresses <file>` analyses one address per line (comments and blank lines allowed, invalid lines reported and skipped).
- Reports per run in `output/<run_id>/`: `address_scores.csv`, `alerts.csv`, `transactions.csv`.
- Audit trail: `audit_log.json` (timestamps, tool version, input file hash, rules version and config hash, full rule definitions, OFAC list version, labels hash, parameters, data sources used, skipped addresses, rules not evaluated) and `run.log`. Only file names are recorded, never full paths.
- Demo input `examples/demo_addresses.txt` (OFAC-listed addresses and the genesis address only).

### Fixed
- Historical prices: mempool.space returns weekly price points for older dates; a price dated up to 7 days before the transaction is now accepted, and the date of the price used is reported (`btc_eur_price_date`).

## [0.7.0] - 2026-10-06

### Added
- Explainable risk score (0-100): each rule counts once (weight x strength of its strongest alert), sum capped at 100, configurable bands, direct sanctions exposure forces the Severe band. Every score lists its contributions.

## [0.6.0] - 2026-10-06

### Added
- Rule framework: common `Rule` interface (id, name, AML rationale, regulatory reference, parameters), registry that checks code and `rules.yaml` match, engine that records rules failing on API errors instead of aborting.
- 18 red-flag rules: R01, R03-R16 and the new R18 (post-CoinJoin consolidation), R19 (co-spending with flagged address), R21 (anomalous fee). R02, R17 and R20 follow with multi-hop analysis.
- CoinJoin detection heuristic (equal-output and Whirlpool 5x5), configurable in `settings.yaml`.
- Esplora: output spending status (`outspends`) and block median fee rate (mempool.space).
- `analyze` command.

### Changed
- R13 no longer checks round EUR amounts: with a daily price they cannot be detected reliably.

## [0.5.0] - 2026-10-06

### Added
- Normalised data model (transactions, flows net of change, counterparties with pro-rata attribution, balance timeline reconstructed from the current balance).
- Address profile builder: full history, EUR price per transaction, truncation flag.

## [0.4.0] - 2026-10-06

### Added
- `update-ofac`: downloads the official OFAC SDN XML and extracts "Digital Currency Address - XBT" entries with entity name, SDN uid and programmes. The list version (publish date + SHA-256) is stored for the audit trail.
- Addresses designated under several entities keep every attribution.
- Address labels CSV (`address,category,source,date_added`) with empty template, strict line-by-line validation and all-or-nothing `import-labels`.
- `screen` command and `Screener` combining OFAC and labels.
- Italian user guide `docs/GUIDA.md`, including the procedure for importing verifiable public label sources.

## [0.3.0] - 2026-10-06

### Added
- Esplora API client (`mempool.space` primary, `blockstream.info` fallback) with rate limiting, retries with exponential backoff, `Retry-After` support and automatic failover.
- Address history download with pagination and a configurable cap (`max_tx_per_address`); truncation is reported.
- Historical BTC/EUR price service (daily, UTC). Missing prices (pre-July 2010, or service down) are reported as unavailable instead of 0.
- CLI commands `fetch-tx` and `cache-stats`.
- Offline test fixtures recorded from the real APIs.

## [0.2.0] - 2026-10-06

### Added
- SQLite cache with namespaces: confirmed transactions, blocks and prices cached forever; address histories refreshed after `address_ttl_hours`.

## [0.1.0] - 2026-10-06

### Added
- Project skeleton (`src/` layout, `pyproject.toml`, MIT license).
- YAML configuration: `config/settings.yaml` (data sources, rate limits, exposure limits, risk bands) and `config/rules.yaml` (16 red-flag rules with weights, severities and thresholds).
- Configuration validation with clear error messages and a stable configuration hash for the audit trail.
- CLI `btc-aml` with `--version` and `show-config`.
- Offline test suite (pytest) and GitHub Actions CI on Python 3.11 and 3.12, with ruff lint.
- `.gitignore` excluding virtual environment, caches, downloaded lists, outputs, logs and secrets.
