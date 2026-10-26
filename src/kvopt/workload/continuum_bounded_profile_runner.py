"""Execute all seven frozen PrefillReload points and assemble one Profile."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .continuum_native_formal_profile import assemble


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def run_profile(
    *, base_config_path: Path, protocol_path: Path, preflight_path: Path,
    output_dir: Path, budget_hours: float,
) -> Path:
    if budget_hours <= 0:
        raise ValueError("budget_hours must be positive")
    protocol = _load(protocol_path)
    preflight = _load(preflight_path)
    if preflight.get("status") != "PASS":
        raise ValueError("target GPU preflight has not passed")
    if preflight.get("model") != protocol["model"]["name"] or preflight.get(
        "model_revision"
    ) != protocol["model"]["revision"]:
        raise ValueError("profile/preflight model binding mismatch")
    if int(preflight["available_kv_blocks"]) < 2048:
        raise ValueError("preflight KV capacity cannot serve the 32,256-token anchor")
    points_dir = output_dir / "points"
    points_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    for token_count in protocol["token_grid"]:
        if (time.monotonic() - started) / 3600.0 >= budget_hours:
            raise RuntimeError("PrefillReload Profile reached its wall-clock budget cap")
        output = points_dir / f"point-{token_count}.json"
        if output.exists():
            raise FileExistsError(f"profile point already exists: {output}")
        environment = os.environ.copy()
        environment["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "kvopt.workload.continuum_w1b_profile_runner",
                "--base-config",
                str(base_config_path.resolve()),
                "--protocol",
                str(protocol_path.resolve()),
                "--token-count",
                str(token_count),
                "--output",
                str(output.resolve()),
            ],
            check=False,
            env=environment,
        )
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError(f"profile point failed and was preserved: {token_count}")
    profile_path = output_dir / "prefill-reload-profile.json"
    if profile_path.exists():
        raise FileExistsError(profile_path)
    assemble(
        protocol_path=protocol_path,
        points_dir=points_dir,
        output_path=profile_path,
    )
    return profile_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budget-hours", type=float, default=12.0)
    args = parser.parse_args()
    output = run_profile(
        base_config_path=args.base_config,
        protocol_path=args.protocol,
        preflight_path=args.preflight,
        output_dir=args.output_dir,
        budget_hours=args.budget_hours,
    )
    print(f"complete bounded PrefillReload Profile: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
