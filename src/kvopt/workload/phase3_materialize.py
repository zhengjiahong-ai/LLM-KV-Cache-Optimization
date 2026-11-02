"""Non-executing six-arm configuration expansion for Phase 3 cells."""

from __future__ import annotations

import copy
import hashlib
import json
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


def materialize_six_arm_cell(
    *, base_config: dict[str, object], cell_id: str, output_dir: Path
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
    options = base_config.get("backend_options")
    if not isinstance(options, dict):
        raise TypeError("base_config.backend_options must be an object")

    output_dir.mkdir(parents=True)
    shared_input_sha = _canonical_sha(base_config)
    runs: list[dict[str, object]] = []
    for arm in ARMS:
        binding = arm_binding(arm)
        config = copy.deepcopy(base_config)
        config["campaign_kind"] = CAMPAIGN_KIND
        config["execution_authorized"] = False
        config["run_id"] = f"{cell_id}-{arm.lower()}"
        config["policy"] = binding.label
        backend = config["backend_options"]
        assert isinstance(backend, dict)
        backend["phase2g_release_policy"] = binding.release_policy
        backend["phase2g_block_policy"] = binding.block_policy
        backend["phase3_arm"] = arm
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

    manifest = {
        "schema_version": "phase3.six_arm_cell_manifest.v1",
        "execution_authorized": False,
        "campaign_kind": CAMPAIGN_KIND,
        "cell_id": cell_id,
        "arms": list(ARMS),
        "shared_input_sha256": shared_input_sha,
        "runs": runs,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest
