# Examples

Real outputs of btc-aml-monitor v1.0.0, generated on 9-10 October 2026 with the default
configuration and the OFAC SDN list of that date.

| Folder | Command | Content |
|---|---|---|
| [`address_mode/`](address_mode) | `btc-aml scan-addresses examples/demo_addresses.txt` | `address_scores.csv`, `alerts.csv`, `transactions.csv`, `audit_log.json` |
| [`block_scan/`](block_scan) | `btc-aml scan-blocks 733459` | `blocks.csv`, `block_alerts.csv`, `addresses_for_review.txt`, `audit_log.json` |

[`demo_addresses.txt`](demo_addresses.txt) contains only addresses that are public for a
documented reason: two addresses on the OFAC SDN list and the genesis block address. One
invalid line is kept on purpose to show how errors are reported.

## Redaction

The reports were copied here with
[`scripts/build_examples.py`](../scripts/build_examples.py), which keeps OFAC-listed and
demo addresses and replaces every other address with `<address redacted>`. Those are
addresses of private parties: publishing them next to a heuristic alert would read as an
accusation. Transaction ids are kept, so every alert can still be checked on a block
explorer.

Results change over time: new transactions arrive, only the latest 200 transactions of an
address are analysed, and public APIs can return slightly different price points. Running
the same command today may give different numbers.
