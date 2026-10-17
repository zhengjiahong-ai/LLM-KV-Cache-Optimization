import json
from collections import Counter, defaultdict
from pathlib import Path

from kvopt.workload.phase2g_a1_bounded_materialize import (
    materialize_bounded_campaign,
)

DISTRIBUTION = Path("configs/phase2/phase2g-a1-bounded-distribution-v1.json")


def _materialize(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    path = materialize_bounded_campaign(
        distribution_path=DISTRIBUTION,
        output_dir=tmp_path / "campaign",
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_materializes_36_scenarios_and_144_locked_runs(tmp_path: Path) -> None:
    _, manifest = _materialize(tmp_path)

    assert manifest["scenario_count"] == 36
    assert manifest["planned_run_count"] == 144
    assert manifest["execution_authorized"] is False
    assert manifest["outcomes_materialized"] is False
    assert Counter(row["family"] for row in manifest["scenarios"]) == Counter(
        {family: 6 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}
    )


def test_each_scenario_has_identical_paired_inputs(tmp_path: Path) -> None:
    path, manifest = _materialize(tmp_path)
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for run in manifest["runs"]:
        grouped[str(run["scenario_id"])].append(run)

    for runs in grouped.values():
        assert Counter((run["policy"], run["repeat"]) for run in runs) == Counter(
            (policy, repeat) for policy in ("A0", "A1") for repeat in (1, 2)
        )
        assert len({run["trace_sha256"] for run in runs}) == 1
        configs = [
            json.loads((path.parent / str(run["config"])).read_text(encoding="utf-8"))
            for run in runs
        ]
        assert len({config["seed"] for config in configs}) == 1
        for field in ("model", "tokenizer", "generation", "batching", "cache", "trace"):
            assert all(config[field] == configs[0][field] for config in configs)
        assert all(
            config["backend_options"]["prefix_segments_by_request"]
            == configs[0]["backend_options"]["prefix_segments_by_request"]
            for config in configs
        )


def test_family_contracts_create_real_parameter_variation(tmp_path: Path) -> None:
    _, manifest = _materialize(tmp_path)

    for family in ("F1", "F2", "F3", "F4", "F5", "F6"):
        rows = [row for row in manifest["scenarios"] if row["family"] == family]
        assert len({row["entry_count"] for row in rows}) >= 2
        assert len({tuple(row["family_parameters"]["prefix_sizes_tokens"]) for row in rows}) >= 3
        assert len({row["pressure_count"] for row in rows}) >= 2
