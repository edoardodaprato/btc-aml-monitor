# btc-aml-monitor

[![tests](https://github.com/edoardodaprato/btc-aml-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/edoardodaprato/btc-aml-monitor/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)

**Retrospective Bitcoin transaction monitoring for AML compliance**, built on free public data only.

The tool screens Bitcoin addresses and block ranges against the OFAC SDN list and a set of
red-flag rules derived from the FATF *Red Flag Indicators of ML/TF on Virtual Assets* (2020)
and the EBA ML/TF Risk Factors Guidelines for crypto-asset service providers. Every alert is
explainable: it carries the rule that fired, its regulatory reference, the score contribution
and the transaction-level evidence.

> ⚠️ **Status: work in progress (v0.8.0 — address mode end to end).** See the [CHANGELOG](CHANGELOG.md)
> and the roadmap below.

## The problem

Crypto-asset service providers (VASPs/CASPs) must monitor the on-chain history of the
addresses their customers interact with. Commercial blockchain-analytics tools solve this at
scale, but they are opaque and expensive. This project shows how the core logic works —
sanctions screening, exposure analysis, typology detection, risk scoring — in readable,
tested and fully configurable code.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
btc-aml show-config
btc-aml fetch-tx 7a86eb72b432ce2440aca3d8c71a4a5ec92645e4678ccb211c0ce41d882753ee
btc-aml update-ofac
btc-aml update-fx      # ECB EUR/USD rates, fill EUR price gaps
btc-aml screen 12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL
btc-aml analyze 12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL
btc-aml scan-addresses examples/demo_addresses.txt   # CSV reports + audit log in output/
```

A beginner's guide in Italian is available in [docs/GUIDA.md](docs/GUIDA.md).

## Red-flag rules

Every rule is a separate module in [`src/btc_aml/rules`](src/btc_aml/rules) with its AML
rationale in the docstring. Weights, severities and thresholds live in
[`config/rules.yaml`](config/rules.yaml).

| ID | Rule | What it detects | Reference |
|---|---|---|---|
| R01 | Direct sanctions exposure | Address on the OFAC SDN list, or direct transactions with one | OFAC SDN; FATF R.6; FATF RFI (source of funds) |
| R02 | Indirect sanctions exposure | Sanctioned funds within N hops, decayed per hop | *planned: multi-hop phase* |
| R03 | High-risk category exposure | Direct transactions with addresses labelled mixer, darknet market, ransomware, scam | FATF RFI (source of funds, anonymity); EBA GL 21 |
| R04 | CoinJoin participation | Equal-output CoinJoins (Wasabi/JoinMarket-style) and Whirlpool 5x5 mixes | FATF RFI (anonymity); EBA GL 21 |
| R05 | Peel chain | Chain of transactions each paying out a small amount and forwarding the rest | FATF RFI (patterns) |
| R06 | Structuring | Repeated amounts just below 1,000 / 10,000 EUR in a short window | FATF RFI (size and frequency); TFR |
| R07 | Pass-through | Funds received and sent on within hours, balance back near zero | FATF RFI (patterns) |
| R08 | Fan-in | Many distinct senders within a short window | FATF RFI (patterns) |
| R09 | Fan-out | Many distinct recipients within a short window | FATF RFI (patterns) |
| R10 | High velocity | Transactions per day above threshold | FATF RFI (size and frequency) |
| R11 | Dormant reactivation | Significant movement after a long inactivity | FATF RFI (patterns) |
| R12 | New address, high volume | Large value in the first transactions of a new address | FATF RFI (patterns) |
| R13 | Round amounts | Repeated exact multiples of 0.1 / 1 BTC | FATF RFI (patterns) |
| R14 | Large transaction | Single transfer above 100,000 EUR (or 2 BTC when no price) | FATF RFI (size and frequency) |
| R15 | Dust | Tiny unsolicited amounts from many sources (dusting attack) | FATF RFI (patterns) |
| R16 | Consolidation | Many small inputs merged into one transaction | FATF RFI (patterns) |
| R17 | Address hopping | Funds moved quickly through fresh single-use addresses | *planned: multi-hop phase* |
| R18 | Post-CoinJoin consolidation | Several CoinJoin outputs merged in one transaction | FATF RFI (anonymity) |
| R19 | Co-spending with flagged address | Inputs signed together with a sanctioned/high-risk address (common-input ownership) | OFAC SDN; FATF RFI (source of funds) |
| R20 | Round-trip | Funds returning to their origin within N hops | *planned: multi-hop phase* |
| R21 | Anomalous fee | Fee rate far above the block median (urgency) | FATF RFI (patterns) |

*FATF RFI = FATF (2020) Red Flag Indicators of ML/TF – Virtual Assets. EBA GL 21 = EBA ML/TF
Risk Factors Guidelines, Guideline 21 (CASPs). TFR = Regulation (EU) 2023/1113. References
are given at section level and should be verified against the official texts.*

## Roadmap

- [x] Project skeleton, configuration, CI
- [x] SQLite cache
- [x] Esplora API client (mempool.space with automatic Blockstream fallback) and BTC/EUR prices
- [x] OFAC SDN list import and custom address labels
- [x] Single-address analysis
- [x] Red-flag rules (18 of 21; R02, R17, R20 need multi-hop)
- [x] Explainable risk scoring (0–100, with sanctions override)
- [x] CSV reports and audit log
- [ ] Multi-hop exposure, clustering and change detection
- [ ] Block-range scanning

## Disclaimer

This is an educational project. It is **not** a validated compliance solution and must not be
used as the sole basis for any compliance decision. It uses only public data and contains no
non-public information from any professional activity.

## License

[MIT](LICENSE) © 2026 Edoardo Daprato
