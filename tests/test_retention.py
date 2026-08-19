from datetime import datetime, timezone

from vo_backup.retention import parse_snapshot_id


def test_parse_snapshot_id_valid():
    dt = parse_snapshot_id("2026-05-29T143022Z")
    assert dt == datetime(2026, 5, 29, 14, 30, 22, tzinfo=timezone.utc)


def test_parse_snapshot_id_invalid():
    assert parse_snapshot_id("not-a-snapshot") is None
    assert parse_snapshot_id("2026-05-29") is None
