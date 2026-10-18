"""Package Phase 2G A2 Native Gate 1 evidence with a verifiable manifest."""

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


def package_phase2g_a2_evidence(
    *,
    repository: Path,
    campaign_root: Path,
    run_root: Path,
    review_report: Path,
    smoke_roots: Sequence[Path],
    archive_path: Path,
) -> tuple[Path, Path]:
    repository = repository.resolve()
    campaign_root = campaign_root.resolve()
    run_root = run_root.resolve()
    review_report = review_report.resolve()
    smoke_roots = tuple(path.resolve() for path in smoke_roots)
    archive_path = archive_path.resolve()
    required = (campaign_root / "manifest.json", review_report)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing Phase 2G A2 evidence: " + ", ".join(missing))
    repository_files = (
        Path("configs/phase2/phase2g-a2-native-gate1-v1.json"),
        Path("scripts/spikes/phase2_minimal_observability_metal.py"),
        Path("src/kvopt/costaware/a2_contract.py"),
        Path("src/kvopt/costaware/a2_geometry.py"),
        Path("src/kvopt/costaware/a2_native.py"),
        Path("src/kvopt/costaware/a2_selector.py"),
        Path("src/kvopt/profiling/phase2g_a2_evidence.py"),
        Path("src/kvopt/profiling/phase2g_a2_gate1.py"),
        Path("src/kvopt/runtime/vllm/bridge.py"),
        Path("src/kvopt/runtime/vllm/retention_integration.py"),
        Path("src/kvopt/runtime/vllm/types.py"),
        Path("src/kvopt/workload/phase2g_a2_gate1_materialize.py"),
        Path("src/kvopt/workload/phase2g_a2_gate1_runner.py"),
        Path("tests/test_costaware_a2_native.py"),
        Path("tests/test_phase2g_a2_gate1_materialize.py"),
        Path("tests/test_phase2g_a2_gate1_report.py"),
    )
    missing_repository = [
        str(path) for path in repository_files if not (repository / path).is_file()
    ]
    if missing_repository:
        raise FileNotFoundError(
            "missing repository evidence: " + ", ".join(missing_repository)
        )
    run_manifests = sorted(run_root.glob("*/run.json"))
    if len(run_manifests) != 24:
        raise ValueError("Phase 2G A2 Gate 1 evidence requires all 24 run manifests")
    statuses = Counter(
        str(json.loads(path.read_text(encoding="utf-8"))["execution_status"])
        for path in run_manifests
    )
    report = json.loads(review_report.read_text(encoding="utf-8"))
    if report.get("schema_version") != "phase2g.a2_native_gate1_report.v1":
        raise ValueError("unsupported Phase 2G A2 Gate 1 report")
    if report.get("gate2_execution_authorized") is not False:
        raise ValueError("A2 evidence package cannot authorize Gate 2")

    sources: list[tuple[Path, Path]] = []
    artifact_roots = (campaign_root, run_root, *smoke_roots)
    for root in artifact_roots:
        if not root.is_dir():
            continue
        destination_root = Path("artifacts") / root.name
        sources.extend(
            (path, destination_root / path.relative_to(root))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
    sources.append((review_report, Path("artifacts/review/gate1-report.json")))
    sources.extend((repository / path, path) for path in repository_files)
    smoke_manifests = [
        path
        for root in smoke_roots
        if root.is_dir()
        for path in root.glob("*/run.json")
    ]
    smoke_statuses = Counter(
        str(json.loads(path.read_text(encoding="utf-8"))["execution_status"])
        for path in smoke_manifests
    )
    manifest = {
        "schema_version": "phase2g.a2_native_gate1_evidence_handoff.v1",
        "scope": "PHASE2G_A2_NATIVE_GATE1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "packaging_git_sha": _git(repository, "rev-parse", "HEAD"),
        "packaging_git_dirty": bool(
            _git(repository, "status", "--porcelain", "--untracked-files=no")
        ),
        "planned_run_count": 24,
        "recorded_run_count": len(run_manifests),
        "run_status_counts": dict(sorted(statuses.items())),
        "smoke_run_count": len(smoke_manifests),
        "smoke_status_counts": dict(sorted(smoke_statuses.items())),
        "review_outcome": report["outcome"],
        "native_selection_divergence": report["native_selection_divergence"],
        "shared_multichain_mechanism": report["shared_multichain_mechanism"],
        "physical_eviction_correlation": report["physical_eviction_correlation"],
        "gate2_execution_authorized": False,
        "a0_modified": False,
        "native_block_pool_modified": False,
        "a3_implemented": False,
        "b1_unlocked": False,
        "formal_h1_h2_modified": False,
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
    parser.add_argument("--review-report", type=Path, required=True)
    parser.add_argument("--smoke-root", action="append", type=Path, default=[])
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest, archive = package_phase2g_a2_evidence(
        repository=args.repository,
        campaign_root=args.campaign_root,
        run_root=args.run_root,
        review_report=args.review_report,
        smoke_roots=args.smoke_root,
        archive_path=args.archive,
    )
    print(f"manifest: {manifest}")
    print(f"archive: {archive}")
    print(f"archive sha256: {_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
