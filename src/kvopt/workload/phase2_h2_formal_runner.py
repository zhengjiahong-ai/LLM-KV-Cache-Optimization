"""Execute authorized formal H2 M1 measurements in isolated processes."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from .phase2_h2_calibration_runner import _run_isolated


def execute_formal_m1(campaign_path: Path, authorization_path: Path,
                      output: Path, *, resume: bool = False) -> tuple[dict, Path]:
    campaign_path = campaign_path.resolve()
    campaign = json.loads(campaign_path.read_text())
    authorization = json.loads(authorization_path.read_text())
    if campaign.get("schema_version") != "phase2a.h2_formal_m1_campaign.v1":
        raise ValueError("unsupported formal M1 campaign")
    if authorization.get("formal_h2_measurement_authorized") is not True:
        raise ValueError("formal H2 measurement is not authorized")
    authorization_sha = hashlib.sha256(authorization_path.read_bytes()).hexdigest()
    if campaign.get("authorization_sha256") != authorization_sha:
        raise ValueError("campaign authorization hash mismatch")
    if campaign.get("formal_measurement") is not True:
        raise ValueError("campaign must declare formal measurement")
    if campaign.get("formal_verdict_authorized") is not False:
        raise ValueError("formal verdict must await validation")
    frozen = {p["prefix_tokens"]: p for p in authorization["m1_execution_configurations"]}
    points = campaign["points"]
    if [p["prefix_tokens"] for p in points] != list(frozen):
        raise ValueError("formal M1 point grid mismatch")
    selected = []
    seen = set()
    for point in points:
        config_path = (campaign_path.parent / point["config"]).resolve()
        if config_path.parent != campaign_path.parent:
            raise ValueError("configuration must be inside campaign directory")
        config = json.loads(config_path.read_text())
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
        expected = frozen[point["prefix_tokens"]]["config_sha256"]
        if hashlib.sha256(encoded).hexdigest() != expected:
            raise ValueError("formal configuration differs from authorization")
        trace_path = (config_path.parent / config["trace"]).resolve()
        if trace_path.parent != campaign_path.parent:
            raise ValueError("trace must be inside campaign directory")
        if hashlib.sha256(trace_path.read_bytes()).hexdigest() != point["trace_sha256"]:
            raise ValueError("formal trace hash mismatch")
        runs = point["runs"]
        if [r["role"] for r in runs] != ["warmup"] * 2 + ["measured"] * 9:
            raise ValueError("formal repetitions must be 2 warmups and 9 measured")
        for run in runs:
            run_id = run["run_id"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
                raise ValueError("unsafe formal run ID")
            if run_id in seen:
                raise ValueError("duplicate formal run ID")
            seen.add(run_id)
            selected.append((config_path, point, run))
    if len(selected) != 187:
        raise ValueError("formal M1 requires 187 runs")
    git = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           check=True, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise ValueError("commit tracked changes before formal execution")
    output = output.resolve()
    if not resume and any((output / run["run_id"]).exists() for _, _, run in selected):
        raise FileExistsError("formal run already exists; use resume for validated successes")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (config_path, point, run) in enumerate(selected, 1):
        run_id = run["run_id"]
        directory = output / run_id
        existing = directory.exists()
        if not existing:
            directory = _run_isolated(config_path, output, run_id)
        manifest = json.loads((directory / "run.json").read_text())
        if manifest.get("status") != "success":
            raise ValueError(f"formal run failed; preserve evidence: {run_id}")
        if manifest.get("git_sha") != git or manifest.get("git_dirty") is not False:
            raise ValueError(f"formal run code provenance mismatch: {run_id}")
        if manifest.get("config_sha256") != point["runtime_config_sha256"]:
            raise ValueError(f"formal run config provenance mismatch: {run_id}")
        if manifest.get("trace_sha256") != point["trace_sha256"]:
            raise ValueError(f"formal run trace provenance mismatch: {run_id}")
        results.append({**run, "status": "skipped_existing" if existing else "success"})
        print(f"[{index}/187] {run_id}: {results[-1]['status']}", flush=True)
    summary = {"schema_version": "phase2a.h2_formal_m1_execution.v1",
               "git_sha": git, "authorization_sha256": authorization_sha,
               "campaign_sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(),
               "formal_measurement": True, "formal_verdict_authorized": False,
               "successful_run_count": sum(r["status"] == "success" for r in results),
               "skipped_run_count": sum(r["status"] == "skipped_existing" for r in results),
               "results": results}
    path = output / f"formal-m1-execution-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary, path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(VLLM_ENABLE_V1_MULTIPROCESSING="0", VLLM_METAL_USE_PAGED_ATTENTION="1",
                      VLLM_METAL_MEMORY_FRACTION="auto", VLLM_MLX_DEVICE="gpu",
                      VLLM_HOST_IP="127.0.0.1",
                      VLLM_METAL_SOURCE_CHECKOUT=str(args.vllm_metal_source_checkout.resolve()))
    summary, path = execute_formal_m1(args.campaign, args.authorization,
                                    args.output_root, resume=args.resume)
    print(f"formal H2 M1 complete: {summary['successful_run_count']} success, "
          f"{summary['skipped_run_count']} skipped -> {path}")
