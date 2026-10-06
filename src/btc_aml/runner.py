"""Address mode: analyse every address listed in a text file and write the reports.

Each run gets its own folder ``<output>/<run_id>/`` with the three CSV reports, the
audit log (``audit_log.json``) and the technical log (``run.log``). An address that
fails (invalid format, API outage) is skipped and listed in the audit log; it never
stops the rest of the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from btc_aml.analysis import AddressAnalysis, analyze_address
from btc_aml.config import AppConfig
from btc_aml.data_sources.http import DataSourceError
from btc_aml.data_sources.labels import Label, is_valid_btc_address
from btc_aml.data_sources.ofac import OfacList
from btc_aml.reports.audit_log import build_audit_log, file_fingerprint, write_audit_log
from btc_aml.reports.csv_export import write_reports
from btc_aml.rules.registry import build_rules
from btc_aml.screening import Screener
from btc_aml.services import Services

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: str
    output_dir: Path
    analyses: list[AddressAnalysis]
    skipped: dict[str, str]


def read_address_file(path: Path) -> tuple[list[str], dict[str, str]]:
    """Return (valid addresses in order, without duplicates) and {invalid line: reason}.

    Blank lines and lines starting with '#' are ignored, so the file can be commented.
    """
    addresses: list[str] = []
    invalid: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if not is_valid_btc_address(text):
            invalid[text] = f"line {number}: not a valid Bitcoin address"
        elif text not in addresses:
            addresses.append(text)
    return addresses, invalid


def run_address_mode(
    input_path: Path,
    config: AppConfig,
    services: Services,
    ofac: OfacList,
    labels: list[Label],
    progress: Callable[[str], None] = lambda message: None,
) -> RunResult:
    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = config.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_handler = _attach_run_log(output_dir / "run.log")
    try:
        addresses, skipped = read_address_file(input_path)
        logger.info("Run %s: %d addresses, %d invalid lines", run_id, len(addresses), len(skipped))
        screener = Screener(ofac, labels)
        rules = build_rules(config)

        analyses = []
        for index, address in enumerate(addresses, start=1):
            progress(f"[{index}/{len(addresses)}] {address}")
            try:
                analyses.append(analyze_address(address, services, config, screener, rules))
            except DataSourceError as exc:
                logger.error("Address %s skipped: %s", address, exc)
                skipped[address] = str(exc)

        finished = datetime.now(UTC)
        reports = write_reports(
            analyses, output_dir, run_id, finished.date().isoformat(), config.coinjoin
        )
        audit = build_audit_log(
            run_id=run_id,
            mode="addresses",
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            config=config,
            ofac=ofac,
            fx=services.fx,
            label_count=len(labels),
            input_info={**file_fingerprint(input_path), "addresses": len(addresses)},
            analyses=analyses,
            skipped=skipped,
            requests_by_source=dict(services.http.requests_by_source),
            report_files=reports,
        )
        write_audit_log(audit, output_dir / "audit_log.json")
        logger.info("Run %s finished: %d analysed, %d skipped", run_id, len(analyses), len(skipped))
        return RunResult(run_id, output_dir, analyses, skipped)
    finally:
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()


def _attach_run_log(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    return handler
