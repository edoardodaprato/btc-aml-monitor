"""Run the two analysis modes and write their reports.

* Address mode analyses every address listed in a text file.
* Block-scan mode checks every transaction of a range of blocks.

Each run gets its own folder ``<output>/<run_id>/`` with the CSV reports, the audit
log (``audit_log.json``) and the technical log (``run.log``). An item that fails
(invalid address, API outage on one block) is skipped and listed in the audit log;
it never stops the rest of the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from btc_aml.analysis import AddressAnalysis, analyze_address
from btc_aml.block_scan import BlockInfo, BlockReport, BlockScanner
from btc_aml.config import AppConfig
from btc_aml.data_sources.http import DataSourceError
from btc_aml.data_sources.labels import Label, is_valid_btc_address
from btc_aml.data_sources.ofac import OfacList
from btc_aml.reports.audit_log import (
    build_audit_log,
    build_block_audit_log,
    file_fingerprint,
    write_audit_log,
)
from btc_aml.reports.csv_export import write_block_reports, write_reports
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


@dataclass
class BlockRunResult:
    run_id: str
    output_dir: Path
    reports: list[BlockReport]
    skipped: dict[str, str]


class BlockRangeError(ValueError):
    """The requested block range is empty, too long or beyond the chain tip."""


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


def run_block_mode(
    start_height: int,
    end_height: int,
    config: AppConfig,
    services: Services,
    ofac: OfacList,
    labels: list[Label],
    progress: Callable[[str], None] = lambda message: None,
) -> BlockRunResult:
    """Scan blocks ``start_height``..``end_height`` (inclusive)."""
    count = end_height - start_height + 1
    if start_height < 0 or count < 1:
        raise BlockRangeError(f"Invalid block range {start_height}-{end_height}")
    if count > config.max_blocks:
        raise BlockRangeError(
            f"{count} blocks requested, the limit is {config.max_blocks} "
            "(block_scan.max_blocks in settings.yaml)"
        )
    tip = services.esplora.get_tip_height()
    if end_height > tip:
        raise BlockRangeError(f"Block {end_height} does not exist yet (chain tip is {tip})")

    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = config.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_handler = _attach_run_log(output_dir / "run.log")
    try:
        scanner = BlockScanner(config, Screener(ofac, labels))
        logger.info("Run %s: blocks %d-%d", run_id, start_height, end_height)
        reports: list[BlockReport] = []
        skipped: dict[str, str] = {}
        for height in range(start_height, end_height + 1):
            try:
                block = _load_block(height, services)
                progress(f"[block {height}] {block.tx_count} transactions")
                raw_txs = services.esplora.get_block_txs(block.block_hash, block.tx_count)
            except DataSourceError as exc:
                logger.error("Block %d skipped: %s", height, exc)
                skipped[str(height)] = str(exc)
                continue
            report = scanner.scan(block, raw_txs)
            logger.info("Block %d: %d alerts", height, len(report.findings))
            reports.append(report)

        finished = datetime.now(UTC)
        files = write_block_reports(reports, output_dir, run_id)
        audit = build_block_audit_log(
            run_id=run_id,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            config=config,
            ofac=ofac,
            fx=services.fx,
            label_count=len(labels),
            input_info={"start_height": start_height, "end_height": end_height, "tip": tip},
            reports=reports,
            rules_applied=scanner.enabled_rules,
            skipped=skipped,
            requests_by_source=dict(services.http.requests_by_source),
            report_files=files,
        )
        write_audit_log(audit, output_dir / "audit_log.json")
        logger.info("Run %s finished: %d blocks, %d skipped", run_id, len(reports), len(skipped))
        return BlockRunResult(run_id, output_dir, reports, skipped)
    finally:
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()


def _load_block(height: int, services: Services) -> BlockInfo:
    esplora = services.esplora
    block_hash = esplora.get_block_hash(height)
    block = esplora.get_block(block_hash)
    return BlockInfo(
        height=block["height"],
        block_hash=block_hash,
        timestamp=block["timestamp"],
        tx_count=block["tx_count"],
        median_fee_rate=esplora.get_block_median_fee_rate(block_hash),
        price=services.prices.eur_quote(block["timestamp"]),
    )


def _attach_run_log(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    return handler
