"""Materialize the authorized formal H2 M4 headroom campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .phase2_h2_headroom_validation import _entry_config, _entry_trace
from .phase2_h2_mechanism import (
    _canonical_sha,
    _load_authorization,
    _mechanism_config,
    _trace,
)

_PREFIX_GRID = (512, 2048, 8192, 24576)
_EVICTION_GRID = (1, 4, 16)
_M1_OUTCOME_PATH = "artifacts/phase2a-h2-formal-m1-outcome-v1/m1-outcome.json"
_M1_OUTCOME_SHA256 = "5261a1616efe31c0d80a1ef28fb76e765e68072fb403720b7f4247f5323036df"


def _runs(probe_id: str) -> list[dict[str, object]]:
    return [
        {"run_id": f"{probe_id}-{role}-{index}", "role": role, "repeat_index": index}
        for role, count in (("warmup", 2), ("measured", 9))
        for index in range(1, count + 1)
    ]


def materialize_formal_m4(authorization_path: Path, output: Path) -> Path:
    authorization_path = authorization_path.resolve()
    authorization = _load_authorization(authorization_path)
    rule = authorization["protocol"]["m4_rules"]
    if rule != {
        "block_path": "controlled_trailing_j_offline_mechanism_oracle",
        "comparator": "single_prefix_native_lru_entry_path_vs_controlled_trailing_j_oracle",
        "entry_path": "logical_entry_release_then_native_lru_physical_selection",
        "repeats_per_cell": 9,
        "resolved_effect_tokens": 16,
        "supporting_cells_required": 10,
        "supporting_repeats_required": 8,
        "total_cells": 12,
    }:
        raise ValueError("H2 M4 authorization differs from the frozen rule")
    output.mkdir(parents=True, exist_ok=False)
    probes = []
    for prefix_tokens in _PREFIX_GRID:
        for evicted_blocks in _EVICTION_GRID:
            cell_id = f"m4-r{prefix_tokens}-j{evicted_blocks}"
            for arm in ("entry", "block"):
                probe_id = f"{cell_id}-{arm}"
                trace_name = f"{probe_id}.trace.json"
                config_name = f"{probe_id}.config.json"
                if arm == "entry":
                    trace = _entry_trace(probe_id).to_dict()
                    config = _entry_config(
                        authorization, probe_id, prefix_tokens, evicted_blocks, trace_name
                    )
                    config["campaign_kind"] = "h2_formal_measurement"
                    options = config["backend_options"]
                    assert isinstance(options, dict)
                    options["h2_m4_prefill_curve_path"] = _M1_OUTCOME_PATH
                    options["h2_m4_prefill_curve_sha256"] = _M1_OUTCOME_SHA256
                    config["h2_measurement"] = {
                        **config["h2_measurement"],
                        "formal_measurement": True,
                        "validation_only": False,
                    }
                else:
                    trace = _trace(probe_id, prefix_tokens).to_dict()
                    config = _mechanism_config(
                        authorization,
                        probe_id=probe_id,
                        prefix_tokens=prefix_tokens,
                        trace_name=trace_name,
                        position="trailing",
                        count=evicted_blocks,
                    )
                    config["h2_measurement"] = {
                        **config["h2_measurement"],
                        "measurement": "M4",
                        "arm": "block",
                        "formal_measurement": True,
                        "validation_only": False,
                    }
                trace_text = json.dumps(trace, indent=2, sort_keys=True) + "\n"
                config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
                (output / trace_name).write_text(trace_text)
                (output / config_name).write_text(config_text)
                probes.append(
                    {
                        "probe_id": probe_id,
                        "cell_id": cell_id,
                        "arm": arm,
                        "prefix_tokens": prefix_tokens,
                        "evicted_blocks": evicted_blocks,
                        "config": config_name,
                        "runtime_config_sha256": _canonical_sha(config),
                        "config_file_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
                        "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                        "runs": _runs(probe_id),
                    }
                )
    campaign = {
        "schema_version": "phase2a.h2_formal_m4_campaign.v1",
        "campaign_id": "phase2a-h2-formal-m4-v1",
        "authorization_sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
        "comparator_validation_sha256": (
            "2231b9f2fc76f6ae7bb76f4087270cb10e7e8c1e806d91a5f4cbdb1a54524651"
        ),
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "planned_run_count": 264,
        "warmup_repeats_per_arm": 2,
        "measured_repeats_per_arm": 9,
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
    print(f"wrote formal H2 M4 campaign: {materialize_formal_m4(arguments.authorization, arguments.output)}")
