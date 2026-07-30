from __future__ import annotations

import stat
from pathlib import Path

from ctld_launcher.core.profile import ProfileKind, ProfileStore
from ctld_launcher.ui.main_window import MainWindow

FAKE_CTLD = Path(__file__).parent / "_fake_ctld.py"
FAKE_RIGCTL = Path(__file__).parent / "_fake_rigctl.py"
FAKE_HAMLIB_LIST = Path(__file__).parent / "_fake_hamlib_list.py"


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


def test_version_label_shown_near_top_of_sidebar(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.version import get_version

    window = _make_window(tmp_path, qtbot)
    assert get_version() in window._version_label.text()
    assert "ctld-launcher" in window._version_label.text()


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

    checkbox = window._sidebar_autostart_toggles[profile.id]
    checkbox.setChecked(True)
    assert profile.auto_start is True

    store = ProfileStore(path=tmp_path / "profiles.json")
    assert store.load()[0].auto_start is True


def test_sidebar_autostart_checkbox_reflects_existing_profile_state(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    profile.auto_start = True
    window._refresh_sidebar_item(profile)

    assert window._sidebar_autostart_toggles[profile.id].isChecked() is True


def test_sidebar_autostart_checkbox_removed_when_profile_removed(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    window._add_profile(ProfileKind.RIG)
    profile_id = window.profiles[0].id
    assert profile_id in window._sidebar_autostart_toggles

    window._remove_selected()

    assert profile_id not in window._sidebar_autostart_toggles


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


def test_model_name_combo_keeps_correct_model_after_form_repopulate(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    # Regression test: _populate_model_combo() used to never explicitly
    # select the entry matching profile.model_id, so re-populating the form
    # (profile reselect, language switch, USB hotplug reconnect) always
    # defaulted the displayed model name to index 0 of that manufacturer's
    # list (FT-847 here) even though model_id itself never changed.
    FAKE_HAMLIB_LIST.chmod(FAKE_HAMLIB_LIST.stat().st_mode | stat.S_IXUSR)
    window = _make_window(tmp_path, qtbot, executable_resolver=lambda kind: str(FAKE_HAMLIB_LIST))
    window._add_profile(ProfileKind.RIG)
    profile = window.profiles[0]
    profile.model_id = 1035  # Yaesu FT-991 -- not index 0 of Yaesu's model list

    window._populate_form(profile)

    assert window._model_combo.currentText() == "FT-991"
    assert window._model_combo.currentData() == 1035
    assert window._model_id_spin.value() == 1035


def test_test_connection_reports_success(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    FAKE_RIGCTL.chmod(FAKE_RIGCTL.stat().st_mode | stat.S_IXUSR)
    window = _make_window(tmp_path, qtbot, test_executable_resolver=lambda kind: str(FAKE_RIGCTL))
    window._add_profile(ProfileKind.RIG)

    window._on_test_connection()

    assert "✓" in window._test_connection_result.text()
    assert "145000000" in window._test_connection_result.text()
    assert window._test_connection_button.isEnabled() is True
    assert window._test_connection_button.text() == "Test connection"
    assert "#1D9E75" in window._test_connection_button.styleSheet()


def test_test_connection_reports_missing_executable(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    from ctld_launcher.core.hamlib_locator import ExecutableNotFoundError

    def missing(kind: ProfileKind) -> str:
        raise ExecutableNotFoundError("rigctl not found")

    window = _make_window(tmp_path, qtbot, test_executable_resolver=missing)
    window._add_profile(ProfileKind.RIG)

    window._on_test_connection()

    assert "✗" in window._test_connection_result.text()
    assert "#D9534F" in window._test_connection_button.styleSheet()


def test_test_connection_button_style_resets_on_profile_switch(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    FAKE_RIGCTL.chmod(FAKE_RIGCTL.stat().st_mode | stat.S_IXUSR)
    window = _make_window(tmp_path, qtbot, test_executable_resolver=lambda kind: str(FAKE_RIGCTL))
    window._add_profile(ProfileKind.RIG)
    window._on_test_connection()
    assert window._test_connection_button.styleSheet() != ""

    window._add_profile(ProfileKind.RIG)

    assert window._test_connection_button.styleSheet() == ""


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


def test_hamlib_version_label_hidden_when_not_bundled(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    # isHidden() (not isVisible()) since the window isn't shown in this test.
    window = _make_window(tmp_path, qtbot)
    assert window._hamlib_version_label.isHidden() is True


def test_update_button_hidden_by_default(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _make_window(tmp_path, qtbot)
    assert window._update_button.isHidden() is True


def _mock_current_version(monkeypatch, version: str = "0.1.0") -> None:  # type: ignore[no-untyped-def]
    # _on_update_check_result() compares against the real get_version(),
    # which resolves via `git describe` / package metadata and can be a
    # messy, unparseable dev string depending on the checkout (e.g. a
    # shallow CI clone with no reachable tags) — is_newer_version() treats
    # that as "never newer" by design, which would make these tests flaky
    # across environments. Pin it to a known clean version instead.
    from ctld_launcher.ui import main_window

    monkeypatch.setattr(main_window, "get_version", lambda: version)


def test_update_check_result_shows_button_for_newer_version(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_current_version(monkeypatch)
    window = _make_window(tmp_path, qtbot)

    window._on_update_check_result("9.9.9", "https://example.com/asset")

    assert window._update_button.isHidden() is False
    assert "9.9.9" in window._update_button.text()


def test_update_check_result_ignores_older_or_equal_version(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_current_version(monkeypatch, "5.0.0")
    window = _make_window(tmp_path, qtbot)

    window._on_update_check_result("5.0.0", "https://example.com/asset")

    assert window._update_button.isHidden() is True


def test_update_button_click_confirms_and_starts_download(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from ctld_launcher.core import app_update

    def fail_immediately(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("no network in tests")

    monkeypatch.setattr(app_update.urllib.request, "urlretrieve", fail_immediately)

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    # The forced urlretrieve failure above means the worker's finished signal
    # will take the failure path, which pops a warning dialog once the
    # queued cross-thread signal is delivered (possibly not until qtbot's
    # own teardown pumps the event loop) — must be mocked too, or that
    # dialog's real .exec() hangs the test run.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window._on_update_button_clicked()

    assert window._update_button.isEnabled() is False
    assert "Downloading" in window._update_button.text()

    worker = window._update_install_worker
    assert worker is not None
    assert worker.wait(3000) is True
    qtbot.wait(50)


def test_update_button_click_declined_does_not_start_download(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._on_update_button_clicked()

    assert window._update_install_worker is None
    assert window._update_button.isEnabled() is True


def test_update_install_finished_failure_resets_button(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")
    window._update_button.setEnabled(False)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    window._on_update_install_finished(False, "", "connection refused")

    assert window._update_button.isEnabled() is True
    assert "9.9.9" in window._update_button.text()


def test_update_restart_ready_restarts_on_confirm(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    restart_calls = []
    monkeypatch.setattr(window, "_restart_app", lambda: restart_calls.append(True))

    window._on_update_install_finished(True, "restart_ready", "")

    assert restart_calls == [True]


def test_update_restart_ready_stays_running_if_declined(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    restart_calls = []
    monkeypatch.setattr(window, "_restart_app", lambda: restart_calls.append(True))

    window._on_update_install_finished(True, "restart_ready", "")

    assert restart_calls == []
    assert "Updated" in window._update_button.text()


def test_update_install_finished_installer_launched_quits(tmp_path, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path, qtbot)
    _mock_current_version(monkeypatch)
    window._on_update_check_result("9.9.9", "https://example.com/asset")

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    quit_calls = []
    monkeypatch.setattr(window, "_quit_app", lambda: quit_calls.append(True))

    window._on_update_install_finished(True, "installer_launched", "")

    assert quit_calls == [True]
