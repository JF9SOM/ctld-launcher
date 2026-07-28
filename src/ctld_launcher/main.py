from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from ctld_launcher.ui.main_window import MainWindow
from ctld_launcher.ui.tray import TrayIcon


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    _tray = TrayIcon(window, app)  # kept alive for the app's lifetime
    app.aboutToQuit.connect(window.stop_all)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
