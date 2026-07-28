"""Locates the rigctld/rotctld/rigctl/rotctl executables to launch.

When packaged (PyInstaller, see scripts/ctld-launcher.spec), the
hamlib-bundle release (rigctld/rotctld/rigctl/rotctl + libhamlib + the
Python bindings) ships inside the app under a "hamlib/" subdirectory and
is preferred over anything on PATH, so the packaged app works without
Hamlib installed system-wide. Falls back to PATH search for unpackaged/
dev runs (or if the packaged bundle is somehow missing).

TODO: for unpackaged/dev runs with nothing on PATH either, consider
auto-downloading the hamlib-bundle release into the platformdirs user
data dir, the way FBSAT59's "Help > Hamlib Update" flow does.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ctld_launcher.core.profile import ProfileKind

_DAEMON_NAME = {
    ProfileKind.RIG: "rigctld",
    ProfileKind.ROTATOR: "rotctld",
}
_TEST_TOOL_NAME = {
    ProfileKind.RIG: "rigctl",
    ProfileKind.ROTATOR: "rotctl",
}


class ExecutableNotFoundError(Exception):
    """Raised when a Hamlib executable cannot be located."""


def bundled_hamlib_dir() -> Path | None:
    """Directory containing the PyInstaller-bundled hamlib-bundle, if any.

    sys._MEIPASS is set by PyInstaller's bootloader (both onefile and
    onedir builds) to the bundle's extraction/data root — the standard,
    documented way to locate bundled data files at runtime.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is None:
        return None
    candidate = Path(meipass) / "hamlib"
    return candidate if candidate.is_dir() else None


def _find(name: str) -> str:
    if sys.platform == "win32":
        name += ".exe"

    bundled_dir = bundled_hamlib_dir()
    if bundled_dir is not None:
        candidate = bundled_dir / name
        if candidate.exists():
            return str(candidate)

    path = shutil.which(name)
    if path is None:
        raise ExecutableNotFoundError(f"{name} not found (bundled or on PATH)")
    return path


def find_executable(kind: ProfileKind) -> str:
    """Resolve rigctld/rotctld — the long-running network daemon."""
    return _find(_DAEMON_NAME[kind])


def find_test_executable(kind: ProfileKind) -> str:
    """Resolve rigctl/rotctl — the one-shot CLI tool used for connection tests."""
    return _find(_TEST_TOOL_NAME[kind])
