"""Phase 3 G4 reachability analysis (M4, read-only).

Reads the frozen M1 evidence pack, re-derives the load-calibration numbers, and
classifies all 40 iteration-1 cells. Writes nothing outside ``--out``; touches no
GPU, no workload input, no frozen artifact.

Usage
-----
    python scripts/probes/phase3_g4_reachability/reachability_analysis.py \
        --pack local/phase3-g4-reachability-analysis-pack-v1 \
        --out  local/phase3-g4-reachability-m4

Design rules this script enforces (RC revision 2, 2026-11-06)
------------------------------------------------------------
1. **Three separate measurements.** §3.6 Headroom / §9 G4
   (``rho0 >= 5% and R0 >= 512``), §5.2 load-calibration target (``rho0`` inside
   a frozen band), and the model's own reachability. None pronounces on another.
2. **Evidence tiers, not a single "reachable".** Every verdict carries
   ``MEASURED`` / ``INTERPOLATED`` / ``EXTRAPOLATED``. Two-level feasibility is
   reported at three nested levels: both bands hit at **measured** pressures,
   both reachable **inside the 256-1024 bracket** (measured or interpolated), and
   **model-only** (requires extrapolation). A model prediction is never reported
   as experimental support.
3. **G4-a guards every extrapolated operating point**, not only the 16-block
   floor. The floor is simply the most common extrapolated point, not a special
   case. An extrapolated or floor operating point is admissible only inside a
   group that has in-bracket separability.
4. **Negative extrapolations are diagnostics only.** For four groups the
   two-point secant returns a negative recomputation ratio at 16 blocks. Those
   values are retained in ``rho0_at_minimum_blocks`` for audit, flagged
   ``physically_valid = false``, and excluded from every ratio-based metric such
   as ``floor_share_of_low_measurement``.
5. **Integrity.** The complete 250-entry pack manifest is SHA-256 verified before
   analysis, including all three G-E source files. Five frozen planning inputs are
   additionally pinned; the proposal's own ``source_observations_sha256`` must bind
   the pinned observation hash.

Read-only. No GPU. No new calibration run is generated or executed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ANALYSIS_VERSION = "phase3.g4_reachability_analysis.v3"

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
#: than this. 0.01 is 1/25 of the 0.25 span the frozen bands require, and at the
#: observed prefill magnitudes it is under 0.7 tokens of recompute per block of
#: pressure, i.e. under 4% of the mechanically expected 16 tokens/block.
FLAT_DELTA_RHO = 0.01

#: WEAK: the metric responds, but by less than the gap between the L_LOW ceiling
#: and the L_HIGH floor (0.25 - 0.15 = 0.10). Below that gap a group cannot
#: straddle the two frozen bands even in principle.
WEAK_DELTA_RHO = 0.10

#: Option E is a *proposal*, not an inherited constant: it covers 0.15-0.25,
#: which neither frozen band covers. Groups whose operating point relies on that
#: sub-interval are reported separately so the change can be adjudicated alone.
OPTION_E_BAND = (0.15, 0.45)

#: Option F keeps both pressures that iteration 1 actually executed and drops the
#: requirement that they hit the designed bands. The conditions are therefore
#: *facts about the executed runs*, not a new parameter choice: no threshold is
#: relaxed and no new pressure is introduced. They are relabelled C1/C2 because
#: "L_LOW"/"L_HIGH" would assert a state separation the data does not show for
#: 11 of 20 groups.
OPTION_F_CONDITIONS: dict[str, str] = {"C1": "L_LOW", "C2": "L_HIGH"}

#: Option F noise design: 5 groups x 2 conditions x R=3, unchanged from v3.
NOISE_GROUPS = 5
NOISE_CONDITIONS = 2
NOISE_REPEATS = 3

#: Planning SD inherited from Phase 2E/2G observations. Used only to *plan*
#: precision; never reported as an achieved half-width.
PLANNING_GROUP_SD_TOKENS = 2000.0
NORMAL_95_Z = 1.959963984540054

#: Run accounting per design. Calibration is A0-only.
ARMS_PER_CELL = 6
REPEATS = 1
DISCRIMINABLE_DECISION_THRESHOLD = 8

PLANNING_DIR = "artifacts/phase3-load-calibration-iteration2-planning-v1"

#: The five frozen planning inputs. ``sha256-manifest-iteration2-proposal.txt``
#: is the one M1 originally named (``35cd...``); it is retained here rather than
#: replaced. The observation CSV is carried as a fifth input so that the JSON and
#: CSV views can disagree loudly instead of silently.
FROZEN_INPUTS: dict[str, str] = {
    f"{PLANNING_DIR}/iteration1-cell-observations.json": (
        "a47acef4a96cbedec37d88c941c70a8ed30f3208d7cac8ec1d599acb6d876d5a"
    ),
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.json": (
        "1b59758a7ef8b5d0b42c4431fa0d2983d27062bf5d89c4a0b4b01175ff3c36a8"
    ),
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.csv": (
        "49738f3715a945038c566f2260eb50053b7fb68760e8ac5b60bcc9bb112d8a36"
    ),
    f"{PLANNING_DIR}/sha256-manifest-iteration2-proposal.txt": (
        "35cd5eead7706a29006a423bfe7be5141a91b96b9fd3c0933d615d9cd3a0bf99"
    ),
    f"{PLANNING_DIR}/iteration1-cell-observations.csv": (
        "2fb77aae8dd734860e7a3664f724fad2113db263ea63f806656abad4975179ec"
    ),
} 

EXPECTED_PACK_MANIFEST_ENTRIES = 250
G_E_REQUIRED_MANIFEST_PATHS = (
    "artifacts/phase3-same-batch-physical-qualification-audit-v1/qualification-audit.json",
    "artifacts/phase3-load-calibration-analysis-v7/evidence-failures.json",
    "artifacts/phase3-concurrent-eligibility-rejection-audit-v1/qualification-rejection-audit.json",
)

#: The four inputs M1 designated, for the provenance report.
M1_DESIGNATED_INPUTS = (
    f"{PLANNING_DIR}/iteration1-cell-observations.json",
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.json",
    f"{PLANNING_DIR}/iteration2-required-blocks-proposal.csv",
    f"{PLANNING_DIR}/sha256-manifest-iteration2-proposal.txt",
)

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

    # reachability under the two-point model, at three evidence levels
    reachable_measured: bool
    reachable_in_bracket: bool
    reachable_model_only: bool
    reachable_evidence_class: str
    rho0_at_minimum_blocks: float
    rho0_at_minimum_physically_valid: bool
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
    rho0_at_minimum_physically_valid: bool
    floor_share_of_low_measurement: float | None
    pressure_response: str

    # G4-a at three evidence levels (nested):
    g4a_measured_two_level: bool
    g4a_in_bracket_two_level: bool
    g4a_model_only_two_level: bool
    g4a_evidence_tier: str
    g4a_achievable_delta_rho_in_bracket: float

    # G4-b per cell, generalized: extrapolated operating points need G4-a
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


def verify_pack_manifest(
    pack: Path, *, expected_entries: int | None = EXPECTED_PACK_MANIFEST_ENTRIES
) -> dict:
    """Verify every entry in the frozen pack manifest before analysis.

    The manifest intentionally does not hash itself or the additional pack
    metadata files. Every listed artifact must exist, remain inside the pack,
    have a unique relative path, and match its SHA-256 digest. The three source
    files used by G-E are mandatory manifest entries, not optional conveniences.
    """

    manifest_path = pack / "sha256-manifest.txt"
    if not manifest_path.is_file():
        raise InputIntegrityError("pack manifest missing: sha256-manifest.txt")

    pack_root = pack.resolve()
    manifest: dict[str, str] = {}
    for line_number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        digest, separator, relative = line.partition("  ")
        relative = relative.strip()
        if not separator or len(digest) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in digest
        ):
            raise InputIntegrityError(
                f"malformed pack manifest entry at line {line_number}"
            )
        if (
            not relative
            or relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
        ):
            raise InputIntegrityError(
                f"unsafe pack manifest path at line {line_number}: {relative!r}"
            )
        if relative in manifest:
            raise InputIntegrityError(f"duplicate pack manifest path: {relative}")

        candidate = pack.joinpath(*relative.split("/"))
        try:
            candidate.resolve().relative_to(pack_root)
        except ValueError as exc:
            raise InputIntegrityError(
                f"pack manifest path escapes evidence pack: {relative}"
            ) from exc
        if not candidate.is_file():
            raise InputIntegrityError(f"manifest file missing: {relative}")

        actual = sha256_file(candidate)
        if actual != digest.lower():
            raise InputIntegrityError(
                f"pack manifest hash mismatch for {relative}: "
                f"expected {digest.lower()}, got {actual}"
            )
        manifest[relative] = actual

    if not manifest:
        raise InputIntegrityError("pack manifest contains no entries")
    if expected_entries is not None and len(manifest) != expected_entries:
        raise InputIntegrityError(
            f"pack manifest entry count mismatch: expected {expected_entries}, "
            f"got {len(manifest)}"
        )

    missing_g_e = sorted(set(G_E_REQUIRED_MANIFEST_PATHS) - set(manifest))
    if missing_g_e:
        raise InputIntegrityError(
            f"G-E source files are not covered by pack manifest: {missing_g_e}"
        )

    return {
        "status": "VERIFIED",
        "manifest_path": "sha256-manifest.txt",
        "entries_checked": len(manifest),
        "missing": 0,
        "mismatches": 0,
        "required_g_e_paths": list(G_E_REQUIRED_MANIFEST_PATHS),
    }


def verify_frozen_inputs(pack: Path) -> dict[str, str]:
    """Verify the frozen planning inputs against pins and the pack manifest."""

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


def bracket_grid() -> list[int]:
    """Pressures inside the interval the two measured points bracket."""

    return [
        n
        for n in legal_pressure_grid()
        if n in ITER1_PRESSURE.values() or (ITER1_PRESSURE["L_LOW"] < n < ITER1_PRESSURE["L_HIGH"])
    ]


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


def _band_points(
    model: GroupModel, band: tuple[float, float], grid: list[int] | None = None
) -> list[int]:
    low, high = band
    candidates = legal_pressure_grid() if grid is None else grid
    return [n for n in candidates if low <= model.rho(n) <= high]


def _pairable(low_points: list[int], high_points: list[int]) -> list[tuple[int, int]]:
    return [
        (lo, hi) for lo in low_points for hi in high_points if hi - lo >= PRESSURE_QUANTUM_BLOCKS
    ]


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
    measured_grid = sorted(ITER1_PRESSURE.values())
    cells: list[Cell] = []

    for row in obs_rows:
        group_id = row["group_id"]
        model = models[group_id]
        prop = proposed[(group_id, row["load_level"])]
        band = (row["target_min"], row["target_max"])
        delta_rho = abs(model.rho(ITER1_PRESSURE["L_HIGH"]) - model.rho(ITER1_PRESSURE["L_LOW"]))

        points_measured = _band_points(model, band, measured_grid)
        points_bracket = _band_points(model, band, bracket_grid())
        points_model = _band_points(model, band)

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
        floor_valid = floor >= 0.0

        if not points_model:
            if delta_rho < FLAT_DELTA_RHO:
                classification = "INFEASIBLE_AND_PRESSURE_INSENSITIVE"
                rationale = (
                    "no legal pressure on the 16-block grid places rho0 in this "
                    "band under the two-point model, and the measured response to "
                    "pressure is below the flat threshold"
                )
            else:
                classification = "INFEASIBLE_BELOW_MINIMUM_PRESSURE"
                rationale = (
                    "the model's value at the 16-block minimum "
                    f"({floor:.4f}) is outside the band, so no legal pressure "
                    "reaches it, while the response to pressure is non-trivial. "
                    "This is an EXTRAPOLATED statement about a point 240 blocks "
                    "below the lowest measured pressure"
                )
        elif points_measured:
            classification = "REACHABLE_MEASURED"
            rationale = (
                "a pressure that was actually run places rho0 inside the band; "
                "this is an observation, not a prediction"
            )
        elif points_bracket:
            classification = "REACHABLE_INTERPOLATED"
            rationale = (
                "the band is reached strictly between the two measured pressures "
                "(258-1022 blocks), so the claim is bounded by the measured "
                "endpoints rather than extrapolated past them"
            )
        else:
            classification = "REACHABLE_EXTRAPOLATED"
            rationale = (
                "the band is reached only outside [256, 1024]; this is a model "
                "prediction at an unmeasured pressure and must not be reported "
                "as experimental support"
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
                reachable_measured=bool(points_measured),
                reachable_in_bracket=bool(points_bracket),
                reachable_model_only=bool(points_model),
                reachable_evidence_class=_best_evidence(points_model),
                rho0_at_minimum_blocks=round(floor, 6),
                rho0_at_minimum_physically_valid=floor_valid,
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
    measured_grid = sorted(ITER1_PRESSURE.values())

    rows: list[GroupSummary] = []
    for group_id in sorted(by_cell):
        model = models[group_id]
        low, high = by_cell[group_id]["L_LOW"], by_cell[group_id]["L_HIGH"]
        delta_rho = abs(high.rho0 - low.rho0)
        floor = model.rho(MIN_PRESSURE_BLOCKS)
        floor_valid = floor >= 0.0

        measured_pairs = _pairable(
            _band_points(model, L_LOW_BAND, measured_grid),
            _band_points(model, L_HIGH_BAND, measured_grid),
        )
        bracket_pairs = _pairable(
            _band_points(model, L_LOW_BAND, bracket_grid()),
            _band_points(model, L_HIGH_BAND, bracket_grid()),
        )
        model_pairs = _pairable(_band_points(model, L_LOW_BAND), _band_points(model, L_HIGH_BAND))

        if measured_pairs:
            tier = "MEASURED"
        elif bracket_pairs:
            tier = "INTERPOLATED"
        elif model_pairs:
            tier = "EXTRAPOLATED"
        else:
            tier = "NONE"

        in_bracket_achievable = max(
            (model.rho(hi) - model.rho(lo) for lo, hi in bracket_pairs), default=0.0
        )

        if delta_rho < FLAT_DELTA_RHO:
            response = "FLAT"
        elif delta_rho < WEAK_DELTA_RHO:
            response = "WEAK"
        else:
            response = "RESPONSIVE"

        bracket_feasible = bool(bracket_pairs)

        def placement(cell: Cell, controllable: bool = bracket_feasible) -> bool:
            """G4-b, generalized (RC6).

            An operating point counts when the model places rho0 in band. If that
            operating point is **extrapolated** -- which includes every clamp to
            the 16-block floor -- it counts only inside a group whose two-level
            separability is already established *within the measured bracket*.
            """

            if cell.proposed_status != "PASS":
                return False
            if cell.proposal_evidence_class != "EXTRAPOLATED":
                return True
            return controllable

        both_ok = placement(low) and placement(high)
        collision = low.proposed_blocks == high.proposed_blocks
        model_feasible = bool(model_pairs)

        # A collision dominates: if both loads resolve to the same pressure there
        # is no contrast to support, whatever the model says about the bands.
        if collision:
            verdict = "BOTH_LOADS_COLLAPSE_TO_SAME_PRESSURE"
        elif model_feasible and both_ok:
            if (
                low.proposal_evidence_class == "MEASURED"
                and high.proposal_evidence_class == "MEASURED"
            ):
                verdict = "TWO_LEVEL_CONTRAST_MEASURED_SUPPORTED"
            else:
                verdict = "TWO_LEVEL_CONTRAST_INTERPOLATED_SUPPORTED"
        elif model_feasible:
            verdict = "TWO_LEVEL_CONTRAST_MODEL_ONLY"
        else:
            verdict = "TWO_LEVEL_CONTRAST_UNAVAILABLE"

        low_tag = tags.get((group_id, "L_LOW"), "")
        high_tag = tags.get((group_id, "L_HIGH"), "")
        floor_share = round(floor / low.rho0, 4) if floor_valid and low.rho0 > 0 else None

        rows.append(
            GroupSummary(
                group_id=group_id,
                rho0_l_low=round(low.rho0, 6),
                rho0_l_high=round(high.rho0, 6),
                delta_rho_measured=round(delta_rho, 6),
                slope_tokens_per_block=round(model.slope_r, 4),
                empirical_marginal_response_ratio=round(model.slope_r / BLOCK_SIZE_TOKENS, 4),
                rho0_at_minimum_blocks=round(floor, 6),
                rho0_at_minimum_physically_valid=floor_valid,
                floor_share_of_low_measurement=floor_share,
                pressure_response=response,
                g4a_measured_two_level=bool(measured_pairs),
                g4a_in_bracket_two_level=bracket_feasible,
                g4a_model_only_two_level=model_feasible,
                g4a_evidence_tier=tier,
                g4a_achievable_delta_rho_in_bracket=round(in_bracket_achievable, 6),
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
    group's rows carry a different frozen ``limitation`` tag. Reporting both, plus
    the differing groups, reproduces the 9-versus-10 count from the frozen file
    instead of guessing a convention.
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
        "note": (
            "The 9-versus-10 difference is g14, whose rows carry "
            "FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE rather than "
            "TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE. If M1 was reading a "
            "different field, the difference set above localises it."
        ),
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
            "The Headroom gate itself is not what fails on iteration-1 "
            "parameters: it admits 38 of 40 cells. It has never been evaluated "
            "at any other pressure, which is why a design that moves pressures "
            "needs a new calibration run (see calibration-cost accounting)."
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
        "reachable_measured": sum(1 for c in cells if c.reachable_measured),
        "reachable_in_bracket": sum(1 for c in cells if c.reachable_in_bracket),
        "reachable_model_only": sum(1 for c in cells if c.reachable_model_only),
        "by_load_classification": by_load,
        "groups_two_level_measured": sorted(g.group_id for g in groups if g.g4a_measured_two_level),
        "groups_two_level_in_bracket": sorted(
            g.group_id for g in groups if g.g4a_in_bracket_two_level
        ),
        "groups_two_level_model_only": sorted(
            g.group_id for g in groups if g.g4a_model_only_two_level
        ),
        "groups_two_level_needs_extrapolation": sorted(
            g.group_id
            for g in groups
            if g.g4a_model_only_two_level and not g.g4a_in_bracket_two_level
        ),
    }


def _operating_points(
    cells: list[Cell], bands: list[tuple[float, float]], label: str
) -> list[dict]:
    """Pick one measured operating point per group inside any of ``bands``.

    The point must be a **measured** pressure so that the Headroom gate (§3.6) has
    actually been evaluated there. Ties break on lower `R0` (cheaper), then lower
    pressure, then group id -- a rule that can be frozen in G0. Candidates are
    pooled across all supplied bands first, so a group with a qualifying point at
    both loads is counted once, at its cheapest qualifying operating point.
    """

    by_group: dict[str, list[Cell]] = {}
    for cell in cells:
        by_group.setdefault(cell.group_id, []).append(cell)

    picked: list[dict] = []
    for group_id in sorted(by_group):
        candidates = [
            c
            for c in by_group[group_id]
            if c.measured_evidence_class == "MEASURED"
            and any(low <= c.rho0 <= high for low, high in bands)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda c: (c.r0, c.measured_blocks, c.group_id))
        chosen = candidates[0]
        picked.append(
            {
                "group_id": group_id,
                "chosen_load_level": chosen.load_level,
                "chosen_pressure_blocks": chosen.measured_blocks,
                "rho0_at_operating_point": round(chosen.rho0, 6),
                "r0_at_operating_point": chosen.r0,
                "headroom_ratio_ok": chosen.headroom_ratio_ok,
                "headroom_abs_ok": chosen.headroom_abs_ok,
                "headroom_eligible": chosen.headroom_eligible,
                "band_matched": (
                    "L_LOW" if L_LOW_BAND[0] <= chosen.rho0 <= L_LOW_BAND[1] else "L_HIGH"
                ),
                "in_option_e_only_gap": L_LOW_BAND[1] < chosen.rho0 < L_HIGH_BAND[0],
                "alternative_candidates": [
                    f"{c.load_level}@{c.measured_blocks}={c.rho0:.4f}" for c in candidates[1:]
                ],
                "design": label,
            }
        )
    return picked


def option_report(cells: list[Cell], groups: list[GroupSummary]) -> dict:
    """Group counts and operating-point mappings per design option."""

    frozen_bands = [L_LOW_BAND, L_HIGH_BAND]
    a_prime_map = {
        row["group_id"]: row for row in _operating_points(cells, frozen_bands, "A_PRIME")
    }

    e_map: dict[str, dict] = {
        row["group_id"]: row for row in _operating_points(cells, [OPTION_E_BAND], "E")
    }
    # E must not lose an A' group: keep the A' pick where it already qualifies.
    for group_id, row in a_prime_map.items():
        e_map.setdefault(group_id, {**row, "design": "E"})

    responsive = {g.group_id for g in groups if g.pressure_response == "RESPONSIVE"}
    weak = {g.group_id for g in groups if g.pressure_response == "WEAK"}
    flat = {g.group_id for g in groups if g.pressure_response == "FLAT"}

    a_prime_ids = sorted(a_prime_map)
    e_ids = sorted(e_map)

    # --- Option F: both executed pressures, all groups, no band requirement ---
    by_group: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        by_group.setdefault(cell.group_id, {})[cell.load_level] = cell

    paired_groups = [
        group_id
        for group_id in sorted(by_group)
        if all(
            by_group[group_id][level].headroom_eligible for level in OPTION_F_CONDITIONS.values()
        )
    ]
    excluded_pairs: list[dict] = []
    for group_id in sorted(by_group):
        for label, level in OPTION_F_CONDITIONS.items():
            cell = by_group[group_id][level]
            if cell.headroom_eligible:
                continue
            reasons = []
            if not cell.headroom_ratio_ok:
                reasons.append(f"rho0 {cell.rho0:.4f} below the 5% ratio floor")
            if not cell.headroom_abs_ok:
                reasons.append(f"R0 {cell.r0} below the 512-token floor")
            excluded_pairs.append(
                {
                    "group_id": group_id,
                    "condition": label,
                    "load_level": level,
                    "why": "; ".join(reasons),
                    "effect": "the group cannot supply a two-condition pair",
                }
            )

    f_block = {
        "rule": (
            "Keep both executed pressures (256 and 1024 blocks) for all 20 groups. "
            "Band attainment is a manipulation check, not an admission rule."
        ),
        "conditions": {
            label: {
                "load_level": level,
                "pressure_blocks": ITER1_PRESSURE[level],
                "evidence_class": "MEASURED",
            }
            for label, level in OPTION_F_CONDITIONS.items()
        },
        "arms": ARMS_PER_CELL,
        "groups_in_design": len(by_group),
        "cells_in_design": len(cells),
        "cells_headroom_eligible": sum(1 for c in cells if c.headroom_eligible),
        "paired_groups": paired_groups,
        "paired_groups_n": len(paired_groups),
        "excluded_pairs": excluded_pairs,
        "per_condition_analysed_cells": {
            label: sum(1 for c in cells if c.load_level == level and c.headroom_eligible)
            for label, level in OPTION_F_CONDITIONS.items()
        },
        "new_calibration_required": False,
        "noise_design": {
            "groups": NOISE_GROUPS,
            "conditions": NOISE_CONDITIONS,
            "repeats": NOISE_REPEATS,
            "runs": NOISE_GROUPS * NOISE_CONDITIONS * NOISE_REPEATS,
            "unchanged_from_v3": True,
        },
        "F_responsive": sorted(set(paired_groups) & responsive),
        "F_weak": sorted(set(paired_groups) & weak),
        "F_flat": sorted(set(paired_groups) & flat),
        "F_design_responsive": sorted(responsive),
        "F_design_weak": sorted(weak),
        "F_design_flat": sorted(flat),
        "F_h3_primary_cells": sum(
            1 for c in cells if c.group_id in responsive and c.headroom_eligible
        ),
        "design_strata": {
            "RESPONSIVE": len(responsive),
            "WEAK": len(weak),
            "FLAT": len(flat),
        },
    }

    return {
        "A_two_level_groups": sorted(
            g.group_id for g in groups if g.verdict == "TWO_LEVEL_CONTRAST_MEASURED_SUPPORTED"
        ),
        "A_two_level_groups_including_interpolated": sorted(
            g.group_id
            for g in groups
            if g.verdict
            in {
                "TWO_LEVEL_CONTRAST_MEASURED_SUPPORTED",
                "TWO_LEVEL_CONTRAST_INTERPOLATED_SUPPORTED",
            }
        ),
        "A_two_level_groups_model_only": sorted(
            g.group_id for g in groups if g.verdict == "TWO_LEVEL_CONTRAST_MODEL_ONLY"
        ),
        "B_and_C_note": (
            "B needs new group acquisition and a full 40-run recalibration; C is "
            "rejected because it changes the frozen 2048-block pool"
        ),
        "A_PRIME_groups": a_prime_ids,
        "A_PRIME_operating_points": [a_prime_map[g] for g in a_prime_ids],
        "E_band": list(OPTION_E_BAND),
        "E_groups": e_ids,
        "E_operating_points": [e_map[g] for g in e_ids],
        "E_groups_added_by_gap": [g for g in e_ids if g not in set(a_prime_ids)],
        "A_PRIME_responsive": sorted(set(a_prime_ids) & responsive),
        "A_PRIME_weak": sorted(set(a_prime_ids) & weak),
        "A_PRIME_flat": sorted(set(a_prime_ids) & flat),
        "E_responsive": sorted(set(e_ids) & responsive),
        "E_weak": sorted(set(e_ids) & weak),
        "E_flat": sorted(set(e_ids) & flat),
        "F": f_block,
        "frozen_band_union": [
            L_LOW_BAND[0],
            L_LOW_BAND[1],
            L_HIGH_BAND[0],
            L_HIGH_BAND[1],
        ],
    }


def _eligible_cells_by_group(
    cells: list[Cell], group_ids: list[str] | None = None
) -> dict[str, dict[str, Cell]]:
    """Headroom-eligible cells per group, optionally restricted to ``group_ids``."""

    wanted = set(group_ids) if group_ids is not None else None
    out: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        if not cell.headroom_eligible:
            continue
        if wanted is not None and cell.group_id not in wanted:
            continue
        out.setdefault(cell.group_id, {})[cell.load_level] = cell
    return out


def _h3_population(cells: list[Cell], group_ids: list[str], stratum: str) -> dict:
    """Describe one H3 population: groups, cells per condition, and weights.

    H3 is a per-cell ``A0 - N0`` comparison. When a group contributes two
    eligible cells (one per condition), those two cells are **not** independent
    draws -- they are the same workload. So the group-level estimator averages
    the group's eligible cells first and then treats the group as one unit with
    weight ``1 / G``. Cell-weighted averaging is deliberately *not* used: it
    would give two-cell groups twice the influence of one-cell groups, which
    would make the inference depend on Headroom's per-condition count rather
    than on the workload pool.
    """

    by_group = _eligible_cells_by_group(cells, group_ids)
    two_cell = sorted(g for g, c in by_group.items() if len(c) == 2)
    one_cell = sorted(g for g, c in by_group.items() if len(c) == 1)
    total_cells = sum(len(c) for c in by_group.values())
    return {
        "stratum": stratum,
        "groups": sorted(by_group),
        "group_count": len(by_group),
        "cells_total": total_cells,
        "cells_C1": sum(1 for c in by_group.values() if "L_LOW" in c),
        "cells_C2": sum(1 for c in by_group.values() if "L_HIGH" in c),
        "groups_with_two_cells": two_cell,
        "groups_with_one_cell": one_cell,
        "one_cell_groups_missing_condition": {
            group_id: ("C1" if by_group[group_id].keys() == {"L_HIGH"} else "C2")
            for group_id in one_cell
        },
        "estimator": (
            "group mean of Headroom-eligible cells, then mean / bootstrap over "
            "groups; one cell counts fully, two cells are averaged 1/2 each"
        ),
        "group_weight": ("1 / group_count -- equal group weight, NOT proportional to cell count"),
        "cell_weight_within_group": "1 / (cells in that group); 1 for a one-cell group",
        "resampling_unit": "group",
        "blind_to_arms": True,
    }


def h3_report(cells: list[Cell], groups: list[GroupSummary], options: dict) -> dict:
    """H3 populations, restructured for RC10-2.

    The previous revision promoted RESPONSIVE to H3's primary population and
    dropped FLAT on the grounds that ``A0 - N0`` was *predicted* to be near zero
    there. That inference was wrong in kind: a small ``dRho`` describes how much
    **A0's own recomputation** moves with pressure, and says nothing about what a
    force-release arm does relative to A0. Prediction is not a reason to remove a
    group from a hypothesis.

    So the structure is now:

    * **H3-0 (original, decision-bearing)** -- every Headroom-qualified cell, in
      both conditions, all strata included. This is the hypothesis as written.
    * **H3-R (separate, pre-registered)** -- RESPONSIVE only. An *additional*
      hypothesis about whether the forced-release cost is observable where the
      baseline itself responds to pressure. It has its own estimand and cannot
      replace H3-0.
    * **Heterogeneity analysis** -- RESPONSIVE / WEAK / FLAT reported side by
      side, pre-registered, no stratum allowed to gate another.
    """

    strata = {g.group_id: g.pressure_response for g in groups}
    all_groups = sorted(strata)
    responsive = [g for g in all_groups if strata[g] == "RESPONSIVE"]
    weak = [g for g in all_groups if strata[g] == "WEAK"]
    flat = [g for g in all_groups if strata[g] == "FLAT"]

    h3_0 = _h3_population(cells, all_groups, "ALL_HEADROOM_QUALIFIED")
    h3_r = _h3_population(cells, responsive, "RESPONSIVE")
    h3_w = _h3_population(cells, weak, "WEAK")
    h3_f = _h3_population(cells, flat, "FLAT")

    return {
        "rule": (
            "H3-0 is the hypothesis as written: every Headroom-qualified cell, both "
            "conditions, all strata. Strata are a pre-registered heterogeneity "
            "analysis, not an admission rule. H3-R (RESPONSIVE only) is an "
            "additional hypothesis with its own estimand and cannot replace H3-0."
        ),
        "primary": {
            "id": "H3-0",
            "question": (
                "Does forced release (A0 vs N0) have a net cost on recomputation, "
                "across the Headroom-qualified workload pool?"
            ),
            "population": "every Headroom-qualified cell, both conditions, all strata",
            "flip_note": (
                "FLAT is INCLUDED. A small dRho measures A0's baseline sensitivity "
                "to pressure; it is not evidence about the arm-vs-A0 difference, so "
                "it cannot exclude a group from this hypothesis."
            ),
            **h3_0,
        },
        "secondary_hypothesis": {
            "id": "H3-R",
            "question": (
                "Is the forced-release cost observable in the subset whose baseline "
                "recomputation itself responds to pressure?"
            ),
            "status": "pre-registered, separate, not a replacement for H3-0",
            "rationale": (
                "A non-trivial empirical marginal response ratio is a necessary "
                "condition for the mechanism to have anywhere to act. If the cost "
                "appears only here, that is a finding about the mechanism's domain; "
                "if it appears in H3-0 and not here, that is a finding about "
                "sensitivity, not a contradiction."
            ),
            "threshold_provenance": "dRho >= 0.10, the same constant G4-a uses",
            **h3_r,
        },
        "heterogeneity": {
            "status": "pre-registered, descriptive, reported side by side",
            "note": (
                "No stratum gates another. The FLAT stratum is reported with its "
                "own interval even though its predicted effect is small, because "
                "'predicted small' is not 'measured zero'."
            ),
            "WEAK": h3_w,
            "FLAT": h3_f,
        },
        "by_design": {
            "F": {
                "population": "campaign runs all 20 groups, both conditions",
                "headroom_cells": {"C1": h3_0["cells_C1"], "C2": h3_0["cells_C2"]},
                "H3_0_groups": h3_0["group_count"],
                "H3_0_cells": h3_0["cells_total"],
                "H3_R_groups": h3_r["group_count"],
                "H3_R_cells": h3_r["cells_total"],
            },
            "A_PRIME": {
                "population": "one measured operating point per group",
                "H3_0_groups": len(options["A_PRIME_groups"]),
                "H3_R_groups": len(options["A_PRIME_responsive"]),
            },
            "E": {
                "population": "one measured operating point per group",
                "H3_0_groups": len(options["E_groups"]),
                "H3_R_groups": len(options["E_responsive"]),
            },
        },
        "flat_policy": (
            "FLAT is retained in H3-0 and reported as its own heterogeneity "
            "stratum. It is not removed from the hypothesis; it is only expected "
            "to be uninformative, and expectation is not measurement."
        ),
    }


def _f_group_average_precision(paired_n: int) -> list[dict]:
    """Planned precision of the two-condition group-averaged delta.

    Averaging the two condition deltas inside a group cancels part of the noise
    when they are positively correlated: ``Var(mean) = sd^2 * (1 + rho) / 2``.
    ``rho`` is not measured here, so the whole range is reported rather than a
    single flattering number.
    """

    baseline = NORMAL_95_Z * PLANNING_GROUP_SD_TOKENS / (20**0.5)
    rows: list[dict] = []
    for rho in (0.0, 0.5, 0.8, 1.0):
        sd = PLANNING_GROUP_SD_TOKENS * (((1.0 + rho) / 2.0) ** 0.5)
        half_width = NORMAL_95_Z * sd / (paired_n**0.5)
        rows.append(
            {
                "within_group_rho": rho,
                "sd_tokens": round(sd, 1),
                "planned_ci_half_width_tokens": round(half_width, 1),
                "ratio_vs_single_level_n20": round(half_width / baseline, 3),
                "equivalent_single_level_n": round(paired_n * 2.0 / (1.0 + rho), 1),
            }
        )
    return rows


def _f_interaction_precision(paired_n: int) -> list[dict]:
    """Planned precision of ``delta_D = Delta(C2) - Delta(C1)``.

    ``sd(delta_D) = sqrt(2) * sd_delta * sqrt(1 - rho)``: the difference of two
    correlated deltas is *worse* than a single delta when the conditions are
    independent, and no better than one delta when they are perfectly correlated.
    """

    rows: list[dict] = []
    for rho in (0.0, 0.5, 0.8):
        sd = (2.0**0.5) * PLANNING_GROUP_SD_TOKENS * ((1.0 - rho) ** 0.5)
        half_width = NORMAL_95_Z * sd / (paired_n**0.5)
        rows.append(
            {
                "within_group_rho": rho,
                "sd_tokens": round(sd, 1),
                "planned_ci_half_width_tokens": round(half_width, 1),
            }
        )
    return rows


def f_report(cells: list[Cell], groups: list[GroupSummary], options: dict) -> dict:
    """Option F -- two-level fixed-pressure evaluation (offline design analysis).

    F keeps both pressures that were actually executed and stops treating the
    designed ``rho0`` bands as an admission rule. Nothing is relaxed: no threshold
    moves, no new pressure appears, and every cell in the analysis is one that was
    actually run. What changes is the *operational definition of the condition* --
    from "a level of a controlled variable" to "a fixed operating point" -- and
    that is why the band check becomes a manipulation check instead of a gate.
    """

    f = options["F"]
    strata = {g.group_id: g.pressure_response for g in groups}
    by_group: dict[str, dict[str, Cell]] = {}
    for cell in cells:
        by_group.setdefault(cell.group_id, {})[cell.load_level] = cell

    rows: list[dict] = []
    for group_id in sorted(by_group):
        low = by_group[group_id]["L_LOW"]
        high = by_group[group_id]["L_HIGH"]
        rows.append(
            {
                "group_id": group_id,
                "condition_C1": {
                    "load_level": "L_LOW",
                    "pressure_blocks": low.measured_blocks,
                    "rho0": round(low.rho0, 6),
                    "r0": low.r0,
                    "in_designed_band": low.measured_inside_target,
                    "headroom_eligible": low.headroom_eligible,
                },
                "condition_C2": {
                    "load_level": "L_HIGH",
                    "pressure_blocks": high.measured_blocks,
                    "rho0": round(high.rho0, 6),
                    "r0": high.r0,
                    "in_designed_band": high.measured_inside_target,
                    "headroom_eligible": high.headroom_eligible,
                },
                "delta_rho_measured": round(high.rho0 - low.rho0, 6),
                "pressure_response": strata[group_id],
                "both_in_designed_band": (
                    low.measured_inside_target and high.measured_inside_target
                ),
                "neither_in_designed_band": (
                    not low.measured_inside_target and not high.measured_inside_target
                ),
                "paired_admissible": (low.headroom_eligible and high.headroom_eligible),
            }
        )

    both = [r["group_id"] for r in rows if r["both_in_designed_band"]]
    neither = [r["group_id"] for r in rows if r["neither_in_designed_band"]]
    one = [
        r["group_id"]
        for r in rows
        if not r["both_in_designed_band"] and not r["neither_in_designed_band"]
    ]
    responsive = [r for r in rows if r["pressure_response"] == "RESPONSIVE"]
    weak = [r for r in rows if r["pressure_response"] == "WEAK"]
    flat = [r for r in rows if r["pressure_response"] == "FLAT"]
    paired_n = f["paired_groups_n"]
    paired_responsive = [r["group_id"] for r in responsive if r["paired_admissible"]]

    return {
        "design": {
            "name": "OPTION_F_TWO_LEVEL_FIXED_PRESSURE",
            "conditions": f["conditions"],
            "arms": f["arms"],
            "groups_in_design": f["groups_in_design"],
            "cells_in_design": f["cells_in_design"],
            "band_attainment_is_a_gate": False,
            "band_attainment_role": "manipulation_check",
            "new_calibration_required": f["new_calibration_required"],
            "why_no_new_calibration": (
                "F's two conditions are exactly the two pressures iteration 1 "
                "executed (40 A0 runs). Every cell in the analysis therefore has a "
                "measured rho0 and a measured R0 at the pressure it will be run at, "
                "so the §3.6 Headroom test has already been evaluated there."
            ),
        },
        "manipulation_check": {
            "purpose": (
                "Report whether the two fixed pressures induced the intended "
                "recomputation states. Not used to admit or exclude any cell."
            ),
            "cells_in_designed_band": sum(
                1
                for r in rows
                for key in ("condition_C1", "condition_C2")
                if r[key]["in_designed_band"]
            ),
            "cells_total": 2 * len(rows),
            "groups_with_both_conditions_in_band": both,
            "groups_with_one_condition_in_band": one,
            "groups_with_neither_condition_in_band": neither,
            "delta_rho_at_least_0_10": [r["group_id"] for r in responsive],
            "delta_rho_between_0_01_and_0_10": [r["group_id"] for r in weak],
            "delta_rho_below_0_01": [r["group_id"] for r in flat],
            "reading": (
                "The intended two-state assignment is realised in "
                f"{len(both)} of {len(rows)} groups and the metric separates by at "
                "least 0.10 in "
                f"{len(responsive)}. F therefore measures two *fixed* operating "
                "points, not two validated levels of a manipulated variable; that "
                "is the claim it is allowed to make."
            ),
            "rows": rows,
        },
        "population": {
            "levels": {
                "campaign": {
                    "groups": f["groups_in_design"],
                    "cells": f["cells_in_design"],
                    "note": (
                        "All 20 groups are executed at both conditions. This is the "
                        "execution population, not an analysis population."
                    ),
                },
                "C1_analysed": {
                    "groups": f["per_condition_analysed_cells"]["C1"],
                    "cells": f["per_condition_analysed_cells"]["C1"],
                    "note": "Headroom-qualified cells in condition C1",
                },
                "C2_analysed": {
                    "groups": f["per_condition_analysed_cells"]["C2"],
                    "cells": f["per_condition_analysed_cells"]["C2"],
                    "note": "Headroom-qualified cells in condition C2",
                },
                "paired_primary": {
                    "groups": paired_n,
                    "cells": 2 * paired_n,
                    "note": (
                        "Groups with a Headroom-qualified cell in BOTH conditions. "
                        "The group-averaged delta is estimated here and only here."
                    ),
                },
            },
            "scope_warning": (
                f"The paired primary estimates the {paired_n}-group paired "
                f"population, NOT the {f['groups_in_design']}-group pool. g09 and "
                "g18 are executed and enter the C2 estimate and H3-0, but they do "
                "not exist in the paired estimand's population. Any sentence that "
                "awkwardly pairs 'full pool' with the paired number is wrong."
            ),
            "paired_groups": f["paired_groups"],
            "paired_groups_n": paired_n,
            "excluded_pairs": f["excluded_pairs"],
            "per_condition_analysed_cells": f["per_condition_analysed_cells"],
            "strata_over_design": {
                "RESPONSIVE": len(responsive),
                "WEAK": len(weak),
                "FLAT": len(flat),
            },
            "strata_over_paired": {
                "RESPONSIVE": len(paired_responsive),
                "WEAK": len([r for r in weak if r["paired_admissible"]]),
                "FLAT": len([r for r in flat if r["paired_admissible"]]),
            },
        },
        "estimands": {
            "per_condition": (
                "Delta per condition, bootstrapped over the groups analysed in that "
                "condition (C1: "
                f"{f['per_condition_analysed_cells']['C1']} cells, C2: "
                f"{f['per_condition_analysed_cells']['C2']} cells)."
            ),
            "group_averaged": (
                "Headline: mean over the two condition deltas inside each paired "
                f"group, then bootstrapped over the {paired_n} paired groups. "
                "Averaging inside the group first keeps group as the independent "
                "unit."
            ),
            "interaction": (
                "Two separate analyses, never merged into one conclusion. "
                "(A) Interaction-A over all 18 complete pairs: "
                "delta_D_g = Delta_g(C2) - Delta_g(C1), group is the unit. "
                "(B) Interaction-B over the RESPONSIVE pairs only: the same "
                "quantity, reported as a pre-registered heterogeneity analysis."
            ),
        },
        "precision": {
            "group_averaged": _f_group_average_precision(paired_n),
            "interaction": _f_interaction_precision(paired_n),
            "caveat": (
                "Planning values from an assumed per-delta group SD of "
                f"{PLANNING_GROUP_SD_TOKENS:.0f} tokens and an unmeasured "
                "within-group correlation. Not achieved precision."
            ),
        },
        "interaction": {
            "estimable": paired_n > 0,
            "interaction_A_all_pairs": {
                "definition": "delta_D over all 18 complete pairs, group-weighted",
                "paired_groups": paired_n,
                "group_weight": "1 / paired_groups",
                "is_primary_interaction_analysis": True,
                "meets_minimum_analysed_cells": (paired_n >= DISCRIMINABLE_DECISION_THRESHOLD),
                "note": (
                    "All 18 pairs are used. No stratum is removed, and no stratum's "
                    "difference is asserted to be zero in advance."
                ),
            },
            "interaction_B_responsive": {
                "definition": (
                    "delta_D over the RESPONSIVE pairs only, reported as a "
                    "pre-registered heterogeneity analysis"
                ),
                "paired_groups": len(paired_responsive),
                "groups": paired_responsive,
                "is_primary_interaction_analysis": False,
                "meets_minimum_analysed_cells": (
                    len(paired_responsive) >= DISCRIMINABLE_DECISION_THRESHOLD
                ),
                "note": (
                    "Heterogeneity, not a second primary. A difference between "
                    "Interaction-A and Interaction-B is a statement about where the "
                    "interaction is visible, not a contradiction."
                ),
            },
            "not_inferable_from_delta_rho": (
                "dRho measures how much A0's own recomputation moves between the "
                "two conditions. It says nothing about how an arm's difference from "
                "A0 moves between them. So a small dRho is NOT evidence that that "
                "group's delta_D is zero, and FLAT groups are retained in "
                "Interaction-A rather than assumed away."
            ),
            "caveats": [
                (
                    "g09 and g18 lose their pair to Headroom, so both interaction "
                    f"analyses are limited to {paired_n} complete pairs, and "
                    f"Interaction-B to {len(paired_responsive)} RESPONSIVE groups "
                    "rather than 9."
                ),
                (
                    "Interaction-B is below the 8-group minimum, so its interval is "
                    "reported with N_analyzed and no verdict."
                ),
                (
                    "A difference of differences has sd sqrt(2)*sd_delta*sqrt(1-rho); "
                    "it is less precise than either main effect, not more."
                ),
            ],
        },
        "threats": [
            (
                "Condition semantics: calling C1/C2 'low' and 'high' pressure would "
                "assert a state separation the data contradicts for 14 of 20 "
                "groups. The labels are fixed operating points."
            ),
            (
                "Dilution of the POOLED estimate: the group-averaged delta is a "
                "population average over groups whose baseline sensitivity differs "
                "by an order of magnitude, so it is not an effect size and a small "
                "value is not evidence that the mechanism is weak. Stratum "
                "estimates carry the mechanistic reading."
            ),
            (
                "Attribution: the two conditions are not two levels of one "
                "variable for 11 groups, so a condition-by-arm interaction cannot "
                "be attributed to pressure intensity there."
            ),
            (
                "No post-hoc selection: groups and strata are fixed from A0 "
                "calibration only; no group may be dropped after seeing an arm."
            ),
        ],
    }


NOISE_SELECTION_SALT = "phase3-noise-selection-v1"

#: Stratified allocation of the 5 noise groups over the paired population. The
#: proportions follow the paired stratum sizes (7 RESPONSIVE / 8 WEAK / 3 FLAT),
#: rounded up for the smallest stratum so that no stratum is unrepresented.
NOISE_STRATUM_ALLOCATION = {"RESPONSIVE": 2, "WEAK": 2, "FLAT": 1}


def _selection_key(group_id: str) -> str:
    """Deterministic, result-blind ordering key for group selection.

    Hashing a frozen salt with the group id gives a reproducible order that cannot
    be steered after seeing any measurement, and needs no stored random state. It
    is not "random" in the sampling sense -- it is a fixed permutation, which is
    exactly what a pre-registration needs.
    """

    return hashlib.sha256(f"{NOISE_SELECTION_SALT}:{group_id}".encode()).hexdigest()


def noise_selection_report(cells: list[Cell], groups: list[GroupSummary], options: dict) -> dict:
    """RC10-5: close the noise-calibration rule.

    Protocol v3 §6.4 requires the noise set to be independent of the Headroom
    *screening*. Two readings are possible and they are not equivalent:

    * **Decision independence** (the requirement's purpose) -- the noise set must
      not influence which cells are analysable. Drawing from the already-decided
      paired set does not: the Headroom outcome is fixed before any noise run.
    * **Population independence** (a stronger reading) -- the noise set must be a
      sample of all 20 groups regardless of Headroom. This is what "independent of
      Headroom screening" literally says, and a paired-only draw violates it.

    F needs pairs, so its noise sample must come from the 18 paired groups; a
    σ_run estimated on cells that are not in the analysis population would not
    describe the `tied` threshold that is applied to that population. The report
    therefore takes the first reading, states the cost of the second, and asks for
    an explicit v4 amendment rather than claiming "unchanged because it is still
    30 runs".
    """

    strata = {g.group_id: g.pressure_response for g in groups}
    paired = options["F"]["paired_groups"]
    paired_set = set(paired)

    all_20 = sorted(strata)
    unpaired = [g for g in all_20 if g not in paired_set]

    selection: dict[str, list[str]] = {}
    for stratum, count in NOISE_STRATUM_ALLOCATION.items():
        candidates = sorted((g for g in paired if strata[g] == stratum), key=_selection_key)
        selection[stratum] = candidates[:count]

    selected = sorted(g for members in selection.values() for g in members)
    cells_in_noise = len(selected) * NOISE_CONDITIONS
    df = cells_in_noise * (NOISE_REPEATS - 1)

    alt_candidates = {
        stratum: sorted((g for g in all_20 if strata[g] == stratum), key=_selection_key)[
            : NOISE_STRATUM_ALLOCATION[stratum]
        ]
        for stratum in NOISE_STRATUM_ALLOCATION
    }
    alt_selected = sorted(g for members in alt_candidates.values() for g in members)

    return {
        "independence": {
            "v3_requirement": (
                "§6.4: the noise set is independent of the main campaign and of "
                "the Headroom screening"
            ),
            "decision_independence": {
                "preserved": True,
                "why": (
                    "The Headroom outcome is computed from A0 calibration data and "
                    "frozen before any noise run. Selecting the noise groups from "
                    "the resulting paired set cannot feed back into that decision."
                ),
            },
            "population_independence": {
                "preserved": False,
                "why": (
                    "A paired-only draw is conditional on Headroom passing at both "
                    "conditions, so sigma_run describes the paired population and "
                    "not all 20 groups."
                ),
                "consequence": (
                    f"{len(unpaired)} group(s) ({', '.join(unpaired)}) are never "
                    "sampled for noise and have no run-to-run variance estimate."
                ),
            },
            "verdict": (
                "Drawing from the 18 paired groups changes the reading of §6.4 "
                "from population independence to decision independence. That is "
                "defensible for F because `tied` is applied to the same paired "
                "population, but it is a change and must be written into v4 rather "
                "than described as an unchanged 30-run design."
            ),
        },
        "selection_rule": {
            "candidate_set": "the 18 Headroom-paired groups",
            "deterministic_key": (f"sha256('{NOISE_SELECTION_SALT}:' || group_id), ascending"),
            "why_not_random": (
                "A frozen hash permutation is reproducible without storing random "
                "state and cannot be steered after seeing a measurement."
            ),
            "stratum_allocation": dict(NOISE_STRATUM_ALLOCATION),
            "allocation_rationale": (
                "Proportional to the paired strata (7/8/3) with the smallest "
                "stratum rounded up to 1 so no stratum is unrepresented."
            ),
            "selected_groups": selected,
            "selected_by_stratum": selection,
            "design": (
                f"{NOISE_GROUPS} groups x {NOISE_CONDITIONS} conditions x R="
                f"{NOISE_REPEATS} = {NOISE_GROUPS * NOISE_CONDITIONS * NOISE_REPEATS} runs"
            ),
            "alternative_if_population_independence_is_required": {
                "candidate_set": "all 20 groups",
                "selected_groups": alt_selected,
                "selected_by_stratum": alt_candidates,
                "cost": (
                    "The FLAT allocation would sample a group that may fail Headroom "
                    "at C1, so its sigma_run would partly describe a cell that is "
                    "not analysed. Same 30 runs either way."
                ),
            },
            "frozen_by": "must be written into G0 with the salt and the allocation",
        },
        "variance_estimation": {
            "frozen_rule": (
                "ONE rule: sigma_run is the pooled within-cell standard deviation "
                "of per-run Sigma(E-C) over the 10 sampled cells (5 groups x 2 "
                "conditions), with equal weight per cell and df = 10 x (3 - 1) = 20. "
                "sigma_delta = sqrt(2) sigma_run, tied = 2 sqrt(2) sigma_run. No "
                "other estimator is permitted for this campaign."
            ),
            "assumption": (
                "COMMON within-cell variance across strata and conditions (homoscedasticity)."
            ),
            "justification": [
                (
                    "Every sampled cell has the same R = 3, so the pooled estimator "
                    "is balanced rather than weighted by unequal cell counts."
                ),
                (
                    "The design needs ONE absolute `tied` threshold applied "
                    "uniformly to the paired population; per-stratum thresholds "
                    "would change what counts as tied depending on which stratum a "
                    "cell fell into, and no protocol section defines that."
                ),
                (
                    "Per-stratum estimates would rest on 4 cells (df 4) each, which "
                    "is too unstable to freeze as a threshold."
                ),
            ],
            "sigma_run": (
                "pooled within-cell SD, equal weight per cell, over "
                f"{cells_in_noise} cells with R={NOISE_REPEATS}"
            ),
            "df": df,
            "relative_se_of_sigma_run": round(1.0 / (2.0 * df) ** 0.5, 4),
            "weights": (
                "equal per cell. Because the draw is stratified with a fixed "
                "allocation, the cell weights are NOT proportional to the "
                "population stratum shares: FLAT supplies 2 of 10 cells (20%) while "
                "being 3 of 18 groups (16.7%). The pooled value is therefore a "
                "design-based summary of the sampled cells, not a population-"
                "weighted variance."
            ),
            "target_population_stratum_weights": {
                "RESPONSIVE": round(7 / 18, 4),
                "WEAK": round(8 / 18, 4),
                "FLAT": round(3 / 18, 4),
                "basis": "the 18 paired groups",
            },
            "stratified_reporting_required": True,
            "stratified_outputs": {
                "per_stratum_sigma_run": "reported",
                "max_over_min_stratum_ratio": "reported",
                "status": (
                    "DIAGNOSTIC_ONLY. The pooled rule stands regardless of the "
                    "ratio. Switching to per-stratum thresholds after seeing this "
                    "diagnostic would be an S9 violation, so any such switch would "
                    "require a fresh protocol amendment before the run."
                ),
            },
            "sigma_delta": "sqrt(2) * sigma_run under independent equal variance",
            "tied": "2 * sqrt(2) * sigma_run",
            "interaction": (
                "no tied classification: it would need the within-group "
                "correlation of the two condition deltas, which is unmeasured"
            ),
            "no_post_run_change": (
                "This block is frozen at G0. The estimator, the df and the "
                "diagnostic obligations may not be revised once the noise runs "
                "exist."
            ),
        },
        "v4_clause_changes": [
            (
                "§6.4: replace 'independent of the Headroom screening' with "
                "'independent of the Headroom decision procedure, conditioned on "
                "its outcome, and drawn by the G0-frozen deterministic rule below'."
            ),
            (
                "§6.4: state that sigma_run estimates the paired population and "
                "that groups failing Headroom at either condition are not sampled."
            ),
            (
                "§6.4: require stratum-specific sigma_run to be reported alongside "
                "the pooled value, because the draw is stratified and not a simple "
                "random sample of the 20 groups."
            ),
            (
                "§6.4: keep the 30-run budget and the A0-only design unchanged; only "
                "the sampling frame and the reporting obligations change."
            ),
        ],
    }


def nesting_report(options: dict) -> dict:
    """RC10-4: the cell-set relation between F, E and A'.

    The previous revision wrote ``F ⊃ E ⊃ A'``. The part that is true is that every
    A' and E operating point is one of F's 40 cells. The part that is false is that
    E and A' are nested in each other: they pick *different* operating points for
    at least g03 and g16, so neither cell set contains the other.
    """

    a_points = {row["group_id"]: row for row in options["A_PRIME_operating_points"]}
    e_points = {row["group_id"]: row for row in options["E_operating_points"]}

    shared = sorted(set(a_points) & set(e_points))
    a_only = sorted(set(a_points) - set(e_points))
    e_only = sorted(set(e_points) - set(a_points))
    moved = [
        {
            "group_id": group_id,
            "A_PRIME": {
                "condition": ("C1" if a_points[group_id]["chosen_load_level"] == "L_LOW" else "C2"),
                "pressure_blocks": a_points[group_id]["chosen_pressure_blocks"],
                "rho0": a_points[group_id]["rho0_at_operating_point"],
            },
            "E": {
                "condition": ("C1" if e_points[group_id]["chosen_load_level"] == "L_LOW" else "C2"),
                "pressure_blocks": e_points[group_id]["chosen_pressure_blocks"],
                "rho0": e_points[group_id]["rho0_at_operating_point"],
            },
        }
        for group_id in shared
        if (
            a_points[group_id]["chosen_pressure_blocks"]
            != e_points[group_id]["chosen_pressure_blocks"]
        )
    ]

    return {
        "true_relations": {
            "F_contains_E": True,
            "F_contains_A_prime": True,
            "reason": (
                "Every E and A' operating point is one of the 40 cells F already "
                "contains, so F can host both as pre-registered subgroups."
            ),
        },
        "false_relation": {
            "E_contains_A_prime": False,
            "A_prime_contains_E": False,
            "reason": (
                "E and A' choose different operating points for some groups, so "
                "neither cell set contains the other."
            ),
        },
        "correct_statement": "F ⊃ E and F ⊃ A′; E and A′ are neither nested nor disjoint",
        "shared_groups": shared,
        "A_PRIME_only_groups": a_only,
        "E_only_groups": e_only,
        "groups_whose_operating_point_moves": moved,
        "why_they_move": (
            "A' picks the cheapest measured pressure inside a FROZEN band; E also "
            "accepts the 0.15-0.25 gap, which makes a different (cheaper) cell "
            "available for the same group. g03 moves to C1 (rho0 0.1821, in the "
            "gap) and g16 moves to C2 (rho0 0.4444), so the same group is studied "
            "at a different condition in the two designs."
        ),
        "consequence": (
            "A' and E cannot be described as a subset and superset of one another, "
            "and their estimates are not nested comparisons. Only F's relation to "
            "each of them is nested."
        ),
    }


def calibration_cost_report(options: dict) -> dict:
    """Run accounting per design, with calibration charged where it is due (RC8).

    The Headroom gate has only ever been evaluated at 256 and 1024 blocks. Any
    design that moves a cell to a different pressure therefore needs a new A0
    calibration run *before* the Headroom list can be frozen -- reusing the 40
    existing runs would freeze a gate that was never measured at the new
    operating point.
    """

    def runs(cells: int, calibration: int, noise: int) -> dict:
        main = ARMS_PER_CELL * cells * REPEATS
        return {
            "cells": cells,
            "calibration_runs": calibration,
            "noise_runs": noise,
            "main_campaign_runs": main,
            "total_new_runs": calibration + noise + main,
            "discriminable_decisions_available": cells,
            "fraction_needing_to_differ_for_g3cm": (
                round(DISCRIMINABLE_DECISION_THRESHOLD / cells, 3) if cells else None
            ),
            "g3cm_reachable": cells >= DISCRIMINABLE_DECISION_THRESHOLD,
        }

    a_two_level = len(options["A_two_level_groups_including_interpolated"])
    a_measured_only = len(options["A_two_level_groups"])
    model_only_two_level = len(options["A_two_level_groups_model_only"])
    a_prime_n = len(options["A_PRIME_groups"])
    e_n = len(options["E_groups"])
    f_cells = options["F"]["cells_in_design"]
    f_noise = options["F"]["noise_design"]["runs"]

    return {
        "arms_per_cell": ARMS_PER_CELL,
        "repeats": REPEATS,
        "calibration_note": (
            "The 40 executed A0 runs cover exactly two pressures per group, 256 "
            "and 1024. Option A executes cells at the iteration-2 proposed "
            "pressures, which are new, so Headroom has never been measured there."
        ),
        "designs": {
            "v3_as_written": runs(40, 0, 30),
            "option_A_measured_two_level_only": runs(a_measured_only, 2 * a_measured_only, 30),
            "option_A_incl_interpolated_two_level": runs(a_two_level, 2 * a_two_level, 30),
            "option_A_model_only_two_level": runs(
                model_only_two_level, 2 * model_only_two_level, 30
            ),
            "option_A_prime": runs(a_prime_n, 0, 27),
            "option_E": runs(e_n, 0, 27),
            "option_E_with_g4a": runs(len(options["E_responsive"]), 0, 27),
            "option_F_two_level_fixed_pressure": runs(f_cells, 0, f_noise),
            "option_B": runs(40, 40, 30),
        },
        "option_F_note": (
            "F uses the two pressures that were already executed, so it needs no "
            "new calibration and its noise design is the v3 design unchanged "
            "(5 groups x 2 conditions x R=3). Its 270 new runs equal v3's."
        ),
        "why_A_needs_calibration": (
            f"Option A was previously costed as if {a_two_level} groups x 2 levels "
            "could reuse the existing evidence. It cannot: the proposed pressures "
            "differ from 256/1024, so a fresh A0-only calibration of "
            f"{2 * a_two_level} runs is required before the Headroom list can be "
            "frozen, and any group that then fails Headroom drops out of the "
            "design. Because only {a_measured_only} group supports a measured "
            "two-level contrast, Option A cannot reach the 8-decision G3-CM "
            "threshold on measured evidence at all."
        ),
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


def pack_provenance(pack: Path, verified: dict[str, str]) -> dict:
    """Where the evidence came from, with file names attached to each hash."""

    files = [p for p in pack.rglob("*") if p.is_file()]
    designated = [
        {
            "file": relative,
            "name": Path(relative).name,
            "sha256": verified[relative],
            "m1_designated": relative in M1_DESIGNATED_INPUTS,
        }
        for relative in sorted(verified)
    ]
    return {
        "pack_path": str(pack).replace("\\", "/"),
        "tracked_by_git": False,
        "why_not_tracked": (
            "local/ is gitignored by repository policy; the pack is a 209 MiB "
            "M1-provided read-only bundle with its own sha256-manifest.txt"
        ),
        "file_count": len(files),
        "inputs": designated,
        "m1_designated_inputs": list(M1_DESIGNATED_INPUTS),
        "note": (
            "sha256-manifest-iteration2-proposal.txt (35cd5eea...) is retained "
            "among the verified inputs; the previous revision had replaced it with "
            "the observation CSV, which is now carried as an additional fifth "
            "input rather than a substitute."
        ),
    }


G_E_QUALIFIED = "QUALIFIED_SAME_BATCH_SHARED_PREDECESSOR"
G_E_PENDING = "PENDING_EARLIER_FORWARD_ORDER_PROOF"


def _row_integrity_failures(row: dict) -> list[str]:
    """Check physical-prefix integrity and the qualification's causal relation."""

    failures: list[str] = []
    if row.get("physical_prefix_complete") is not True:
        failures.append("PHYSICAL_PREFIX_INCOMPLETE")
    if row.get("physical_prefix_equal") is not True:
        failures.append("PHYSICAL_PREFIX_MISMATCH")

    producer_ids = row.get("producer_prefix_block_ids")
    consumer_ids = row.get("consumer_prefix_block_ids")
    if not isinstance(producer_ids, list) or not isinstance(consumer_ids, list):
        failures.append("PREFIX_BLOCK_IDS_MISSING_OR_INVALID")
    else:
        if producer_ids != consumer_ids:
            failures.append("PREFIX_BLOCK_ID_MISMATCH")
        try:
            if len(set(producer_ids)) != len(producer_ids):
                failures.append("PREFIX_BLOCK_IDS_NOT_UNIQUE")
        except TypeError:
            failures.append("PREFIX_BLOCK_IDS_NOT_HASHABLE")

    required_blocks = row.get("required_shared_blocks")
    hash_blocks = row.get("hash_lcp_blocks")
    if type(required_blocks) is not int or required_blocks < 0:
        failures.append("REQUIRED_SHARED_BLOCKS_MISSING_OR_INVALID")
    if type(hash_blocks) is not int or hash_blocks < 0:
        failures.append("HASH_LCP_BLOCKS_MISSING_OR_INVALID")
    if type(required_blocks) is int and type(hash_blocks) is int:
        if required_blocks != hash_blocks:
            failures.append("REQUIRED_SHARED_BLOCKS_NE_HASH_LCP_BLOCKS")
    if type(required_blocks) is int and isinstance(producer_ids, list):
        if len(producer_ids) != required_blocks:
            failures.append("PRODUCER_PREFIX_BLOCK_COUNT_MISMATCH")
    if type(required_blocks) is int and isinstance(consumer_ids, list):
        if len(consumer_ids) != required_blocks:
            failures.append("CONSUMER_PREFIX_BLOCK_COUNT_MISMATCH")

    if row.get("hash_function_match") is not True:
        failures.append("HASH_FUNCTION_MISMATCH")
    if row.get("hash_process_match") is not True:
        failures.append("HASH_PROCESS_MISMATCH")
    lcp_tokens = row.get("hash_lcp_tokens")
    if type(lcp_tokens) is not int or lcp_tokens < 0:
        failures.append("HASH_LCP_TOKENS_MISSING_OR_INVALID")
    if type(row.get("native_c")) is not int:
        failures.append("NATIVE_C_MISSING_OR_INVALID")

    qualification = row.get("qualification")
    expected_relations = {
        G_E_QUALIFIED: (
            "SAME_FORWARD_BATCH_SOURCE_BOUND",
            "SAME_SCHEDULER_ITERATION",
        ),
        G_E_PENDING: (
            "EARLIER_FORWARD_ORDER_NEEDS_SEPARATE_PROOF",
            "EARLIER_SCHEDULER_ITERATION",
        ),
    }
    if qualification in expected_relations:
        expected_forward, expected_scheduler = expected_relations[qualification]
        if row.get("forward_relation") != expected_forward:
            failures.append("FORWARD_RELATION_INCONSISTENT_WITH_QUALIFICATION")
        if row.get("scheduler_relation") != expected_scheduler:
            failures.append("SCHEDULER_RELATION_INCONSISTENT_WITH_QUALIFICATION")

    return failures


def validate_qualification_audit(rows: object) -> list[dict]:
    """Require the complete, unique 20-group x 2-condition G-E audit cohort."""

    if not isinstance(rows, list):
        raise InputSchemaError("G-E round-2 qualification audit must be a JSON array")
    if len(rows) != EXPECTED_CELL_COUNT:
        raise InputSchemaError(
            f"G-E round-2 audit must contain {EXPECTED_CELL_COUNT} rows; got {len(rows)}"
        )

    expected_pairs = {
        (f"g{group:02d}", load)
        for group in range(1, EXPECTED_GROUP_COUNT + 1)
        for load in ("L_LOW", "L_HIGH")
    }
    required_keys = (
        "group_id",
        "load_level",
        "run_id",
        "qualification",
        "independent_e",
        "native_c",
        "hash_lcp_tokens",
        "hash_lcp_blocks",
        "required_shared_blocks",
        "physical_prefix_complete",
        "physical_prefix_equal",
        "producer_prefix_block_ids",
        "consumer_prefix_block_ids",
        "hash_function_match",
        "hash_process_match",
        "forward_relation",
        "scheduler_relation",
    )
    seen_pairs: set[tuple[str, str]] = set()
    seen_run_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InputSchemaError(f"G-E round-2 row {index} must be an object")
        missing = [key for key in required_keys if key not in row]
        if missing:
            raise InputSchemaError(f"G-E round-2 row {index} missing keys: {missing}")
        group_id = row["group_id"]
        load_level = row["load_level"]
        pair = (group_id, load_level)
        if pair not in expected_pairs:
            raise InputSchemaError(f"G-E round-2 row {index} has unexpected cell: {pair!r}")
        if pair in seen_pairs:
            raise InputSchemaError(f"G-E round-2 audit contains duplicate cell: {pair!r}")
        seen_pairs.add(pair)
        run_id = row["run_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            raise InputSchemaError(f"G-E round-2 row {index} has invalid run_id")
        if run_id in seen_run_ids:
            raise InputSchemaError(f"G-E round-2 audit contains duplicate run_id: {run_id}")
        seen_run_ids.add(run_id)

    missing_pairs = sorted(expected_pairs - seen_pairs)
    if missing_pairs:
        raise InputSchemaError(f"G-E round-2 audit is missing cells: {missing_pairs}")
    return rows

def summarize_qualification(rows: list[dict], evidence_failures: list) -> dict:
    """Summarize G-E eligibility without conflating three different quantities.

    RC10-1 correction. The previous revision used ``hash_lcp_tokens == native_c``
    as proof that ``E == C``, hardcoded ``evidence_failure_count = 0``, and
    asserted a zero contribution to the primary metric across all 40 pairs.

    * ``hash_lcp_tokens`` and ``native_c`` are **content-hash and native-prefix
      measurements**. They say how much prefix the producer and consumer share;
      they do not establish that a *computed, independently qualified* ``E``
      exists for that pair.
    * ``E`` is only defined where the audit actually qualified the pair. On a
      ``PENDING_EARLIER_FORWARD_ORDER_PROOF`` row ``independent_e`` is null, so
      ``E`` is **not established** and nothing may be asserted about ``E == C``
      there -- neither equality nor a conservative zero.

    So the three quantities are reported separately, ``E`` is summarized only over
    qualified rows, pending rows keep their pending status, and the primary
    metric's contribution is stated per qualification state rather than globally.
    """

    integrity_failures: dict[str, list[str]] = {}
    for row in rows:
        found = _row_integrity_failures(row)
        if found:
            integrity_failures[str(row.get("run_id", "?"))] = found
    row_failure_count = len(integrity_failures)
    recorded_failure_count = len(evidence_failures)

    qualified = [r for r in rows if r.get("qualification") == G_E_QUALIFIED]
    pending = [r for r in rows if r.get("qualification") == G_E_PENDING]
    other = [r for r in rows if r.get("qualification") not in {G_E_QUALIFIED, G_E_PENDING}]

    qualified_with_e = [r for r in qualified if isinstance(r.get("independent_e"), int)]
    qualified_without_e = [r for r in qualified if not isinstance(r.get("independent_e"), int)]
    pending_with_e = [r for r in pending if isinstance(r.get("independent_e"), int)]
    # E - C needs both numbers; a row with E but no native C cannot be evaluated.
    evaluable = [r for r in qualified_with_e if isinstance(r.get("native_c"), int)]
    unevaluable = [r for r in qualified_with_e if not isinstance(r.get("native_c"), int)]

    e_values = sorted({r["independent_e"] for r in qualified_with_e})
    native_c_values = sorted({r["native_c"] for r in rows if isinstance(r.get("native_c"), int)})
    hash_lcp_values = sorted(
        {r["hash_lcp_tokens"] for r in rows if isinstance(r.get("hash_lcp_tokens"), int)}
    )

    contradictions: list[str] = []
    if qualified_without_e:
        contradictions.append(
            f"{len(qualified_without_e)} row(s) are qualified but carry no "
            "independently_qualified_e, so their E cannot be asserted"
        )
    if pending_with_e:
        contradictions.append(
            f"{len(pending_with_e)} row(s) are pending yet carry an "
            "independently_qualified_e, which is inconsistent with the frozen "
            "pending semantics"
        )
    if other:
        contradictions.append(
            f"{len(other)} row(s) carry a qualification value that is neither qualified nor pending"
        )
    e_neq_c_on_qualified = [
        str(r.get("run_id", "?")) for r in evaluable if r["independent_e"] != r["native_c"]
    ]
    if unevaluable:
        contradictions.append(
            f"{len(unevaluable)} qualified row(s) carry an E but no usable native "
            "C, so E - C cannot be evaluated for them"
        )
    if e_neq_c_on_qualified:
        contradictions.append(
            f"{len(e_neq_c_on_qualified)} qualified row(s) have independent_e != "
            "native_c, so the audited contribution is NOT zero"
        )
    if recorded_failure_count:
        contradictions.append(f"the audit records {recorded_failure_count} evidence failure(s)")
    if row_failure_count:
        contradictions.append(f"{row_failure_count} row(s) fail per-row integrity checks")

    contribution = {
        "basis": (
            "Sigma(E-C) can be judged only where the audit qualified the pair and "
            "produced an independent E. Pending pairs are UNDETERMINED."
        ),
        "qualified_rows": len(qualified_with_e),
        "qualified_rows_evaluable": len(evaluable),
        "qualified_rows_e_equals_c": len(evaluable) - len(e_neq_c_on_qualified),
        "qualified_rows_e_not_equal_c": e_neq_c_on_qualified,
        "qualified_contribution_tokens": int(
            sum(r["independent_e"] - r["native_c"] for r in evaluable)
        ),
        "pending_rows": len(pending),
        "pending_contribution": "UNDETERMINED_PENDING_QUALIFICATION",
        "unqualified_rows": len(other),
        "overall": (
            "CONTRADICTORY_EVIDENCE"
            if contradictions
            else ("PARTIAL_DETERMINATE" if pending or other else "DETERMINATE")
        ),
        "not_established_note": (
            "A null independent_e means E was never established for that pair. It "
            "does not mean E == C, and it is not a conservative zero by "
            "construction; it is an unmeasured quantity."
        ),
    }

    return {
        "row_count": len(rows),
        "hash_lcp": {
            "row_count": sum(1 for r in rows if isinstance(r.get("hash_lcp_tokens"), int)),
            "token_values": hash_lcp_values,
            "block_values": sorted(
                {r["hash_lcp_blocks"] for r in rows if isinstance(r.get("hash_lcp_blocks"), int)}
            ),
            "meaning": "shared prefix measured by content hash; not an eligibility test",
        },
        "native_c": {
            "row_count": sum(1 for r in rows if isinstance(r.get("native_c"), int)),
            "token_values": native_c_values,
            "meaning": "native prefix computed by the engine; not E",
        },
        "independently_qualified_e": {
            "row_count": len(qualified_with_e),
            "token_values": e_values,
            "rows_without_e": [str(r.get("run_id", "?")) for r in qualified_without_e],
            "meaning": (
                "E as established by the qualification procedure; defined only on qualified rows"
            ),
        },
        "e_equals_c_on_qualified_rows": bool(evaluable) and not e_neq_c_on_qualified,
        "e_status_for_pending_rows": "NOT_ESTABLISHED",
        "physical_prefix_equal_is_not_e_qualification": (
            "Physical prefix block equality shows the two requests resolved the "
            "same blocks. It is necessary but not sufficient for eligibility, "
            "which additionally needs the forward-order proof. Treating the former "
            "as the latter is exactly the inference this report refuses to make."
        ),
        "qualification_counts": {
            G_E_QUALIFIED: len(qualified),
            G_E_PENDING: len(pending),
            "OTHER": len(other),
        },
        "pending_rows": [
            {
                "group_id": r.get("group_id"),
                "condition": ("C1" if r.get("load_level") == "L_LOW" else "C2"),
                "qualification": r.get("qualification"),
                "forward_relation": r.get("forward_relation"),
                "scheduler_relation": r.get("scheduler_relation"),
                "independent_e": r.get("independent_e"),
                "e_status": "NOT_ESTABLISHED",
            }
            for r in pending
        ],
        "evidence_failures": {
            "recorded_failure_records": recorded_failure_count,
            "rows_failing_integrity_checks": row_failure_count,
            "row_detail": integrity_failures,
            "total": recorded_failure_count + row_failure_count,
            "derivation": (
                "recorded_failure_records is the length of the audit's own "
                "evidence-failures list; rows_failing_integrity_checks is computed "
                "per row from the invariant columns. Neither is a constant."
            ),
        },
        "contradictions": contradictions,
        "primary_metric_contribution": contribution,
    }


def _read_required_json(path: Path, label: str) -> object:
    if not path.is_file():
        raise InputIntegrityError(f"required G-E evidence file missing: {label}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InputIntegrityError(f"required G-E evidence file is invalid JSON: {label}") from exc


def _extract_audit_rows(payload: object, label: str) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        rows = payload["rows"]
    else:
        raise InputSchemaError(f"{label} must be an array or an object containing a rows array")
    if any(not isinstance(row, dict) for row in rows):
        raise InputSchemaError(f"{label} contains a non-object row")
    return rows


def g_e_report(pack: Path) -> dict:
    """RC10-1: current G-E state, with every source input required and validated."""

    qual_dir = pack / "artifacts/phase3-same-batch-physical-qualification-audit-v1"
    rej_dir = pack / "artifacts/phase3-concurrent-eligibility-rejection-audit-v1"
    failure_path = pack / "artifacts/phase3-load-calibration-analysis-v7/evidence-failures.json"

    audit_payload = _read_required_json(
        qual_dir / "qualification-audit.json",
        "phase3-same-batch-physical-qualification-audit-v1/qualification-audit.json",
    )
    audit_rows = validate_qualification_audit(
        _extract_audit_rows(audit_payload, "G-E round-2 qualification audit")
    )

    failure_payload = _read_required_json(
        failure_path, "phase3-load-calibration-analysis-v7/evidence-failures.json"
    )
    if isinstance(failure_payload, list):
        recorded = failure_payload
    elif isinstance(failure_payload, dict) and isinstance(failure_payload.get("rows"), list):
        recorded = failure_payload["rows"]
    else:
        raise InputSchemaError(
            "G-E evidence-failures.json must be an array or an object containing a rows array"
        )
    if any(not isinstance(row, dict) for row in recorded):
        raise InputSchemaError("G-E evidence-failures.json contains a non-object failure record")

    round1_payload = _read_required_json(
        rej_dir / "qualification-rejection-audit.json",
        "phase3-concurrent-eligibility-rejection-audit-v1/qualification-rejection-audit.json",
    )
    rows1 = _extract_audit_rows(round1_payload, "G-E round-1 historical rejection audit")
    if len(rows1) != EXPECTED_CELL_COUNT:
        raise InputSchemaError(
            f"G-E round-1 historical audit must contain {EXPECTED_CELL_COUNT} rows; got {len(rows1)}"
        )

    outcomes = Counter(str(r.get("qualification_result")) for r in rows1)
    qualified_e = sorted({str(r.get("independently_qualified_e")) for r in rows1})
    round2 = {
        "status": "CURRENT",
        "source": (
            "phase3-same-batch-physical-qualification-audit-v1, M6 recompute "
            "at git 712b3fc628c5bbebe95a782119654834c741149"
        ),
        "question": (
            "Do producer and consumer resolve the same physical prefix blocks "
            "under a bound forward-batch source, and is the pair therefore eligible?"
        ),
        "input_validation": {
            "round2_row_count": len(audit_rows),
            "round2_unique_cell_pairs": len({(r["group_id"], r["load_level"]) for r in audit_rows}),
            "round1_row_count": len(rows1),
            "evidence_failure_records": len(recorded),
            "required_source_files": list(G_E_REQUIRED_MANIFEST_PATHS),
        },
        **summarize_qualification(audit_rows, recorded),
    }
    round1 = {
        "status": "SUPERSEDED_BY_ROUND_2_FOR_CURRENT_STATE",
        "source": "phase3-concurrent-eligibility-rejection-audit-v1",
        "question": (
            "Is the producer's prefill COMPLETE AND VISIBLE to a same-wave "
            "consumer before the lookup?"
        ),
        "audit_coverage": "one request pair per cell (40 pairs from 40 cells)",
        "audit_row_count": len(rows1),
        "qualified_count": sum(
            1 for value in (r.get("independently_qualified_e") for r in rows1) if value
        ),
        "rejected_count": sum(
            1
            for r in rows1
            if str(r.get("qualification_result", "")).startswith("REJECTED")
        ),
        "status_code": "FAIL_CLOSED",
        "uses_c_to_compute_e": any(bool(r.get("uses_c_to_compute_e")) for r in rows1),
        "independently_qualified_e_values": qualified_e,
        "qualification_result": (
            next(iter(outcomes)) if len(outcomes) == 1 else dict(outcomes)
        ),
    }

    return {
        "item": "G-E (concurrent eligibility qualification)",
        "current_state": round2,
        "history": round1,
        "semantic_difference": (
            "Round 1 asks about visibility and completion timing of the producer's "
            "prefill; round 2 asks about physical block identity and forward-batch "
            "source binding, and additionally requires the forward-order proof "
            "before a pair counts as eligible. Neither count corrects the other."
        ),
        "what_does_not_change": (
            "uses_c_to_compute_e is false in both rounds, so the arm-independence "
            "requirement on E is not violated. On pending rows E is not established, "
            "and neither equality nor a zero contribution may be asserted."
        ),
        "remaining_open_item": (
            f"{len(round2.get('pending_rows', []))} pair(s) remain {G_E_PENDING} "
            "and have no established E; the audit covers one pair per cell, so the "
            "remaining request pairs are unverified in either round."
        ),
        "adjudication": (
            "Independent of G4 and of the design choice. It must not block, and "
            "must not be blocked by, the Option A'/E/F decision."
        ),
    }

def evidence_inventory_report(pack: Path, manifest_verification: dict | None = None) -> dict:
    """Classify execution inputs, run reports, summaries, audits and derived files.

    The load-calibration analysis directory is intentionally treated as mixed:
    it contains per-run execution reports alongside offline aggregate/audit files.
    File-level classification makes unknown files visible instead of assigning
    the entire directory one misleading label.
    """

    frozen_inputs = {
        "phase3-load-calibration-inputs-v1": (
            "Frozen per-cell inputs, traces, configurations and freeze records; "
            "these are execution inputs, not execution outputs."
        ),
    }
    audits = {
        "phase3-same-batch-physical-qualification-audit-v1": "Round-2 eligibility audit",
        "phase3-concurrent-eligibility-rejection-audit-v1": "Round-1 eligibility audit",
        "phase3-scheduler-and-run-mapping-audit-v1": "Scheduler / run mapping audit",
        "phase3-vllm-same-batch-source-audit-v1": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v2": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v3": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v4": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v5": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v6": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v7": "vLLM source audit",
        "phase3-vllm-same-batch-source-audit-v8": "vLLM source audit",
        "phase3-vllm-scheduler-iteration-source-audit-v1": "vLLM scheduler source audit",
        "phase3-vllm-scheduler-iteration-source-audit-v2": "vLLM scheduler source audit",
    }
    derived = {
        "phase3-load-calibration-iteration2-planning-v1": (
            "Offline derivation from iteration-1 observations. PROPOSED_NOT_EXECUTED."
        ),
    }

    manifest_paths: set[str] = set()
    manifest_entries = 0
    manifest_path = pack / "sha256-manifest.txt"
    if manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            _, separator, relative = line.partition("  ")
            if separator:
                manifest_paths.add(relative.strip())
            manifest_entries += 1

    entries: list[dict] = []
    file_level: dict[str, dict[str, list[str]]] = {}
    unclassified_files: list[str] = []
    separation = {
        "frozen_execution_inputs": [],
        "per_run_execution_reports": [],
        "execution_summaries": [],
        "runtime_evidence_inventories": [],
        "offline_audits_over_gpu_evidence": [],
        "offline_derived_analysis": [],
        "mixed_directories": [],
        "unclassified_directories": [],
    }

    art_root = pack / "artifacts"
    names = sorted(d.name for d in art_root.iterdir() if d.is_dir()) if art_root.is_dir() else []
    for name in names:
        full = art_root / name
        file_paths: list[Path] = []
        size = 0
        for root, _, filenames in os.walk(full):
            for filename in filenames:
                path = Path(root) / filename
                file_paths.append(path)
                size += path.stat().st_size

        classified: dict[str, list[str]] = {}
        for path in sorted(file_paths):
            relative = path.relative_to(full).as_posix()
            if name in frozen_inputs:
                kind = "FROZEN_EXECUTION_INPUT"
            elif name == "phase3-load-calibration-analysis-v7":
                filename = path.name
                if (
                    relative.startswith("runs/")
                    and filename.startswith("phase3-load-calibration-g")
                    and filename.endswith("-a0.json")
                ):
                    kind = "PER_RUN_EXECUTION_REPORT"
                elif relative in {
                    "aggregate-report.json",
                    "evidence-bindings.json",
                    "evidence-failures.json",
                    "qualification-audit.json",
                }:
                    kind = "OFFLINE_AUDIT_OR_AGGREGATE"
                else:
                    kind = "UNCLASSIFIED"
            elif name == "phase3-load-calibration-runs-v2":
                kind = "EXECUTION_SUMMARY"
            elif name == "phase3-same-batch-runtime-evidence-inventory-v1":
                kind = "RUNTIME_EVIDENCE_INVENTORY"
            elif name in audits:
                kind = "OFFLINE_AUDIT_OVER_GPU_EVIDENCE"
            elif name in derived:
                kind = "OFFLINE_DERIVED_ANALYSIS"
            else:
                kind = "UNCLASSIFIED"

            relative_pack_path = f"artifacts/{name}/{relative}"
            classified.setdefault(kind, []).append(relative_pack_path)
            if kind == "UNCLASSIFIED":
                unclassified_files.append(relative_pack_path)

        file_counts = {kind: len(paths) for kind, paths in sorted(classified.items())}
        if name in frozen_inputs:
            directory_kind = "FROZEN_EXECUTION_INPUTS"
            separation["frozen_execution_inputs"].append(name)
        elif name == "phase3-load-calibration-analysis-v7":
            directory_kind = "MIXED_PER_RUN_REPORTS_AND_OFFLINE_ANALYSIS"
            separation["mixed_directories"].append(name)
            if classified.get("PER_RUN_EXECUTION_REPORT"):
                separation["per_run_execution_reports"].append(name)
            file_level[name] = {kind: sorted(paths) for kind, paths in sorted(classified.items())}
        elif name == "phase3-load-calibration-runs-v2":
            directory_kind = "EXECUTION_SUMMARY"
            separation["execution_summaries"].append(name)
        elif name == "phase3-same-batch-runtime-evidence-inventory-v1":
            directory_kind = "RUNTIME_EVIDENCE_INVENTORY"
            separation["runtime_evidence_inventories"].append(name)
        elif name in audits:
            directory_kind = "OFFLINE_AUDIT_OVER_GPU_EVIDENCE"
            separation["offline_audits_over_gpu_evidence"].append(name)
        elif name in derived:
            directory_kind = "OFFLINE_DERIVED_ANALYSIS"
            separation["offline_derived_analysis"].append(name)
        else:
            directory_kind = "UNCLASSIFIED"
            separation["unclassified_directories"].append(name)

        manifested = sum(
            1
            for paths in classified.values()
            for relative in paths
            if relative in manifest_paths
        )
        entries.append(
            {
                "directory": f"artifacts/{name}",
                "evidence_kind": directory_kind,
                "file_count": len(file_paths),
                "bytes": size,
                "manifested_file_count": manifested,
                "unmanifested_file_count": len(file_paths) - manifested,
                "file_class_counts": file_counts,
                "note": (
                    frozen_inputs[name]
                    if name in frozen_inputs
                    else audits[name]
                    if name in audits
                    else derived[name]
                    if name in derived
                    else (
                        "Contains per-run execution reports and offline aggregate/audit "
                        "outputs; see file_class_counts and file_level_evidence_separation."
                    )
                    if name == "phase3-load-calibration-analysis-v7"
                    else (
                        "Execution summary of the 40-run calibration batch."
                        if name == "phase3-load-calibration-runs-v2"
                        else (
                            "Inventory of runtime evidence captured during execution."
                            if name == "phase3-same-batch-runtime-evidence-inventory-v1"
                            else "not classified by this report"
                        )
                    )
                ),
            }
        )

    pack_files = 0
    pack_bytes = 0
    for root, _, filenames in os.walk(pack):
        for filename in filenames:
            path = Path(root) / filename
            pack_files += 1
            pack_bytes += path.stat().st_size

    separation = {key: sorted(value) for key, value in separation.items()}
    return {
        "pack_path": str(pack).replace("\\", "/"),
        "pack_file_count": pack_files,
        "pack_bytes": pack_bytes,
        "pack_untracked": True,
        "why_untracked": (
            "the pack is ~209 MiB and lives under local/, which repository policy "
            "gitignores; committing it is not possible in this repository"
        ),
        "manifest_verification": manifest_verification or {
            "status": "NOT_PERFORMED",
            "reason": "inventory-only call; run() performs full verification before analysis",
        },
        "delivery_status": {
            "raw_pack_transferred_to_m1": False,
            "manifest_committed": True,
            "manifest_entry_count": manifest_entries,
            "pack_files_not_listed_in_manifest": max(0, pack_files - manifest_entries),
            "what_is_committed": (
                "outputs/pack-sha256-manifest.txt and outputs/pack-metadata.json, "
                "plus the full derived analysis outputs"
            ),
            "what_is_not_committed": (
                "the executed-run material itself; a manifest proves integrity only "
                "for bytes that M1 already holds or obtains out of band"
            ),
            "open_action": (
                "M1 must transfer or locate the original pack directory and verify "
                "it against the committed manifest; until then the raw GPU evidence "
                "is referenced, not delivered"
            ),
        },
        "directories": entries,
        "evidence_separation": {
            **separation,
            "note": (
                "Frozen inputs, per-run execution reports, execution summaries and "
                "runtime inventories are distinct. The analysis-v7 directory is mixed "
                "and is classified file-by-file; offline audits and planning outputs "
                "are not GPU execution evidence."
            ),
        },
        "file_level_evidence_separation": file_level,
        "unclassified_file_count": len(unclassified_files),
        "unclassified_files": sorted(unclassified_files),
        "reproduction_claims_this_analysis_does_not_make": [
            "It does not reproduce a GPU experiment. No GPU command is issued.",
            (
                "Its CPU tests exercise the analysis code against synthetic "
                "fixtures and, when present, the local copy of the pack. They are "
                "unit and regression tests, not experimental replication."
            ),
            (
                "Re-running this script regenerates the derived outputs. It does "
                "not regenerate the 40 executed runs, which would need new GPU "
                "authorisation."
            ),
        ],
    }

def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(pack: Path, out: Path) -> dict:
    manifest_verification = verify_pack_manifest(pack)
    verified = verify_frozen_inputs(pack)
    observations, proposal = load_inputs(pack)
    obs_rows, prop_rows, method = validate_inputs(observations, proposal, verified)
    models = build_models(obs_rows)
    cells = build_cells(obs_rows, prop_rows, models)
    groups = build_groups(models, cells, prop_rows)

    headroom = headroom_report(cells)
    load_target = load_target_report(cells, groups)
    collisions = collision_report(groups)
    options = option_report(cells, groups)
    h3 = h3_report(cells, groups, options)
    calibration = calibration_cost_report(options)
    f_detail = f_report(cells, groups, options)
    noise = noise_selection_report(cells, groups, options)
    nesting = nesting_report(options)
    g_e = g_e_report(pack)
    inventory = evidence_inventory_report(pack, manifest_verification)
    provenance = pack_provenance(pack, verified)
    precision = precision_table(
        {
            "v3_20_groups": 20,
            "option_F_paired_groups": options["F"]["paired_groups_n"],
            "option_E_all": len(options["E_groups"]),
            "option_E_g4a_responsive": len(options["E_responsive"]),
            "option_A_prime": len(options["A_PRIME_groups"]),
            "option_A_measured_two_level": len(options["A_two_level_groups"]),
            "option_A_including_interpolated": len(
                options["A_two_level_groups_including_interpolated"]
            ),
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
            "condition_labels": {
                "L_LOW": "C1",
                "L_HIGH": "C2",
                "note": (
                    "L_LOW / L_HIGH are the frozen source labels and are retained "
                    "only as provenance. Formal Phase 3 reporting uses C1 / C2, "
                    "because 'low' and 'high' would assert a state separation the "
                    "measurements contradict for 14 of 20 groups."
                ),
            },
            "thresholds": {
                "block_size_tokens": BLOCK_SIZE_TOKENS,
                "minimum_blocks": MIN_PRESSURE_BLOCKS,
                "maximum_blocks": MAX_PRESSURE_BLOCKS,
                "quantum_blocks": PRESSURE_QUANTUM_BLOCKS,
                "flat_delta_rho": FLAT_DELTA_RHO,
                "weak_delta_rho": WEAK_DELTA_RHO,
                "headroom_ratio_min": HEADROOM_RATIO_MIN,
                "headroom_r0_min_tokens": HEADROOM_R0_MIN_TOKENS,
                "option_e_band": list(OPTION_E_BAND),
            },
            "rows": [asdict(cell) for cell in cells],
        },
    )
    _write_json(
        out / "group-summary.json",
        {"schema_version": f"{ANALYSIS_VERSION}.groups", "rows": [asdict(g) for g in groups]},
    )
    _write_json(out / "headroom-report.json", headroom)
    _write_json(out / "load-target-report.json", load_target)
    _write_json(out / "collision-report.json", collisions)
    _write_json(out / "option-report.json", options)
    _write_json(out / "h3-report.json", h3)
    _write_json(out / "calibration-cost-report.json", calibration)
    _write_json(out / "option-f-report.json", f_detail)
    _write_json(out / "noise-selection-report.json", noise)
    _write_json(out / "nesting-report.json", nesting)
    _write_json(out / "g-e-report.json", g_e)
    _write_json(out / "evidence-inventory.json", inventory)
    _write_json(out / "pack-provenance.json", provenance)
    _write_json(
        out / "precision-report.json",
        {
            "planning_group_sd_tokens": PLANNING_GROUP_SD_TOKENS,
            "caveat": (
                "Half-widths are a planning calculation from an assumed group SD, "
                "not an achieved precision. They say nothing about coverage and "
                "must not be quoted as a guarantee."
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
        "collisions": collisions,
        "options": options,
        "h3": h3,
        "calibration": calibration,
        "f": f_detail,
        "noise": noise,
        "nesting": nesting,
        "g_e": g_e,
        "inventory": inventory,
        "provenance": provenance,
        "precision": precision,
        "method": method,
        "verified": verified,
        "manifest_verification": manifest_verification,
    }


def _print_report(result: dict) -> None:
    cells: list[Cell] = result["cells"]
    groups: list[GroupSummary] = result["groups"]
    headroom = result["headroom"]
    load_target = result["load_target"]
    options = result["options"]
    h3 = result["h3"]
    calibration = result["calibration"]

    print("== frozen inputs (SHA-256 verified) ==")
    for relative, digest in result["verified"].items():
        marker = "*" if relative in M1_DESIGNATED_INPUTS else " "
        print(f" {marker}{digest[:16]}...  {Path(relative).name}")

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
            f"rho0={row['rho0']:.4f} R0={row['r0']}"
        )

    print()
    print("== LOAD-CALIBRATION TARGET (§5.2) ==")
    print(f"  measured inside target       : {load_target['measured_inside_target']}/40")
    print(f"  reachable at a measured point: {load_target['reachable_measured']}/40")
    print(f"  reachable inside [256,1024]  : {load_target['reachable_in_bracket']}/40")
    print(f"  reachable on the full grid   : {load_target['reachable_model_only']}/40")

    print()
    print("== cell classification (40) ==")
    for name, count in sorted(Counter(c.classification for c in cells).items()):
        print(f"  {count:2d}  {name}")

    print()
    print("== two-level feasibility by evidence tier (RC6) ==")
    for tier in ("MEASURED", "INTERPOLATED", "EXTRAPOLATED"):
        members = [g.group_id for g in groups if g.g4a_evidence_tier == tier]
        print(f"  {tier:12s} {len(members):2d}  {', '.join(members)}")
    none_members = [g.group_id for g in groups if g.g4a_evidence_tier == "NONE"]
    print(f"  {'NONE':12s} {len(none_members):2d}  {', '.join(none_members)}")

    print()
    print("== pressure response (20 groups) ==")
    for stratum in ("FLAT", "WEAK", "RESPONSIVE"):
        members = [g.group_id for g in groups if g.pressure_response == stratum]
        print(f"  {stratum:10s} {len(members):2d}  {', '.join(members)}")

    print()
    print("== group verdicts (20) ==")
    for name, count in sorted(Counter(g.verdict for g in groups).items()):
        print(f"  {count:2d}  {name}")

    print()
    print("== proposed-pressure collisions ==")
    print(
        f"  unrestricted                                      : "
        f"{len(result['collisions']['unrestricted'])} -> "
        f"{', '.join(result['collisions']['unrestricted'])}"
    )
    print(
        f"  both rows tagged TARGET_PREDICTED_BELOW_MINIMUM.. : "
        f"{len(result['collisions']['both_rows_tagged_below_minimum_pressure'])} -> "
        f"{', '.join(result['collisions']['both_rows_tagged_below_minimum_pressure'])}"
    )
    print(
        f"  only outside the tagged subset                    : "
        f"{', '.join(result['collisions']['only_outside_tagged_subset']) or 'none'}"
    )

    print()
    print("== H3 populations (RC10-2: H3-0 primary, H3-R separate, strata descriptive) ==")
    primary = h3["primary"]
    print(
        f"  H3-0  {primary['group_count']} groups / {primary['cells_total']} cells"
        f"  (C1 {primary['cells_C1']}, C2 {primary['cells_C2']})"
    )
    print(f"        FLAT included: {h3['flat_policy'][:60]}...")
    secondary = h3["secondary_hypothesis"]
    print(
        f"  H3-R  {secondary['group_count']} groups / {secondary['cells_total']} cells"
        f"  (C1 {secondary['cells_C1']}, C2 {secondary['cells_C2']})"
    )
    print(f"        groups: {', '.join(secondary['groups'])}")
    for stratum in ("WEAK", "FLAT"):
        block = h3["heterogeneity"][stratum]
        print(
            f"  {stratum:5s} {block['group_count']} groups / {block['cells_total']} cells"
            f"  (C1 {block['cells_C1']}, C2 {block['cells_C2']})"
        )

    f_detail = result["f"]
    f_options = options["F"]
    print()
    print("== OPTION F: two-level fixed-pressure evaluation ==")
    print("  conditions            : C1=256 blocks, C2=1024 blocks (both MEASURED)")
    levels = f_detail["population"]["levels"]
    print(
        f"  campaign (executed)   : {levels['campaign']['groups']} groups / "
        f"{levels['campaign']['cells']} cells"
    )
    print(
        f"  Headroom-analysed     : C1 {levels['C1_analysed']['cells']} cells, "
        f"C2 {levels['C2_analysed']['cells']} cells"
    )
    print(
        f"  paired primary        : {levels['paired_primary']['groups']} groups "
        f"(NOT a {levels['campaign']['groups']}-group pool estimate)"
    )
    for row in f_options["excluded_pairs"]:
        print(f"    pair lost: {row['group_id']} {row['condition']} - {row['why']}")
    print("  manipulation check (NOT a gate):")
    manip = f_detail["manipulation_check"]
    print(
        f"    cells in designed band        : "
        f"{manip['cells_in_designed_band']}/{manip['cells_total']}"
    )
    print(
        f"    groups with both in band      : "
        f"{len(manip['groups_with_both_conditions_in_band'])} -> "
        f"{', '.join(manip['groups_with_both_conditions_in_band']) or 'none'}"
    )
    print(
        f"    groups with one in band       : "
        f"{len(manip['groups_with_one_condition_in_band'])} -> "
        f"{', '.join(manip['groups_with_one_condition_in_band']) or 'none'}"
    )
    print(
        f"    groups with neither in band   : {len(manip['groups_with_neither_condition_in_band'])}"
    )
    print(
        f"    dRho >= 0.10 / 0.01-0.10 / <0.01 : "
        f"{len(manip['delta_rho_at_least_0_10'])} / "
        f"{len(manip['delta_rho_between_0_01_and_0_10'])} / "
        f"{len(manip['delta_rho_below_0_01'])}"
    )
    interaction = f_detail["interaction"]
    inter_a = interaction["interaction_A_all_pairs"]
    inter_b = interaction["interaction_B_responsive"]
    print(
        f"  interaction-A (all)   : n={inter_a['paired_groups']} pairs "
        f"meets>=8={inter_a['meets_minimum_analysed_cells']}  [primary]"
    )
    print(
        f"  interaction-B (resp)  : n={inter_b['paired_groups']} pairs "
        f"meets>=8={inter_b['meets_minimum_analysed_cells']}  [heterogeneity]  "
        f"{', '.join(inter_b['groups'])}"
    )
    print("  planned precision (group-averaged delta, SD=2000 assumption):")
    for row in f_detail["precision"]["group_averaged"]:
        print(
            f"    rho={row['within_group_rho']:.1f}  sd={row['sd_tokens']:7.1f}  "
            f"+/-{row['planned_ci_half_width_tokens']:7.1f} tokens  "
            f"({row['ratio_vs_single_level_n20']:.2f}x n=20)  "
            f"n_eff={row['equivalent_single_level_n']}"
        )

    print()
    print("== operating points (design A') ==")
    for row in options["A_PRIME_operating_points"]:
        flag = "gap" if row["in_option_e_only_gap"] else "   "
        print(
            f"  {row['group_id']:4s} {row['chosen_load_level']:6s} "
            f"@{row['chosen_pressure_blocks']:4d}  rho0={row['rho0_at_operating_point']:.4f} "
            f"R0={row['r0_at_operating_point']:6d} hr={row['headroom_eligible']} {flag}"
        )

    print()
    print("== run accounting (RC8) ==")
    print(
        f"  {'design':34s}{'cells':>6}{'calib':>7}{'noise':>7}{'main':>7}{'total':>7}{'8/cells':>9}"
    )
    for name, row in calibration["designs"].items():
        print(
            f"  {name:34s}{row['cells']:>6}{row['calibration_runs']:>7}"
            f"{row['noise_runs']:>7}{row['main_campaign_runs']:>7}"
            f"{row['total_new_runs']:>7}"
            f"{(row['fraction_needing_to_differ_for_g3cm'] or 0):>9.2f}"
        )

    print()
    print("== nesting (RC10-4) ==")
    nesting = result["nesting"]
    print(f"  {nesting['correct_statement']}")
    print(
        f"  E contains A'? {nesting['false_relation']['E_contains_A_prime']}"
        f"   A' contains E? {nesting['false_relation']['A_prime_contains_E']}"
    )
    print(
        f"  A'-only groups: {', '.join(nesting['A_PRIME_only_groups']) or 'none'}"
        f"   E-only groups: {', '.join(nesting['E_only_groups']) or 'none'}"
    )
    for row in nesting["groups_whose_operating_point_moves"]:
        print(
            f"    moves: {row['group_id']}  A'={row['A_PRIME']['condition']}"
            f"@{row['A_PRIME']['pressure_blocks']}  E={row['E']['condition']}"
            f"@{row['E']['pressure_blocks']}"
        )

    print()
    print("== noise selection (RC10-5) ==")
    noise = result["noise"]
    print(
        f"  decision independence    : {noise['independence']['decision_independence']['preserved']}"
    )
    print(
        f"  population independence  : {noise['independence']['population_independence']['preserved']}"
    )
    print(f"  rule                     : {noise['selection_rule']['deterministic_key']}")
    print(
        f"  selected ({noise['selection_rule']['design']}) : "
        f"{', '.join(noise['selection_rule']['selected_groups'])}"
    )
    print(f"  stratum allocation       : {noise['selection_rule']['stratum_allocation']}")
    print(
        f"  sigma_run df             : {noise['variance_estimation']['df']}"
        f" (rel. SE {noise['variance_estimation']['relative_se_of_sigma_run']})"
    )
    print(f"  v4 amendments required   : {len(noise['v4_clause_changes'])}")

    print()
    print("== G-E (RC10-1) ==")
    g_e = result["g_e"]
    cur = g_e["current_state"]
    hist = g_e["history"]
    print(
        f"  round 1 (history, {hist['status_code']}): "
        f"{hist['qualified_count']}/{hist['audit_row_count']} qualified"
    )
    counts = cur.get("qualification_counts", {})
    print(
        f"  round 2 (current)   : {counts.get(G_E_QUALIFIED, '?')} qualified, "
        f"{counts.get(G_E_PENDING, '?')} pending, {counts.get('OTHER', '?')} other"
    )
    for row in cur.get("pending_rows", []):
        print(
            f"    pending {row['group_id']} {row['condition']}: "
            f"{row['qualification']}  E={row['e_status']}"
        )
    lcp = cur.get("hash_lcp", {})
    native = cur.get("native_c", {})
    qual_e = cur.get("independently_qualified_e", {})
    print(f"  hash LCP tokens     : {lcp.get('token_values')} ({lcp.get('row_count')} rows)")
    print(f"  native C tokens     : {native.get('token_values')} ({native.get('row_count')} rows)")
    print(
        f"  qualified E tokens  : {qual_e.get('token_values')} "
        f"({qual_e.get('row_count')} rows with E)"
    )
    contrib = cur.get("primary_metric_contribution", {})
    print(
        f"  Sigma(E-C) qualified : {contrib.get('qualified_contribution_tokens')} "
        f"tokens over {contrib.get('qualified_rows')} rows; "
        f"pending={contrib.get('pending_contribution')}"
    )
    print(f"  contribution verdict : {contrib.get('overall')}")
    failures = cur.get("evidence_failures", {})
    print(
        f"  evidence failures    : recorded "
        f"{failures.get('recorded_failure_records')} + row checks "
        f"{failures.get('rows_failing_integrity_checks')} = "
        f"{failures.get('total')}"
    )
    for note in cur.get("contradictions", []):
        print(f"    CONTRADICTION: {note}")

    print()
    print("== evidence inventory (for M1 transfer) ==")
    inv = result["inventory"]
    status = inv["delivery_status"]
    print(
        f"  pack {inv['pack_file_count']} files / "
        f"{inv['pack_bytes'] / 1024 / 1024:.1f} MiB, untracked={inv['pack_untracked']}"
    )
    print(
        f"  manifest committed: {status['manifest_committed']} "
        f"({status['manifest_entry_count']} entries); "
        f"raw pack delivered to M1: {status['raw_pack_transferred_to_m1']}"
    )
    for kind, count in sorted(Counter(e["evidence_kind"] for e in inv["directories"]).items()):
        print(f"    {kind:36s} {count} directories")

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
