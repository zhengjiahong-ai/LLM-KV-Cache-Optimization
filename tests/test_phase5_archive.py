from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from kvopt.workload.phase5_archive import (
    create_phase5_evidence_archive,
    validate_phase5_evidence_archive,
)


def test_archive_round_trip_is_hash_bound_and_does_not_mutate_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "run"
    source.mkdir()
    (source / "run.json").write_text('{"status":"PASS"}\n')
    (source / "events.jsonl").write_text('{"event_index":1}\n')
    before = sorted(path.name for path in source.iterdir())
    archive = tmp_path / "evidence.tar.gz"

    report = create_phase5_evidence_archive(
        source_root=source,
        archive_path=archive,
        required_relative_paths=("run.json", "events.jsonl"),
    )
    validation = validate_phase5_evidence_archive(archive)
    second_archive = tmp_path / "same-evidence.tar.gz"
    second = create_phase5_evidence_archive(
        source_root=source,
        archive_path=second_archive,
        required_relative_paths=("run.json", "events.jsonl"),
    )

    assert report["status"] == "PASS"
    assert validation["status"] == "PASS"
    assert validation["file_count"] == 2
    assert second["archive_sha256"] == report["archive_sha256"]
    assert sorted(path.name for path in source.iterdir()) == before
    with tarfile.open(archive, "r:gz") as handle:
        assert sorted(handle.getnames()) == [
            "events.jsonl",
            "run.json",
            "sha256-manifest.txt",
        ]


def test_archive_fails_on_missing_required_file_and_existing_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "run"
    source.mkdir()
    (source / "run.json").write_text("{}\n")
    archive = tmp_path / "evidence.tar.gz"

    with pytest.raises(ValueError, match="required files"):
        create_phase5_evidence_archive(
            source_root=source,
            archive_path=archive,
            required_relative_paths=("events.jsonl",),
        )

    archive.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        create_phase5_evidence_archive(
            source_root=source,
            archive_path=archive,
            required_relative_paths=("run.json",),
        )


def test_archive_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "run"
    source.mkdir()
    target = source / "run.json"
    target.write_text("{}\n")
    (source / "alias.json").symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        create_phase5_evidence_archive(
            source_root=source,
            archive_path=tmp_path / "evidence.tar.gz",
            required_relative_paths=("run.json",),
        )
