import json
import math
from pathlib import Path

from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase2_formal import (
    FORMAL_SEEDS,
    formal_scenario_specs,
    materialize_formal_campaign,
)

BASE_CONFIG = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "profiling"
    / "p3-a128-b512-a-early.json"
)


def test_formal_matrix_covers_required_axes() -> None:
    specs = formal_scenario_specs()

    assert len(specs) == 18
    assert {spec.family_id for spec in specs} == {
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
    }
    assert all(
        sum(spec.family_id == family for spec in specs) == 3
        for family in {spec.family_id for spec in specs}
    )
    assert {len(spec.prefix_tokens) for spec in specs} >= {2, 3, 5}
    assert {spec.required_blocks for spec in specs} >= {4, 16, 32}
    tags = {tag for spec in specs for tag in spec.tags}
    assert {
        "homogeneous",
        "heterogeneous",
        "early-return",
        "late-return",
        "outside-horizon",
        "repeated-pressure",
        "block-slot-reuse",
        "shared-ownership",
    }.issubset(tags)
    assert len(specs) * len(FORMAL_SEEDS) == 54


def test_materialized_campaign_is_deterministic_and_loadable(
    tmp_path: Path,
) -> None:
    first_manifest = materialize_formal_campaign(
        BASE_CONFIG,
        tmp_path / "first",
    )
    second_manifest = materialize_formal_campaign(
        BASE_CONFIG,
        tmp_path / "second",
    )
    first = json.loads(first_manifest.read_text(encoding="utf-8"))
    second = json.loads(second_manifest.read_text(encoding="utf-8"))

    assert first == second
    assert first["schema_version"] == "phase2a.formal_campaign.v1"
    assert first["planned_run_count"] == 54
    assert first["family_scenario_counts"] == {
        family: 3 for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }

    specs_by_id = {spec.scenario_id: spec for spec in formal_scenario_specs()}
    for scenario in first["scenarios"]:
        config_path = first_manifest.parent / scenario["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        trace = load_phase2_trace(first_manifest.parent / config["trace"])
        spec = specs_by_id[scenario["scenario_id"]]
        block_size = config["cache"]["block_size"]
        protected_blocks = sum(
            math.ceil(tokens / block_size) for tokens in spec.prefix_tokens
        )
        pressure_blocks = math.ceil(
            config["backend_options"]["pressure_prompt_tokens"] / block_size
        )
        assert config["profiling_scenario_id"] == scenario["scenario_id"]
        assert config["profiling_scenario_family"] == scenario["family_id"]
        assert config["backend_options"]["pressure_prompt_tokens"] == (
            spec.required_blocks * block_size
        )
        assert config["cache"]["block_override"] == (
            protected_blocks + pressure_blocks
        )
        assert len(trace.pressure_stages) >= 1
        assert len({request.program_id for request in trace.requests}) >= 2
