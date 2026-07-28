from __future__ import annotations

from ctld_launcher.main import MainWindow


def test_main_window_title(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "ctld-launcher"
