"""Application version string, shown in the UI and window title.

Resolution order (same pattern as the sibling FBSAT59 project):
  1. version.txt bundled by PyInstaller — written by build-release.yml from
     the pushed git tag before pyinstaller runs, read back via sys._MEIPASS
     (the frozen-bundle data root; see hamlib_locator.py/i18n.py for the
     same pattern). This is the path real end-user installs take.
  2. `git describe` — accurate for a source/dev checkout.
  3. importlib.metadata — accurate for a `pip install`, editable or not.
  4. Hardcoded fallback so the app never crashes over a missing version.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path

_FALLBACK_VERSION = "0.0.0-dev"


def _from_frozen_bundle() -> str | None:
    if not getattr(sys, "frozen", False):
        return None
    version_file = Path(getattr(sys, "_MEIPASS", "")) / "version.txt"
    try:
        text = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _from_git_describe() -> str | None:
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "describe", "--tags", "--long"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # "v0.1.3-4-gf1dd166" -> tag "0.1.3", 4 commits since
    parts = result.stdout.strip().split("-")
    if len(parts) < 3:
        return None
    tag = "-".join(parts[:-2]).lstrip("v")
    try:
        count = int(parts[-2])
    except ValueError:
        return None
    return tag if count == 0 else f"{tag}.dev{count}"


def _from_installed_metadata() -> str | None:
    try:
        ver = _installed_version("ctld-launcher")
    except PackageNotFoundError:
        return None
    return ver.split("+")[0]


def get_version() -> str:
    for resolver in (_from_frozen_bundle, _from_git_describe, _from_installed_metadata):
        version = resolver()
        if version:
            return version
    return _FALLBACK_VERSION
