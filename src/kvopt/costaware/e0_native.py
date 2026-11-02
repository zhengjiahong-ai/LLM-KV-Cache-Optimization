"""Native coordinator for the Phase 3 E0 deadline-only control arm."""

from __future__ import annotations

from collections.abc import Mapping

from .a3_native import A3NativeSelectionCoordinator
from .a3_suffix import A3SuffixCostStrategy
from .e0_deadline import E0DeadlineStrategy
from .entry_depth import DepthVerificationMode


class E0NativeSelectionCoordinator(A3NativeSelectionCoordinator):
    """Use A3's live evidence boundary while replacing only S2A ordering."""

    def _build_strategy(
        self, live_hashes: Mapping[int, str]
    ) -> E0DeadlineStrategy:
        classifier = A3SuffixCostStrategy(
            depth_index=self._depth_index,
            native_hash_process_id=self._native_hash_process_id,
            decision_clock_domain=self._decision_clock_domain,
            verification_mode=DepthVerificationMode.NATIVE_LIVE,
            content_hashes=live_hashes,
            lambda_=self.strategy.lambda_,
            tau_seconds=self.strategy.tau_seconds,
        )
        return E0DeadlineStrategy(classifier)
