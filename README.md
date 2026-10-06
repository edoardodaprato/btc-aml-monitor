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

> ⚠️ **Status: work in progress (v0.4.0 — data layer and sanctions screening).** See the [CHANGELOG](CHANGELOG.md)
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
btc-aml screen 12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL
```

A beginner's guide in Italian is available in [docs/GUIDA.md](docs/GUIDA.md).

## Roadmap

- [x] Project skeleton, configuration, CI
- [x] SQLite cache
- [x] Esplora API client (mempool.space with automatic Blockstream fallback) and BTC/EUR prices
- [x] OFAC SDN list import and custom address labels
- [ ] Single-address analysis
- [ ] 16 red-flag rules
- [ ] Explainable risk scoring (0–100, with sanctions override)
- [ ] CSV reports and audit log
- [ ] Multi-hop exposure, clustering and change detection
- [ ] Block-range scanning

## Disclaimer

This is an educational project. It is **not** a validated compliance solution and must not be
used as the sole basis for any compliance decision. It uses only public data and contains no
non-public information from any professional activity.

## License

[MIT](LICENSE) © 2026 Edoardo Daprato
