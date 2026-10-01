"""Run one Phase 2A profiling template across a small seed set."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Sequence

from kvopt.workload.phase2_runner import run_phase2


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=(11, 23, 37))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/phase2a-pilot"))
    parser.add_argument("--run-prefix")
    parser.add_argument("--vllm-metal-source-checkout", type=Path)
    return parser.parse_args(argv)


def _load_template(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("profiling config must be a JSON object")
    trace = value.get("trace")
    if not isinstance(trace, str) or not trace.strip():
        raise ValueError("profiling config trace must be non-empty text")
    trace_path = Path(trace)
    if not trace_path.is_absolute():
        trace_path = (path.parent / trace_path).resolve()
    value["trace"] = str(trace_path)
    return value


def _scenario_id(config: dict[str, object], path: Path) -> str:
    value = config.get("profiling_scenario_id")
    if isinstance(value, str) and value.strip():
        return value
    return path.stem


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = args.config.resolve()
    template = _load_template(config_path)
    scenario = _scenario_id(template, config_path)
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

    failures = 0
    prefix = args.run_prefix or scenario
    for seed in args.seeds:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        concrete = dict(template)
        concrete["seed"] = seed
        run_id = f"{prefix}-seed-{seed}"

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix=".phase2a-pilot-",
                dir=output_root,
                delete=False,
            ) as stream:
                json.dump(concrete, stream, sort_keys=True, allow_nan=False)
                stream.write("\n")
                temp_path = Path(stream.name)

            output = run_phase2(
                temp_path,
                output_root=output_root,
                run_id=run_id,
            )
            manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
            status = manifest.get("status")
            print(f"{scenario} seed={seed}: {status} -> {output}")
            if status != "success":
                failures += 1
                print(f"  failure_reason={manifest.get('failure_reason')}")
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
