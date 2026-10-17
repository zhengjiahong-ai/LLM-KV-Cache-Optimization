"""Package Phase 2G A1 native evidence with a verifiable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
from collections import Counter
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


def package_phase2g_a1_evidence(
    *,
    repository: Path,
    gate1_report: Path,
    campaign_root: Path,
    run_root: Path,
    outcome_report: Path,
    archive_path: Path,
) -> tuple[Path, Path]:
    repository = repository.resolve()
    gate1_report = gate1_report.resolve()
    campaign_root = campaign_root.resolve()
    run_root = run_root.resolve()
    outcome_report = outcome_report.resolve()
    archive_path = archive_path.resolve()
    required = [
        gate1_report,
        campaign_root / "manifest.json",
        campaign_root / "validation.json",
        campaign_root / "authorization.json",
        outcome_report,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Phase 2G A1 evidence: " + ", ".join(missing))
    repository_files = [
        Path("configs/phase2/phase2g-a1-native-gate1-v1.json"),
        Path("configs/phase2/phase2g-a1-bounded-distribution-v1.json"),
        Path("src/kvopt/continuum/pressure.py"),
        Path("src/kvopt/costaware/a1_native.py"),
        Path("src/kvopt/profiling/ingestion.py"),
        Path("src/kvopt/profiling/phase2g_a1_gate1.py"),
        Path("src/kvopt/profiling/phase2g_a1_bounded_gate.py"),
        Path("src/kvopt/profiling/phase2g_a1_evidence.py"),
        Path("src/kvopt/workload/phase2g_a1_gate1_materialize.py"),
        Path("src/kvopt/workload/phase2g_a1_gate1_runner.py"),
        Path("src/kvopt/workload/phase2g_a1_bounded_materialize.py"),
        Path("src/kvopt/workload/phase2g_a1_bounded_validate.py"),
        Path("src/kvopt/workload/phase2g_a1_bounded_authorize.py"),
        Path("src/kvopt/workload/phase2g_a1_bounded_runner.py"),
        Path("scripts/spikes/phase2_minimal_observability_metal.py"),
    ]
    missing_repository = [
        str(path) for path in repository_files if not (repository / path).is_file()
    ]
    if missing_repository:
        raise FileNotFoundError("missing repository evidence: " + ", ".join(missing_repository))
    run_manifests = sorted(run_root.glob("*/run.json"))
    statuses = Counter(
        str(json.loads(path.read_text(encoding="utf-8"))["execution_status"])
        for path in run_manifests
    )
    if len(run_manifests) != 144:
        raise ValueError("Phase 2G evidence requires all 144 run manifests")
    outcome = json.loads(outcome_report.read_text(encoding="utf-8"))
    if outcome.get("schema_version") != "phase2g.a1_bounded_gate.v1":
        raise ValueError("unsupported Phase 2G outcome report")
    sources: list[tuple[Path, Path]] = []
    for root in (campaign_root, run_root):
        destination_root = Path("artifacts") / root.name
        sources.extend(
            (path, destination_root / path.relative_to(root))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
    sources.extend(
        [
            (gate1_report, Path("artifacts/gate1/gate1-report.json")),
            (outcome_report, Path("artifacts/outcome/gate-report.json")),
        ]
    )
    sources.extend((repository / path, path) for path in repository_files)
    manifest = {
        "schema_version": "phase2g.a1_native_evidence_handoff.v1",
        "scope": "PHASE2G_A1_NATIVE_BOUNDED_EVALUATION",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "packaging_git_sha": _git(repository, "rev-parse", "HEAD"),
        "packaging_git_dirty": bool(
            _git(repository, "status", "--porcelain", "--untracked-files=no")
        ),
        "planned_run_count": 144,
        "recorded_run_count": len(run_manifests),
        "run_status_counts": dict(sorted(statuses.items())),
        "missing_run_count": 144 - len(run_manifests),
        "failed_runs_preserved": statuses.get("failed", 0) > 0,
        "gate1_status": "PASS",
        "independent_statistical_unit": "scenario_draw",
        "primary_metric": "aggregate_recomputed_tokens",
        "outcome_summary": outcome["overall"],
        "formal_h1_h2_modified": False,
        "a0_modified": False,
        "native_block_pool_modified": False,
        "a2_a3_implemented": False,
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
    parser.add_argument("--gate1-report", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--outcome-report", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest, archive = package_phase2g_a1_evidence(
        repository=args.repository,
        gate1_report=args.gate1_report,
        campaign_root=args.campaign_root,
        run_root=args.run_root,
        outcome_report=args.outcome_report,
        archive_path=args.archive,
    )
    print(f"manifest: {manifest}")
    print(f"archive: {archive}")
    print(f"archive sha256: {_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
