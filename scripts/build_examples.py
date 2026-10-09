"""Copy the reports of a run into examples/, redacting third-party addresses.

Only addresses that are public for a documented reason are kept: those on the OFAC SDN
list and those in examples/demo_addresses.txt. Every other address is replaced, because
publishing a private person's address next to an alert would read as an accusation even
though alerts are heuristic leads. Transaction ids are kept as verifiable evidence.

Usage:
    python scripts/build_examples.py output/<run_id> examples/address_mode
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from btc_aml.config import load_config
from btc_aml.data_sources.ofac import load_ofac_list
from btc_aml.runner import read_address_file

ADDRESS = re.compile(r"\b(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
REDACTED = "<address redacted>"
PUBLISHED_FILES = (
    "address_scores.csv",
    "alerts.csv",
    "transactions.csv",
    "blocks.csv",
    "block_alerts.csv",
    "addresses_for_review.txt",
    "audit_log.json",
)


def main(run_dir: Path, target: Path) -> None:
    config = load_config(Path("config"))
    public = set(load_ofac_list(config.ofac_local_path).addresses)
    public |= set(read_address_file(Path("examples/demo_addresses.txt"))[0])

    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    redacted = 0
    for name in PUBLISHED_FILES:
        source = run_dir / name
        if not source.is_file():
            continue
        text, count = _redact(source.read_text(encoding="utf-8"), public)
        if name == "addresses_for_review.txt":
            kept = [line for line in text.splitlines() if REDACTED not in line]
            if len(kept) < len(text.splitlines()):
                kept.append("# (third-party addresses removed from this published example)")
            text = "\n".join(kept) + "\n"
        (target / name).write_text(text, encoding="utf-8")
        redacted += count
    print(f"{target}: {redacted} third-party address occurrences redacted")


def _redact(text: str, public: set[str]) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        if match.group(0) in public:
            return match.group(0)
        count += 1
        return REDACTED

    return ADDRESS.sub(replace, text), count


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
