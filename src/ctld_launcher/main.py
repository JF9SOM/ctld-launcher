from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ctld_launcher.core.autostart import MINIMIZED_FLAG
from ctld_launcher.i18n import detect_system_language, set_language
from ctld_launcher.ui.main_window import MainWindow
from ctld_launcher.ui.tray import TrayIcon
from ctld_launcher.version import get_version


def should_show_on_startup(argv: list[str]) -> bool:
    """Open the settings window on startup unless launched via autostart.

    autostart.default_command() appends MINIMIZED_FLAG when registering the
    login-time launch, so a manual launch (double-click, app menu, PATH —
    none of which pass this flag) opens the window immediately instead of
    silently landing in the tray, which reads to users as "it didn't start."
    """
    return MINIMIZED_FLAG not in argv


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ctld-launcher")
    app.setApplicationVersion(get_version())

    # Must run before any widget is built: ui/main_window.py's translatable
    # string lists (e.g. _debug_levels()) are evaluated lazily inside
    # instance methods for exactly this reason — see i18n.py's docstring.
    set_language(detect_system_language())

    window = MainWindow()
    _tray = TrayIcon(window, app)  # kept alive for the app's lifetime
    app.aboutToQuit.connect(window.stop_all)
    window.start_autostart_profiles()
    window.check_for_updates()

    if should_show_on_startup(sys.argv) or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
