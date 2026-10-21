"""Read saved runs from the output folder and record the manual review of their alerts.

The control panel never keeps results in memory: it reads the same CSV files and audit
log a reviewer would open by hand, so what the screen shows is exactly what was saved.

Manual review: for each alert the reviewer records a decision and a note. Decisions are
stored next to the reports (``review.json``) and exported as ``review.csv``; the
automated reports themselves are never modified.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_aml.reports.excel import Sheet, workbook_bytes

RUN_ID = re.compile(r"^\d{8}T\d{6}Z$")
DECISIONS = {
    "open": "Not reviewed",
    "escalate": "Escalate (possible suspicious activity)",
    "false_positive": "False positive",
    "no_action": "Explained, no action",
}
DOWNLOADABLE = frozenset(
    {
        "address_scores.csv",
        "alerts.csv",
        "transactions.csv",
        "blocks.csv",
        "block_alerts.csv",
        "addresses_for_review.txt",
        "audit_log.json",
        "run.log",
        "review.csv",
        "findings.csv",
        "reconciliation.csv",
        "rule_metrics.csv",
        "backlog.csv",
        "data_quality.csv",
        "qa_sample.csv",
    }
)
CONTROL_TABLES = (
    "findings",
    "reconciliation",
    "rule_metrics",
    "backlog",
    "data_quality",
    "qa_sample",
)
SHEET_TITLES = {
    "address_scores": "Address scores",
    "alerts": "Alerts",
    "transactions": "Transactions",
    "blocks": "Blocks",
    "block_alerts": "Block alerts",
    "findings": "Findings",
    "reconciliation": "Re-performance",
    "rule_metrics": "Rule metrics",
    "backlog": "Backlog",
    "data_quality": "Data quality",
    "qa_sample": "QA sample",
}
REVIEW_COLUMNS = ("alert_id", "rule_id", "subject", "decision", "note", "reviewer", "reviewed_at")


class RunNotFoundError(LookupError):
    """No run folder with this id (or an id that is not a run id at all)."""


@dataclass
class Run:
    run_id: str
    folder: Path
    audit: dict[str, Any]
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    reviews: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return self.audit.get("mode", "unknown")

    @property
    def alerts(self) -> list[dict[str, str]]:
        return self.tables.get("alerts") or self.tables.get("block_alerts") or []

    @property
    def reviewed_count(self) -> int:
        return sum(1 for r in self.reviews.values() if r.get("decision", "open") != "open")

    def decision_of(self, alert_id: str) -> dict[str, str]:
        return self.reviews.get(alert_id, {"decision": "open", "note": "", "reviewer": ""})


def list_runs(output_dir: Path) -> list[Run]:
    """Saved runs, newest first (folders without an audit log are ignored)."""
    if not output_dir.is_dir():
        return []
    runs = []
    for folder in sorted(output_dir.iterdir(), reverse=True):
        if RUN_ID.match(folder.name) and (folder / "audit_log.json").is_file():
            runs.append(load_run(output_dir, folder.name))
    return runs


def load_run(output_dir: Path, run_id: str) -> Run:
    folder = _run_folder(output_dir, run_id)
    audit = json.loads((folder / "audit_log.json").read_text(encoding="utf-8"))
    run = Run(run_id, folder, audit, reviews=_read_reviews(folder))
    for name in (
        "address_scores",
        "alerts",
        "transactions",
        "blocks",
        "block_alerts",
        *CONTROL_TABLES,
    ):
        path = folder / f"{name}.csv"
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as handle:
                run.tables[name] = list(csv.DictReader(handle))
    return run


def run_file(output_dir: Path, run_id: str, name: str) -> Path:
    """Path of a downloadable report file, refusing anything outside the allow-list."""
    path = _run_folder(output_dir, run_id) / name
    if name not in DOWNLOADABLE or not path.is_file():
        raise RunNotFoundError(f"No file {name} in run {run_id}")
    return path


def excel_name(run: Run) -> str:
    return f"tracery_{run.run_id}.xlsx"


def run_workbook(run: Run) -> bytes:
    """The whole run as one Excel workbook.

    Sheets: a summary of the audit log, then every report table. The alerts sheet also
    carries the reviewer's decision, note and date, so it doubles as the review export.
    """
    sheets = [Sheet("Summary", ("field", "value"), list(_flatten(run.audit)))]
    for name, rows in run.tables.items():
        header = list(rows[0]) if rows else []
        table = [[row.get(column, "") for column in header] for row in rows]
        if name in ("alerts", "block_alerts"):
            header = [*header, "review_decision", "review_note", "reviewer", "reviewed_at"]
            for row, values in zip(rows, table, strict=True):
                review = run.decision_of(row["alert_id"])
                values += [
                    DECISIONS[review["decision"]],
                    review.get("note", ""),
                    review.get("reviewer", ""),
                    review.get("reviewed_at", ""),
                ]
        sheets.append(Sheet(SHEET_TITLES.get(name, name), header, table))
    return workbook_bytes(sheets)


def _flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list) and any(isinstance(v, dict | list) for v in value):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    elif isinstance(value, list):
        yield prefix, ", ".join(str(v) for v in value)
    else:
        yield prefix, "" if value is None else str(value)


def save_review(
    output_dir: Path, run_id: str, alert_id: str, decision: str, note: str, reviewer: str
) -> None:
    """Record the reviewer's decision on one alert and refresh review.csv."""
    run = load_run(output_dir, run_id)
    alerts = {a["alert_id"]: a for a in run.alerts}
    if alert_id not in alerts:
        raise RunNotFoundError(f"No alert {alert_id} in run {run_id}")
    if decision not in DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}")
    run.reviews[alert_id] = {
        "decision": decision,
        "note": note.strip(),
        "reviewer": reviewer.strip(),
        "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (run.folder / "review.json").write_text(json.dumps(run.reviews, indent=2), encoding="utf-8")
    _write_review_csv(run, alerts)


def _write_review_csv(run: Run, alerts: dict[str, dict[str, str]]) -> None:
    with (run.folder / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(REVIEW_COLUMNS)
        for alert_id, alert in alerts.items():
            review = run.decision_of(alert_id)
            writer.writerow(
                (
                    alert_id,
                    alert["rule_id"],
                    alert.get("address") or alert.get("evidence_txids", ""),
                    DECISIONS[review["decision"]],
                    review.get("note", ""),
                    review.get("reviewer", ""),
                    review.get("reviewed_at", ""),
                )
            )


def _read_reviews(folder: Path) -> dict[str, dict[str, str]]:
    path = folder / "review.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _run_folder(output_dir: Path, run_id: str) -> Path:
    folder = output_dir / run_id
    if not RUN_ID.match(run_id) or not (folder / "audit_log.json").is_file():
        raise RunNotFoundError(f"No run {run_id}")
    return folder
