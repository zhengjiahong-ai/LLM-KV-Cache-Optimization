import json
from pathlib import Path

import pytest

from kvopt.profiling.phase2g_a2_evidence import package_phase2g_a2_evidence


def test_evidence_pack_rejects_incomplete_gate1_run_set(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    runs = tmp_path / "runs"
    campaign.mkdir()
    runs.mkdir()
    (campaign / "manifest.json").write_text("{}\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a2_native_gate1_report.v1",
                "gate2_execution_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all 24 run manifests"):
        package_phase2g_a2_evidence(
            repository=Path(__file__).parents[1],
            campaign_root=campaign,
            run_root=runs,
            review_report=report,
            smoke_roots=(),
            archive_path=tmp_path / "evidence.tar.gz",
        )
