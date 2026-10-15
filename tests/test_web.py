"""Tests for the local control panel: pages, background runs and manual review (offline)."""

from __future__ import annotations

import csv
import dataclasses
import json
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from btc_aml.config import AppConfig
from btc_aml.data_sources.ofac import update_ofac_list
from btc_aml.web.server import create_server
from tests.conftest import FIXTURES, PROJECT_ROOT
from tests.test_block_scan import FakeChainApi

EXAMPLE_RUN = "20261009T223246Z"  # examples/address_mode


@pytest.fixture
def panel_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
    return dataclasses.replace(
        app_config,
        output_dir=tmp_path / "output",
        ofac_local_path=tmp_path / "ofac.json",
        labels_path=tmp_path / "labels.csv",
    )


@pytest.fixture
def panel(panel_config: AppConfig) -> Iterator[str]:
    """Base URL of a running control panel whose network is a fake two-block chain."""
    server = create_server(panel_config, 0, transport=httpx.MockTransport(FakeChainApi().handler))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post(url: str, form: dict[str, str]) -> tuple[int, str]:
    data = urllib.parse.urlencode(form).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data)) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def install_example_run(config: AppConfig) -> Path:
    target = config.output_dir / EXAMPLE_RUN
    shutil.copytree(PROJECT_ROOT / "examples" / "address_mode", target)
    return target


def install_ofac(config: AppConfig) -> None:
    xml = (FIXTURES / "ofac_sdn_sample.xml").read_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=xml))
    update_ofac_list("https://ofac.test/SDN.XML", config.ofac_local_path, transport)


def test_home_page_warns_when_the_ofac_list_is_missing(panel: str) -> None:
    status, html = get(panel + "/")
    assert status == 200
    assert "Control panel" in html
    assert "not downloaded yet" in html
    assert "Latest block known: 101" in html


def test_saved_run_is_shown_with_evidence_links(panel: str, panel_config: AppConfig) -> None:
    install_example_run(panel_config)

    status, html = get(f"{panel}/")
    assert EXAMPLE_RUN in html

    status, html = get(f"{panel}/runs/{EXAMPLE_RUN}")
    assert status == 200
    assert "12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL" in html
    assert "R01_OFAC_DIRECT" in html
    assert "https://mempool.space/tx/" in html
    assert "Audit trail" in html
    assert "Scan block" in html  # one-click scan of the block of each transaction


def test_review_decision_is_saved_and_exported(panel: str, panel_config: AppConfig) -> None:
    folder = install_example_run(panel_config)
    alert_id = f"{EXAMPLE_RUN}-00001"

    status, html = post(
        f"{panel}/runs/{EXAMPLE_RUN}/review",
        {
            "alert_id": alert_id,
            "decision": "escalate",
            "note": "Address on OFAC SDN list",
            "reviewer": "ED",
        },
    )

    assert status == 200  # redirected back to the run page
    assert "1 reviewed" in html
    saved = json.loads((folder / "review.json").read_text())
    assert saved[alert_id]["decision"] == "escalate"
    with (folder / "review.csv").open(newline="") as handle:
        rows = {row["alert_id"]: row for row in csv.DictReader(handle)}
    assert rows[alert_id]["note"] == "Address on OFAC SDN list"
    assert rows[alert_id]["reviewer"] == "ED"
    # The automated report is never modified by the review.
    assert (folder / "alerts.csv").read_bytes() == (
        PROJECT_ROOT / "examples" / "address_mode" / "alerts.csv"
    ).read_bytes()


def test_data_is_escaped(panel: str, panel_config: AppConfig) -> None:
    folder = install_example_run(panel_config)
    alerts = (folder / "alerts.csv").read_text()
    (folder / "alerts.csv").write_text(
        alerts.replace("The address itself is sanctioned", "<script>alert(1)</script>", 1)
    )
    _, html = get(f"{panel}/runs/{EXAMPLE_RUN}")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    "path",
    [
        "/runs/..%2F..%2Fetc",
        f"/runs/{EXAMPLE_RUN}/files/..%2Faudit_log.json",
        f"/runs/{EXAMPLE_RUN}/files/settings.yaml",
        "/runs/20991231T000000Z",
    ],
)
def test_unknown_runs_and_files_are_refused(panel: str, panel_config: AppConfig, path: str) -> None:
    install_example_run(panel_config)
    status, _ = get(panel + path)
    assert status == 404


def test_report_file_download(panel: str, panel_config: AppConfig) -> None:
    install_example_run(panel_config)
    status, body = get(f"{panel}/runs/{EXAMPLE_RUN}/files/address_scores.csv")
    assert status == 200
    assert body.startswith("address,risk_score")


def test_block_scan_runs_in_background_and_opens_results(
    panel: str, panel_config: AppConfig
) -> None:
    install_ofac(panel_config)

    status, html = post(f"{panel}/run/blocks", {"start": "100", "end": "101"})
    assert status == 200 and "Block scan 100-101" in html

    for _ in range(100):
        _, html = get(f"{panel}/job")
        if "running" not in html.lower() or "done" in html:
            break
        time.sleep(0.05)
    assert "done" in html
    run_id = html.split('href="/runs/')[1].split('"')[0]

    status, html = get(f"{panel}/runs/{run_id}")
    assert status == 200
    assert "Blocks" in html and "101" in html


def test_failed_task_shows_the_reason(panel: str) -> None:
    post(f"{panel}/run/blocks", {"start": "100"})  # no OFAC list installed
    for _ in range(100):
        _, html = get(f"{panel}/job")
        if "failed" in html:
            break
        time.sleep(0.05)
    assert "OFAC list not found" in html


def test_invalid_txid_is_rejected(panel: str) -> None:
    status, html = get(f"{panel}/tx?txid=not-a-txid")
    assert status == 200
    assert "Not a valid transaction id" in html


# --- labels -------------------------------------------------------------------------------

BIP173_EXAMPLE = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"  # example from BIP-173, not real


def test_add_one_label(panel: str, panel_config: AppConfig) -> None:
    status, html = post(
        f"{panel}/labels/add",
        {
            "address": BIP173_EXAMPLE,
            "category": "scam",
            "source": "https://example.org/court-filing",
            "date_added": "2026-10-15",
        },
    )
    assert status == 200
    assert "1 label(s) added" in html
    assert BIP173_EXAMPLE in html
    assert BIP173_EXAMPLE in panel_config.labels_path.read_text()


def test_invalid_label_is_rejected_and_nothing_is_written(
    panel: str, panel_config: AppConfig
) -> None:
    _, html = post(
        f"{panel}/labels/add",
        {"address": BIP173_EXAMPLE, "category": "scam", "source": "", "date_added": "2026-10-15"},
    )
    assert "Nothing was imported" in html
    assert "missing source" in html
    assert "ui_inputs" not in html  # no internal file names in messages
    assert not panel_config.labels_path.exists()


def test_csv_import_skips_duplicates(panel: str) -> None:
    csv_text = (
        "address,category,source,date_added\n"
        f"{BIP173_EXAMPLE},mixer,https://example.org/a,2026-10-15\n"
    )
    post(f"{panel}/labels/import", {"csv": csv_text})
    _, html = post(f"{panel}/labels/import", {"csv": csv_text})
    assert "0 label(s) added, 1 already present" in html


def test_guide_page_shows_the_full_guide(panel: str) -> None:
    status, html = get(f"{panel}/guide")
    assert status == 200
    assert "Tracery user guide" in html
    assert "The rules in plain words" in html
    status, html = get(f"{panel}/help")  # former address
    assert status == 200 and "Tracery user guide" in html
