"""Command-line entrypoint."""
from __future__ import annotations

import json
import logging
import sys

import click

from commencement.common.logging import setup_logging
from commencement.config import CONFIG
from commencement.db.session import init_schema


@click.group()
@click.option("--verbose", "-v", is_flag=True)
def cli(verbose: bool) -> None:
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)


@cli.command("init-db")
def init_db_cmd() -> None:
    """Create the SQLite schema if it doesn't exist."""
    init_schema()
    click.echo(f"schema initialized at {CONFIG.DB_URL}")


@cli.command("frame")
@click.option("--reload", is_flag=True, help="drop and reload the institutions table")
@click.option("--sample-size", type=int, default=CONFIG.PILOT_SAMPLE_SIZE)
@click.option("--seed", type=int, default=CONFIG.RANDOM_SEED)
def frame_cmd(reload: bool, sample_size: int, seed: int) -> None:
    """Stage 0: download IPEDS HD and draw the stratified sample."""
    from commencement.stage0_frame.flow import flow_frame_construction

    result = flow_frame_construction(reload=reload, sample_size=sample_size, seed=seed)
    click.echo(json.dumps(result, indent=2))


@cli.command("discover")
@click.option(
    "--mode",
    type=click.Choice(["initial", "catch-late", "future", "institution"]),
    default="initial",
)
@click.option("--ipeds-id", type=int, default=None)
@click.option("--triggered-by", default="manual")
@click.option("--year", type=int, default=CONFIG.PILOT_YEAR, help="ceremony year to operate on")
def discover_cmd(mode: str, ipeds_id: int | None, triggered_by: str, year: int) -> None:
    """Run discovery (Steps 1->2->3) for the chosen mode."""
    from commencement.discovery.flow import flow_discovery

    result = flow_discovery(
        mode=mode, ipeds_id=ipeds_id, triggered_by=triggered_by, year=year
    )
    click.echo(json.dumps(result, indent=2))


@cli.command("export")
@click.option("--version", "-V", type=int, required=True)
@click.option("--year", type=int, default=CONFIG.PILOT_YEAR, help="ceremony year to export")
def export_cmd(version: int, year: int) -> None:
    """Write a versioned export of ceremonies x links to exports/."""
    from commencement.export import export_corpus

    paths = export_corpus(version=version, year=year)
    for k, p in paths.items():
        click.echo(f"{k}: {p}")


if __name__ == "__main__":
    sys.exit(cli())
