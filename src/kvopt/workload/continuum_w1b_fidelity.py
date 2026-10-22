"""Materialize, execute, and evaluate the W1-B exact-token Native fidelity fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .phase2d_e2_runner import _run_phase2d_stage

STAGE = "W1B_NATIVE_FIDELITY"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def materialize(*, freeze_path: Path, output_dir: Path) -> Path:
    freeze = _load(freeze_path)
    if freeze.get("schema_version") != "continuum.w1b_native_smoke_freeze.v1":
        raise ValueError("unsupported W1-B smoke freeze")
    if freeze.get("native_fidelity_status") != "PENDING":
        raise ValueError("W1-B Native fidelity must still be pending")
    source_path = Path(str(freeze["source_replay_manifest"]))
    if _sha256(source_path) != freeze.get("source_replay_manifest_sha256"):
        raise ValueError("W1-B source replay manifest binding changed")
    source = _load(source_path)
    session_binding = next(
        row for row in source["sessions"] if row["session_id"] == "astropy__astropy-13236"
    )
    session_path = source_path.parent / session_binding["path"]
    if _sha256(session_path) != session_binding["sha256"]:
        raise ValueError("W1-B fidelity source session binding changed")
    session = _load(session_path)
    if session.get("completion_status") != "OBSERVED_COMPLETE":
        raise ValueError("W1-B fidelity fixture requires the natural-completion control")
    requests = session["requests"]
    token_map = {row["request_id"]: row["token_ids"] for row in requests}
    reusable_max = max(len(values) // 16 * 16 for values in token_map.values())
    pressure_tokens = 512
    block_override = reusable_max // 16 + pressure_tokens // 16
    output_dir.mkdir(parents=True, exist_ok=False)
    trace = {
        "schema_version": "phase2.trace.v1",
        "trace_id": "continuum-w1b-native-fidelity-v1",
        "requests": [
            {
                "program_id": session["session_id"],
                "request_id": row["request_id"],
                "turn_index": row["turn_index"],
                "planned_arrival_offset_seconds": float(row["turn_index"] - 1),
                "prompt": "w1b-exact-token-input-is-bound-in-backend-options",
                "prefix_prompt": "",
                "is_terminal": row["turn_index"] == len(requests),
                "next_tool_type": (
                    None if row["turn_index"] == len(requests) else "w1b-frozen-tool-gap"
                ),
                "tool_gap_seconds": None if row["turn_index"] == len(requests) else 0.0,
            }
            for row in requests
        ],
        "pressure_stages": [],
    }
    trace_path = output_dir / "trace.json"
    _write(trace_path, trace)
    runtime = freeze["runtime"]
    config = {
        "schema_version": "phase2.config.v1",
        "runtime_mode": "vllm-metal-observability",
        "backend_factory": (
            "scripts.spikes.phase2_minimal_observability_metal:"
            "build_phase2_metal_observability_backend"
        ),
        "backend_revision": "continuum-w1b-native-fidelity-v1",
        "campaign_kind": "continuum_w1b_native_smoke",
        "policy": "continuum-a0",
        "seed": runtime["seed"],
        "observe": True,
        "model": {"name": runtime["model"], "revision": runtime["model_revision"]},
        "tokenizer": {
            "name": runtime["tokenizer"],
            "revision": runtime["tokenizer_revision"],
        },
        "generation": {
            "max_new_tokens": runtime["max_new_tokens"],
            "temperature": runtime["temperature"],
        },
        "batching": {"max_concurrent_requests": 1},
        "cache": {"block_size": 16, "block_override": block_override},
        "pressure": {
            "initial_shortage_blocks": 1,
            "required_blocks": pressure_tokens // 16,
            "safety_ceiling": 1,
        },
        "backend_options": {
            "execute_planned_timing": False,
            "executor_mode": "submit_collect",
            "gpu_memory_utilization": 0.8,
            "continuum_w1b_replay_mode": True,
            "replay_token_ids_by_request": token_map,
            "program_prefix_tokens": {session["session_id"]: reusable_max},
            "pressure_prompt_tokens": pressure_tokens,
            "phase2g_release_policy": "A0",
            "phase2g_block_policy": "A0",
            "capture_terminal_prefix_snapshot": True,
            "prefill_profile_path": (
                "docs/experiments/phase1b-continuum/artifacts/"
                "prefill-reload-profile-formal-20260920T045859Z-6183d106.json"
            ),
        },
        "trace": "trace.json",
        "continuum_w1b_stage": {
            "stage": STAGE,
            "case_id": "natural-completion-exact-token-chain",
            "repeat": 1,
            "source_session_sha256": session_binding["sha256"],
        },
    }
    config_path = output_dir / "config.json"
    _write(config_path, config)
    manifest = {
        "schema_version": "continuum.w1b_native_fidelity_fixture.v1",
        "freeze_sha256": _sha256(freeze_path),
        "source_session_sha256": session_binding["sha256"],
        "trace": "trace.json",
        "trace_sha256": _sha256(trace_path),
        "config": "config.json",
        "config_sha256": _sha256(config_path),
        "expected_request_digests": {
            row["request_id"]: row["token_ids_sha256"] for row in requests
        },
        "expected_token_counts": {row["request_id"]: row["token_count"] for row in requests},
        "comparison_claim_authorized": False,
    }
    path = output_dir / "manifest.json"
    _write(path, manifest)
    return path


def run(config_path: Path, *, output_root: Path, run_id: str) -> Path:
    return _run_phase2d_stage(
        config_path,
        output_root=output_root,
        run_id=run_id,
        expected_stage=STAGE,
        stage_field="continuum_w1b_stage",
        run_kind="W1B_NATIVE_INPUT_FIDELITY",
        schema_namespace="continuum.w1b",
        required_content_mode="continuum_w1b_replay_mode",
    )


def evaluate(*, fixture_path: Path, run_dir: Path, output_path: Path) -> dict[str, Any]:
    fixture = _load(fixture_path)
    run_manifest = _load(run_dir / "run.json")
    expected = fixture["expected_request_digests"]
    expected_counts = fixture["expected_token_counts"]
    materialized: dict[str, dict[str, Any]] = {}
    native: dict[str, dict[str, Any]] = {}
    indexes: dict[tuple[str, str], int] = {}
    with (run_dir / "events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            event_type = event.get("event_type")
            request_id = event.get("request_id")
            if request_id not in expected:
                continue
            if event_type == "BACKEND_INPUT_MATERIALIZED":
                materialized[request_id] = event["payload"]
                indexes[(request_id, "materialized")] = event["event_index"]
            elif event_type == "VLLM_NATIVE_REQUEST_OBSERVATION":
                native[request_id] = event["payload"]
                indexes[(request_id, "native")] = event["event_index"]
    rows = []
    for request_id, digest in expected.items():
        before = materialized.get(request_id)
        observation = native.get(request_id)
        passed = bool(
            before
            and observation
            and before.get("submitted_token_ids_sha256") == digest
            and before.get("token_count") == expected_counts[request_id]
            and before.get("w1b_replay_input_equivalence")
            == "EXACT_TOKEN_SEQUENCE_SUBMITTED"
            and observation.get("native_prompt_tokens") == expected_counts[request_id]
            and indexes[(request_id, "materialized")] < indexes[(request_id, "native")]
        )
        rows.append({"request_id": request_id, "pass": passed})
    passed = run_manifest.get("execution_status") == "success" and all(
        row["pass"] for row in rows
    )
    report = {
        "schema_version": "continuum.w1b_native_fidelity_report.v1",
        "fixture_sha256": _sha256(fixture_path),
        "run_manifest_sha256": _sha256(run_dir / "run.json"),
        "event_sha256": _sha256(run_dir / "events.jsonl"),
        "requests": rows,
        "request_count": len(rows),
        "native_input_equivalence": "PASS" if passed else "FAIL",
        "comparison_claim_authorized": False,
        "verdict": "PASS_NATIVE_INPUT_FIDELITY_ONLY" if passed else "FAIL",
    }
    _write(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("materialize")
    create.add_argument("--freeze", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--config", type=Path, required=True)
    execute.add_argument("--output-root", type=Path, required=True)
    execute.add_argument("--run-id", required=True)
    review = sub.add_parser("evaluate")
    review.add_argument("--fixture", type=Path, required=True)
    review.add_argument("--run-dir", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        path = materialize(freeze_path=args.freeze, output_dir=args.output_dir)
        print(f"wrote W1-B Native fidelity fixture: {path}")
        return 0
    if args.command == "run":
        output = run(args.config, output_root=args.output_root, run_id=args.run_id)
        status = _load(output / "run.json")["execution_status"]
        print(f"{status}: {output}")
        return 0 if status == "success" else 1
    report = evaluate(fixture_path=args.fixture, run_dir=args.run_dir, output_path=args.output)
    print(f"W1-B Native fidelity: {report['verdict']} -> {args.output}")
    return 0 if report["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
