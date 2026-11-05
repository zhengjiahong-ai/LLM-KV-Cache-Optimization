"""Phase 3 G4 reachability analysis (M4, read-only).

Reads the frozen M1 evidence pack and classifies all 40 load-calibration cells.
Writes nothing outside the given output directory; touches no GPU and no
workload input.

Usage
-----
    python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
        --pack local/phase3-g4-reachability-analysis-pack-v1 \
        --out  local/phase3-g4-reachability-m4

Why this file exists
--------------------
Iteration 1 executed 40 A0-only Native runs (256 and 1024 required_blocks per
group) and only 8 of 40 cells landed inside the frozen L_LOW/L_HIGH bands. The
question M1 posed is not "find better parameters" but "is the target itself
built on an assumption that pressure can place the metric anywhere it wants".

This script answers that with the two quantities the iteration-1 data already
contains:

``slope``
    dR0 / d(required_blocks), in tokens per block. The mechanically expected
    value is exactly one block of recompute per block of pressure, i.e.
    ``block_size = 16`` tokens. ``slope / 16`` is therefore the fraction of
    forced releases that are *marginal* (would not have been evicted anyway).

``rho_at_minimum_pressure``
    the proposal's own extrapolation of ``rho0`` to the minimum legal pressure
    (16 blocks). This is the pressure-independent floor: the recomputation the
    frozen workload incurs even when controlled pressure is switched off. It is
    a property of the workload and the 2048-block pool, not a property of the
    pressure parameter.

A cell is *reachable* only if that floor sits at or below the L_LOW upper bound,
because no legal pressure can go below the floor.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

# --- frozen protocol constants (from the iteration-2 proposal `method` block) ---
BLOCK_SIZE_TOKENS = 16
MIN_PRESSURE_BLOCKS = 16
MAX_PRESSURE_BLOCKS = 2032
L_LOW_BAND = (0.05, 0.15)
L_HIGH_BAND = (0.25, 0.45)
ITER1_PRESSURE = {"L_LOW": 256, "L_HIGH": 1024}

#: A response is FLAT when the whole legal pressure range moves rho0 by less than
#: this. 1% is 1/25 of the 0.25 span the two bands require, and at the observed
#: prefill magnitudes it corresponds to fewer than 0.7 tokens of recompute per
#: block of pressure -- i.e. under 4% marginality. Not a tuned constant: it is
#: "the response is smaller than the measurement granularity of the design".
FLAT_DELTA_RHO = 0.01

#: WEAK: responds, but not enough to cross from the L_LOW band to the L_HIGH band.
#: The gap between the band edges is 0.25 - 0.15 = 0.10, so anything below that
#: cannot straddle the two levels even in principle.
WEAK_DELTA_RHO = 0.10


@dataclass(frozen=True, slots=True)
class Cell:
    group_id: str
    load_level: str
    required_blocks: int
    r0: int
    w0: int
    rho0: float
    target_min: float
    target_max: float
    proposed_blocks: int
    predicted_rho0: float
    slope: float
    pressure_insensitive: bool
    at_minimum_pressure: bool
    floor_exceeds_l_low_ceiling: bool
    reachable: bool
    classification: str
    rationale: str


def load_pack(pack: Path) -> tuple[list[dict], list[dict], dict]:
    obs_path = (
        pack
        / "artifacts/phase3-load-calibration-iteration2-planning-v1"
        / "iteration1-cell-observations.json"
    )
    prop_path = (
        pack
        / "artifacts/phase3-load-calibration-iteration2-planning-v1"
        / "iteration2-required-blocks-proposal.json"
    )
    observations = json.loads(obs_path.read_text(encoding="utf-8"))
    proposal = json.loads(prop_path.read_text(encoding="utf-8"))
    return observations["rows"], proposal["rows"], proposal["method"]


def build_cells(observations: list[dict], proposal: list[dict]) -> list[Cell]:
    by_group: dict[str, dict[str, dict]] = {}
    for row in observations:
        by_group.setdefault(row["group_id"], {})[row["load_level"]] = row
    proposed = {(r["group_id"], r["load_level"]): r for r in proposal}

    cells: list[Cell] = []
    for group_id in sorted(by_group):
        low = by_group[group_id]["L_LOW"]
        high = by_group[group_id]["L_HIGH"]
        span = ITER1_PRESSURE["L_HIGH"] - ITER1_PRESSURE["L_LOW"]
        slope = (high["R0_recomputed_tokens"] - low["R0_recomputed_tokens"]) / span
        delta_rho = high["rho0_iteration1"] - low["rho0_iteration1"]

        for level, row in (("L_LOW", low), ("L_HIGH", high)):
            prop = proposed[(group_id, level)]
            in_band = prop["predicted_target_status"] == "PASS"
            at_floor = prop["proposed_required_blocks"] == MIN_PRESSURE_BLOCKS
            floor_too_high = at_floor and not in_band
            insensitive = delta_rho < FLAT_DELTA_RHO

            if floor_too_high and insensitive:
                verdict = "INFEASIBLE_AND_PRESSURE_INSENSITIVE"
                why = (
                    "both loads clamp to the 16-block floor and the metric does "
                    "not respond to pressure at all, so neither target level nor "
                    "level separation is attainable"
                )
            elif floor_too_high:
                verdict = "INFEASIBLE_BELOW_MINIMUM_PRESSURE"
                why = (
                    "the band is only reachable at pressures below the 16-block "
                    "legal minimum, where the predicted rho0 is still outside it"
                )
            elif insensitive:
                verdict = "PRESSURE_INSENSITIVE"
                why = (
                    "the band may be hit at the floor, but the metric does not "
                    "move with pressure, so the level was not controlled by the "
                    "parameter under study"
                )
            elif in_band:
                verdict = "REACHABLE_IN_BAND"
                why = "a legal, distinct pressure places the cell inside its band"
            else:
                verdict = "REACHABLE_OFF_BAND"
                why = (
                    "the cell is controllable but the chosen pressure misses the "
                    "band; a different legal pressure would fix it"
                )

            cells.append(
                Cell(
                    group_id=group_id,
                    load_level=level,
                    required_blocks=row["original_required_blocks"],
                    r0=row["R0_recomputed_tokens"],
                    w0=row["W0_actual_prefill_tokens"],
                    rho0=row["rho0_iteration1"],
                    target_min=row["target_min"],
                    target_max=row["target_max"],
                    proposed_blocks=prop["proposed_required_blocks"],
                    predicted_rho0=prop["predicted_rho0"],
                    slope=round(slope, 4),
                    pressure_insensitive=insensitive,
                    at_minimum_pressure=at_floor,
                    floor_exceeds_l_low_ceiling=floor_too_high,
                    reachable=verdict.startswith("REACHABLE"),
                    classification=verdict,
                    rationale=why,
                )
            )
    return cells


def group_summary(cells: list[Cell]) -> list[dict]:
    by_group: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        by_group.setdefault(cell.group_id, {})[cell.load_level] = cell

    rows: list[dict] = []
    for group_id in sorted(by_group):
        low, high = by_group[group_id]["L_LOW"], by_group[group_id]["L_HIGH"]
        delta_rho = high.rho0 - low.rho0
        both_reachable = low.reachable and high.reachable
        same_pressure = low.proposed_blocks == high.proposed_blocks
        rows.append(
            {
                "group_id": group_id,
                "rho0_L_LOW": round(low.rho0, 4),
                "rho0_L_HIGH": round(high.rho0, 4),
                "delta_rho": round(delta_rho, 4),
                "slope_tokens_per_block": low.slope,
                "marginality_ratio": round(low.slope / BLOCK_SIZE_TOKENS, 3),
                "band_crossing_possible": delta_rho >= WEAK_DELTA_RHO,
                "predicted_pressure_L_LOW": low.proposed_blocks,
                "predicted_pressure_L_HIGH": high.proposed_blocks,
                "predicted_pressure_collision": same_pressure,
                "both_loads_reachable": both_reachable,
                "verdict": (
                    "TWO_LEVEL_CONTRAST_SUPPORTED"
                    if both_reachable and not same_pressure
                    else (
                        "BOTH_LOADS_COLLAPSE_TO_FLOOR"
                        if same_pressure
                        else "TWO_LEVEL_CONTRAST_UNSUPPORTED"
                    )
                ),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pack",
        default="local/phase3-g4-reachability-analysis-pack-v1",
        type=Path,
    )
    parser.add_argument("--out", default="local/phase3-g4-reachability-m4", type=Path)
    args = parser.parse_args()

    observations, proposal, method = load_pack(args.pack)
    cells = build_cells(observations, proposal)
    groups = group_summary(cells)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cell-classification.json").write_text(
        json.dumps(
            {
                "schema_version": "phase3.g4_reachability_cells.v1",
                "frozen_method": method,
                "thresholds": {
                    "flat_delta_rho": FLAT_DELTA_RHO,
                    "weak_delta_rho": WEAK_DELTA_RHO,
                    "block_size_tokens": BLOCK_SIZE_TOKENS,
                    "minimum_blocks": MIN_PRESSURE_BLOCKS,
                },
                "rows": [asdict(cell) for cell in cells],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.out / "group-summary.json").write_text(
        json.dumps(
            {"schema_version": "phase3.g4_reachability_groups.v1", "rows": groups},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (args.out / "cells.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(cells[0])))
        writer.writeheader()
        for cell in cells:
            writer.writerow(asdict(cell))
    with (args.out / "groups.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(groups[0]))
        writer.writeheader()
        writer.writerows(groups)

    print("== cell classification (40 cells) ==")
    for name, count in Counter(c.classification for c in cells).most_common():
        print(f"  {count:2d}  {name}")
    print()
    in_band = [c for c in cells if c.classification == "REACHABLE_IN_BAND"]
    floor_accidents = [c for c in in_band if c.at_minimum_pressure]
    print("== in-band cells that only land there because of the floor ==")
    print(f"  {len(floor_accidents)} of {len(in_band)} in-band cells sit at the 16-block floor:")
    for cell in floor_accidents:
        print(
            f"    {cell.group_id} {cell.load_level}: predicted rho0 "
            f"{cell.predicted_rho0:.4f} inside [{cell.target_min}, {cell.target_max}] "
            "at minimum pressure -- no control demonstrated"
        )
    print()
    print("== group verdicts (20 groups) ==")
    for name, count in Counter(g["verdict"] for g in groups).most_common():
        print(f"  {count:2d}  {name}")
    print()
    flat = [g for g in groups if g["delta_rho"] < FLAT_DELTA_RHO]
    weak = [g for g in groups if FLAT_DELTA_RHO <= g["delta_rho"] < WEAK_DELTA_RHO]
    responsive = [g for g in groups if g["delta_rho"] >= WEAK_DELTA_RHO]
    collisions = [g for g in groups if g["predicted_pressure_collision"]]
    print("== pressure sensitivity ==")
    print(
        f"  flat (dRho < {FLAT_DELTA_RHO}): {len(flat)} -> {', '.join(g['group_id'] for g in flat)}"
    )
    print(f"  weak: {len(weak)} -> {', '.join(g['group_id'] for g in weak)}")
    print(
        f"  responsive (dRho >= {WEAK_DELTA_RHO}): {len(responsive)} -> "
        f"{', '.join(g['group_id'] for g in responsive)}"
    )
    print(
        f"  proposed L_LOW pressure == L_HIGH: {len(collisions)} -> "
        f"{', '.join(g['group_id'] for g in collisions)}"
    )
    print()
    print("== per group ==")
    print(
        f"  {'g':<4}{'rhoLOW':>8}{'rhoHIGH':>8}{'dRho':>8}{'slope':>8}"
        f"{'marg':>7}{'pLOW':>6}{'pHIGH':>7}  verdict"
    )
    for row in groups:
        print(
            f"  {row['group_id']:<4}{row['rho0_L_LOW']:>8.4f}"
            f"{row['rho0_L_HIGH']:>8.4f}{row['delta_rho']:>8.4f}"
            f"{row['slope_tokens_per_block']:>8.2f}"
            f"{row['marginality_ratio']:>7.2f}"
            f"{row['predicted_pressure_L_LOW']:>6d}"
            f"{row['predicted_pressure_L_HIGH']:>7d}  {row['verdict']}"
        )
    print()
    supported = [g["group_id"] for g in groups if g["verdict"] == "TWO_LEVEL_CONTRAST_SUPPORTED"]
    print(f"== two-level contrast supported by {len(supported)} groups: {', '.join(supported)}")
    print(f"== outputs written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
