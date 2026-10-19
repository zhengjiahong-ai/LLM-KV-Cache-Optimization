"""Execute Gate 2 only after validating the independent M1 authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from kvopt.profiling.phase2g_a2_gate2 import _validate_execution_authorization
from .phase2d_e2_runner import _run_phase2d_stage


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorize_campaign(manifest_path: Path, authorization_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    manifest_path = manifest_path.resolve()
    authorization_path = authorization_path.resolve()
    authorization = _validate_execution_authorization(
        manifest_path=manifest_path,
        authorization_path=authorization_path,
    )
    repository = Path(__file__).parents[3].resolve()
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if current_sha != authorization["experiment_tooling_git_sha"]:
        raise ValueError("runtime code SHA does not match Gate 2 authorization")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("dirty working tree is not authorized")

    root = manifest_path.parent
    for row in manifest["runs"]:
        config_path = (root / str(row["config"])).resolve()
        trace_path = (root / str(row["trace"])).resolve()
        if root not in config_path.parents or root not in trace_path.parents:
            raise ValueError("config/trace path escapes the frozen campaign directory")
        if not config_path.is_file() or _sha(config_path) != row["config_sha256"]:
            raise ValueError(f"config hash mismatch before execution: {row['run_id']}")
        if not trace_path.is_file() or _sha(trace_path) != row["trace_sha256"]:
            raise ValueError(f"trace hash mismatch before execution: {row['run_id']}")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("phase2g_stage", {}).get("scenario_id") != row["scenario_id"]:
            raise ValueError(f"scenario binding mismatch before execution: {row['run_id']}")
        if config.get("phase2g_stage", {}).get("policy") != row["policy"]:
            raise ValueError(f"policy binding mismatch before execution: {row['run_id']}")
        if config.get("phase2g_stage", {}).get("repeat") != row["repeat"]:
            raise ValueError(f"repeat binding mismatch before execution: {row['run_id']}")
    return manifest, authorization


def run_campaign(
    *, manifest_path: Path, authorization_path: Path, output_root: Path
) -> list[Path]:
    manifest, _authorization = authorize_campaign(manifest_path, authorization_path)
    root = manifest_path.resolve().parent
    output_root = output_root.resolve()
    outputs: list[Path] = []
    # Validate the entire campaign before starting the first native process.
    for row in manifest["runs"]:
        config = root / str(row["config"])
        output = _run_phase2d_stage(
            config,
            output_root=output_root,
            run_id=str(row["run_id"]),
            expected_stage="A2_GATE2_PREPARATION",
            stage_field="phase2g_stage",
            run_kind="PHASE2G_A2_GATE2_FORMAL_NATIVE",
            schema_namespace="phase2g",
        )
        outputs.append(output)
        run_manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
        if run_manifest.get("execution_status") != "success":
            # Preserve the failed attempt and stop. No silent retry or replacement.
            break
    return outputs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = run_campaign(
        manifest_path=args.manifest,
        authorization_path=args.authorization,
        output_root=args.output_root,
    )
    failed = []
    for output in outputs:
        run_manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
        if run_manifest.get("execution_status") != "success":
            failed.append(output.name)
    print(
        f"completed {len(outputs)} Gate 2 run attempt(s); "
        f"failed={len(failed)}; inspect all run manifests before proceeding"
    )
    return 1 if failed or not outputs else 0


if __name__ == "__main__":
    raise SystemExit(main())
