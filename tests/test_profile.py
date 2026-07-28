from __future__ import annotations

from ctld_launcher.core.profile import Profile, ProfileKind, ProfileStore


def test_profile_round_trip_dict() -> None:
    profile = Profile(name="IC-9700", kind=ProfileKind.RIG, model_id=3081, port="/dev/ttyUSB0")
    restored = Profile.from_dict(profile.to_dict())
    assert restored == profile


def test_new_rig_and_new_rotator_defaults() -> None:
    rig = Profile.new_rig("IC-9700 Main", model_id=3081, port="/dev/ttyUSB0")
    rotator = Profile.new_rotator("SPID", model_id=901, port="/dev/ttyUSB1")
    assert rig.kind == ProfileKind.RIG
    assert rig.listen_port == 4532
    assert rotator.kind == ProfileKind.ROTATOR
    assert rotator.listen_port == 4533


def test_profile_store_save_and_load(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "profiles.json")
    profiles = [
        Profile.new_rig("IC-9700 Main", model_id=3081, port="/dev/ttyUSB0"),
        Profile.new_rotator("SPID", model_id=901, port="/dev/ttyUSB1"),
    ]
    store.save(profiles)
    assert store.load() == profiles


def test_profile_store_load_missing_file_returns_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "missing.json")
    assert store.load() == []
