"""Execute one Phase 2E measured run only after an immutable joint freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .phase2d_e2_runner import _run_phase2d_stage


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorize_config(config_path: Path, authorization_path: Path) -> dict[str, object]:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if authorization.get("schema_version") != "phase2e.joint_freeze.v1":
        raise ValueError("unsupported Phase 2E joint freeze record")
    if authorization.get("joint_freeze_complete") is not True:
        raise ValueError("Phase 2E joint freeze is incomplete")
    if authorization.get("measured_campaign_authorized") is not True:
        raise ValueError("Phase 2E measured campaign is not authorized")
    allowed = authorization.get("authorized_config_sha256")
    if not isinstance(allowed, list) or _sha(config_path) not in allowed:
        raise ValueError("config is not bound by the joint freeze record")
    campaign_path = Path(str(authorization.get("campaign_manifest_path")))
    if not campaign_path.is_absolute():
        campaign_path = authorization_path.parent / campaign_path
    if not campaign_path.is_file() or _sha(campaign_path) != authorization.get(
        "campaign_manifest_sha256"
    ):
        raise ValueError("authorized campaign manifest hash mismatch")
    repository = Path(__file__).parents[3]
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_sha != authorization.get("git_sha"):
        raise ValueError("runtime code SHA does not match the joint freeze record")
    bindings = authorization.get("bindings")
    if not isinstance(bindings, dict):
        raise TypeError("joint freeze record lacks code bindings")
    required = {
        "runner": repository / "src/kvopt/workload/phase2e_runner.py",
        "gate_c_evaluator": repository / "src/kvopt/profiling/phase2e_gate.py",
        "campaign_evaluator": repository
        / "src/kvopt/profiling/phase2e_campaign_gate.py",
    }
    for name, path in required.items():
        binding = bindings.get(name)
        if not isinstance(binding, dict) or binding.get("sha256") != _sha(path):
            raise ValueError(f"{name} hash does not match the joint freeze record")
    return authorization


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    authorize_config(args.config.resolve(), args.authorization.resolve())
    output = _run_phase2d_stage(
        args.config,
        output_root=args.output_root,
        run_id=args.run_id,
        expected_stage="MEASURED",
        stage_field="phase2e_stage",
        run_kind="NON_HOLDOUT_RESEARCH_DISCOVERY",
        schema_namespace="phase2e",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
