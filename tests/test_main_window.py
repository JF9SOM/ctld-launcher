from __future__ import annotations

from ctld_launcher.core.profile import ProfileKind, ProfileStore
from ctld_launcher.ui.main_window import MainWindow


def _fake_resolver(kind: ProfileKind) -> str:
    return "rigctld" if kind == ProfileKind.RIG else "rotctld"


def _make_window(tmp_path, qtbot) -> MainWindow:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "profiles.json")
    window = MainWindow(store=store, executable_resolver=_fake_resolver)
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
