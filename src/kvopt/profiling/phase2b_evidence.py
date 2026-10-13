"""Package the bounded Phase 2B fidelity evidence for external review."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def package_phase2b_evidence(
    *,
    repository: Path,
    artifact_root: Path,
    archive_path: Path,
    primary_run_id: str,
    legacy_regression_path: Path,
) -> tuple[Path, Path]:
    repository = repository.resolve()
    artifact_root = artifact_root.resolve()
    archive_path = archive_path.resolve()
    diagnostic_files = [
        Path("phase2b-fidelity-smoke-v1/run.json"),
        Path("phase2b-fidelity-smoke-v1/events.jsonl"),
        Path("phase2b-fidelity-smoke-v1/replay.jsonl"),
        Path("phase2b-fidelity-smoke-v1/fidelity-result.json"),
        Path("phase2b-fidelity-smoke-v2/config.json"),
        Path("phase2b-fidelity-smoke-v2/run.json"),
        Path("phase2b-fidelity-smoke-v2/trace.json"),
        Path("phase2b-fidelity-smoke-v2/events.jsonl"),
        Path("phase2b-fidelity-smoke-v2/replay.jsonl"),
        Path("phase2b-fidelity-smoke-v2/fidelity-result.json"),
        Path("phase2b-fidelity-smoke-v2/fidelity-audit.json"),
        Path("phase2b-fidelity-smoke-v2/fidelity-audit-final.json"),
    ]
    primary = Path(primary_run_id)
    primary_files = [
        primary / "config.json",
        primary / "run.json",
        primary / "trace.json",
        primary / "events.jsonl",
        primary / "replay.jsonl",
        primary / "fidelity-result.json",
        primary / "fidelity-audit.json",
        primary / "fidelity-audit-final.json",
    ]
    relative_files = [*diagnostic_files, *primary_files]
    repository_files = [
        Path("docs/phase2b-m6-experimental-fidelity-repair-spec.md"),
        Path("docs/phase2b-m6-fidelity-baseline.json"),
        legacy_regression_path.resolve().relative_to(repository),
        Path("src/kvopt/profiling/phase2b_fidelity.py"),
        Path("src/kvopt/workload/phase2b_fidelity.py"),
        Path("tests/test_phase2b_fidelity_report.py"),
        Path("tests/test_phase2b_pressure_fidelity.py"),
        Path("tests/test_phase2b_history_fidelity.py"),
        Path("configs/phase2/phase2b-fidelity-smoke-config.json"),
        Path("configs/phase2/phase2b-fidelity-smoke-config-v2.json"),
        Path("configs/phase2/phase2b-fidelity-smoke-contract.json"),
        Path("configs/phase2/phase2b-fidelity-smoke-trace.json"),
    ]
    sources: list[tuple[Path, Path]] = [
        (artifact_root / relative, Path("artifacts/phase2b-fidelity") / relative)
        for relative in relative_files
    ] + [(repository / relative, relative) for relative in repository_files]
    missing = [str(source) for source, _archive in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError("missing evidence files: " + ", ".join(missing))

    final_audit = json.loads(
        (artifact_root / primary / "fidelity-audit-final.json").read_text(
            encoding="utf-8"
        )
    )
    primary_run = json.loads(
        (artifact_root / primary / "run.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "phase2b.fidelity_evidence_handoff.v1",
        "scope": "NON_HOLDOUT_FIDELITY_REPAIR",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "packaging_git_sha": _git_head(),
        "packaging_git_dirty": _git_dirty(),
        "raw_evidence_git_sha": primary_run.get("git_sha"),
        "audit_recalculation_git_sha": _git_head(),
        "raw_evidence_reused_without_gpu_rerun": True,
        "formal_h1_h2_modified": False,
        "primary_run_id": primary_run_id,
        "gate_statuses": {
            gate["gate"]: gate["status"] for gate in final_audit["gates"]
        },
        "limitations": final_audit["limitations"],
        "files": [
            {
                "archive_path": archive.as_posix(),
                "sha256": _sha256(source),
                "size_bytes": source.stat().st_size,
            }
            for source, archive in sources
        ],
    }
    manifest_path = artifact_root / "handoff-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for source, destination in sources:
            archive.add(source, arcname=destination.as_posix())
        archive.add(
            manifest_path,
            arcname="artifacts/phase2b-fidelity/handoff-manifest.json",
        )
    return manifest_path, archive_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--primary-run-id", required=True)
    parser.add_argument("--legacy-regression", type=Path, required=True)
    arguments = parser.parse_args(argv)
    manifest, archive = package_phase2b_evidence(
        repository=arguments.repository,
        artifact_root=arguments.artifact_root,
        archive_path=arguments.archive,
        primary_run_id=arguments.primary_run_id,
        legacy_regression_path=arguments.legacy_regression,
    )
    print(f"manifest: {manifest}")
    print(f"archive: {archive}")
    print(f"archive sha256: {_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
