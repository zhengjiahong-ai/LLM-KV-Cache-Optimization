"""Read-only rebuild of one recorded A2 block decision from its own evidence.

Why this module exists
----------------------
``step_costs`` does **not** describe the cost distribution over the candidates of a
decision. ``a2_selector.greedy_select`` appends exactly one entry per pick: the
marginal cost of the block that was chosen. The candidates that lost never appear.
Any classification that reads ``step_costs`` as a same-decision spread is therefore
not measuring what it claims to measure. The rebuild here is the only source of
per-step, all-candidate marginal costs.

Rank
----
``VLLMEvictionBridge.build_candidates`` numbers ``lru_rank`` by ``enumerate(blocks)``
over the native free-queue snapshot and passes that list through unchanged, so a
block's position in ``legal_block_ids`` *is* its native LRU rank. This module does
not assume that: :func:`rebuild` checks ``native_lru_victims == legal_block_ids[:need]``
on every decision and reports every violation.

Completeness
------------
Every legal id is kept. Three identity states are reconstructed from the payload:

``HASHLESS_NO_CONTENT``
    no memberships, no content hash -> ``has_block_hash=False``, cost zero by
    construction, still a legal candidate and still part of the decision.
``CONTENT_UNVERIFIED``
    content hash present but memberships empty -> the engine stripped them, so the
    decision is recorded as having a content gap and is reported unscorable rather
    than silently scored with the missing cost treated as zero.
``CONTENT_VERIFIED_*``
    memberships present; weighted when every chain has a decision-time reuse weight.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from kvopt.costaware.a2_geometry import (
    ChainKey,
    DecisionGeometry,
    LegalBlock,
    Membership,
)

BLOCK = "COST_AWARE_BLOCK_DECISION"
FORCED = "FORCED_RELEASE_DECISION"

RUNS_ROOT = (
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/"
    "artifacts/continuum-native-cost-aware-bounded-runs-v10/runs"
)


@dataclass(frozen=True, slots=True)
class Rebuild:
    """One decision, reconstructed from the payload and checked against it."""

    run: str
    geometry: DecisionGeometry
    need: int
    legal_count: int
    hashless_count: int
    unverified_count: int
    recorded_states: dict[str, int]
    rebuilt_states: dict[str, int]
    rank_order_ok: bool
    selector: str
    selected: tuple[int, ...]
    native: tuple[int, ...]
    recorded_loss: float | None
    recorded_truncated: bool

    @property
    def state_ok(self) -> bool:
        """The reconstructed identity states reproduce the recorded counts exactly."""
        return self.recorded_states == self.rebuilt_states

    @property
    def unselected_legal_blocks(self) -> int:
        """Legal candidates the engine could have chosen between."""
        return self.legal_count - self.need


def iter_decisions(arm: str = "a2", root: str = RUNS_ROOT) -> Iterator[tuple[str, dict]]:
    """Yield ``(run_id, payload)`` for every block decision of one arm."""
    for path in sorted(Path(root).glob(f"*-{arm}-repeat-*/events.jsonl")):
        run = path.parent.name
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event_type"] == BLOCK:
                yield run, event["payload"]


def _memberships(payload: dict) -> dict[int, tuple[Membership, ...]]:
    table: dict[int, tuple[Membership, ...]] = {}
    for item in payload.get("block_memberships") or []:
        block_id = int(item["block_id"])
        table[block_id] = tuple(
            Membership(
                chain=str(member.get("chain_id", member.get("chain"))),
                depth=int(member["depth"]),
                content_hash=member.get("content_hash") or "",
            )
            for member in item.get("memberships") or []
        )
    return table


def _chain_length(payload: dict) -> dict[ChainKey, int]:
    return {
        str(chain): int(length)
        for chain, length in (payload.get("effective_chain_lengths") or {}).items()
    }


def _weights(payload: dict) -> dict[ChainKey, float]:
    return {
        str(chain): float(weight)
        for chain, weight in (payload.get("decision_reuse_weights") or {}).items()
    }


def rebuild(run: str, payload: dict) -> Rebuild:
    """Rebuild the decision geometry, keeping the complete legal set."""
    legal = [int(block_id) for block_id in payload.get("legal_block_ids") or []]
    hashes = {
        int(item["block_id"]): item.get("content_hash")
        for item in payload.get("legal_content_hashes") or []
    }
    memberships = _memberships(payload)
    weights = _weights(payload)
    lengths = _chain_length(payload)

    blocks: dict[int, LegalBlock] = {}
    hashless: list[int] = []
    unverified: list[int] = []
    for native_rank, block_id in enumerate(legal):
        owned = memberships.get(block_id, ())
        has_hash = hashes.get(block_id) is not None
        if owned:
            blocks[block_id] = LegalBlock(
                block_id=block_id,
                native_rank=native_rank,
                memberships=owned,
                has_block_hash=True,
            )
            continue
        # No provable membership: either the block carries no content at all, or its
        # content identity is present but the engine could not prove where it lives.
        if has_hash:
            unverified.append(block_id)
        else:
            hashless.append(block_id)
        blocks[block_id] = LegalBlock(
            block_id=block_id,
            native_rank=native_rank,
            memberships=(),
            has_block_hash=has_hash,
        )

    geometry = DecisionGeometry(
        blocks=blocks,
        chain_length=lengths,
        q_by_chain=weights,
        gaps={block_id: "content_unverified" for block_id in unverified},
    )

    states: Counter[str] = Counter()
    for block_id in legal:
        owned = blocks[block_id].memberships
        if block_id in unverified:
            states["CONTENT_UNVERIFIED"] += 1
        elif owned and all(member.chain in weights for member in owned):
            states["CONTENT_VERIFIED_CHAIN_WEIGHTED"] += 1
        elif owned:
            states["CONTENT_VERIFIED_WEIGHT_UNKNOWN"] += 1
        elif blocks[block_id].has_block_hash:
            states["CONTENT_VERIFIED_CHAIN_UNUSABLE"] += 1
        else:
            states["HASHLESS_NO_CONTENT"] += 1

    need = min(int(payload.get("required_blocks") or 0), len(legal))
    native = tuple(payload.get("native_lru_victims") or ())
    return Rebuild(
        run=run,
        geometry=geometry,
        need=need,
        legal_count=len(legal),
        hashless_count=len(hashless),
        unverified_count=len(unverified),
        recorded_states={
            str(k): int(v) for k, v in (payload.get("identity_state_counts") or {}).items()
        },
        rebuilt_states=dict(sorted(states.items())),
        rank_order_ok=native == tuple(legal[:need]),
        selector=str(payload.get("selector")),
        selected=tuple(payload.get("selected_victims") or ()),
        native=native,
        recorded_loss=payload.get("proxy_weighted_loss"),
        recorded_truncated=bool(payload.get("search_truncated")),
    )


def apply_block(block: LegalBlock, evicted: dict[ChainKey, set[int]]) -> None:
    """Record an eviction: every chain containing the block moves its gap inward."""
    for member in block.memberships:
        evicted.setdefault(member.chain, set()).add(member.depth)


def marginal_table(geometry: DecisionGeometry, need: int, marginal_cost) -> list[dict[int, float]]:
    """Same-step marginal cost of **every** remaining candidate, one dict per pick.

    ``marginal_cost`` is ``a2_selector.marginal_cost``; it is passed in so this
    module stays independent of the selector's private helpers. The walk follows the
    same rule as ``greedy_select`` -- cheapest first, rank then id on ties -- so the
    rows describe the decision as the engine faced it, not the picks it happened to
    make.
    """
    remaining = dict(geometry.blocks)
    evicted: dict[ChainKey, set[int]] = {}
    rows: list[dict[int, float]] = []
    for _ in range(min(need, len(remaining))):
        costs = {
            block_id: marginal_cost(block, evicted, geometry)
            for block_id, block in remaining.items()
        }
        rows.append(costs)
        chosen = min(costs, key=lambda bid: (costs[bid], geometry.blocks[bid].native_rank, bid))
        apply_block(remaining.pop(chosen), evicted)
    return rows
