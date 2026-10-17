import json
from pathlib import Path

import pytest

from kvopt.profiling.phase2g_a1_evidence import package_phase2g_a1_evidence


def test_evidence_pack_rejects_incomplete_run_set(tmp_path: Path) -> None:
    gate1 = tmp_path / "gate1.json"
    campaign = tmp_path / "campaign"
    runs = tmp_path / "runs"
    outcome = tmp_path / "outcome.json"
    campaign.mkdir()
    runs.mkdir()
    gate1.write_text("{}\n", encoding="utf-8")
    for name in ("manifest.json", "validation.json", "authorization.json"):
        (campaign / name).write_text("{}\n", encoding="utf-8")
    outcome.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_bounded_gate.v1",
                "overall": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all 144 run manifests"):
        package_phase2g_a1_evidence(
            repository=Path(__file__).parents[1],
            gate1_report=gate1,
            campaign_root=campaign,
            run_root=runs,
            outcome_report=outcome,
            archive_path=tmp_path / "evidence.tar.gz",
        )
