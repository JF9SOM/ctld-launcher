from __future__ import annotations

from ctld_launcher.core.profile import ProfileKind, ProfileStore
from ctld_launcher.ui.main_window import MainWindow
from ctld_launcher.ui.tray import TrayIcon


def _fake_resolver(kind: ProfileKind) -> str:
    return "rigctld" if kind == ProfileKind.RIG else "rotctld"


def test_tray_menu_lists_profiles_and_actions(tmp_path, qtbot, qapp) -> None:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "profiles.json")
    window = MainWindow(store=store, executable_resolver=_fake_resolver)
    qtbot.addWidget(window)
    window._add_profile(ProfileKind.RIG)

    tray = TrayIcon(window, qapp)
    menu = tray.contextMenu()
    tray._rebuild_menu(menu)

    labels = [action.text() for action in menu.actions()]
    assert any("New Rig" in label for label in labels)
    assert "Open settings…" in labels
    assert "Quit" in labels


def test_tray_menu_empty_state(tmp_path, qtbot, qapp) -> None:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "profiles.json")
    window = MainWindow(store=store, executable_resolver=_fake_resolver)
    qtbot.addWidget(window)

    tray = TrayIcon(window, qapp)
    menu = tray.contextMenu()
    tray._rebuild_menu(menu)

    labels = [action.text() for action in menu.actions()]
    assert "No profiles" in labels


def test_tray_right_click_shows_context_menu(tmp_path, qtbot, qapp) -> None:  # type: ignore[no-untyped-def]
    # Some Linux tray hosts don't auto-show the menu set via
    # setContextMenu() on right-click, so TrayIcon falls back to popping it
    # up explicitly on a Context-reason activation. See tray.py.
    from PySide6.QtWidgets import QSystemTrayIcon

    store = ProfileStore(path=tmp_path / "profiles.json")
    window = MainWindow(store=store, executable_resolver=_fake_resolver)
    qtbot.addWidget(window)

    tray = TrayIcon(window, qapp)
    popup_calls = []
    tray.contextMenu().popup = popup_calls.append  # type: ignore[method-assign]

    tray._on_activated(QSystemTrayIcon.ActivationReason.Context)

    assert len(popup_calls) == 1
