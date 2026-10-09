from kvopt.costaware.h1_formal import classify_scenario_validity


def test_validity_counts_complete_seed_triads_and_preserves_failures() -> None:
    results = []
    for family, scenario, statuses in (
        ("F1", "valid", ("success", "success", "success")),
        ("F2", "invalid", ("failed", "failed", "failed")),
    ):
        for seed, status in zip((101, 211, 307), statuses, strict=True):
            results.append(
                {
                    "run_id": f"{scenario}-seed-{seed}",
                    "scenario_id": scenario,
                    "family_id": family,
                    "seed": seed,
                    "status": status,
                    "failure_reason": None if status == "success" else "capacity",
                }
            )

    audit = classify_scenario_validity({"results": results})

    assert audit["valid_independent_scenario_count"] == 1
    assert audit["invalid_independent_scenario_count"] == 1
    assert audit["valid_family_counts"] == {"F1": 1}
    assert audit["invalid_scenarios"][0]["failure_reasons"] == ["capacity"]
    assert audit["adequate"] is False
