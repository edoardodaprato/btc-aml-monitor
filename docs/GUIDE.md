# btc-aml-monitor user guide

A step-by-step guide for readers starting from scratch. It describes version 1.0.0.

## 1. Installation

You need Python 3.11 or later and Git. In a terminal:

```bash
git clone https://github.com/edoardodaprato/btc-aml-monitor.git
cd btc-aml-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

| Command | What it does |
|---|---|
| `git clone ...` | Downloads the project from GitHub |
| `python3 -m venv .venv` | Creates an isolated Python environment for this project only |
| `source .venv/bin/activate` | Activates the environment; repeat it every time you open a new terminal |
| `pip install -e ".[dev]"` | Installs the tool and the libraries it needs |

To check that everything works:

```bash
btc-aml show-config
pytest
```

## 2. Configuration

All thresholds, weights and limits live in two text files that can be changed without
touching the code:

- `config/settings.yaml`: data sources, request limits, depth of the multi-hop analysis,
  risk bands.
- `config/rules.yaml`: for each rule, whether it is on (`enabled`), its weight in the
  score (`weight`), its severity (`severity`) and its thresholds (`params`).

If a value is invalid (for example a weight of 150 or a gap between risk bands), the tool
stops with a clear message instead of producing wrong scores. `btc-aml show-config` prints
the configuration in use and its **hash**, the fingerprint recorded in the audit log of
every analysis.

## 3. OFAC sanctions list

```bash
btc-aml update-ofac
```

Downloads the official SDN list from the U.S. Treasury and extracts the Bitcoin addresses
(type "Digital Currency Address - XBT") with the designated entity and the sanctions
programmes. It also stores the publication date and the SHA-256 fingerprint of the file:
together they form the **list version** recorded in every analysis.

Run it regularly (for example weekly), because OFAC updates the list often.

> Note: the same address can be attributed to several persons or entities. The tool keeps
> all of them, because every designation matters for reporting.

## 4. Address labels

The file `data/labels.csv` holds your own attributions: address → category. Start from the
empty template `data/labels_template.csv`:

```
address,category,source,date_added
```

| Column | Content |
|---|---|
| `address` | Bitcoin address |
| `category` | One of: `exchange`, `mixer`, `darknet_market`, `ransomware`, `scam`, `gambling`, `sanctioned` |
| `source` | Link or reference to a **verifiable** public source (mandatory) |
| `date_added` | Date added, format `YYYY-MM-DD` |

### Import procedure

1. Prepare a CSV with the same four columns, starting from a copy of the template.
2. For each row, put in the `source` column the public document the attribution comes from.
3. Import it:

   ```bash
   btc-aml import-labels my_labels.csv
   ```

4. The file is checked line by line. If even one line is wrong (malformed address, unknown
   category, missing source, invalid date), **the whole import is rejected** and the
   message lists the lines to fix. Labels already present are skipped, so the same file
   can be imported again without creating duplicates.

### Verifiable public sources

Guiding principle: **never add an attribution you could not document** in front of an
auditor or a supervisor.

| Source | Typical categories | Notes |
|---|---|---|
| U.S. Department of Justice court filings and press releases (e.g. forfeiture complaints) | darknet_market, ransomware, scam, mixer | Often list addresses in an annex; cite the case number |
| Europol, Eurojust and national authority press releases | darknet_market, mixer | Takedowns of marketplaces and mixers |
| Proof-of-reserves addresses published by exchanges | exchange | Published by the exchanges themselves; cite the official page |
| Open research datasets (e.g. collections of ransomware payment addresses) | ransomware | Check the evidence attached to each address |

OFAC addresses must **not** be copied into the labels file: `btc-aml update-ofac` already
handles them.

## 5. Analysing an address

```bash
btc-aml analyze <address>
```

The tool downloads the address history (up to `max_tx_per_address` transactions), converts
every amount to EUR at the price of the day, runs every enabled rule and prints the alerts
with their explanation and regulatory reference. A second analysis of the same address uses
the cache and is almost instant.

If the history exceeds the limit, the output says **TRUNCATED**: the oldest transactions
were not analysed.

### Analysing a list of addresses (address mode)

```bash
btc-aml scan-addresses examples/demo_addresses.txt
```

The file holds one address per line. Blank lines and lines starting with `#` are ignored,
so the file can be annotated. Invalid lines are reported and skipped without stopping the
run.

Every run creates a folder `output/<date-time>/` with:

| File | Content |
|---|---|
| `address_scores.csv` | One address per row: score, band, rules triggered, score explanation |
| `alerts.csv` | One alert per row: rule, severity, score contribution, evidence transactions, amounts, explanation, regulatory reference |
| `transactions.csv` | Every analysed transaction, with net amount, EUR value and the date of the price used |
| `audit_log.json` | Audit trail: date, tool version, input file fingerprint, rule version and parameters, OFAC list version, data sources used, skipped addresses |
| `run.log` | Technical log of the run |

**How the score is computed.** Each triggered rule contributes once, even if it raises
several alerts: its weight times the strength of its strongest alert (indirect exposure is
weakened at each hop). The total is capped at 100. Bands: Low 0-24, Medium 25-49,
High 50-74, Severe 75-100. Direct sanctions exposure (R01) always means Severe. The
`score_explanation` column shows the contribution of each rule.

**EUR prices.** Historical prices come from mempool.space: hourly for recent dates, weekly
for older ones (up to 7 days before the transaction), none before July 2010. On some days
mempool.space has a USD price but no EUR price: if you have downloaded the official ECB
rates with `btc-aml update-fx`, the tool converts the USD price at that day's ECB reference
rate. The `btc_eur_price_source` column always states which source was used. When no price
is available, the EUR cell is left empty.

## 6. The rules in plain words

| ID | Rule | What it means | Why it is a red flag |
|---|---|---|---|
| R01 | Direct sanctions exposure | The address is on the OFAC list, or exchanged funds directly with one that is | Possible sanctions breach: always Severe |
| R02 | Indirect sanctions exposure | Sanctioned funds 2-3 hops away | Sanctions are evaded through intermediaries; the weight decreases at each hop |
| R03 | High-risk categories | Transactions with addresses labelled mixer, darknet market, ransomware, scam | Illicit or opaque source of funds |
| R04 | CoinJoin | Taking part in transactions that mix the coins of several users | Deliberately breaks traceability |
| R05 | Peel chain | A chain of transactions that "peel off" small amounts and pass the rest on | Typical of cashing out stolen funds in instalments |
| R06 | Structuring | Several amounts just below 1,000 or 10,000 EUR within a few hours | Splitting to avoid controls (Travel Rule, internal thresholds) |
| R07 | Pass-through | Funds received and sent on within 24 hours, balance back to zero | Transit account, money-mule behaviour |
| R08 | Fan-in | Many different senders in a short time | Collection of proceeds (scam victims, ransoms) |
| R09 | Fan-out | Many different recipients in a short time | Dispersal of funds (layering) |
| R10 | High velocity | Too many transactions in one day | Automated movement of funds |
| R11 | Dormant reactivation | An address idle for over a year moves significant amounts | Possible cash-out of proceeds of old crimes |
| R12 | New address, high volume | Large amounts in the first transactions | Throwaway address |
| R13 | Round amounts | Several transfers of exactly 0.1 or 1 BTC | OTC deals or pre-agreed payments |
| R14 | Large transaction | A single transaction above 100,000 EUR | Higher inherent risk, requires source-of-funds checks |
| R15 | Dust | Tiny amounts from many sources | Tracking attack: the address is being watched |
| R16 | Consolidation | Many small inputs merged into one transaction | Aggregation of proceeds of many small offences |
| R17 | Address hopping | Funds moved quickly through fresh single-use addresses | Layering: adds distance from the origin with no economic reason |
| R18 | Post-CoinJoin consolidation | Several CoinJoin outputs merged together | Collecting "laundered" funds before depositing them at an exchange |
| R19 | Co-spending with a flagged address | The address signs a transaction together with a sanctioned or high-risk address | They probably belong to the same entity |
| R20 | Round-trip | Funds come back to the origin after a few hops | Circular flows: artificial history or "cleaning" |
| R21 | Anomalous fee | Fee far above the block median | Urgency to move funds (e.g. after a theft) |

**How to read alerts.** An alert is an indicator, not proof. Several rules (fan-in, fan-out,
consolidation) also fire for legitimate services such as exchanges: every alert must be
read in the context of the customer and the address.

**EUR amounts.** When no historical price is available, rules with EUR thresholds use the
equivalent BTC threshold and say so in the explanation. Structuring (R06) is evaluated only
on transactions with a known price, because its thresholds only make sense in EUR.

## 7. Multi-hop analysis, clusters and change

**Multi-hop exposure.** The tool follows funds beyond direct counterparties, in both
directions: where the money received came from (source of funds) and where the money sent
went (destination). Amounts are attributed **pro rata**: if a counterparty received 25% of
its inflows from a sanctioned address before paying us, 25% of what it paid us counts as
exposed. Only what happened **before** (for the source) or **after** (for the destination)
counts.

The weight in the score decreases with distance (`hop_decay`: 100% at the first hop, 50% at
the second, 25% at the third). To avoid thousands of API calls the expansion has limits:
number of hops, addresses per hop, transactions per address, maximum time. When a limit is
hit, the report says so (`exposure_complete = False` and `exposure_notes`).

**High-degree nodes.** Addresses with a very large number of transactions (above
`high_degree_threshold`, usually exchanges and services) are not expanded: pro-rata
attribution through an exchange's shared wallet would be meaningless. They are listed in
`high_degree_counterparties`.

**Clusters.** Addresses that sign a transaction together normally belong to the same wallet
(the *common-input-ownership* heuristic), and change goes back to the sender. The tool uses
this to group the addresses of the same probable entity, excluding CoinJoins. **A cluster of
thousands of addresses** usually means a custodial service (for example an exchange's
deposit addresses swept together).

**Change detection.** Three heuristics, in order of reliability: reuse of an input address,
same script type as the inputs, non-round amount when the payment is round. When the case
is ambiguous, no output is treated as change.

## 8. Block scan

Address mode starts from addresses you already care about. **Block scan** starts from the
blockchain instead: it reads every transaction of one or more blocks (at most 10,
`block_scan.max_blocks` in `settings.yaml`) and flags those that show a red flag on their
own.

```bash
btc-aml scan-blocks 733459            # a single block
btc-aml scan-blocks 733459 733461     # blocks 733459 to 733461 inclusive
```

The number is the block **height**, its position in the chain (the first block is 0). A
full block holds 2,000-5,000 transactions and the first read takes about a minute per
block, because public APIs return 25 transactions at a time. Later reads use the cache and
are instant.

**Which rules.** Only those that make sense on a single transaction: sanctioned (R01) or
labelled (R03) addresses, CoinJoin (R04), payments to many recipients (R09), transfers above
threshold excluding change (R14), consolidation of many small inputs (R16) and fees far
above the block median (R21). Thresholds are the same as in `rules.yaml`. Rules that need an
address history (structuring, velocity, dormancy...) stay in address mode.

**Block clustering (R19).** Addresses that spend together with a sanctioned or labelled
address, even in different transactions of the same block, are flagged as probably the same
wallet. **When the cluster exceeds 50 addresses** the explanation warns that it is typically a
custodial service (an exchange sweeping customer deposits). In that case the sanctioned
address is probably a customer's deposit address, and the exchange is the party to contact.

**Files produced** in `output/<run_id>/`:

| File | Content |
|---|---|
| `blocks.csv` | One row per block: hash, date, number of transactions, median fee rate, BTC/EUR price used, number of alerts |
| `block_alerts.csv` | One alert per row: rule, severity, transactions, addresses involved, amount in BTC and EUR, explanation, regulatory reference |
| `addresses_for_review.txt` | Sanctioned or labelled addresses and their co-spenders, ready for `btc-aml scan-addresses`. Members of large clusters are included but commented out with `#` |
| `audit_log.json`, `run.log` | Traceability, as in address mode |

**A real example.** In block 733459 (April 2022) the scan finds two addresses on the OFAC
list spending funds, each together with dozens or hundreds of other addresses: the typical
behaviour of an exchange collecting deposits. The other alerts in the block (large
transfers, batch payments, consolidations) are mostly normal exchange and mining-pool
activity. Any block has dozens of them, and they should be read as a list of things to
look at, not as established suspicions.

## 9. Ready-made examples

The `examples/` folder contains the real results of two analyses, so you can look at the
files without running anything:

- `examples/address_mode/`: the three addresses of `demo_addresses.txt` (two on the OFAC
  list and the genesis block address);
- `examples/block_scan/`: the scan of block 733459.

Addresses that are not public for a documented reason (OFAC list or demo addresses) are
replaced with `<address redacted>`. The others belong to ordinary people: publishing them
next to an alert would read as an accusation, even though an alert is only a heuristic.
Transaction ids (txids) are kept, because they serve as evidence and anyone can check them
on a block explorer.

## 10. Limitations compared with commercial tools

This project shows the logic of a transaction-monitoring system, but it does **not
replace** tools such as Chainalysis, Elliptic or TRM Labs. The main differences:

- **Attribution.** The real value of commercial tools is millions of already-labelled
  addresses (exchanges, services, illicit actors). Here we only know the OFAC list and the
  labels you import. An address with no known links scores *Low* even if it belongs to an
  illicit service.
- **Heuristics make mistakes.** Common-input clustering breaks with PayJoin and
  collaborative transactions, and merges customer deposits when an exchange sweeps them.
  Change detection is an estimate. Fan-in, fan-out, consolidations and large transfers are
  everyday activity for exchanges and mining pools. **An alert is a lead to investigate, not
  a conclusion.**
- **Limited coverage.** At most 200 transactions per address, 20 counterparties per hop,
  3 hops, 10 minutes per address, 10 blocks per scan. When a limit is hit the report says
  so, but whatever lies beyond it is not seen.
- **Bitcoin only, on-chain only.** No other blockchains, Lightning, bridges, internal
  exchange data or Travel Rule messages.
- **Public APIs.** Free but slow and rate-limited, with no service guarantee.
- **Prices.** For older dates the BTC/EUR price can be up to 7 days old; the date and source
  are always stated.
- **Regulatory references and thresholds.** References are given at section level and
  should be checked against the official texts; weights and thresholds are illustrative,
  not calibrated on real data.
- **Not a validated system.** There is no model validation, case management, four-eyes
  review or alert tuning on a real customer base.

## 11. Available commands

| Command | What it does |
|---|---|
| `btc-aml show-config` | Checks and prints the configuration |
| `btc-aml fetch-tx <txid>` | Downloads a transaction and shows its value in EUR |
| `btc-aml update-ofac` | Downloads the latest OFAC list |
| `btc-aml update-fx` | Downloads the ECB EUR/USD reference rates |
| `btc-aml import-labels <file.csv>` | Imports labels from a CSV |
| `btc-aml screen <address> ...` | Checks one or more addresses against OFAC and the labels |
| `btc-aml analyze <address>` | Analyses one address with every rule |
| `btc-aml scan-addresses <file>` | Analyses every address in a file and writes the reports |
| `btc-aml scan-blocks <start> [end]` | Checks every transaction of a block range |
| `btc-aml cache-stats` | Shows how much data is stored in the local cache |
