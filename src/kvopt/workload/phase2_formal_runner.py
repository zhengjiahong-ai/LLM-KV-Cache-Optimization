"""Execute a materialized Phase 2A formal campaign without replacing runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .phase2_runner import run_phase2


@dataclass(frozen=True, slots=True)
class FormalCampaignScenario:
    scenario_id: str
    family_id: str
    config_path: Path


@dataclass(frozen=True, slots=True)
class LoadedFormalCampaign:
    campaign_id: str
    manifest_path: Path
    seeds: tuple[int, ...]
    scenarios: tuple[FormalCampaignScenario, ...]


@dataclass(frozen=True, slots=True)
class FormalRunResult:
    run_id: str
    scenario_id: str
    family_id: str
    seed: int
    action: str
    status: str
    output_dir: str
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class FormalExecutionSummary:
    schema_version: str
    campaign_id: str
    campaign_manifest: str
    campaign_manifest_sha256: str
    started_at_utc: str
    ended_at_utc: str
    resume: bool
    planned_run_count: int
    executed_run_count: int
    skipped_run_count: int
    successful_run_count: int
    failed_run_count: int
    results: tuple[FormalRunResult, ...]


RunExecutor = Callable[..., Path]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def load_formal_campaign(path: str | Path) -> LoadedFormalCampaign:
    """Validate a materialized formal campaign manifest."""

    manifest_path = Path(path).resolve()
    value = _json_object(manifest_path)
    if value.get("schema_version") != "phase2a.formal_campaign.v1":
        raise ValueError("unsupported formal campaign schema_version")
    if value.get("campaign_kind") != "formal":
        raise ValueError("campaign_kind must be formal")
    campaign_id = _text(value.get("campaign_id"), "campaign_id")

    raw_seeds = value.get("seeds")
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ValueError("campaign seeds must be a non-empty list")
    seeds: list[int] = []
    for seed in raw_seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("campaign seeds must be non-negative integers")
        seeds.append(seed)
    if len(seeds) != len(set(seeds)):
        raise ValueError("campaign seeds must be unique")

    raw_scenarios = value.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("campaign scenarios must be a non-empty list")
    scenarios: list[FormalCampaignScenario] = []
    identities: set[str] = set()
    for raw_scenario in raw_scenarios:
        if not isinstance(raw_scenario, dict):
            raise TypeError("campaign scenario must be an object")
        scenario_id = _text(raw_scenario.get("scenario_id"), "scenario_id")
        family_id = _text(raw_scenario.get("family_id"), "family_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", scenario_id) is None:
            raise ValueError("scenario_id must be a safe path component")
        if scenario_id in identities:
            raise ValueError("campaign scenario_id must be unique")
        identities.add(scenario_id)
        config_name = _text(raw_scenario.get("config"), "scenario config")
        config_path = Path(config_name)
        if not config_path.is_absolute():
            config_path = (manifest_path.parent / config_path).resolve()
        if not config_path.is_file():
            raise ValueError(f"scenario config does not exist: {config_path}")
        config = _json_object(config_path)
        if config.get("profiling_scenario_id") != scenario_id:
            raise ValueError("scenario config has mismatched profiling_scenario_id")
        if config.get("profiling_scenario_family") != family_id:
            raise ValueError("scenario config has mismatched profiling_scenario_family")
        scenarios.append(FormalCampaignScenario(scenario_id, family_id, config_path))

    expected_runs = len(seeds) * len(scenarios)
    if value.get("predeclared_repetitions_per_scenario") != len(seeds):
        raise ValueError("campaign repetition declaration does not match seeds")
    if value.get("planned_run_count") != expected_runs:
        raise ValueError("campaign planned_run_count is inconsistent")
    return LoadedFormalCampaign(
        campaign_id=campaign_id,
        manifest_path=manifest_path,
        seeds=tuple(seeds),
        scenarios=tuple(scenarios),
    )


def _selected_runs(
    campaign: LoadedFormalCampaign,
    family_ids: set[str] | None,
    scenario_ids: set[str] | None,
    seeds: set[int] | None,
) -> tuple[tuple[FormalCampaignScenario, int], ...]:
    selected = tuple(
        (scenario, seed)
        for scenario in campaign.scenarios
        for seed in campaign.seeds
        if (family_ids is None or scenario.family_id in family_ids)
        and (scenario_ids is None or scenario.scenario_id in scenario_ids)
        and (seeds is None or seed in seeds)
    )
    if not selected:
        raise ValueError("campaign filters selected no runs")
    return selected


def _materialize_run_config(
    scenario: FormalCampaignScenario,
    seed: int,
    output_root: Path,
) -> Path:
    config = _json_object(scenario.config_path)
    trace_value = _text(config.get("trace"), "config.trace")
    trace_path = Path(trace_value)
    if not trace_path.is_absolute():
        trace_path = (scenario.config_path.parent / trace_path).resolve()
    if not trace_path.is_file():
        raise ValueError(f"scenario trace does not exist: {trace_path}")
    config["trace"] = str(trace_path)
    config["seed"] = seed
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix=".phase2a-formal-run-",
        dir=output_root,
        delete=False,
    ) as stream:
        json.dump(config, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        return Path(stream.name)


def _existing_result(
    run_id: str,
    scenario: FormalCampaignScenario,
    seed: int,
    run_dir: Path,
) -> FormalRunResult:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        return FormalRunResult(
            run_id,
            scenario.scenario_id,
            scenario.family_id,
            seed,
            "skipped_existing",
            "invalid_existing_run",
            str(run_dir),
            "existing run directory has no run.json",
        )
    try:
        manifest = _json_object(manifest_path)
        status = manifest.get("status")
        if status not in {"success", "failed"}:
            raise ValueError("existing run status is not terminal")
        failure = manifest.get("failure_reason")
        return FormalRunResult(
            run_id,
            scenario.scenario_id,
            scenario.family_id,
            seed,
            "skipped_existing",
            status,
            str(run_dir),
            failure if isinstance(failure, str) else None,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return FormalRunResult(
            run_id,
            scenario.scenario_id,
            scenario.family_id,
            seed,
            "skipped_existing",
            "invalid_existing_run",
            str(run_dir),
            f"{type(error).__name__}: {error}",
        )


def execute_formal_campaign(
    campaign_path: str | Path,
    output_root: str | Path,
    *,
    resume: bool = False,
    family_ids: Iterable[str] | None = None,
    scenario_ids: Iterable[str] | None = None,
    seeds: Iterable[int] | None = None,
    run_executor: RunExecutor = run_phase2,
) -> tuple[FormalExecutionSummary, Path]:
    """Execute selected formal runs and preserve every terminal result."""

    campaign = load_formal_campaign(campaign_path)
    selected = _selected_runs(
        campaign,
        None if family_ids is None else set(family_ids),
        None if scenario_ids is None else set(scenario_ids),
        None if seeds is None else set(seeds),
    )
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    collisions = [
        output / f"{scenario.scenario_id}-seed-{seed}"
        for scenario, seed in selected
        if (output / f"{scenario.scenario_id}-seed-{seed}").exists()
    ]
    if collisions and not resume:
        raise FileExistsError(
            f"formal run output already exists: {collisions[0]}"
        )

    started_at = _now()
    results: list[FormalRunResult] = []
    for scenario, seed in selected:
        run_id = f"{scenario.scenario_id}-seed-{seed}"
        run_dir = output / run_id
        if run_dir.exists():
            results.append(
                _existing_result(run_id, scenario, seed, run_dir)
            )
            continue

        temp_path: Path | None = None
        try:
            temp_path = _materialize_run_config(scenario, seed, output)
            produced = run_executor(
                temp_path,
                output_root=output,
                run_id=run_id,
            )
            manifest = _json_object(produced / "run.json")
            status = manifest.get("status")
            if status not in {"success", "failed"}:
                raise ValueError("executed run status is not terminal")
            failure = manifest.get("failure_reason")
            results.append(
                FormalRunResult(
                    run_id,
                    scenario.scenario_id,
                    scenario.family_id,
                    seed,
                    "executed",
                    status,
                    str(produced),
                    failure if isinstance(failure, str) else None,
                )
            )
        except (OSError, ValueError, TypeError, RuntimeError, ImportError) as error:
            results.append(
                FormalRunResult(
                    run_id,
                    scenario.scenario_id,
                    scenario.family_id,
                    seed,
                    "launcher_error",
                    "failed",
                    str(run_dir),
                    f"{type(error).__name__}: {error}",
                )
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    summary = FormalExecutionSummary(
        schema_version="phase2a.formal_execution.v1",
        campaign_id=campaign.campaign_id,
        campaign_manifest=str(campaign.manifest_path),
        campaign_manifest_sha256=hashlib.sha256(
            campaign.manifest_path.read_bytes()
        ).hexdigest(),
        started_at_utc=started_at,
        ended_at_utc=_now(),
        resume=resume,
        planned_run_count=len(selected),
        executed_run_count=sum(row.action == "executed" for row in results),
        skipped_run_count=sum(row.action == "skipped_existing" for row in results),
        successful_run_count=sum(row.status == "success" for row in results),
        failed_run_count=sum(row.status != "success" for row in results),
        results=tuple(results),
    )
    summary_path = output / f"formal-execution-{uuid.uuid4().hex[:12]}.json"
    summary_path.write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary, summary_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--family", action="append", dest="families")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--vllm-metal-source-checkout", type=Path)
    arguments = parser.parse_args(argv)

    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_METAL_USE_PAGED_ATTENTION", "1")
    os.environ.setdefault("VLLM_METAL_MEMORY_FRACTION", "auto")
    os.environ.setdefault("VLLM_MLX_DEVICE", "gpu")
    os.environ.setdefault("VLLM_HOST_IP", "127.0.0.1")
    if arguments.vllm_metal_source_checkout is not None:
        os.environ["VLLM_METAL_SOURCE_CHECKOUT"] = str(
            arguments.vllm_metal_source_checkout.resolve()
        )

    summary, path = execute_formal_campaign(
        arguments.campaign,
        arguments.output_root,
        resume=arguments.resume,
        family_ids=arguments.families,
        scenario_ids=arguments.scenarios,
        seeds=arguments.seeds,
    )
    print(
        f"formal campaign complete: {summary.successful_run_count} success, "
        f"{summary.failed_run_count} failed -> {path}"
    )
    return 1 if summary.failed_run_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
