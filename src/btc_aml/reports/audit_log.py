"""Audit trail of an analysis run.

The audit log answers the questions a supervisor or internal auditor would ask:
*when* was the analysis run, *on what input*, *with which rules and thresholds*,
*against which version of the sanctions list*, *from which data sources*, and
*what could not be evaluated*. Only file names and SHA-256 hashes of local inputs
are recorded, never full paths (they can contain personal information).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from btc_aml import __version__
from btc_aml.analysis import AddressAnalysis
from btc_aml.block_scan import BlockReport
from btc_aml.config import AppConfig
from btc_aml.data_sources.ecb import EcbRates
from btc_aml.data_sources.ofac import OfacList


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"file": path.name, "sha256": None}
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build_audit_log(
    *,
    run_id: str,
    mode: str,
    started_at: str,
    finished_at: str,
    config: AppConfig,
    ofac: OfacList,
    fx: EcbRates | None,
    label_count: int,
    input_info: dict[str, Any],
    analyses: list[AddressAnalysis],
    skipped: dict[str, str],
    requests_by_source: dict[str, int],
    report_files: dict[str, Path],
) -> dict[str, Any]:
    results = {
        "addresses_analysed": len(analyses),
        "addresses_skipped": skipped,
        "risk_bands": dict(Counter(a.score.band for a in analyses)),
        "alerts": sum(len(a.alerts) for a in analyses),
        "truncated_histories": [a.profile.address for a in analyses if a.profile.truncated],
        "rules_not_evaluated": {
            a.profile.address: a.rule_errors for a in analyses if a.rule_errors
        },
        "incomplete_exposure": {
            a.profile.address: a.exposure.notes
            for a in analyses
            if a.exposure is not None and not a.exposure.complete
        },
    }
    return _audit_document(
        run_id=run_id,
        mode=mode,
        started_at=started_at,
        finished_at=finished_at,
        config=config,
        ofac=ofac,
        fx=fx,
        label_count=label_count,
        input_info=input_info,
        results=results,
        requests_by_source=requests_by_source,
        report_files=report_files,
    )


def build_block_audit_log(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    config: AppConfig,
    ofac: OfacList,
    fx: EcbRates | None,
    label_count: int,
    input_info: dict[str, Any],
    reports: list[BlockReport],
    rules_applied: list[str],
    skipped: dict[str, str],
    requests_by_source: dict[str, int],
    report_files: dict[str, Path],
) -> dict[str, Any]:
    results = {
        "blocks_scanned": [report.block.height for report in reports],
        "blocks_skipped": skipped,
        "transactions_scanned": sum(len(report.txs) for report in reports),
        "alerts_by_rule": dict(Counter(f.rule_id for r in reports for f in r.findings)),
        "addresses_for_review": len({a for r in reports for a in r.addresses_for_review}),
        "rules_applied": rules_applied,
        "blocks_without_fee_statistics": [
            r.block.height for r in reports if r.block.median_fee_rate is None
        ],
        "blocks_without_eur_price": [r.block.height for r in reports if r.block.price is None],
    }
    return _audit_document(
        run_id=run_id,
        mode="blocks",
        started_at=started_at,
        finished_at=finished_at,
        config=config,
        ofac=ofac,
        fx=fx,
        label_count=label_count,
        input_info=input_info,
        results=results,
        requests_by_source=requests_by_source,
        report_files=report_files,
    )


def _audit_document(
    *,
    run_id: str,
    mode: str,
    started_at: str,
    finished_at: str,
    config: AppConfig,
    ofac: OfacList,
    fx: EcbRates | None,
    label_count: int,
    input_info: dict[str, Any],
    results: dict[str, Any],
    requests_by_source: dict[str, int],
    report_files: dict[str, Path],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "mode": mode,
        "tool_version": __version__,
        "started_at": started_at,
        "finished_at": finished_at,
        "input": input_info,
        "results": results,
        "rules": {
            "rules_version": config.rules_version,
            "config_hash": config.config_hash,
            "enabled": [rule_id for rule_id, rule in config.rules.items() if rule.enabled],
            "definitions": {rule_id: asdict(rule) for rule_id, rule in config.rules.items()},
        },
        "sanctions_list": {
            "name": "OFAC SDN",
            "version": ofac.version,
            "publish_date": ofac.publish_date,
            "downloaded_at": ofac.downloaded_at,
            "source_url": ofac.source_url,
            "sha256": ofac.sha256,
            "xbt_addresses": len(ofac.addresses),
        },
        "fx_rates": {
            "version": fx.version if fx else "not loaded (EUR gaps not filled)",
            "downloaded_at": fx.downloaded_at if fx else None,
            "source_url": fx.source_url if fx else config.fx_ecb_url,
        },
        "labels": {**file_fingerprint(config.labels_path), "count": label_count},
        "parameters": {
            "data_sources": asdict(config.data_sources),
            "exposure": asdict(config.exposure),
            "coinjoin": asdict(config.coinjoin),
            "scoring": asdict(config.scoring),
            "address_ttl_hours": config.cache.address_ttl_hours,
            "max_blocks": config.max_blocks,
        },
        "data_sources_used": requests_by_source,
        "report_files": {name: path.name for name, path in report_files.items()},
    }


def write_audit_log(audit: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
