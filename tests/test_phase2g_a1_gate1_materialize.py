import json
from pathlib import Path

from kvopt.workload.phase2g_a1_gate1_materialize import materialize_gate1

FIXTURE = Path("configs/phase2/phase2g-a1-native-gate1-v1.json")


def test_gate1_materializes_two_cases_two_policies_two_repeats(
    tmp_path: Path,
) -> None:
    manifest_path = materialize_gate1(
        fixture_path=FIXTURE,
        output_dir=tmp_path / "campaign",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["planned_run_count"] == 8
    assert manifest["case_count"] == 2
    assert manifest["policies"] == ["A0", "A1"]
    assert manifest["gate2_execution_started"] is False


def test_paired_arms_bind_identical_workload_and_runtime(tmp_path: Path) -> None:
    manifest_path = materialize_gate1(
        fixture_path=FIXTURE,
        output_dir=tmp_path / "campaign",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for run in manifest["runs"]:
        grouped.setdefault((run["case_id"], run["repeat"]), []).append(run)

    for arms in grouped.values():
        assert {arm["policy"] for arm in arms} == {"A0", "A1"}
        assert len({arm["trace_sha256"] for arm in arms}) == 1
        configs = [
            json.loads((manifest_path.parent / arm["config"]).read_text(encoding="utf-8"))
            for arm in arms
        ]
        left, right = configs
        assert left["seed"] == right["seed"]
        assert left["model"] == right["model"]
        assert left["cache"] == right["cache"]
        assert left["generation"] == right["generation"]
        assert left["backend_options"]["prefix_segments_by_request"] == right[
            "backend_options"
        ]["prefix_segments_by_request"]
        assert {
            left["backend_options"]["phase2g_release_policy"],
            right["backend_options"]["phase2g_release_policy"],
        } == {"A0", "A1"}


def test_gate1_has_divergence_and_same_selection_controls(tmp_path: Path) -> None:
    manifest_path = materialize_gate1(
        fixture_path=FIXTURE,
        output_dir=tmp_path / "campaign",
    )
    relations = {
        json.loads((manifest_path.parent / run["config"]).read_text(encoding="utf-8"))[
            "phase2g_stage"
        ]["expected_selection_relation"]
        for run in json.loads(manifest_path.read_text(encoding="utf-8"))["runs"]
    }

    assert relations == {"DIFFERENT", "SAME"}
