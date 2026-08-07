from __future__ import annotations

import uuid

from ctld_launcher.core.single_instance import SingleInstanceGuard


def _unique_key() -> str:
    return f"test-ctld-launcher-{uuid.uuid4().hex}"


def test_first_guard_acquires_lock(qapp) -> None:  # type: ignore[no-untyped-def]
    guard = SingleInstanceGuard(key=_unique_key())
    assert guard.try_acquire() is True


def test_second_guard_with_same_key_fails_to_acquire(qapp) -> None:  # type: ignore[no-untyped-def]
    key = _unique_key()
    first = SingleInstanceGuard(key=key)
    second = SingleInstanceGuard(key=key)

    assert first.try_acquire() is True
    assert second.try_acquire() is False


def test_guard_can_be_reacquired_after_release(qapp) -> None:  # type: ignore[no-untyped-def]
    key = _unique_key()
    first = SingleInstanceGuard(key=key)
    assert first.try_acquire() is True

    first.close()

    second = SingleInstanceGuard(key=key)
    assert second.try_acquire() is True
