from __future__ import annotations

import json
import urllib.error

import pytest

from ctld_launcher.core import app_update


def test_asset_name_per_platform() -> None:
    assert app_update.asset_name("Linux") == "ctld-launcher-x86_64.AppImage"
    assert app_update.asset_name("Windows") == "ctld-launcher-Setup.exe"
    assert app_update.asset_name("Darwin") == "ctld-launcher.dmg"
    assert app_update.asset_name("FreeBSD") == ""


def test_is_newer_version_true_when_greater() -> None:
    assert app_update.is_newer_version("0.1.8", "0.1.7") is True


def test_is_newer_version_false_when_equal_or_older() -> None:
    assert app_update.is_newer_version("0.1.7", "0.1.7") is False
    assert app_update.is_newer_version("0.1.6", "0.1.7") is False


def test_is_newer_version_handles_multi_digit_segments() -> None:
    # Plain string comparison would wrongly say "0.1.10" < "0.1.9"
    assert app_update.is_newer_version("0.1.10", "0.1.9") is True


def test_is_newer_version_false_for_unparseable_dev_build() -> None:
    assert app_update.is_newer_version("0.1.dev20+gc16b80a5e", "0.1.7") is False


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_fetch_latest_release_returns_matching_asset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(app_update, "asset_name", lambda: "ctld-launcher-x86_64.AppImage")
    payload = {
        "tag_name": "v0.1.8",
        "assets": [
            {"name": "ctld-launcher-Setup.exe", "browser_download_url": "https://x/exe"},
            {"name": "ctld-launcher-x86_64.AppImage", "browser_download_url": "https://x/appimage"},
        ],
    }
    monkeypatch.setattr(
        app_update.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
    )

    result = app_update.fetch_latest_release()

    assert result == ("0.1.8", "https://x/appimage")


def test_fetch_latest_release_none_when_no_matching_asset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(app_update, "asset_name", lambda: "ctld-launcher-x86_64.AppImage")
    payload = {"tag_name": "v0.1.8", "assets": []}
    monkeypatch.setattr(
        app_update.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
    )

    assert app_update.fetch_latest_release() is None


def test_fetch_latest_release_none_on_network_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def raise_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(app_update.urllib.request, "urlopen", raise_error)

    assert app_update.fetch_latest_release() is None


def test_fetch_latest_release_none_on_malformed_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _BadResponse:
        def read(self) -> bytes:
            return b"not json"

        def __enter__(self) -> _BadResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(app_update.urllib.request, "urlopen", lambda *a, **k: _BadResponse())

    assert app_update.fetch_latest_release() is None


def test_fetch_latest_release_or_raise_propagates_network_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # fetch_latest_release() intentionally swallows this (see tests above) so
    # the silent startup check never bothers the user, but UpdateCheckWorker
    # needs the real reason to report back on a manually-triggered check --
    # this is the underlying function that lets it propagate.
    def raise_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise urllib.error.URLError("no network in tests")

    monkeypatch.setattr(app_update.urllib.request, "urlopen", raise_error)

    with pytest.raises(urllib.error.URLError):
        app_update._fetch_latest_release_or_raise()
