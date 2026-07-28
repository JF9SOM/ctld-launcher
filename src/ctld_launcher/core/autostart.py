"""Registers/unregisters ctld-launcher to start automatically at login.

v1 scope only: user-level autostart, no admin/root elevation.
  - Linux: a systemd --user unit, enabled without --now (so toggling this
    on while the app is already running doesn't spawn a second instance;
    it takes effect on the next login).
  - macOS: a LaunchAgent plist in ~/Library/LaunchAgents. Deliberately not
    calling `launchctl load` for the same reason — launchd picks up
    LaunchAgents at the next login on its own.
  - Windows: a HKEY_CURRENT_USER...\\Run registry value (no admin rights
    needed, unlike HKEY_LOCAL_MACHINE).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

APP_NAME = "ctld-launcher"
LINUX_UNIT_NAME = f"{APP_NAME}.service"
MACOS_LABEL = f"com.jf9som.{APP_NAME}"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartError(Exception):
    """Raised when enabling/disabling autostart fails."""


class AutostartBackend(Protocol):
    """Structural type satisfied by this module itself — lets MainWindow
    accept a fake backend in tests instead of touching the real OS state.
    """

    def is_supported(self) -> bool: ...
    def is_enabled(self) -> bool: ...
    def enable(self, command: list[str] | None = None) -> None: ...
    def disable(self) -> None: ...


def default_command() -> list[str]:
    """Best-effort command to relaunch this app.

    Prefers the installed `ctld-launcher` console script; falls back to
    `python -m ctld_launcher` for unpackaged/dev runs. Packaging (AppImage/
    .exe/.app, step 7) should pass the final bundled binary path explicitly
    to enable() instead of relying on this default.
    """
    exe = shutil.which(APP_NAME)
    if exe:
        return [exe]
    return [sys.executable, "-m", "ctld_launcher"]


def is_supported() -> bool:
    return sys.platform in ("linux", "darwin", "win32")


def is_enabled() -> bool:
    if sys.platform == "linux":
        return _linux_is_enabled()
    if sys.platform == "darwin":
        return _macos_is_enabled()
    if sys.platform == "win32":
        return _windows_is_enabled()
    return False


def enable(command: list[str] | None = None) -> None:
    command = command or default_command()
    if sys.platform == "linux":
        _linux_enable(command)
    elif sys.platform == "darwin":
        _macos_enable(command)
    elif sys.platform == "win32":
        _windows_enable(command)
    else:
        raise AutostartError(f"autostart is not supported on {sys.platform}")


def disable() -> None:
    if sys.platform == "linux":
        _linux_disable()
    elif sys.platform == "darwin":
        _macos_disable()
    elif sys.platform == "win32":
        _windows_disable()
    else:
        raise AutostartError(f"autostart is not supported on {sys.platform}")


# ---------------------------------------------------------------------------
# Linux: systemd --user
# ---------------------------------------------------------------------------
def _linux_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / LINUX_UNIT_NAME


def _linux_exec_start(command: list[str]) -> str:
    return " ".join(f'"{arg}"' if " " in arg else arg for arg in command)


def _linux_enable(command: list[str]) -> None:
    unit_path = _linux_unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(
        "[Unit]\n"
        "Description=ctld-launcher\n\n"
        "[Service]\n"
        f"ExecStart={_linux_exec_start(command)}\n"
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(  # noqa: S603
            ["systemctl", "--user", "daemon-reload"], check=True, capture_output=True
        )
        subprocess.run(  # noqa: S603
            ["systemctl", "--user", "enable", LINUX_UNIT_NAME], check=True, capture_output=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AutostartError(f"systemctl failed: {exc}") from exc


def _linux_disable() -> None:
    try:
        subprocess.run(  # noqa: S603
            ["systemctl", "--user", "disable", LINUX_UNIT_NAME], capture_output=True
        )
    except OSError as exc:
        raise AutostartError(f"systemctl failed: {exc}") from exc
    _linux_unit_path().unlink(missing_ok=True)


def _linux_is_enabled() -> bool:
    try:
        result = subprocess.run(  # noqa: S603
            ["systemctl", "--user", "is-enabled", LINUX_UNIT_NAME],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.stdout.strip() == "enabled"


# ---------------------------------------------------------------------------
# macOS: LaunchAgent
# ---------------------------------------------------------------------------
def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"


def _macos_enable(command: list[str]) -> None:
    import plistlib

    plist_path = _macos_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as fh:
        plistlib.dump({"Label": MACOS_LABEL, "ProgramArguments": command, "RunAtLoad": True}, fh)


def _macos_disable() -> None:
    _macos_plist_path().unlink(missing_ok=True)


def _macos_is_enabled() -> bool:
    return _macos_plist_path().exists()


# ---------------------------------------------------------------------------
# Windows: HKCU Run key
# ---------------------------------------------------------------------------
def _windows_enable(command: list[str]) -> None:
    if sys.platform == "win32":
        import winreg

        command_str = subprocess.list2cmdline(command)
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command_str)
        except OSError as exc:
            raise AutostartError(f"registry write failed: {exc}") from exc


def _windows_disable() -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise AutostartError(f"registry delete failed: {exc}") from exc


def _windows_is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False
    return False
