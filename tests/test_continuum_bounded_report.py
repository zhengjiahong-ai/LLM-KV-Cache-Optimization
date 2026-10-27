from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import kvopt.profiling.continuum_bounded_report as report_module
import kvopt.workload.continuum_bounded_pipeline as pipeline_module


def _evaluated(binding: dict[str, object], *, mechanism: str) -> dict[str, object]:
    return {
        "run_id": binding["run_id"],
        "group_id": binding["group_id"],
        "pressure_regime": binding["pressure_regime"],
        "arm": binding["arm"],
        "status": "VALID",
        "mechanism_status": mechanism,
        "request_outcomes": {"request": {"N": 16}},
        "totals": {
            "aggregate_recomputed_tokens": 1,
            "aggregate_actual_prefill_tokens": 1,
            "aggregate_new_suffix_tokens": 0,
        },
        "selection_sequence": [],
        "physical_eviction_signature": [],
        "profile_cost_ordering_status": "NOT_APPLICABLE_COLD_START",
    }


def _manifest() -> dict[str, object]:
    runs: list[dict[str, object]] = []
    for group_index in range(1, 10):
        group_id = f"g{group_index:02d}-group"
        for regime in ("moderate", "deep"):
            for arm in ("A0", "A1", "A2"):
                runs.append(
                    {
                        "run_id": f"{group_id}-{regime}-{arm.lower()}-repeat-1",
                        "group_id": group_id,
                        "pressure_regime": regime,
                        "arm": arm,
                    }
                )
    return {"runs": runs}


def test_report_keeps_not_realized_run_without_invalidating_metrics(
    tmp_path: Path, monkeypatch,
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    runs_root = tmp_path / "runs"
    for row in manifest["runs"]:  # type: ignore[index]
        (runs_root / row["run_id"]).mkdir(parents=True)  # type: ignore[index]

    def fake_evaluate(_run_dir: Path, binding: dict[str, object]) -> dict[str, object]:
        mechanism = "NOT_REALIZED" if binding["run_id"] == manifest["runs"][0]["run_id"] else "REALIZED"  # type: ignore[index]
        return _evaluated(binding, mechanism=mechanism)

    monkeypatch.setattr(report_module, "evaluate_run", fake_evaluate)
    report = report_module.build_report(
        manifest_path=manifest_path,
        runs_root=runs_root,
    )

    assert report["gate"] == "PASS"
    assert report["mechanism_status_counts"] == {"NOT_REALIZED": 1, "REALIZED": 53}
    assert report["statistical_unit_count"] == 9


def test_integrated_fidelity_fails_when_mechanism_is_not_realized(
    tmp_path: Path, monkeypatch,
) -> None:
    rows = [
        {
            "run_id": f"formal-{arm.lower()}",
            "group_id": "g01-short-extreme",
            "pressure_regime": "moderate",
            "arm": arm,
            "config": f"{arm.lower()}.json",
        }
        for arm in ("A0", "A1", "A2")
    ]
    manifest_path = tmp_path / "campaign" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps({"runs": rows}), encoding="utf-8")
    for row in rows:
        (manifest_path.parent / row["config"]).write_text("{}", encoding="utf-8")
    output_root = tmp_path / "preflight"

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["VLLM_ENABLE_V1_MULTIPROCESSING"] == "0"
        run_id = command[command.index("--run-id") + 1]
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    def fake_evaluate(_run_dir: Path, binding: dict[str, object]) -> dict[str, object]:
        return _evaluated(
            binding,
            mechanism="NOT_REALIZED" if binding["arm"] == "A2" else "REALIZED",
        )

    monkeypatch.setattr(pipeline_module.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_module, "evaluate_run", fake_evaluate)
    result = pipeline_module._run_fidelity_preflight(
        repository=tmp_path,
        manifest_path=manifest_path,
        output_root=output_root,
    )

    assert result["status"] == "FAIL"
    assert result["cross_arm_native_prompt_tokens_equal"] is True


def test_resource_preflight_runs_in_disposable_process(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    output = tmp_path / "resource.json"

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert "resource-preflight" in command
        assert "--source-freeze" in command
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["VLLM_ENABLE_V1_MULTIPROCESSING"] == "0"
        output.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pipeline_module.subprocess, "run", fake_run)
    result = pipeline_module._run_resource_preflight(
        repository=tmp_path,
        source_freeze_path=source,
        output_path=output,
    )

    assert result == {"status": "PASS"}


def test_a1_diagnostics_ignore_empty_allocation_traces_and_match_release() -> None:
    key = ["program-a", "prefix-a"]
    events = (
        {
            "event_type": "COST_AWARE_RELEASE_DECISION",
            "payload": {"selection_trace": []},
        },
        {
            "event_type": "FORCED_RELEASE_DECISION",
            "payload": {
                "required_blocks": 3,
                "selected_releases": [
                    {"program_id": key[0], "prefix_id": key[1]}
                ],
            },
        },
        {
            "event_type": "COST_AWARE_RELEASE_DECISION",
            "payload": {
                "selection_trace": [
                    {
                        "key": key,
                        "scores": [
                            {
                                "key": key,
                                "reuse_proxy": 0.2,
                                "new_blocks": 4,
                                "deadline": 2.0,
                            },
                            {
                                "key": ["program-b", "prefix-b"],
                                "reuse_proxy": 0.7,
                                "new_blocks": 5,
                                "deadline": 1.0,
                            },
                        ],
                    }
                ]
            },
        },
    )

    result = report_module._a1_diagnostics(SimpleNamespace(events=events))

    assert result["decision_count"] == 1
    assert result["q_spans"] == [0.5]
    assert result["earliest_deadline_match_count"] == 0
    assert result["minimum_overshoot_match_count"] == 1
