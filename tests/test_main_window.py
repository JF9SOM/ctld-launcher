from __future__ import annotations

import stat
from pathlib import Path

from ctld_launcher.core.profile import ProfileKind, ProfileStore
from ctld_launcher.ui.main_window import MainWindow

FAKE_CTLD = Path(__file__).parent / "_fake_ctld.py"
FAKE_RIGCTL = Path(__file__).parent / "_fake_rigctl.py"


def _fake_resolver(kind: ProfileKind) -> str:
    return "rigctld" if kind == ProfileKind.RIG else "rotctld"


def _fake_test_resolver(kind: ProfileKind) -> str:
    return "rigctl" if kind == ProfileKind.RIG else "rotctl"


class FakeAutostartBackend:
    def __init__(self, supported: bool = True, enabled: bool = False) -> None:
        self.supported = supported
        self.enabled = enabled
        self.enable_calls = 0
        self.disable_calls = 0

    def is_supported(self) -> bool:
        return self.supported

    def is_enabled(self) -> bool:
        return self.enabled

    def enable(self, command: list[str] | None = None) -> None:
        self.enable_calls += 1
        self.enabled = True

    def disable(self) -> None:
        self.disable_calls += 1
        self.enabled = False


def _make_window(  # type: ignore[no-untyped-def]
    tmp_path,
    qtbot,
    autostart_backend=None,
    executable_resolver=_fake_resolver,
    test_executable_resolver=_fake_test_resolver,
) -> MainWindow:
    store = ProfileStore(path=tmp_path / "profiles.json")
    kwargs = {} if autostart_backend is None else {"autostart_backend": autostart_backend}
    window = MainWindow(
        store=store,
        executable_resolver=executable_resolver,
        test_executable_resolver=test_executable_resolver,
        **kwargs,
    )
    qtbot.addWidget(window)
    return window


def test_main_window_title(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    assert window.windowTitle() == "ctld-launcher"


def test_add_rig_profile_appears_in_list_and_store(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    assert len(window.profiles) == 1
    assert window.profiles[0].kind == ProfileKind.RIG
    assert window._list.count() == 1

    store = ProfileStore(path=tmp_path / "profiles.json")
    assert len(store.load()) == 1


def test_selecting_profile_populates_form_and_command_preview(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]

    assert window._name_edit.text() == profile.name
    assert "rigctld" in window._command_preview.text()
    assert f"-m {profile.model_id}" in window._command_preview.text()


def test_editing_field_updates_profile_and_command_preview(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]

    window._port_combo.setCurrentText("/dev/ttyUSB0")
    window._baud_combo.setCurrentText("19200")
    window._on_field_changed()

    assert profile.port == "/dev/ttyUSB0"
    assert profile.serial_speed == 19200
    assert "-r /dev/ttyUSB0" in window._command_preview.text()
    assert "-s 19200" in window._command_preview.text()


def test_remove_selected_profile(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    assert len(window.profiles) == 1

    window._remove_selected()
    assert window.profiles == []
    assert window._list.count() == 0


def test_autostart_checkbox_reflects_initial_backend_state(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    backend = FakeAutostartBackend(supported=True, enabled=True)
    window = _make_window(tmp_path, qtbot, autostart_backend=backend)
    assert window._autostart_checkbox.isChecked() is True
    assert window._autostart_checkbox.isEnabled() is True


def test_autostart_checkbox_disabled_when_unsupported(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    backend = FakeAutostartBackend(supported=False)
    window = _make_window(tmp_path, qtbot, autostart_backend=backend)
    assert window._autostart_checkbox.isEnabled() is False


def test_toggling_autostart_checkbox_calls_backend(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    backend = FakeAutostartBackend(supported=True, enabled=False)
    window = _make_window(tmp_path, qtbot, autostart_backend=backend)

    window._autostart_checkbox.setChecked(True)
    assert backend.enable_calls == 1

    window._autostart_checkbox.setChecked(False)
    assert backend.disable_calls == 1


def test_profile_autostart_checkbox_persists(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    assert profile.auto_start is False

    window._profile_autostart_checkbox.setChecked(True)
    assert profile.auto_start is True

    store = ProfileStore(path=tmp_path / "profiles.json")
    assert store.load()[0].auto_start is True


def test_start_autostart_profiles_starts_only_flagged_ones(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    FAKE_CTLD.chmod(FAKE_CTLD.stat().st_mode | stat.S_IXUSR)

    def resolver(kind: ProfileKind) -> str:
        return str(FAKE_CTLD)

    window = _make_window(tmp_path, qtbot, executable_resolver=resolver)
    window._add_profile(ProfileKind.RIG)
    window._add_profile(ProfileKind.RIG)
    flagged, unflagged = window.profiles
    flagged.auto_start = True

    try:
        window.start_autostart_profiles()
        qtbot.waitUntil(lambda: window.is_running(flagged.id), timeout=1000)
        assert window.is_running(flagged.id) is True
        assert window.is_running(unflagged.id) is False
    finally:
        window.stop_all()


def test_manufacturer_and_model_combos_are_searchable(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot, executable_resolver=lambda kind: "rigctld")
    window._add_profile(ProfileKind.RIG)
    assert window._manufacturer_combo.isEditable() is True
    assert window._manufacturer_combo.completer() is not None
    assert window._model_combo.isEditable() is True
    assert window._model_combo.completer() is not None


def test_test_connection_reports_success(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    FAKE_RIGCTL.chmod(FAKE_RIGCTL.stat().st_mode | stat.S_IXUSR)
    window = _make_window(tmp_path, qtbot, test_executable_resolver=lambda kind: str(FAKE_RIGCTL))
    window._add_profile(ProfileKind.RIG)

    window._on_test_connection()

    assert "✓" in window._test_connection_result.text()
    assert "145000000" in window._test_connection_result.text()
    assert window._test_connection_button.isEnabled() is True
    assert window._test_connection_button.text() == "接続テスト"


def test_test_connection_reports_missing_executable(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.core.hamlib_locator import ExecutableNotFoundError

    def missing(kind: ProfileKind) -> str:
        raise ExecutableNotFoundError("rigctl not found")

    window = _make_window(tmp_path, qtbot, test_executable_resolver=missing)
    window._add_profile(ProfileKind.RIG)

    window._on_test_connection()

    assert "✗" in window._test_connection_result.text()
