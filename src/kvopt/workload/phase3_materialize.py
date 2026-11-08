"""Non-executing six-arm configuration expansion for Phase 3 cells."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

CAMPAIGN_KIND = "phase3_final_evaluation"
ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")


@dataclass(frozen=True, slots=True)
class ArmBinding:
    release_policy: str
    block_policy: str
    label: str


_BINDINGS = {
    "N0": ArmBinding("N0", "A0", "native-no-forced-release"),
    "A0": ArmBinding("A0", "A0", "project-continuum-entry-native-lru"),
    "A1": ArmBinding("A1", "A0", "cost-aware-entry-native-lru"),
    "A2": ArmBinding("A0", "A2", "project-continuum-entry-a2-block"),
    "A3": ArmBinding("A3", "A0", "suffix-cost-entry-native-lru"),
    "E0": ArmBinding("E0", "A0", "deadline-step2-entry-native-lru"),
}


def arm_binding(arm: str) -> ArmBinding:
    try:
        return _BINDINGS[arm]
    except KeyError as error:
        raise ValueError(f"unsupported Phase 3 arm: {arm}") from error


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def pressure_request_contract(config: dict[str, object]) -> tuple[dict[str, object], ...]:
    """Return the fixed pressure request identities for one Phase 3 arm."""

    options = config.get("backend_options")
    if not isinstance(options, dict):
        raise TypeError("config.backend_options must be an object")
    stages = options.get("controlled_pressure_stages_by_boundary")
    if not isinstance(stages, dict) or not stages:
        raise ValueError("Phase 3 requires controlled pressure stages")
    rows: list[dict[str, object]] = []
    for boundary_id in sorted(stages):
        stage = stages[boundary_id]
        if not isinstance(boundary_id, str) or not boundary_id:
            raise ValueError("pressure boundary_id must be non-empty")
        if not isinstance(stage, dict):
            raise TypeError("controlled pressure stage must be an object")
        stage_id = stage.get("stage_id")
        maximum = stage.get("max_requests")
        stop = stage.get("stop_on_forced_release")
        if not isinstance(stage_id, str) or not stage_id:
            raise ValueError("pressure stage_id must be non-empty")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise ValueError("pressure max_requests must be a positive integer")
        if stop is not False:
            raise ValueError(
                "Phase 3 pressure requests must not stop on policy outcomes"
            )
        rows.append(
            {
                "boundary_id": boundary_id,
                "stage_id": stage_id,
                "request_ids": [
                    f"pressure:{stage_id}:{attempt}"
                    for attempt in range(1, maximum + 1)
                ],
            }
        )
    return tuple(rows)


def validate_pressure_identity(configs: dict[str, dict[str, object]]) -> str:
    """Fail closed unless every arm has the same fixed pressure contract."""

    if set(configs) != set(ARMS):
        raise ValueError("pressure isolation requires all six Phase 3 arms")
    contracts = {arm: pressure_request_contract(config) for arm, config in configs.items()}
    reference = contracts["A0"]
    if any(contract != reference for contract in contracts.values()):
        raise ValueError("Phase 3 pressure request identity differs across arms")
    return _canonical_sha(reference)


def materialize_six_arm_cell(
    *,
    base_config: dict[str, object],
    trace_path: Path,
    cell_id: str,
    output_dir: Path,
) -> dict[str, object]:
    """Expand one frozen cell without authorizing or starting execution."""

    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not cell_id:
        raise ValueError("cell_id must be non-empty")
    if base_config.get("schema_version") != "phase2.config.v1":
        raise ValueError("Phase 3 base config must use phase2.config.v1")
    if base_config.get("execution_authorized") is True:
        raise ValueError("engineering materialization cannot authorize execution")
    if not trace_path.is_file():
        raise FileNotFoundError(trace_path)
    common_config = copy.deepcopy(base_config)
    options = common_config.get("backend_options")
    if not isinstance(options, dict):
        raise TypeError("base_config.backend_options must be an object")
    stages = options.get("controlled_pressure_stages_by_boundary")
    if not isinstance(stages, dict) or not stages:
        raise ValueError("Phase 3 requires controlled pressure stages")
    for stage in stages.values():
        if not isinstance(stage, dict):
            raise TypeError("controlled pressure stage must be an object")
        # Fixed attempt counts are part of the input.  No arm may stop after a
        # policy-dependent forced-release outcome.
        stage["stop_on_forced_release"] = False

    output_dir.mkdir(parents=True)
    frozen_trace = output_dir / f"{cell_id}.trace.json"
    shutil.copyfile(trace_path, frozen_trace)
    trace_sha = hashlib.sha256(frozen_trace.read_bytes()).hexdigest()
    common_config["trace"] = frozen_trace.name
    pressure_contract = pressure_request_contract(common_config)
    pressure_contract_sha = _canonical_sha(pressure_contract)
    shared_input_sha = _canonical_sha(
        {"config": common_config, "trace_sha256": trace_sha}
    )
    runs: list[dict[str, object]] = []
    configs: dict[str, dict[str, object]] = {}
    for arm in ARMS:
        binding = arm_binding(arm)
        config = copy.deepcopy(common_config)
        config["campaign_kind"] = CAMPAIGN_KIND
        config["execution_authorized"] = False
        config["run_id"] = f"{cell_id}-{arm.lower()}"
        config["policy"] = binding.label
        backend = config["backend_options"]
        assert isinstance(backend, dict)
        backend["phase2g_release_policy"] = binding.release_policy
        backend["phase2g_block_policy"] = binding.block_policy
        backend["phase3_arm"] = arm
        configs[arm] = config
        path = output_dir / f"{cell_id}-{arm.lower()}.config.json"
        _write(path, config)
        runs.append(
            {
                "arm": arm,
                "run_id": config["run_id"],
                "config": path.name,
                "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "shared_input_sha256": shared_input_sha,
            }
        )

    if validate_pressure_identity(configs) != pressure_contract_sha:
        raise RuntimeError("materialized pressure contract changed across arms")

    manifest = {
        "schema_version": "phase3.six_arm_cell_manifest.v1",
        "execution_authorized": False,
        "campaign_kind": CAMPAIGN_KIND,
        "cell_id": cell_id,
        "arms": list(ARMS),
        "shared_input_sha256": shared_input_sha,
        "trace": frozen_trace.name,
        "trace_sha256": trace_sha,
        "pressure_request_contract": pressure_contract,
        "pressure_request_contract_sha256": pressure_contract_sha,
        "runs": runs,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest
