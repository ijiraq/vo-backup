from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from vo_backup.progress import (
    SamplePoint,
    compute_progress,
    eta_seconds_from_samples,
    eta_seconds_from_started,
    format_bytes,
    format_duration,
    format_report,
    list_remote_sizes,
    load_sample,
    parse_started,
    save_sample,
)
from vo_backup.vospace import VOSpace


def test_compute_progress_done_and_remaining():
    local = {"a/f1": 100, "a/f2": 200, "b/f3": 50}
    remote = {"a/f1", "b/f3", "extra/remote-only"}

    report = compute_progress(local, remote)

    assert report.local_files == 3
    assert report.local_bytes == 350
    assert report.remote_files == 3
    assert report.done_files == 2
    assert report.done_bytes == 150
    assert report.remaining_files == 1
    assert report.remaining_bytes == 200
    assert abs(report.file_pct - 200 / 3) < 0.01
    assert abs(report.byte_pct - 150 / 350 * 100) < 0.01


def test_compute_progress_empty_local():
    report = compute_progress({}, set())
    assert report.file_pct == 100.0
    assert report.byte_pct == 100.0
    assert report.remaining_files == 0


def test_list_remote_sizes_does_not_follow_links():
    vos = VOSpace.__new__(VOSpace)
    vos.fix_uri = lambda uri: uri
    vos._client = MagicMock()

    container = SimpleNamespace(
        name="subdir/",
        type="vos:ContainerNode",
        uri="vos:u/current/subdir",
        attr={},
        setattr=MagicMock(),
    )
    data = SimpleNamespace(
        name="file.bin",
        type="vos:DataNode",
        uri="vos:u/current/file.bin",
        attr={"st_size": 42},
        setattr=MagicMock(),
    )
    link = SimpleNamespace(
        name="linked.txt",
        type="vos:LinkNode",
        uri="vos:u/current/linked.txt",
        target="vos:u/elsewhere/linked.txt",
        attr={"st_size": 7},
        setattr=MagicMock(),
    )
    nested = SimpleNamespace(
        name="nested.dat",
        type="vos:DataNode",
        uri="vos:u/current/subdir/nested.dat",
        attr={"st_size": 99},
        setattr=MagicMock(),
    )

    def get_children(uri, force=True):
        if uri.rstrip("/") == "vos:u/current":
            return [data, link, container]
        if uri.rstrip("/") == "vos:u/current/subdir":
            return [nested]
        return []

    vos._client.get_children_info.side_effect = get_children
    vos.get_node_info = MagicMock()

    sizes = list_remote_sizes(vos, "vos:u/current")

    assert sizes == {
        "file.bin": 42,
        "linked.txt": 7,
        "subdir/nested.dat": 99,
    }
    vos.get_node_info.assert_not_called()
    vos._client.get_node.assert_not_called()


def test_parse_started_date_and_iso():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert parse_started("2026-08-14", now=now) == datetime(
        2026, 8, 14, 0, 0, tzinfo=timezone.utc
    )
    assert parse_started("2026-08-14T15:30:00Z", now=now) == datetime(
        2026, 8, 14, 15, 30, tzinfo=timezone.utc
    )


def test_eta_from_started():
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)  # 10 days
    # 100 bytes in 10 days -> 10 B/day; 50 left -> 5 days
    eta = eta_seconds_from_started(started, 100, 50, now=now)
    assert eta is not None
    assert abs(eta - 5 * 86400) < 1


def test_eta_from_samples():
    prev = SamplePoint(ts=1000.0, done_bytes=1000, done_files=10)
    curr = SamplePoint(ts=1100.0, done_bytes=2000, done_files=20)
    # gained 1000 bytes in 100s -> 10 B/s; 500 remaining -> 50s
    assert eta_seconds_from_samples(prev, curr, 500) == 50.0
    assert eta_seconds_from_samples(prev, curr, 0) == 0.0
    assert eta_seconds_from_samples(prev, prev, 500) is None


def test_sample_roundtrip(tmp_path: Path):
    path = tmp_path / "progress.json"
    sample = SamplePoint(ts=1234.5, done_bytes=99, done_files=3)
    save_sample(path, sample)
    loaded = load_sample(path)
    assert loaded == sample


def test_format_helpers():
    assert format_bytes(1536) == "1.5 KiB"
    assert "1d" in format_duration(90000)
    text = format_report(
        compute_progress({"a": 100}, {"a"}),
        eta_seconds=3600,
        eta_source="from --started 2026-08-14",
    )
    assert "Done:" in text
    assert "ETA:" in text
