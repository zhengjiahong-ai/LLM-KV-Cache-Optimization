"""Materialize authorized formal H2 M2/M3 mechanism campaigns."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .phase2 import Phase2Trace, PlannedRequest

_BLOCK_SIZE = 16
_M2_PREFIX_BLOCKS = 64
_M2_RETAINED_BLOCKS = (0, 16, 32, 48, 64)
_M3_PREFIX_TOKENS = (512, 2048, 8192, 24576)
_M3_EVICTED_BLOCKS = (1, 4, 16)
_WARMUPS = 2
_MEASUREMENTS = 9


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_authorization(path: Path) -> dict[str, Any]:
    authorization = json.loads(path.read_text(encoding="utf-8"))
    if authorization.get("schema_version") != "phase2a.h2_measurement_authorization.v1":
        raise ValueError("unsupported H2 authorization")
    if authorization.get("formal_h2_measurement_authorized") is not True:
        raise ValueError("formal H2 measurement is not authorized")
    if authorization.get("formal_h2_verdict_authorized") is not False:
        raise ValueError("formal H2 verdict must remain unauthorized")
    if authorization.get("b1_method_or_implementation_authorized") is not False:
        raise ValueError("B1 must remain unauthorized")
    root = Path(__file__).resolve().parents[3]
    submission = root / "configs/phase2/h2-final-authorization-submission.json"
    if _sha(submission) != authorization.get("submission_sha256"):
        raise ValueError("reviewed H2 authorization submission hash mismatch")
    bindings = authorization.get("bindings")
    if not isinstance(bindings, dict):
        raise TypeError("H2 authorization bindings must be an object")
    local_bindings = {
        "numeric_audit_sha256": (
            "docs/experiments/phase2a-m6-h2/"
            "isolated-calibration-numeric-audit.json"
        ),
        "independent_verifier_sha256": "scripts/audit_h2_bootstrap.py",
        "final_freeze_record_sha256": "configs/phase2/h2-final-freeze-record.json",
        "formal_freeze_spec_sha256": "configs/phase2/h2-formal-freeze-spec.json",
    }
    for field, relative_path in local_bindings.items():
        if _sha(root / relative_path) != bindings.get(field):
            raise ValueError(f"H2 authorization binding mismatch: {field}")
    protocol = authorization.get("protocol")
    if not isinstance(protocol, dict):
        raise TypeError("H2 authorization protocol must be an object")
    if protocol.get("warmup_repeats") != _WARMUPS:
        raise ValueError("H2 warmup count differs from the frozen protocol")
    if protocol.get("measured_repeats") != _MEASUREMENTS:
        raise ValueError("H2 measured repeat count differs from the frozen protocol")
    if protocol.get("m2_rules") != {
        "block_size_tokens": _BLOCK_SIZE,
        "fresh_suffix_tokens": 1,
        "no_eviction_full_hit_control": True,
        "prefix_blocks": _M2_PREFIX_BLOCKS,
        "retained_leading_blocks": list(_M2_RETAINED_BLOCKS),
        "token_tolerance": 0,
    }:
        raise ValueError("H2 M2 rules differ from the frozen protocol")
    m3 = protocol.get("m3_rules")
    if not isinstance(m3, dict) or m3 != {
        "cell_definition": "4_prefix_sizes_x_3_equal_evicted_block_counts",
        "repeats_per_cell": _MEASUREMENTS,
        "resolved_effect_tokens": 16,
        "supporting_cells_required": 10,
        "supporting_repeats_required": 8,
        "total_cells": 12,
    }:
        raise ValueError("H2 M3 rules differ from the frozen protocol")
    if protocol.get("position_and_headroom_prefix_tokens") != list(
        _M3_PREFIX_TOKENS
    ):
        raise ValueError("H2 M3 prefix grid differs from the frozen protocol")
    if protocol.get("evicted_block_counts") != list(_M3_EVICTED_BLOCKS):
        raise ValueError("H2 M3 eviction grid differs from the frozen protocol")
    configurations = authorization.get("m1_execution_configurations")
    if not isinstance(configurations, list):
        raise TypeError("authorized M1 execution configurations must be a list")
    for row in configurations:
        if not isinstance(row, dict) or not isinstance(row.get("config"), dict):
            raise TypeError("authorized execution configuration must be an object")
        if _canonical_sha(row["config"]) != row.get("config_sha256"):
            raise ValueError("authorized base configuration hash mismatch")
    return authorization


def _authorized_base_config(
    authorization: dict[str, Any],
    prefix_tokens: int,
) -> dict[str, object]:
    rows = authorization.get("m1_execution_configurations")
    if not isinstance(rows, list):
        raise TypeError("authorized M1 execution configurations must be a list")
    matches = [row for row in rows if row.get("prefix_tokens") == prefix_tokens]
    if len(matches) != 1:
        raise ValueError("H2 mechanism prefix lacks one authorized base configuration")
    row = matches[0]
    config = row.get("config")
    if not isinstance(config, dict) or _canonical_sha(config) != row.get("config_sha256"):
        raise ValueError("authorized base configuration hash mismatch")
    return copy.deepcopy(config)


def _trace(probe_id: str, prefix_tokens: int) -> Phase2Trace:
    return Phase2Trace(
        trace_id=f"phase2a-h2-{probe_id}-v1",
        requests=(
            PlannedRequest(
                program_id=probe_id,
                request_id=f"{probe_id}:turn:1",
                turn_index=1,
                planned_arrival_offset_seconds=0.0,
                prompt="H2 native prefix mechanism priming request",
                prefix_prompt="deterministic H2 native prefix",
                is_terminal=False,
                next_tool_type="h2-mechanism-probe",
                tool_gap_seconds=0.0,
            ),
            PlannedRequest(
                program_id=probe_id,
                request_id=f"{probe_id}:turn:2",
                turn_index=2,
                planned_arrival_offset_seconds=0.0,
                prompt="H2 native prefix mechanism return request",
                prefix_prompt="deterministic H2 native prefix",
                is_terminal=True,
                next_tool_type=None,
                tool_gap_seconds=None,
            ),
        ),
        pressure_stages=(),
    )


def _mechanism_config(
    authorization: dict[str, Any],
    *,
    probe_id: str,
    prefix_tokens: int,
    trace_name: str,
    position: str | None,
    count: int,
    campaign_kind: str = "h2_formal_measurement",
) -> dict[str, object]:
    config = _authorized_base_config(authorization, prefix_tokens)
    config["trace"] = trace_name
    config["campaign_kind"] = campaign_kind
    config["h2_measurement"] = {
        "probe_id": probe_id,
        "prefix_tokens": prefix_tokens,
        "position": position,
        "evicted_blocks": count,
    }
    options = config.get("backend_options")
    if not isinstance(options, dict):
        raise TypeError("authorized backend_options must be an object")
    options["program_prefix_tokens"] = {probe_id: prefix_tokens}
    options["capture_terminal_prefix_snapshot"] = False
    options["isolated_native_prefill_timing"] = False
    options["h2_native_prefix_interventions"] = (
        {}
        if position is None
        else {f"{probe_id}:turn:1": {"position": position, "count": count}}
    )
    return config


def _runs(probe_id: str) -> list[dict[str, str]]:
    return [
        {"run_id": f"{probe_id}-{role}-{index}", "role": role}
        for role, count in (("warmup", _WARMUPS), ("measured", _MEASUREMENTS))
        for index in range(1, count + 1)
    ]


def _write_probe(
    output: Path,
    authorization: dict[str, Any],
    *,
    probe_id: str,
    prefix_tokens: int,
    position: str | None,
    count: int,
    metadata: dict[str, object],
) -> dict[str, object]:
    trace_name = f"{probe_id}.trace.json"
    config_name = f"{probe_id}.config.json"
    trace = _trace(probe_id, prefix_tokens).to_dict()
    config = _mechanism_config(
        authorization,
        probe_id=probe_id,
        prefix_tokens=prefix_tokens,
        trace_name=trace_name,
        position=position,
        count=count,
    )
    trace_text = json.dumps(trace, indent=2, sort_keys=True) + "\n"
    config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
    (output / trace_name).write_text(trace_text, encoding="utf-8")
    (output / config_name).write_text(config_text, encoding="utf-8")
    return {
        **metadata,
        "probe_id": probe_id,
        "prefix_tokens": prefix_tokens,
        "position": position,
        "evicted_blocks": count,
        "config": config_name,
        "runtime_config_sha256": _canonical_sha(config),
        "config_file_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
        "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
        "runs": _runs(probe_id),
    }


def materialize_formal_m2_m3(authorization_path: Path, output: Path) -> Path:
    authorization_path = authorization_path.resolve()
    authorization = _load_authorization(authorization_path)
    output.mkdir(parents=True, exist_ok=False)
    probes: list[dict[str, object]] = []
    prefix_tokens = _M2_PREFIX_BLOCKS * _BLOCK_SIZE
    for retained in _M2_RETAINED_BLOCKS:
        evicted = _M2_PREFIX_BLOCKS - retained
        probe_id = f"m2-k{retained}"
        probes.append(
            _write_probe(
                output,
                authorization,
                probe_id=probe_id,
                prefix_tokens=prefix_tokens,
                position="trailing",
                count=evicted,
                metadata={
                    "measurement": "M2",
                    "retained_leading_blocks": retained,
                    "control": (
                        "full-evict" if retained == 0 else
                        "full-retain" if retained == _M2_PREFIX_BLOCKS else None
                    ),
                },
            )
        )
    probes.append(
        _write_probe(
            output,
            authorization,
            probe_id="m2-no-eviction-control",
            prefix_tokens=prefix_tokens,
            position=None,
            count=0,
            metadata={
                "measurement": "M2",
                "retained_leading_blocks": _M2_PREFIX_BLOCKS,
                "control": "no-eviction-full-hit",
            },
        )
    )
    for prefix_tokens in _M3_PREFIX_TOKENS:
        for count in _M3_EVICTED_BLOCKS:
            for position in ("leading", "trailing"):
                probe_id = f"m3-r{prefix_tokens}-j{count}-{position}"
                probes.append(
                    _write_probe(
                        output,
                        authorization,
                        probe_id=probe_id,
                        prefix_tokens=prefix_tokens,
                        position=position,
                        count=count,
                        metadata={
                            "measurement": "M3",
                            "cell_id": f"m3-r{prefix_tokens}-j{count}",
                        },
                    )
                )
    manifest = {
        "schema_version": "phase2a.h2_formal_m2_m3_campaign.v1",
        "campaign_id": "phase2a-h2-formal-m2-m3-v1",
        "authorization_sha256": _sha(authorization_path),
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "warmup_repeats_per_probe": _WARMUPS,
        "measured_repeats_per_probe": _MEASUREMENTS,
        "probe_count": len(probes),
        "planned_run_count": sum(len(probe["runs"]) for probe in probes),
        "m2_probe_count": sum(probe["measurement"] == "M2" for probe in probes),
        "m3_arm_count": sum(probe["measurement"] == "M3" for probe in probes),
        "m3_cell_count": len(
            {probe.get("cell_id") for probe in probes if probe["measurement"] == "M3"}
        ),
        "probes": probes,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        "wrote formal H2 M2/M3 campaign: "
        f"{materialize_formal_m2_m3(args.authorization, args.output)}"
    )
