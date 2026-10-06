"""User-maintained address labels (CSV: address, category, source, date_added).

Labels let a compliance team attribute addresses to entity types (exchange, mixer,
darknet market...). Each label must cite a verifiable public ``source`` so that any
alert based on it can be justified to an auditor or supervisor.

Imports are validated line by line: a malformed address, an unknown category, a
missing source or an invalid date rejects the whole file, so that the labels file
never contains half-imported data.
"""

from __future__ import annotations

import csv
import re
from dataclasses import astuple, dataclass
from datetime import date
from pathlib import Path

COLUMNS = ("address", "category", "source", "date_added")
CATEGORIES = frozenset(
    {"exchange", "mixer", "darknet_market", "ransomware", "scam", "gambling", "sanctioned"}
)

_BASE58 = re.compile(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$")
_BECH32 = re.compile(r"^bc1[02-9ac-hj-np-z]{11,71}$")


class LabelError(ValueError):
    """The labels file is malformed; the message lists every offending line."""


@dataclass(frozen=True)
class Label:
    address: str
    category: str
    source: str
    date_added: str


@dataclass(frozen=True)
class ImportResult:
    added: int
    duplicates: int
    total: int


def is_valid_btc_address(address: str) -> bool:
    """Format check for mainnet addresses (P2PKH, P2SH, SegWit, Taproot). No checksum."""
    return bool(_BASE58.match(address) or _BECH32.match(address))


def read_labels(path: Path) -> list[Label]:
    """Read and validate a labels CSV. A missing file means no labels."""
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise LabelError(f"{path}: header must be exactly {','.join(COLUMNS)}")
        labels, errors = [], []
        for line_number, row in enumerate(reader, start=2):
            label = Label(**{column: (row[column] or "").strip() for column in COLUMNS})
            problem = _validate(label)
            if problem:
                errors.append(f"line {line_number}: {problem}")
            else:
                labels.append(label)
    if errors:
        raise LabelError(f"{path}: " + "; ".join(errors))
    return labels


def import_labels(source: Path, target: Path) -> ImportResult:
    """Validate ``source`` and merge it into ``target``, skipping exact duplicates."""
    if not source.is_file():
        raise LabelError(f"File not found: {source}")
    existing = read_labels(target)
    incoming = read_labels(source)
    known = {(label.address, label.category) for label in existing}

    added = []
    for label in incoming:
        if (label.address, label.category) not in known:
            added.append(label)
            known.add((label.address, label.category))

    _write(target, existing + added)
    return ImportResult(
        added=len(added), duplicates=len(incoming) - len(added), total=len(existing) + len(added)
    )


def _validate(label: Label) -> str | None:
    if not is_valid_btc_address(label.address):
        return f"invalid Bitcoin address '{label.address}'"
    if label.category not in CATEGORIES:
        return f"unknown category '{label.category}' (allowed: {', '.join(sorted(CATEGORIES))})"
    if not label.source:
        return "missing source (every label must cite a verifiable public source)"
    try:
        date.fromisoformat(label.date_added)
    except ValueError:
        return f"date_added '{label.date_added}' is not YYYY-MM-DD"
    return None


def _write(path: Path, labels: list[Label]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(astuple(label) for label in labels)
