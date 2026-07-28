from __future__ import annotations

import functools
import shlex
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ctld_launcher.core.hamlib_locator import ExecutableNotFoundError, find_executable
from ctld_launcher.core.known_models import models_for
from ctld_launcher.core.process_manager import CtldProcess, build_command
from ctld_launcher.core.profile import Profile, ProfileKind, ProfileStore
from ctld_launcher.core.serial_ports import list_serial_ports

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]
DEBUG_LEVELS = [
    "通常",
    "詳細 (-v)",
    "詳細 (-vv)",
    "詳細 (-vvv)",
    "デバッグ (-vvvv)",
    "トレース (-vvvvv)",
]
UNSET = "(未指定)"
DATA_BITS_OPTIONS = [UNSET, "7", "8"]
STOP_BITS_OPTIONS = [UNSET, "1", "2"]
PARITY_OPTIONS = [UNSET, "None", "Even", "Odd", "Mark", "Space"]
HANDSHAKE_OPTIONS = [UNSET, "None", "XONXOFF", "Hardware"]

RUNNING_COLOR = QColor("#1D9E75")
STOPPED_COLOR = QColor("#888780")


def status_dot_icon(running: bool) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(RUNNING_COLOR if running else STOPPED_COLOR)
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pixmap)


def _set_combo_text(combo: QComboBox, value: str) -> None:
    index = combo.findText(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _combo_or_none(combo: QComboBox) -> str | None:
    text = combo.currentText()
    return None if text == UNSET else text


def _int_or_none(combo: QComboBox) -> int | None:
    text = combo.currentText()
    return None if text == UNSET else int(text)


class MainWindow(QMainWindow):
    """Sidebar of rig/rotator profiles + a detail form to configure and run each one."""

    state_changed = Signal()
    _log_line = Signal(str, str)
    _process_exited = Signal(str, int)

    def __init__(
        self,
        store: ProfileStore | None = None,
        executable_resolver: Callable[[ProfileKind], str] = find_executable,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ctld-launcher")
        self.resize(760, 560)

        self._store = store or ProfileStore()
        self._profiles: list[Profile] = self._store.load()
        self._processes: dict[str, CtldProcess] = {}
        self._executable_resolver = executable_resolver
        self._current_id: str | None = None
        self._updating_form = False

        self._log_line.connect(self._on_log_line)
        self._process_exited.connect(self._on_process_exited)

        self._build_ui()
        for profile in self._profiles:
            self._add_sidebar_item(profile)
        if self._profiles:
            self._list.setCurrentRow(0)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        splitter = QSplitter()
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_form())
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _build_sidebar(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        add_row = QHBoxLayout()
        add_rig_button = QPushButton("+ リグ")
        add_rig_button.clicked.connect(lambda: self._add_profile(ProfileKind.RIG))
        add_rotator_button = QPushButton("+ ローテーター")
        add_rotator_button.clicked.connect(lambda: self._add_profile(ProfileKind.ROTATOR))
        add_row.addWidget(add_rig_button)
        add_row.addWidget(add_rotator_button)
        layout.addLayout(add_row)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        remove_button = QPushButton("削除")
        remove_button.clicked.connect(self._remove_selected)
        layout.addWidget(remove_button)

        container.setMaximumWidth(220)
        return container

    def _build_form(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        header = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)
        header.addWidget(self._name_edit)
        self._status_label = QLabel()
        header.addWidget(self._status_label)
        layout.addLayout(header)

        layout.addWidget(self._build_model_group())
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_network_group())
        layout.addWidget(self._build_debug_group())
        layout.addWidget(self._build_extra_args_group())

        layout.addWidget(QLabel("実行中のコマンド"))
        self._command_preview = QLineEdit()
        self._command_preview.setReadOnly(True)
        self._command_preview.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._command_preview)

        button_row = QHBoxLayout()
        self._start_button = QPushButton("起動")
        self._start_button.clicked.connect(self._on_start)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._on_stop)
        self._restart_button = QPushButton("再起動")
        self._restart_button.clicked.connect(self._on_restart)
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._restart_button)
        layout.addLayout(button_row)

        layout.addWidget(QLabel("ログ"))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._log_view, stretch=1)

        self._set_form_enabled(False)
        return container

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("モデル")
        layout = QHBoxLayout(group)
        self._manufacturer_combo = QComboBox()
        self._manufacturer_combo.currentIndexChanged.connect(self._on_manufacturer_changed)
        self._model_combo = QComboBox()
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        self._model_id_spin = QSpinBox()
        self._model_id_spin.setRange(0, 999_999)
        self._model_id_spin.valueChanged.connect(self._on_field_changed)
        layout.addWidget(self._manufacturer_combo)
        layout.addWidget(self._model_combo)
        layout.addWidget(QLabel("モデルID"))
        layout.addWidget(self._model_id_spin)
        return group

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("接続")
        outer = QVBoxLayout(group)

        row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.currentTextChanged.connect(self._on_field_changed)
        refresh_button = QToolButton()
        refresh_button.setText("⟳")
        refresh_button.setToolTip("ポートを再検出")
        refresh_button.clicked.connect(self._refresh_ports)
        self._baud_combo = QComboBox()
        self._baud_combo.setEditable(True)
        self._baud_combo.addItems(BAUD_RATES)
        self._baud_combo.currentTextChanged.connect(self._on_field_changed)
        row.addWidget(self._port_combo, stretch=2)
        row.addWidget(refresh_button)
        row.addWidget(self._baud_combo, stretch=1)
        outer.addLayout(row)

        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setText("詳細設定(データビット・パリティ・フロー制御)")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._advanced_toggle.clicked.connect(self._on_advanced_toggled)
        outer.addWidget(self._advanced_toggle)

        self._advanced_widget = QWidget()
        advanced_row = QHBoxLayout(self._advanced_widget)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        self._data_bits_combo = QComboBox()
        self._data_bits_combo.addItems(DATA_BITS_OPTIONS)
        self._data_bits_combo.currentTextChanged.connect(self._on_field_changed)
        self._stop_bits_combo = QComboBox()
        self._stop_bits_combo.addItems(STOP_BITS_OPTIONS)
        self._stop_bits_combo.currentTextChanged.connect(self._on_field_changed)
        self._parity_combo = QComboBox()
        self._parity_combo.addItems(PARITY_OPTIONS)
        self._parity_combo.currentTextChanged.connect(self._on_field_changed)
        self._handshake_combo = QComboBox()
        self._handshake_combo.addItems(HANDSHAKE_OPTIONS)
        self._handshake_combo.currentTextChanged.connect(self._on_field_changed)
        for label, widget in (
            ("データビット", self._data_bits_combo),
            ("ストップビット", self._stop_bits_combo),
            ("パリティ", self._parity_combo),
            ("フロー制御", self._handshake_combo),
        ):
            advanced_row.addWidget(QLabel(label))
            advanced_row.addWidget(widget)
        self._advanced_widget.setVisible(False)
        outer.addWidget(self._advanced_widget)
        return group

    def _build_network_group(self) -> QGroupBox:
        group = QGroupBox("ネットワーク")
        layout = QHBoxLayout(group)
        self._listen_address_edit = QLineEdit()
        self._listen_address_edit.editingFinished.connect(self._on_field_changed)
        self._listen_port_spin = QSpinBox()
        self._listen_port_spin.setRange(1, 65535)
        self._listen_port_spin.valueChanged.connect(self._on_field_changed)
        layout.addWidget(self._listen_address_edit, stretch=1)
        layout.addWidget(self._listen_port_spin)
        return group

    def _build_debug_group(self) -> QGroupBox:
        group = QGroupBox("デバッグ")
        layout = QHBoxLayout(group)
        self._debug_level_combo = QComboBox()
        self._debug_level_combo.addItems(DEBUG_LEVELS)
        self._debug_level_combo.currentIndexChanged.connect(self._on_field_changed)
        self._log_file_edit = QLineEdit()
        self._log_file_edit.setPlaceholderText("ログファイルパス(任意)")
        self._log_file_edit.editingFinished.connect(self._on_field_changed)
        browse_button = QPushButton("参照…")
        browse_button.clicked.connect(self._browse_log_file)
        layout.addWidget(self._debug_level_combo)
        layout.addWidget(self._log_file_edit, stretch=1)
        layout.addWidget(browse_button)
        return group

    def _build_extra_args_group(self) -> QGroupBox:
        group = QGroupBox("追加オプション(上級者向け)")
        layout = QVBoxLayout(group)
        self._extra_args_edit = QLineEdit()
        self._extra_args_edit.setPlaceholderText("-c 0x94")
        self._extra_args_edit.setStyleSheet("font-family: monospace;")
        self._extra_args_edit.editingFinished.connect(self._on_field_changed)
        layout.addWidget(self._extra_args_edit)
        return group

    # ------------------------------------------------------------------ #
    # Profile list management
    # ------------------------------------------------------------------ #
    @property
    def profiles(self) -> list[Profile]:
        return self._profiles

    def _find_profile(self, profile_id: str) -> Profile | None:
        for profile in self._profiles:
            if profile.id == profile_id:
                return profile
        return None

    def _selected_profile(self) -> Profile | None:
        if self._current_id is None:
            return None
        return self._find_profile(self._current_id)

    def _add_sidebar_item(self, profile: Profile) -> None:
        item = QListWidgetItem(status_dot_icon(self.is_running(profile.id)), profile.name)
        item.setData(Qt.ItemDataRole.UserRole, profile.id)
        self._list.addItem(item)

    def _refresh_sidebar_item(self, profile: Profile) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == profile.id:
                item.setIcon(status_dot_icon(self.is_running(profile.id)))
                item.setText(profile.name)
                return

    def _add_profile(self, kind: ProfileKind) -> None:
        models = models_for(kind)
        first_manufacturer = next(iter(models))
        model_id, _name = models[first_manufacturer][0]
        if kind == ProfileKind.RIG:
            profile = Profile.new_rig(name="新しいリグ", model_id=model_id)
        else:
            profile = Profile.new_rotator(name="新しいローテーター", model_id=model_id)
        self._profiles.append(profile)
        self._store.save(self._profiles)
        self._add_sidebar_item(profile)
        self._list.setCurrentRow(self._list.count() - 1)

    def _remove_selected(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self._stop_profile(profile.id)
        self._processes.pop(profile.id, None)
        self._profiles = [p for p in self._profiles if p.id != profile.id]
        self._store.save(self._profiles)
        row = self._list.currentRow()
        self._list.takeItem(row)

    # ------------------------------------------------------------------ #
    # Form population / persistence
    # ------------------------------------------------------------------ #
    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            self._current_id = None
            self._set_form_enabled(False)
            return
        profile_id = current.data(Qt.ItemDataRole.UserRole)
        self._current_id = profile_id
        profile = self._find_profile(profile_id)
        if profile is not None:
            self._set_form_enabled(True)
            self._populate_form(profile)

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (
            self._name_edit,
            self._manufacturer_combo,
            self._model_combo,
            self._model_id_spin,
            self._port_combo,
            self._baud_combo,
            self._listen_address_edit,
            self._listen_port_spin,
            self._debug_level_combo,
            self._log_file_edit,
            self._extra_args_edit,
        ):
            widget.setEnabled(enabled)

    def _populate_form(self, profile: Profile) -> None:
        self._updating_form = True
        try:
            self._name_edit.setText(profile.name)

            models = models_for(profile.kind)
            self._manufacturer_combo.clear()
            self._manufacturer_combo.addItems(list(models))
            manufacturer = self._manufacturer_for_model(profile.kind, profile.model_id)
            if manufacturer is not None:
                _set_combo_text(self._manufacturer_combo, manufacturer)
            self._populate_model_combo(profile.kind, self._manufacturer_combo.currentText())
            self._model_id_spin.setValue(profile.model_id)

            if not self._port_combo.count():
                self._refresh_ports()
            self._port_combo.setCurrentText(profile.port)
            baud_text = str(profile.serial_speed) if profile.serial_speed else ""
            self._baud_combo.setCurrentText(baud_text)

            data_bits_text = str(profile.data_bits) if profile.data_bits else UNSET
            stop_bits_text = str(profile.stop_bits) if profile.stop_bits else UNSET
            _set_combo_text(self._data_bits_combo, data_bits_text)
            _set_combo_text(self._stop_bits_combo, stop_bits_text)
            _set_combo_text(self._parity_combo, profile.serial_parity or UNSET)
            _set_combo_text(self._handshake_combo, profile.serial_handshake or UNSET)

            self._listen_address_edit.setText(profile.listen_address)
            self._listen_port_spin.setValue(profile.listen_port)
            self._debug_level_combo.setCurrentIndex(profile.debug_level)
            self._log_file_edit.setText(profile.log_file or "")
            self._extra_args_edit.setText(shlex.join(profile.extra_args))
        finally:
            self._updating_form = False
        self._update_status_and_buttons()

    def _manufacturer_for_model(self, kind: ProfileKind, model_id: int) -> str | None:
        for manufacturer, models in models_for(kind).items():
            if any(mid == model_id for mid, _name in models):
                return manufacturer
        return None

    def _populate_model_combo(self, kind: ProfileKind, manufacturer: str) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model_id, name in models_for(kind).get(manufacturer, []):
            self._model_combo.addItem(name, userData=model_id)
        self._model_combo.blockSignals(False)

    def _on_manufacturer_changed(self) -> None:
        if self._updating_form:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        self._populate_model_combo(profile.kind, self._manufacturer_combo.currentText())
        self._on_model_combo_changed()

    def _on_model_combo_changed(self) -> None:
        if self._updating_form:
            return
        model_id = self._model_combo.currentData()
        if model_id is not None:
            self._model_id_spin.setValue(model_id)

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_widget.setVisible(checked)
        self._advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _refresh_ports(self) -> None:
        current = self._port_combo.currentText()
        self._port_combo.clear()
        self._port_combo.addItems(list_serial_ports())
        self._port_combo.setCurrentText(current)

    def _browse_log_file(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "ログファイルを選択",
            self._log_file_edit.text(),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self._log_file_edit.setText(path)
            self._on_field_changed()

    def _on_name_changed(self) -> None:
        if self._updating_form:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        profile.name = self._name_edit.text()
        self._store.save(self._profiles)
        self._refresh_sidebar_item(profile)

    def _on_field_changed(self) -> None:
        if self._updating_form:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        profile.model_id = self._model_id_spin.value()
        profile.port = self._port_combo.currentText()
        baud_text = self._baud_combo.currentText().strip()
        profile.serial_speed = int(baud_text) if baud_text else None
        profile.data_bits = _int_or_none(self._data_bits_combo)
        profile.stop_bits = _int_or_none(self._stop_bits_combo)
        profile.serial_parity = _combo_or_none(self._parity_combo)
        profile.serial_handshake = _combo_or_none(self._handshake_combo)
        profile.listen_address = self._listen_address_edit.text()
        profile.listen_port = self._listen_port_spin.value()
        profile.debug_level = self._debug_level_combo.currentIndex()
        profile.log_file = self._log_file_edit.text() or None
        profile.extra_args = shlex.split(self._extra_args_edit.text())
        self._store.save(self._profiles)
        self._update_command_preview()

    def _update_command_preview(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            self._command_preview.setText("")
            return
        try:
            executable = self._executable_resolver(profile.kind)
        except ExecutableNotFoundError:
            executable = "rigctld" if profile.kind == ProfileKind.RIG else "rotctld"
        self._command_preview.setText(" ".join(build_command(executable, profile)))

    # ------------------------------------------------------------------ #
    # Process control
    # ------------------------------------------------------------------ #
    def is_running(self, profile_id: str) -> bool:
        process = self._processes.get(profile_id)
        return process is not None and process.is_running

    def _on_start(self) -> None:
        profile = self._selected_profile()
        if profile is not None:
            self._start_profile(profile)

    def _on_stop(self) -> None:
        if self._current_id is not None:
            self._stop_profile(self._current_id)

    def _on_restart(self) -> None:
        profile = self._selected_profile()
        if profile is not None:
            self._stop_profile(profile.id)
            self._start_profile(profile)

    def toggle_process(self, profile_id: str) -> None:
        if self.is_running(profile_id):
            self._stop_profile(profile_id)
        else:
            profile = self._find_profile(profile_id)
            if profile is not None:
                self._start_profile(profile)

    def _start_profile(self, profile: Profile) -> None:
        if self.is_running(profile.id):
            return
        try:
            executable = self._executable_resolver(profile.kind)
        except ExecutableNotFoundError as exc:
            QMessageBox.warning(self, "起動できません", str(exc))
            return
        command = build_command(executable, profile)
        process = CtldProcess(
            command=command,
            log_file=profile.log_file or None,
            on_output=functools.partial(self._emit_log_line, profile.id),
            on_exit=functools.partial(self._emit_process_exited, profile.id),
        )
        process.start()
        self._processes[profile.id] = process
        self._refresh_sidebar_item(profile)
        if profile.id == self._current_id:
            self._update_status_and_buttons()
        self.state_changed.emit()

    def _stop_profile(self, profile_id: str) -> None:
        process = self._processes.get(profile_id)
        if process is None:
            return
        process.stop()
        profile = self._find_profile(profile_id)
        if profile is not None:
            self._refresh_sidebar_item(profile)
            if profile_id == self._current_id:
                self._update_status_and_buttons()
        self.state_changed.emit()

    def stop_all(self) -> None:
        for profile_id in list(self._processes):
            self._stop_profile(profile_id)

    def _emit_log_line(self, profile_id: str, line: str) -> None:
        # Called from CtldProcess's reader thread; Signal.emit() is safe to
        # call cross-thread, Qt queues delivery to _on_log_line on the GUI
        # thread automatically.
        self._log_line.emit(profile_id, line)

    def _emit_process_exited(self, profile_id: str, exit_code: int) -> None:
        self._process_exited.emit(profile_id, exit_code)

    def _on_log_line(self, profile_id: str, line: str) -> None:
        if profile_id == self._current_id:
            self._log_view.appendPlainText(line)

    def _on_process_exited(self, profile_id: str, _exit_code: int) -> None:
        profile = self._find_profile(profile_id)
        if profile is not None:
            self._refresh_sidebar_item(profile)
            if profile_id == self._current_id:
                self._update_status_and_buttons()
        self.state_changed.emit()

    def _update_status_and_buttons(self) -> None:
        profile = self._selected_profile()
        running = profile is not None and self.is_running(profile.id)
        if profile is None:
            self._status_label.setText("")
        elif running:
            process = self._processes[profile.id]
            self._status_label.setText(f"● 稼働中 · PID {process.pid}")
        else:
            self._status_label.setText("○ 停止中")
        self._start_button.setEnabled(profile is not None and not running)
        self._stop_button.setEnabled(running)
        self._restart_button.setEnabled(running)
        self._update_command_preview()

    # ------------------------------------------------------------------ #
    # Window lifecycle (tray app: closing hides, it doesn't quit)
    # ------------------------------------------------------------------ #
    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
