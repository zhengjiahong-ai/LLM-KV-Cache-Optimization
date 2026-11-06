"""CPU tests for the Phase 3 G4 reachability analysis.

No GPU, no network, no writes outside ``tmp_path``. The frozen evidence pack
lives under ``local/`` (gitignored), so the end-to-end test skips when it is not
present; every other test builds a synthetic, schema-conformant fixture.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "probes"
    / "phase3_g4_reachability"
    / "reachability_analysis.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("g4_reachability", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()

W0 = 100_000


def _observation(group_id: str, load_level: str, rho: float, *, w0: int = W0) -> dict:
    r0 = round(rho * w0)
    band = mod.L_LOW_BAND if load_level == "L_LOW" else mod.L_HIGH_BAND
    return {
        "group_id": group_id,
        "load_level": load_level,
        "original_required_blocks": mod.ITER1_PRESSURE[load_level],
        "R0_recomputed_tokens": r0,
        "W0_actual_prefill_tokens": w0,
        "rho0_iteration1": r0 / w0,
        "target_min": band[0],
        "target_max": band[1],
        "iteration1_headroom_eligible": (r0 / w0 >= mod.HEADROOM_RATIO_MIN)
        and (r0 >= mod.HEADROOM_R0_MIN_TOKENS),
    }


def _proposals(
    observations: list[dict],
    proposed: dict[tuple[str, str], int] | None = None,
    limitations: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    models = mod.build_models(observations)
    rows: list[dict] = []
    for row in observations:
        key = (row["group_id"], row["load_level"])
        blocks = (proposed or {}).get(key, mod.ITER1_PRESSURE[row["load_level"]])
        rho = models[row["group_id"]].rho(blocks)
        band = (row["target_min"], row["target_max"])
        rows.append(
            {
                "group_id": key[0],
                "load_level": key[1],
                "proposed_required_blocks": blocks,
                "predicted_rho0": rho,
                "predicted_target_status": (
                    "PASS" if band[0] <= rho <= band[1] else "PREDICTED_MISS"
                ),
                "target_min": band[0],
                "target_max": band[1],
                "limitation": (limitations or {}).get(key, ""),
            }
        )
    return rows


def _build(
    rhos: dict[str, tuple[float, float]],
    proposed: dict[tuple[str, str], int] | None = None,
    limitations: dict[tuple[str, str], str] | None = None,
) -> tuple[list[dict], list[dict], list, list]:
    observations: list[dict] = []
    for group_id, (rho_low, rho_high) in rhos.items():
        observations.append(_observation(group_id, "L_LOW", rho_low))
        observations.append(_observation(group_id, "L_HIGH", rho_high))
    proposal = _proposals(observations, proposed, limitations)
    models = mod.build_models(observations)
    cells = mod.build_cells(observations, proposal, models)
    groups = mod.build_groups(models, cells, proposal)
    return observations, proposal, cells, groups


def _twenty_group_observations() -> list[dict]:
    observations: list[dict] = []
    for index in range(1, 21):
        group_id = f"g{index:02d}"
        rho_low = 0.04 + 0.02 * index
        rho_high = rho_low + 0.01 * (index % 5)
        observations.append(_observation(group_id, "L_LOW", rho_low))
        observations.append(_observation(group_id, "L_HIGH", rho_high))
    return observations


def _documents(
    observations: list[dict],
    proposal: list[dict],
    *,
    cell_count: int = 40,
    method: dict | None = None,
    source_hash: str = "0" * 64,
) -> tuple[dict, dict]:
    return (
        {"cell_count": cell_count, "rows": observations},
        {
            "cell_count": cell_count,
            "rows": proposal,
            "method": method or {"minimum_blocks": 16, "maximum_blocks": 2032},
            "source_observations_sha256": source_hash,
        },
    )


# --------------------------------------------------------------------------- #
# schema / completeness / uniqueness
# --------------------------------------------------------------------------- #


def test_validate_accepts_a_conformant_forty_cell_document() -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    obs_doc, prop_doc = _documents(observations, proposal)

    obs_rows, prop_rows, method = mod.validate_inputs(obs_doc, prop_doc)

    assert len(obs_rows) == mod.EXPECTED_CELL_COUNT == 40
    assert len(prop_rows) == 40
    assert method["minimum_blocks"] == 16


@pytest.mark.parametrize("field", ["cell_count", "rows"])
def test_validate_rejects_wrong_cell_count(field: str) -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    obs_doc, prop_doc = _documents(observations, proposal)
    if field == "cell_count":
        obs_doc["cell_count"] = 39
    else:
        obs_doc["rows"] = observations[:-1]

    with pytest.raises(mod.InputSchemaError, match="40"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_rejects_duplicate_cells() -> None:
    observations = _twenty_group_observations()
    observations[1] = dict(observations[0])
    proposal = _proposals(_twenty_group_observations())
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError, match="not unique|groups"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_rejects_rho0_that_does_not_equal_r0_over_w0() -> None:
    observations = _twenty_group_observations()
    observations[0]["rho0_iteration1"] = 0.5
    proposal = _proposals(_twenty_group_observations())
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError, match="rho0 does not equal"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_rejects_headroom_flag_that_disagrees_with_the_frozen_gate() -> None:
    observations = _twenty_group_observations()
    observations[0]["iteration1_headroom_eligible"] = not observations[0][
        "iteration1_headroom_eligible"
    ]
    proposal = _proposals(_twenty_group_observations())
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError, match="headroom flag"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_rejects_fewer_than_twenty_groups() -> None:
    observations = [row for row in _twenty_group_observations() if row["group_id"] != "g20"]
    proposal = _proposals(observations)
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError):
        mod.validate_inputs(obs_doc, prop_doc)


@pytest.mark.parametrize("blocks", [8, 2048, 100])
def test_validate_rejects_proposed_pressure_outside_range_or_quantum(
    blocks: int,
) -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    proposal[0]["proposed_required_blocks"] = blocks
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError, match="legal range|quantum"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_rejects_band_that_differs_from_the_frozen_bands() -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    proposal[0]["target_max"] = 0.20
    obs_doc, prop_doc = _documents(observations, proposal)

    with pytest.raises(mod.InputSchemaError, match="target band"):
        mod.validate_inputs(obs_doc, prop_doc)


def test_validate_requires_the_proposal_to_bind_the_pinned_observation_hash() -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    obs_doc, prop_doc = _documents(observations, proposal, source_hash="a" * 64)
    pinned = "b" * 64
    verified = {f"{mod.PLANNING_DIR}/iteration1-cell-observations.json": pinned}

    with pytest.raises(mod.InputSchemaError, match="source_observations_sha256"):
        mod.validate_inputs(obs_doc, prop_doc, verified)


def test_validate_rejects_proposal_method_that_contradicts_frozen_constants() -> None:
    observations = _twenty_group_observations()
    proposal = _proposals(observations)
    obs_doc, prop_doc = _documents(
        observations, proposal, method={"minimum_blocks": 32, "maximum_blocks": 2032}
    )

    with pytest.raises(mod.InputSchemaError, match="minimum_blocks"):
        mod.validate_inputs(obs_doc, prop_doc)


# --------------------------------------------------------------------------- #
# SHA-256 integrity
# --------------------------------------------------------------------------- #


def _materialise_pack(root: Path, payloads: dict[str, str]) -> Path:
    pack = root / "pack"
    for relative, text in payloads.items():
        target = pack / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return pack


def test_verify_frozen_inputs_detects_a_missing_input(tmp_path: Path) -> None:
    pack = _materialise_pack(tmp_path, {"PACK-METADATA.json": "{}"})

    with pytest.raises(mod.InputIntegrityError, match="frozen input missing"):
        mod.verify_frozen_inputs(pack)


def test_verify_frozen_inputs_detects_tampering_against_the_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {relative: f"payload {relative}" for relative in mod.FROZEN_INPUTS}
    pack = _materialise_pack(tmp_path, payloads)
    monkeypatch.setattr(mod, "FROZEN_INPUTS", dict(mod.FROZEN_INPUTS))

    # A hash that cannot match the written payloads.
    with pytest.raises(mod.InputIntegrityError, match="hash mismatch"):
        mod.verify_frozen_inputs(pack)


def test_verify_frozen_inputs_detects_a_manifest_that_disagrees_with_the_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {relative: f"payload {relative}" for relative in mod.FROZEN_INPUTS}
    pack = _materialise_pack(tmp_path, payloads)
    pins = {
        relative: hashlib.sha256(payloads[relative].encode("utf-8")).hexdigest()
        for relative in mod.FROZEN_INPUTS
    }
    monkeypatch.setattr(mod, "FROZEN_INPUTS", pins)
    first = next(iter(pins))
    lines = [
        "{}  {}".format("0" * 64 if relative == first else digest, relative)
        for relative, digest in pins.items()
    ]
    (pack / "sha256-manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(mod.InputIntegrityError, match="manifest disagrees"):
        mod.verify_frozen_inputs(pack)


def test_verify_frozen_inputs_accepts_a_pack_that_matches_its_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {relative: f"payload {relative}" for relative in mod.FROZEN_INPUTS}
    pack = _materialise_pack(tmp_path, payloads)
    pins = {
        relative: hashlib.sha256(payloads[relative].encode("utf-8")).hexdigest()
        for relative in mod.FROZEN_INPUTS
    }
    monkeypatch.setattr(mod, "FROZEN_INPUTS", pins)
    (pack / "sha256-manifest.txt").write_text(
        "\n".join(f"{digest}  {relative}" for relative, digest in pins.items()) + "\n",
        encoding="utf-8",
    )

    assert mod.verify_frozen_inputs(pack) == pins


# --------------------------------------------------------------------------- #
# model + evidence class
# --------------------------------------------------------------------------- #


def test_two_point_model_reproduces_the_frozen_proposal_value() -> None:
    """g01 L_LOW: the frozen proposal publishes predicted_rho0 = 0.55127..."""

    model = mod.GroupModel(group_id="g01", r_lo=77168, w_lo=139518, r_hi=78992, w_hi=141342)

    assert model.rho(16) == pytest.approx(0.5512709790713073, abs=1e-12)
    assert model.rho(256) == pytest.approx(77168 / 139518, abs=1e-12)


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (16, "EXTRAPOLATED"),
        (256, "MEASURED"),
        (640, "INTERPOLATED"),
        (1024, "MEASURED"),
        (2032, "EXTRAPOLATED"),
    ],
)
def test_evidence_class_marks_extrapolation_beyond_the_measured_range(
    blocks: int, expected: str
) -> None:
    assert mod.evidence_class(blocks) == expected


def test_empirical_marginal_response_ratio_is_the_slope_over_block_size() -> None:
    """A group whose recompute grows exactly one block per block has ratio 1.0."""

    observations = [
        {
            "group_id": "g1",
            "load_level": "L_LOW",
            "original_required_blocks": 256,
            "R0_recomputed_tokens": 30_000,
            "W0_actual_prefill_tokens": 100_000,
            "rho0_iteration1": 0.3,
            "target_min": 0.25,
            "target_max": 0.45,
            "iteration1_headroom_eligible": True,
        },
        {
            "group_id": "g1",
            "load_level": "L_HIGH",
            "original_required_blocks": 1024,
            "R0_recomputed_tokens": 30_000 + 16 * 768,
            "W0_actual_prefill_tokens": 100_000,
            "rho0_iteration1": (30_000 + 16 * 768) / 100_000,
            "target_min": 0.25,
            "target_max": 0.45,
            "iteration1_headroom_eligible": True,
        },
    ]
    proposal = _proposals(observations)
    models = mod.build_models(observations)
    cells = mod.build_cells(observations, proposal, models)

    assert cells[0].slope_tokens_per_block == pytest.approx(16.0)
    assert cells[0].empirical_marginal_response_ratio == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #


def test_pressure_insensitive_group_is_infeasible_and_insensitive() -> None:
    _, _, cells, groups = _build({"g14": (0.6386, 0.6386)})

    assert {cell.classification for cell in cells} == {"INFEASIBLE_AND_PRESSURE_INSENSITIVE"}
    assert groups[0].pressure_response == "FLAT"
    assert groups[0].empirical_marginal_response_ratio == pytest.approx(0.0)


def test_band_reachable_between_the_measured_pressures_is_interpolated() -> None:
    _, _, cells, _ = _build({"g1": (0.20, 0.50)})
    high = next(cell for cell in cells if cell.load_level == "L_HIGH")

    assert high.classification == "REACHABLE_INTERPOLATED"
    assert high.reachable_in_bracket is True
    assert high.reachable_model_only is True


def test_band_reachable_only_beyond_the_measurements_is_extrapolated() -> None:
    # rho0 falls into the L_LOW band only above 1024 blocks, i.e. outside the
    # interval the two measured points bracket.
    _, _, cells, _ = _build({"g1": (0.30, 0.16)})
    low = next(cell for cell in cells if cell.load_level == "L_LOW")

    assert low.classification == "REACHABLE_EXTRAPOLATED"
    assert low.reachable_in_bracket is False
    assert low.reachable_model_only is True
    assert low.rho0_at_maximum_blocks < mod.L_LOW_BAND[0]


def test_measured_in_band_cell_is_not_reported_as_a_model_prediction() -> None:
    _, _, cells, _ = _build({"g1": (0.13, 0.30)})
    low = next(cell for cell in cells if cell.load_level == "L_LOW")

    assert low.classification == "REACHABLE_MEASURED"
    assert low.measured_evidence_class == "MEASURED"
    assert low.measured_inside_target is True


# --------------------------------------------------------------------------- #
# G4-a / G4-b
# --------------------------------------------------------------------------- #


def test_extrapolated_operating_point_does_not_establish_controllability() -> None:
    """An extrapolated operating point is not evidence, and G4-a is what decides."""

    proposed = {("gweak", "L_LOW"): 16, ("gweak", "L_HIGH"): 16}
    _, _, cells, groups = _build({"gweak": (0.151, 0.170)}, proposed=proposed)
    low = next(cell for cell in cells if cell.load_level == "L_LOW")

    assert low.proposed_status == "PASS"
    assert low.proposal_evidence_class == "EXTRAPOLATED"
    assert groups[0].g4a_in_bracket_two_level is False
    assert groups[0].g4b_l_low_ok is False
    assert not groups[0].verdict.startswith("TWO_LEVEL_CONTRAST_MEASURED")


def test_extrapolated_operating_point_is_admitted_only_with_in_bracket_feasibility() -> None:
    """RC6: the floor is just the commonest extrapolation, not a special case.

    This group has an L_LOW point at 256 blocks and an L_HIGH point at 1024, so
    its two-level separability is established inside the measured bracket. Its
    proposed L_LOW pressure is the 16-block floor, which is extrapolated, and the
    model still places it in band -- so the operating point is admissible, but
    only because the group already passes G4-a in-bracket.
    """

    proposed = {("gx", "L_LOW"): 16, ("gx", "L_HIGH"): 1024}
    _, _, cells, groups = _build({"gx": (0.14, 0.30)}, proposed=proposed)
    low = next(cell for cell in cells if cell.load_level == "L_LOW")

    assert low.proposal_evidence_class == "EXTRAPOLATED"
    assert groups[0].g4a_in_bracket_two_level is True
    assert groups[0].g4b_l_low_ok is True
    assert groups[0].verdict == "TWO_LEVEL_CONTRAST_INTERPOLATED_SUPPORTED"


def test_group_feasible_only_by_extrapolation_is_labelled_model_only() -> None:
    """g03's L_LOW is only reachable below 256 blocks, so its contrast is a model claim."""

    proposed = {("g03", "L_LOW"): 16, ("g03", "L_HIGH"): 1024}
    _, _, _, groups = _build({"g03": (0.1821, 0.3557)}, proposed=proposed)

    assert groups[0].g4a_model_only_two_level is True
    assert groups[0].g4a_in_bracket_two_level is False
    assert groups[0].g4a_evidence_tier == "EXTRAPOLATED"
    assert groups[0].g4b_l_low_ok is False
    assert groups[0].verdict == "TWO_LEVEL_CONTRAST_MODEL_ONLY"


def test_measured_two_level_is_distinguished_from_interpolated() -> None:
    _, _, _, groups = _build({"gm": (0.1070, 0.4444)})

    assert groups[0].g4a_measured_two_level is True
    assert groups[0].g4a_evidence_tier == "MEASURED"
    assert groups[0].verdict == "TWO_LEVEL_CONTRAST_MEASURED_SUPPORTED"


def test_distinct_proposed_pressures_collide_only_when_they_are_equal() -> None:
    proposed = {("g1", "L_LOW"): 1024, ("g1", "L_HIGH"): 1024}
    _, _, _, groups = _build({"g1": (0.1821, 0.3557)}, proposed=proposed)

    assert groups[0].proposed_pressure_collision is True
    assert groups[0].verdict == "BOTH_LOADS_COLLAPSE_TO_SAME_PRESSURE"


def test_two_band_feasibility_requires_a_pressure_gap_of_one_quantum() -> None:
    _, _, cells, groups = _build({"g03": (0.1821, 0.3557)})

    assert groups[0].g4a_model_only_two_level is True
    assert all(cell.delta_rho_measured == groups[0].delta_rho_measured for cell in cells)


def test_negative_floor_is_flagged_and_excluded_from_floor_share() -> None:
    """RC6: an impossible extrapolation may be kept as a diagnostic only."""

    # rho0 rises steeply, so the secant goes negative below 256 blocks.
    _, _, cells, groups = _build({"gneg": (0.0448, 0.2949)})
    group = groups[0]

    assert group.rho0_at_minimum_blocks < 0
    assert group.rho0_at_minimum_physically_valid is False
    assert group.floor_share_of_low_measurement is None
    assert all(cell.rho0_at_minimum_physically_valid is False for cell in cells)


def test_positive_floor_keeps_its_share() -> None:
    _, _, _, groups = _build({"gpos": (0.40, 0.45)})
    group = groups[0]

    assert group.rho0_at_minimum_physically_valid is True
    assert group.floor_share_of_low_measurement is not None
    assert 0.0 < group.floor_share_of_low_measurement <= 1.0


# --------------------------------------------------------------------------- #
# original Headroom gate vs the load target
# --------------------------------------------------------------------------- #


def test_headroom_gate_matches_the_protocol_definition_and_excludes_small_cells() -> None:
    observations = [
        _observation("g_big", "L_LOW", 0.30),
        _observation("g_big", "L_HIGH", 0.35),
        _observation("g_ratio", "L_LOW", 0.01),
        _observation("g_ratio", "L_HIGH", 0.35),
        _observation("g_tiny", "L_LOW", 0.30, w0=1_000),
        _observation("g_tiny", "L_HIGH", 0.35),
    ]
    proposal = _proposals(observations)
    models = mod.build_models(observations)
    cells = mod.build_cells(observations, proposal, models)

    report = mod.headroom_report(cells)
    excluded = {row["group_id"]: row for row in report["excluded"]}

    assert report["candidate_cells"] == 6
    assert report["no_headroom_cells"] == 2
    assert set(excluded) == {"g_ratio", "g_tiny"}
    assert excluded["g_ratio"]["failed_ratio"] is True
    assert excluded["g_ratio"]["failed_absolute"] is False
    assert excluded["g_tiny"]["failed_ratio"] is False
    assert excluded["g_tiny"]["failed_absolute"] is True


def test_headroom_is_reported_separately_from_the_load_target() -> None:
    """A cell can pass Headroom and still miss its load band, and vice versa."""

    observations = [
        _observation("g1", "L_LOW", 0.60),
        _observation("g1", "L_HIGH", 0.61),
        _observation("g2", "L_LOW", 0.00),
        _observation("g2", "L_HIGH", 0.30),
    ]
    proposal = _proposals(observations)
    models = mod.build_models(observations)
    cells = mod.build_cells(observations, proposal, models)

    headroom = mod.headroom_report(cells)
    target = mod.load_target_report(cells, mod.build_groups(models, cells, proposal))

    assert headroom["eligible_cells"] == 3
    assert target["measured_inside_target"] == 1
    assert headroom["gate"] != target["gate"]


# --------------------------------------------------------------------------- #
# collision counting: 9 vs 10
# --------------------------------------------------------------------------- #


def test_collision_count_depends_on_the_limitation_tag_not_on_a_convention() -> None:
    below = "TARGET_PREDICTED_BELOW_MINIMUM_PRESSURE;LOAD_ORDER_NOT_IDENTIFIABLE"
    flat = "FLAT_OR_NEAR_FLAT_EMPIRICAL_RESPONSE;LOAD_ORDER_NOT_IDENTIFIABLE"
    limitations = {
        ("ga", "L_LOW"): below,
        ("ga", "L_HIGH"): below,
        ("gb", "L_LOW"): below,
        ("gb", "L_HIGH"): below,
        ("gc", "L_LOW"): flat,
        ("gc", "L_HIGH"): flat,
    }
    proposed = {
        (group_id, load_level): 16
        for group_id in ("ga", "gb", "gc")
        for load_level in ("L_LOW", "L_HIGH")
    }
    _, _, _, groups = _build(
        {"ga": (0.55, 0.556), "gb": (0.40, 0.41), "gc": (0.62, 0.62)},
        proposed=proposed,
        limitations=limitations,
    )

    report = mod.collision_report(groups)

    assert report["unrestricted"] == ["ga", "gb", "gc"]
    assert report["both_rows_tagged_below_minimum_pressure"] == ["ga", "gb"]
    assert report["only_outside_tagged_subset"] == ["gc"]
    assert flat in report["tag_detail"]["gc"]


# --------------------------------------------------------------------------- #
# option arithmetic
# --------------------------------------------------------------------------- #


def test_option_counts_are_additive_and_report_the_gap_subset() -> None:
    rhos = {
        "g_in_frozen_band": (0.13, 0.30),
        "g_in_gap": (0.21, 0.48),
        "g_out": (0.60, 0.61),
    }
    _, _, cells, groups = _build(rhos)

    options = mod.option_report(cells, groups)

    assert options["A_PRIME_groups"] == ["g_in_frozen_band"]
    assert options["E_groups"] == ["g_in_frozen_band", "g_in_gap"]
    assert options["E_groups_added_by_gap"] == ["g_in_gap"]


def test_operating_points_pick_the_cheapest_qualifying_measured_pressure() -> None:
    """g16 qualifies at both loads; the tie-break must yield exactly one point."""

    _, _, cells, groups = _build({"g16": (0.1070, 0.4444)})
    options = mod.option_report(cells, groups)
    points = options["A_PRIME_operating_points"]

    assert len(points) == 1
    assert points[0]["group_id"] == "g16"
    assert points[0]["chosen_pressure_blocks"] == 256
    assert points[0]["alternative_candidates"]


def test_operating_points_are_measured_and_headroom_eligible() -> None:
    """RC8: the operating point must be a pressure Headroom was evaluated at."""

    _, _, cells, groups = _build(
        {
            "g1": (0.30, 0.40),
            "g_small": (
                0.06,
                0.40,
            ),
            "g_low": (0.12, 0.30),
        }
    )
    options = mod.option_report(cells, groups)

    for row in options["A_PRIME_operating_points"]:
        assert row["chosen_pressure_blocks"] in mod.ITER1_PRESSURE.values()
        assert row["headroom_eligible"] is True
        assert row["headroom_ratio_ok"] is True
        assert row["headroom_abs_ok"] is True


# --------------------------------------------------------------------------- #
# H3 populations (RC10-2)
# --------------------------------------------------------------------------- #


def _h3_fixture():
    """g_resp RESPONSIVE, g_weak WEAK, g_flat FLAT, g_nohr RESPONSIVE but C1 fails Headroom."""

    rhos = {
        "g_resp": (0.13, 0.44),
        "g_weak": (0.30, 0.35),
        "g_flat": (0.40, 0.40),
        "g_nohr": (0.0447, 0.30),
    }
    _, _, cells, groups = _build(rhos)
    options = mod.option_report(cells, groups)
    return cells, groups, options, mod.h3_report(cells, groups, options)


def test_h3_primary_keeps_the_whole_headroom_population_including_flat() -> None:
    """RC10-2: FLAT is not removed from the original hypothesis."""

    _, _, _, report = _h3_fixture()
    primary = report["primary"]

    assert primary["id"] == "H3-0"
    assert "g_flat" in primary["groups"]
    assert "g_weak" in primary["groups"]
    assert "g_resp" in primary["groups"]
    assert set(primary["groups"]) == {"g_flat", "g_nohr", "g_resp", "g_weak"}


def test_h3_flat_is_a_heterogeneity_stratum_not_an_exclusion() -> None:
    _, _, _, report = _h3_fixture()

    assert report["heterogeneity"]["FLAT"]["groups"] == ["g_flat"]
    assert report["heterogeneity"]["FLAT"]["cells_total"] == 2
    assert "not removed from the hypothesis" in report["flat_policy"]


def test_h3_responsive_is_a_separate_hypothesis_with_its_own_estimand() -> None:
    _, _, _, report = _h3_fixture()
    secondary = report["secondary_hypothesis"]

    assert secondary["id"] == "H3-R"
    assert secondary["status"] == "pre-registered, separate, not a replacement for H3-0"
    assert secondary["groups"] == ["g_nohr", "g_resp"]
    assert secondary["question"] != report["primary"]["question"]


def test_h3_reports_effective_group_counts_per_condition() -> None:
    _, _, _, report = _h3_fixture()
    primary = report["primary"]

    # g_nohr loses its C1 cell, so C1 has 3 groups' worth of cells and C2 has 4.
    assert primary["cells_C1"] == 3
    assert primary["cells_C2"] == 4
    assert primary["cells_total"] == 7
    assert primary["group_count"] == 4


def test_h3_weighting_is_by_group_not_by_cell() -> None:
    _, _, _, report = _h3_fixture()
    primary = report["primary"]

    assert primary["resampling_unit"] == "group"
    assert "1 / group_count" in primary["group_weight"]
    assert primary["group_weight"].endswith("NOT proportional to cell count")
    assert primary["cell_weight_within_group"].startswith("1 / (cells in that group)")
    assert primary["groups_with_two_cells"] == ["g_flat", "g_resp", "g_weak"]
    assert primary["groups_with_one_cell"] == ["g_nohr"]
    assert primary["one_cell_groups_missing_condition"] == {"g_nohr": "C1"}


def test_h3_secondary_does_not_depend_on_the_paired_set() -> None:
    """RC10-2: H3 is per cell, so a lost pair must not shrink the H3 population."""

    _, _, options, report = _h3_fixture()

    paired = set(options["F"]["paired_groups"])
    h3_groups = set(report["primary"]["groups"])

    assert "g_nohr" not in paired
    assert "g_nohr" in h3_groups
    assert len(h3_groups) == len(paired) + 1


def test_h3_by_design_reports_the_two_population_sizes() -> None:
    _, _, _, report = _h3_fixture()
    by_design = report["by_design"]["F"]

    assert by_design["H3_0_groups"] == 4
    assert by_design["H3_0_cells"] == 7
    assert by_design["H3_R_groups"] == 2
    assert by_design["H3_R_cells"] == 3


# --------------------------------------------------------------------------- #
# run accounting (RC8)
# --------------------------------------------------------------------------- #


def test_option_a_is_charged_a_fresh_calibration_and_a_prime_is_not() -> None:
    rhos = {"g1": (0.13, 0.44), "g2": (0.30, 0.40), "g3": (0.60, 0.61)}
    _, _, cells, groups = _build(rhos)
    report = mod.calibration_cost_report(mod.option_report(cells, groups))
    designs = report["designs"]

    for key in (
        "option_A_measured_two_level_only",
        "option_A_incl_interpolated_two_level",
        "option_A_model_only_two_level",
    ):
        row = designs[key]
        assert row["calibration_runs"] == 2 * row["cells"]

    assert designs["option_A_prime"]["calibration_runs"] == 0
    assert designs["option_E"]["calibration_runs"] == 0
    assert designs["option_B"]["calibration_runs"] == 40


def test_run_totals_add_up_across_the_three_run_sets() -> None:
    rhos = {"g1": (0.13, 0.44)}
    _, _, cells, groups = _build(rhos)
    report = mod.calibration_cost_report(mod.option_report(cells, groups))

    for row in report["designs"].values():
        assert row["total_new_runs"] == (
            row["calibration_runs"] + row["noise_runs"] + row["main_campaign_runs"]
        )
        assert row["main_campaign_runs"] == mod.ARMS_PER_CELL * row["cells"] * mod.REPEATS


# --------------------------------------------------------------------------- #
# input provenance (RC9)
# --------------------------------------------------------------------------- #


def test_the_m1_designated_four_are_all_pinned() -> None:
    assert len(mod.M1_DESIGNATED_INPUTS) == 4
    for relative in mod.M1_DESIGNATED_INPUTS:
        assert relative in mod.FROZEN_INPUTS


def test_the_proposal_manifest_hash_is_not_replaced() -> None:
    relative = f"{mod.PLANNING_DIR}/sha256-manifest-iteration2-proposal.txt"

    assert relative in mod.FROZEN_INPUTS
    assert mod.FROZEN_INPUTS[relative].startswith("35cd5eea")


def test_precision_table_labels_itself_as_a_planning_assumption() -> None:
    table = mod.precision_table({"n20": 20, "n15": 15, "n7": 7})

    assert table["n20"]["ratio_vs_n20"] == pytest.approx(1.0)
    assert (
        table["n15"]["planned_ci_half_width_tokens"] > table["n20"]["planned_ci_half_width_tokens"]
    )
    assert (
        table["n7"]["planned_ci_half_width_tokens"] > table["n15"]["planned_ci_half_width_tokens"]
    )


# --------------------------------------------------------------------------- #
# Option F: two-level fixed-pressure evaluation
# --------------------------------------------------------------------------- #

REAL_PACK = (
    Path(__file__).resolve().parents[1] / "local" / "phase3-g4-reachability-analysis-pack-v1"
)


def _f_fixture():
    """Five groups covering each F-relevant role.

    g_resp   RESONSIVE, both conditions inside their designed bands
    g_weak   WEAK, only the high condition inside its band
    g_flat   FLAT, only the high condition inside its band
    g_none   WEAK, neither condition inside its band (band attainment must NOT gate)
    g_nohr   RESPONSIVE, but its low condition fails Headroom (pair must be lost)
    """

    rhos = {
        "g_resp": (0.10, 0.35),
        "g_weak": (0.30, 0.35),
        "g_flat": (0.40, 0.40),
        "g_none": (0.20, 0.22),
        "g_nohr": (0.04, 0.30),
    }
    _, _, cells, groups = _build(rhos)
    options = mod.option_report(cells, groups)
    return cells, groups, options, mod.f_report(cells, groups, options)


def test_option_f_keeps_both_executed_pressures_and_all_groups() -> None:
    _, _, options, report = _f_fixture()
    f = options["F"]

    assert f["conditions"]["C1"]["pressure_blocks"] == 256
    assert f["conditions"]["C2"]["pressure_blocks"] == 1024
    assert f["conditions"]["C1"]["evidence_class"] == "MEASURED"
    assert f["groups_in_design"] == 5
    assert f["cells_in_design"] == 10
    assert report["design"]["band_attainment_is_a_gate"] is False
    assert report["design"]["band_attainment_role"] == "manipulation_check"


def test_option_f_needs_no_new_calibration() -> None:
    _, _, options, report = _f_fixture()

    assert options["F"]["new_calibration_required"] is False
    assert options["F"]["noise_design"]["runs"] == 30
    assert options["F"]["noise_design"]["unchanged_from_v3"] is True
    assert "iteration 1" in report["design"]["why_no_new_calibration"]


def test_option_f_does_not_relax_any_frozen_band() -> None:
    """F changes the condition definition, not the acceptance thresholds."""

    _f_fixture()

    assert mod.L_LOW_BAND == (0.05, 0.15)
    assert mod.L_HIGH_BAND == (0.25, 0.45)
    assert mod.HEADROOM_RATIO_MIN == 0.05
    assert mod.HEADROOM_R0_MIN_TOKENS == 512
    assert set(mod.OPTION_F_CONDITIONS.values()) == {"L_LOW", "L_HIGH"}


def test_band_attainment_does_not_exclude_a_group_from_option_f() -> None:
    _, _, options, report = _f_fixture()
    neither = report["manipulation_check"]["groups_with_neither_condition_in_band"]
    paired = options["F"]["paired_groups"]

    assert "g_none" in neither
    assert "g_none" in paired
    assert options["F"]["groups_in_design"] == 5


def test_option_f_loses_only_the_pair_whose_cell_fails_headroom() -> None:
    _, _, options, report = _f_fixture()

    assert options["F"]["paired_groups_n"] == 4
    assert "g_nohr" not in options["F"]["paired_groups"]
    excluded = {(row["group_id"], row["condition"]) for row in options["F"]["excluded_pairs"]}
    assert excluded == {("g_nohr", "C1")}
    assert report["population"]["per_condition_analysed_cells"] == {"C1": 4, "C2": 5}


def test_option_f_strata_are_reported_over_both_design_and_paired_sets() -> None:
    _, _, _, report = _f_fixture()

    assert report["population"]["strata_over_design"] == {
        "RESPONSIVE": 2,
        "WEAK": 2,
        "FLAT": 1,
    }
    assert report["population"]["strata_over_paired"] == {
        "RESPONSIVE": 1,
        "WEAK": 2,
        "FLAT": 1,
    }


def test_option_f_h3_uses_every_eligible_cell_including_one_cell_groups() -> None:
    cells, groups, options, _ = _f_fixture()
    h3 = mod.h3_report(cells, groups, options)

    assert h3["primary"]["id"] == "H3-0"
    assert h3["primary"]["group_count"] == 5  # g_nohr keeps one eligible cell
    assert h3["primary"]["cells_total"] == 9
    assert h3["primary"]["cells_C1"] == 4
    assert h3["primary"]["cells_C2"] == 5
    assert h3["secondary_hypothesis"]["groups"] == ["g_nohr", "g_resp"]
    assert h3["secondary_hypothesis"]["cells_total"] == 3


def test_option_f_interaction_reports_all_pairs_separately_from_responsive() -> None:
    _, _, _, report = _f_fixture()
    interaction = report["interaction"]

    inter_a = interaction["interaction_A_all_pairs"]
    inter_b = interaction["interaction_B_responsive"]

    assert inter_a["paired_groups"] == 4
    assert inter_a["is_primary_interaction_analysis"] is True
    assert inter_a["meets_minimum_analysed_cells"] is False
    assert inter_b["groups"] == ["g_resp"]
    assert inter_b["is_primary_interaction_analysis"] is False


def test_option_f_interaction_does_not_infer_zero_from_delta_rho() -> None:
    """RC10-3: dRho describes A0's baseline, not the arm-vs-A0 difference."""

    _, _, _, report = _f_fixture()
    interaction = report["interaction"]

    assert "NOT evidence" in interaction["not_inferable_from_delta_rho"]
    assert "zero" in interaction["not_inferable_from_delta_rho"]
    joined = " ".join(interaction["caveats"])
    assert "by construction" not in joined


def test_option_f_run_accounting_matches_v3() -> None:
    _, _, options, _ = _f_fixture()
    report = mod.calibration_cost_report(options)
    f_row = report["designs"]["option_F_two_level_fixed_pressure"]
    v3_row = report["designs"]["v3_as_written"]

    assert f_row["calibration_runs"] == 0
    assert f_row["noise_runs"] == 30
    assert f_row["main_campaign_runs"] == mod.ARMS_PER_CELL * 10
    assert f_row["total_new_runs"] == 30 + 6 * 10
    assert f_row["cells"] == 10
    assert v3_row["total_new_runs"] == 270


def test_option_f_group_average_precision_improves_with_positive_correlation() -> None:
    _, _, _, report = _f_fixture()
    rows = report["precision"]["group_averaged"]

    widths = [row["planned_ci_half_width_tokens"] for row in rows]
    assert widths == sorted(widths)
    # Perfectly correlated conditions cannot be better than one condition.
    assert rows[-1]["within_group_rho"] == 1.0
    assert rows[0]["equivalent_single_level_n"] > rows[-1]["equivalent_single_level_n"]


def test_option_f_interaction_precision_worsens_with_independence() -> None:
    _, _, _, report = _f_fixture()
    rows = report["precision"]["interaction"]

    widths = [row["planned_ci_half_width_tokens"] for row in rows]
    assert widths == sorted(widths, reverse=True)
    assert rows[0]["within_group_rho"] == 0.0


def test_option_f_declares_its_threats_explicitly() -> None:
    _, _, _, report = _f_fixture()
    text = " ".join(report["threats"])

    assert "dilut" in text.lower()
    assert "attribution" in text.lower()
    assert "post-hoc" in text.lower()
    assert "manipulation_check" == report["design"]["band_attainment_role"]


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_option_f_numbers(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)

    options = result["options"]
    report = result["f"]

    assert options["F"]["groups_in_design"] == 20
    assert options["F"]["cells_in_design"] == 40
    assert options["F"]["cells_headroom_eligible"] == 38
    assert options["F"]["paired_groups_n"] == 18
    assert options["F"]["per_condition_analysed_cells"] == {"C1": 18, "C2": 20}
    assert options["F"]["new_calibration_required"] is False
    assert options["F"]["noise_design"]["runs"] == 30

    excluded = {(row["group_id"], row["condition"]) for row in options["F"]["excluded_pairs"]}
    assert excluded == {("g09", "C1"), ("g18", "C1")}

    manip = report["manipulation_check"]
    assert manip["cells_in_designed_band"] == 8
    assert manip["groups_with_both_conditions_in_band"] == ["g16"]
    assert len(manip["delta_rho_at_least_0_10"]) == 9
    assert len(manip["delta_rho_between_0_01_and_0_10"]) == 8
    assert len(manip["delta_rho_below_0_01"]) == 3

    h3 = result["h3"]
    assert h3["primary"]["id"] == "H3-0"
    assert h3["primary"]["group_count"] == 20
    assert h3["primary"]["cells_total"] == 38
    assert h3["primary"]["cells_C1"] == 18
    assert h3["primary"]["cells_C2"] == 20
    assert h3["secondary_hypothesis"]["id"] == "H3-R"
    assert h3["secondary_hypothesis"]["group_count"] == 9
    assert h3["secondary_hypothesis"]["cells_total"] == 16
    assert h3["heterogeneity"]["FLAT"]["group_count"] == 3

    interaction = report["interaction"]
    inter_a = interaction["interaction_A_all_pairs"]
    inter_b = interaction["interaction_B_responsive"]
    assert inter_a["paired_groups"] == 18
    assert inter_a["meets_minimum_analysed_cells"] is True
    assert inter_b["paired_groups"] == 7
    assert inter_b["groups"] == ["g03", "g04", "g05", "g10", "g12", "g16", "g19"]
    assert inter_b["meets_minimum_analysed_cells"] is False

    levels = report["population"]["levels"]
    assert levels["campaign"] == {"groups": 20, "cells": 40, "note": levels["campaign"]["note"]}
    assert levels["C1_analysed"]["cells"] == 18
    assert levels["C2_analysed"]["cells"] == 20
    assert levels["paired_primary"]["groups"] == 18
    assert "NOT the 20-group pool" in report["population"]["scope_warning"]

    calibration = result["calibration"]["designs"]["option_F_two_level_fixed_pressure"]
    assert calibration["total_new_runs"] == 270


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_nesting_is_asymmetric(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)
    nesting = result["nesting"]

    assert nesting["true_relations"]["F_contains_E"] is True
    assert nesting["true_relations"]["F_contains_A_prime"] is True
    assert nesting["false_relation"]["E_contains_A_prime"] is False
    assert nesting["false_relation"]["A_prime_contains_E"] is False
    assert nesting["E_only_groups"] == ["g05", "g10", "g19"]
    moved = {row["group_id"] for row in nesting["groups_whose_operating_point_moves"]}
    assert moved == {"g03", "g16"}
    assert "E ⊃ A′" not in nesting["correct_statement"]


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_noise_selection_is_deterministic_and_flagged(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)
    noise = result["noise"]

    assert noise["independence"]["decision_independence"]["preserved"] is True
    assert noise["independence"]["population_independence"]["preserved"] is False
    assert noise["selection_rule"]["stratum_allocation"] == {
        "RESPONSIVE": 2,
        "WEAK": 2,
        "FLAT": 1,
    }
    assert len(noise["selection_rule"]["selected_groups"]) == 5
    assert noise["variance_estimation"]["df"] == 20
    assert len(noise["v4_clause_changes"]) == 4

    # The draw is a pure function of the frozen salt and the group ids.
    again = mod.run(REAL_PACK, tmp_path)
    assert (
        again["noise"]["selection_rule"]["selected_groups"]
        == noise["selection_rule"]["selected_groups"]
    )


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_g_e_uses_round_two_as_current_state(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)
    g_e = result["g_e"]

    current = g_e["current_state"]
    history = g_e["history"]

    assert current["status"] == "CURRENT"
    assert current["qualified"] == 36
    assert current["pending"] == 4
    assert {row["group_id"] for row in current["pending_rows"]} == {"g08", "g20"}
    assert current["physical_prefix_equal"] == 40
    assert current["evidence_failure_count"] == 0
    assert current["e_equals_c_everywhere"] is True

    assert history["status"] == "SUPERSEDED_BY_ROUND_2_FOR_CURRENT_STATE"
    assert history["status_code"] == "FAIL_CLOSED"
    assert history["qualified_count"] == 0
    assert history["rejected_count"] == 40
    assert (
        "different" in g_e["semantic_difference"]
        or "not a correction" in g_e["semantic_difference"]
    )

    written = json.loads((tmp_path / "option-f-report.json").read_text("utf-8"))
    assert written["design"]["name"] == "OPTION_F_TWO_LEVEL_FIXED_PRESSURE"


# --------------------------------------------------------------------------- #
# end to end against the real frozen pack (skipped when absent)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_end_to_end(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)

    cells = result["cells"]
    assert len(cells) == 40
    assert len({(cell.group_id, cell.load_level) for cell in cells}) == 40
    assert result["headroom"]["eligible_cells"] == 38
    assert result["headroom"]["no_headroom_cells"] == 2
    assert result["load_target"]["groups_two_level_needs_extrapolation"] == [
        "g03",
        "g05",
        "g10",
        "g19",
    ]
    assert result["load_target"]["groups_two_level_in_bracket"] == ["g09", "g16", "g18"]
    assert result["load_target"]["groups_two_level_measured"] == ["g16"]

    g14 = [cell for cell in cells if cell.group_id == "g14"]
    assert g14[0].r0 == g14[1].r0
    assert g14[0].w0 == g14[1].w0

    written = json.loads((tmp_path / "cell-classification.json").read_text("utf-8"))
    assert written["frozen_inputs_sha256"] == result["verified"]
    assert len(written["rows"]) == 40
