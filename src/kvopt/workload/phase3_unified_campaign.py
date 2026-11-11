"""Fail-closed controller for the authorized Phase 3 Option F 270-run campaign."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from kvopt.profiling.phase3_nec import (
    evaluate_phase3_nec_arm,
    evaluate_phase3_nec_cell,
)

from .phase3_materialize import ARMS, pressure_request_contract
from .phase3_option_f import evaluate_noise, evaluate_option_f_results

NOISE_COUNT = 30
MAIN_COUNT = 240
TOTAL_COUNT = NOISE_COUNT + MAIN_COUNT
_CONDITIONS = ("C1", "C2")


def validate_native_environment(
    *,
    expected_gpu: str = "NVIDIA GeForce RTX 4090 D",
    expected_vllm: str = "0.27.1",
    expected_torch: str = "2.13.0+cu130",
    expected_cuda: str = "13.0",
) -> dict[str, object]:
    """Bind the reviewed Native environment and refuse an occupied GPU."""

    processes = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if processes:
        raise RuntimeError(f"GPU already has active compute processes: {processes}")
    query = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=uuid,pci.bus_id,name,memory.used,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fields = [field.strip() for field in query.split(",")]
    if len(fields) != 6:
        raise ValueError("unexpected nvidia-smi GPU inventory")
    gpu = fields[2]
    if gpu != expected_gpu:
        raise ValueError(f"GPU differs from freeze: expected={expected_gpu}, observed={gpu}")

    # Version inspection follows the idle query and deliberately avoids
    # get_device_name(), which would create a CUDA context in the controller.
    import torch

    vllm_version = importlib.metadata.version("vllm")
    if vllm_version != expected_vllm:
        raise ValueError("vLLM version differs from freeze")
    if torch.__version__ != expected_torch or torch.version.cuda != expected_cuda:
        raise ValueError("PyTorch/CUDA version differs from freeze")
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access CUDA")
    return {
        "schema_version": "phase3.option_f_native_environment.v1",
        "status": "PASS",
        "gpu": gpu,
        "gpu_query": query,
        "vllm": vllm_version,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "active_compute_processes": [],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _write_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _events(path: Path) -> list[dict[str, object]]:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path} event must be an object")
        result.append(value)
    return result


def _git_sha(repository: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_dirty(repository: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


@dataclass(frozen=True, slots=True)
class FrozenInputs:
    repository: Path
    g0_directory: Path
    input_directory: Path
    cohort_seal_path: Path
    authorization_path: Path


@dataclass(frozen=True, slots=True)
class RunSpec:
    stage: str
    run_id: str
    group_id: str
    condition: str
    arm: str
    repeat: int
    config_path: Path
    config_sha256: str
    stratum: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedCampaign:
    git_sha: str
    g0: dict[str, object]
    classification: dict[str, object]
    noise_plan: dict[str, object]
    main_plan: dict[str, object]
    cohort: dict[str, object]
    authorization: dict[str, object]
    noise_runs: tuple[RunSpec, ...]
    main_runs: tuple[RunSpec, ...]


def _expected_noise_rows(plan: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = plan.get("runs")
    if not isinstance(rows, list) or len(rows) != NOISE_COUNT:
        raise ValueError("Noise plan must contain exactly 30 runs")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Noise plan run must be an object")
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or run_id in result:
            raise ValueError("Noise plan Run IDs must be present and unique")
        result[run_id] = row
    return result


def _main_input_rows(input_directory: Path, manifest: Mapping[str, object]) -> dict[str, dict[str, object]]:
    cells = manifest.get("cells")
    if not isinstance(cells, list) or len(cells) != 40:
        raise ValueError("Main input manifest must bind exactly 40 cells")
    result: dict[str, dict[str, object]] = {}
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise TypeError("Main input cell must be an object")
        group = cell.get("group_id")
        condition = cell.get("condition")
        directory = cell.get("directory")
        if not all(isinstance(value, str) for value in (group, condition, directory)):
            raise TypeError("Main input cell identity must use strings")
        cell_directory = input_directory / str(directory)
        manifest_path = cell_directory / "manifest.json"
        if _sha256(manifest_path) != cell.get("manifest_sha256"):
            raise ValueError(f"Main cell manifest hash mismatch: {group}/{condition}")
        cell_manifest = _read(manifest_path)
        runs = cell_manifest.get("runs")
        if not isinstance(runs, list) or len(runs) != len(ARMS):
            raise ValueError(f"Main cell arm inventory is incomplete: {group}/{condition}")
        for run in runs:
            if not isinstance(run, Mapping):
                raise TypeError("Main cell run must be an object")
            run_id = run.get("run_id")
            arm = run.get("arm")
            config = run.get("config")
            if not all(isinstance(value, str) for value in (run_id, arm, config)):
                raise TypeError("Main cell run identity must use strings")
            config_path = cell_directory / str(config)
            if _sha256(config_path) != run.get("config_sha256"):
                raise ValueError(f"Main config hash mismatch: {run_id}")
            if run_id in result:
                raise ValueError(f"duplicate Main input Run ID: {run_id}")
            result[str(run_id)] = {
                "group_id": group,
                "condition": condition,
                "arm": arm,
                "config_path": config_path,
                "config_sha256": str(run["config_sha256"]),
            }
    return result


def validate_campaign(inputs: FrozenInputs) -> ValidatedCampaign:
    """Validate every frozen identity before any GPU process is started."""

    repository = inputs.repository.resolve()
    g0_directory = inputs.g0_directory.resolve()
    input_directory = inputs.input_directory.resolve()
    paths = {
        "g0": g0_directory / "g0-freeze-manifest.json",
        "candidate": g0_directory / "g0-freeze-candidate.json",
        "classification": g0_directory / "calibration-classification.json",
        "noise_plan": g0_directory / "noise-run-plan.json",
        "main_plan": g0_directory / "main-run-plan.json",
        "bundle": input_directory / "manifest.json",
        "noise_inputs": input_directory / "noise-input-manifest.json",
        "main_inputs": input_directory / "main-input-manifest.json",
    }
    for path in (*paths.values(), inputs.cohort_seal_path, inputs.authorization_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    g0 = _read(paths["g0"])
    classification = _read(paths["classification"])
    noise_plan = _read(paths["noise_plan"])
    main_plan = _read(paths["main_plan"])
    bundle = _read(paths["bundle"])
    noise_inputs = _read(paths["noise_inputs"])
    main_inputs = _read(paths["main_inputs"])
    cohort = _read(inputs.cohort_seal_path)
    authorization = _read(inputs.authorization_path)

    if g0.get("schema_version") != "phase3.option_f_g0_freeze_manifest.v1":
        raise ValueError("unsupported G0 freeze manifest")
    bindings = {
        "candidate_sha256": paths["candidate"],
        "classification_sha256": paths["classification"],
        "noise_plan_sha256": paths["noise_plan"],
        "main_plan_sha256": paths["main_plan"],
        "input_bundle_sha256": paths["bundle"],
    }
    for field, path in bindings.items():
        if g0.get(field) != _sha256(path):
            raise ValueError(f"G0 binding mismatch: {field}")
    candidate = _read(paths["candidate"])
    evidence = candidate.get("a0_execution_evidence")
    if not isinstance(evidence, Mapping) or not evidence:
        raise ValueError("G0 candidate lacks external A0 execution evidence")
    for name, binding in evidence.items():
        if not isinstance(binding, Mapping):
            raise TypeError(f"G0 external evidence binding is invalid: {name}")
        evidence_path = Path(str(binding.get("path")))
        if not evidence_path.is_absolute():
            evidence_path = repository / evidence_path
        if not evidence_path.is_file() or _sha256(evidence_path) != binding.get("sha256"):
            raise ValueError(f"G0 external evidence binding mismatch: {name}")
    if bundle.get("noise_input_manifest_sha256") != _sha256(paths["noise_inputs"]):
        raise ValueError("Noise input manifest binding mismatch")
    if bundle.get("main_input_manifest_sha256") != _sha256(paths["main_inputs"]):
        raise ValueError("Main input manifest binding mismatch")
    if any(
        document.get("execution_authorized") is not False
        for document in (g0, noise_plan, main_plan, bundle, noise_inputs, main_inputs)
    ):
        raise ValueError("frozen G0 inputs must remain independently unauthorized")

    git_sha = _git_sha(repository)
    if _git_dirty(repository):
        raise ValueError("unified campaign requires a clean worktree")
    expected_authorization = {
        "schema_version": "phase3.option_f_unified_execution_authorization.v1",
        "g0_accepted": True,
        "one_shot_270_run_pipeline_authorized": True,
        "noise_runs_authorized": NOISE_COUNT,
        "main_runs_authorized": MAIN_COUNT,
        "intermediate_manual_m1_review_required": False,
        "git_sha": git_sha,
        "g0_freeze_manifest_sha256": _sha256(paths["g0"]),
        "noise_plan_sha256": _sha256(paths["noise_plan"]),
        "main_plan_sha256": _sha256(paths["main_plan"]),
        "input_bundle_sha256": _sha256(paths["bundle"]),
    }
    for field, expected in expected_authorization.items():
        if authorization.get(field) != expected:
            raise ValueError(f"unified execution authorization mismatch: {field}")

    planned_noise = _expected_noise_rows(noise_plan)
    noise_rows = noise_inputs.get("runs")
    if not isinstance(noise_rows, list) or len(noise_rows) != NOISE_COUNT:
        raise ValueError("Noise input manifest must contain exactly 30 runs")
    noise_specs = []
    seen_noise: set[str] = set()
    for row in noise_rows:
        if not isinstance(row, Mapping):
            raise TypeError("Noise input run must be an object")
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or run_id in seen_noise or run_id not in planned_noise:
            raise ValueError("Noise input Run ID differs from frozen plan")
        seen_noise.add(run_id)
        planned = planned_noise[run_id]
        for field in ("group_id", "condition", "arm", "repeat", "stratum"):
            if row.get(field) != planned.get(field):
                raise ValueError(f"Noise input identity mismatch: {run_id}/{field}")
        config_path = input_directory / str(row["config"])
        if _sha256(config_path) != row.get("config_sha256"):
            raise ValueError(f"Noise config hash mismatch: {run_id}")
        noise_specs.append(
            RunSpec(
                stage="NOISE",
                run_id=run_id,
                group_id=str(row["group_id"]),
                condition=str(row["condition"]),
                arm="A0",
                repeat=int(row["repeat"]),
                config_path=config_path,
                config_sha256=str(row["config_sha256"]),
                stratum=str(row["stratum"]),
            )
        )
    if seen_noise != set(planned_noise):
        raise ValueError("Noise input Run ID set differs from frozen plan")

    planned_main_rows = main_plan.get("runs")
    if not isinstance(planned_main_rows, list) or len(planned_main_rows) != MAIN_COUNT:
        raise ValueError("Main plan must contain exactly 240 runs")
    planned_main = {}
    for row in planned_main_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("run_id"), str):
            raise TypeError("Main plan run identity is invalid")
        if row["run_id"] in planned_main:
            raise ValueError("Main plan Run IDs must be unique")
        planned_main[str(row["run_id"])] = row
    materialized_main = _main_input_rows(input_directory, main_inputs)
    if set(materialized_main) != set(planned_main):
        raise ValueError("Main input Run ID set differs from frozen plan")
    main_specs = []
    for run_id, planned in planned_main.items():
        materialized = materialized_main[run_id]
        for field in ("group_id", "condition", "arm"):
            if materialized[field] != planned.get(field):
                raise ValueError(f"Main input identity mismatch: {run_id}/{field}")
        main_specs.append(
            RunSpec(
                stage="MAIN",
                run_id=run_id,
                group_id=str(planned["group_id"]),
                condition=str(planned["condition"]),
                arm=str(planned["arm"]),
                repeat=int(planned["repeat"]),
                config_path=Path(materialized["config_path"]),
                config_sha256=str(materialized["config_sha256"]),
            )
        )
    expected_grid = {
        (f"g{index:02d}", condition, arm)
        for index in range(1, 21)
        for condition in _CONDITIONS
        for arm in ARMS
    }
    if {(row.group_id, row.condition, row.arm) for row in main_specs} != expected_grid:
        raise ValueError("Main plan differs from frozen 20x2x6 grid")

    return ValidatedCampaign(
        git_sha=git_sha,
        g0=g0,
        classification=classification,
        noise_plan=noise_plan,
        main_plan=main_plan,
        cohort=cohort,
        authorization=authorization,
        noise_runs=tuple(noise_specs),
        main_runs=tuple(main_specs),
    )


def _cohort_group(cohort: Mapping[str, object], group_id: str) -> Mapping[str, object]:
    groups = cohort.get("groups")
    if not isinstance(groups, list):
        raise TypeError("Cohort Seal lacks groups")
    matches = [row for row in groups if isinstance(row, Mapping) and row.get("group_id") == group_id]
    if len(matches) != 1:
        raise ValueError(f"Cohort Seal does not uniquely bind {group_id}")
    return matches[0]


def _contracts(group: Mapping[str, object]) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str]],
    dict[tuple[str, str], tuple[tuple[str, str], ...]],
]:
    order = group.get("frozen_request_order")
    enqueue = group.get("native_enqueue_order")
    predecessors = group.get("history_predecessors")
    if not isinstance(order, list) or not isinstance(enqueue, list) or not isinstance(predecessors, Mapping):
        raise TypeError("Cohort Group lacks request-history contracts")

    def identity(value: object) -> tuple[str, str]:
        if not isinstance(value, str) or ":turn:" not in value:
            raise ValueError("invalid frozen request identity")
        return value.split(":turn:", 1)[0], value

    frozen = [identity(value) for value in order]
    native = [identity(value) for value in enqueue]
    history = {
        identity(request_id): tuple(identity(value) for value in values)
        for request_id, values in predecessors.items()
        if isinstance(values, list)
    }
    return frozen, native, history


def evaluate_run(spec: RunSpec, run_directory: Path, cohort: Mapping[str, object]) -> dict[str, object]:
    manifest = _read(run_directory / "run.json")
    if manifest.get("status") != "success" or manifest.get("run_id") != spec.run_id:
        raise ValueError(f"Native run did not succeed: {spec.run_id}")
    config = _read(spec.config_path)
    frozen, native, history = _contracts(_cohort_group(cohort, spec.group_id))
    pressure_ids = frozenset(
        request_id
        for row in pressure_request_contract(config)
        for request_id in row["request_ids"]
    )
    arm = evaluate_phase3_nec_arm(
        arm=spec.arm,
        events=_events(run_directory / "events.jsonl"),
        frozen_requests=frozen,
        native_enqueue_order=native,
        history_predecessors=history,
        pressure_request_ids=pressure_ids,
    )
    return {
        "run_id": spec.run_id,
        "group_id": spec.group_id,
        "condition": spec.condition,
        "arm": spec.arm,
        "repeat": spec.repeat,
        "stratum": spec.stratum,
        "aggregate_recomputed_tokens": arm["aggregate_recomputed_tokens"],
        "nec": arm,
        "native_run_directory": str(run_directory),
    }


def execute_native_run(spec: RunSpec, output_root: Path, timeout_seconds: int) -> Path:
    """Execute one run in a fresh process so no KV state crosses run boundaries."""

    command = [
        sys.executable,
        "-m",
        "kvopt.workload.phase2_single_runner",
        "--config",
        str(spec.config_path),
        "--output-root",
        str(output_root),
        "--run-id",
        spec.run_id,
    ]
    logs = output_root.parent / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / f"{spec.run_id}.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            os.killpg(process.pid, signal.SIGINT)
            deadline = time.monotonic() + 60
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.25)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise TimeoutError(f"Native run timed out: {spec.run_id}") from error
    if return_code != 0:
        raise RuntimeError(f"Native run failed: {spec.run_id} ({return_code})")
    return output_root / spec.run_id


class UnifiedCampaignController:
    """Persist every transition and never authorize Main before Noise passes."""

    def __init__(
        self,
        *,
        campaign: ValidatedCampaign,
        output_root: Path,
        executor: Callable[[RunSpec, Path, int], Path] = execute_native_run,
        run_evaluator: Callable[[RunSpec, Path, Mapping[str, object]], dict[str, object]] = evaluate_run,
        timeout_seconds: int = 1800,
        environment_report: Mapping[str, object] | None = None,
    ) -> None:
        self.campaign = campaign
        self.output_root = output_root.resolve()
        self.executor = executor
        self.run_evaluator = run_evaluator
        self.timeout_seconds = timeout_seconds
        self.environment_report = environment_report
        self.state_path = self.output_root / "pipeline-state.json"
        self.runs_root = self.output_root / "native-runs"
        self.results_root = self.output_root / "results"

    def _new_state(self) -> dict[str, object]:
        return {
            "schema_version": "phase3.option_f_unified_pipeline_state.v1",
            "git_sha": self.campaign.git_sha,
            "status": "NOISE_RUNNING",
            "main_authorization_state": "LOCKED_PENDING_AUTOMATED_NOISE_GATE",
            "completed_noise_run_ids": [],
            "completed_main_run_ids": [],
            "failure": None,
        }

    def _state(self) -> dict[str, object]:
        if not self.state_path.exists():
            if self.output_root.exists() and any(self.output_root.iterdir()):
                raise ValueError("non-empty output directory lacks pipeline state")
            self.output_root.mkdir(parents=True, exist_ok=True)
            self.runs_root.mkdir()
            self.results_root.mkdir()
            state = self._new_state()
            _write_atomic(self.state_path, state)
            if self.environment_report is not None:
                if self.environment_report.get("status") != "PASS":
                    raise ValueError("Native environment validation did not pass")
                _write_atomic(
                    self.output_root / "preflight-validation.json",
                    dict(self.environment_report),
                )
            return state
        state = _read(self.state_path)
        if state.get("git_sha") != self.campaign.git_sha:
            raise ValueError("pipeline state Git SHA differs from execution code")
        return state

    def _result_path(self, spec: RunSpec) -> Path:
        return self.results_root / f"{spec.run_id}.json"

    def _run_stage(
        self, specs: Sequence[RunSpec], completed_field: str, state: dict[str, object]
    ) -> list[dict[str, object]]:
        completed = state.get(completed_field)
        if not isinstance(completed, list) or not all(isinstance(value, str) for value in completed):
            raise TypeError(f"pipeline state {completed_field} is invalid")
        completed_set = set(completed)
        results = []
        for spec in specs:
            result_path = self._result_path(spec)
            if spec.run_id in completed_set:
                if not result_path.is_file():
                    raise ValueError(f"completed run lacks persisted result: {spec.run_id}")
                results.append(_read(result_path))
                continue
            if result_path.exists() or (self.runs_root / spec.run_id).exists():
                raise ValueError(f"uncommitted partial run requires manual audit: {spec.run_id}")
            run_directory = self.executor(spec, self.runs_root, self.timeout_seconds)
            result = self.run_evaluator(spec, run_directory, self.campaign.cohort)
            _write_atomic(result_path, result)
            completed.append(spec.run_id)
            completed_set.add(spec.run_id)
            _write_atomic(self.state_path, state)
            results.append(result)
        return results

    def _evaluate_main_cells(self) -> list[dict[str, object]]:
        """Re-evaluate all six arms together and enforce cross-arm N/E equality."""

        reports = []
        by_cell: dict[tuple[str, str], list[RunSpec]] = {}
        for spec in self.campaign.main_runs:
            by_cell.setdefault((spec.group_id, spec.condition), []).append(spec)
        if len(by_cell) != 40:
            raise ValueError("Main N/E/C evaluation requires exactly 40 cells")
        cell_root = self.output_root / "nec-cells"
        cell_root.mkdir(exist_ok=True)
        for (group_id, condition), specs in sorted(by_cell.items()):
            if {spec.arm for spec in specs} != set(ARMS):
                raise ValueError(f"Main cell lacks six arms: {group_id}/{condition}")
            group = _cohort_group(self.campaign.cohort, group_id)
            frozen, native, history = _contracts(group)
            events_by_arm = {
                spec.arm: _events(self.runs_root / spec.run_id / "events.jsonl")
                for spec in specs
            }
            manifest_path = specs[0].config_path.parent / "manifest.json"
            if any(spec.config_path.parent != manifest_path.parent for spec in specs):
                raise ValueError(f"Main cell configs span directories: {group_id}/{condition}")
            report = evaluate_phase3_nec_cell(
                events_by_arm=events_by_arm,
                frozen_requests=frozen,
                native_enqueue_order=native,
                history_predecessors=history,
                cell_manifest=_read(manifest_path),
            )
            report.update({"group_id": group_id, "condition": condition})
            if report.get("status") != "PASS":
                raise ValueError(f"Main N/E/C cell failed: {group_id}/{condition}")
            _write_atomic(cell_root / f"{group_id}-{condition.lower()}.json", report)
            reports.append(report)
        return reports

    def _finalize_evidence(self) -> tuple[Path, str]:
        files = sorted(
            path
            for path in self.output_root.rglob("*")
            if path.is_file() and path.name != "sha256-manifest.txt"
        )
        manifest = self.output_root / "sha256-manifest.txt"
        manifest.write_text(
            "".join(
                f"{_sha256(path)}  {path.relative_to(self.output_root)}\n"
                for path in files
            ),
            encoding="utf-8",
        )
        archive = self.output_root.with_name(f"{self.output_root.name}-evidence.tar.gz")
        if archive.exists():
            raise FileExistsError(archive)
        temporary = archive.with_suffix(archive.suffix + ".tmp")
        with tarfile.open(temporary, "w:gz") as handle:
            handle.add(self.output_root, arcname=self.output_root.name)
        temporary.replace(archive)
        return archive, _sha256(archive)

    def run(self) -> dict[str, object]:
        state = self._state()
        if state.get("status") == "COMPLETE":
            return state
        try:
            noise_results = self._run_stage(
                self.campaign.noise_runs, "completed_noise_run_ids", state
            )
            noise_report = evaluate_noise(noise_results, self.campaign.noise_plan)
            if noise_report.get("status") != "PASS":
                raise ValueError("Noise primary estimator did not pass")
            _write_atomic(self.output_root / "noise-report.json", noise_report)
            transition = {
                "schema_version": "phase3.option_f_automatic_stage_transition.v1",
                "status": "MAIN_AUTHORIZED_BY_PIPELINE",
                "noise_run_count": len(noise_results),
                "noise_run_ids_sha256": _canonical_sha(
                    sorted(row["run_id"] for row in noise_results)
                ),
                "noise_report_sha256": _sha256(self.output_root / "noise-report.json"),
                "tied_threshold": noise_report["tied_threshold"],
                "diagnostic_ratio_status": noise_report[
                    "stratum_sigma_max_min_ratio_status"
                ],
            }
            _write_atomic(self.output_root / "stage-transition.json", transition)
            state["status"] = "MAIN_RUNNING"
            state["main_authorization_state"] = "MAIN_AUTHORIZED_BY_PIPELINE"
            _write_atomic(self.state_path, state)

            main_results = self._run_stage(
                self.campaign.main_runs, "completed_main_run_ids", state
            )
            nec_cells = self._evaluate_main_cells()
            main_report = evaluate_option_f_results(
                main_results, self.campaign.classification
            )
            main_report["nec_cell_count"] = len(nec_cells)
            main_report["nec_cells_sha256"] = _canonical_sha(nec_cells)
            _write_atomic(self.output_root / "main-report.json", main_report)
            state["status"] = "COMPLETE"
            state["main_authorization_state"] = "MAIN_COMPLETED"
            state["noise_report_sha256"] = _sha256(
                self.output_root / "noise-report.json"
            )
            state["main_report_sha256"] = _sha256(
                self.output_root / "main-report.json"
            )
            _write_atomic(self.state_path, state)
            archive, archive_sha = self._finalize_evidence()
            state["evidence_archive"] = str(archive)
            state["evidence_archive_sha256"] = archive_sha
            _write_atomic(self.state_path, state)
            return state
        except Exception as error:
            state["status"] = "FAIL_CLOSED"
            state["failure"] = f"{type(error).__name__}: {error}"
            _write_atomic(self.state_path, state)
            raise


def run_unified_campaign(
    *,
    inputs: FrozenInputs,
    output_root: Path,
    timeout_seconds: int = 1800,
    environment_report: Mapping[str, object] | None = None,
) -> dict[str, object]:
    campaign = validate_campaign(inputs)
    return UnifiedCampaignController(
        campaign=campaign,
        output_root=output_root,
        timeout_seconds=timeout_seconds,
        environment_report=environment_report,
    ).run()
