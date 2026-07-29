"""Internationalization (i18n) foundation module.

Translation system based on Python's standard gettext. Source strings in
the codebase are written in English; locale/<lang>/LC_MESSAGES/
ctld_launcher.po provides translations (compiled to .mo with msgfmt). To
add a language, add a new locale/<lang>/ directory and translate
locale/ctld_launcher.pot.

Usage:
    from ctld_launcher.i18n import _, set_language, detect_system_language

    set_language(detect_system_language())
    print(_("Start"))  # -> translated string

set_language() must run before any UI widget is built (module-level
string *lists* in ui/main_window.py are built lazily inside methods for
exactly this reason — see e.g. _debug_levels()), since _() looks up the
current translation each time it's called, not once at import time.
"""

from __future__ import annotations

import gettext
import sys
import threading
from pathlib import Path

_DOMAIN = "ctld_launcher"

_lock = threading.Lock()
_current_lang: str = "en"
_translation: gettext.NullTranslations = gettext.NullTranslations()


def _locale_dir() -> Path:
    """locale/ directory: bundled next to the app when frozen (PyInstaller
    sets sys._MEIPASS — see core/hamlib_locator.py's bundled_hamlib_dir()
    for the same pattern), otherwise the repo-root locale/ in a source
    checkout.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass) / "locale"
    return Path(__file__).resolve().parent.parent.parent / "locale"


def _(message: str) -> str:
    """Translate a message to the current language."""
    return _translation.gettext(message)


def set_language(lang: str) -> None:
    """Change the active language ("en" or a locale/ subdirectory name like
    "ja"). Falls back to English (identity transform) if no matching .mo
    file exists.
    """
    global _translation, _current_lang

    with _lock:
        if lang == "en":
            _translation = gettext.NullTranslations()
            _current_lang = "en"
            return

        translation: gettext.NullTranslations
        try:
            translation = gettext.translation(
                _DOMAIN, localedir=str(_locale_dir()), languages=[lang]
            )
        except FileNotFoundError:
            translation = gettext.NullTranslations()
            lang = "en"

        _translation = translation
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def detect_system_language() -> str:
    """Only Japanese is currently translated (see locale/ja/); everything
    else falls back to the English source strings.
    """
    from PySide6.QtCore import QLocale

    if QLocale.system().name().startswith("ja"):
        return "ja"
    return "en"
