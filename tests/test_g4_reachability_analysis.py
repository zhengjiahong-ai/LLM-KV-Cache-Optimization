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


def _write_test_manifest(pack: Path, relative_paths: list[str]) -> None:
    lines = []
    for relative in relative_paths:
        digest = hashlib.sha256((pack / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    (pack / "sha256-manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_pack_manifest_verifies_all_entries_and_requires_g_e_sources(tmp_path: Path) -> None:
    pack = _materialise_pack(
        tmp_path,
        {relative: f"payload {relative}" for relative in mod.G_E_REQUIRED_MANIFEST_PATHS},
    )
    _write_test_manifest(pack, list(mod.G_E_REQUIRED_MANIFEST_PATHS))

    result = mod.verify_pack_manifest(pack, expected_entries=3)

    assert result["status"] == "VERIFIED"
    assert result["entries_checked"] == 3
    assert result["missing"] == 0
    assert result["mismatches"] == 0


def test_pack_manifest_fails_closed_when_a_listed_file_is_missing(tmp_path: Path) -> None:
    pack = _materialise_pack(tmp_path, {"artifacts/extra.json": "{}"})
    (pack / "sha256-manifest.txt").write_text(
        f"{hashlib.sha256(b'{}').hexdigest()}  artifacts/missing.json\n",
        encoding="utf-8",
    )

    with pytest.raises(mod.InputIntegrityError, match="manifest file missing"):
        mod.verify_pack_manifest(pack, expected_entries=1)


def test_pack_manifest_fails_closed_on_a_hash_mismatch(tmp_path: Path) -> None:
    pack = _materialise_pack(tmp_path, {"artifacts/extra.json": "{}"})
    (pack / "sha256-manifest.txt").write_text(
        f"{'0' * 64}  artifacts/extra.json\n",
        encoding="utf-8",
    )

    with pytest.raises(mod.InputIntegrityError, match="pack manifest hash mismatch"):
        mod.verify_pack_manifest(pack, expected_entries=1)


def test_pack_manifest_rejects_duplicate_and_unsafe_paths(tmp_path: Path) -> None:
    pack = _materialise_pack(tmp_path, {"artifacts/extra.json": "{}"})
    digest = hashlib.sha256(b"{}").hexdigest()
    (pack / "sha256-manifest.txt").write_text(
        f"{digest}  artifacts/extra.json\n{digest}  artifacts/extra.json\n",
        encoding="utf-8",
    )

    with pytest.raises(mod.InputIntegrityError, match="duplicate pack manifest path"):
        mod.verify_pack_manifest(pack, expected_entries=2)

    (pack / "sha256-manifest.txt").write_text(
        f"{digest}  ../outside.json\n",
        encoding="utf-8",
    )
    with pytest.raises(mod.InputIntegrityError, match="unsafe pack manifest path"):
        mod.verify_pack_manifest(pack, expected_entries=1)


def test_pack_manifest_requires_all_three_g_e_source_files(tmp_path: Path) -> None:
    one = mod.G_E_REQUIRED_MANIFEST_PATHS[0]
    pack = _materialise_pack(tmp_path, {one: "{}"})
    _write_test_manifest(pack, [one])

    with pytest.raises(mod.InputIntegrityError, match="G-E source files are not covered"):
        mod.verify_pack_manifest(pack, expected_entries=1)


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
    assert current["qualification_counts"][mod.G_E_QUALIFIED] == 36
    assert current["qualification_counts"][mod.G_E_PENDING] == 4
    assert {row["group_id"] for row in current["pending_rows"]} == {"g08", "g20"}
    assert current["independently_qualified_e"]["row_count"] == 36
    assert current["evidence_failures"]["total"] == 0
    assert current["e_equals_c_on_qualified_rows"] is True

    assert history["status"] == "SUPERSEDED_BY_ROUND_2_FOR_CURRENT_STATE"
    assert history["status_code"] == "FAIL_CLOSED"
    assert history["qualified_count"] == 0
    assert history["rejected_count"] == 40
    assert "corrects" in g_e["semantic_difference"] or "pending" in g_e["semantic_difference"]

    written = json.loads((tmp_path / "option-f-report.json").read_text("utf-8"))
    assert written["design"]["name"] == "OPTION_F_TWO_LEVEL_FIXED_PRESSURE"


# --------------------------------------------------------------------------- #
# G-E evidence semantics (RC10-1 fix)
# --------------------------------------------------------------------------- #


def _audit_row(
    group_id: str,
    load_level: str,
    *,
    qualification: str = mod.G_E_QUALIFIED,
    independent_e: int | None = 112,
    native_c: int = 112,
    hash_lcp_tokens: int = 112,
    physical_prefix_equal: bool = True,
    physical_prefix_complete: bool = True,
    producer_ids: list[int] | None = None,
    consumer_ids: list[int] | None = None,
) -> dict:
    ids = list(range(1, 8))
    pending = qualification == mod.G_E_PENDING
    return {
        "group_id": group_id,
        "load_level": load_level,
        "run_id": f"run-{group_id}-{load_level}",
        "qualification": qualification,
        "independent_e": independent_e,
        "native_c": native_c,
        "hash_lcp_tokens": hash_lcp_tokens,
        "hash_lcp_blocks": 7,
        "required_shared_blocks": 7,
        "physical_prefix_complete": physical_prefix_complete,
        "physical_prefix_equal": physical_prefix_equal,
        "hash_function_match": True,
        "hash_process_match": True,
        "producer_prefix_block_ids": ids if producer_ids is None else producer_ids,
        "consumer_prefix_block_ids": ids if consumer_ids is None else consumer_ids,
        "forward_relation": (
            "EARLIER_FORWARD_ORDER_NEEDS_SEPARATE_PROOF"
            if pending
            else "SAME_FORWARD_BATCH_SOURCE_BOUND"
        ),
        "scheduler_relation": (
            "EARLIER_SCHEDULER_ITERATION" if pending else "SAME_SCHEDULER_ITERATION"
        ),
    }


def _make_complete_g_e_rows() -> list[dict]:
    rows = []
    for group in range(1, mod.EXPECTED_GROUP_COUNT + 1):
        for load_level in ("L_LOW", "L_HIGH"):
            pending = group in {8, 20}
            row = _audit_row(
                f"g{group:02d}",
                load_level,
                qualification=mod.G_E_PENDING if pending else mod.G_E_QUALIFIED,
                independent_e=None if pending else 112,
            )
            if pending:
                row["forward_relation"] = "EARLIER_FORWARD_ORDER_NEEDS_SEPARATE_PROOF"
                row["scheduler_relation"] = "EARLIER_SCHEDULER_ITERATION"
            rows.append(row)
    return rows


def _make_g_e_pack(
    root: Path,
    *,
    include_failure_file: bool = True,
    failure_text: str = "[]\n",
    round2_rows: list[dict] | None = None,
) -> Path:
    pack = root / "g-e-pack"
    qual = pack / "artifacts/phase3-same-batch-physical-qualification-audit-v1"
    round1 = pack / "artifacts/phase3-concurrent-eligibility-rejection-audit-v1"
    analysis = pack / "artifacts/phase3-load-calibration-analysis-v7"
    qual.mkdir(parents=True)
    round1.mkdir(parents=True)
    analysis.mkdir(parents=True)
    (qual / "qualification-audit.json").write_text(
        json.dumps(_make_complete_g_e_rows() if round2_rows is None else round2_rows),
        encoding="utf-8",
    )
    (round1 / "qualification-rejection-audit.json").write_text(
        json.dumps(
            [
                {
                    "qualification_result": "REJECTED_SAME_WAVE_PREFILL_NOT_COMPLETE_BEFORE_CONSUMER_LOOKUP",
                    "independently_qualified_e": None,
                    "uses_c_to_compute_e": False,
                }
                for _ in range(mod.EXPECTED_CELL_COUNT)
            ]
        ),
        encoding="utf-8",
    )
    if include_failure_file:
        (analysis / "evidence-failures.json").write_text(failure_text, encoding="utf-8")
    return pack


def test_g_e_report_fails_closed_when_evidence_failures_file_is_missing(tmp_path: Path) -> None:
    pack = _make_g_e_pack(tmp_path, include_failure_file=False)

    with pytest.raises(mod.InputIntegrityError, match="evidence-failures.json"):
        mod.g_e_report(pack)


@pytest.mark.parametrize(
    "failure_text",
    ["{", '{"rows": "not-a-list"}', '{"rows": [null]}'],
)
def test_g_e_report_fails_closed_on_invalid_evidence_failure_payload(
    tmp_path: Path, failure_text: str
) -> None:
    pack = _make_g_e_pack(tmp_path, failure_text=failure_text)

    with pytest.raises((mod.InputIntegrityError, mod.InputSchemaError)):
        mod.g_e_report(pack)


def test_g_e_audit_rejects_duplicate_or_missing_group_load_pairs() -> None:
    rows = _make_complete_g_e_rows()
    rows[-1] = dict(rows[0])

    with pytest.raises(mod.InputSchemaError, match="duplicate cell"):
        mod.validate_qualification_audit(rows)


def test_g_e_audit_rejects_incomplete_row_schema() -> None:
    rows = _make_complete_g_e_rows()
    rows[0].pop("forward_relation")

    with pytest.raises(mod.InputSchemaError, match="missing keys"):
        mod.validate_qualification_audit(rows)


def test_row_integrity_checks_qualification_relations_and_block_counts() -> None:
    row = _audit_row("g01", "L_LOW")
    row["forward_relation"] = "EARLIER_FORWARD_ORDER_NEEDS_SEPARATE_PROOF"
    row["required_shared_blocks"] = 8

    failures = mod._row_integrity_failures(row)

    assert "FORWARD_RELATION_INCONSISTENT_WITH_QUALIFICATION" in failures
    assert "PRODUCER_PREFIX_BLOCK_COUNT_MISMATCH" in failures
    assert "CONSUMER_PREFIX_BLOCK_COUNT_MISMATCH" in failures


def test_qualified_rows_contribute_zero_only_when_e_is_established() -> None:
    rows = [
        _audit_row("g01", "L_LOW"),
        _audit_row("g01", "L_HIGH"),
    ]
    summary = mod.summarize_qualification(rows, [])

    assert summary["independently_qualified_e"]["row_count"] == 2
    assert summary["e_equals_c_on_qualified_rows"] is True
    contribution = summary["primary_metric_contribution"]
    assert contribution["qualified_contribution_tokens"] == 0
    assert contribution["overall"] == "DETERMINATE"


def test_pending_rows_do_not_assert_e_equals_c() -> None:
    """A null E is unmeasured, not a conservative zero."""

    rows = [
        _audit_row("g01", "L_LOW"),
        _audit_row(
            "g08",
            "L_LOW",
            qualification=mod.G_E_PENDING,
            independent_e=None,
        ),
        _audit_row(
            "g08",
            "L_HIGH",
            qualification=mod.G_E_PENDING,
            independent_e=None,
        ),
    ]
    summary = mod.summarize_qualification(rows, [])

    assert summary["independently_qualified_e"]["row_count"] == 1
    assert summary["e_status_for_pending_rows"] == "NOT_ESTABLISHED"
    assert summary["qualification_counts"][mod.G_E_PENDING] == 2
    assert {row["e_status"] for row in summary["pending_rows"]} == {"NOT_ESTABLISHED"}
    assert {row["qualification"] for row in summary["pending_rows"]} == {mod.G_E_PENDING}

    contribution = summary["primary_metric_contribution"]
    assert contribution["qualified_contribution_tokens"] == 0
    assert contribution["pending_contribution"] == "UNDETERMINED_PENDING_QUALIFICATION"
    assert contribution["overall"] == "PARTIAL_DETERMINATE"
    assert "does not mean E == C" in contribution["not_established_note"]


def test_pending_row_keeps_its_pending_semantics_even_if_prefixes_match() -> None:
    rows = [
        _audit_row(
            "g20",
            "L_HIGH",
            qualification=mod.G_E_PENDING,
            independent_e=None,
        )
    ]
    summary = mod.summarize_qualification(rows, [])

    assert summary["qualification_counts"][mod.G_E_PENDING] == 1
    assert summary["primary_metric_contribution"]["overall"] == "PARTIAL_DETERMINATE"
    assert summary["pending_rows"][0]["condition"] == "C2"


def test_hash_lcp_and_native_c_are_reported_separately_from_e() -> None:
    rows = [_audit_row("g01", "L_LOW"), _audit_row("g01", "L_HIGH")]
    summary = mod.summarize_qualification(rows, [])

    assert summary["hash_lcp"]["token_values"] == [112]
    assert summary["native_c"]["token_values"] == [112]
    assert summary["independently_qualified_e"]["token_values"] == [112]
    assert "not an eligibility test" in summary["hash_lcp"]["meaning"]
    assert "not E" in summary["native_c"]["meaning"]
    assert "necessary but not sufficient" in summary["physical_prefix_equal_is_not_e_qualification"]


def test_evidence_failures_are_counted_not_assumed() -> None:
    rows = [_audit_row("g01", "L_LOW")]
    summary = mod.summarize_qualification(rows, [{"failure": "x"}])

    failures = summary["evidence_failures"]
    assert failures["recorded_failure_records"] == 1
    assert failures["rows_failing_integrity_checks"] == 0
    assert failures["total"] == 1
    assert summary["primary_metric_contribution"]["overall"] == "CONTRADICTORY_EVIDENCE"


def test_per_row_integrity_failures_are_detected() -> None:
    rows = [
        _audit_row("g01", "L_LOW", physical_prefix_equal=False),
        _audit_row("g02", "L_LOW", consumer_ids=[1, 2, 3]),
        _audit_row("g03", "L_LOW", native_c=None),
    ]
    summary = mod.summarize_qualification(rows, [])

    detail = summary["evidence_failures"]["row_detail"]
    assert summary["evidence_failures"]["rows_failing_integrity_checks"] == 3
    assert "PHYSICAL_PREFIX_MISMATCH" in detail["run-g01-L_LOW"]
    assert "PREFIX_BLOCK_ID_MISMATCH" in detail["run-g02-L_LOW"]
    assert "NATIVE_C_MISSING_OR_INVALID" in detail["run-g03-L_LOW"]
    assert summary["primary_metric_contribution"]["overall"] == "CONTRADICTORY_EVIDENCE"


def test_qualified_row_without_e_is_a_contradiction() -> None:
    rows = [_audit_row("g01", "L_LOW", independent_e=None)]
    summary = mod.summarize_qualification(rows, [])

    assert summary["independently_qualified_e"]["rows_without_e"] == ["run-g01-L_LOW"]
    assert summary["e_equals_c_on_qualified_rows"] is False
    assert any("qualified but carry no" in note for note in summary["contradictions"])


def test_pending_row_carrying_e_is_a_contradiction() -> None:
    rows = [_audit_row("g08", "L_LOW", qualification=mod.G_E_PENDING, independent_e=112)]
    summary = mod.summarize_qualification(rows, [])

    assert any("pending yet carry" in note for note in summary["contradictions"])
    assert summary["primary_metric_contribution"]["overall"] == "CONTRADICTORY_EVIDENCE"


def test_qualified_row_with_e_not_equal_c_reports_a_nonzero_contribution() -> None:
    rows = [_audit_row("g01", "L_LOW", independent_e=100, native_c=112)]
    summary = mod.summarize_qualification(rows, [])

    contribution = summary["primary_metric_contribution"]
    assert contribution["qualified_rows_e_not_equal_c"] == ["run-g01-L_LOW"]
    assert contribution["qualified_contribution_tokens"] == -12
    assert summary["e_equals_c_on_qualified_rows"] is False


def test_unknown_qualification_value_is_flagged() -> None:
    rows = [_audit_row("g01", "L_LOW", qualification="SOMETHING_ELSE")]
    summary = mod.summarize_qualification(rows, [])

    assert summary["qualification_counts"]["OTHER"] == 1
    assert any("neither" in note for note in summary["contradictions"])


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_g_e_does_not_assert_e_for_pending_rows(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)
    current = result["g_e"]["current_state"]

    assert current["qualification_counts"][mod.G_E_QUALIFIED] == 36
    assert current["qualification_counts"][mod.G_E_PENDING] == 4
    assert current["independently_qualified_e"]["row_count"] == 36
    assert current["hash_lcp"]["row_count"] == 40
    assert current["native_c"]["row_count"] == 40

    contribution = current["primary_metric_contribution"]
    assert contribution["qualified_contribution_tokens"] == 0
    assert contribution["pending_contribution"] == "UNDETERMINED_PENDING_QUALIFICATION"
    assert contribution["overall"] == "PARTIAL_DETERMINATE"
    assert {row["group_id"] for row in current["pending_rows"]} == {"g08", "g20"}
    assert all(row["e_status"] == "NOT_ESTABLISHED" for row in current["pending_rows"])

    assert current["evidence_failures"]["total"] == 0
    assert current["contradictions"] == []


# --------------------------------------------------------------------------- #
# noise variance rule (RC10-5)
# --------------------------------------------------------------------------- #


def _f_fixture_args():
    """``(cells, groups, options)`` for functions that do not need the F report."""

    cells, groups, options, _ = _f_fixture()
    return cells, groups, options


def test_noise_variance_rule_is_a_single_frozen_estimator() -> None:
    noise = mod.noise_selection_report(*_f_fixture_args())

    variance = noise["variance_estimation"]
    assert "ONE rule" in variance["frozen_rule"]
    assert variance["assumption"].startswith("COMMON within-cell variance")
    assert len(variance["justification"]) == 3
    allocation = noise["selection_rule"]["stratum_allocation"]
    selected = len(noise["selection_rule"]["selected_groups"])
    expected_df = selected * mod.NOISE_CONDITIONS * (mod.NOISE_REPEATS - 1)
    assert variance["df"] == expected_df
    assert sum(allocation.values()) == 5
    assert variance["stratified_reporting_required"] is True
    assert "DIAGNOSTIC_ONLY" in variance["stratified_outputs"]["status"]
    assert "not be revised once the noise runs exist" in variance["no_post_run_change"]
    assert variance["tied"] == "2 * sqrt(2) * sigma_run"
    assert variance["sigma_delta"] == "sqrt(2) * sigma_run under independent equal variance"


def test_noise_stratum_weights_are_stated_but_not_used_as_cell_weights() -> None:
    noise = mod.noise_selection_report(*_f_fixture_args())
    variance = noise["variance_estimation"]

    weights = variance["target_population_stratum_weights"]
    assert weights["RESPONSIVE"] == pytest.approx(7 / 18, abs=1e-4)
    assert weights["WEAK"] == pytest.approx(8 / 18, abs=1e-4)
    assert weights["FLAT"] == pytest.approx(3 / 18, abs=1e-4)
    assert "NOT proportional" in variance["weights"]

    allocation = noise["selection_rule"]["stratum_allocation"]
    assert sum(allocation.values()) == 5


# --------------------------------------------------------------------------- #
# evidence inventory (RC10 item 3)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not REAL_PACK.is_dir(),
    reason="frozen evidence pack absent (local/ is not tracked)",
)
def test_real_pack_evidence_inventory_separates_gpu_from_derived(tmp_path: Path) -> None:
    result = mod.run(REAL_PACK, tmp_path)
    inventory = result["inventory"]

    separation = inventory["evidence_separation"]
    assert "phase3-load-calibration-inputs-v1" in separation["frozen_execution_inputs"]
    assert "phase3-load-calibration-analysis-v7" in separation["mixed_directories"]
    assert "phase3-load-calibration-analysis-v7" in separation["per_run_execution_reports"]
    assert "phase3-load-calibration-runs-v2" in separation["execution_summaries"]
    assert (
        "phase3-same-batch-runtime-evidence-inventory-v1"
        in separation["runtime_evidence_inventories"]
    )
    assert (
        "phase3-load-calibration-iteration2-planning-v1" in separation["offline_derived_analysis"]
    )
    assert (
        "phase3-same-batch-physical-qualification-audit-v1"
        in separation["offline_audits_over_gpu_evidence"]
    )

    directories = {entry["directory"]: entry for entry in inventory["directories"]}
    analysis = directories["artifacts/phase3-load-calibration-analysis-v7"]
    assert analysis["evidence_kind"] == "MIXED_PER_RUN_REPORTS_AND_OFFLINE_ANALYSIS"
    assert analysis["file_class_counts"]["PER_RUN_EXECUTION_REPORT"] == 40
    assert analysis["file_class_counts"]["OFFLINE_AUDIT_OR_AGGREGATE"] == 4
    assert analysis["file_class_counts"]["UNCLASSIFIED"] == 1
    assert analysis["manifested_file_count"] == 44
    assert inventory["unclassified_file_count"] == 1

    assert separation["unclassified_directories"] == []

    delivery = inventory["delivery_status"]
    assert delivery["manifest_committed"] is True
    assert delivery["manifest_entry_count"] == 250
    assert delivery["raw_pack_transferred_to_m1"] is False

    claims = " ".join(inventory["reproduction_claims_this_analysis_does_not_make"])
    assert "does not reproduce a GPU experiment" in claims
    assert "not experimental replication" in claims

    written = json.loads((tmp_path / "evidence-inventory.json").read_text("utf-8"))
    assert written["pack_file_count"] == inventory["pack_file_count"]


def test_evidence_inventory_classifies_mixed_execution_and_analysis_files(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    files = {
        "artifacts/phase3-load-calibration-inputs-v1/freeze.json": "{}\n",
        "artifacts/phase3-load-calibration-analysis-v7/runs/phase3-load-calibration-g01-l-low-a0.json": "{}\n",
        "artifacts/phase3-load-calibration-analysis-v7/aggregate-report.json": "{}\n",
        "artifacts/phase3-load-calibration-analysis-v7/evidence-failures.json": "[]\n",
        "artifacts/phase3-load-calibration-analysis-v7/qualification-audit.json": "[]\n",
        "artifacts/phase3-load-calibration-analysis-v7/unexpected.bin": "x",
        "artifacts/phase3-load-calibration-runs-v2/execution-summary.json": "{}\n",
        "artifacts/phase3-same-batch-runtime-evidence-inventory-v1/runtime-evidence-inventory.json": "{}\n",
        "artifacts/phase3-same-batch-physical-qualification-audit-v1/qualification-audit.json": "[]\n",
        "artifacts/phase3-load-calibration-iteration2-planning-v1/proposal.json": "{}\n",
        "artifacts/mystery-dir/row.json": "{}\n",
    }
    pack = _materialise_pack(tmp_path, files)
    (pack / "sha256-manifest.txt").write_text("", encoding="utf-8")

    inventory = mod.evidence_inventory_report(pack)
    entries = {entry["directory"]: entry for entry in inventory["directories"]}

    assert (
        entries["artifacts/phase3-load-calibration-inputs-v1"]["evidence_kind"]
        == "FROZEN_EXECUTION_INPUTS"
    )
    mixed = entries["artifacts/phase3-load-calibration-analysis-v7"]
    assert mixed["evidence_kind"] == "MIXED_PER_RUN_REPORTS_AND_OFFLINE_ANALYSIS"
    assert mixed["file_class_counts"] == {
        "OFFLINE_AUDIT_OR_AGGREGATE": 3,
        "PER_RUN_EXECUTION_REPORT": 1,
        "UNCLASSIFIED": 1,
    }
    assert (
        entries["artifacts/phase3-load-calibration-runs-v2"]["evidence_kind"] == "EXECUTION_SUMMARY"
    )
    assert (
        entries["artifacts/phase3-same-batch-runtime-evidence-inventory-v1"]["evidence_kind"]
        == "RUNTIME_EVIDENCE_INVENTORY"
    )
    assert (
        entries["artifacts/phase3-same-batch-physical-qualification-audit-v1"]["evidence_kind"]
        == "OFFLINE_AUDIT_OVER_GPU_EVIDENCE"
    )
    assert (
        entries["artifacts/phase3-load-calibration-iteration2-planning-v1"]["evidence_kind"]
        == "OFFLINE_DERIVED_ANALYSIS"
    )
    assert entries["artifacts/mystery-dir"]["evidence_kind"] == "UNCLASSIFIED"
    assert inventory["unclassified_file_count"] == 2
    assert inventory["evidence_separation"]["unclassified_directories"] == ["mystery-dir"]
    assert inventory["delivery_status"]["manifest_entry_count"] == 0


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
