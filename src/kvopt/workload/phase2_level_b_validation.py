"""Materialize the dedicated S1-S5 Level-B seam-validation campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .phase2 import Phase2Trace, PlannedRequest, PressureStage


@dataclass(frozen=True, slots=True)
class SeamValidationSpec:
    case_id: str
    description: str
    prefix_tokens: int
    pressure_tokens: int | None
    initial_shortage_blocks: int
    expected_semantics: str


def seam_validation_specs() -> tuple[SeamValidationSpec, ...]:
    return (
        SeamValidationSpec(
            "s1-cold-no-eligible-prefix",
            "First request has no prior materialized native prefix.",
            256,
            None,
            1,
            "NO_REUSE_ELIGIBLE_PREFIX",
        ),
        SeamValidationSpec(
            "s2-no-eviction-full-hit",
            "Re-request the materialized prefix without pressure.",
            256,
            None,
            1,
            "FULL_HIT",
        ),
        SeamValidationSpec(
            "s3-controlled-partial-hit",
            "Apply bounded pressure before re-requesting the prefix.",
            256,
            384,
            8,
            "PARTIAL_HIT",
        ),
        SeamValidationSpec(
            "s4-controlled-full-loss",
            "Apply pressure sized to remove the reusable prefix.",
            256,
            512,
            16,
            "MISS",
        ),
        SeamValidationSpec(
            "s5-old-prefix-fresh-suffix",
            "Validate W = R + (N - E) on a pressured re-request.",
            512,
            512,
            16,
            "FRESH_SUFFIX_SEPARATED",
        ),
    )


def _trace(spec: SeamValidationSpec) -> Phase2Trace:
    first_is_terminal = spec.case_id == "s1-cold-no-eligible-prefix"
    requests = [
        PlannedRequest(
            program_id="agent-a",
            request_id="agent-a:turn:1",
            turn_index=1,
            planned_arrival_offset_seconds=0.0,
            prompt="materialize deterministic reusable prefix",
            prefix_prompt="level-b seam validation prefix",
            is_terminal=first_is_terminal,
            next_tool_type=None if first_is_terminal else "search",
            tool_gap_seconds=None if first_is_terminal else 0.4,
        )
    ]
    if not first_is_terminal:
        requests.append(
            PlannedRequest(
                program_id="agent-a",
                request_id="agent-a:turn:2",
                turn_index=2,
                planned_arrival_offset_seconds=0.4,
                prompt="return with a fresh deterministic suffix",
                prefix_prompt="level-b seam validation prefix",
                is_terminal=True,
                next_tool_type=None,
                tool_gap_seconds=None,
            )
        )
    stages = ()
    if spec.pressure_tokens is not None:
        stages = (
            PressureStage(
                stage_id="seam-pressure",
                planned_arrival_offset_seconds=0.2,
                prompt="level-b seam validation pressure",
                max_requests=1,
                stop_on_forced_release=True,
            ),
        )
    return Phase2Trace(
        trace_id=f"phase2a-level-b-{spec.case_id}-v1",
        requests=tuple(requests),
        pressure_stages=stages,
    )


def _config(
    spec: SeamValidationSpec,
    base_config: dict[str, object],
) -> dict[str, object]:
    config = copy.deepcopy(base_config)
    config["trace"] = f"{spec.case_id}.trace.json"
    config["seed"] = 42
    config["validation_case_id"] = spec.case_id
    config["campaign_kind"] = "instrumentation_seam_validation"
    block_size = 16
    # The pinned backend keeps a 528-token minimum max_model_len, so even
    # no-pressure validation cases need enough configured blocks to serve it.
    pressure_tokens = spec.pressure_tokens or 512
    prefix_blocks = math.ceil(spec.prefix_tokens / block_size)
    pressure_blocks = math.ceil(pressure_tokens / block_size)
    cache = config["cache"]
    pressure = config["pressure"]
    options = config["backend_options"]
    if not isinstance(cache, dict) or not isinstance(pressure, dict) or not isinstance(options, dict):
        raise TypeError("base config cache, pressure, and backend_options must be objects")
    cache["block_size"] = block_size
    cache["block_override"] = (
        prefix_blocks
        + pressure_blocks
        + 1
        - spec.initial_shortage_blocks
    )
    pressure["required_blocks"] = pressure_blocks
    pressure["initial_shortage_blocks"] = spec.initial_shortage_blocks
    pressure["safety_ceiling"] = 1
    options["program_prefix_tokens"] = {"agent-a": spec.prefix_tokens}
    options["pressure_prompt_tokens"] = pressure_tokens
    options["pressure_stage_prompt_tokens"] = (
        {"seam-pressure": pressure_tokens}
        if spec.pressure_tokens is not None
        else {}
    )
    options["execute_planned_timing"] = True
    return config


def materialize_seam_validation_campaign(
    base_config_path: str | Path,
    output_dir: str | Path,
) -> Path:
    base_path = Path(base_config_path).resolve()
    base_config = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(base_config, dict):
        raise TypeError("base config must be an object")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    scenarios: list[dict[str, object]] = []
    for spec in seam_validation_specs():
        trace_text = json.dumps(
            _trace(spec).to_dict(), indent=2, sort_keys=True
        ) + "\n"
        config_text = json.dumps(
            _config(spec, base_config), indent=2, sort_keys=True
        ) + "\n"
        trace_path = output / f"{spec.case_id}.trace.json"
        config_path = output / f"{spec.case_id}.config.json"
        trace_path.write_text(trace_text, encoding="utf-8")
        config_path.write_text(config_text, encoding="utf-8")
        scenarios.append(
            {
                "case_id": spec.case_id,
                "description": spec.description,
                "config": config_path.name,
                "config_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
                "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                "expected_semantics": spec.expected_semantics,
                "target_request_id": (
                    "agent-a:turn:1"
                    if spec.case_id == "s1-cold-no-eligible-prefix"
                    else "agent-a:turn:2"
                ),
            }
        )
    manifest = {
        "schema_version": "phase2a.level_b_seam_validation.v1",
        "campaign_id": "phase2a-level-b-seam-validation-v1",
        "campaign_kind": "instrumentation_seam_validation",
        "formal_h1_evidence": False,
        "formal_h1_execution_authorized": False,
        "scenarios": scenarios,
    }
    manifest_path = output / "campaign.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    manifest = materialize_seam_validation_campaign(
        arguments.base_config,
        arguments.output,
    )
    print(f"wrote Level-B seam-validation campaign: {manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
