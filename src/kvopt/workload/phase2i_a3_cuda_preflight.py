"""Materialize and evaluate the authorized Phase 2I A3 CUDA preflight."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

from .phase2_runner import run_phase2
from .phase2i_a3_preflight import evaluate_a3_native_preflight

MODEL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
RUN_ID = "phase2i-a3-target-cuda-native-preflight"
PRESSURE_BOUNDARIES = frozenset(
    {
        "pressure:after-round-40",
        "pressure:after-round-50",
        "pressure:after-round-55",
    }
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_frozen_source(config: dict[str, object], trace: dict[str, object]) -> None:
    backend = config.get("backend_options")
    if not isinstance(backend, dict):
        raise TypeError("source backend_options are missing")
    expected = {
        "campaign_kind": "phase2h_history_rich_native_smoke",
        "runtime_mode": "vllm-cuda-observability",
        "policy": "continuum-a1-entry-native-lru",
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise ValueError(f"source {field} does not match frozen HR02/A1 input")
    if config.get("model") != {
        "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "revision": MODEL_REVISION,
    } or config.get("tokenizer") != {
        "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "revision": MODEL_REVISION,
    }:
        raise ValueError("source model/tokenizer identity is not frozen")
    if config.get("cache") != {"block_override": 2048, "block_size": 16}:
        raise ValueError("source cache geometry is not the frozen 2048-block pool")
    if config.get("pressure") != {
        "initial_shortage_blocks": 128,
        "required_blocks": 379,
        "safety_ceiling": 1,
    }:
        raise ValueError("source HR02 pressure geometry drifted")
    if backend.get("phase2g_release_policy") != "A1" or backend.get(
        "phase2g_block_policy"
    ) != "A0":
        raise ValueError("source must be the frozen HR02/A1 entry arm")
    stages = backend.get("controlled_pressure_stages_by_boundary")
    if not isinstance(stages, dict) or set(stages) != PRESSURE_BOUNDARIES:
        raise ValueError("source pressure barriers drifted")
    requests = trace.get("requests")
    if not isinstance(requests, list) or len(requests) != 180:
        raise ValueError("source trace must contain the frozen 180 requests")
    replay = backend.get("replay_token_ids_by_request")
    submissions = backend.get("expected_native_submission_sha256_by_request")
    if not isinstance(replay, dict) or not isinstance(submissions, dict):
        raise TypeError("source explicit-token bindings are missing")
    if set(replay) != set(submissions) or len(replay) != 180:
        raise ValueError("source explicit-token request membership drifted")
    for request_id, token_ids in replay.items():
        if _canonical_sha(token_ids) != submissions[request_id]:
            raise ValueError(f"explicit-token binding mismatch: {request_id}")


def materialize_preflight(
    *,
    source_config_path: Path,
    source_trace_path: Path,
    profile_path: Path,
    output_dir: Path,
    repository: Path,
) -> dict[str, object]:
    """Derive one A3 run while preserving the frozen HR02 execution inputs."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    source_trace = json.loads(source_trace_path.read_text(encoding="utf-8"))
    if not isinstance(source_config, dict) or not isinstance(source_trace, dict):
        raise TypeError("source config and trace must be JSON objects")
    _validate_frozen_source(source_config, source_trace)
    if not profile_path.is_file():
        raise FileNotFoundError(profile_path)

    output_dir.mkdir(parents=True)
    trace_path = output_dir / "hr02-short-gap-long-context.trace.json"
    trace_path.write_bytes(source_trace_path.read_bytes())
    config = copy.deepcopy(source_config)
    config["campaign_kind"] = "phase2i_a3_native_integration"
    config["backend_revision"] = "phase2i-a3-target-cuda-native-preflight-v1"
    config["policy"] = "continuum-a3-entry-native-lru"
    config["trace"] = trace_path.name
    backend = config["backend_options"]
    assert isinstance(backend, dict)
    backend["phase2g_release_policy"] = "A3"
    backend["prefill_profile_path"] = str(profile_path.resolve())
    config_path = output_dir / f"{RUN_ID}.config.json"
    _write(config_path, config)

    git_sha = _git(repository, "rev-parse", "HEAD")
    if _git(repository, "status", "--porcelain"):
        raise ValueError("execution freeze requires a clean Git worktree")
    manifest = {
        "schema_version": "phase2i.a3_target_cuda_preflight_freeze.v1",
        "execution_authorized": True,
        "authorization_scope": "ONE_TARGET_CUDA_NATIVE_PREFLIGHT_NOT_EFFECT_CAMPAIGN",
        "run_id": RUN_ID,
        "git_sha": git_sha,
        "source": {
            "config_sha256": _sha(source_config_path),
            "trace_sha256": _sha(source_trace_path),
            "profile_sha256": _sha(profile_path),
            "explicit_token_ids_sha256": _canonical_sha(
                backend["replay_token_ids_by_request"]
            ),
            "pressure_token_ids_sha256": _canonical_sha(
                backend["pressure_token_ids_by_stage"]
            ),
            "logical_sequence_sha256": config["controlled_sparse_replay"][
                "logical_sequence_sha256"
            ],
        },
        "derived": {
            "config": config_path.name,
            "config_sha256": _sha(config_path),
            "trace": trace_path.name,
            "trace_sha256": _sha(trace_path),
            "profile_path": str(profile_path.resolve()),
            "profile_sha256": _sha(profile_path),
            "explicit_token_ids_sha256": _canonical_sha(
                backend["replay_token_ids_by_request"]
            ),
            "pressure_token_ids_sha256": _canonical_sha(
                backend["pressure_token_ids_by_stage"]
            ),
            "logical_sequence_sha256": config["controlled_sparse_replay"][
                "logical_sequence_sha256"
            ],
        },
        "frozen": {
            "model_revision": MODEL_REVISION,
            "cache_blocks": 2048,
            "request_count": 180,
            "pressure_boundaries": sorted(PRESSURE_BOUNDARIES),
            "release_policy": "A3",
            "block_policy": "A0",
        },
    }
    _write(output_dir / "freeze-record.json", manifest)
    return manifest


def _verify_freeze(input_dir: Path, repository: Path) -> tuple[dict[str, object], Path]:
    manifest_path = input_dir / "freeze-record.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "phase2i.a3_target_cuda_preflight_freeze.v1":
        raise ValueError("unsupported Phase 2I preflight freeze record")
    if manifest.get("execution_authorized") is not True:
        raise ValueError("Phase 2I target CUDA preflight is not authorized")
    if _git(repository, "rev-parse", "HEAD") != manifest.get("git_sha"):
        raise ValueError("execution Git SHA does not match freeze record")
    if _git(repository, "status", "--porcelain"):
        raise ValueError("execution requires a clean Git worktree")
    derived = manifest.get("derived")
    if not isinstance(derived, dict):
        raise TypeError("freeze record derived bindings are missing")
    config_path = input_dir / str(derived["config"])
    trace_path = input_dir / str(derived["trace"])
    profile_path = Path(str(derived["profile_path"]))
    for path, field in (
        (config_path, "config_sha256"),
        (trace_path, "trace_sha256"),
        (profile_path, "profile_sha256"),
    ):
        if not path.is_file() or _sha(path) != derived.get(field):
            raise ValueError(f"freeze binding mismatch: {field}")
    return manifest, config_path


def _environment() -> dict[str, object]:
    import torch
    import vllm

    nvidia_smi = subprocess.run(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "vllm": vllm.__version__,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "gpu_memory_bytes": (
            torch.cuda.get_device_properties(0).total_memory
            if torch.cuda.is_available()
            else None
        ),
        "nvidia_smi_query": (
            nvidia_smi.stdout.strip() if nvidia_smi.returncode == 0 else None
        ),
        "nvidia_smi_error": (
            None if nvidia_smi.returncode == 0 else nvidia_smi.stderr.strip()
        ),
    }


def _write_sha_manifest(root: Path) -> Path:
    manifest = root / "sha256-manifest.txt"
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == manifest:
            continue
        rows.append(f"{_sha(path)}  {path.relative_to(root)}")
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return manifest


def run_preflight(
    *, input_dir: Path, output_root: Path, repository: Path
) -> dict[str, object]:
    """Run once and independently evaluate persisted CUDA Native evidence."""
    freeze, config_path = _verify_freeze(input_dir, repository)
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    _write(output_root / "freeze-record.json", freeze)
    environment = _environment()
    if environment["cuda_available"] is not True:
        raise RuntimeError("target CUDA preflight requires an available CUDA GPU")
    _write(output_root / "environment.json", environment)
    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    started = time.perf_counter()
    run_path = run_phase2(
        config_path,
        output_root=output_root / "runs",
        run_id=RUN_ID,
    )
    wall_seconds = time.perf_counter() - started
    run_manifest = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    events = tuple(
        json.loads(line)
        for line in (run_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    static_report = evaluate_a3_native_preflight(
        events, require_a1_a3_intervention=False
    )
    gates = static_report["gates"]
    passed = run_manifest.get("status") == "success" and all(
        gate.get("status") == "PASS" for gate in gates.values()
    )
    a3_events = [row for row in events if row.get("event_type") == "A3_SUFFIX_RELEASE_DECISION"]
    non_fallback = sum(
        1
        for event in a3_events
        for selection in event.get("payload", {}).get("selection_trace", ())
        if selection.get("fell_back") is not True
    )
    report = {
        "schema_version": "phase2i.a3_target_cuda_native_preflight.v1",
        "status": "PASS_NATIVE_PREFLIGHT" if passed else "FAIL_CLOSED",
        "claim_scope": "ONE_TARGET_CUDA_NATIVE_PREFLIGHT_NOT_EFFECT_CAMPAIGN",
        "run_status": run_manifest.get("status"),
        "git_sha": freeze["git_sha"],
        "gates": gates,
        "a3_decision_event_count": len(a3_events),
        "a3_non_fallback_selection_count": non_fallback,
        "wall_elapsed_seconds": wall_seconds,
        "missingness": {
            "physical_eviction_unattributed_count": sum(
                1
                for row in events
                if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
                and row.get("payload", {}).get("physical_attribution")
                != "MATCHED_PENDING_SELECTION_PLAN"
            ),
            "right_censoring_preserved": True,
        },
    }
    _write(output_root / "native-preflight-report.json", report)
    _write_sha_manifest(output_root)
    if not passed:
        raise RuntimeError("Phase 2I target CUDA Native preflight failed closed")
    return report
