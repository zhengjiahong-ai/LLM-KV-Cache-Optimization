"""Phase 2I: content-keyed chain depth proofs for the suffix cost proxy.

Why this module exists
----------------------
The suffix term ``S_X = m_X - d_min(X) + 1`` needs two things the retention
entry cannot provide by itself:

``d_min(X)``
    the **original** prefix depth of the shallowest predicted victim, and
``m_X``
    the **full** original chain length.

``RetentionEntrySnapshot.block_ids`` is an ordered tuple, so it is tempting to
treat the index as the depth. That is wrong as soon as a block is evicted: the
frozen retention code compacts the tuple in place.

    retention.py::observe_eviction             block_ids = tuple(b for b in ... if b != evicted)
    retention.py::reconcile_entry_evictions    block_ids = tuple(b for b in ... if b not in stale)

After depth ``d`` is evicted every later block shifts down one position, so
``index + 1`` stops being that block's depth, and ``len(block_ids)`` stops being
``m``. Both errors are biased: they make ``S`` smaller, which makes an entry with
missing depth information look cheap. The cost proxy would then favour exactly
the entries whose geometry it cannot see.

The fix
-------
Record the depth **when the chain is observed**, bind it to the content identity
of each slot, and never re-derive it from array position:

``ChainDepthProof``
    immutable snapshot of one chain: ``(block_id, content_hash, depth)`` triples
    plus the chain length, the native hash process, the observation ordinal and
    time, and the clock domain.
``DepthQuery``
    everything the lookup must be validated against: the chain it belongs to,
    the native process, the decision ordinal and timestamp, the clock domain,
    and the observation the caller believes is current.
``ChainDepthIndex``
    the store of observed proofs, answering "which proof is the latest valid one
    strictly before this decision".

Identity and freshness are *checked*, not merely stored
-------------------------------------------------------
A lookup returns a depth only when all of the following hold; anything else
returns ``None`` with an attributable status:

1. same chain identity;
2. same native hash process;
3. the observation strictly precedes the decision;
4. the proof is the latest observation of that chain before the decision
   (``SUPERSEDED`` otherwise);
5. where clock domains are comparable, the observation is neither from the
   future nor older than ``max_age_seconds``;
6. the proof actually records content identity (``IDENTITY_UNVERIFIED``
   otherwise);
7. the slot exists and still holds the recorded content
   (``UNKNOWN_BLOCK`` / ``CONTENT_MISMATCH``).

Clock domains
-------------
The raw archive uses ``system_monotonic`` for prefix snapshots and
``continuum_pressure`` for forced-release decisions, so raw timestamp
subtraction across those two events is meaningless. Freshness is therefore
enforced in two layers:

* **binding** -- observation order (``observation_index < decision_index``) plus
  "this proof is the latest observation of the chain". Both are clock-free.
* **auxiliary** -- ``max_age_seconds``, applied only when the clock domains
  match. This is why the docstring of ``max_age_seconds`` says it is an upper
  bound and *not* a substitute for the lifecycle consistency check.

Block id recycling
------------------
A recycled physical slot must not inherit the old depth. Recycling implies a new
chain identity (the frozen prefix id embeds the root native hash) or a new
observation of the same chain, and both are caught: the former by the chain
identity check, the latter by ``SUPERSEDED`` plus the content check.

What this module must not do
----------------------------
It is read-only metadata. It does not touch the native ``BlockPool``, the free
queue, ref counts, hash cleanup, scheduler ownership or the physical eviction
lifecycle. Nothing here can cause an eviction.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

#: Auxiliary freshness bound for a recorded proof.
#:
#: This is a correctness ceiling, not a tuning knob, and it is explicitly *not*
#: the primary validity check: the binding requirement is that the proof be the
#: latest observation of the chain strictly before the decision. It is applied
#: only when the observation and the decision share a clock domain, because
#: timestamps from different domains are not comparable.
DEFAULT_MAX_AGE_SECONDS = 600.0

#: Sentinel clock domain meaning "unknown / not recorded".
CLOCK_DOMAIN_UNKNOWN = ""

#: Sentinel process id meaning "the caller did not pin a process".
#:
#: A real runtime must pass the *current* native hash process id, so that a proof
#: recorded by a previous process is rejected as ``WRONG_PROCESS``. The sentinel
#: exists for single-runtime offline replay, where the proof itself carries the
#: only process that ever observed the chain. It is never a value a live query
#: may use to assert a process identity.
CHAIN_PROCESS_UNSET = ""


class DepthStatus(str, Enum):
    """Outcome of one depth lookup.

    Only :attr:`OK` yields a depth. Every other member is a fail-closed signal
    the caller must surface rather than paper over; they are distinct so a
    fallback can record *why* it happened.
    """

    OK = "OK"
    WRONG_CHAIN = "WRONG_CHAIN"
    WRONG_PROCESS = "WRONG_PROCESS"
    FUTURE_OBSERVATION = "FUTURE_OBSERVATION"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    SUPERSEDED = "SUPERSEDED"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    CONTENT_MISMATCH = "CONTENT_MISMATCH"
    UNKNOWN_BLOCK = "UNKNOWN_BLOCK"
    #: Native scoring was requested but the caller supplied no current content
    #: identity for this block. A recorded proof is *not* a substitute: it only
    #: says what the slot held when the chain was observed.
    LIVE_IDENTITY_REQUIRED = "LIVE_IDENTITY_REQUIRED"


class DepthVerificationMode(str, Enum):
    """Which identity standard a depth lookup must meet.

    The two modes are not interchangeable, and the distinction is the whole point
    of this enum: a result produced in :attr:`HISTORICAL_REPLAY` mode must never be
    described as native content verification.

    ``HISTORICAL_REPLAY``
        Offline analysis of an archive. No live content identity exists, so the
        proof's own recorded identity is used. Sound *for replay*, because the
        proof must be the latest observation of the chain and any later content
        change would have produced a later observation. It is nevertheless a
        statement about the past, so every result is flagged
        ``content_verified = False``.

    ``NATIVE_LIVE``
        Real native scoring. The caller must supply the current content identity
        of every victim, because a block id can be recycled after the snapshot and
        no new snapshot may ever appear for the old chain. A missing live identity
        is a fail-closed condition (:attr:`DepthStatus.LIVE_IDENTITY_REQUIRED`),
        never a reason to fall back to the recorded hash.
    """

    HISTORICAL_REPLAY = "historical_replay"
    NATIVE_LIVE = "native_live"


#: Statuses that mean "the caller must fall back", as opposed to "this block
#: genuinely has no depth". Both are fail-closed; the distinction is only for
#: reporting.
FALLBACK_STATUSES = frozenset(DepthStatus) - {DepthStatus.OK}


@dataclass(frozen=True, slots=True)
class DepthQuery:
    """Identity, ordering and freshness context a lookup is validated against.

    A bare ``(block_id, content_hash)`` pair is not enough: the same physical
    slot can appear in another chain, in another runtime process, at a much later
    time, or be an observation that has since been superseded by a newer one.
    """

    chain_id: tuple[str, str]
    native_hash_process_id: str
    decision_index: int
    decision_time: float
    decision_clock_domain: str = CLOCK_DOMAIN_UNKNOWN
    expected_observation_index: int | None = None
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
    verification_mode: DepthVerificationMode = DepthVerificationMode.HISTORICAL_REPLAY

    def __post_init__(self) -> None:
        if not self.chain_id[0] or not self.chain_id[1]:
            raise ValueError("chain_id must name both a program and a prefix")
        if not self.native_hash_process_id:
            raise ValueError("native_hash_process_id must be non-empty")
        if self.decision_index < 0:
            raise ValueError("decision_index must be non-negative")
        if self.max_age_seconds <= 0.0:
            raise ValueError("max_age_seconds must be positive")

    @property
    def requires_live_identity(self) -> bool:
        return self.verification_mode is DepthVerificationMode.NATIVE_LIVE


@dataclass(frozen=True, slots=True)
class DepthResolution:
    """Result of resolving a whole victim set."""

    depths: Mapping[int, int]
    failures: Mapping[int, DepthStatus]
    #: True only when a live content hash was actually compared for every
    #: resolved block. ``False`` means the depth came from the recorded proof and
    #: therefore describes the observation, not the present.
    live_identity_checked: bool = False

    @property
    def resolved(self) -> bool:
        """True only when every requested block resolved.

        Partial resolution is never usable as a partial score: an under-counted
        victim set yields a smaller ``S``, which makes the entry look cheaper.
        """

        return not self.failures

    @property
    def content_verified(self) -> bool:
        """True only when the depths were validated against current content.

        Callers must use this, not :attr:`resolved`, when deciding whether a result
        may be described as native content verification.
        """

        return self.resolved and self.live_identity_checked


@dataclass(frozen=True, slots=True)
class ChainDepthProof:
    """Immutable, content-keyed depth record for one observed chain.

    Created at observation time by :meth:`from_observation`; the depth of a block
    is the position it held in the chain **when the chain was observed**, which
    is the only place that information exists.
    """

    chain_id: tuple[str, str]
    native_hash_process_id: str
    block_ids: tuple[int, ...]
    content_hashes: tuple[str, ...]
    depths: tuple[int, ...]
    observation_index: int
    observed_at: float
    clock_domain: str = CLOCK_DOMAIN_UNKNOWN

    def __post_init__(self) -> None:
        if not self.chain_id[0] or not self.chain_id[1]:
            raise ValueError("chain_id must name both a program and a prefix")
        if not self.native_hash_process_id:
            raise ValueError("native_hash_process_id must be non-empty")
        count = len(self.block_ids)
        if count == 0:
            raise ValueError("a chain proof must describe at least one block")
        if len(self.depths) != count:
            raise ValueError("block_ids and depths must be aligned")
        if len(set(self.block_ids)) != count:
            raise ValueError("block_ids must not contain duplicates")
        if sorted(self.depths) != list(range(1, count + 1)):
            raise ValueError("depths must be exactly 1..n, one per block, no holes")
        # An empty tuple means "identity was never recorded", which is a legal
        # observation; a non-empty tuple must be aligned with block_ids.
        if self.content_hashes and len(self.content_hashes) != count:
            raise ValueError("content_hashes must be aligned with block_ids")
        if self.observation_index < 0:
            raise ValueError("observation_index must be non-negative")
        if not math.isfinite(self.observed_at):
            raise ValueError("observed_at must be finite")

    # -- construction ----------------------------------------------------

    @classmethod
    def from_observation(
        cls,
        chain_id: tuple[str, str],
        native_hash_process_id: str,
        block_ids: Sequence[int],
        *,
        content_hashes: Sequence[str] = (),
        observation_index: int,
        observed_at: float,
        clock_domain: str = CLOCK_DOMAIN_UNKNOWN,
    ) -> ChainDepthProof:
        """Record a chain observation, with depth = observed chain position.

        ``content_hashes`` may be empty when the observation did not capture
        content identity; such a proof is still stored but can never return a
        depth, because it cannot prove which content occupies a slot.
        """
        ordered_blocks = tuple(int(block_id) for block_id in block_ids)
        hashes = tuple(str(value) for value in content_hashes)
        if hashes and len(hashes) != len(ordered_blocks):
            raise ValueError("content_hashes must be either empty or aligned with block_ids")
        return cls(
            chain_id=chain_id,
            native_hash_process_id=native_hash_process_id,
            block_ids=ordered_blocks,
            content_hashes=hashes,
            depths=tuple(range(1, len(ordered_blocks) + 1)),
            observation_index=observation_index,
            observed_at=float(observed_at),
            clock_domain=clock_domain,
        )

    # -- properties ------------------------------------------------------

    @property
    def chain_length(self) -> int:
        """``m``: the full prefix length at observation time, never a live count."""

        return len(self.depths)

    @property
    def identity_verified(self) -> bool:
        """True when every slot recorded a usable content identity."""

        return bool(self.content_hashes) and all(
            value not in ("", None) for value in self.content_hashes
        )

    def recorded_hash(self, block_id: int) -> str | None:
        try:
            index = self.block_ids.index(block_id)
        except ValueError:
            return None
        if not self.content_hashes:
            return None
        return self.content_hashes[index]

    # -- validated lookup ------------------------------------------------

    def status_for(self, query: DepthQuery) -> DepthStatus | None:
        """Validate everything that does not depend on the specific slot.

        Returns ``None`` when the proof is usable for this query, otherwise the
        first failing status. Kept separate from :meth:`depth_of` so a caller can
        reject a proof once for a whole victim set.
        """

        if query.chain_id != self.chain_id:
            return DepthStatus.WRONG_CHAIN
        if query.native_hash_process_id != self.native_hash_process_id:
            return DepthStatus.WRONG_PROCESS
        if self.observation_index >= query.decision_index:
            return DepthStatus.FUTURE_OBSERVATION
        if (
            query.expected_observation_index is not None
            and query.expected_observation_index != self.observation_index
        ):
            # A newer observation of the same chain exists before this decision,
            # so this proof no longer describes the chain.
            return DepthStatus.SUPERSEDED
        if query.decision_clock_domain and query.decision_clock_domain == self.clock_domain:
            if query.decision_time < self.observed_at:
                return DepthStatus.FUTURE_OBSERVATION
            if query.decision_time - self.observed_at > query.max_age_seconds:
                return DepthStatus.STALE_OBSERVATION
        # Cross-domain timestamps are not comparable; the ordering checks above
        # are the binding ones in that case.
        if not self.identity_verified:
            return DepthStatus.IDENTITY_UNVERIFIED
        return None

    def depth_of(
        self, query: DepthQuery, block_id: int, content_hash: str
    ) -> tuple[int | None, DepthStatus]:
        """Depth of one slot, validated against identity, freshness and content."""

        status = self.status_for(query)
        if status is not None:
            return None, status
        try:
            index = self.block_ids.index(block_id)
        except ValueError:
            return None, DepthStatus.UNKNOWN_BLOCK
        if self.content_hashes[index] != content_hash:
            return None, DepthStatus.CONTENT_MISMATCH
        return self.depths[index], DepthStatus.OK

    def resolve(
        self,
        query: DepthQuery,
        victim_block_ids: Sequence[int],
        live_hashes: Mapping[int, str] | None = None,
    ) -> DepthResolution:
        """Resolve a victim set, splitting resolved from unresolvable blocks.

        ``live_hashes`` is what the slots hold **now**. Passing it is mandatory in
        :attr:`DepthVerificationMode.NATIVE_LIVE`, because a block id can be
        recycled after the snapshot and the old chain may never produce another
        observation -- so the recorded hash would then describe content that is no
        longer there. A missing live hash is
        :attr:`DepthStatus.LIVE_IDENTITY_REQUIRED`, never a reason to substitute
        the recorded one.

        In :attr:`DepthVerificationMode.HISTORICAL_REPLAY` a missing ``live_hashes``
        falls back to the recorded identity, which is sound for replay, and the
        result is flagged ``live_identity_checked = False`` so it cannot be
        reported as native content verification.
        """

        status = self.status_for(query)
        if status is not None:
            return DepthResolution({}, {int(b): status for b in victim_block_ids})

        if live_hashes is None and query.requires_live_identity:
            return DepthResolution(
                {},
                {int(b): DepthStatus.LIVE_IDENTITY_REQUIRED for b in victim_block_ids},
            )

        depths: dict[int, int] = {}
        failures: dict[int, DepthStatus] = {}
        for raw_block_id in victim_block_ids:
            block_id = int(raw_block_id)
            try:
                index = self.block_ids.index(block_id)
            except ValueError:
                failures[block_id] = DepthStatus.UNKNOWN_BLOCK
                continue
            if live_hashes is None:
                depth = self.depths[index]
            else:
                live = live_hashes.get(block_id)
                if live is None:
                    failures[block_id] = DepthStatus.LIVE_IDENTITY_REQUIRED
                    continue
                if live != self.content_hashes[index]:
                    failures[block_id] = DepthStatus.CONTENT_MISMATCH
                    continue
                depth = self.depths[index]
            depths[block_id] = depth
        return DepthResolution(depths, failures, live_identity_checked=live_hashes is not None)


@dataclass(slots=True)
class ChainDepthIndex:
    """Observations of chains, answering "the latest valid proof before now".

    The index is append-only and read-only with respect to native state. It never
    derives a depth from an array position; it only stores what was observed.
    """

    _by_chain: dict[tuple[str, str], list[ChainDepthProof]] = field(default_factory=dict)

    def observe(self, proof: ChainDepthProof) -> None:
        chain = self._by_chain.setdefault(proof.chain_id, [])
        if chain and proof.observation_index <= chain[-1].observation_index:
            raise ValueError("observations for a chain must be appended in increasing order")
        chain.append(proof)

    def observe_chain(
        self,
        chain_id: tuple[str, str],
        native_hash_process_id: str,
        block_ids: Sequence[int],
        *,
        content_hashes: Sequence[str] = (),
        observation_index: int,
        observed_at: float,
        clock_domain: str = CLOCK_DOMAIN_UNKNOWN,
    ) -> ChainDepthProof:
        """Convenience wrapper around :meth:`ChainDepthProof.from_observation`."""

        proof = ChainDepthProof.from_observation(
            chain_id,
            native_hash_process_id,
            block_ids,
            content_hashes=content_hashes,
            observation_index=observation_index,
            observed_at=observed_at,
            clock_domain=clock_domain,
        )
        self.observe(proof)
        return proof

    def latest_before(
        self, chain_id: tuple[str, str], decision_index: int
    ) -> ChainDepthProof | None:
        """The most recent observation of ``chain_id`` strictly before the decision."""

        best: ChainDepthProof | None = None
        for proof in self._by_chain.get(chain_id, ()):
            if proof.observation_index >= decision_index:
                # Appended in increasing order, so nothing later can qualify.
                break
            best = proof
        return best

    def chains(self) -> Iterable[tuple[str, str]]:
        return tuple(self._by_chain)

    def query_for(
        self,
        chain_id: tuple[str, str],
        native_hash_process_id: str,
        *,
        decision_index: int,
        decision_time: float,
        decision_clock_domain: str = CLOCK_DOMAIN_UNKNOWN,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        verification_mode: DepthVerificationMode = DepthVerificationMode.HISTORICAL_REPLAY,
    ) -> tuple[ChainDepthProof, DepthQuery] | None:
        """Build a query pinned to the current observation, or ``None`` if there is none.

        Pinning ``expected_observation_index`` is what makes ``SUPERSEDED``
        detectable: a caller holding a stale proof cannot quietly use it.
        """

        proof = self.latest_before(chain_id, decision_index)
        if proof is None:
            return None
        query = DepthQuery(
            chain_id=chain_id,
            native_hash_process_id=native_hash_process_id,
            decision_index=decision_index,
            decision_time=decision_time,
            decision_clock_domain=decision_clock_domain,
            expected_observation_index=proof.observation_index,
            max_age_seconds=max_age_seconds,
            verification_mode=verification_mode,
        )
        return proof, query


def index_from_events(events: Iterable[Mapping[str, object]]) -> ChainDepthIndex:
    """Build an index from raw ``VLLM_PREFIX_SNAPSHOT`` events.

    The snapshot is the project-layer record of a chain observation: ordered
    ``block_ids``, the aligned ``ordered_native_cache_keys``, and the native hash
    process id. Its order **is** the depth ordering at observation time, which is
    the only moment at which position and depth coincide.

    A snapshot whose content keys are missing or misaligned is still recorded,
    but with no content identity, so every lookup on it returns
    ``IDENTITY_UNVERIFIED`` instead of silently trusting a depth.
    """

    index = ChainDepthIndex()
    for event in events:
        if event.get("event_type") != "VLLM_PREFIX_SNAPSHOT":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        block_ids = tuple(int(value) for value in payload.get("block_ids") or ())
        if not block_ids:
            continue
        process_id = str(payload.get("native_hash_process_id") or "")
        if not process_id:
            # Without a native process identity the observation cannot be bound to
            # a runtime, so nothing it says could ever be validated. Dropping it
            # makes every lookup on that chain fall back as NO_OBSERVATION rather
            # than matching some other process by accident.
            continue
        raw_keys = tuple(payload.get("ordered_native_cache_keys") or ())
        content_hashes: tuple[str, ...]
        if len(raw_keys) == len(block_ids):
            content_hashes = tuple(str(value) for value in raw_keys)
        else:
            # Misaligned or absent keys must not be silently paired up.
            content_hashes = ()
        index.observe(
            ChainDepthProof.from_observation(
                (str(event.get("program_id")), str(event.get("prefix_id"))),
                process_id,
                block_ids,
                content_hashes=content_hashes,
                observation_index=int(event.get("event_index") or 0),
                observed_at=float(event.get("timestamp") or 0.0),
                clock_domain=str(event.get("clock_domain") or CLOCK_DOMAIN_UNKNOWN),
            )
        )
    return index
