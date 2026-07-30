from __future__ import annotations

import subprocess
import sys

from ctld_launcher import i18n
from ctld_launcher.i18n import (
    _,
    _locale_dir,
    _macos_preferred_language,
    detect_system_language,
    get_language,
    set_language,
)


def test_english_is_identity_by_default() -> None:
    set_language("en")
    assert _("Start") == "Start"
    assert get_language() == "en"


def test_japanese_translation_loads_real_catalog() -> None:
    set_language("ja")
    try:
        assert _("Start") == "起動"
        assert _("Stop") == "停止"
        assert _("Model name") == "機種"
        assert get_language() == "ja"
    finally:
        set_language("en")


def test_format_placeholder_survives_translation() -> None:
    set_language("ja")
    try:
        assert _("✓ Response: {output}").format(output="145000000") == "✓ 応答: 145000000"
    finally:
        set_language("en")


def test_unknown_language_falls_back_to_english() -> None:
    set_language("fr")
    try:
        assert _("Start") == "Start"
        assert get_language() == "en"
    finally:
        set_language("en")


def test_locale_dir_prefers_bundled_over_source_tree(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert _locale_dir() == tmp_path / "locale"


def test_locale_dir_falls_back_to_repo_root_when_not_frozen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert _locale_dir().name == "locale"
    assert (_locale_dir() / "ja" / "LC_MESSAGES" / "ctld_launcher.mo").exists()


def test_macos_preferred_language_parses_defaults_output(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args, 0, stdout='(\n    "ja-JP",\n    "en-US"\n)\n')

    monkeypatch.setattr(i18n.subprocess, "run", fake_run)
    assert _macos_preferred_language() == "ja-JP"


def test_macos_preferred_language_none_when_defaults_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("defaults not found")

    monkeypatch.setattr(i18n.subprocess, "run", fake_run)
    assert _macos_preferred_language() is None


def test_detect_system_language_uses_macos_preference_on_darwin(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_macos_preferred_language", lambda: "ja-JP")
    assert detect_system_language() == "ja"


def test_detect_system_language_falls_back_to_qlocale_when_macos_preference_unknown(  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    from PySide6.QtCore import QLocale

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_macos_preferred_language", lambda: None)

    expected = "ja" if QLocale.system().name().startswith("ja") else "en"
    assert detect_system_language() == expected
