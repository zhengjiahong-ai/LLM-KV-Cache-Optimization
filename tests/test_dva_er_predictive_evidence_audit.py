import pytest

from scripts.audit_dva_er_predictive_evidence import (
    comparative_geometry,
    event_archive,
    phase3_inventory,
    unique_index,
)


def test_duplicate_decision_identity_is_rejected():
    rows = [{"run": "a", "decision": "d"}, {"run": "b", "decision": "d"}]

    def key(row):
        return row["run"], row["decision"]

    assert len(unique_index(rows, key)) == 2
    with pytest.raises(ValueError, match="Duplicate evidence identity"):
        unique_index([*rows, rows[0]], key)


def test_raw_archive_must_match_the_pinned_hash(tmp_path):
    archive = tmp_path / "other.tar.gz"
    archive.write_bytes(b"other evidence")
    with pytest.raises(ValueError, match="SHA-256"):
        event_archive(archive, "0" * 64)
    assert event_archive(None, "0" * 64)["inspection"] == "RAW_ARCHIVE_NOT_SUPPLIED"


def test_geometry_comparison_requires_known_complete_candidate_suffix():
    candidates = [
        {"program": "a", "first_victim_depth": 5, "chain_length": 6},
        {"program": "b", "first_victim_depth": 6, "chain_length": 7},
    ]
    assert comparative_geometry(candidates, 2, {"a": 0, "b": 16})["deeper_prefix_ordinal"] == "DISCORDANT"
    assert comparative_geometry(candidates, 2, {"a": 0, "b": 0})["deeper_prefix_ordinal"] == "TIED_LABEL"
    with pytest.raises(ValueError, match="contiguous"):
        comparative_geometry(candidates, 3, {"a": 0, "b": 16})
    with pytest.raises(ValueError, match="candidates differ"):
        comparative_geometry(candidates, 2, {"a": 0})


def test_checked_in_phase3_counts_keep_native_and_counterfactual_labels_separate():
    result = phase3_inventory()
    assert result["main_request_arm_outcomes"] == 5760
    assert sum(arm["forced_decisions"] for arm in result["arms"].values()) == 635
    assert result["arms"]["A0"]["competitive"] == 7
    assert result["arms"]["A0"]["downstream_attribution"] == {"NOT_ESTABLISHED": 127}
    historical = result["legacy_candidate_comparison"]
    assert historical["distinct_groups"] == 4
    assert historical["equal_victim_budget_pairs"] == 7
    assert historical["unequal_window_losses"] == 4
    assert historical["depth_order_by_label"] == {"TIED_LABEL": 2, "DISCORDANT": 3}
    assert all(row["score"] == "NOT_EVALUABLE" and
               row["native_candidate_recompute_attribution"] == "NOT_ESTABLISHED"
               for row in historical["cases"])
