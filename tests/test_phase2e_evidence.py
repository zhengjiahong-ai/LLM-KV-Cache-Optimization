import json
import subprocess
import tarfile
from pathlib import Path

from kvopt.profiling.phase2e_evidence import package_phase2e_evidence


def test_package_contains_manifest_and_invalid_attempts(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
    repository_files = [
        "docs/phase2e-m4-task-a-metrics-freeze.md",
        "docs/phase2e-m4-t1-capability-reconciliation.md",
        "docs/phase2e-m6-measured-campaign-report.md",
        "configs/phase2/phase2e-workload-distribution-v1.json",
        "src/kvopt/workload/phase2e_materialize.py",
        "src/kvopt/workload/phase2e_runner.py",
        "src/kvopt/workload/phase2e_validate.py",
        "src/kvopt/profiling/phase2e_gate.py",
        "src/kvopt/profiling/phase2e_campaign_gate.py",
        "src/kvopt/profiling/phase2e_analysis.py",
    ]
    for relative in repository_files:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
    campaign = tmp_path / "campaign"
    runs = tmp_path / "runs"
    campaign.mkdir()
    runs.mkdir()
    for name in ("manifest.json", "validation.json", "joint-freeze-authorization.json"):
        (campaign / name).write_text("{}\n", encoding="utf-8")
    for name in ("campaign-gate.json", "measured-analysis.json"):
        (runs / name).write_text("{}\n", encoding="utf-8")
    invalid = runs / "invalid-attempts" / "network-failure"
    invalid.mkdir(parents=True)
    (invalid / "run.json").write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "evidence.tar.gz"

    manifest_path, _ = package_phase2e_evidence(
        repository=repository,
        campaign_root=campaign,
        run_root=runs,
        archive_path=archive,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["invalid_attempts_preserved"] is True
    with tarfile.open(archive, "r:gz") as evidence:
        names = evidence.getnames()
    assert "artifacts/runs/invalid-attempts/network-failure/run.json" in names
    assert "evidence/evidence-manifest.json" in names
