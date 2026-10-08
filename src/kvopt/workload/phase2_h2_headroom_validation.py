"""Materialize the non-formal H2 M4 comparator validation campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from .phase2 import Phase2Trace, PlannedRequest, PressureStage
from .phase2_h2_mechanism import (
    _canonical_sha,
    _load_authorization,
    _mechanism_config,
    _trace,
)

_CELLS = ((512, 1), (512, 4), (512, 16))
_PRESSURE_BLOCKS = 32


def _entry_trace(probe_id: str) -> Phase2Trace:
    return Phase2Trace(
        trace_id=f"phase2a-h2-{probe_id}-v1",
        requests=(
            PlannedRequest(
                program_id=probe_id,
                request_id=f"{probe_id}:turn:1",
                turn_index=1,
                planned_arrival_offset_seconds=0.0,
                prompt="H2 entry-path priming request",
                prefix_prompt="deterministic H2 M4 prefix",
                is_terminal=False,
                next_tool_type="h2-headroom-probe",
                tool_gap_seconds=2.0,
            ),
            PlannedRequest(
                program_id=probe_id,
                request_id=f"{probe_id}:turn:2",
                turn_index=2,
                planned_arrival_offset_seconds=2.0,
                prompt="H2 entry-path return request",
                prefix_prompt="deterministic H2 M4 prefix",
                is_terminal=True,
                next_tool_type=None,
                tool_gap_seconds=None,
            ),
        ),
        pressure_stages=(
            PressureStage(
                stage_id="m4-pressure",
                planned_arrival_offset_seconds=1.0,
                prompt="H2 M4 entry-path pressure",
                max_requests=1,
                stop_on_forced_release=True,
            ),
        ),
    )


def _base_config(authorization: dict[str, object], prefix_tokens: int) -> dict[str, object]:
    matches = [
        row for row in authorization["m1_execution_configurations"]  # type: ignore[index]
        if row["prefix_tokens"] == prefix_tokens
    ]
    if len(matches) != 1:
        raise ValueError("M4 prefix lacks one authorized base configuration")
    return copy.deepcopy(matches[0]["config"])


def _entry_config(
    authorization: dict[str, object], probe_id: str, prefix_tokens: int,
    evicted_blocks: int, trace_name: str,
) -> dict[str, object]:
    config = _base_config(authorization, prefix_tokens)
    config["trace"] = trace_name
    config["campaign_kind"] = "h2_intervention_validation"
    config["h2_measurement"] = {
        "measurement": "M4",
        "arm": "entry",
        "probe_id": probe_id,
        "prefix_tokens": prefix_tokens,
        "evicted_blocks": evicted_blocks,
        "formal_measurement": False,
        "validation_only": True,
    }
    cache = config["cache"]
    pressure = config["pressure"]
    options = config["backend_options"]
    assert isinstance(cache, dict) and isinstance(pressure, dict) and isinstance(options, dict)
    prefix_blocks = prefix_tokens // 16
    cache["block_override"] = prefix_blocks + _PRESSURE_BLOCKS + 1 - evicted_blocks
    pressure.update(
        required_blocks=_PRESSURE_BLOCKS,
        initial_shortage_blocks=evicted_blocks,
        safety_ceiling=1,
        stage_required_blocks=[_PRESSURE_BLOCKS],
    )
    options.update(
        program_prefix_tokens={probe_id: prefix_tokens},
        pressure_prompt_tokens=_PRESSURE_BLOCKS * 16,
        pressure_stage_prompt_tokens={"m4-pressure": _PRESSURE_BLOCKS * 16},
        execute_planned_timing=False,
        capture_terminal_prefix_snapshot=False,
        isolated_native_prefill_timing=False,
        h2_native_mechanism_only=False,
        h2_native_prefix_interventions={},
    )
    return config


def materialize_h2_headroom_validation(authorization_path: Path, output: Path) -> Path:
    authorization_path = authorization_path.resolve()
    authorization = _load_authorization(authorization_path)
    output.mkdir(parents=True, exist_ok=False)
    probes = []
    for prefix_tokens, evicted_blocks in _CELLS:
        for arm in ("entry", "block"):
            probe_id = f"h2m4v-r{prefix_tokens}-j{evicted_blocks}-{arm}"
            trace_name = f"{probe_id}.trace.json"
            config_name = f"{probe_id}.config.json"
            if arm == "entry":
                trace = _entry_trace(probe_id).to_dict()
                config = _entry_config(
                    authorization, probe_id, prefix_tokens, evicted_blocks, trace_name
                )
            else:
                trace = _trace(probe_id, prefix_tokens).to_dict()
                config = _mechanism_config(
                    authorization,
                    probe_id=probe_id,
                    prefix_tokens=prefix_tokens,
                    trace_name=trace_name,
                    position="trailing",
                    count=evicted_blocks,
                    campaign_kind="h2_intervention_validation",
                )
                config["h2_measurement"] = {
                    **config["h2_measurement"],  # type: ignore[misc]
                    "measurement": "M4",
                    "arm": "block",
                    "formal_measurement": False,
                    "validation_only": True,
                }
            trace_text = json.dumps(trace, indent=2, sort_keys=True) + "\n"
            config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
            (output / trace_name).write_text(trace_text, encoding="utf-8")
            (output / config_name).write_text(config_text, encoding="utf-8")
            probes.append(
                {
                    "probe_id": probe_id,
                    "cell_id": f"r{prefix_tokens}-j{evicted_blocks}",
                    "arm": arm,
                    "prefix_tokens": prefix_tokens,
                    "evicted_blocks": evicted_blocks,
                    "config": config_name,
                    "runtime_config_sha256": _canonical_sha(config),
                    "config_file_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
                    "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                    "run_id": probe_id,
                }
            )
    campaign = {
        "schema_version": "phase2a.h2_m4_comparator_validation_campaign.v1",
        "campaign_id": "phase2a-h2-m4-comparator-validation-v1",
        "authorization_sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "purpose": "validate entry/native-LRU and trailing-j oracle comparability",
        "planned_run_count": len(probes),
        "probes": probes,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(campaign, indent=2, sort_keys=True) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(
        "wrote H2 M4 comparator validation campaign: "
        f"{materialize_h2_headroom_validation(arguments.authorization, arguments.output)}"
    )
