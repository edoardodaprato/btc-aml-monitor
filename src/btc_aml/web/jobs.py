"""Long-running tasks of the control panel (analyses, list updates), one at a time.

An analysis can take minutes on public APIs, so it runs in a background thread while
the browser polls its progress. Only one task runs at a time: the public APIs are
rate-limited anyway, and two runs would compete for the same budget.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from btc_aml.config import AppConfig, ConfigError
from btc_aml.data_sources.ecb import FxError, update_ecb_rates
from btc_aml.data_sources.http import DataSourceError
from btc_aml.data_sources.labels import LabelError, read_labels
from btc_aml.data_sources.ofac import OfacError, load_ofac_list, update_ofac_list
from btc_aml.rules.registry import build_rules
from btc_aml.runner import BlockRangeError, run_address_mode, run_block_mode
from btc_aml.services import Services

EXPECTED_ERRORS = (
    BlockRangeError,
    ConfigError,
    DataSourceError,
    FxError,
    LabelError,
    OfacError,
    OSError,
)


@dataclass
class Job:
    description: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "running"  # running | done | failed
    log: list[str] = field(default_factory=list)
    run_id: str | None = None  # set when the task produced a report folder
    error: str | None = None


class JobRunner:
    """Runs one task at a time in a background thread."""

    def __init__(self, config: AppConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport
        self._lock = threading.Lock()
        self.current: Job | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.status == "running"

    def analyse_addresses(self, addresses_text: str) -> Job:
        """Save the pasted addresses to a file and run address mode on it."""
        inputs = self._config.output_dir / "ui_inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        path = inputs / f"addresses_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.txt"
        path.write_text(addresses_text.strip() + "\n", encoding="utf-8")
        return self._start("Address analysis", lambda job: self._run_addresses(job, path))

    def scan_blocks(self, start: int, end: int) -> Job:
        label = f"Block scan {start}" if start == end else f"Block scan {start}-{end}"
        return self._start(label, lambda job: self._run_blocks(job, start, end))

    def update_ofac(self) -> Job:
        return self._start("OFAC list update", self._run_update_ofac)

    def update_fx(self) -> Job:
        return self._start("ECB rates update", self._run_update_fx)

    # --- task bodies ------------------------------------------------------------------

    def _run_addresses(self, job: Job, path: Path) -> None:
        config = self._config
        ofac = load_ofac_list(config.ofac_local_path)
        labels = read_labels(config.labels_path)
        build_rules(config)
        with Services.from_config(config, self._transport) as services:
            result = run_address_mode(path, config, services, ofac, labels, progress=job.log.append)
        job.run_id = result.run_id
        job.log.append(f"{len(result.analyses)} analysed, {len(result.skipped)} skipped")

    def _run_blocks(self, job: Job, start: int, end: int) -> None:
        config = self._config
        ofac = load_ofac_list(config.ofac_local_path)
        labels = read_labels(config.labels_path)
        with Services.from_config(config, self._transport) as services:
            result = run_block_mode(
                start, end, config, services, ofac, labels, progress=job.log.append
            )
        job.run_id = result.run_id
        alerts = sum(len(report.findings) for report in result.reports)
        job.log.append(f"{len(result.reports)} block(s) scanned, {alerts} alerts")

    def _run_update_ofac(self, job: Job) -> None:
        job.log.append("Downloading the OFAC SDN list (about 30 MB)...")
        ofac = update_ofac_list(self._config.ofac_sdn_url, self._config.ofac_local_path)
        job.log.append(
            f"List published {ofac.publish_date}: {len(ofac.addresses)} Bitcoin addresses"
        )

    def _run_update_fx(self, job: Job) -> None:
        job.log.append("Downloading ECB EUR/USD reference rates...")
        rates = update_ecb_rates(self._config.fx_ecb_url, self._config.fx_local_path)
        job.log.append(f"{len(rates.usd_per_eur)} days of rates loaded")

    # --- plumbing ---------------------------------------------------------------------

    def _start(self, description: str, body: Callable[[Job], None]) -> Job:
        with self._lock:
            if self.busy:
                raise RuntimeError("Another task is still running. Wait for it to finish.")
            job = Job(description)
            self.current = job
        threading.Thread(target=self._execute, args=(job, body), daemon=True).start()
        return job

    @staticmethod
    def _execute(job: Job, body: Callable[[Job], None]) -> None:
        try:
            body(job)
        except EXPECTED_ERRORS as exc:
            job.error = str(exc)
            job.status = "failed"
        except Exception as exc:  # noqa: BLE001 - a crash must be shown, not lost in a thread
            job.error = f"Unexpected error ({type(exc).__name__}): {exc}"
            job.status = "failed"
        else:
            job.status = "done"
