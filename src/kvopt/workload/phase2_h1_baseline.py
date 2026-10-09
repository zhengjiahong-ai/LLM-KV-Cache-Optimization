"""Materialize and execute the frozen five-repeat H1 latency baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .phase2_h2_calibration_runner import execute_h2_calibration_pilot
from .phase2_level_b_validation import _config, _trace, seam_validation_specs


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def materialize_h1_baseline_campaign(
    base_config_path: str | Path,
    output_dir: str | Path,
) -> Path:
    """Create five identical S2 runs without authorizing holdout outcomes."""
    base = json.loads(Path(base_config_path).read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise TypeError("base config must be an object")
    spec = next(item for item in seam_validation_specs() if item.case_id.startswith("s2-"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    trace_text = json.dumps(_trace(spec).to_dict(), indent=2, sort_keys=True) + "\n"
    config = _config(spec, base)
    config["campaign_kind"] = "h1_identical_baseline_calibration"
    config["trace"] = "baseline.trace.json"
    config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
    (output / "baseline.trace.json").write_text(trace_text, encoding="utf-8")
    (output / "baseline.config.json").write_text(config_text, encoding="utf-8")
    runs = [
        {"run_id": f"h1-identical-baseline-{index}", "role": "measured"} for index in range(1, 6)
    ]
    campaign = {
        "schema_version": "phase2a.h2_calibration_pilot.v1",
        "campaign_id": "phase2a-h1-identical-baseline-v1",
        "campaign_kind": "h1_latency_baseline_calibration",
        "formal_measurement": False,
        "formal_verdict": False,
        "formal_h1_outcome_execution_authorized": False,
        "target_request_id": "agent-a:turn:2",
        "expected_apc_outcome": "FULL_HIT",
        "primary_metric": "backend_service_e2e_seconds",
        "epsilon_rule": "max_absolute_deviation_from_baseline_mean",
        "identical_baseline_repeats": 5,
        "config_sha256": _sha256(config_text),
        "trace_sha256": _sha256(trace_text),
        "points": [
            {
                "prefix_tokens": spec.prefix_tokens,
                "config": "baseline.config.json",
                "runs": runs,
            }
        ],
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(campaign, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--base-config", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--campaign", type=Path, required=True)
    execute.add_argument("--output-root", type=Path, required=True)
    execute.add_argument("--resume", action="store_true")
    execute.add_argument("--vllm-metal-source-checkout", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "materialize":
        path = materialize_h1_baseline_campaign(arguments.base_config, arguments.output)
        print(f"wrote H1 identical-baseline campaign: {path.resolve()}")
        return 0
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    if arguments.vllm_metal_source_checkout is not None:
        os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(
            arguments.vllm_metal_source_checkout.resolve()
        )
    summary, path = execute_h2_calibration_pilot(
        arguments.campaign, arguments.output_root, resume=arguments.resume
    )
    print(
        "H1 identical baseline: "
        f"{summary['successful_run_count']} success, "
        f"{summary['failed_run_count']} failed, "
        f"{summary['skipped_run_count']} skipped -> {path}"
    )
    return 0 if summary["failed_run_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
