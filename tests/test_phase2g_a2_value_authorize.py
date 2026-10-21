from pathlib import Path

from kvopt.workload.phase2g_a2_value_authorize import A2_IMPLEMENTATION_SHA


def test_bounded_value_authorization_keeps_frozen_a2_identity() -> None:
    assert A2_IMPLEMENTATION_SHA == "15a65e36604af5679987bb91d224fd20ce560e8a"
    assert len(A2_IMPLEMENTATION_SHA) == 40
    assert Path("configs/phase2/phase2g-a2-bounded-value-distribution-v2.json").name
