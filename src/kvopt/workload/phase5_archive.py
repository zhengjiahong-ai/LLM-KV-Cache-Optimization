"""Deterministic, fail-closed evidence archives for Phase 5 runs."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tarfile
from collections.abc import Sequence
from pathlib import Path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(source_root: Path) -> tuple[Path, ...]:
    files = []
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"evidence archive rejects symlink: {path}")
        if path.is_file():
            files.append(path)
    if not files:
        raise ValueError("evidence archive source is empty")
    return tuple(files)


def create_phase5_evidence_archive(
    *,
    source_root: Path,
    archive_path: Path,
    required_relative_paths: Sequence[str],
) -> dict[str, object]:
    """Archive immutable source evidence without modifying its directory."""

    source_root = source_root.resolve()
    archive_path = archive_path.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if archive_path.exists():
        raise FileExistsError(archive_path)
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    files = _source_files(source_root)
    names = {path.relative_to(source_root).as_posix() for path in files}
    required = set(required_relative_paths)
    if not required or not required.issubset(names):
        raise ValueError("evidence archive lacks one or more required files")
    hashes = {
        path.relative_to(source_root).as_posix(): _sha256_path(path) for path in files
    }
    manifest = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(hashes.items())
    ).encode()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            temporary.open("xb") as raw,
            gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            for path in files:
                name = path.relative_to(source_root).as_posix()
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            info = tarfile.TarInfo("sha256-manifest.txt")
            info.size = len(manifest)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(manifest))
        validation = validate_phase5_evidence_archive(temporary)
        if validation["status"] != "PASS":
            raise ValueError("new evidence archive failed internal validation")
        os.replace(temporary, archive_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "schema_version": "phase5.evidence_archive.v1",
        "status": "PASS",
        "source_file_count": len(files),
        "archive_sha256": _sha256_path(archive_path),
        "internal_manifest_sha256": _sha256_bytes(manifest),
        "archive_path": str(archive_path),
    }


def validate_phase5_evidence_archive(archive_path: Path) -> dict[str, object]:
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [row.name for row in members]
        if len(names) != len(set(names)):
            raise ValueError("evidence archive contains duplicate members")
        if any(not row.isfile() for row in members):
            raise ValueError("evidence archive may contain regular files only")
        if "sha256-manifest.txt" not in names:
            raise ValueError("evidence archive lacks internal manifest")
        manifest_handle = archive.extractfile("sha256-manifest.txt")
        assert manifest_handle is not None
        manifest_bytes = manifest_handle.read()
        expected = {}
        for line in manifest_bytes.decode().splitlines():
            digest, separator, name = line.partition("  ")
            if not separator or len(digest) != 64 or not name:
                raise ValueError("evidence archive manifest line is invalid")
            if name in expected:
                raise ValueError("evidence archive manifest contains duplicate path")
            expected[name] = digest
        actual_names = set(names) - {"sha256-manifest.txt"}
        if set(expected) != actual_names:
            raise ValueError("evidence archive member set differs from manifest")
        for name, digest in expected.items():
            handle = archive.extractfile(name)
            assert handle is not None
            if _sha256_bytes(handle.read()) != digest:
                raise ValueError(f"evidence archive hash mismatch: {name}")
    return {
        "schema_version": "phase5.evidence_archive_validation.v1",
        "status": "PASS",
        "file_count": len(expected),
        "internal_manifest_sha256": _sha256_bytes(manifest_bytes),
        "archive_sha256": _sha256_path(archive_path),
    }
