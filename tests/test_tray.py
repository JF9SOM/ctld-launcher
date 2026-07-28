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
    assert any("新しいリグ" in label for label in labels)
    assert "設定を開く…" in labels
    assert "終了" in labels


def test_tray_menu_empty_state(tmp_path, qtbot, qapp) -> None:  # type: ignore[no-untyped-def]
    store = ProfileStore(path=tmp_path / "profiles.json")
    window = MainWindow(store=store, executable_resolver=_fake_resolver)
    qtbot.addWidget(window)

    tray = TrayIcon(window, qapp)
    menu = tray.contextMenu()
    tray._rebuild_menu(menu)

    labels = [action.text() for action in menu.actions()]
    assert "プロファイルがありません" in labels
