from __future__ import annotations

import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest

from ctld_launcher.core import autostart


def _systemd_user_available() -> bool:
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["systemctl", "--user", "status"], capture_output=True, timeout=5
        )
    except OSError:
        return False
    return result.returncode == 0


@pytest.mark.skipif(
    sys.platform != "linux" or not _systemd_user_available(),
    reason="requires a real systemd --user session",
)
def test_linux_enable_disable_real_systemd() -> None:
    assert autostart.is_enabled() is False
    try:
        autostart.enable(["/usr/bin/true"])
        assert autostart.is_enabled() is True
        unit_path = autostart._linux_unit_path()
        assert unit_path.exists()
        assert "ExecStart=/usr/bin/true" in unit_path.read_text()
    finally:
        autostart.disable()
    assert autostart.is_enabled() is False
    assert not autostart._linux_unit_path().exists()


def test_macos_enable_disable_plist(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    plist_path = tmp_path / f"{autostart.MACOS_LABEL}.plist"
    monkeypatch.setattr(autostart, "_macos_plist_path", lambda: plist_path)

    assert autostart._macos_is_enabled() is False
    autostart._macos_enable(["/Applications/ctld-launcher.app/Contents/MacOS/ctld-launcher"])
    assert autostart._macos_is_enabled() is True

    import plistlib

    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == autostart.MACOS_LABEL
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"] == [
        "/Applications/ctld-launcher.app/Contents/MacOS/ctld-launcher"
    ]

    autostart._macos_disable()
    assert autostart._macos_is_enabled() is False


def test_windows_enable_disable_registry(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "platform", "win32")

    stored: dict[str, str] = {}

    def fake_set_value_ex(key: object, name: str, reserved: int, type_: int, value: str) -> None:
        stored[name] = value

    def fake_query_value_ex(key: object, name: str) -> tuple[str, int]:
        if name not in stored:
            raise FileNotFoundError(name)
        return stored[name], 1

    def fake_delete_value(key: object, name: str) -> None:
        if name not in stored:
            raise FileNotFoundError(name)
        del stored[name]

    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_SET_VALUE=1,
        KEY_READ=1,
        REG_SZ=1,
        CreateKeyEx=MagicMock(return_value=MagicMock()),
        OpenKey=MagicMock(return_value=MagicMock()),
        SetValueEx=fake_set_value_ex,
        QueryValueEx=fake_query_value_ex,
        DeleteValue=fake_delete_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert autostart._windows_is_enabled() is False
    autostart._windows_enable(["C:\\Program Files\\ctld-launcher\\ctld-launcher.exe"])
    assert stored[autostart.APP_NAME] == '"C:\\Program Files\\ctld-launcher\\ctld-launcher.exe"'
    assert autostart._windows_is_enabled() is True

    autostart._windows_disable()
    assert autostart.APP_NAME not in stored
    assert autostart._windows_is_enabled() is False


def test_default_command_falls_back_to_module_invocation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(autostart.shutil, "which", lambda _name: None)
    command = autostart.default_command()
    assert command == [sys.executable, "-m", "ctld_launcher", autostart.MINIMIZED_FLAG]


def test_default_command_uses_installed_script_when_found(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(autostart.shutil, "which", lambda _name: "/usr/bin/ctld-launcher")
    command = autostart.default_command()
    assert command == ["/usr/bin/ctld-launcher", autostart.MINIMIZED_FLAG]
