import json
from pathlib import Path

from kvopt.profiling.phase2g_a2_positive_control import evaluate_positive_control


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path, *, diverged: bool) -> tuple[Path, Path]:
    root = tmp_path / "runs"
    rows = []
    for policy in ("A0", "A2"):
        run_id = f"a2-cost-divergence-{policy.lower()}-repeat-1"
        rows.append(
            {
                "run_id": run_id,
                "case_id": "a2-cost-divergence",
                "policy": policy,
                "repeat": 1,
            }
        )
        run = root / run_id
        run.mkdir(parents=True)
        _write(run / "run.json", {"execution_status": "success"})
        events = []
        if policy == "A2":
            selected = [2] if diverged else [1]
            events = [
                {
                    "event_index": 1,
                    "event_type": "COST_AWARE_BLOCK_DECISION",
                    "payload": {
                        "identified_hashed_block_count": 2,
                        "cost_known": True,
                        "fallbacks": [],
                        "adapter_problems": [],
                        "contract_problems": [],
                        "selected_victims": selected,
                        "native_lru_victims": [1],
                        "native_hash_process_id": "p1",
                        "legal_content_hashes": [
                            {"block_id": 1, "content_hash": "h1"},
                            {"block_id": 2, "content_hash": "h2"},
                        ],
                    },
                },
                {
                    "event_index": 2,
                    "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                    "payload": {
                        "block_id": selected[0],
                        "native_cache_key_before": f"h{selected[0]}",
                        "native_hash_process_id": "p1",
                        "hash_removed_after": True,
                    },
                },
            ]
        (run / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
    campaign = tmp_path / "manifest.json"
    _write(
        campaign,
        {
            "scope": "NON_FORMAL_NATIVE_INTERVENTION_POSITIVE_CONTROL",
            "formal": False,
            "runs": rows,
        },
    )
    return campaign, root


def test_positive_control_reports_all_three_gates(tmp_path: Path) -> None:
    campaign, root = _fixture(tmp_path, diverged=True)
    report = evaluate_positive_control(campaign_manifest=campaign, run_root=root)

    assert report["gates"] == {
        "cost_evidence": "PASS",
        "selection_intervention": "PASS",
        "physical_realization": "PASS",
    }
    assert report["outcome"] == "PASS"


def test_no_selection_divergence_keeps_physical_gate_unobservable(
    tmp_path: Path,
) -> None:
    campaign, root = _fixture(tmp_path, diverged=False)
    report = evaluate_positive_control(campaign_manifest=campaign, run_root=root)

    assert report["gates"]["cost_evidence"] == "PASS"
    assert report["gates"]["selection_intervention"] == "FAIL"
    assert report["gates"]["physical_realization"] == "NOT_OBSERVABLE"
    assert report["outcome"] == "INTERVENTION_NOT_REALIZED"
