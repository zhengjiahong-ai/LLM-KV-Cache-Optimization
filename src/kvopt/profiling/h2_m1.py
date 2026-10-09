"""Validate, analyze, and seal the frozen formal H2 M1 cost curve."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .h2_calibration import _dispersion
from .ingestion import load_run_artifacts
from .runtime_evidence import build_request_runtime_evidence_table

_FULL_GRID = (
    16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 12288,
    16384, 20480, 24576, 26624, 28672, 30720,
)
_CONFIRMATORY_GRID = (8192, 12288, 16384, 20480, 24576, 26624, 28672, 30720)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small dense system by pivoted Gaussian elimination."""

    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-15:
            raise ValueError("singular model fit")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                left - factor * right
                for left, right in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(size)]


def _features(prefix_tokens: int, model: str) -> list[float]:
    scaled = prefix_tokens / max(_FULL_GRID)
    if model == "linear_no_intercept":
        return [scaled]
    if model == "affine":
        return [1.0, scaled]
    if model == "quadratic":
        return [1.0, scaled, scaled * scaled]
    raise ValueError(f"unknown model: {model}")


def _fit(points: Sequence[tuple[int, float]], model: str) -> dict[str, object]:
    rows = [_features(tokens, model) for tokens, _value in points]
    values = [value for _tokens, value in points]
    width = len(rows[0])
    matrix = [
        [sum(row[left] * row[right] for row in rows) for right in range(width)]
        for left in range(width)
    ]
    vector = [sum(row[column] * value for row, value in zip(rows, values, strict=True))
              for column in range(width)]
    scaled_coefficients = _solve(matrix, vector)
    predictions = [
        sum(coefficient * feature for coefficient, feature in zip(
            scaled_coefficients, row, strict=True
        ))
        for row in rows
    ]
    residual_sum_squares = sum(
        (value - prediction) ** 2
        for value, prediction in zip(values, predictions, strict=True)
    )
    total_sum_squares = sum((value - statistics.mean(values)) ** 2 for value in values)
    scale = max(_FULL_GRID)
    if model == "linear_no_intercept":
        coefficients = {"beta": scaled_coefficients[0] / scale}
    elif model == "affine":
        coefficients = {
            "a": scaled_coefficients[0],
            "beta": scaled_coefficients[1] / scale,
        }
    else:
        coefficients = {
            "a": scaled_coefficients[0],
            "beta": scaled_coefficients[1] / scale,
            "gamma": scaled_coefficients[2] / (scale * scale),
        }
    return {
        "model": model,
        "coefficients": coefficients,
        "scaled_coefficients": scaled_coefficients,
        "residual_sum_squares": residual_sum_squares,
        "r_squared": 1.0 - residual_sum_squares / total_sum_squares
        if total_sum_squares > 0 else None,
    }


def _predict(prefix_tokens: int, fit: dict[str, object]) -> float:
    coefficients = fit["scaled_coefficients"]
    assert isinstance(coefficients, list)
    return sum(
        coefficient * feature
        for coefficient, feature in zip(
            coefficients, _features(prefix_tokens, str(fit["model"])), strict=True
        )
    )


def _lopo_rmse(points: Sequence[tuple[int, float]], model: str) -> float:
    squared_errors = []
    for held_out in range(len(points)):
        training = [point for index, point in enumerate(points) if index != held_out]
        fit = _fit(training, model)
        tokens, observed = points[held_out]
        squared_errors.append((_predict(tokens, fit) - observed) ** 2)
    return math.sqrt(statistics.mean(squared_errors))


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered or not 0 < probability <= 1:
        raise ValueError("nearest-rank percentile requires values and probability in (0, 1]")
    return ordered[math.ceil(probability * len(ordered)) - 1]


def analyze_m1_observations(
    observations: dict[int, list[float]],
    *,
    delta_m1_seconds: float,
    iterations: int = 10_000,
    seed: int = 20261007,
) -> tuple[dict[str, object], list[dict[str, float | int]]]:
    """Apply the preregistered M1 models and stratified repeat bootstrap."""

    if tuple(observations) != _FULL_GRID:
        raise ValueError("M1 observations must use the frozen 17-point grid")
    if any(len(values) != 9 for values in observations.values()):
        raise ValueError("M1 requires nine measured repetitions per point")
    if iterations != 10_000 or seed != 20261007:
        raise ValueError("M1 bootstrap controls are frozen")
    medians = {tokens: statistics.median(values) for tokens, values in observations.items()}
    full_points = list(medians.items())
    confirmatory = [(tokens, medians[tokens]) for tokens in _CONFIRMATORY_GRID]
    models = {
        model: _fit(full_points, model)
        for model in ("linear_no_intercept", "affine", "quadratic")
    }
    observed_l1 = _lopo_rmse(confirmatory, "affine")
    observed_l2 = _lopo_rmse(confirmatory, "quadratic")
    observed_delta = observed_l1 - observed_l2
    generator = random.Random(seed)
    bootstrap: list[dict[str, float | int]] = []
    for index in range(1, iterations + 1):
        sampled_medians = {
            tokens: statistics.median(generator.choices(values, k=9))
            for tokens, values in observations.items()
        }
        sampled = [(tokens, sampled_medians[tokens]) for tokens in _CONFIRMATORY_GRID]
        l1_rmse = _lopo_rmse(sampled, "affine")
        l2_rmse = _lopo_rmse(sampled, "quadratic")
        quadratic = _fit(sampled, "quadratic")
        coefficients = quadratic["coefficients"]
        assert isinstance(coefficients, dict)
        bootstrap.append(
            {
                "iteration": index,
                "delta_fit_seconds": l1_rmse - l2_rmse,
                "gamma_seconds_per_token_squared": float(coefficients["gamma"]),
            }
        )
    deltas = [float(row["delta_fit_seconds"]) for row in bootstrap]
    gammas = [float(row["gamma_seconds_per_token_squared"]) for row in bootstrap]
    q05_delta = _percentile(deltas, 0.05)
    q95_delta = _percentile(deltas, 0.95)
    q05_gamma = _percentile(gammas, 0.05)
    q95_gamma = _percentile(gammas, 0.95)
    if observed_delta > delta_m1_seconds and q05_delta > 0 and q05_gamma > 0:
        candidate = "PASS_PENDING_REVIEW"
    elif q95_delta <= 0 or q95_gamma <= 0:
        candidate = "FAIL_PENDING_REVIEW"
    else:
        candidate = "INCONCLUSIVE_PENDING_REVIEW"
    report = {
        "schema_version": "phase2a.h2_formal_m1_outcome.v1",
        "measurement": "M1",
        "primary_observation": "isolated_native_prefill_elapsed_seconds",
        "measurement_semantics": (
            "synchronized_native_forward_execution_excludes_sampling_and_request_e2e"
        ),
        "point_summaries": [
            {
                "prefix_tokens": tokens,
                "run_values_seconds": values,
                "isolated_native_prefill": _dispersion(values),
            }
            for tokens, values in observations.items()
        ],
        "full_grid_models": models,
        "confirmatory_region": list(_CONFIRMATORY_GRID),
        "observed_lopo_rmse_l1_seconds": observed_l1,
        "observed_lopo_rmse_l2_seconds": observed_l2,
        "observed_delta_fit_seconds": observed_delta,
        "delta_M1_seconds": delta_m1_seconds,
        "bootstrap": {
            "iterations": iterations,
            "seed": seed,
            "resample_size_per_prefix_point": 9,
            "scheme": "stratified_within_prefix_point_with_replacement",
            "cross_point_rng": "single_deterministic_stream_in_frozen_grid_order",
            "point_statistic": "median",
            "percentile_rule": "nearest_rank",
            "q05_delta_fit_seconds": q05_delta,
            "q95_delta_fit_seconds": q95_delta,
            "q05_gamma_seconds_per_token_squared": q05_gamma,
            "q95_gamma_seconds_per_token_squared": q95_gamma,
        },
        "candidate_outcome": candidate,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
    }
    return report, bootstrap


def build_h2_m1_outcome_bundle(
    campaign_path: Path,
    authorization_path: Path,
    execution_path: Path,
    run_root: Path,
    output: Path,
) -> Path:
    campaign_path = campaign_path.resolve()
    authorization_path = authorization_path.resolve()
    execution_path = execution_path.resolve()
    run_root = run_root.resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if campaign.get("schema_version") != "phase2a.h2_formal_m1_campaign.v1":
        raise ValueError("unsupported formal M1 campaign")
    authorization_sha = _sha(authorization_path)
    if campaign.get("authorization_sha256") != authorization_sha:
        raise ValueError("campaign authorization hash mismatch")
    if execution.get("schema_version") != "phase2a.h2_formal_m1_execution.v1":
        raise ValueError("unsupported formal M1 execution summary")
    if execution.get("campaign_sha256") != _sha(campaign_path):
        raise ValueError("execution campaign hash mismatch")
    if execution.get("authorization_sha256") != authorization_sha:
        raise ValueError("execution authorization hash mismatch")
    if execution.get("formal_verdict_authorized") is not False:
        raise ValueError("formal verdict must remain pending review")
    result_ids = {row.get("run_id") for row in execution.get("results", [])}
    observations: dict[int, list[float]] = {}
    raw_bindings = []
    measurement_git_shas = set()
    for point in campaign["points"]:
        tokens = point["prefix_tokens"]
        values = []
        for run in point["runs"]:
            if run["run_id"] not in result_ids:
                raise ValueError(f"execution summary lacks run: {run['run_id']}")
            directory = run_root / run["run_id"]
            artifacts = load_run_artifacts(directory)
            manifest = artifacts.manifest
            if (
                manifest.get("status") != "success"
                or manifest.get("git_dirty") is not False
                or manifest.get("config_sha256") != point["runtime_config_sha256"]
                or manifest.get("trace_sha256") != point["trace_sha256"]
            ):
                raise ValueError(f"formal raw provenance is invalid: {run['run_id']}")
            measurement_git_shas.add(manifest.get("git_sha"))
            raw_bindings.append(
                {
                    "run_id": run["run_id"],
                    "role": run["role"],
                    "run_manifest_sha256": _sha(directory / "run.json"),
                    "events_sha256": _sha(directory / "events.jsonl"),
                }
            )
            if run["role"] != "measured":
                continue
            rows = build_request_runtime_evidence_table((artifacts,))
            if len(rows) != 1 or rows[0].native_prompt_tokens != tokens + 1:
                raise ValueError(f"formal request shape mismatch: {run['run_id']}")
            row = rows[0]
            if (
                row.isolated_native_prefill_elapsed_status != "available"
                or row.isolated_native_prefill_elapsed_seconds is None
            ):
                raise ValueError(f"isolated timing unavailable: {run['run_id']}")
            values.append(row.isolated_native_prefill_elapsed_seconds)
        observations[tokens] = values
    if len(measurement_git_shas) != 1 or next(iter(measurement_git_shas)) != execution.get(
        "git_sha"
    ):
        raise ValueError("formal runs must share the execution git SHA")
    outcome, bootstrap = analyze_m1_observations(
        observations,
        delta_m1_seconds=float(authorization["delta_M1_seconds"]),
        iterations=int(authorization["protocol"]["m1_rules"]["bootstrap_iterations"]),
        seed=int(authorization["protocol"]["m1_rules"]["bootstrap_seed"]),
    )
    analysis_git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", "src", "configs"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("commit analysis source/config changes before sealing")
    output.mkdir(parents=True, exist_ok=False)
    observations_path = output / "raw-observations.json"
    observations_path.write_text(
        json.dumps({str(key): value for key, value in observations.items()}, indent=2) + "\n"
    )
    outcome_path = output / "m1-outcome.json"
    outcome_path.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
    bootstrap_path = output / "bootstrap-distribution.json"
    bootstrap_path.write_text(json.dumps(bootstrap, separators=(",", ":")) + "\n")
    provenance = {
        "schema_version": "phase2a.h2_formal_m1_provenance.v1",
        "measurement_git_sha": execution["git_sha"],
        "analysis_git_sha": analysis_git_sha,
        "analysis_code_sha256": _sha(Path(__file__)),
        "authorization_sha256": authorization_sha,
        "campaign_sha256": _sha(campaign_path),
        "execution_summary_sha256": _sha(execution_path),
        "validated_run_count": len(raw_bindings),
        "measured_row_count": sum(len(values) for values in observations.values()),
        "raw_bindings": raw_bindings,
    }
    provenance_path = output / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    seal = {
        "schema_version": "phase2a.h2_formal_m1_seal.v1",
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "review_state": "PENDING_M1_M4_FORMAL_VERDICT_REVIEW",
        "candidate_outcome": outcome["candidate_outcome"],
        "files": {
            path.name: _sha(path)
            for path in (observations_path, outcome_path, bootstrap_path, provenance_path)
        },
    }
    seal_path = output / "seal.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n")
    return seal_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    path = build_h2_m1_outcome_bundle(
        arguments.campaign,
        arguments.authorization,
        arguments.execution,
        arguments.run_root,
        arguments.output,
    )
    print(f"wrote sealed H2 M1 outcome bundle: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
