from vo_backup.manifest import SnapshotManifest


def test_manifest_roundtrip():
    m = SnapshotManifest.create("2026-05-29T120000Z", "job", ["/a"], 5)
    restored = SnapshotManifest.from_json(m.to_json())
    assert restored.snapshot_id == m.snapshot_id
    assert restored.file_count == 5
