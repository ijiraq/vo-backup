# vo-backup

Incremental backups from a Linux filesystem to [CADC VOSpace](https://www.opencadc.org/canfar/latest/platform/storage/vospace/) (CANFAR).

## Features

- **Hybrid backup model**: fast incremental sync into a `current/` mirror, plus dated snapshots under `snapshots/` for history
- **Snapshot deduplication**: unchanged files are **moved** into the new snapshot; the previous snapshot path becomes a **VOSpace link** (no re-upload)
- **Include/exclude** patterns (gitignore-style via pathspec)
- **Age-based retention** pruning of old snapshots
- **Restore** from `current/` or a specific snapshot
- **Parallel uploads** (`nstreams` in config)
- **X509 certificate** authentication (standard CADC / `vos` workflow)



## Requirements

- Python 3.10+
- A [CANFAR account](https://www.canfar.net/) with VOSpace write access
- An X509 proxy certificate at `~/.ssl/cadcproxy.pem` (see Authentication below)
- Network access to CADC services



## Install

```bash
cd /path/to/vo_backup
pip install -e ".[dev]"
```



## Configuration

Copy the example and edit:

```bash
cp config.example.yaml config.yaml
```

See `[config.example.yaml](config.example.yaml)`. Required fields: `job_name`, `vospace_root`, `source_paths`.

## Authentication

vo-backup uses the same X509 proxy certificate as the `vos` command-line tools. By default it reads:

```text
${HOME}/.ssl/cadcproxy.pem
```

Obtain or refresh the certificate with `[cadc-get-cert](https://pypi.org/project/cadcutils/)` (installed with `vos`):

```bash
cadc-get-cert -u <your-canfar-username> -f ~/.ssl/cadcproxy.pem
```

Override the path in config with `certfile: /path/to/cert.pem`, or set the `VOSPACE_CERTFILE` environment variable.

Remote layout (created automatically if missing, including parent folders):

```text
vos:{user}/{backup_root}/
  current/
    project/file.txt          # LinkNode -> snapshots/latest/project/file.txt
  snapshots/
    latest                    # LinkNode -> snapshots/2026-05-29T143022Z/
    2026-05-29T143022Z/       # real data for this generation
      project/file.txt
    2026-05-22T090000Z/       # older generation (may contain links into newer trees)
```

`current/` holds only **links** into `snapshots/latest/…` after a snapshot completes. The `latest` link is repointed at each new snapshot so `current/` never references pruned timestamp directories.

Do not commit `config.yaml` if it contains site-specific paths. Protect `~/.ssl/cadcproxy.pem` with mode `600`.

### Snapshot storage and links

Each snapshot is a directory under `snapshots/{timestamp}/`. When a previous snapshot exists, unchanged files (MD5) are **moved** into the new snapshot; the old snapshot path becomes a link to the new data.

At the end of every `snapshot` run:

1. All file data for this generation lives under `snapshots/{timestamp}/`.
2. `snapshots/latest` is updated to point at that timestamp directory.
3. Every path under `current/` is turned into a link to `snapshots/latest/{same path}`.

Files that were **data nodes in** `current/` but not in the previous snapshot are **moved** into the new snapshot (not re-uploaded from disk when possible).

**Prune** deletes old `snapshots/{timestamp}/` trees only; it never removes `snapshots/latest` or the snapshot `latest` currently points at. `current/` links stay valid because they always target `snapshots/latest/…`.

### Sync

`sync` updates `current/` against disk, using content under `snapshots/latest/` (via the `latest` pointer):

- Disk matches latest but missing from `current/` → link `current/…` → `snapshots/latest/…` (no upload).
- `current/` link points at a **stale** timestamp path (e.g. after manual changes) → rewire to `snapshots/latest/…` when content still matches.
- Disk changed vs link target → replace link with a local upload to `current/` (snapshot data untouched).
- Normal data node in `current/` → size/mtime rules as before.



## Usage

```bash
# Incremental sync to current/
vo-backup -c config.yaml sync

# Create a dated snapshot (syncs first; unchanged files move+link, others upload)
vo-backup -c config.yaml snapshot

# Sync + snapshot + prune
vo-backup -c config.yaml run --snapshot

# Remove snapshots older than retention_days
vo-backup -c config.yaml prune

# List snapshots
vo-backup -c config.yaml list

# Job status
vo-backup -c config.yaml status

# Restore
vo-backup -c config.yaml restore --from current --dest ./restored
vo-backup -c config.yaml restore --from snapshot --snapshot-id 2026-05-29T143022Z --dest ./restored
```

Add `--dry-run` to `sync`, `snapshot`, `run`, `prune`, or `restore` to log actions without transferring data.

Add `-v` for debug logging.

## Scheduling (future)

Example cron (adjust paths):

```cron
# Daily incremental sync at 02:00
0 2 * * * vo-backup -c /etc/vo-backup/config.yaml sync

# Weekly snapshot + prune on Sunday 03:00
0 3 * * 0 vo-backup -c /etc/vo-backup/config.yaml run --snapshot
```



## Manual verification checklist

1. `pip install -e ".[dev]"` in the project directory.
2. Create a small test directory and a minimal `config.yaml` pointing at it and a test `vospace_root`.
3. `vo-backup -c config.yaml sync` — verify files appear under `current/` with `vls vos:.../current/`.
4. Change and delete a local file; run `sync` again — confirm update and deletion on `current/`.
5. `vo-backup -c config.yaml snapshot` — confirm a new folder under `snapshots/`.
6. Set `retention_days: 0` on a test config (or old snapshots) and run `prune`.
7. `vo-backup -c config.yaml restore --from snapshot --snapshot-id ... --dest ./out` — confirm files match.



## Development

```bash
pytest
```



## License

MIT