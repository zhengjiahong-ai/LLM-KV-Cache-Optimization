"""Execute the authorized formal H2 M4 campaign in isolated processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

from .phase2_h2_calibration_runner import _run_isolated
from .phase2_h2_headroom_validation_runner import (
    _events,
    _return_recomputed,
    _validate_block,
    _validate_entry,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute_formal_m4(
    campaign_path: Path,
    authorization_path: Path,
    output: Path,
    *,
    resume: bool = False,
) -> tuple[dict[str, object], Path]:
    campaign_path = campaign_path.resolve()
    campaign = json.loads(campaign_path.read_text())
    authorization_sha = _sha(authorization_path.resolve())
    if campaign.get("schema_version") != "phase2a.h2_formal_m4_campaign.v1":
        raise ValueError("unsupported formal M4 campaign")
    if campaign.get("authorization_sha256") != authorization_sha:
        raise ValueError("formal M4 authorization hash mismatch")
    if (
        campaign.get("formal_measurement") is not True
        or campaign.get("formal_verdict_authorized") is not False
        or campaign.get("b1_authorized") is not False
    ):
        raise ValueError("formal M4 authorization state is invalid")
    probes = campaign.get("probes")
    if not isinstance(probes, list) or len(probes) != 24:
        raise ValueError("formal M4 requires 24 arms")
    selected = []
    seen = set()
    for probe in probes:
        config_path = (campaign_path.parent / str(probe["config"])).resolve()
        if config_path.parent != campaign_path.parent:
            raise ValueError("formal M4 config must remain in campaign directory")
        if _sha(config_path) != probe["config_file_sha256"]:
            raise ValueError("formal M4 config file hash mismatch")
        trace_path = (campaign_path.parent / json.loads(config_path.read_text())["trace"]).resolve()
        if trace_path.parent != campaign_path.parent or _sha(trace_path) != probe["trace_sha256"]:
            raise ValueError("formal M4 trace hash mismatch")
        runs = probe.get("runs")
        roles = ["warmup"] * 2 + ["measured"] * 9
        if not isinstance(runs, list) or [run.get("role") for run in runs] != roles:
            raise ValueError("formal M4 requires 2 warmups and 9 measured runs per arm")
        for run in runs:
            run_id = run.get("run_id")
            if not isinstance(run_id, str) or run_id in seen:
                raise ValueError("formal M4 run IDs must be unique text")
            seen.add(run_id)
            selected.append((config_path, probe, run))
    if len(selected) != 264 or campaign.get("planned_run_count") != 264:
        raise ValueError("formal M4 requires 264 total runs")
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("commit tracked changes before formal M4 execution")
    output = output.resolve()
    if not resume and any((output / str(run["run_id"])).exists() for _, _, run in selected):
        raise FileExistsError("formal M4 output exists; use resume")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (config_path, probe, run) in enumerate(selected, 1):
        run_id = str(run["run_id"])
        directory = output / run_id
        existing = directory.exists()
        if not existing:
            directory = _run_isolated(config_path, output, run_id)
        manifest = json.loads((directory / "run.json").read_text())
        if manifest.get("status") != "success":
            raise ValueError(f"formal M4 run failed; preserve evidence: {run_id}")
        if (
            manifest.get("git_sha") != git_sha
            or manifest.get("git_dirty") is not False
            or manifest.get("config_sha256") != probe["runtime_config_sha256"]
            or manifest.get("trace_sha256") != probe["trace_sha256"]
        ):
            raise ValueError(f"formal M4 provenance mismatch: {run_id}")
        events = _events(directory)
        audit = _validate_entry(events, probe) if probe["arm"] == "entry" else _validate_block(events, probe)
        recomputed = _return_recomputed(events, str(probe["probe_id"]), int(probe["prefix_tokens"]))
        results.append(
            {
                "run_id": run_id,
                "role": run["role"],
                "repeat_index": run["repeat_index"],
                "probe_id": probe["probe_id"],
                "cell_id": probe["cell_id"],
                "arm": probe["arm"],
                "observed_recomputed_tokens": recomputed,
                "physically_selected_prefix_block_count": audit[
                    "physically_selected_prefix_block_count"
                ],
                "status": "skipped_existing" if existing else "success",
            }
        )
        print(f"[{index}/264] {run_id}: {results[-1]['status']}", flush=True)
    summary = {
        "schema_version": "phase2a.h2_formal_m4_execution.v1",
        "git_sha": git_sha,
        "authorization_sha256": authorization_sha,
        "campaign_sha256": _sha(campaign_path),
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "successful_run_count": sum(row["status"] == "success" for row in results),
        "skipped_run_count": sum(row["status"] == "skipped_existing" for row in results),
        "results": results,
    }
    path = output / f"formal-m4-execution-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    arguments = parser.parse_args()
    os.environ.update(
        VLLM_ENABLE_V1_MULTIPROCESSING="0",
        VLLM_METAL_USE_PAGED_ATTENTION="1",
        VLLM_METAL_MEMORY_FRACTION="auto",
        VLLM_MLX_DEVICE="gpu",
        VLLM_HOST_IP="127.0.0.1",
        VLLM_METAL_SOURCE_CHECKOUT=str(arguments.vllm_metal_source_checkout.resolve()),
    )
    summary, path = execute_formal_m4(
        arguments.campaign, arguments.authorization, arguments.output_root,
        resume=arguments.resume,
    )
    print(
        f"formal H2 M4 complete: {summary['successful_run_count']} success, "
        f"{summary['skipped_run_count']} skipped -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
