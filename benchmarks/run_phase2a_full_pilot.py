"""Run the full frozen Phase 2A P0-P3 pilot suite."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Sequence

from kvopt.workload.phase2_runner import run_phase2


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        type=Path,
        default=_repo_root() / "configs/phase2/profiling/phase2a-full-suite.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/phase2a-full-pilot"),
    )
    parser.add_argument("--vllm-metal-source-checkout", type=Path)
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _load_suite(path: Path) -> tuple[list[int], list[tuple[str, Path]]]:
    value = _load_json(path)
    if value.get("schema_version") != "phase2a.pilot_suite.v1":
        raise ValueError("unsupported pilot suite schema_version")
    raw_seeds = value.get("seeds")
    raw_scenarios = value.get("scenarios")
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ValueError("suite.seeds must be a non-empty list")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("suite.scenarios must be a non-empty list")

    seeds: list[int] = []
    for seed in raw_seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("suite seeds must be non-negative integers")
        seeds.append(seed)

    scenarios: list[tuple[str, Path]] = []
    for item in raw_scenarios:
        if not isinstance(item, dict):
            raise TypeError("suite scenario must be an object")
        scenario_id = item.get("scenario_id")
        config = item.get("config")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("scenario_id must be non-empty text")
        if not isinstance(config, str) or not config.strip():
            raise ValueError("scenario config must be non-empty text")
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = (path.parent / config_path).resolve()
        scenarios.append((scenario_id, config_path))
    return seeds, scenarios


def _materialize_config(config_path: Path, seed: int, output_root: Path) -> Path:
    config = _load_json(config_path)
    trace = config.get("trace")
    if not isinstance(trace, str) or not trace.strip():
        raise ValueError(f"{config_path}: trace must be non-empty text")
    trace_path = Path(trace)
    if not trace_path.is_absolute():
        trace_path = (config_path.parent / trace_path).resolve()
    config["trace"] = str(trace_path)
    config["seed"] = seed

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix=".phase2a-full-",
        dir=output_root,
        delete=False,
    ) as stream:
        json.dump(config, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        return Path(stream.name)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    suite_path = args.suite.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    if args.vllm_metal_source_checkout is not None:
        os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(
            args.vllm_metal_source_checkout.resolve()
        )

    seeds, scenarios = _load_suite(suite_path)
    failures: list[str] = []
    total = len(seeds) * len(scenarios)

    for scenario_id, config_path in scenarios:
        for seed in seeds:
            run_id = f"{scenario_id}-seed-{seed}"
            temp_path = _materialize_config(config_path, seed, output_root)
            try:
                output = run_phase2(
                    temp_path,
                    output_root=output_root,
                    run_id=run_id,
                )
                manifest = _load_json(output / "run.json")
                status = manifest.get("status")
                print(f"{scenario_id} seed={seed}: {status} -> {output}")
                if status != "success":
                    failures.append(run_id)
                    print(f"  failure_reason={manifest.get('failure_reason')}")
            finally:
                temp_path.unlink(missing_ok=True)

    print(f"full suite complete: {total} runs, {len(failures)} failures")
    if failures:
        print("failed runs:")
        for run_id in failures:
            print(f"  - {run_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
