"""Package Phase 2E measured evidence with an independently verifiable manifest."""

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
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def package_phase2e_evidence(
    *,
    repository: Path,
    campaign_root: Path,
    run_root: Path,
    archive_path: Path,
) -> tuple[Path, Path]:
    repository = repository.resolve()
    campaign_root = campaign_root.resolve()
    run_root = run_root.resolve()
    archive_path = archive_path.resolve()
    required = [
        campaign_root / "manifest.json",
        campaign_root / "validation.json",
        campaign_root / "joint-freeze-authorization.json",
        run_root / "campaign-gate.json",
        run_root / "measured-analysis.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Phase 2E evidence: " + ", ".join(missing))
    repository_files = [
        Path("docs/phase2e-m4-task-a-metrics-freeze.md"),
        Path("docs/phase2e-m4-t1-capability-reconciliation.md"),
        Path("docs/phase2e-m6-measured-campaign-report.md"),
        Path("configs/phase2/phase2e-workload-distribution-v1.json"),
        Path("src/kvopt/workload/phase2e_materialize.py"),
        Path("src/kvopt/workload/phase2e_runner.py"),
        Path("src/kvopt/workload/phase2e_validate.py"),
        Path("src/kvopt/profiling/phase2e_gate.py"),
        Path("src/kvopt/profiling/phase2e_campaign_gate.py"),
        Path("src/kvopt/profiling/phase2e_analysis.py"),
    ]
    missing_repository = [
        str(path) for path in repository_files if not (repository / path).is_file()
    ]
    if missing_repository:
        raise FileNotFoundError(
            "missing repository evidence: " + ", ".join(missing_repository)
        )
    sources: list[tuple[Path, Path]] = []
    for root in (campaign_root, run_root):
        destination_root = Path("artifacts") / root.name
        sources.extend(
            (path, destination_root / path.relative_to(root))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
    sources.extend((repository / path, path) for path in repository_files)
    manifest = {
        "schema_version": "phase2e.measured_evidence_handoff.v1",
        "scope": "PHASE2E_NATIVE_BASELINE_CHARACTERIZATION",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "packaging_git_sha": _git(repository, "rev-parse", "HEAD"),
        "packaging_git_dirty": bool(
            _git(repository, "status", "--porcelain", "--untracked-files=no")
        ),
        "execution_git_sha": "9f9de3199f21f45b1c283f62422ab0f85b074a48",
        "planned_run_count": 144,
        "successful_run_count": 144,
        "invalid_attempts_preserved": True,
        "formal_h1_h2_modified": False,
        "cost_aware_policy_implemented": False,
        "files": [
            {
                "archive_path": destination.as_posix(),
                "sha256": _sha256(source),
                "size_bytes": source.stat().st_size,
            }
            for source, destination in sources
        ],
    }
    base_name = (
        archive_path.name.removesuffix(".tar.gz")
        if archive_path.name.endswith(".tar.gz")
        else archive_path.stem
    )
    manifest_path = archive_path.with_name(f"{base_name}-manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        for source, destination in sources:
            archive.add(source, arcname=destination.as_posix())
        archive.add(manifest_path, arcname=f"evidence/{manifest_path.name}")
    return manifest_path, archive_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest, archive = package_phase2e_evidence(
        repository=args.repository,
        campaign_root=args.campaign_root,
        run_root=args.run_root,
        archive_path=args.archive,
    )
    print(f"manifest: {manifest}")
    print(f"archive: {archive}")
    print(f"archive sha256: {_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
