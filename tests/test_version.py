from __future__ import annotations

import subprocess
import sys

from ctld_launcher import version as version_module


def test_get_version_prefers_frozen_bundle(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "version.txt").write_text("1.2.3", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert version_module.get_version() == "1.2.3"


def test_get_version_frozen_bundle_missing_file_falls_through(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(version_module, "_from_git_describe", lambda: None)
    monkeypatch.setattr(version_module, "_from_installed_metadata", lambda: None)

    assert version_module.get_version() == version_module._FALLBACK_VERSION


def test_git_describe_parses_exact_tag(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args, 0, stdout="v0.1.3-0-gf1dd166\n")

    monkeypatch.setattr(version_module.subprocess, "run", fake_run)

    assert version_module._from_git_describe() == "0.1.3"


def test_git_describe_parses_commits_since_tag(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args, 0, stdout="v0.1.3-4-gf1dd166\n")

    monkeypatch.setattr(version_module.subprocess, "run", fake_run)

    assert version_module._from_git_describe() == "0.1.3.dev4"


def test_git_describe_returns_none_when_git_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(version_module.subprocess, "run", fake_run)

    assert version_module._from_git_describe() is None


def test_installed_metadata_strips_local_version_segment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        version_module, "_installed_version", lambda _name: "0.1.dev20+gc16b80a5e.d20260728"
    )

    assert version_module._from_installed_metadata() == "0.1.dev20"


def test_get_version_falls_back_to_hardcoded_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(version_module, "_from_git_describe", lambda: None)
    monkeypatch.setattr(version_module, "_from_installed_metadata", lambda: None)

    assert version_module.get_version() == version_module._FALLBACK_VERSION
