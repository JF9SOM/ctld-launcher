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
    usb_ports_resolver=list,
) -> MainWindow:
    store = ProfileStore(path=tmp_path / "profiles.json")
    kwargs = {} if autostart_backend is None else {"autostart_backend": autostart_backend}
    window = MainWindow(
        store=store,
        executable_resolver=executable_resolver,
        test_executable_resolver=test_executable_resolver,
        usb_ports_resolver=usb_ports_resolver,
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
    assert window._test_connection_button.text() == "Test connection"


def test_test_connection_reports_missing_executable(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.core.hamlib_locator import ExecutableNotFoundError

    def missing(kind: ProfileKind) -> str:
        raise ExecutableNotFoundError("rigctl not found")

    window = _make_window(tmp_path, qtbot, test_executable_resolver=missing)
    window._add_profile(ProfileKind.RIG)

    window._on_test_connection()

    assert "✗" in window._test_connection_result.text()


def test_language_switch_retranslates_widgets(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.i18n import get_language, set_language

    set_language("en")
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    assert window._start_button.text() == "Start"
    assert window._model_group.title() == "Model"

    ja_index = window._language_combo.findData("ja")
    window._language_combo.setCurrentIndex(ja_index)

    try:
        assert get_language() == "ja"
        assert window._start_button.text() == "起動"
        assert window._model_group.title() == "モデル"
        assert window._manufacturer_label.text() == "メーカー"
        # profile.model_id / port / etc. must survive the retranslation
        assert window.profiles[0].model_id == 1
    finally:
        set_language("en")


def test_language_combo_reflects_current_language_on_open(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.i18n import set_language

    set_language("ja")
    try:
        window = _make_window(tmp_path, qtbot)
        assert window._language_combo.currentData() == "ja"
    finally:
        set_language("en")


def test_civ_field_visible_only_for_rig(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    # isHidden() (not isVisible()) since the window isn't shown in this
    # test — isVisible() would be False regardless once shown/not shown.
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    assert window._civ_widget.isHidden() is False

    window._add_profile(ProfileKind.ROTATOR)
    assert window._civ_widget.isHidden() is True


def test_civ_field_persists_to_profile(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    assert profile.civ_address is None

    window._civ_address_edit.setText("0x94")
    window._on_field_changed()

    assert profile.civ_address == "0x94"
    assert "-c 0x94" in window._command_preview.text()


def test_minimize_button_hides_window(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window.show()

    window._minimize_button.click()

    assert window.isHidden() is True


def test_quit_button_calls_qapplication_quit(tmp_path, qtbot, qapp) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    calls = []
    qapp.quit = lambda: calls.append(True)  # type: ignore[method-assign]

    window._on_quit_clicked()

    assert len(calls) == 1


def test_listen_port_tooltip_differs_by_kind(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    rig_tooltip = window._listen_port_spin.toolTip()
    assert "4532" in rig_tooltip

    window._add_profile(ProfileKind.ROTATOR)
    rotator_tooltip = window._listen_port_spin.toolTip()
    assert "4533" in rotator_tooltip
    assert rotator_tooltip != rig_tooltip


class FakePortInfo:
    def __init__(self, device: str, vid: int | None = None, pid: int | None = None) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid
        self.serial_number = None


def test_usb_hotplug_checkbox_captures_identity_of_selected_port(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    ports = [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)]
    window = _make_window(tmp_path, qtbot, usb_ports_resolver=lambda: ports)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    window._port_combo.setCurrentText("/dev/ttyUSB0")
    window._on_field_changed()

    window._usb_hotplug_checkbox.setChecked(True)

    assert profile.usb_hotplug is True
    assert profile.usb_vid == 0x0403
    assert profile.usb_pid == 0x6001
    assert "identified" in window._usb_hotplug_status_label.text()


def test_usb_hotplug_checkbox_stays_unidentified_when_device_not_present(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot, usb_ports_resolver=list)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    window._port_combo.setCurrentText("/dev/ttyUSB0")
    window._on_field_changed()

    window._usb_hotplug_checkbox.setChecked(True)

    assert profile.usb_hotplug is True
    assert profile.usb_vid is None
    assert "no USB device identified" in window._usb_hotplug_status_label.text()


def test_usb_hotplug_poll_starts_and_stops_profile_on_plug_unplug(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    FAKE_CTLD.chmod(FAKE_CTLD.stat().st_mode | stat.S_IXUSR)
    ports: list[FakePortInfo] = []

    def resolver(kind: ProfileKind) -> str:
        return str(FAKE_CTLD)

    window = _make_window(
        tmp_path, qtbot, executable_resolver=resolver, usb_ports_resolver=lambda: ports
    )
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    profile.usb_hotplug = True
    profile.usb_vid = 0x0403
    profile.usb_pid = 0x6001
    window._refresh_usb_tracking()

    try:
        ports.append(FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001))
        window._poll_usb_hotplug()
        qtbot.waitUntil(lambda: window.is_running(profile.id), timeout=1000)
        assert profile.port == "/dev/ttyUSB0"

        ports.clear()
        window._poll_usb_hotplug()
        qtbot.waitUntil(lambda: not window.is_running(profile.id), timeout=1000)
    finally:
        window.stop_all()
