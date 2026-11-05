from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from kvopt.workload.phase3_load_calibration import (
    LOADS,
    materialize_load_calibration,
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    groups = []
    for group_index in range(1, 21):
        sessions = []
        timeline = []
        for session_index in range(2):
            program = f"repo{group_index}-{session_index}__task-{group_index}"
            calls = []
            selected = []
            for turn in range(1, 13):
                request_id = f"{program}:turn:{turn}"
                tokens = [group_index + session_index] * (16 * turn)
                calls.append(
                    {
                        "request_id": request_id,
                        "rendered_prompt": request_id,
                        "submitted_token_ids": tokens,
                        "model_submit_monotonic_seconds": float(turn * 2),
                        "model_completion_monotonic_seconds": float(turn * 2 + 1),
                    }
                )
                selected.append(
                    {
                        "request_id": request_id,
                        "token_count": len(tokens),
                        "token_ids_sha256": _sha(tokens),
                    }
                )
                timeline.extend(
                    (
                        {
                            "boundary_id": f"arrival:{request_id}",
                            "logical_timestamp": float(turn * 2 + session_index / 4),
                            "source": "submit",
                            "kind": "ARRIVAL",
                            "request_id": request_id,
                        },
                        {
                            "boundary_id": f"completion:{request_id}",
                            "logical_timestamp": float(turn * 2 + 1 + session_index / 4),
                            "source": "complete",
                            "kind": "COMPLETION",
                            "request_id": request_id,
                        },
                    )
                )
            sidecar = tmp_path / f"{program}.json"
            sidecar.write_text(json.dumps({"model_calls": calls}), encoding="utf-8")
            sessions.append(
                {
                    "instance_id": program,
                    "sidecar_path": str(sidecar),
                    "sidecar_sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest(),
                    "selected_requests": selected,
                }
            )
        timeline.sort(
            key=lambda row: (
                row["logical_timestamp"],
                0 if row["kind"] == "ARRIVAL" else 1,
                row["boundary_id"],
            )
        )
        order = [row["request_id"] for row in timeline if row["kind"] == "ARRIVAL"]
        history = {}
        completed = {session["instance_id"]: [] for session in sessions}
        for row in timeline:
            request_id = row["request_id"]
            program = request_id.split(":turn:", 1)[0]
            if row["kind"] == "ARRIVAL":
                history[request_id] = list(completed[program])
            else:
                completed[program].append(request_id)
        groups.append(
            {
                "group_id": f"g{group_index:02d}",
                "sessions": sessions,
                "frozen_request_order": order,
                "native_enqueue_order": order,
                "history_predecessors": history,
                "replay_timeline": timeline,
            }
        )
    seal = tmp_path / "seal.json"
    seal.write_text(
        json.dumps({"schema_version": "phase3.cohort_seal.v1", "groups": groups}),
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    return seal, profile


def test_materializes_forty_authorized_a0_calibration_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seal, profile = _fixture(tmp_path)
    monkeypatch.setattr(
        "kvopt.workload.phase3_native_preflight.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "git-sha\n", ""),
    )
    monkeypatch.setattr(
        "kvopt.workload.phase3_load_calibration.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "git-sha\n", ""),
    )

    manifest = materialize_load_calibration(
        repository=tmp_path,
        seal_path=seal,
        profile_path=profile,
        output_dir=tmp_path / "output",
    )

    assert manifest["planned_run_count"] == 40
    assert manifest["execution_authorized"] is True
    assert manifest["candidate_grid"] == LOADS
    assert {row["load_level"] for row in manifest["runs"]} == set(LOADS)
    for row in manifest["runs"]:
        config = json.loads(
            (tmp_path / "output" / row["config"]).read_text(encoding="utf-8")
        )
        assert config["backend_options"]["phase3_arm"] == "A0"
        assert config["cache"]["block_override"] == 2048
        stages = config["backend_options"][
            "controlled_pressure_stages_by_boundary"
        ]
        assert len(stages) == 1
        assert next(iter(stages.values()))["stop_on_forced_release"] is False
        assert sum(
            boundary["kind"] == "PRESSURE"
            for boundary in config["controlled_sparse_replay"]["boundaries"]
        ) == 1


def test_materializer_rejects_non_twenty_group_seal(
    tmp_path: Path,
) -> None:
    seal, profile = _fixture(tmp_path)
    document = json.loads(seal.read_text(encoding="utf-8"))
    document["groups"].pop()
    seal.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="twenty frozen groups"):
        materialize_load_calibration(
            repository=tmp_path,
            seal_path=seal,
            profile_path=profile,
            output_dir=tmp_path / "output",
        )
