"""Independently reproduce H2 resolution from the committed numeric evidence."""

import argparse
import json
import random
from pathlib import Path


def reproduce(audit: dict) -> dict:
    """Use order statistics and explicit uniform draws, without production imports."""
    assert audit["bootstrap_iterations"] == 10000
    assert audit["resample_size"] == 9
    assert audit["seed"] == 20261007
    assert audit["percentile_rule"] == "nearest_rank"
    assert [p["prefix_tokens"] for p in audit["points"]] == [
        8192, 12288, 16384, 20480, 24576, 26624, 28672, 30720
    ]
    results = []
    for point in audit["points"]:
        rows = point["measured_runs"]
        assert len(rows) == 5
        assert all(r["git_dirty"] is False for r in rows)
        values = [r["elapsed_seconds"] for r in rows]
        assert all(v > 0 for v in values)
        center = sorted(values)[2]
        rng = random.Random(20261007)
        deviations = []
        for _ in range(10000):
            # random.choices uses floor(random() * population_size) for uniform draws.
            sample = [values[int(rng.random() * 5)] for _ in range(9)]
            deviations.append(abs(sorted(sample)[4] - center))
        delta = sorted(deviations)[9499]
        results.append({"prefix_tokens": point["prefix_tokens"], "delta_r_seconds": delta})
    delta = max(r["delta_r_seconds"] for r in results)
    assert delta == audit["recorded_delta_M1_seconds"], "recorded delta does not reproduce"
    return {"outcome": "PASS", "delta_M1_seconds": delta, "point_results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    args = parser.parse_args()
    print(json.dumps(reproduce(json.loads(args.audit.read_text())), indent=2))
