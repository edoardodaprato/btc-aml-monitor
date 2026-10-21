"""Test a firm's transaction monitoring the way an auditor or a supervisor would.

Input: the firm's alert export (one row per alert, see ``FIRM_ALERT_COLUMNS``) and,
optionally, a Tracery address-mode run over the same addresses. Output: the evidence a
reviewer needs, without any model or prediction:

* data quality: is the alert file complete and internally consistent?
* re-performance: does an independent run over the same population agree with the
  firm's alerts? Where it does not, which side is likely wrong?
* rule metrics: per rule, how many alerts, how many escalated, how fast closed?
* backlog: how many alerts are open and for how long?
* closure quality: closures that are too fast, unexplained, copy-pasted, inconsistent
  or that clear a sanctioned address.
* QA sample: a reproducible random sample of closed alerts for re-review, sized for
  zero-defect attribute testing.

Every threshold is a parameter recorded in the audit log, so the test can be re-run
and challenged. Nothing here changes the firm's data or Tracery's own reports.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from btc_aml import __version__
from btc_aml.data_sources.labels import is_valid_btc_address

REQUIRED_COLUMNS = ("alert_id", "address", "rule", "created_at", "status")
OPTIONAL_COLUMNS = ("disposition", "closed_at", "reviewer", "rationale", "txid")
FIRM_ALERT_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

DISPOSITIONS = {
    "escalated": "Escalated",
    "false_positive": "False positive",
    "no_action": "Explained, no action",
}
DISPOSITION_SYNONYMS = {
    "escalated": "escalated",
    "escalate": "escalated",
    "sar": "escalated",
    "str": "escalated",
    "sar filed": "escalated",
    "false_positive": "false_positive",
    "false positive": "false_positive",
    "fp": "false_positive",
    "no_action": "no_action",
    "no action": "no_action",
    "explained": "no_action",
    "explained, no action": "no_action",
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
HIGH_RISK_BANDS = ("High", "Severe")
BAND_ORDER = ("Low", "Medium", "High", "Severe")
AGE_BUCKETS = (
    (0, 7, "0-7 days"),
    (8, 30, "8-30 days"),
    (31, 90, "31-90 days"),
    (91, None, "over 90 days"),
)

TEMPLATE_CSV = (
    "alert_id,address,rule,created_at,status,disposition,closed_at,reviewer,rationale,txid\n"
    "A-0001,bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4,Fan-in,2026-09-01T10:00:00Z,closed,"
    'false_positive,2026-09-03T15:20:00Z,AB,"Payroll consolidation, customer explanation and '
    'invoices on file",\n'
)

RULE_METRIC_COLUMNS = (
    "rule",
    "alerts",
    "open",
    "closed",
    "escalated",
    "false_positive",
    "no_action",
    "escalation_rate",
    "median_days_to_close",
    "open_over_sla",
    "finding",
)
RECONCILIATION_COLUMNS = (
    "address",
    "firm_alerts",
    "firm_open",
    "firm_escalated",
    "firm_closed_without_escalation",
    "tracery_score",
    "tracery_band",
    "tracery_rules",
    "result",
    "note",
)
FINDING_COLUMNS = ("alert_id", "address", "rule", "severity", "finding", "detail")
DATA_QUALITY_COLUMNS = ("row", "alert_id", "field", "severity", "issue")
BACKLOG_COLUMNS = ("age", "open_alerts", "over_sla")
QA_SAMPLE_COLUMNS = (
    "alert_id",
    "address",
    "rule",
    "disposition",
    "reviewer",
    "closed_at",
    "rationale",
    "qa_outcome",
    "qa_comment",
)


class ControlTestError(ValueError):
    """The alert file cannot be tested at all (missing columns, no usable rows)."""


@dataclass(frozen=True)
class ControlTestParams:
    """Thresholds of the test. All are recorded in the audit log."""

    as_of: date
    sla_days: int = 30
    fast_closure_minutes: int = 5
    min_rationale_chars: int = 20
    repeated_rationale_min: int = 5
    max_closures_per_reviewer_day: int = 50
    zero_conversion_min_closed: int = 20
    qa_confidence: float = 0.95
    qa_tolerable_error: float = 0.05
    tracery_alert_band: str = "High"  # Tracery band from which an address "should" alert

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["as_of"] = self.as_of.isoformat()
        return data


@dataclass
class FirmAlert:
    row: int
    alert_id: str
    address: str
    rule: str
    created_at: datetime
    status: str  # open | closed
    disposition: str | None  # escalated | false_positive | no_action
    closed_at: datetime | None
    reviewer: str
    rationale: str
    txid: str


@dataclass
class TraceryAddress:
    """What an independent Tracery run found for one address."""

    address: str
    score: int
    band: str
    rules: list[str]
    sanctioned: bool  # R01: the address itself is on the OFAC list


@dataclass
class ControlTestResult:
    params: ControlTestParams
    alerts: list[FirmAlert]
    data_quality: list[dict[str, Any]]
    rule_metrics: list[dict[str, Any]]
    backlog: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    qa_sample: list[dict[str, Any]]
    qa_sample_size: int
    qa_seed: int
    reconciliation: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        closed = [a for a in self.alerts if a.status == "closed"]
        open_alerts = [a for a in self.alerts if a.status == "open"]
        return {
            "alerts_tested": len(self.alerts),
            "rows_rejected": len({d["row"] for d in self.data_quality if d["severity"] == "high"}),
            "open_alerts": len(open_alerts),
            "open_over_sla": sum(
                1 for a in open_alerts if _age_days(a, self.params) > self.params.sla_days
            ),
            "closed_alerts": len(closed),
            "escalated": sum(1 for a in closed if a.disposition == "escalated"),
            "findings_by_severity": dict(Counter(f["severity"] for f in self.findings)),
            "reconciliation": dict(Counter(r["result"] for r in self.reconciliation)),
            "qa_sample_size": len(self.qa_sample),
        }


# --- reading the firm's alert file ---------------------------------------------------------


def read_firm_alerts(text: str) -> tuple[list[FirmAlert], list[dict[str, Any]]]:
    """Parse the alert export. Returns the usable alerts and the data-quality issues.

    A row with a missing or unreadable required field is listed as an issue and left
    out of the metrics; minor problems are listed but the row is kept.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ControlTestError(
            "The alert file is missing the column(s): "
            + ", ".join(missing)
            + ". Expected: "
            + ", ".join(FIRM_ALERT_COLUMNS)
            + "."
        )
    alerts: list[FirmAlert] = []
    issues: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    for number, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        alert_id = row.get("alert_id", "")

        def issue(
            column: str, severity: str, text: str, number: int = number, alert_id: str = alert_id
        ) -> None:
            issues.append(
                {
                    "row": number,
                    "alert_id": alert_id,
                    "field": column,
                    "severity": severity,
                    "issue": text,
                }
            )

        usable = True
        for column in REQUIRED_COLUMNS:
            if not row.get(column):
                issue(column, "high", "missing required value")
                usable = False
        if alert_id and alert_id in seen_ids:
            issue("alert_id", "high", f"duplicate of row {seen_ids[alert_id]}")
            usable = False
        elif alert_id:
            seen_ids[alert_id] = number
        if row.get("address") and not is_valid_btc_address(row["address"]):
            issue("address", "medium", "not a valid Bitcoin address")
        created = _parse_time(row.get("created_at", ""))
        if row.get("created_at") and created is None:
            issue("created_at", "high", f"unreadable date {row['created_at']!r}")
            usable = False
        status = row.get("status", "").lower()
        if status and status not in ("open", "closed"):
            issue("status", "high", f"unknown status {row['status']!r} (expected open or closed)")
            usable = False
        disposition = None
        if row.get("disposition"):
            disposition = DISPOSITION_SYNONYMS.get(row["disposition"].lower())
            if disposition is None:
                issue("disposition", "medium", f"unknown disposition {row['disposition']!r}")
        closed = _parse_time(row.get("closed_at", ""))
        if row.get("closed_at") and closed is None:
            issue("closed_at", "medium", f"unreadable date {row['closed_at']!r}")
        if status == "closed":
            if disposition is None and not row.get("disposition"):
                issue("disposition", "medium", "closed alert without a disposition")
            if closed is None and not row.get("closed_at"):
                issue("closed_at", "medium", "closed alert without a closing date")
        if status == "open" and (disposition or closed):
            issue("status", "medium", "open alert with a disposition or closing date")
        if created and closed and closed < created:
            issue("closed_at", "medium", "closed before it was created")
        if not usable:
            continue
        alerts.append(
            FirmAlert(
                row=number,
                alert_id=alert_id,
                address=row["address"],
                rule=row["rule"],
                created_at=created,  # type: ignore[arg-type]  # checked above
                status=status,
                disposition=disposition if status == "closed" else None,
                closed_at=closed if status == "closed" else None,
                reviewer=row.get("reviewer", ""),
                rationale=row.get("rationale", ""),
                txid=row.get("txid", ""),
            )
        )
    if not alerts:
        raise ControlTestError("The alert file has no usable rows.")
    return alerts, issues


def _parse_time(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        value = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# --- reading a Tracery run for re-performance ------------------------------------------------


def read_tracery_run(folder: Path) -> dict[str, TraceryAddress]:
    """Address-mode results of a Tracery run, by address."""
    scores_path, alerts_path = folder / "address_scores.csv", folder / "alerts.csv"
    if not scores_path.is_file():
        raise ControlTestError(
            "The selected run is not an address analysis (no address_scores.csv)."
        )
    sanctioned = set()
    if alerts_path.is_file():
        with alerts_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["rule_id"].startswith("R01") and row.get("hop_distance") == "0":
                    sanctioned.add(row["address"])
    result = {}
    with scores_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rules = [r for r in row["rules_triggered"].split(";") if r]
            result[row["address"]] = TraceryAddress(
                address=row["address"],
                score=int(row["risk_score"]),
                band=row["risk_band"],
                rules=rules,
                sanctioned=row["address"] in sanctioned,
            )
    return result


# --- the test --------------------------------------------------------------------------------


def run_control_test(
    text: str,
    params: ControlTestParams,
    tracery: dict[str, TraceryAddress] | None = None,
) -> ControlTestResult:
    alerts, data_quality = read_firm_alerts(text)
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    sample_size = qa_sample_size(params.qa_confidence, params.qa_tolerable_error)
    closed = [a for a in alerts if a.status == "closed"]
    sample = random.Random(seed).sample(closed, min(sample_size, len(closed)))
    sample.sort(key=lambda a: a.row)
    result = ControlTestResult(
        params=params,
        alerts=alerts,
        data_quality=data_quality,
        rule_metrics=_rule_metrics(alerts, params),
        backlog=_backlog(alerts, params),
        findings=_closure_findings(alerts, params, tracery or {}),
        qa_sample=[_qa_row(a) for a in sample],
        qa_sample_size=sample_size,
        qa_seed=seed,
    )
    result.findings.extend(
        _finding(None, "medium", "Rule never leads to escalation", row["finding"], rule=row["rule"])
        for row in result.rule_metrics
        if row["finding"]
    )
    if tracery is not None:
        result.reconciliation = _reconcile(alerts, tracery, params)
        result.findings.extend(_reconciliation_findings(result.reconciliation))
    result.findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["alert_id"], f["finding"]))
    return result


def qa_sample_size(confidence: float, tolerable_error: float) -> int:
    """Zero-defect attribute sample: with n clean items, the error rate is below the
    tolerable rate at the given confidence (n = ln(1 - c) / ln(1 - e), rounded up)."""
    return math.ceil(math.log(1 - confidence) / math.log(1 - tolerable_error))


def _age_days(alert: FirmAlert, params: ControlTestParams) -> int:
    return (params.as_of - alert.created_at.date()).days


def _rule_metrics(alerts: list[FirmAlert], params: ControlTestParams) -> list[dict[str, Any]]:
    by_rule: dict[str, list[FirmAlert]] = defaultdict(list)
    for alert in alerts:
        by_rule[alert.rule].append(alert)
    rows = []
    for rule, items in sorted(by_rule.items()):
        closed = [a for a in items if a.status == "closed"]
        counts = Counter(a.disposition for a in closed)
        durations = [
            (a.closed_at - a.created_at).total_seconds() / 86400 for a in closed if a.closed_at
        ]
        open_items = [a for a in items if a.status == "open"]
        over_sla = sum(1 for a in open_items if _age_days(a, params) > params.sla_days)
        escalation_rate = counts["escalated"] / len(closed) if closed else None
        finding = ""
        if len(closed) >= params.zero_conversion_min_closed and counts["escalated"] == 0:
            finding = "no escalation in any closed alert: check the rule still targets a real risk"
        rows.append(
            {
                "rule": rule,
                "alerts": len(items),
                "open": len(open_items),
                "closed": len(closed),
                "escalated": counts["escalated"],
                "false_positive": counts["false_positive"],
                "no_action": counts["no_action"],
                "escalation_rate": "" if escalation_rate is None else f"{escalation_rate:.1%}",
                "median_days_to_close": f"{statistics.median(durations):.1f}" if durations else "",
                "open_over_sla": over_sla,
                "finding": finding,
            }
        )
    return rows


def _backlog(alerts: list[FirmAlert], params: ControlTestParams) -> list[dict[str, Any]]:
    open_alerts = [a for a in alerts if a.status == "open"]
    rows = []
    for low, high, label in AGE_BUCKETS:
        bucket = [
            a
            for a in open_alerts
            if _age_days(a, params) >= low and (high is None or _age_days(a, params) <= high)
        ]
        rows.append(
            {
                "age": label,
                "open_alerts": len(bucket),
                "over_sla": sum(1 for a in bucket if _age_days(a, params) > params.sla_days),
            }
        )
    return rows


def _finding(
    alert: FirmAlert | None, severity: str, finding: str, detail: str, **override: str
) -> dict[str, Any]:
    return {
        "alert_id": override.get("alert_id", alert.alert_id if alert else ""),
        "address": override.get("address", alert.address if alert else ""),
        "rule": override.get("rule", alert.rule if alert else ""),
        "severity": severity,
        "finding": finding,
        "detail": detail,
    }


def _closure_findings(
    alerts: list[FirmAlert], params: ControlTestParams, tracery: dict[str, TraceryAddress]
) -> list[dict[str, Any]]:
    findings = []
    closed = [a for a in alerts if a.status == "closed"]
    normalised = Counter(_normalise(a.rationale) for a in closed if a.rationale)
    per_reviewer_day = Counter(
        (a.reviewer, a.closed_at.date()) for a in closed if a.reviewer and a.closed_at
    )

    for alert in closed:
        not_escalated = alert.disposition in ("false_positive", "no_action")
        hit = tracery.get(alert.address)
        if not_escalated and hit is not None and hit.sanctioned:
            findings.append(
                _finding(
                    alert,
                    "critical",
                    "Sanctioned address closed without escalation",
                    "The address is on the OFAC SDN list (Tracery R01) but the alert was closed as "
                    f"{DISPOSITIONS[alert.disposition]}.",
                )
            )
        if not alert.rationale:
            findings.append(
                _finding(
                    alert,
                    "high",
                    "No rationale recorded",
                    "A closed alert must say why it was closed.",
                )
            )
        elif len(alert.rationale) < params.min_rationale_chars:
            findings.append(
                _finding(
                    alert,
                    "medium",
                    "Rationale too short",
                    f"{len(alert.rationale)} characters (minimum {params.min_rationale_chars}).",
                )
            )
        if (
            alert.rationale
            and normalised[_normalise(alert.rationale)] >= params.repeated_rationale_min
        ):
            findings.append(
                _finding(
                    alert,
                    "medium",
                    "Copy-pasted rationale",
                    f"Same text used in {normalised[_normalise(alert.rationale)]} closures.",
                )
            )
        if alert.closed_at:
            minutes = (alert.closed_at - alert.created_at).total_seconds() / 60
            if 0 <= minutes < params.fast_closure_minutes:
                findings.append(
                    _finding(
                        alert,
                        "high",
                        "Closed too fast to have been investigated",
                        f"Closed {minutes:.0f} minute(s) after it was raised.",
                    )
                )
            if (
                alert.reviewer
                and per_reviewer_day[(alert.reviewer, alert.closed_at.date())]
                > params.max_closures_per_reviewer_day
            ):
                count = per_reviewer_day[(alert.reviewer, alert.closed_at.date())]
                findings.append(
                    _finding(
                        alert,
                        "medium",
                        "Reviewer closed an unusual volume that day",
                        f"{alert.reviewer} closed {count} alerts on {alert.closed_at.date()}.",
                    )
                )
        if not alert.reviewer:
            findings.append(
                _finding(
                    alert,
                    "medium",
                    "No reviewer recorded",
                    "The person accountable for the decision is not identified.",
                )
            )

    for alert in alerts:
        if alert.status == "open" and _age_days(alert, params) > params.sla_days:
            findings.append(
                _finding(
                    alert,
                    "high",
                    "Open beyond the review deadline",
                    f"Open for {_age_days(alert, params)} days (deadline {params.sla_days}).",
                )
            )

    by_address: dict[str, set[str]] = defaultdict(set)
    for alert in closed:
        if alert.disposition:
            by_address[alert.address].add(alert.disposition)
    for address, outcomes in sorted(by_address.items()):
        if "escalated" in outcomes and "false_positive" in outcomes:
            findings.append(
                _finding(
                    None,
                    "medium",
                    "Inconsistent outcomes for the same address",
                    "Some alerts on this address were escalated, others closed as false positive.",
                    address=address,
                )
            )
    return findings


def _normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _qa_row(alert: FirmAlert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "address": alert.address,
        "rule": alert.rule,
        "disposition": DISPOSITIONS.get(alert.disposition or "", ""),
        "reviewer": alert.reviewer,
        "closed_at": alert.closed_at.isoformat(timespec="minutes") if alert.closed_at else "",
        "rationale": alert.rationale,
        "qa_outcome": "",
        "qa_comment": "",
    }


def _reconcile(
    alerts: list[FirmAlert], tracery: dict[str, TraceryAddress], params: ControlTestParams
) -> list[dict[str, Any]]:
    by_address: dict[str, list[FirmAlert]] = defaultdict(list)
    for alert in alerts:
        by_address[alert.address].append(alert)
    threshold = BAND_ORDER.index(params.tracery_alert_band)
    rows = []
    for address in sorted(set(tracery) | set(by_address)):
        items = by_address.get(address, [])
        hit = tracery.get(address)
        escalated = sum(1 for a in items if a.disposition == "escalated")
        cleared = sum(1 for a in items if a.disposition in ("false_positive", "no_action"))
        if hit is None:
            result, note = (
                "outside re-performed population",
                "The firm alerted on an address the independent run did not cover.",
            )
        else:
            risky = BAND_ORDER.index(hit.band) >= threshold if hit.band in BAND_ORDER else False
            if hit.sanctioned and not escalated:
                result = "sanctions gap"
                note = "Address on the OFAC SDN list, no escalated alert at the firm."
            elif risky and not items:
                result = "possible missed alert"
                note = f"Tracery scores it {hit.band} ({hit.score}) but the firm raised no alert."
            elif risky:
                result = "agreed: high risk"
                note = "Both sides flag the address."
            elif items:
                result = "firm only"
                note = (
                    "The firm alerted, Tracery scores it lower: "
                    "a firm rule Tracery lacks, or over-alerting."
                )
            else:
                result = "agreed: no alert"
                note = ""
        rows.append(
            {
                "address": address,
                "firm_alerts": len(items),
                "firm_open": sum(1 for a in items if a.status == "open"),
                "firm_escalated": escalated,
                "firm_closed_without_escalation": cleared,
                "tracery_score": "" if hit is None else hit.score,
                "tracery_band": "" if hit is None else hit.band,
                "tracery_rules": "" if hit is None else ";".join(hit.rules),
                "result": result,
                "note": note,
            }
        )
    return rows


def _reconciliation_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity = {"sanctions gap": "critical", "possible missed alert": "high"}
    return [
        _finding(
            None,
            severity[row["result"]],
            row["result"].capitalize(),
            row["note"],
            address=row["address"],
        )
        for row in rows
        if row["result"] in severity
    ]


# --- writing the reports ---------------------------------------------------------------------


def write_control_test(result: ControlTestResult, folder: Path) -> dict[str, Path]:
    files = {
        "data_quality": (folder / "data_quality.csv", DATA_QUALITY_COLUMNS, result.data_quality),
        "rule_metrics": (folder / "rule_metrics.csv", RULE_METRIC_COLUMNS, result.rule_metrics),
        "backlog": (folder / "backlog.csv", BACKLOG_COLUMNS, result.backlog),
        "findings": (folder / "findings.csv", FINDING_COLUMNS, result.findings),
        "qa_sample": (folder / "qa_sample.csv", QA_SAMPLE_COLUMNS, result.qa_sample),
    }
    if result.reconciliation:
        files["reconciliation"] = (
            folder / "reconciliation.csv",
            RECONCILIATION_COLUMNS,
            result.reconciliation,
        )
    for path, columns, rows in files.values():
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return {name: path for name, (path, _, _) in files.items()}


# --- a control test as a run ------------------------------------------------------------------


@dataclass
class ControlRunResult:
    run_id: str
    output_dir: Path
    result: ControlTestResult


def run_control_test_mode(
    text: str,
    source_name: str,
    output_root: Path,
    params: ControlTestParams,
    reperform_run_id: str | None = None,
) -> ControlRunResult:
    """Test an alert file and save the evidence as a run folder with its audit log.

    ``source_name`` is only the file name of the input, never a path.
    """
    started = datetime.now(UTC)
    tracery = None
    reperformed: dict[str, Any] | None = None
    if reperform_run_id:
        folder = output_root / reperform_run_id
        if not (folder / "audit_log.json").is_file():
            raise ControlTestError(f"No Tracery run {reperform_run_id} to re-perform against.")
        tracery = read_tracery_run(folder)
        source_audit = json.loads((folder / "audit_log.json").read_text(encoding="utf-8"))
        reperformed = {
            "run_id": reperform_run_id,
            "tool_version": source_audit.get("tool_version"),
            "config_hash": source_audit.get("rules", {}).get("config_hash"),
            "ofac_version": source_audit.get("sanctions_list", {}).get("version"),
            "addresses": len(tracery),
        }
    result = run_control_test(text, params, tracery)

    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    files = write_control_test(result, output_dir)
    finished = datetime.now(UTC)
    audit = {
        "run_id": run_id,
        "mode": "controls",
        "tool_version": __version__,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "input": {
            "file": source_name,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "alerts": len(result.alerts),
        },
        "results": result.summary,
        "parameters": params.to_dict(),
        "reperformed_against": reperformed or "not re-performed",
        "qa_sample": {
            "method": "zero-defect attribute sampling: "
            "n = ln(1 - confidence) / ln(1 - tolerable error)",
            "size_required": result.qa_sample_size,
            "size_drawn": len(result.qa_sample),
            "seed": result.qa_seed,
            "seed_source": "first 8 hex digits of the input SHA-256 (redrawable)",
        },
        "report_files": {name: path.name for name, path in files.items()},
    }
    (output_dir / "audit_log.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    summary = result.summary
    (output_dir / "run.log").write_text(
        f"{started.isoformat(timespec='seconds')} control test of {source_name}: "
        f"{summary['alerts_tested']} alerts, {summary['findings_by_severity']} findings, "
        f"re-performed against {reperform_run_id or 'nothing'}\n",
        encoding="utf-8",
    )
    return ControlRunResult(run_id, output_dir, result)
