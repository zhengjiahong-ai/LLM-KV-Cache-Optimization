from pathlib import Path

from kvopt.profiling.phase2g_a2_value_smoke import EXPECTED_RUN_IDS


def test_smoke_contract_targets_f4_and_f6_paired_arms() -> None:
    assert EXPECTED_RUN_IDS == (
        "f4-draw-06-a0-repeat-1",
        "f4-draw-06-a2-repeat-1",
        "f6-draw-02-a0-repeat-1",
        "f6-draw-02-a2-repeat-1",
    )
    assert all(Path(run_id).name == run_id for run_id in EXPECTED_RUN_IDS)
