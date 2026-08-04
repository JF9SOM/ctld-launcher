"""Checks GitHub Releases for a newer ctld-launcher version and, on user
confirmation, downloads and installs it.

Adapted from the sibling FBSAT59 project's proven `ui/app_update_dialog.py`
(same GitHub-Releases-API check, same per-platform install strategy),
which has shipped working self-updates for AppImage/NSIS/dmg builds.

This module only concerns ctld-launcher's own version — the bundled
Hamlib's version is tracked separately (see CLAUDE.md's two-stage
Hamlib-version design: a scheduled CI check builds and flags new Hamlib
releases, but a human decides when to actually adopt one).
"""

from __future__ import annotations

import json
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Literal

import certifi
from PySide6.QtCore import QThread, Signal

GITHUB_API = "https://api.github.com/repos/JF9SOM/ctld-launcher/releases/latest"
GITHUB_RELEASES = "https://github.com/JF9SOM/ctld-launcher/releases"

# Frozen macOS builds don't reliably have a system CA bundle Python's ssl
# module can find on its own (confirmed on real hardware: urlopen() raised
# "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate" with
# working internet) -- python.org/PyInstaller builds skip the "Install
# Certificates.command" step that normally sets this up. Installing an
# opener with an explicit certifi CA bundle fixes both urlopen() below and
# urlretrieve() in UpdateInstallWorker (which has no context= parameter of
# its own to pass this to), independent of whatever the host OS has.
urllib.request.install_opener(
    urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))
    )
)

# What the installer left the caller needing to do, so the UI can pick the
# right restart wording (see core docstring above and CLAUDE.md): Linux/
# macOS finish the file swap themselves and can restart immediately;
# Windows hands off to a separately-launched NSIS installer that needs the
# app to close before it can overwrite locked files.
InstallOutcome = Literal["restart_ready", "installer_launched"]


def asset_name(os_name: str | None = None) -> str:
    """Expected release asset filename for the given (or current) platform."""
    os_name = os_name or platform.system()
    if os_name == "Linux":
        return "ctld-launcher-x86_64.AppImage"
    if os_name == "Windows":
        return "ctld-launcher-Setup.exe"
    if os_name == "Darwin":
        return "ctld-launcher.dmg"
    return ""


def is_newer_version(latest: str, current: str) -> bool:
    """Compare dotted numeric version strings (e.g. "0.1.8" > "0.1.7").

    Falls back to a plain inequality check for anything that doesn't parse
    as dotted integers (dev builds like "0.1.dev20+gc16b80a5e") — never
    prompts to "update" to something that isn't a clean newer release.
    """
    try:
        latest_parts = tuple(int(p) for p in latest.split("."))
        current_parts = tuple(int(p) for p in current.split("."))
    except ValueError:
        return False
    return latest_parts > current_parts


def _fetch_latest_release_or_raise(timeout: float = 10) -> tuple[str, str] | None:
    """Same contract as fetch_latest_release() below, but lets network/parse
    errors propagate instead of swallowing them, so UpdateCheckWorker can
    report *why* a manually-triggered check failed instead of just "no".
    """
    req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "ctld-launcher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read())

    tag = str(data.get("tag_name", "")).lstrip("v")
    raw_assets = data.get("assets")
    assets = [a for a in raw_assets if isinstance(a, dict)] if isinstance(raw_assets, list) else []

    target = asset_name()
    for asset in assets:
        if str(asset.get("name", "")) == target:
            url = str(asset.get("browser_download_url", ""))
            return (tag, url) if tag and url else None
    return None


def fetch_latest_release(timeout: float = 10) -> tuple[str, str] | None:
    """Latest (version, download_url) from GitHub Releases, or None on any
    failure (network error, no matching asset for this platform, malformed
    response, ...) — a failed check must never crash or block the app.
    """
    try:
        return _fetch_latest_release_or_raise(timeout)
    except (OSError, ValueError):
        return None


def _current_macos_app_dir() -> Path:
    """Directory containing the currently running .app bundle, so the
    update installs back to wherever the user actually put it (could be
    outside /Applications) instead of assuming a fixed location.
    """
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent.parent
    return Path("/Applications")


class UpdateCheckWorker(QThread):
    """Runs the GitHub Releases check off the GUI thread."""

    result = Signal(str, str)  # latest_version, download_url
    not_found = Signal(str)  # reason (empty string if simply no matching asset)

    def run(self) -> None:
        try:
            found = _fetch_latest_release_or_raise()
        except (OSError, ValueError) as exc:
            self.not_found.emit(str(exc))
            return
        if found is None:
            self.not_found.emit("")
            return
        version, url = found
        self.result.emit(version, url)


class UpdateInstallWorker(QThread):
    """Downloads the release asset and installs it for the current platform."""

    progress = Signal(str)
    finished = Signal(bool, str, str)  # success, outcome_or_error, message

    def __init__(self, url: str, version: str) -> None:
        super().__init__()
        self._url = url
        self._version = version

    def run(self) -> None:
        try:
            fname = self._url.split("/")[-1]
            tmp_dir = Path(tempfile.mkdtemp(prefix="ctld-launcher-update-"))
            tmp_path = tmp_dir / fname

            self.progress.emit(f"Downloading {fname}…")
            urllib.request.urlretrieve(self._url, tmp_path, reporthook=self._reporthook)  # noqa: S310

            self.progress.emit("Preparing installation…")
            os_name = platform.system()
            if os_name == "Windows":
                self._install_windows(tmp_path)
            elif os_name == "Linux":
                self._install_linux(tmp_path)
            elif os_name == "Darwin":
                self._install_macos(tmp_path)
            else:
                raise RuntimeError(f"Unsupported platform: {os_name}")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            self.finished.emit(False, "", str(exc))

    def _reporthook(self, count: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            pct = min(100, int(count * block_size * 100 / total_size))
            self.progress.emit(f"Downloading… {pct}%")

    def _install_windows(self, setup_exe: Path) -> None:
        """Launch the NSIS installer with UAC elevation via ShellExecute.

        subprocess.Popen cannot trigger the UAC prompt and would be denied
        when the installer tries to write to Program Files. Deliberately
        not passing /S (silent) — the UAC dialog and installer UI should
        stay visible, matching FBSAT59's own installer flow.
        """
        import ctypes

        ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", str(setup_exe), None, None, 1
        )
        self.finished.emit(True, "installer_launched", "")

    def _install_linux(self, appimage: Path) -> None:
        """Replace the running AppImage in place (Linux allows this while
        the old file is still executing — the running process keeps using
        the old inode until it exits; the next launch picks up the new
        file). Atomic: copy beside the target, then rename over it.
        """
        current = Path(sys.executable)
        if not getattr(sys, "frozen", False):
            raise RuntimeError(
                "Auto-update is only supported in the AppImage bundle. "
                "Please download the new version manually."
            )
        appimage.chmod(0o755)
        tmp_target = current.with_suffix(".new")
        shutil.copy2(appimage, tmp_target)
        tmp_target.rename(current)
        self.finished.emit(True, "restart_ready", "")

    def _install_macos(self, dmg: Path) -> None:
        mount_point = Path(tempfile.mkdtemp(prefix="ctld-launcher-dmg-"))
        self.progress.emit("Mounting disk image…")
        subprocess.run(  # noqa: S603, S607
            ["hdiutil", "attach", str(dmg), "-mountpoint", str(mount_point), "-nobrowse"],
            check=True,
        )
        try:
            apps = list(mount_point.glob("*.app"))
            if not apps:
                raise RuntimeError("No .app bundle found in the disk image.")
            src_app = apps[0]
            dest_app = _current_macos_app_dir() / src_app.name
            self.progress.emit(f"Installing {src_app.name}…")
            if dest_app.exists():
                shutil.rmtree(dest_app)
            shutil.copytree(src_app, dest_app)
        finally:
            subprocess.run(  # noqa: S603, S607
                ["hdiutil", "detach", str(mount_point)], check=False
            )
        self.finished.emit(True, "restart_ready", "")
