"""Run the preregistered Phase 3 Agent acquisition in frozen rank order."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .continuum_w1a_runner import load_acquisition_config, run_one


def pending_candidates(
    plan: Mapping[str, object],
    *,
    runs_root: Path,
    roles: Sequence[str] = ("PRIMARY",),
) -> list[dict[str, object]]:
    """Return unattempted candidates without changing the frozen order."""

    candidates = plan.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("candidate plan candidates must be an array")
    allowed = set(roles)
    if not allowed or not allowed <= {"PRIMARY", "RESERVE"}:
        raise ValueError("roles must contain PRIMARY and/or RESERVE")
    ordered = sorted(
        (dict(row) for row in candidates if isinstance(row, dict)),
        key=lambda row: int(row["acquisition_rank"]),
    )
    expected_ranks = list(range(1, len(ordered) + 1))
    if [int(row["acquisition_rank"]) for row in ordered] != expected_ranks:
        raise ValueError("candidate acquisition ranks are not contiguous")
    result: list[dict[str, object]] = []
    for row in ordered:
        if row.get("role") not in allowed:
            continue
        instance_id = str(row.get("instance_id", ""))
        if not instance_id:
            raise ValueError("candidate identity must be non-empty")
        run_dir = runs_root / instance_id
        if run_dir.exists():
            manifest = run_dir / "run.json"
            if not manifest.is_file():
                raise ValueError(f"existing candidate directory lacks run.json: {instance_id}")
            continue
        result.append(row)
    return result


def run_batch(
    *,
    repository: Path,
    source_checkout: Path,
    config_path: Path,
    output_root: Path,
    roles: Sequence[str],
    maximum_tasks: int,
) -> list[Path]:
    if maximum_tasks <= 0:
        raise ValueError("maximum_tasks must be positive")
    _config, plan = load_acquisition_config(config_path, repository=repository)
    selected = pending_candidates(plan, runs_root=output_root, roles=roles)[
        :maximum_tasks
    ]
    outputs: list[Path] = []
    for row in selected:
        outputs.append(
            run_one(
                repository=repository,
                source_checkout=source_checkout,
                config_path=config_path,
                instance_id=str(row["instance_id"]),
                output_root=output_root,
            )
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--maximum-tasks", type=int, default=1)
    parser.add_argument(
        "--role", choices=("PRIMARY", "RESERVE"), default="PRIMARY"
    )
    arguments = parser.parse_args()
    outputs = run_batch(
        repository=arguments.repository.resolve(),
        source_checkout=arguments.source_checkout.resolve(),
        config_path=arguments.config.resolve(),
        output_root=arguments.output_root.resolve(),
        roles=(arguments.role,),
        maximum_tasks=arguments.maximum_tasks,
    )
    print(
        json.dumps(
            {"attempted": len(outputs), "run_directories": [str(p) for p in outputs]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
