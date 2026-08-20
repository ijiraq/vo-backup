"""Command-line interface for vo-backup."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from vo_backup.config import DEFAULT_CONFIG_PATH, create_config_interactively, load_config
from vo_backup.restore import run_restore
from vo_backup.retention import list_snapshot_ids, parse_snapshot_id, run_prune
from vo_backup.snapshot import run_snapshot
from vo_backup.state import RunStats, load_state, save_state, utc_now_iso
from vo_backup.sync import run_sync
from vo_backup.vospace import VOSpace

WEEKDAY_TO_NUM = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _ensure_config(config_path: str) -> Path:
    path = Path(config_path)
    if path.is_file():
        return path

    click.echo(f"No config found at {path}; creating one.")
    create_config_interactively(
        path,
        prompt=lambda message: click.prompt(message, type=str),
        echo=click.echo,
    )
    click.echo(f"Wrote {path.resolve()}")
    return path


def _load_ctx(config_path: str):
    path = _ensure_config(config_path)
    config = load_config(path)
    vos = VOSpace(config.certfile, nstreams=config.nstreams)
    state = load_state(config.state_file, config.job_name)
    return config, vos, state


def _exit_code(stats: RunStats) -> int:
    return 1 if stats.errors else 0


@click.group()
@click.option(
    "-c",
    "--config",
    default=str(DEFAULT_CONFIG_PATH),
    show_default=True,
    type=click.Path(),
    help="YAML config file (created interactively if missing)",
)
@click.option("-v", "--verbose", is_flag=True, help="Debug logging")
@click.pass_context
def main(ctx, config: str, verbose: bool) -> None:
    """Incremental backups from Linux to CADC VOSpace."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    cfg, vos, state = _load_ctx(config)
    ctx.obj["config"] = cfg
    ctx.obj["vos"] = vos
    ctx.obj["state"] = state


@main.command()
@click.option("--dry-run", is_flag=True, help="Show actions without transferring")
@click.pass_context
def sync(ctx, dry_run: bool) -> None:
    """Incremental sync to VOSpace current/ mirror."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    state = ctx.obj["state"]
    stats = run_sync(config, vos, dry_run=dry_run)
    if not dry_run and stats.errors == 0:
        state.last_sync_at = utc_now_iso()
        state.last_sync_stats = {
            "uploaded": stats.uploaded,
            "skipped": stats.skipped,
            "deleted": stats.deleted,
            "bytes_uploaded": stats.bytes_uploaded,
        }
        save_state(config.state_file, state)
    sys.exit(_exit_code(stats))


@main.command()
@click.option("--dry-run", is_flag=True)
@click.option("--skip-sync", is_flag=True, help="Skip syncing current/ before snapshot")
@click.pass_context
def snapshot(ctx, dry_run: bool, skip_sync: bool) -> None:
    """Create a dated snapshot under snapshots/."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    state = ctx.obj["state"]
    snap_id, stats = run_snapshot(config, vos, dry_run=dry_run, skip_sync=skip_sync)
    if not dry_run and stats.errors == 0:
        state.last_snapshot_at = utc_now_iso()
        state.last_snapshot_id = snap_id
        save_state(config.state_file, state)
    sys.exit(_exit_code(stats))


@main.command()
@click.option("--snapshot", "do_snapshot", is_flag=True, help="Also create a snapshot and prune")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def run(ctx, do_snapshot: bool, dry_run: bool) -> None:
    """Run sync; optionally snapshot and prune old snapshots."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    state = ctx.obj["state"]

    stats = run_sync(config, vos, dry_run=dry_run)
    if not dry_run and stats.errors == 0:
        state.last_sync_at = utc_now_iso()
        state.last_sync_stats = {
            "uploaded": stats.uploaded,
            "skipped": stats.skipped,
            "deleted": stats.deleted,
            "bytes_uploaded": stats.bytes_uploaded,
        }

    if do_snapshot and stats.errors == 0:
        snap_id, snap_stats = run_snapshot(
            config, vos, dry_run=dry_run, skip_sync=True
        )
        stats.errors += snap_stats.errors
        if not dry_run and snap_stats.errors == 0:
            state.last_snapshot_at = utc_now_iso()
            state.last_snapshot_id = snap_id
        if stats.errors == 0:
            run_prune(config, vos, dry_run=dry_run)

    if not dry_run:
        save_state(config.state_file, state)
    sys.exit(_exit_code(stats))


@main.command()
@click.option("--dry-run", is_flag=True)
@click.pass_context
def prune(ctx, dry_run: bool) -> None:
    """Delete snapshots older than retention_days."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    run_prune(config, vos, dry_run=dry_run)


@main.command("list")
@click.pass_context
def list_cmd(ctx) -> None:
    """List available snapshots."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    now = datetime.now(timezone.utc)
    for snap_id in list_snapshot_ids(vos, config):
        created = parse_snapshot_id(snap_id)
        age_days = (now - created).days if created else "?"
        click.echo(f"{snap_id}  age={age_days}d")


@main.command()
@click.pass_context
def status(ctx) -> None:
    """Show job state and remote summary."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    state = ctx.obj["state"]
    click.echo(f"job: {config.job_name}")
    click.echo(f"vospace_root: {config.vospace_root}")
    click.echo(f"last_sync_at: {state.last_sync_at or 'never'}")
    click.echo(f"last_snapshot_at: {state.last_snapshot_at or 'never'}")
    click.echo(f"last_snapshot_id: {state.last_snapshot_id or 'none'}")
    remote = vos.list_tree(config.current_uri)
    click.echo(f"remote_current_files: {len(remote)}")
    snaps = list_snapshot_ids(vos, config)
    click.echo(f"remote_snapshots: {len(snaps)}")


@main.command()
@click.option(
    "--from",
    "restore_from",
    type=click.Choice(["current", "snapshot"]),
    required=True,
)
@click.option("--snapshot-id", default=None, help="Snapshot folder name (required for snapshot)")
@click.option("--dest", required=True, type=click.Path(), help="Local destination directory")
@click.option("--paths", multiple=True, help="Relative paths to restore (default: all)")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def restore(ctx, restore_from: str, snapshot_id: str | None, dest: str, paths: tuple, dry_run: bool) -> None:
    """Restore files from current/ or a snapshot."""
    config = ctx.obj["config"]
    vos = ctx.obj["vos"]
    restored, errors = run_restore(
        config,
        vos,
        source=restore_from,
        snapshot_id=snapshot_id,
        dest=Path(dest),
        paths=list(paths) or None,
        dry_run=dry_run,
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
