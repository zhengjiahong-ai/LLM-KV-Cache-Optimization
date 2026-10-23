import json
from pathlib import Path

import pytest

from kvopt.profiling.continuum_w1b_evidence import package_w1b_evidence


def test_w1b_evidence_rejects_incomplete_run_set(tmp_path: Path) -> None:
    roots = [
        tmp_path / name for name in ("replay", "fidelity", "profile", "freeze", "campaign", "runs")
    ]
    for root in roots:
        root.mkdir()
    (roots[-1] / "comparison-report-v2.json").write_text(
        json.dumps({"gate": "PASS"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exactly 12 run manifests"):
        package_w1b_evidence(
            repository=Path(__file__).parents[1],
            replay_root=roots[0],
            fidelity_root=roots[1],
            profile_root=roots[2],
            freeze_root=roots[3],
            campaign_root=roots[4],
            run_root=roots[5],
            archive_path=tmp_path / "evidence.tar.gz",
        )
