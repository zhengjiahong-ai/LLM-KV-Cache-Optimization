import json
from pathlib import Path

from kvopt.workload.phase2g_a2_gate1_materialize import materialize_gate1

FIXTURE = Path("configs/phase2/phase2g-a2-native-gate1-v1.json")


def test_materializes_six_cases_two_policies_two_repeats(tmp_path: Path) -> None:
    path = materialize_gate1(fixture_path=FIXTURE, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["planned_run_count"] == 24
    assert manifest["case_count"] == 6
    assert manifest["policies"] == ["A0", "A2"]
    assert len({row["config_sha256"] for row in manifest["runs"]}) == 24


def test_a0_and_a2_hold_entry_release_and_workload_fixed(tmp_path: Path) -> None:
    path = materialize_gate1(fixture_path=FIXTURE, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent

    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in manifest["runs"]:
        grouped.setdefault((row["case_id"], row["repeat"]), []).append(row)
    for rows in grouped.values():
        assert len(rows) == 2
        configs = [
            json.loads((root / row["config"]).read_text(encoding="utf-8"))
            for row in rows
        ]
        left, right = configs
        assert left["trace"] == right["trace"]
        assert left["cache"] == right["cache"]
        assert left["pressure"] == right["pressure"]
        assert left["seed"] == right["seed"]
        assert left["backend_options"]["phase2g_release_policy"] == "A0"
        assert right["backend_options"]["phase2g_release_policy"] == "A0"
        assert {
            left["backend_options"]["phase2g_block_policy"],
            right["backend_options"]["phase2g_block_policy"],
        } == {"A0", "A2"}


def test_shared_case_uses_real_repeated_content_key(tmp_path: Path) -> None:
    path = materialize_gate1(fixture_path=FIXTURE, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    row = next(
        item
        for item in manifest["runs"]
        if item["case_id"] == "a2-shared-multichain" and item["policy"] == "A2"
    )
    config = json.loads((path.parent / row["config"]).read_text(encoding="utf-8"))
    segments = config["backend_options"]["prefix_segments_by_request"]

    assert segments["gate1-a:1"][0] == ["shared-root", 64]
    assert segments["gate1-b:1"][0] == ["shared-root", 64]
    assert config["backend_options"]["phase2g_unique_protected_blocks"] == 28


def test_fallback_cases_are_a2_only_diagnostics(tmp_path: Path) -> None:
    path = materialize_gate1(fixture_path=FIXTURE, output_dir=tmp_path / "campaign")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for row in manifest["runs"]:
        if "fallback" not in row["case_id"]:
            continue
        config = json.loads(
            (path.parent / row["config"]).read_text(encoding="utf-8")
        )
        mode = config["backend_options"]["phase2g_a2_identity_mode"]
        assert mode == (row["identity_mode"] if row["policy"] == "A2" else "normal")
