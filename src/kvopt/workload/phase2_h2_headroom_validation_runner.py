"""Execute and audit the non-formal H2 M4 comparator validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

from .phase2_h2_calibration_runner import _run_isolated


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(directory: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _return_recomputed(
    events: list[dict[str, object]], probe_id: str, prefix_tokens: int
) -> int:
    matches = [
        event for event in events
        if event.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
        and event.get("request_id") == f"{probe_id}:turn:2"
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
        raise ValueError("M4 validation lacks one native return observation")
    payload = matches[0]["payload"]
    cached = payload.get("native_cached_prefix_tokens")
    if payload.get("native_prompt_tokens") != prefix_tokens + 1:
        raise ValueError("M4 validation return prompt shape differs")
    if isinstance(cached, bool) or not isinstance(cached, int):
        raise TypeError("M4 validation lacks native cached-prefix amount")
    return prefix_tokens - cached


def _validate_entry(
    events: list[dict[str, object]], probe: dict[str, object]
) -> dict[str, object]:
    probe_id = str(probe["probe_id"])
    snapshots = [
        event for event in events
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
        and event.get("request_id") == f"{probe_id}:turn:1"
    ]
    decisions = [event for event in events if event.get("event_type") == "FORCED_RELEASE_DECISION"]
    completions = [
        event for event in events if event.get("event_type") == "PRESSURE_REQUEST_COMPLETED"
    ]
    if len(snapshots) != 1 or len(decisions) != 1 or len(completions) != 1:
        raise ValueError("entry path lacks one snapshot, forced release, and pressure completion")
    snapshot_payload = snapshots[0].get("payload")
    decision_payload = decisions[0].get("payload")
    completion_payload = completions[0].get("payload")
    if not all(isinstance(value, dict) for value in (
        snapshot_payload, decision_payload, completion_payload
    )):
        raise TypeError("entry-path evidence payload is invalid")
    prefix_ids = set(snapshot_payload["block_ids"])  # type: ignore[index]
    selected_releases = decision_payload.get("selected_releases")  # type: ignore[union-attr]
    if not isinstance(selected_releases, list) or len(selected_releases) != 1:
        raise ValueError("entry path must logically release exactly one prefix")
    selected = completion_payload.get("last_selected_block_ids")  # type: ignore[union-attr]
    if not isinstance(selected, list):
        raise TypeError("entry path lacks native selected block IDs")
    selected_prefix_ids = [block_id for block_id in selected if block_id in prefix_ids]
    expected = int(probe["evicted_blocks"])
    if len(selected_prefix_ids) != expected:
        raise ValueError("entry path did not physically select the frozen block count")
    queue = decision_payload.get("original_free_queue")  # type: ignore[union-attr]
    if not isinstance(queue, list):
        raise TypeError("entry path lacks native LRU queue snapshot")
    ranks = {
        row.get("block_id"): row.get("native_lru_rank")
        for row in queue if isinstance(row, dict)
    }
    if any(block_id not in ranks for block_id in selected_prefix_ids):
        raise ValueError("entry path selected block lacks native LRU rank")
    return {
        "logical_release_count": 1,
        "physically_selected_prefix_block_count": len(selected_prefix_ids),
        "selected_prefix_block_ids": selected_prefix_ids,
        "selected_native_lru_ranks": [ranks[block_id] for block_id in selected_prefix_ids],
        "native_ownership_basis": "single_prefix_snapshot_membership",
    }


def _validate_block(
    events: list[dict[str, object]], probe: dict[str, object]
) -> dict[str, object]:
    interventions = [
        event for event in events if event.get("event_type") == "H2_NATIVE_PREFIX_INTERVENTION"
    ]
    if len(interventions) != 1 or not isinstance(interventions[0].get("payload"), dict):
        raise ValueError("block path lacks one native intervention")
    payload = interventions[0]["payload"]
    expected = int(probe["evicted_blocks"])
    if (
        payload.get("position") != "trailing"
        or payload.get("count") != expected
        or payload.get("ownership_changed") is not False
        or payload.get("queue_reordered") is not False
        or len(payload.get("selected_block_ids", [])) != expected
    ):
        raise ValueError("block path differs from the frozen trailing-j oracle")
    return {
        "physically_selected_prefix_block_count": expected,
        "selected_prefix_block_ids": payload["selected_block_ids"],
        "ownership_changed": False,
        "queue_reordered": False,
    }


def execute_h2_headroom_validation(
    campaign_path: Path, authorization_path: Path, output: Path
) -> tuple[dict[str, object], Path]:
    campaign_path = campaign_path.resolve()
    campaign = json.loads(campaign_path.read_text())
    if campaign.get("schema_version") != "phase2a.h2_m4_comparator_validation_campaign.v1":
        raise ValueError("unsupported H2 M4 validation campaign")
    if campaign.get("authorization_sha256") != _sha(authorization_path.resolve()):
        raise ValueError("H2 M4 validation authorization hash mismatch")
    if any(campaign.get(key) is not False for key in (
        "formal_measurement", "formal_verdict", "b1_authorized"
    )):
        raise ValueError("H2 M4 comparator validation must remain non-formal")
    probes = campaign.get("probes")
    if not isinstance(probes, list) or len(probes) != 6:
        raise ValueError("H2 M4 comparator validation requires six probes")
    output = output.resolve()
    if any((output / str(probe["run_id"])).exists() for probe in probes):
        raise FileExistsError("validation output exists; use a new output root")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for probe in probes:
        config_path = (campaign_path.parent / str(probe["config"])).resolve()
        if config_path.parent != campaign_path.parent or _sha(config_path) != probe[
            "config_file_sha256"
        ]:
            raise ValueError("H2 M4 validation config hash mismatch")
        run_id = str(probe["run_id"])
        directory = _run_isolated(config_path, output, run_id)
        manifest = json.loads((directory / "run.json").read_text())
        if manifest.get("status") != "success":
            raise ValueError(f"H2 M4 validation failed; preserve evidence: {run_id}")
        if (
            manifest.get("config_sha256") != probe["runtime_config_sha256"]
            or manifest.get("trace_sha256") != probe["trace_sha256"]
        ):
            raise ValueError("H2 M4 validation run provenance mismatch")
        events = _events(directory)
        audit = (
            _validate_entry(events, probe)
            if probe["arm"] == "entry"
            else _validate_block(events, probe)
        )
        recomputed = _return_recomputed(events, run_id, int(probe["prefix_tokens"]))
        results.append({**probe, **audit, "observed_recomputed_tokens": recomputed})
        print(f"{run_id}: success ({recomputed} recomputed tokens)", flush=True)
    by_cell: dict[str, dict[str, dict[str, object]]] = {}
    for result in results:
        by_cell.setdefault(str(result["cell_id"]), {})[str(result["arm"])] = result
    for arms in by_cell.values():
        if set(arms) != {"entry", "block"}:
            raise ValueError("M4 validation cell is not paired")
        if arms["entry"]["physically_selected_prefix_block_count"] != arms["block"][
            "physically_selected_prefix_block_count"
        ]:
            raise ValueError("M4 comparator released-block counts are not comparable")
    summary = {
        "schema_version": "phase2a.h2_m4_comparator_validation_execution.v1",
        "campaign_sha256": _sha(campaign_path),
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "comparator_status": "VALIDATED_FOR_FORMAL_M4_MATERIALIZATION",
        "successful_run_count": len(results),
        "results": results,
    }
    path = output / f"headroom-validation-{uuid.uuid4().hex[:12]}.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
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
    summary, path = execute_h2_headroom_validation(
        arguments.campaign, arguments.authorization, arguments.output_root
    )
    print(
        f"H2 M4 comparator validation: {summary['successful_run_count']} success -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
