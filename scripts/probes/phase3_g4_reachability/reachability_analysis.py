"""Phase 3 G4 reachability analysis (M4, read-only).

Reads the frozen M1 evidence pack, re-derives the load-calibration numbers, and
classifies all 40 iteration-1 cells. Writes nothing outside ``--out``; touches no
GPU, no workload input, no frozen artifact.

Usage
-----
    python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
        --pack local/phase3-g4-reachability-analysis-pack-v1 \
        --out  local/phase3-g4-reachability-m4

What this script is careful about (RC revision, 2026-11-05)
----------------------------------------------------------
1. **Two different gates, reported separately.** Protocol v3 §3.6 defines the
   *Headroom* gate (``rho0 >= 5% and R0 >= 512 tokens``); §9 G4 consumes the
   frozen Headroom list. §5.2 defines a *load-calibration target*
   (``rho0`` inside ``[0.05, 0.15]`` / ``[0.25, 0.45]``). These are different
   quantities and this script never uses one to pronounce on the other.
   ``headroom_*`` fields are the original gate; ``measured_inside_target`` /
   ``target_reachable_*`` fields are the load target; ``headroom-report.json``
   states the gate's own status.
2. **Measured vs extrapolated.** The 16-block "floor" is an extrapolation of a
   two-point linear model 240 blocks below the lowest measured pressure. Every
   derived value carries an ``evidence_class`` of ``MEASURED`` /
   ``INTERPOLATED`` / ``EXTRAPOLATED``, and reachability verdicts name the class
   they rely on.
3. **No silently invented constant.** ``empirical_marginal_response_ratio`` is an
   observed slope ratio, not a claimed release-cost coefficient. The Option-E
   band is only evaluated behind an explicit report, and the groups whose
   operating point would land in the 0.15-0.25 interval -- covered by neither
   frozen band -- are enumerated rather than absorbed.
4. **Integrity.** The four frozen planning inputs are SHA-256 verified against
   pins recorded below and cross-checked against the pack manifest, and the
   proposal's own ``source_observations_sha256`` must bind the pinned
   observation hash.

Read-only. No GPU. No new calibration run is generated or executed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ANALYSIS_VERSION = "phase3.g4_reachability_analysis.v2"

# --- frozen protocol constants (mirrors the iteration-2 proposal `method`) ---
BLOCK_SIZE_TOKENS = 16
MIN_PRESSURE_BLOCKS = 16
MAX_PRESSURE_BLOCKS = 2032
PRESSURE_QUANTUM_BLOCKS = 16
L_LOW_BAND = (0.05, 0.15)
L_HIGH_BAND = (0.25, 0.45)
ITER1_PRESSURE = {"L_LOW": 256, "L_HIGH": 1024}

# --- original Headroom gate (Protocol v3 §3.6), frozen before any analysis ---
HEADROOM_RATIO_MIN = 0.05
HEADROOM_R0_MIN_TOKENS = 512

EXPECTED_GROUP_COUNT = 20
EXPECTED_CELL_COUNT = 40

#: A response is FLAT when the whole legal pressure range moves rho0 by less
#: than this. 0.01 is 1/25 of the 0.25 span the two frozen bands require, and at
#: the observed prefill magnitudes it corresponds to under 0.7 tokens of
#: recompute per block of pressure, i.e. under 4% of the mechanically expected
#: 16 tokens/block. It is "below the measurement granularity of the design",
#: not a tuned constant.
FLAT_DELTA_RHO = 0.01

#: WEAK: the metric responds, but by less than the gap between the L_LOW ceiling
#: and the L_HIGH floor (0.25 - 0.15 = 0.10). Below that gap a group cannot
#: straddle the two frozen bands even in principle.
WEAK_DELTA_RHO = 0.10

#: Option E is a *proposal*, not an inherited constant. Its interval covers
#: 0.15-0.25, which neither frozen band covers, so it is not a subset of the
#: frozen design. Groups relying on that sub-interval are reported separately.
OPTION_E_BAND = (0.15, 0.45)

#: SD used only to *plan* precision. Inherited planning assumption from Phase
#: 2E/2G observations, never reported as an achieved precision.
PLANNING_GROUP_SD_TOKENS = 2000.0
NORMAL_95_Z = 1.959963984540054

#: The four frozen planning inputs M1 froze, pinned here so that a tampered pack
#: manifest cannot silently change the analysis. Verified against
#: ``sha256-manifest.txt`` and against the proposal's own source binding.
PLANNING_DIR = "artifacts/phase3-load-calibration-iteration2-planning-v1"
FROZEN_INPUTS: dict[str, str] = {
    f"{PLANNING_DIR}/iteration1-cell-observations.json": (
        "a47acef4a96cbedec37d88c941c70a8ed30f3208d7cac8ec1d599acb6d876d5a"
    ),
    f"{PLANNING_DIR}/iteration1-cell-observations.csv": (
        "2fb77aae8dd734860e7a3664f724fad2113db263ea63f806656abad4975179ec"
    ),
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.json": (
        "1b59758a7ef8b5d0b42c4431fa0d2983d27062bf5d89c4a0b4b01175ff3c36a8"
    ),
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.csv": (
        "49738f3715a945038c566f2260eb50053b7fb68760e8ac5b60bcc9bb112d8a36"
    ),
}

OBSERVATION_KEYS = (
    "group_id",
    "load_level",
    "original_required_blocks",
    "R0_recomputed_tokens",
    "W0_actual_prefill_tokens",
    "rho0_iteration1",
    "target_min",
    "target_max",
    "iteration1_headroom_eligible",
)
PROPOSAL_KEYS = (
    "group_id",
    "load_level",
    "proposed_required_blocks",
    "predicted_rho0",
    "predicted_target_status",
    "target_min",
    "target_max",
    "limitation",
)

BELOW_MIN_LIMITATION = "TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE"


class InputIntegrityError(RuntimeError):
    """Raised when the frozen evidence pack does not match its pinned hashes."""


class InputSchemaError(RuntimeError):
    """Raised when the frozen inputs do not satisfy the expected schema."""


@dataclass(frozen=True, slots=True)
class GroupModel:
    """Two-point linear model per group, in absolute tokens.

    ``R0(N) = R_lo + slope_r * (N - 256)`` and likewise for ``W0``; this is the
    same secant the frozen iteration-2 proposal uses, and ``rho0(N)`` is their
    ratio. Validated against the proposal's own ``predicted_rho0`` on load.
    """

    group_id: str
    r_lo: int
    w_lo: int
    r_hi: int
    w_hi: int

    @property
    def slope_r(self) -> float:
        span = ITER1_PRESSURE["L_HIGH"] - ITER1_PRESSURE["L_LOW"]
        return (self.r_hi - self.r_lo) / span

    @property
    def slope_w(self) -> float:
        span = ITER1_PRESSURE["L_HIGH"] - ITER1_PRESSURE["L_LOW"]
        return (self.w_hi - self.w_lo) / span

    def rho(self, blocks: int) -> float:
        offset = blocks - ITER1_PRESSURE["L_LOW"]
        r0 = self.r_lo + self.slope_r * offset
        w0 = self.w_lo + self.slope_w * offset
        return (r0 / w0) if w0 > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Cell:
    group_id: str
    load_level: str

    # measured facts (observations, not estimates)
    measured_blocks: int
    r0: int
    w0: int
    rho0: float
    delta_rho_measured: float

    # frozen load-calibration target for this cell (§5.2)
    target_min: float
    target_max: float
    measured_inside_target: bool
    measured_evidence_class: str

    # what the frozen iteration-2 proposal would do (never executed)
    proposed_blocks: int
    proposed_predicted_rho0: float
    proposed_reproduced_rho0: float
    proposed_status: str
    proposal_evidence_class: str

    # original Headroom gate (§3.6)
    headroom_ratio_ok: bool
    headroom_abs_ok: bool
    headroom_eligible: bool

    # reachability under the two-point linear model over the legal grid
    target_reachable_any_legal: bool
    target_reachable_non_floor: bool
    target_reachable_class: str
    rho0_at_minimum_blocks: float
    rho0_at_maximum_blocks: float

    # observed slope and its ratio to the mechanically expected 1:1 value
    slope_tokens_per_block: float
    empirical_marginal_response_ratio: float

    classification: str
    rationale: str


@dataclass(frozen=True, slots=True)
class GroupSummary:
    group_id: str
    rho0_l_low: float
    rho0_l_high: float
    delta_rho_measured: float
    slope_tokens_per_block: float
    empirical_marginal_response_ratio: float
    rho0_at_minimum_blocks: float
    floor_share_of_low_measurement: float
    pressure_response: str

    # G4-a as proposed: can two levels live at distinct legal pressures?
    g4a_two_band_feasible: bool
    g4a_achievable_delta_rho: float
    g4a_measured_delta_rho_ok: bool
    g4a_measured_pressures_distinct: bool

    # G4-b per cell, floor clause applied
    g4b_l_low_ok: bool
    g4b_l_high_ok: bool

    proposed_pressure_collision: bool
    collision_limitations: str
    verdict: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen_inputs(pack: Path) -> dict[str, str]:
    """Verify the four frozen planning inputs against pins and pack manifest."""

    verified: dict[str, str] = {}
    for relative, pinned in FROZEN_INPUTS.items():
        path = pack / relative
        if not path.is_file():
            raise InputIntegrityError(f"frozen input missing: {relative}")
        actual = sha256_file(path)
        if actual != pinned:
            raise InputIntegrityError(
                f"frozen input hash mismatch for {relative}: expected {pinned}, got {actual}"
            )
        verified[relative] = actual

    manifest_path = pack / "sha256-manifest.txt"
    if not manifest_path.is_file():
        raise InputIntegrityError("pack manifest missing: sha256-manifest.txt")
    manifest: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        digest, _, relative = stripped.partition("  ")
        manifest[relative.strip()] = digest
    for relative, digest in verified.items():
        if relative not in manifest:
            raise InputIntegrityError(f"frozen input not covered by manifest: {relative}")
        if manifest[relative] != digest:
            raise InputIntegrityError(f"manifest disagrees with pinned hash for {relative}")
    return verified


def _require_mapping(row: object, keys: tuple[str, ...], where: str) -> dict:
    if not isinstance(row, dict):
        raise InputSchemaError(f"{where}: expected object, got {type(row).__name__}")
    missing = [key for key in keys if key not in row]
    if missing:
        raise InputSchemaError(f"{where}: missing keys {missing}")
    return row


def load_inputs(pack: Path) -> tuple[dict, dict]:
    obs_path = pack / f"{PLANNING_DIR}/iteration1-cell-observations.json"
    prop_path = pack / f"{PLANNING_DIR}/iteration2-required-blocks-proposal.json"
    return (
        json.loads(obs_path.read_text(encoding="utf-8")),
        json.loads(prop_path.read_text(encoding="utf-8")),
    )


def validate_inputs(
    observations: dict, proposal: dict, verified: dict[str, str] | None = None
) -> tuple[list[dict], list[dict], dict]:
    """Validate schema, completeness and uniqueness; return validated rows."""

    obs_rows = observations.get("rows")
    prop_rows = proposal.get("rows")
    if not isinstance(obs_rows, list) or not isinstance(prop_rows, list):
        raise InputSchemaError("rows must be a list in both frozen inputs")

    for name, document in (("observations", observations), ("proposal", proposal)):
        if document.get("cell_count") != EXPECTED_CELL_COUNT:
            raise InputSchemaError(
                f"{name} cell_count must be {EXPECTED_CELL_COUNT}, "
                f"got {document.get('cell_count')!r}"
            )
    if len(obs_rows) != EXPECTED_CELL_COUNT or len(prop_rows) != EXPECTED_CELL_COUNT:
        raise InputSchemaError(
            f"expected {EXPECTED_CELL_COUNT} rows each, got "
            f"{len(obs_rows)} observations / {len(prop_rows)} proposal rows"
        )

    seen_groups: set[str] = set()
    for index, raw in enumerate(obs_rows):
        row = _require_mapping(raw, OBSERVATION_KEYS, f"observations[{index}]")
        if row["load_level"] not in ITER1_PRESSURE:
            raise InputSchemaError(f"unexpected load_level {row['load_level']!r}")
        if row["original_required_blocks"] != ITER1_PRESSURE[row["load_level"]]:
            raise InputSchemaError(
                f"{row['group_id']}/{row['load_level']}: iteration-1 pressure "
                f"{row['original_required_blocks']} is not the frozen "
                f"{ITER1_PRESSURE[row['load_level']]}"
            )
        if not isinstance(row["iteration1_headroom_eligible"], bool):
            raise InputSchemaError("iteration1_headroom_eligible must be a bool")
        r0 = row["R0_recomputed_tokens"]
        w0 = row["W0_actual_prefill_tokens"]
        if not isinstance(r0, int) or not isinstance(w0, int) or r0 < 0 or w0 <= 0:
            raise InputSchemaError(f"{row['group_id']}/{row['load_level']}: bad R0/W0")
        recomputed = r0 / w0
        if abs(recomputed - row["rho0_iteration1"]) > 1e-9:
            raise InputSchemaError(
                f"{row['group_id']}/{row['load_level']}: rho0 does not equal R0/W0"
            )
        expected_headroom = (recomputed >= HEADROOM_RATIO_MIN) and (r0 >= HEADROOM_R0_MIN_TOKENS)
        if expected_headroom != row["iteration1_headroom_eligible"]:
            raise InputSchemaError(
                f"{row['group_id']}/{row['load_level']}: headroom flag "
                f"{row['iteration1_headroom_eligible']} disagrees with §3.6 = "
                f"{expected_headroom}"
            )
        seen_groups.add(row["group_id"])

    if len(seen_groups) != EXPECTED_GROUP_COUNT:
        raise InputSchemaError(f"expected {EXPECTED_GROUP_COUNT} groups, got {len(seen_groups)}")

    obs_keys = {(r["group_id"], r["load_level"]) for r in obs_rows}
    if len(obs_keys) != EXPECTED_CELL_COUNT:
        raise InputSchemaError("observation cells are not unique")

    prop_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(prop_rows):
        row = _require_mapping(raw, PROPOSAL_KEYS, f"proposal[{index}]")
        key = (row["group_id"], row["load_level"])
        if key in prop_keys:
            raise InputSchemaError(f"duplicate proposal cell {key}")
        prop_keys.add(key)
        if row["load_level"] not in ITER1_PRESSURE:
            raise InputSchemaError(f"unexpected load_level {row['load_level']!r}")
        blocks = row["proposed_required_blocks"]
        if not isinstance(blocks, int):
            raise InputSchemaError("proposed_required_blocks must be an int")
        if not MIN_PRESSURE_BLOCKS <= blocks <= MAX_PRESSURE_BLOCKS:
            raise InputSchemaError(f"{key}: proposed pressure {blocks} outside legal range")
        if blocks % PRESSURE_QUANTUM_BLOCKS != 0:
            raise InputSchemaError(f"{key}: proposed pressure {blocks} not on quantum")
        band = L_LOW_BAND if row["load_level"] == "L_LOW" else L_HIGH_BAND
        if (row["target_min"], row["target_max"]) != band:
            raise InputSchemaError(
                f"{key}: target band {(row['target_min'], row['target_max'])} "
                f"differs from the frozen {band}"
            )
        if row["predicted_target_status"] not in {"PASS", "PREDICTED_MISS"}:
            raise InputSchemaError(
                f"{key}: unexpected predicted_target_status {row['predicted_target_status']!r}"
            )

    if prop_keys != obs_keys:
        raise InputSchemaError("proposal cells do not match observation cells")

    method = proposal.get("method") or {}
    if method.get("minimum_blocks") != MIN_PRESSURE_BLOCKS:
        raise InputSchemaError("proposal method contradicts frozen minimum_blocks")
    if method.get("maximum_blocks") != MAX_PRESSURE_BLOCKS:
        raise InputSchemaError("proposal method contradicts frozen maximum_blocks")

    if verified is not None:
        pinned_obs = verified[f"{PLANNING_DIR}/iteration1-cell-observations.json"]
        if proposal.get("source_observations_sha256") != pinned_obs:
            raise InputSchemaError(
                "proposal source_observations_sha256 does not bind the pinned observation file"
            )

    return obs_rows, prop_rows, method


def legal_pressure_grid() -> list[int]:
    return list(range(MIN_PRESSURE_BLOCKS, MAX_PRESSURE_BLOCKS + 1, PRESSURE_QUANTUM_BLOCKS))


def evidence_class(blocks: int) -> str:
    """How much the linear model is being trusted at ``blocks``."""

    if blocks in ITER1_PRESSURE.values():
        return "MEASURED"
    if ITER1_PRESSURE["L_LOW"] < blocks < ITER1_PRESSURE["L_HIGH"]:
        return "INTERPOLATED"
    return "EXTRAPOLATED"


_EVIDENCE_RANK = {"MEASURED": 3, "INTERPOLATED": 2, "EXTRAPOLATED": 1, "NONE": 0}


def _best_evidence(points: list[int]) -> str:
    if not points:
        return "NONE"
    return max((evidence_class(n) for n in points), key=lambda name: _EVIDENCE_RANK[name])


def _band_points(model: GroupModel, band: tuple[float, float]) -> list[int]:
    low, high = band
    return [n for n in legal_pressure_grid() if low <= model.rho(n) <= high]


def build_models(obs_rows: list[dict]) -> dict[str, GroupModel]:
    by_group: dict[str, dict[str, dict]] = {}
    for row in obs_rows:
        by_group.setdefault(row["group_id"], {})[row["load_level"]] = row
    return {
        group_id: GroupModel(
            group_id=group_id,
            r_lo=pair["L_LOW"]["R0_recomputed_tokens"],
            w_lo=pair["L_LOW"]["W0_actual_prefill_tokens"],
            r_hi=pair["L_HIGH"]["R0_recomputed_tokens"],
            w_hi=pair["L_HIGH"]["W0_actual_prefill_tokens"],
        )
        for group_id, pair in by_group.items()
    }


def build_cells(
    obs_rows: list[dict], prop_rows: list[dict], models: dict[str, GroupModel]
) -> list[Cell]:
    proposed = {(r["group_id"], r["load_level"]): r for r in prop_rows}
    cells: list[Cell] = []

    for row in obs_rows:
        group_id = row["group_id"]
        model = models[group_id]
        prop = proposed[(group_id, row["load_level"])]
        band = (row["target_min"], row["target_max"])
        delta_rho = abs(model.rho(ITER1_PRESSURE["L_HIGH"]) - model.rho(ITER1_PRESSURE["L_LOW"]))
        points = _band_points(model, band)
        non_floor = [n for n in points if n > MIN_PRESSURE_BLOCKS]
        rho_measured = row["rho0_iteration1"]

        reproduced = model.rho(prop["proposed_required_blocks"])
        if abs(reproduced - prop["predicted_rho0"]) > 1e-9:
            raise InputSchemaError(
                f"{group_id}/{row['load_level']}: two-point model does not "
                f"reproduce the frozen proposed rho0 "
                f"({reproduced!r} vs {prop['predicted_rho0']!r})"
            )

        headroom_ratio_ok = rho_measured >= HEADROOM_RATIO_MIN
        headroom_abs_ok = row["R0_recomputed_tokens"] >= HEADROOM_R0_MIN_TOKENS
        inside_target = band[0] <= rho_measured <= band[1]
        floor = model.rho(MIN_PRESSURE_BLOCKS)

        if not points:
            if delta_rho < FLAT_DELTA_RHO:
                classification = "INFEASIBLE_AND_PRESSURE_INSENSITIVE"
                rationale = (
                    "no legal pressure on the 16-block grid places rho0 in this "
                    "band, AND the measured response to pressure is below the "
                    "flat threshold, so the level is neither attainable nor "
                    "controllable"
                )
            else:
                classification = "INFEASIBLE_BELOW_MINIMUM_PRESSURE"
                rationale = (
                    f"the model's floor at {MIN_PRESSURE_BLOCKS} blocks "
                    f"({floor:.4f}) is outside the band, so no legal pressure "
                    "reaches it, while the response to pressure itself is "
                    "non-trivial. Floor is EXTRAPOLATED "
                    f"({MIN_PRESSURE_BLOCKS} < {ITER1_PRESSURE['L_LOW']} measured)"
                )
        elif inside_target:
            classification = "REACHABLE_MEASURED"
            rationale = (
                "a pressure that was actually run places rho0 inside the band; "
                "this is an observation, not an extrapolation"
            )
        else:
            reach_class = _best_evidence(points)
            classification = f"REACHABLE_{reach_class}"
            rationale = (
                "the band is reachable at some legal pressure, but only as "
                f"{reach_class.lower()} model output; no run has landed there"
            )

        cells.append(
            Cell(
                group_id=group_id,
                load_level=row["load_level"],
                measured_blocks=row["original_required_blocks"],
                r0=row["R0_recomputed_tokens"],
                w0=row["W0_actual_prefill_tokens"],
                rho0=rho_measured,
                delta_rho_measured=round(delta_rho, 6),
                target_min=band[0],
                target_max=band[1],
                measured_inside_target=inside_target,
                measured_evidence_class=evidence_class(row["original_required_blocks"]),
                proposed_blocks=prop["proposed_required_blocks"],
                proposed_predicted_rho0=round(prop["predicted_rho0"], 6),
                proposed_reproduced_rho0=round(reproduced, 6),
                proposed_status=prop["predicted_target_status"],
                proposal_evidence_class=evidence_class(prop["proposed_required_blocks"]),
                headroom_ratio_ok=headroom_ratio_ok,
                headroom_abs_ok=headroom_abs_ok,
                headroom_eligible=row["iteration1_headroom_eligible"],
                target_reachable_any_legal=bool(points),
                target_reachable_non_floor=bool(non_floor),
                target_reachable_class=_best_evidence(points),
                rho0_at_minimum_blocks=round(floor, 6),
                rho0_at_maximum_blocks=round(model.rho(MAX_PRESSURE_BLOCKS), 6),
                slope_tokens_per_block=round(model.slope_r, 4),
                empirical_marginal_response_ratio=round(model.slope_r / BLOCK_SIZE_TOKENS, 4),
                classification=classification,
                rationale=rationale,
            )
        )
    return cells


def build_groups(
    models: dict[str, GroupModel], cells: list[Cell], prop_rows: list[dict]
) -> list[GroupSummary]:
    by_cell: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        by_cell.setdefault(cell.group_id, {})[cell.load_level] = cell

    tags: dict[tuple[str, str], str] = {
        (row["group_id"], row["load_level"]): (row.get("limitation") or "") for row in prop_rows
    }

    rows: list[GroupSummary] = []
    for group_id in sorted(by_cell):
        model = models[group_id]
        low, high = by_cell[group_id]["L_LOW"], by_cell[group_id]["L_HIGH"]
        delta_rho = abs(high.rho0 - low.rho0)
        floor = model.rho(MIN_PRESSURE_BLOCKS)

        ll_points = _band_points(model, L_LOW_BAND)
        lh_points = _band_points(model, L_HIGH_BAND)
        feasible_pairs = [
            (lo, hi) for lo in ll_points for hi in lh_points if hi - lo >= PRESSURE_QUANTUM_BLOCKS
        ]
        achievable = max((model.rho(hi) - model.rho(lo) for lo, hi in feasible_pairs), default=0.0)

        if delta_rho < FLAT_DELTA_RHO:
            response = "FLAT"
        elif delta_rho < WEAK_DELTA_RHO:
            response = "WEAK"
        else:
            response = "RESPONSIVE"

        def placement(cell: Cell, controllable: bool = bool(feasible_pairs)) -> bool:
            """G4-b: in band at the chosen pressure, with the floor clause."""

            if cell.proposed_status != "PASS":
                return False
            if cell.proposed_blocks != MIN_PRESSURE_BLOCKS:
                return True
            # A floor cell is a lucky landing, not a demonstrated level. It may
            # serve as an operating point only inside a group whose two-level
            # feasibility is established independently.
            return controllable

        both_ok = placement(low) and placement(high)
        collision = low.proposed_blocks == high.proposed_blocks

        if both_ok and not collision:
            verdict = "TWO_LEVEL_CONTRAST_SUPPORTED"
        elif collision:
            verdict = "BOTH_LOADS_COLLAPSE_TO_SAME_PRESSURE"
        else:
            verdict = "TWO_LEVEL_CONTRAST_UNSUPPORTED"

        low_tag = tags.get((group_id, "L_LOW"), "")
        high_tag = tags.get((group_id, "L_HIGH"), "")

        rows.append(
            GroupSummary(
                group_id=group_id,
                rho0_l_low=round(low.rho0, 6),
                rho0_l_high=round(high.rho0, 6),
                delta_rho_measured=round(delta_rho, 6),
                slope_tokens_per_block=round(model.slope_r, 4),
                empirical_marginal_response_ratio=round(model.slope_r / BLOCK_SIZE_TOKENS, 4),
                rho0_at_minimum_blocks=round(floor, 6),
                floor_share_of_low_measurement=round(
                    (floor / low.rho0) if low.rho0 > 0 else 0.0, 4
                ),
                pressure_response=response,
                g4a_two_band_feasible=bool(feasible_pairs),
                g4a_achievable_delta_rho=round(achievable, 6),
                g4a_measured_delta_rho_ok=delta_rho >= WEAK_DELTA_RHO,
                g4a_measured_pressures_distinct=(
                    ITER1_PRESSURE["L_HIGH"] - ITER1_PRESSURE["L_LOW"] >= PRESSURE_QUANTUM_BLOCKS
                ),
                g4b_l_low_ok=placement(low),
                g4b_l_high_ok=placement(high),
                proposed_pressure_collision=collision,
                collision_limitations=(f"L_LOW={low_tag or '-'} | L_HIGH={high_tag or '-'}"),
                verdict=verdict,
            )
        )
    return rows


def collision_report(groups: list[GroupSummary]) -> dict:
    """Proposed-pressure collisions, counted two ways.

    The unrestricted count and the count restricted to rows tagged
    ``TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE`` differ exactly when a colliding
    group's rows carry a different frozen ``limitation`` tag. Reporting both,
    plus the differing groups, reproduces the 9-versus-10 count from the frozen
    file instead of guessing a convention.
    """

    unrestricted = [g.group_id for g in groups if g.proposed_pressure_collision]
    both_tagged = [
        g.group_id
        for g in groups
        if g.proposed_pressure_collision
        and g.collision_limitations.count(BELOW_MIN_LIMITATION) == 2
    ]
    return {
        "unrestricted": unrestricted,
        "both_rows_tagged_below_minimum_pressure": both_tagged,
        "only_outside_tagged_subset": sorted(set(unrestricted) - set(both_tagged)),
        "tag_detail": {
            g.group_id: g.collision_limitations
            for g in groups
            if g.proposed_pressure_collision and g.group_id not in both_tagged
        },
    }


def headroom_report(cells: list[Cell]) -> dict:
    """State of the original Headroom gate (§3.6) and of G4 (§9)."""

    by_load: dict[str, dict[str, int]] = {}
    for level in ("L_LOW", "L_HIGH"):
        sub = [c for c in cells if c.load_level == level]
        eligible = [c for c in sub if c.headroom_eligible]
        by_load[level] = {
            "candidate_cells": len(sub),
            "eligible": len(eligible),
            "no_headroom": len(sub) - len(eligible),
        }
    excluded = [c for c in cells if not c.headroom_eligible]
    return {
        "gate": "Protocol v3 §3.6 Headroom (rho0 >= 5% AND R0 >= 512 tokens)",
        "consumed_by": "Protocol v3 §9 G4 (frozen Headroom list)",
        "candidate_cells": len(cells),
        "eligible_cells": sum(1 for c in cells if c.headroom_eligible),
        "no_headroom_cells": len(excluded),
        "excluded": [
            {
                "group_id": c.group_id,
                "load_level": c.load_level,
                "rho0": round(c.rho0, 6),
                "r0": c.r0,
                "failed_ratio": not c.headroom_ratio_ok,
                "failed_absolute": not c.headroom_abs_ok,
            }
            for c in excluded
        ],
        "by_load": by_load,
        "status": "APPLICABLE_ON_ITERATION1_PARAMETERS",
        "note": (
            "The Headroom gate itself is not what fails. On the current frozen "
            "parameters it admits 38 of 40 cells, so G4's own threshold is "
            "satisfied. G4 is blocked procedurally because §5.2's load "
            "calibration never settled the parameters and §3.6 forbids freezing "
            "the list before the parameters are frozen."
        ),
    }


def load_target_report(cells: list[Cell], groups: list[GroupSummary]) -> dict:
    by_load = {
        level: dict(Counter(c.classification for c in cells if c.load_level == level))
        for level in ("L_LOW", "L_HIGH")
    }
    return {
        "gate": "Protocol v3 §5.2 load-calibration target (rho0 inside a frozen band)",
        "distinct_from": "§3.6 Headroom / §9 G4",
        "measured_inside_target": sum(1 for c in cells if c.measured_inside_target),
        "reachable_any_legal": sum(1 for c in cells if c.target_reachable_any_legal),
        "reachable_non_floor": sum(1 for c in cells if c.target_reachable_non_floor),
        "by_load_classification": by_load,
        "groups_with_both_bands_reachable": sum(1 for g in groups if g.g4a_two_band_feasible),
        "groups_with_measured_delta_rho_at_least_0_10": sum(
            1 for g in groups if g.g4a_measured_delta_rho_ok
        ),
        "evidence_classes_used": dict(Counter(c.target_reachable_class for c in cells)),
    }


def option_report(cells: list[Cell], groups: list[GroupSummary]) -> dict:
    """Group counts per design option, with no silently imported constant."""

    by_group: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        by_group.setdefault(cell.group_id, {})[cell.load_level] = cell

    measured_band: list[str] = []
    for group_id, pair in by_group.items():
        if any(
            L_LOW_BAND[0] <= c.rho0 <= L_LOW_BAND[1] or L_HIGH_BAND[0] <= c.rho0 <= L_HIGH_BAND[1]
            for c in pair.values()
        ):
            measured_band.append(group_id)

    in_e_band: list[str] = []
    from_gap: list[str] = []
    for group_id, pair in by_group.items():
        for cell in pair.values():
            if OPTION_E_BAND[0] <= cell.rho0 <= OPTION_E_BAND[1]:
                in_e_band.append(group_id)
                if L_LOW_BAND[1] < cell.rho0 < L_HIGH_BAND[0]:
                    from_gap.append(group_id)
                break

    responsive = {g.group_id for g in groups if g.pressure_response == "RESPONSIVE"}
    return {
        "A_two_level_supported": sorted(
            g.group_id for g in groups if g.verdict == "TWO_LEVEL_CONTRAST_SUPPORTED"
        ),
        "B_and_C_not_evaluated": (
            "B needs new group acquisition; C is rejected as it changes the frozen 2048-block pool"
        ),
        "A_prime_measured_inside_frozen_band": sorted(measured_band),
        "E_band": list(OPTION_E_BAND),
        "E_groups": sorted(in_e_band),
        "E_groups_also_responsive": sorted(set(in_e_band) & responsive),
        "E_groups_operating_point_in_0_15_0_25_gap": sorted(from_gap),
        "responsive_groups": sorted(responsive),
    }


def precision_table(group_counts: dict[str, int]) -> dict[str, dict]:
    """Planned CI half-widths under a stated SD assumption -- not a guarantee."""

    baseline = NORMAL_95_Z * PLANNING_GROUP_SD_TOKENS / (20**0.5)
    table: dict[str, dict] = {}
    for label, n in group_counts.items():
        if n <= 0:
            continue
        half_width = NORMAL_95_Z * PLANNING_GROUP_SD_TOKENS / (n**0.5)
        table[label] = {
            "n_groups": n,
            "planned_ci_half_width_tokens": round(half_width, 1),
            "ratio_vs_n20": round(half_width / baseline, 3),
        }
    return table


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(pack: Path, out: Path) -> dict:
    verified = verify_frozen_inputs(pack)
    observations, proposal = load_inputs(pack)
    obs_rows, prop_rows, method = validate_inputs(observations, proposal, verified)
    models = build_models(obs_rows)
    cells = build_cells(obs_rows, prop_rows, models)
    groups = build_groups(models, cells, prop_rows)

    headroom = headroom_report(cells)
    load_target = load_target_report(cells, groups)
    options = option_report(cells, groups)
    precision = precision_table(
        {
            "v3_20_groups": 20,
            "option_E_all_15_groups": len(options["E_groups"]),
            "option_E_responsive_only": len(options["E_groups_also_responsive"]),
            "option_A_two_level_7_groups": len(options["A_two_level_supported"]),
            "option_A_prime_measured_band": len(options["A_prime_measured_inside_frozen_band"]),
        }
    )

    out.mkdir(parents=True, exist_ok=True)
    _write_json(
        out / "cell-classification.json",
        {
            "schema_version": f"{ANALYSIS_VERSION}.cells",
            "analysis_version": ANALYSIS_VERSION,
            "frozen_inputs_sha256": verified,
            "frozen_method": method,
            "thresholds": {
                "block_size_tokens": BLOCK_SIZE_TOKENS,
                "minimum_blocks": MIN_PRESSURE_BLOCKS,
                "maximum_blocks": MAX_PRESSURE_BLOCKS,
                "quantum_blocks": PRESSURE_QUANTUM_BLOCKS,
                "flat_delta_rho": FLAT_DELTA_RHO,
                "weak_delta_rho": WEAK_DELTA_RHO,
                "headroom_ratio_min": HEADROOM_RATIO_MIN,
                "headroom_r0_min_tokens": HEADROOM_R0_MIN_TOKENS,
            },
            "rows": [asdict(cell) for cell in cells],
        },
    )
    _write_json(
        out / "group-summary.json",
        {
            "schema_version": f"{ANALYSIS_VERSION}.groups",
            "rows": [asdict(group) for group in groups],
        },
    )
    _write_json(out / "headroom-report.json", headroom)
    _write_json(out / "load-target-report.json", load_target)
    _write_json(out / "option-report.json", options)
    _write_json(out / "collision-report.json", collision_report(groups))
    _write_json(
        out / "precision-report.json",
        {
            "planning_group_sd_tokens": PLANNING_GROUP_SD_TOKENS,
            "caveat": (
                "Half-widths are a planning calculation from an assumed group "
                "SD, not an achieved precision. They say nothing about coverage "
                "and must not be quoted as a guarantee."
            ),
            "table": precision,
        },
    )

    with (out / "cells.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(cells[0])))
        writer.writeheader()
        for cell in cells:
            writer.writerow(asdict(cell))
    with (out / "groups.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(groups[0])))
        writer.writeheader()
        for group in groups:
            writer.writerow(asdict(group))

    return {
        "cells": cells,
        "groups": groups,
        "headroom": headroom,
        "load_target": load_target,
        "options": options,
        "precision": precision,
        "method": method,
        "verified": verified,
    }


def _print_report(result: dict) -> None:
    cells: list[Cell] = result["cells"]
    groups: list[GroupSummary] = result["groups"]
    headroom = result["headroom"]
    load_target = result["load_target"]
    options = result["options"]

    print("== frozen inputs (SHA-256 verified, 4 files) ==")
    for relative, digest in result["verified"].items():
        print(f"  {digest[:16]}...  {Path(relative).name}")

    print()
    print("== ORIGINAL G4 / HEADROOM (§3.6: rho0 >= 5% AND R0 >= 512) ==")
    print(
        f"  candidate {headroom['candidate_cells']}  "
        f"eligible {headroom['eligible_cells']}  "
        f"no-headroom {headroom['no_headroom_cells']}"
    )
    for level, stats in headroom["by_load"].items():
        print(
            f"  {level}: {stats['eligible']}/{stats['candidate_cells']} eligible, "
            f"{stats['no_headroom']} excluded"
        )
    for row in headroom["excluded"]:
        print(
            f"    excluded {row['group_id']} {row['load_level']}: "
            f"rho0={row['rho0']:.4f} R0={row['r0']} "
            f"ratio_ok={not row['failed_ratio']} abs_ok={not row['failed_absolute']}"
        )
    print(f"  status: {headroom['status']}")

    print()
    print("== LOAD-CALIBRATION TARGET (§5.2: rho0 inside a frozen band) ==")
    print(f"  measured inside target          : {load_target['measured_inside_target']}/40")
    print(f"  reachable at any legal pressure : {load_target['reachable_any_legal']}/40")
    print(f"  reachable off the 16-block floor: {load_target['reachable_non_floor']}/40")
    print(
        f"  groups with both bands reachable: {load_target['groups_with_both_bands_reachable']}/20"
    )
    print(f"  evidence classes                : {load_target['evidence_classes_used']}")

    print()
    print("== cell classification (40) ==")
    for name, count in sorted(Counter(c.classification for c in cells).items()):
        print(f"  {count:2d}  {name}")

    print()
    print("== pressure response (20 groups) ==")
    for stratum in ("FLAT", "WEAK", "RESPONSIVE"):
        members = [g.group_id for g in groups if g.pressure_response == stratum]
        print(f"  {stratum:10s} {len(members):2d}  {', '.join(members)}")

    print()
    print("== group verdicts (20) ==")
    for name, count in sorted(Counter(g.verdict for g in groups).items()):
        print(f"  {count:2d}  {name}")

    collisions = collision_report(groups)
    print()
    print("== proposed-pressure collisions ==")
    print(
        f"  unrestricted                    : "
        f"{len(collisions['unrestricted'])} -> "
        f"{', '.join(collisions['unrestricted'])}"
    )
    print(
        "  both rows tagged TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE: "
        f"{len(collisions['both_rows_tagged_below_minimum_pressure'])} -> "
        f"{', '.join(collisions['both_rows_tagged_below_minimum_pressure'])}"
    )
    print(
        "  only outside the tagged subset  : "
        f"{', '.join(collisions['only_outside_tagged_subset']) or 'none'}"
    )
    for group_id, detail in collisions["tag_detail"].items():
        print(f"    {group_id} tags: {detail}")

    print()
    print("== design options (group counts) ==")
    print(
        "  A  two-level supported           : "
        f"{len(options['A_two_level_supported'])} -> "
        f"{', '.join(options['A_two_level_supported'])}"
    )
    print(
        "  A' measured inside frozen band   : "
        f"{len(options['A_prime_measured_inside_frozen_band'])} -> "
        f"{', '.join(options['A_prime_measured_inside_frozen_band'])}"
    )
    print(
        "  E  measured inside [0.15,0.45]   : "
        f"{len(options['E_groups'])} -> {', '.join(options['E_groups'])}"
    )
    print(
        "     of which RESPONSIVE           : "
        f"{len(options['E_groups_also_responsive'])} -> "
        f"{', '.join(options['E_groups_also_responsive'])}"
    )
    print(
        "     operating point in 0.15-0.25  : "
        f"{len(options['E_groups_operating_point_in_0_15_0_25_gap'])} -> "
        f"{', '.join(options['E_groups_operating_point_in_0_15_0_25_gap'])}"
    )

    print()
    print("== planned CI half-width (SD=2000 assumption, NOT an achieved value) ==")
    for label, row in result["precision"].items():
        print(
            f"  {label:34s} n={row['n_groups']:2d}  "
            f"+/-{row['planned_ci_half_width_tokens']:8.1f} tokens  "
            f"({row['ratio_vs_n20']:.2f}x)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack", default="local/phase3-g4-reachability-analysis-pack-v1", type=Path
    )
    parser.add_argument("--out", default="local/phase3-g4-reachability-m4", type=Path)
    args = parser.parse_args(argv)

    result = run(args.pack, args.out)
    _print_report(result)
    print()
    print(f"== outputs written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
