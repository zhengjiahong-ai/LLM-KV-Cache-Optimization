from scripts.spikes.run_continuum_prefill_profile_metal import _MetalPrefillAdapter


class _Native:
    def __init__(self, resident: set[bytes]) -> None:
        self.resident = resident

    def lookup_hash(self, native_hash: bytes) -> bool:
        return native_hash in self.resident


def test_target_presence_tracks_reusable_leading_hash_not_full_chain() -> None:
    adapter = object.__new__(_MetalPrefillAdapter)
    adapter._target_hashes = (b"leading", b"trailing")
    adapter._native = _Native({b"leading"})
    adapter._require_zero_cached_prefix = True

    assert adapter.read_target_material_presence() is True

    adapter._native = _Native({b"trailing"})
    assert adapter.read_target_material_presence() is False
