from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ctld_launcher.ui.main_window import MainWindow, status_dot_icon


def app_icon(any_running: bool) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#26215C"))
    painter.setBrush(QColor("#7F77DD"))
    painter.drawEllipse(2, 2, 28, 28)
    if any_running:
        painter.setPen(QColor("transparent"))
        painter.setBrush(QColor("#1D9E75"))
        painter.drawEllipse(18, 18, 12, 12)
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """Tray icon showing which rigctld/rotctld instances are running, with
    quick start/stop and a shortcut to the full configuration window.
    """

    def __init__(self, window: MainWindow, app: QApplication) -> None:
        super().__init__(app_icon(any_running=False))
        self._window = window
        self._app = app
        self.setToolTip("ctld-launcher")

        menu = QMenu()
        menu.aboutToShow.connect(lambda: self._rebuild_menu(menu))
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        window.state_changed.connect(self._refresh_icon)
        self._refresh_icon()
        self.show()

    def _rebuild_menu(self, menu: QMenu) -> None:
        menu.clear()
        profiles = self._window.profiles
        if not profiles:
            empty_action = menu.addAction("プロファイルがありません")
            empty_action.setEnabled(False)
        for profile in profiles:
            running = self._window.is_running(profile.id)
            action = menu.addAction(status_dot_icon(running), profile.name)
            action.triggered.connect(
                lambda checked=False, profile_id=profile.id: self._window.toggle_process(profile_id)
            )
        menu.addSeparator()
        open_action = menu.addAction("設定を開く…")
        open_action.triggered.connect(self._window.show_and_raise)
        quit_action = menu.addAction("終了")
        quit_action.triggered.connect(self._app.quit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._window.show_and_raise()

    def _refresh_icon(self) -> None:
        any_running = any(self._window.is_running(p.id) for p in self._window.profiles)
        self.setIcon(app_icon(any_running))
