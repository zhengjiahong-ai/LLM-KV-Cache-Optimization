"""Independent in-memory retention state for the Phase 1B baseline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .clock import Clock
from .selection import RetentionEntryKey
from .snapshots import RetentionEntrySnapshot
from .types import (
    BlockIdentity,
    ProgramIdentity,
    _as_non_negative_finite_float,
    _require_identity,
)


class RetentionManager:
    """Own logical protection and observed edges within one runtime instance.

    Queries return stored state; callers explicitly request lazy expiry.
    Waiting is program-scoped and is cleared by admission, cancellation, or
    terminal cleanup. Physical eviction alone does not end a logical interval.
    """

    def __init__(self, clock: Clock) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        self._clock = clock
        self._entries: dict[RetentionEntryKey, RetentionEntrySnapshot] = {}
        self._reverse: dict[BlockIdentity, set[RetentionEntryKey]] = {}
        self._waiting_programs: set[ProgramIdentity] = set()

    def upsert(self, snapshot: RetentionEntrySnapshot) -> None:
        """Replace one entry and its edges, preserving program-wide waiting.

        A true waiting flag records a waiting program; a false flag cannot
        cancel an already recorded wait. Use the lifecycle methods to end it.
        """
        if not isinstance(snapshot, RetentionEntrySnapshot):
            raise TypeError("snapshot must be RetentionEntrySnapshot")
        key = RetentionEntryKey(snapshot.program_id, snapshot.prefix_id)
        previous = self._entries.get(key)
        if previous is not None:
            self._remove_edges(key, previous)
        if snapshot.waiting_followup:
            self.mark_followup_waiting(snapshot.program_id)
        self._entries[key] = replace(
            snapshot,
            waiting_followup=snapshot.program_id in self._waiting_programs,
        )
        for block_id in snapshot.block_ids:
            self._reverse.setdefault(block_id, set()).add(key)

    def snapshot(self, key: RetentionEntryKey) -> RetentionEntrySnapshot | None:
        _require_identity(key, RetentionEntryKey, "key")
        return self._entries.get(key)

    def planning_snapshots(self) -> tuple[RetentionEntrySnapshot, ...]:
        """Return an immutable snapshot of all entries for read-only planning."""
        return tuple(
            self._entries[key]
            for key in sorted(self._entries, key=lambda item: item.sort_key)
        )

    def entries_for_block(self, block_id: BlockIdentity) -> tuple[RetentionEntryKey, ...]:
        _require_identity(block_id, BlockIdentity, "block_id")
        return tuple(sorted(self._reverse.get(block_id, ()), key=lambda key: key.sort_key))

    def is_block_protected(self, block_id: BlockIdentity) -> bool:
        return any(self._entries[key].protected for key in self.entries_for_block(block_id))

    def expire_due(self) -> None:
        now = _as_non_negative_finite_float(self._clock.now(), "clock timestamp")
        for key, entry in self._entries.items():
            if (
                entry.protected
                and entry.program_id not in self._waiting_programs
                and entry.deadline_timestamp <= now
            ):
                self._entries[key] = replace(entry, protected=False)

    def mark_followup_waiting(self, program_id: ProgramIdentity) -> None:
        _require_identity(program_id, ProgramIdentity, "program_id")
        self._waiting_programs.add(program_id)
        for key, entry in self._entries.items():
            if entry.program_id == program_id:
                self._entries[key] = replace(entry, waiting_followup=True)

    def cancel_followup(self, program_id: ProgramIdentity) -> None:
        """Clear waiting and immediately check that program's deadlines."""
        _require_identity(program_id, ProgramIdentity, "program_id")
        now = _as_non_negative_finite_float(self._clock.now(), "clock timestamp")
        self._waiting_programs.discard(program_id)
        for key, entry in self._entries.items():
            if entry.program_id == program_id:
                self._entries[key] = replace(
                    entry,
                    waiting_followup=False,
                    protected=entry.protected and entry.deadline_timestamp > now,
                )

    def admit_followup(self, program_id: ProgramIdentity) -> None:
        """End the program's prior idle protection, retaining observed edges."""
        _require_identity(program_id, ProgramIdentity, "program_id")
        self._waiting_programs.discard(program_id)
        for key, entry in self._entries.items():
            if entry.program_id == program_id:
                self._entries[key] = replace(entry, protected=False, waiting_followup=False)

    def complete_program(self, program_id: ProgramIdentity) -> None:
        _require_identity(program_id, ProgramIdentity, "program_id")
        keys = [key for key in self._entries if key.program_id == program_id]
        for key in keys:
            self._remove_edges(key, self._entries.pop(key))
        self._waiting_programs.discard(program_id)

    def commit_pressure_releases(
        self, keys: Sequence[RetentionEntryKey]
    ) -> None:
        """End logical protection for validated pressure or expiry releases."""
        if isinstance(keys, (str, bytes)) or not isinstance(keys, Sequence):
            raise TypeError("keys must be an ordered sequence")
        normalized = tuple(keys)
        for key in normalized:
            _require_identity(key, RetentionEntryKey, "keys item")
        if len(normalized) != len(set(normalized)):
            raise ValueError("keys must not contain duplicates")
        for key in normalized:
            if key not in self._entries:
                raise KeyError(key)
        for key in normalized:
            entry = self._entries[key]
            if entry.protected:
                self._entries[key] = replace(entry, protected=False)

    def observe_eviction(self, block_id: BlockIdentity) -> None:
        """Remove every edge for an explicitly observed native eviction."""
        _require_identity(block_id, BlockIdentity, "block_id")
        for key in self._reverse.pop(block_id, ()):
            entry = self._entries[key]
            self._entries[key] = replace(
                entry, block_ids=tuple(block for block in entry.block_ids if block != block_id)
            )

    def _remove_edges(
        self, key: RetentionEntryKey, entry: RetentionEntrySnapshot
    ) -> None:
        for block_id in entry.block_ids:
            owners = self._reverse[block_id]
            owners.remove(key)
            if not owners:
                del self._reverse[block_id]
