"""Tests for the monitoring control test (offline, on the synthetic demo alert file)."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from btc_aml.control_testing import (
    ControlTestError,
    ControlTestParams,
    qa_sample_size,
    read_firm_alerts,
    read_tracery_run,
    run_control_test,
    run_control_test_mode,
)
from tests.conftest import PROJECT_ROOT

DEMO = PROJECT_ROOT / "examples" / "control_test" / "firm_alerts_demo.csv"
EXAMPLE_RUN = "20261009T223246Z"
OFAC_ADDRESS = "12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL"
OFAC_ADDRESS_2 = "1H939dom7i4WDLCKyGbXUp3fs9CSTNRzgL"
PARAMS = ControlTestParams(as_of=date(2026, 10, 15))
HEADER = "alert_id,address,rule,created_at,status,disposition,closed_at,reviewer,rationale\n"
BIP173 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


@pytest.fixture
def tracery():
    return read_tracery_run(PROJECT_ROOT / "examples" / "address_mode")


def findings(result, name):
    return [f for f in result.findings if f["finding"] == name]


def test_bad_rows_are_reported_and_left_out():
    alerts, issues = read_firm_alerts(DEMO.read_text())
    assert len(alerts) == 33
    problems = {(i["alert_id"], i["field"]) for i in issues if i["severity"] == "high"}
    assert problems == {("A-0002", "alert_id"), ("A-0034", "created_at"), ("A-0035", "status")}


def test_missing_columns_are_refused():
    with pytest.raises(ControlTestError, match="created_at"):
        read_firm_alerts("alert_id,address,rule,status\nA,x,y,open\n")


def test_reperformance_finds_sanctions_gaps(tracery):
    result = run_control_test(DEMO.read_text(), PARAMS, tracery)
    outcome = {row["address"]: row["result"] for row in result.reconciliation}
    assert outcome[OFAC_ADDRESS] == "sanctions gap"  # closed as false positive
    assert outcome[OFAC_ADDRESS_2] == "sanctions gap"  # never alerted
    assert outcome[BIP173] == "outside re-performed population"
    closed = findings(result, "Sanctioned address closed without escalation")
    assert [f["alert_id"] for f in closed] == ["A-0001"]
    assert result.findings[0]["severity"] == "critical"  # most severe first


def test_closure_quality_findings():
    result = run_control_test(DEMO.read_text(), PARAMS)
    assert [
        f["alert_id"] for f in findings(result, "Closed too fast to have been investigated")
    ] == ["A-0001"]
    assert len(findings(result, "Copy-pasted rationale")) == 5
    assert [f["alert_id"] for f in findings(result, "No rationale recorded")] == ["A-0030"]
    assert {f["alert_id"] for f in findings(result, "Open beyond the review deadline")} == {
        "A-0031",
        "A-0033",
    }
    assert findings(result, "Inconsistent outcomes for the same address")
    never = findings(result, "Rule never leads to escalation")
    assert [f["rule"] for f in never] == ["Large transfer"]


def test_reviewer_volume_outlier():
    rows = "".join(
        f"A{i},{BIP173},Dust,2026-09-01T08:00:00Z,closed,false_positive,"
        f"2026-09-01T12:00:00Z,R9,Known faucet payouts reviewed against policy {i}\n"
        for i in range(4)
    )
    params = ControlTestParams(as_of=date(2026, 10, 1), max_closures_per_reviewer_day=3)
    result = run_control_test(HEADER + rows, params)
    assert len(findings(result, "Reviewer closed an unusual volume that day")) == 4


def test_rule_metrics_and_backlog():
    result = run_control_test(DEMO.read_text(), PARAMS)
    metrics = {row["rule"]: row for row in result.rule_metrics}
    assert metrics["Fan-in"]["escalated"] == 1
    assert metrics["Fan-in"]["escalation_rate"] == "16.7%"
    backlog = {row["age"]: row["open_alerts"] for row in result.backlog}
    assert backlog == {"0-7 days": 0, "8-30 days": 1, "31-90 days": 1, "over 90 days": 1}


def test_qa_sample_is_sized_and_reproducible():
    assert qa_sample_size(0.95, 0.05) == 59
    first = run_control_test(DEMO.read_text(), PARAMS)
    second = run_control_test(DEMO.read_text(), PARAMS)
    assert [r["alert_id"] for r in first.qa_sample] == [r["alert_id"] for r in second.qa_sample]
    assert len(first.qa_sample) == 30  # all closed alerts: fewer than the 59 required


def test_run_folder_and_audit_log(tmp_path: Path):
    shutil.copytree(PROJECT_ROOT / "examples" / "address_mode", tmp_path / EXAMPLE_RUN)
    run = run_control_test_mode(DEMO.read_text(), DEMO.name, tmp_path, PARAMS, EXAMPLE_RUN)
    audit = json.loads((run.output_dir / "audit_log.json").read_text())
    assert audit["mode"] == "controls"
    assert audit["input"]["file"] == "firm_alerts_demo.csv"
    assert audit["reperformed_against"]["run_id"] == EXAMPLE_RUN
    assert audit["parameters"]["sla_days"] == 30
    assert audit["qa_sample"]["size_required"] == 59
    assert str(Path.home()) not in json.dumps(audit)
    with (run.output_dir / "findings.csv").open(newline="") as handle:
        assert any(row["severity"] == "critical" for row in csv.DictReader(handle))


def test_unknown_reperformance_run_is_refused(tmp_path: Path):
    with pytest.raises(ControlTestError, match="No Tracery run"):
        run_control_test_mode(DEMO.read_text(), DEMO.name, tmp_path, PARAMS, "20990101T000000Z")
