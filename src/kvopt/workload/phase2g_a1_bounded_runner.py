"""Execute one hash-authorized Phase 2G A1 bounded native run."""

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


def authorize_config(
    config_path: Path,
    authorization_path: Path,
) -> dict[str, object]:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if authorization.get("schema_version") != "phase2g.a1_bounded_authorization.v1":
        raise ValueError("unsupported Phase 2G A1 bounded authorization")
    if authorization.get("gate1_status") != "PASS":
        raise ValueError("Phase 2G A1 Gate 1 has not passed")
    if authorization.get("bounded_campaign_authorized") is not True:
        raise ValueError("Phase 2G A1 bounded campaign is not authorized")
    allowed = authorization.get("authorized_config_sha256")
    if not isinstance(allowed, list) or _sha(config_path) not in allowed:
        raise ValueError("config is not bound by the bounded authorization record")
    manifest_path = Path(str(authorization.get("campaign_manifest_path")))
    if not manifest_path.is_absolute():
        manifest_path = authorization_path.parent / manifest_path
    if not manifest_path.is_file() or _sha(manifest_path) != authorization.get(
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
        raise ValueError("runtime code SHA does not match bounded authorization")
    if authorization.get("git_dirty") is not False:
        raise ValueError("bounded authorization was not created from a clean tree")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("dirty working tree is not authorized")
    bindings = authorization.get("bindings")
    if not isinstance(bindings, dict):
        raise TypeError("bounded authorization lacks code bindings")
    required = {
        "materializer": repository / "src/kvopt/workload/phase2g_a1_bounded_materialize.py",
        "validator": repository / "src/kvopt/workload/phase2g_a1_bounded_validate.py",
        "runner": repository / "src/kvopt/workload/phase2g_a1_bounded_runner.py",
        "campaign_evaluator": repository / "src/kvopt/profiling/phase2g_a1_bounded_gate.py",
    }
    for name, path in required.items():
        binding = bindings.get(name)
        if (
            not path.is_file()
            or not isinstance(binding, dict)
            or binding.get("sha256") != _sha(path)
        ):
            raise ValueError(f"{name} hash does not match bounded authorization")
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
        expected_stage="A1_BOUNDED",
        stage_field="phase2g_stage",
        run_kind="A1_BOUNDED_NATIVE_EVALUATION",
        schema_namespace="phase2g",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
