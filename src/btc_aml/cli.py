"""Command-line interface (entry point: ``btc-aml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from btc_aml import __version__
from btc_aml.config import ConfigError, load_config

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
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

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
