"""Command-line interface (entry point: ``btc-aml``)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from btc_aml import __version__
from btc_aml.analysis import AddressAnalysis, analyze_address
from btc_aml.config import AppConfig, ConfigError, load_config
from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import DataSourceError
from btc_aml.data_sources.labels import LabelError, import_labels, read_labels
from btc_aml.data_sources.ofac import OfacError, load_ofac_list, update_ofac_list
from btc_aml.data_sources.price import PriceQuote
from btc_aml.model import sats_to_btc
from btc_aml.rules.base import fmt_time
from btc_aml.rules.registry import build_rules
from btc_aml.runner import run_address_mode
from btc_aml.screening import Screener
from btc_aml.services import Services

SATS_PER_BTC = 100_000_000

app = typer.Typer(
    help="Retrospective Bitcoin transaction monitoring for AML compliance.",
    no_args_is_help=True,
    add_completion=False,
)

ConfigDirOption = Annotated[
    Path, typer.Option("--config-dir", help="Folder containing settings.yaml and rules.yaml.")
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"btc-aml-monitor {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Retrospective Bitcoin transaction monitoring for AML compliance."""


@app.command("show-config")
def show_config(config_dir: ConfigDirOption = Path("config")) -> None:
    """Validate the configuration and print a summary of rules, weights and limits."""
    config = _load_config_or_exit(config_dir)
    exposure = config.exposure
    typer.echo(f"Configuration OK  (hash {config.config_hash}, rules v{config.rules_version})")
    typer.echo(f"Primary API:   {config.data_sources.primary_url}")
    typer.echo(f"Fallback API:  {config.data_sources.fallback_url}")
    typer.echo(
        f"Exposure:      {exposure.max_hops} hops, decay {list(exposure.hop_decay)}, "
        f"high-degree >= {exposure.high_degree_threshold} tx"
    )
    bands = ", ".join(f"{b.name} {b.min}-{b.max}" for b in config.scoring.bands)
    typer.echo(f"Risk bands:    {bands}")
    typer.echo("")
    typer.echo(f"{'RULE':<34} {'ON':<4} {'WEIGHT':>6}  SEVERITY")
    for rule in config.rules.values():
        status = "yes" if rule.enabled else "no"
        typer.echo(f"{rule.rule_id:<34} {status:<4} {rule.weight:>6.0f}  {rule.severity}")


@app.command("fetch-tx")
def fetch_tx(txid: str, config_dir: ConfigDirOption = Path("config")) -> None:
    """Download (or read from cache) one transaction and print its key fields."""
    config = _load_config_or_exit(config_dir)
    with Services.from_config(config) as services:
        try:
            tx = services.esplora.get_tx(txid)
        except DataSourceError as exc:
            _fail(str(exc))
        status = tx["status"]
        quote = services.prices.eur_quote(status["block_time"]) if status["confirmed"] else None
        _print_tx(tx, quote)
        requests = dict(services.http.requests_by_source) or "none (served from cache)"
        typer.echo(f"\nAPI requests:  {requests}")


@app.command("cache-stats")
def cache_stats(config_dir: ConfigDirOption = Path("config")) -> None:
    """Show how many items are stored in the local cache."""
    config = _load_config_or_exit(config_dir)
    with Cache(config.cache.path) as cache:
        stats = cache.stats()
    typer.echo(f"Cache file: {config.cache.path}")
    for namespace, count in stats.items():
        typer.echo(f"  {namespace:<12} {count:>8}")
    if not stats:
        typer.echo("  (empty)")


@app.command("update-ofac")
def update_ofac(config_dir: ConfigDirOption = Path("config")) -> None:
    """Download the official OFAC SDN list and extract its Bitcoin (XBT) addresses."""
    config = _load_config_or_exit(config_dir)
    typer.echo(f"Downloading {config.ofac_sdn_url} ...")
    try:
        ofac = update_ofac_list(config.ofac_sdn_url, config.ofac_local_path)
    except OfacError as exc:
        _fail(str(exc))
    typer.echo(f"OFAC SDN list published:  {ofac.publish_date} ({ofac.record_count} records)")
    entities = {entry.entity_uid for entries in ofac.addresses.values() for entry in entries}
    typer.echo(f"Bitcoin addresses (XBT):  {len(ofac.addresses)} ({len(entities)} entities)")
    typer.echo(f"List version (audit):     {ofac.version}")
    typer.echo(f"Saved to:                 {config.ofac_local_path}")


@app.command("import-labels")
def import_labels_command(
    source: Annotated[Path, typer.Argument(help="CSV with address,category,source,date_added")],
    config_dir: ConfigDirOption = Path("config"),
) -> None:
    """Validate a labels CSV and merge it into the local labels file."""
    config = _load_config_or_exit(config_dir)
    try:
        result = import_labels(source, config.labels_path)
    except LabelError as exc:
        _fail(f"Import rejected, nothing changed. {exc}")
    typer.echo(
        f"Imported {result.added} labels ({result.duplicates} duplicates skipped). "
        f"{config.labels_path} now holds {result.total} labels."
    )


@app.command("screen")
def screen(
    addresses: Annotated[list[str], typer.Argument(help="One or more Bitcoin addresses.")],
    config_dir: ConfigDirOption = Path("config"),
) -> None:
    """Check addresses against the OFAC SDN list and the local labels (no network)."""
    config = _load_config_or_exit(config_dir)
    screener = _load_screener_or_exit(config)
    typer.echo(f"OFAC list version: {screener.ofac_version}\n")
    for address in addresses:
        hits = screener.screen(address)
        if not hits:
            typer.echo(f"{address}  no match")
        for hit in hits:
            typer.secho(
                f"{address}  MATCH [{hit.list_name}] {hit.category}: {hit.detail}",
                fg=typer.colors.RED if hit.category == "sanctioned" else typer.colors.YELLOW,
            )


@app.command("analyze")
def analyze(address: str, config_dir: ConfigDirOption = Path("config")) -> None:
    """Download an address history, run every enabled rule and list the alerts."""
    config = _load_config_or_exit(config_dir)
    screener = _load_screener_or_exit(config)
    try:
        rules = build_rules(config)
    except ConfigError as exc:
        _fail(f"Configuration error: {exc}")
    with Services.from_config(config) as services:
        try:
            analysis = analyze_address(address, services, config, screener, rules)
        except DataSourceError as exc:
            _fail(str(exc))
        _print_analysis(analysis)
        typer.echo(f"\nAPI requests: {dict(services.http.requests_by_source) or 'none (cache)'}")


@app.command("scan-addresses")
def scan_addresses(
    input_file: Annotated[
        Path, typer.Argument(help="Text file with one Bitcoin address per line.")
    ],
    config_dir: ConfigDirOption = Path("config"),
) -> None:
    """Analyse every address in a file and write CSV reports and the audit log."""
    config = _load_config_or_exit(config_dir)
    if not input_file.is_file():
        _fail(f"File not found: {input_file}")
    try:
        ofac = load_ofac_list(config.ofac_local_path)
        labels = read_labels(config.labels_path)
        build_rules(config)  # fail fast on configuration errors, before any download
    except (OfacError, LabelError, ConfigError) as exc:
        _fail(str(exc))

    with Services.from_config(config) as services:
        result = run_address_mode(input_file, config, services, ofac, labels, progress=typer.echo)

    typer.echo(
        f"\nRun {result.run_id}: {len(result.analyses)} analysed, {len(result.skipped)} skipped"
    )
    for analysis in sorted(result.analyses, key=lambda a: -a.score.score):
        score = analysis.score
        typer.echo(f"  {score.score:>3}  {score.band:<7} {analysis.profile.address}")
    for item, reason in result.skipped.items():
        typer.secho(f"  skipped {item}: {reason}", fg=typer.colors.YELLOW)
    typer.echo(f"\nReports and audit log: {result.output_dir}")


def _print_analysis(analysis: AddressAnalysis) -> None:
    prof = analysis.profile
    typer.echo(f"Address        {prof.address}")
    scope = f"{len(prof.txs)} of {prof.tx_count_total}" + (" (TRUNCATED)" if prof.truncated else "")
    typer.echo(f"Transactions   {scope}")
    typer.echo(
        f"Received/sent  {sats_to_btc(prof.total_received_sats):.8f} / "
        f"{sats_to_btc(prof.total_sent_sats):.8f} BTC"
    )
    typer.echo(f"Active         {fmt_time(prof.first_seen)} -> {fmt_time(prof.last_seen)}")
    score = analysis.score
    band_color = {"Severe": typer.colors.RED, "High": typer.colors.RED}.get(score.band)
    typer.secho(f"\nRisk score     {score.score}/100  ({score.band})", fg=band_color, bold=True)
    typer.echo(f"Explained by   {score.explanation()}")
    typer.echo(f"\nAlerts: {len(analysis.alerts)}")
    for alert in analysis.alerts:
        typer.secho(f"  [{alert.severity.upper()}] {alert.rule_id} - {alert.rule_name}", bold=True)
        typer.echo(f"      {alert.explanation}")
        typer.echo(f"      Ref: {alert.regulatory_reference}")
    for rule_id, error in analysis.rule_errors.items():
        typer.secho(f"  NOT EVALUATED {rule_id}: {error}", fg=typer.colors.YELLOW)


def _load_screener_or_exit(config: AppConfig) -> Screener:
    try:
        return Screener(load_ofac_list(config.ofac_local_path), read_labels(config.labels_path))
    except (OfacError, LabelError) as exc:
        _fail(str(exc))


def _print_tx(tx: dict[str, Any], quote: PriceQuote | None) -> None:
    status = tx["status"]
    total_out = sum(out["value"] for out in tx["vout"])
    typer.echo(f"Transaction   {tx['txid']}")
    if status["confirmed"]:
        when = datetime.fromtimestamp(status["block_time"], UTC).strftime("%Y-%m-%d %H:%M UTC")
        typer.echo(f"Status:       confirmed in block {status['block_height']} ({when})")
    else:
        typer.echo("Status:       unconfirmed (not cached)")
    typer.echo(f"Inputs:       {len(tx['vin'])}")
    typer.echo(f"Outputs:      {len(tx['vout'])}  total {total_out / SATS_PER_BTC:.8f} BTC")
    typer.echo(f"Fee:          {tx['fee']} sats")
    if quote is None:
        typer.echo("BTC/EUR:      unavailable -> rules will use BTC thresholds")
    else:
        eur_value = total_out / SATS_PER_BTC * quote.eur
        typer.echo(
            f"BTC/EUR:      {quote.eur:,.0f} (as of {quote.as_of})  "
            f"-> total value {eur_value:,.2f} EUR"
        )
    for out in tx["vout"]:
        address = out.get("scriptpubkey_address", f"<{out['scriptpubkey_type']}>")
        typer.echo(f"  -> {address:<64} {out['value'] / SATS_PER_BTC:.8f} BTC")


def _load_config_or_exit(config_dir: Path) -> AppConfig:
    try:
        return load_config(config_dir)
    except ConfigError as exc:
        _fail(f"Configuration error: {exc}")


def _fail(message: str) -> NoReturn:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)
