"""CLI for vo-backup-progress."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from vo_backup.config import DEFAULT_CONFIG_PATH, load_config
from vo_backup.progress import (
    SamplePoint,
    estimate_progress,
    eta_seconds_from_samples,
    eta_seconds_from_started,
    format_report,
    load_sample,
    parse_started,
    save_sample,
)
from vo_backup.vospace import VOSpace


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.command()
@click.option(
    "-c",
    "--config",
    default=str(DEFAULT_CONFIG_PATH),
    show_default=True,
    type=click.Path(exists=True),
    help="YAML config file",
)
@click.option(
    "--started",
    default=None,
    help="Backup start time (YYYY-MM-DD or ISO-8601) for ETA from overall rate",
)
@click.option(
    "--sample",
    "sample_path",
    default=None,
    type=click.Path(),
    help="JSON sample file; ETA uses delta vs previous sample when present",
)
@click.option("-v", "--verbose", is_flag=True, help="Debug logging")
def main(
    config: str,
    started: str | None,
    sample_path: str | None,
    verbose: bool,
) -> None:
    """Estimate how much of an in-flight backup to VOSpace current/ is done."""
    _setup_logging(verbose)
    cfg = load_config(config)
    vos = VOSpace(cfg.certfile, nstreams=cfg.nstreams)
    report = estimate_progress(cfg, vos)

    eta_seconds = None
    eta_source = None
    now = datetime.now(timezone.utc)

    if sample_path:
        path = Path(sample_path)
        previous = load_sample(path)
        current = SamplePoint(
            ts=time.time(),
            done_bytes=report.done_bytes,
            done_files=report.done_files,
        )
        if previous is not None:
            eta_seconds = eta_seconds_from_samples(
                previous, current, report.remaining_bytes
            )
            if eta_seconds is None:
                eta_source = "sample: need more progress between samples"
            else:
                eta_source = f"from sample delta vs {path}"
        else:
            eta_source = f"sample saved to {path}; re-run later for ETA"
        save_sample(path, current)

    if started and eta_seconds is None:
        started_dt = parse_started(started, now=now)
        eta_seconds = eta_seconds_from_started(
            started_dt,
            report.done_bytes,
            report.remaining_bytes,
            now=now,
        )
        if eta_seconds is None:
            eta_source = f"from --started {started}: need positive elapsed progress"
        else:
            eta_source = f"from --started {started}"

    click.echo(
        format_report(
            report,
            eta_seconds=eta_seconds,
            eta_source=eta_source,
        )
    )


if __name__ == "__main__":
    main()
