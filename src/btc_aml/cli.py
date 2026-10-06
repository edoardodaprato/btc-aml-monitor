"""Command-line interface (entry point: ``btc-aml``)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from btc_aml import __version__
from btc_aml.config import AppConfig, ConfigError, load_config
from btc_aml.data_sources.cache import Cache
from btc_aml.data_sources.http import DataSourceError
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
    typer.echo(f"{'RULE':<30} {'ON':<4} {'WEIGHT':>6}  SEVERITY")
    for rule in config.rules.values():
        status = "yes" if rule.enabled else "no"
        typer.echo(f"{rule.rule_id:<30} {status:<4} {rule.weight:>6.0f}  {rule.severity}")


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
        price = services.prices.eur_price(status["block_time"]) if status["confirmed"] else None
        _print_tx(tx, price)
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


def _print_tx(tx: dict[str, Any], eur_price: float | None) -> None:
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
    if eur_price is None:
        typer.echo("BTC/EUR:      unavailable -> rules will use BTC thresholds")
    else:
        eur_value = total_out / SATS_PER_BTC * eur_price
        typer.echo(f"BTC/EUR:      {eur_price:,.0f}  -> total value {eur_value:,.2f} EUR")
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
