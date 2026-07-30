from __future__ import annotations

import sys

import pytest

from ctld_launcher.core.hamlib_locator import (
    ExecutableNotFoundError,
    bundled_hamlib_dir,
    bundled_hamlib_version,
    find_executable,
    find_test_executable,
)
from ctld_launcher.core.profile import ProfileKind


def test_bundled_hamlib_dir_none_when_not_frozen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert bundled_hamlib_dir() is None


def test_bundled_hamlib_dir_none_when_hamlib_subdir_missing(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_hamlib_dir() is None


def test_bundled_hamlib_dir_found(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hamlib_dir = tmp_path / "hamlib"
    hamlib_dir.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_hamlib_dir() == hamlib_dir


def test_find_executable_prefers_bundled_over_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hamlib_dir = tmp_path / "hamlib"
    hamlib_dir.mkdir()
    bundled_rigctld = hamlib_dir / "rigctld"
    bundled_rigctld.write_text("")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/should/not/be/used")

    assert find_executable(ProfileKind.RIG) == str(bundled_rigctld)


def test_find_executable_falls_back_to_path_when_not_bundled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    assert find_executable(ProfileKind.ROTATOR) == "/usr/bin/rotctld"


def test_find_executable_raises_when_not_found_anywhere(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ExecutableNotFoundError):
        find_executable(ProfileKind.RIG)


def test_find_executable_appends_exe_suffix_on_windows(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "platform", "win32")
    hamlib_dir = tmp_path / "hamlib"
    hamlib_dir.mkdir()
    (hamlib_dir / "rigctld.exe").write_text("")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert find_executable(ProfileKind.RIG) == str(hamlib_dir / "rigctld.exe")


def test_find_test_executable_resolves_rigctl_and_rotctl(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    assert find_test_executable(ProfileKind.RIG) == "/usr/bin/rigctl"
    assert find_test_executable(ProfileKind.ROTATOR) == "/usr/bin/rotctl"


def test_bundled_hamlib_version_none_when_not_frozen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert bundled_hamlib_version() is None


def test_bundled_hamlib_version_none_when_version_file_missing(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hamlib_dir = tmp_path / "hamlib"
    hamlib_dir.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_hamlib_version() is None


def test_bundled_hamlib_version_reads_file(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hamlib_dir = tmp_path / "hamlib"
    hamlib_dir.mkdir()
    (hamlib_dir / "version.txt").write_text("4.7.1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_hamlib_version() == "4.7.1"
