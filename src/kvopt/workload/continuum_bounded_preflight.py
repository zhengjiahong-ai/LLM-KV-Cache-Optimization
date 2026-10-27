"""Run the bounded campaign resource and exact-token preflight on target CUDA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .continuum_bounded_campaign import _selected_calls
from .phase2b_fidelity import token_ids_sha256

MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
REQUESTED_KV_BLOCKS = 2048


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def run_preflight(*, source_freeze_path: Path, output_path: Path) -> dict[str, Any]:
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    import torch
    import vllm
    from vllm import LLM, SamplingParams

    source = _load(source_freeze_path)
    sessions = [session for group in source["groups"] for session in group["sessions"]]
    calls_by_session = {session["instance_id"]: _selected_calls(session) for session in sessions}
    all_calls = [call for calls in calls_by_session.values() for call in calls]
    longest = max(all_calls, key=lambda row: len(row["submitted_token_ids"]))
    longest_tokens = list(longest["submitted_token_ids"])
    if len(longest_tokens) != 32154:
        raise ValueError("frozen longest request is not 32,154 tokens")
    g01 = source["groups"][0]
    dual_tokens = [
        list(calls_by_session[session["instance_id"]][-2]["submitted_token_ids"])
        for session in g01["sessions"]
    ]
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    properties = torch.cuda.get_device_properties(0)
    device_name = torch.cuda.get_device_name(0)
    if "4090" not in device_name:
        raise RuntimeError(f"preflight requires the bound RTX 4090D, observed {device_name}")

    started = time.perf_counter()
    engine_started = time.perf_counter()
    llm = LLM(
        model=MODEL,
        revision=REVISION,
        tokenizer=MODEL,
        tokenizer_revision=REVISION,
        enable_prefix_caching=True,
        gpu_memory_utilization=0.8,
        seed=20261121,
        num_gpu_blocks_override=REQUESTED_KV_BLOCKS,
        max_model_len=32768,
        max_num_batched_tokens=2048,
        enable_chunked_prefill=True,
        enforce_eager=True,
        disable_log_stats=False,
        prefix_caching_hash_algo="sha256",
    )
    engine_initialization_seconds = time.perf_counter() - engine_started
    sampling = SamplingParams(max_tokens=1, temperature=0.0, seed=20261121)
    try:
        longest_started = time.perf_counter()
        longest_ids = tuple(
            llm.enqueue(
                [{"prompt_token_ids": longest_tokens}], sampling, use_tqdm=False
            )
        )
        longest_outputs = tuple(llm.wait_for_completion(use_tqdm=False))
        longest_seconds = time.perf_counter() - longest_started
        if len(longest_ids) != 1 or len(longest_outputs) != 1:
            raise RuntimeError("longest-request preflight completion mismatch")

        dual_started = time.perf_counter()
        dual_ids = tuple(
            llm.enqueue(
                [{"prompt_token_ids": tokens} for tokens in dual_tokens],
                sampling,
                use_tqdm=False,
            )
        )
        dual_outputs = tuple(llm.wait_for_completion(use_tqdm=False))
        dual_seconds = time.perf_counter() - dual_started
        if len(dual_ids) != 2 or len(dual_outputs) != 2:
            raise RuntimeError("two-session preflight completion mismatch")
    finally:
        engine = getattr(llm, "llm_engine", None)
        shutdown = getattr(engine, "shutdown", None)
        if callable(shutdown):
            shutdown()
    result = {
        "schema_version": "continuum.native_costaware_bounded_preflight.v1",
        "status": "PASS",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "source_freeze_path": str(source_freeze_path.resolve()),
        "source_freeze_sha256": hashlib.sha256(source_freeze_path.read_bytes()).hexdigest(),
        "model": MODEL,
        "model_revision": REVISION,
        "tokenizer": MODEL,
        "tokenizer_revision": REVISION,
        "vllm_version": vllm.__version__,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "gpu_name": device_name,
        "gpu_total_memory_bytes": int(properties.total_memory),
        "gpu_memory_utilization": 0.8,
        "available_kv_blocks": REQUESTED_KV_BLOCKS,
        "max_model_len": 32768,
        "max_num_batched_tokens": 2048,
        "longest_request": {
            "request_id": longest["request_id"],
            "token_count": len(longest_tokens),
            "submitted_token_ids_sha256": token_ids_sha256(longest_tokens),
            "completed": True,
            "wall_elapsed_seconds": longest_seconds,
        },
        "two_session_check": {
            "request_count": 2,
            "token_counts": [len(tokens) for tokens in dual_tokens],
            "peak_submitted_before_wait": 2,
            "completed": True,
            "wall_elapsed_seconds": dual_seconds,
        },
        "engine_initialization_seconds": engine_initialization_seconds,
        "wall_elapsed_seconds": time.perf_counter() - started,
        "claim_boundary": (
            "RESOURCE_AND_EXACT_TOKEN_EXECUTION_ONLY; final Native fidelity is "
            "checked with the measured Profile before authorization"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_preflight(
        source_freeze_path=args.source_freeze, output_path=args.output
    )
    print(
        f"preflight {result['status']}: {result['gpu_name']}, "
        f"{result['available_kv_blocks']} blocks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
