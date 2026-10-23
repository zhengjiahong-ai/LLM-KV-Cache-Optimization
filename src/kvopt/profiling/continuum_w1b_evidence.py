"""Package the bounded W1-B Native comparison with a verifiable manifest."""

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


def package_w1b_evidence(
    *,
    repository: Path,
    replay_root: Path,
    fidelity_root: Path,
    profile_root: Path,
    freeze_root: Path,
    campaign_root: Path,
    run_root: Path,
    archive_path: Path,
) -> tuple[Path, Path]:
    repository = repository.resolve()
    roots = tuple(
        path.resolve()
        for path in (
            replay_root,
            fidelity_root,
            profile_root,
            freeze_root,
            campaign_root,
            run_root,
        )
    )
    archive_path = archive_path.resolve()
    report_path = run_root.resolve() / "comparison-report-v2.json"
    if not report_path.is_file():
        raise FileNotFoundError("W1-B comparison report is missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("gate") != "PASS":
        raise ValueError("W1-B evidence requires a passing bounded comparison report")
    run_manifests = sorted(run_root.resolve().glob("*/run.json"))
    if len(run_manifests) != 12:
        raise ValueError("W1-B evidence requires exactly 12 run manifests")
    statuses = Counter(
        str(json.loads(path.read_text(encoding="utf-8"))["execution_status"])
        for path in run_manifests
    )
    if statuses != Counter({"success": 12}):
        raise ValueError("W1-B evidence requires 12 successful runs")
    repository_files = (
        Path("configs/phase2/continuum-w1b-execution-semantics-reconciliation-v1.json"),
        Path("configs/phase2/continuum-w1b-native-smoke-protocol-v2.json"),
        Path("scripts/spikes/phase2_minimal_observability_metal.py"),
        Path("src/kvopt/continuum/prefill_profile.py"),
        Path("src/kvopt/profiling/continuum_w1b_evidence.py"),
        Path("src/kvopt/profiling/continuum_w1b_report.py"),
        Path("src/kvopt/profiling/runtime_evidence.py"),
        Path("src/kvopt/workload/continuum_w1b_campaign.py"),
        Path("src/kvopt/workload/continuum_w1b_cost_audit.py"),
        Path("src/kvopt/workload/continuum_w1b_fidelity.py"),
        Path("src/kvopt/workload/continuum_w1b_runner.py"),
        Path("src/kvopt/workload/continuum_w1b_smoke.py"),
        Path("tests/test_continuum_w1b_campaign.py"),
        Path("tests/test_continuum_w1b_native_input.py"),
        Path("tests/test_continuum_w1b_report.py"),
        Path("tests/test_continuum_w1b_runner.py"),
        Path("tests/test_continuum_vllm_observation_runner.py"),
    )
    missing = [str(path) for path in repository_files if not (repository / path).is_file()]
    if missing:
        raise FileNotFoundError("missing W1-B repository evidence: " + ", ".join(missing))
    sources: list[tuple[Path, Path]] = []
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(f"W1-B artifact root is missing: {root}")
        destination_root = Path("artifacts") / root.name
        sources.extend(
            (path, destination_root / path.relative_to(root))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
    sources.extend((repository / path, path) for path in repository_files)
    manifest = {
        "schema_version": "continuum.w1b_native_comparison_evidence_handoff.v2",
        "scope": "REAL_AGENT_CONTENT_CONTROLLED_SPARSE_TURN_PRESSURE_REPLAY",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "packaging_git_sha": _git(repository, "rev-parse", "HEAD"),
        "packaging_git_dirty": bool(
            _git(repository, "status", "--porcelain", "--untracked-files=no")
        ),
        "planned_run_count": 12,
        "recorded_run_count": len(run_manifests),
        "run_status_counts": dict(sorted(statuses.items())),
        "comparison_gate": report["gate"],
        "valid_group_count": report["valid_group_count"],
        "research_claim": report["research_claim"],
        "formal_performance_campaign": False,
        "a0_modified": False,
        "native_block_pool_modified": False,
        "a3_implemented": False,
        "b1_unlocked": False,
        "files": [
            {
                "archive_path": destination.as_posix(),
                "sha256": _sha256(source),
                "size_bytes": source.stat().st_size,
            }
            for source, destination in sources
        ],
    }
    base_name = archive_path.name.removesuffix(".tar.gz")
    manifest_path = archive_path.with_name(f"{base_name}-manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        for source, destination in sources:
            archive.add(source, arcname=destination.as_posix())
        archive.add(manifest_path, arcname=f"evidence/{manifest_path.name}")
    return manifest_path, archive_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--fidelity-root", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--freeze-root", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest, archive = package_w1b_evidence(
        repository=args.repository,
        replay_root=args.replay_root,
        fidelity_root=args.fidelity_root,
        profile_root=args.profile_root,
        freeze_root=args.freeze_root,
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
