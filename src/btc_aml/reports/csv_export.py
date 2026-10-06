"""CSV reports: address_scores.csv, alerts.csv, transactions.csv.

Amounts are written as plain decimals (BTC with 8 decimals, EUR with 2) so the files
open cleanly in any spreadsheet. An empty EUR cell means "price unavailable".
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from btc_aml.analysis import AddressAnalysis
from btc_aml.config import CoinJoinConfig
from btc_aml.heuristics import detect_coinjoin
from btc_aml.model import sats_to_btc

ADDRESS_SCORES_COLUMNS = (
    "address",
    "risk_score",
    "risk_band",
    "rules_triggered",
    "total_received_btc",
    "total_sent_btc",
    "tx_count",
    "first_seen",
    "last_seen",
    "analysis_date",
    "score_explanation",
    "history_truncated",
    "rules_not_evaluated",
    "cluster_size",
    "exposure_addresses_expanded",
    "exposure_complete",
    "high_degree_counterparties",
    "exposure_notes",
)
ALERTS_COLUMNS = (
    "alert_id",
    "address",
    "rule_id",
    "rule_name",
    "severity",
    "score_contribution",
    "evidence_txids",
    "amount_btc",
    "amount_eur",
    "hop_distance",
    "explanation",
    "regulatory_reference",
)
TRANSACTIONS_COLUMNS = (
    "address",
    "txid",
    "block_height",
    "block_time",
    "direction",
    "amount_btc",
    "amount_eur",
    "btc_eur_price",
    "btc_eur_price_date",
    "btc_eur_price_source",
    "fee_sats",
    "input_count",
    "output_count",
    "is_coinjoin",
)


def write_reports(
    analyses: list[AddressAnalysis],
    output_dir: Path,
    run_id: str,
    analysis_date: str,
    coinjoin: CoinJoinConfig,
) -> dict[str, Path]:
    """Write the three CSV files and return their paths by name."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "address_scores": output_dir / "address_scores.csv",
        "alerts": output_dir / "alerts.csv",
        "transactions": output_dir / "transactions.csv",
    }
    _write(paths["address_scores"], ADDRESS_SCORES_COLUMNS, _score_rows(analyses, analysis_date))
    _write(paths["alerts"], ALERTS_COLUMNS, _alert_rows(analyses, run_id))
    _write(paths["transactions"], TRANSACTIONS_COLUMNS, _transaction_rows(analyses, coinjoin))
    return paths


def _score_rows(analyses: list[AddressAnalysis], analysis_date: str) -> Iterable[tuple]:
    for analysis in analyses:
        prof, score = analysis.profile, analysis.score
        yield (
            prof.address,
            score.score,
            score.band,
            ";".join(score.rules_triggered),
            _btc(prof.total_received_sats),
            _btc(prof.total_sent_sats),
            prof.tx_count_total,
            _iso(prof.first_seen),
            _iso(prof.last_seen),
            analysis_date,
            score.explanation(),
            prof.truncated,
            ";".join(sorted(analysis.rule_errors)),
            len(analysis.cluster),
            *_exposure_columns(analysis),
        )


def _exposure_columns(analysis: AddressAnalysis) -> tuple:
    exposure = analysis.exposure
    if exposure is None:
        return ("", "", "", "not computed")
    return (
        exposure.expanded,
        exposure.complete,
        ";".join(sorted(exposure.high_degree_nodes)),
        "; ".join(exposure.notes),
    )


def _alert_rows(analyses: list[AddressAnalysis], run_id: str) -> Iterable[tuple]:
    counter = 0
    for analysis in analyses:
        for alert in analysis.alerts:
            counter += 1
            yield (
                f"{run_id}-{counter:05d}",
                alert.address,
                alert.rule_id,
                alert.rule_name,
                alert.severity,
                f"{analysis.score.contribution_of(alert):.1f}",
                ";".join(alert.evidence_txids),
                _btc(alert.amount_sats),
                _eur(alert.amount_eur),
                alert.hop_distance,
                alert.explanation,
                alert.regulatory_reference,
            )


def _transaction_rows(analyses: list[AddressAnalysis], coinjoin: CoinJoinConfig) -> Iterable[tuple]:
    for analysis in analyses:
        address = analysis.profile.address
        for tx in analysis.profile.txs:
            net = tx.net_flow(address)
            yield (
                address,
                tx.txid,
                tx.block_height,
                _iso(tx.block_time),
                "in" if net > 0 else "out" if net < 0 else "self",
                _btc(abs(net)),
                _eur(tx.to_eur(abs(net))),
                "" if tx.eur_price is None else f"{tx.eur_price:.2f}",
                tx.eur_price_date or "",
                tx.eur_price_source or "",
                tx.fee_sats,
                len(tx.inputs),
                len(tx.outputs),
                detect_coinjoin(tx, coinjoin) is not None,
            )


def _write(path: Path, columns: tuple[str, ...], rows: Iterable[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


def _btc(sats: int) -> str:
    return f"{sats_to_btc(sats):.8f}"


def _eur(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _iso(timestamp: int | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
