from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ctld_launcher.i18n import detect_system_language, set_language
from ctld_launcher.ui.main_window import MainWindow
from ctld_launcher.ui.tray import TrayIcon


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Must run before any widget is built: ui/main_window.py's translatable
    # string lists (e.g. _debug_levels()) are evaluated lazily inside
    # instance methods for exactly this reason — see i18n.py's docstring.
    set_language(detect_system_language())

    window = MainWindow()
    _tray = TrayIcon(window, app)  # kept alive for the app's lifetime
    app.aboutToQuit.connect(window.stop_all)
    window.start_autostart_profiles()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
