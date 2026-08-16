from __future__ import annotations

import functools
import platform
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
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
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from ctld_launcher.core import autostart as autostart_module
from ctld_launcher.core.app_update import (
    GITHUB_RELEASES,
    UpdateCheckWorker,
    UpdateInstallWorker,
    is_newer_version,
)
from ctld_launcher.core.autostart import AutostartBackend, AutostartError
from ctld_launcher.core.hamlib_locator import (
    ExecutableNotFoundError,
    bundled_hamlib_version,
    find_executable,
    find_test_executable,
)
from ctld_launcher.core.hamlib_models import default_model_id, models_by_manufacturer
from ctld_launcher.core.process_manager import (
    CtldProcess,
    build_command,
    build_test_command,
    probe_daemon,
    serial_port_from_command,
)
from ctld_launcher.core.profile import Profile, ProfileKind, ProfileStore
from ctld_launcher.core.serial_ports import list_serial_ports
from ctld_launcher.core.subprocess_utils import NO_WINDOW_FLAGS
from ctld_launcher.core.usb_watch import UsbHotplugTracker, UsbIdentity, identity_for_port
from ctld_launcher.i18n import _, get_language, set_language
from ctld_launcher.version import get_version

USB_POLL_INTERVAL_MS = 2000

# How often a running daemon is health-checked, and how many consecutive
# failures/timeouts in a row before it's considered wedged and automatically
# killed + respawned. Chosen for fast detection over tolerance of a single
# transient hiccup (e.g. a client mid-query at the exact poll moment) --
# restarting the daemon is cheap, so erring toward restarting sooner.
HEALTH_CHECK_INTERVAL_MS = 5000
HEALTH_CHECK_FAILURE_THRESHOLD = 1

# How many times in a row an unexpected exit (crash, not a hang) is
# auto-restarted before giving up -- same purpose as systemd's
# StartLimitBurst: a daemon that dies on every launch (e.g. persistently
# bad arguments) shouldn't spin forever.
CRASH_RESTART_LIMIT = 3

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]

RUNNING_COLOR = QColor("#1D9E75")
STOPPED_COLOR = QColor("#888780")
FAILURE_COLOR = QColor("#D9534F")

TEST_SUCCESS_STYLE = "background-color: #1D9E75; color: white;"
TEST_FAILURE_STYLE = "background-color: #D9534F; color: white;"
# The Start button stays disabled while running (starting it again is a
# no-op) -- ":disabled" is needed here, or Qt's native disabled-button look
# would override the green and it would just look grey again.
START_BUTTON_RUNNING_STYLE = "QPushButton:disabled { background-color: #1D9E75; color: white; }"


def _debug_levels() -> list[str]:
    # Built lazily (called from _build_debug_group(), not at module import
    # time) so set_language() — called early in main() — has already taken
    # effect. See i18n.py's module docstring.
    return [
        _("Normal"),
        _("Verbose (-v)"),
        _("Verbose (-vv)"),
        _("Verbose (-vvv)"),
        _("Debug (-vvvv)"),
        _("Trace (-vvvvv)"),
    ]


def _unset_label() -> str:
    return _("(Not set)")


def _data_bits_options() -> list[str]:
    return [_unset_label(), "7", "8"]


def _stop_bits_options() -> list[str]:
    return [_unset_label(), "1", "2"]


def _parity_options() -> list[str]:
    # "None"/"Even"/"Odd"/"Mark"/"Space" are Hamlib's own -C serial_parity=
    # values, passed verbatim on the command line — not translatable.
    return [_unset_label(), "None", "Even", "Odd", "Mark", "Space"]


def _handshake_options() -> list[str]:
    # Same as above: Hamlib's -C serial_handshake= values, not translatable.
    return [_unset_label(), "None", "XONXOFF", "Hardware"]


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


class ToggleSwitch(QAbstractButton):
    """A green(ON)/red(OFF) slide toggle with the state spelled out in text.

    Used instead of a QCheckBox for "start this profile automatically when
    the app launches", sitting on the right of each profile's row in the
    sidebar list — a plain square checkbox there read as a "select this
    profile to delete" checkbox to at least one real user, since it sat
    directly above the "Remove" button. A visibly different control shape
    avoids that reading.
    """

    _TRACK_WIDTH = 52
    _TRACK_HEIGHT = 22
    _KNOB_MARGIN = 2
    _KNOB_SIZE = _TRACK_HEIGHT - 2 * _KNOB_MARGIN

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._TRACK_WIDTH, self._TRACK_HEIGHT)
        self._knob_x = float(self._KNOB_MARGIN)
        self._animation = QPropertyAnimation(self, b"knob_x", self)
        self._animation.setDuration(120)
        self.toggled.connect(self._animate_to_state)

    def _end_knob_x(self, checked: bool) -> float:
        if checked:
            return float(self._TRACK_WIDTH - self._KNOB_MARGIN - self._KNOB_SIZE)
        return float(self._KNOB_MARGIN)

    def _animate_to_state(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._knob_x)
        self._animation.setEndValue(self._end_knob_x(checked))
        self._animation.start()

    def _get_knob_x(self) -> float:
        return self._knob_x

    def _set_knob_x(self, value: float) -> None:
        self._knob_x = value
        self.update()

    knob_x = Property(float, _get_knob_x, _set_knob_x)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt override)
        super().setChecked(checked)
        self._animation.stop()
        self._knob_x = self._end_knob_x(checked)
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: ARG002 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_color = RUNNING_COLOR if self.isChecked() else FAILURE_COLOR
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        radius = self._TRACK_HEIGHT / 2
        painter.drawRoundedRect(QRectF(0, 0, self._TRACK_WIDTH, self._TRACK_HEIGHT), radius, radius)

        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        label_width = self._TRACK_WIDTH - self._KNOB_SIZE - self._KNOB_MARGIN
        if self.isChecked():
            label_rect = QRectF(4, 0, label_width, self._TRACK_HEIGHT)
            painter.drawText(
                label_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "ON"
            )
        else:
            label_rect = QRectF(
                self._TRACK_WIDTH - label_width - 4, 0, label_width, self._TRACK_HEIGHT
            )
            painter.drawText(
                label_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), "OFF"
            )

        painter.setBrush(QColor("white"))
        painter.drawEllipse(
            QRectF(self._knob_x, self._KNOB_MARGIN, self._KNOB_SIZE, self._KNOB_SIZE)
        )
        painter.end()


def _set_combo_text(combo: QComboBox, value: str) -> None:
    index = combo.findText(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _combo_or_none(combo: QComboBox) -> str | None:
    text = combo.currentText()
    return None if text == _unset_label() else text


def _int_or_none(combo: QComboBox) -> int | None:
    text = combo.currentText()
    return None if text == _unset_label() else int(text)


def _refresh_combo_search(combo: QComboBox) -> None:
    """Make combo searchable by substring, case-insensitive (e.g. typing
    "yaesu" finds "Yaesu" regardless of where it sits in the list). Must be
    called again whenever the combo's items are repopulated, since the
    completer is bound to a snapshot of combo.model().
    """
    combo.setEditable(True)
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)


class MainWindow(QMainWindow):
    """Sidebar of rig/rotator profiles + a detail form to configure and run each one."""

    state_changed = Signal()
    _log_line = Signal(str, str)
    _process_exited = Signal(str, int)
    _usb_ports_ready = Signal(object)  # list[ListPortInfo]
    _health_check_result = Signal(str, bool)  # profile_id, responded_ok
    _auto_restart_stopped = Signal(str)  # profile_id, after the old process was killed

    def __init__(
        self,
        store: ProfileStore | None = None,
        executable_resolver: Callable[[ProfileKind], str] = find_executable,
        test_executable_resolver: Callable[[ProfileKind], str] = find_test_executable,
        autostart_backend: AutostartBackend = autostart_module,
        usb_ports_resolver: Callable[[], list[ListPortInfo]] = list_ports.comports,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ctld-launcher")
        self.resize(760, 560)

        self._store = store or ProfileStore()
        self._profiles: list[Profile] = self._store.load()
        self._processes: dict[str, CtldProcess] = {}
        self._sidebar_name_labels: dict[str, QLabel] = {}
        self._sidebar_autostart_toggles: dict[str, ToggleSwitch] = {}
        self._executable_resolver = executable_resolver
        self._test_executable_resolver = test_executable_resolver
        self._autostart = autostart_backend
        self._usb_ports_resolver = usb_ports_resolver
        self._usb_tracker = UsbHotplugTracker()
        self._current_id: str | None = None
        self._updating_form = False
        self._update_latest_version: str | None = None
        self._update_download_url: str | None = None
        self._update_button_state = "idle"
        self._update_check_is_manual = False
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_install_worker: UpdateInstallWorker | None = None
        self._usb_poll_in_flight = False
        self._health_check_in_flight: set[str] = set()
        self._health_check_failures: dict[str, int] = {}
        self._auto_restarting: set[str] = set()
        self._auto_restart_stuck_warned: set[str] = set()
        self._intentional_stop: set[str] = set()
        self._crash_restart_attempts: dict[str, int] = {}

        self._log_line.connect(self._on_log_line)
        self._process_exited.connect(self._on_process_exited)
        self._usb_ports_ready.connect(self._on_usb_ports_ready)
        self._health_check_result.connect(self._on_health_check_result)
        self._auto_restart_stopped.connect(self._on_auto_restart_stopped)

        self._build_ui()
        for profile in self._profiles:
            self._add_sidebar_item(profile)
        if self._profiles:
            self._list.setCurrentRow(0)

        self._usb_timer = QTimer(self)
        self._usb_timer.timeout.connect(self._poll_usb_hotplug)
        self._refresh_usb_tracking()

        self._health_check_timer = QTimer(self)
        self._health_check_timer.timeout.connect(self._run_health_checks)
        self._health_check_timer.start(HEALTH_CHECK_INTERVAL_MS)

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

        self._version_label = QLabel(f"ctld-launcher v{get_version()}")
        self._version_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._version_label)

        hamlib_version = bundled_hamlib_version()
        self._hamlib_version_label = QLabel(f"Hamlib v{hamlib_version}" if hamlib_version else "")
        self._hamlib_version_label.setStyleSheet("color: gray; font-size: 10px;")
        self._hamlib_version_label.setVisible(hamlib_version is not None)
        layout.addWidget(self._hamlib_version_label)

        self._update_button = QToolButton()
        self._update_button.setStyleSheet(
            "QToolButton { color: #1D9E75; font-size: 10px; border: none; "
            "background: transparent; padding: 0; }"
        )
        self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_button.setText(_("Check for updates"))
        self._update_button.clicked.connect(self._on_update_button_clicked)
        layout.addWidget(self._update_button)

        # Language names are deliberately NOT translated via _() — each
        # option must always read in its own language, or a user who picks
        # the wrong one by accident could get stuck unable to read the UI
        # well enough to switch back.
        self._language_combo = QComboBox()
        self._language_combo.addItem("English", userData="en")
        self._language_combo.addItem("日本語", userData="ja")
        current_index = self._language_combo.findData(get_language())
        if current_index >= 0:
            self._language_combo.setCurrentIndex(current_index)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self._language_combo)

        add_row = QHBoxLayout()
        self._add_rig_button = QPushButton(_("+ Rig"))
        self._add_rig_button.clicked.connect(lambda: self._add_profile(ProfileKind.RIG))
        self._add_rotator_button = QPushButton(_("+ Rotator"))
        self._add_rotator_button.clicked.connect(lambda: self._add_profile(ProfileKind.ROTATOR))
        add_row.addWidget(self._add_rig_button)
        add_row.addWidget(self._add_rotator_button)
        layout.addLayout(add_row)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        self._remove_button = QPushButton(_("Remove"))
        self._remove_button.clicked.connect(self._remove_selected)
        layout.addWidget(self._remove_button)

        self._autostart_checkbox = QCheckBox(_("Start at login"))
        self._autostart_checkbox.setToolTip(
            _(
                "Starts this app itself in the tray at login. To also start individual "
                "profiles automatically, enable the toggle next to each profile in "
                "the list on the left."
            )
        )
        self._autostart_checkbox.setEnabled(self._autostart.is_supported())
        if self._autostart.is_supported():
            self._autostart_checkbox.setChecked(self._autostart.is_enabled())
        self._autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self._autostart_checkbox)

        self._minimize_button = QPushButton(_("Minimize to tray"))
        self._minimize_button.setToolTip(
            _(
                "Hides this window; rigctld/rotctld keep running in the background. "
                "Click the tray icon to bring it back."
            )
        )
        self._minimize_button.clicked.connect(self.hide)
        layout.addWidget(self._minimize_button)

        self._quit_button = QPushButton(_("Quit ctld-launcher"))
        self._quit_button.setToolTip(
            _(
                "Stops all running rigctld/rotctld processes and closes the app "
                "completely, including the tray icon."
            )
        )
        self._quit_button.clicked.connect(self._on_quit_clicked)
        layout.addWidget(self._quit_button)

        container.setMaximumWidth(220)
        return container

    def _build_form(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        header = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setToolTip(_("Enter any name you like for this profile."))
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

        self._command_label = QLabel(_("Command"))
        layout.addWidget(self._command_label)
        self._command_preview = QLineEdit()
        self._command_preview.setReadOnly(True)
        self._command_preview.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._command_preview)

        button_row = QHBoxLayout()
        self._start_button = QPushButton(_("Start"))
        self._start_button.clicked.connect(self._on_start)
        self._stop_button = QPushButton(_("Stop"))
        self._stop_button.clicked.connect(self._on_stop)
        self._restart_button = QPushButton(_("Restart"))
        self._restart_button.clicked.connect(self._on_restart)
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._restart_button)
        layout.addLayout(button_row)

        self._log_label = QLabel(_("Log"))
        layout.addWidget(self._log_label)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet("font-family: monospace;")
        layout.addWidget(self._log_view, stretch=1)

        self._set_form_enabled(False)
        return container

    def _build_model_group(self) -> QGroupBox:
        self._model_group = QGroupBox(_("Model"))
        layout = QHBoxLayout(self._model_group)
        self._manufacturer_combo = QComboBox()
        self._manufacturer_combo.setToolTip(
            _("Select the manufacturer of your rig/rotator. You can type to filter the list.")
        )
        self._manufacturer_combo.currentIndexChanged.connect(self._on_manufacturer_changed)
        _refresh_combo_search(self._manufacturer_combo)
        self._model_combo = QComboBox()
        self._model_combo.setToolTip(_("Select the model of your rig/rotator."))
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        _refresh_combo_search(self._model_combo)
        self._model_id_spin = QSpinBox()
        self._model_id_spin.setRange(0, 999_999)
        self._model_id_spin.setToolTip(
            _(
                "Hamlib's numeric model ID. Filled in automatically when you pick a "
                "manufacturer/model above; you can also type it directly for a model "
                "not in the list."
            )
        )
        self._model_id_spin.valueChanged.connect(self._on_field_changed)
        self._manufacturer_label = QLabel(_("Manufacturer"))
        self._model_name_label = QLabel(_("Model name"))
        self._model_id_label = QLabel(_("Model ID"))
        layout.addWidget(self._manufacturer_label)
        layout.addWidget(self._manufacturer_combo)
        layout.addWidget(self._model_name_label)
        layout.addWidget(self._model_combo)
        layout.addWidget(self._model_id_label)
        layout.addWidget(self._model_id_spin)
        return self._model_group

    def _build_connection_group(self) -> QGroupBox:
        self._connection_group = QGroupBox(_("Connection"))
        outer = QVBoxLayout(self._connection_group)

        row = QHBoxLayout()
        self._port_label = QLabel(_("Port"))
        row.addWidget(self._port_label)
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.setToolTip(_("Select the serial port your rig/rotator is connected to."))
        self._port_combo.currentTextChanged.connect(self._on_field_changed)
        self._refresh_button = QToolButton()
        self._refresh_button.setText("⟳")
        self._refresh_button.setToolTip(
            _(
                "Re-scan connected serial ports. Click this if you plugged in the "
                "device after opening the app."
            )
        )
        self._refresh_button.clicked.connect(self._refresh_ports)
        row.addWidget(self._port_combo, stretch=2)
        row.addWidget(self._refresh_button)
        self._speed_label = QLabel(_("Speed"))
        row.addWidget(self._speed_label)
        self._baud_combo = QComboBox()
        self._baud_combo.setEditable(True)
        self._baud_combo.addItems(BAUD_RATES)
        self._baud_combo.setToolTip(
            _("Must match the serial speed set on the radio itself, or the connection will fail.")
        )
        self._baud_combo.currentTextChanged.connect(self._on_field_changed)
        row.addWidget(self._baud_combo, stretch=1)
        outer.addLayout(row)

        usb_row = QHBoxLayout()
        self._usb_hotplug_checkbox = QCheckBox(
            _("Auto-start/stop this profile with this USB device")
        )
        self._usb_hotplug_checkbox.setToolTip(
            _(
                "Plug in the device and select its port above first, then turn this "
                "on: ctld-launcher will remember that USB device and automatically "
                "start this profile whenever it's plugged in, and stop it when "
                "unplugged. Only works while ctld-launcher itself is running."
            )
        )
        self._usb_hotplug_checkbox.toggled.connect(self._on_field_changed)
        usb_row.addWidget(self._usb_hotplug_checkbox)
        self._usb_hotplug_status_label = QLabel()
        usb_row.addWidget(self._usb_hotplug_status_label, stretch=1)
        outer.addLayout(usb_row)

        self._civ_widget = QWidget()
        civ_row = QHBoxLayout(self._civ_widget)
        civ_row.setContentsMargins(0, 0, 0, 0)
        self._civ_label = QLabel(_("ICOM CIV address"))
        civ_row.addWidget(self._civ_label)
        self._civ_address_edit = QLineEdit()
        self._civ_address_edit.setPlaceholderText("A2")
        self._civ_address_edit.setToolTip(
            _(
                "For ICOM rigs, enter the CIV address exactly as shown on the radio "
                "(e.g. A2). Leave blank for other manufacturers."
            )
        )
        self._civ_address_edit.editingFinished.connect(self._on_field_changed)
        civ_row.addWidget(self._civ_address_edit, stretch=1)
        outer.addWidget(self._civ_widget)

        test_row = QHBoxLayout()
        self._test_connection_button = QPushButton(_("Test connection"))
        self._test_connection_button.setToolTip(
            _("Query once via rigctl/rotctl to check the port, speed, and model settings")
        )
        self._test_connection_button.clicked.connect(self._on_test_connection)
        self._test_connection_result = QLabel()
        test_row.addWidget(self._test_connection_button)
        test_row.addWidget(self._test_connection_result, stretch=1)
        outer.addLayout(test_row)

        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setText(_("Advanced (data bits, parity, flow control)"))
        self._advanced_toggle.setToolTip(
            _("Usually not needed. Only for rigs/rotators that require non-default settings.")
        )
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._advanced_toggle.clicked.connect(self._on_advanced_toggled)
        outer.addWidget(self._advanced_toggle)

        advanced_tooltip = _(
            'Usually fine left as "(Not set)". Only change if your rig/rotator\'s '
            "manual specifies a particular value."
        )
        self._advanced_widget = QWidget()
        advanced_row = QHBoxLayout(self._advanced_widget)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        self._data_bits_combo = QComboBox()
        self._data_bits_combo.addItems(_data_bits_options())
        self._data_bits_combo.setToolTip(advanced_tooltip)
        self._data_bits_combo.currentTextChanged.connect(self._on_field_changed)
        self._stop_bits_combo = QComboBox()
        self._stop_bits_combo.addItems(_stop_bits_options())
        self._stop_bits_combo.setToolTip(advanced_tooltip)
        self._stop_bits_combo.currentTextChanged.connect(self._on_field_changed)
        self._parity_combo = QComboBox()
        self._parity_combo.addItems(_parity_options())
        self._parity_combo.setToolTip(advanced_tooltip)
        self._parity_combo.currentTextChanged.connect(self._on_field_changed)
        self._handshake_combo = QComboBox()
        self._handshake_combo.addItems(_handshake_options())
        self._handshake_combo.setToolTip(advanced_tooltip)
        self._handshake_combo.currentTextChanged.connect(self._on_field_changed)
        self._data_bits_label = QLabel(_("Data bits"))
        self._stop_bits_label = QLabel(_("Stop bits"))
        self._parity_label = QLabel(_("Parity"))
        self._handshake_label = QLabel(_("Flow control"))
        for label, widget in (
            (self._data_bits_label, self._data_bits_combo),
            (self._stop_bits_label, self._stop_bits_combo),
            (self._parity_label, self._parity_combo),
            (self._handshake_label, self._handshake_combo),
        ):
            advanced_row.addWidget(label)
            advanced_row.addWidget(widget)
        self._advanced_widget.setVisible(False)
        outer.addWidget(self._advanced_widget)
        return self._connection_group

    def _build_network_group(self) -> QGroupBox:
        self._network_group = QGroupBox(_("Network"))
        layout = QHBoxLayout(self._network_group)
        self._listen_address_label = QLabel(_("Listen address"))
        layout.addWidget(self._listen_address_label)
        self._listen_address_edit = QLineEdit()
        self._listen_address_edit.setToolTip(
            _(
                "Usually leave as 127.0.0.1 (only software on this same PC can connect). "
                "Change to 0.0.0.0 to also allow other PCs on your LAN to connect."
            )
        )
        self._listen_address_edit.editingFinished.connect(self._on_field_changed)
        self._listen_port_label = QLabel(_("Port"))
        layout.addWidget(self._listen_port_label)
        self._listen_port_spin = QSpinBox()
        self._listen_port_spin.setRange(1, 65535)
        self._listen_port_spin.valueChanged.connect(self._on_field_changed)
        layout.addWidget(self._listen_address_edit, stretch=1)
        layout.addWidget(self._listen_port_spin)
        return self._network_group

    def _build_debug_group(self) -> QGroupBox:
        self._debug_group = QGroupBox(_("Debug"))
        layout = QHBoxLayout(self._debug_group)
        self._debug_level_combo = QComboBox()
        self._debug_level_combo.addItems(_debug_levels())
        self._debug_level_combo.setToolTip(
            _('Raise this for more detailed logs. Leave as "Normal" unless troubleshooting.')
        )
        self._debug_level_combo.currentIndexChanged.connect(self._on_field_changed)
        self._log_file_edit = QLineEdit()
        self._log_file_edit.setPlaceholderText(_("Log file path (optional)"))
        self._log_file_edit.setToolTip(
            _(
                "Save rigctld/rotctld's output to this file, if you want a record of it. "
                "The app works fine with this left blank."
            )
        )
        self._log_file_edit.editingFinished.connect(self._on_field_changed)
        self._browse_button = QPushButton(_("Browse…"))
        self._browse_button.clicked.connect(self._browse_log_file)
        layout.addWidget(self._debug_level_combo)
        layout.addWidget(self._log_file_edit, stretch=1)
        layout.addWidget(self._browse_button)
        return self._debug_group

    def _build_extra_args_group(self) -> QGroupBox:
        self._extra_args_group = QGroupBox(_("Extra options (advanced)"))
        layout = QVBoxLayout(self._extra_args_group)
        self._extra_args_edit = QLineEdit()
        self._extra_args_edit.setToolTip(
            _("Additional command-line options passed to rigctld/rotctld (advanced).")
        )
        self._extra_args_edit.setStyleSheet("font-family: monospace;")
        self._extra_args_edit.editingFinished.connect(self._on_field_changed)
        layout.addWidget(self._extra_args_edit)
        return self._extra_args_group

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

    def _build_sidebar_row_widget(self, profile: Profile) -> tuple[QWidget, QLabel, ToggleSwitch]:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(4, 2, 4, 2)
        name_label = QLabel(profile.name)
        row_layout.addWidget(name_label, stretch=1)
        toggle = ToggleSwitch()
        toggle.setToolTip(_("Start this profile automatically when the app launches"))
        toggle.setChecked(profile.auto_start)
        toggle.toggled.connect(functools.partial(self._on_profile_autostart_toggled, profile.id))
        row_layout.addWidget(toggle)
        return row_widget, name_label, toggle

    def _add_sidebar_item(self, profile: Profile) -> None:
        item = QListWidgetItem()
        item.setIcon(status_dot_icon(self.is_running(profile.id)))
        item.setData(Qt.ItemDataRole.UserRole, profile.id)
        self._list.addItem(item)
        row_widget, name_label, toggle = self._build_sidebar_row_widget(profile)
        item.setSizeHint(row_widget.sizeHint())
        self._list.setItemWidget(item, row_widget)
        self._sidebar_name_labels[profile.id] = name_label
        self._sidebar_autostart_toggles[profile.id] = toggle

    def _refresh_sidebar_item(self, profile: Profile) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == profile.id:
                item.setIcon(status_dot_icon(self.is_running(profile.id)))
                label = self._sidebar_name_labels.get(profile.id)
                if label is not None:
                    label.setText(profile.name)
                toggle = self._sidebar_autostart_toggles.get(profile.id)
                if toggle is not None:
                    toggle.blockSignals(True)
                    toggle.setChecked(profile.auto_start)
                    toggle.blockSignals(False)
                return

    def _on_profile_autostart_toggled(self, profile_id: str, checked: bool) -> None:
        profile = self._find_profile(profile_id)
        if profile is None:
            return
        profile.auto_start = checked
        self._store.save(self._profiles)

    def _add_profile(self, kind: ProfileKind) -> None:
        model_id = default_model_id(kind)
        if kind == ProfileKind.RIG:
            profile = Profile.new_rig(name=_("New Rig"), model_id=model_id)
        else:
            profile = Profile.new_rotator(name=_("New Rotator"), model_id=model_id)
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
        self._refresh_usb_tracking()
        row = self._list.currentRow()
        item = self._list.item(row)
        if item is not None:
            self._list.removeItemWidget(item)
        self._list.takeItem(row)
        self._sidebar_name_labels.pop(profile.id, None)
        self._sidebar_autostart_toggles.pop(profile.id, None)

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            if checked:
                self._autostart.enable()
            else:
                self._autostart.disable()
        except AutostartError as exc:
            QMessageBox.warning(self, _("Couldn't set autostart"), str(exc))
            self._autostart_checkbox.blockSignals(True)
            self._autostart_checkbox.setChecked(not checked)
            self._autostart_checkbox.blockSignals(False)

    def _on_quit_clicked(self) -> None:
        self._quit_app()

    def _quit_app(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_language_changed(self) -> None:
        lang = self._language_combo.currentData()
        if lang is None or lang == get_language():
            return
        set_language(lang)
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """Re-apply _() to every already-built widget after set_language().

        Qt doesn't auto-retranslate existing widgets — each one needs its
        text set again explicitly (the standard Qt Designer retranslateUi()
        pattern). Combo option lists (debug level, data bits/parity/
        handshake) are cleared and rebuilt with the newly translated
        labels; _populate_form() below then re-derives the correct
        selection from the profile's actual stored values, so it isn't
        lost when e.g. "(Not set)"/"(未指定)" changes text.
        """
        if self._update_button_state == "available" and self._update_latest_version:
            self._update_button.setText(
                _("↑ Update to v{ver} available").format(ver=self._update_latest_version)
            )
        elif self._update_button_state == "idle":
            self._update_button.setText(_("Check for updates"))
        self._add_rig_button.setText(_("+ Rig"))
        self._add_rotator_button.setText(_("+ Rotator"))
        self._remove_button.setText(_("Remove"))
        self._autostart_checkbox.setText(_("Start at login"))
        self._autostart_checkbox.setToolTip(
            _(
                "Starts this app itself in the tray at login. To also start individual "
                "profiles automatically, enable the toggle next to each profile in "
                "the list on the left."
            )
        )
        for toggle in self._sidebar_autostart_toggles.values():
            toggle.setToolTip(_("Start this profile automatically when the app launches"))
        self._minimize_button.setText(_("Minimize to tray"))
        self._minimize_button.setToolTip(
            _(
                "Hides this window; rigctld/rotctld keep running in the background. "
                "Click the tray icon to bring it back."
            )
        )
        self._quit_button.setText(_("Quit ctld-launcher"))
        self._quit_button.setToolTip(
            _(
                "Stops all running rigctld/rotctld processes and closes the app "
                "completely, including the tray icon."
            )
        )

        self._name_edit.setToolTip(_("Enter any name you like for this profile."))
        self._command_label.setText(_("Command"))
        selected = self._selected_profile()
        self._update_start_button_label(selected is not None and self.is_running(selected.id))
        self._stop_button.setText(_("Stop"))
        self._restart_button.setText(_("Restart"))
        self._log_label.setText(_("Log"))

        self._model_group.setTitle(_("Model"))
        self._manufacturer_label.setText(_("Manufacturer"))
        self._manufacturer_combo.setToolTip(
            _("Select the manufacturer of your rig/rotator. You can type to filter the list.")
        )
        self._model_name_label.setText(_("Model name"))
        self._model_combo.setToolTip(_("Select the model of your rig/rotator."))
        self._model_id_label.setText(_("Model ID"))
        self._model_id_spin.setToolTip(
            _(
                "Hamlib's numeric model ID. Filled in automatically when you pick a "
                "manufacturer/model above; you can also type it directly for a model "
                "not in the list."
            )
        )

        self._connection_group.setTitle(_("Connection"))
        self._port_label.setText(_("Port"))
        self._port_combo.setToolTip(_("Select the serial port your rig/rotator is connected to."))
        self._refresh_button.setToolTip(
            _(
                "Re-scan connected serial ports. Click this if you plugged in the "
                "device after opening the app."
            )
        )
        self._speed_label.setText(_("Speed"))
        self._baud_combo.setToolTip(
            _("Must match the serial speed set on the radio itself, or the connection will fail.")
        )
        self._usb_hotplug_checkbox.setText(_("Auto-start/stop this profile with this USB device"))
        self._usb_hotplug_checkbox.setToolTip(
            _(
                "Plug in the device and select its port above first, then turn this "
                "on: ctld-launcher will remember that USB device and automatically "
                "start this profile whenever it's plugged in, and stop it when "
                "unplugged. Only works while ctld-launcher itself is running."
            )
        )
        self._civ_label.setText(_("ICOM CIV address"))
        self._civ_address_edit.setToolTip(
            _(
                "For ICOM rigs, enter the CIV address exactly as shown on the radio "
                "(e.g. A2). Leave blank for other manufacturers."
            )
        )
        self._test_connection_button.setText(_("Test connection"))
        self._test_connection_button.setToolTip(
            _("Query once via rigctl/rotctl to check the port, speed, and model settings")
        )
        self._advanced_toggle.setText(_("Advanced (data bits, parity, flow control)"))
        self._advanced_toggle.setToolTip(
            _("Usually not needed. Only for rigs/rotators that require non-default settings.")
        )
        advanced_tooltip = _(
            'Usually fine left as "(Not set)". Only change if your rig/rotator\'s '
            "manual specifies a particular value."
        )
        self._data_bits_label.setText(_("Data bits"))
        self._data_bits_combo.setToolTip(advanced_tooltip)
        self._stop_bits_label.setText(_("Stop bits"))
        self._stop_bits_combo.setToolTip(advanced_tooltip)
        self._parity_label.setText(_("Parity"))
        self._parity_combo.setToolTip(advanced_tooltip)
        self._handshake_label.setText(_("Flow control"))
        self._handshake_combo.setToolTip(advanced_tooltip)

        self._network_group.setTitle(_("Network"))
        self._listen_address_label.setText(_("Listen address"))
        self._listen_address_edit.setToolTip(
            _(
                "Usually leave as 127.0.0.1 (only software on this same PC can connect). "
                "Change to 0.0.0.0 to also allow other PCs on your LAN to connect."
            )
        )
        self._listen_port_label.setText(_("Port"))

        self._debug_group.setTitle(_("Debug"))
        self._debug_level_combo.setToolTip(
            _('Raise this for more detailed logs. Leave as "Normal" unless troubleshooting.')
        )
        self._log_file_edit.setPlaceholderText(_("Log file path (optional)"))
        self._log_file_edit.setToolTip(
            _(
                "Save rigctld/rotctld's output to this file, if you want a record of it. "
                "The app works fine with this left blank."
            )
        )
        self._browse_button.setText(_("Browse…"))

        self._extra_args_group.setTitle(_("Extra options (advanced)"))
        self._extra_args_edit.setToolTip(
            _("Additional command-line options passed to rigctld/rotctld (advanced).")
        )

        for combo, options in (
            (self._debug_level_combo, _debug_levels()),
            (self._data_bits_combo, _data_bits_options()),
            (self._stop_bits_combo, _stop_bits_options()),
            (self._parity_combo, _parity_options()),
            (self._handshake_combo, _handshake_options()),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(options)
            combo.blockSignals(False)

        profile = self._selected_profile()
        if profile is not None:
            self._populate_form(profile)
        else:
            self._update_status_and_buttons()

    def start_autostart_profiles(self) -> None:
        """Start every profile flagged auto_start. Called once at app launch."""
        for profile in self._profiles:
            if profile.auto_start:
                self._start_profile(profile)

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
            self._usb_hotplug_checkbox,
            self._civ_address_edit,
            self._test_connection_button,
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
            self._test_connection_result.setText("")
            self._test_connection_button.setStyleSheet("")

            models = self._models_for_kind(profile.kind)
            self._manufacturer_combo.clear()
            self._manufacturer_combo.addItems(list(models))
            _refresh_combo_search(self._manufacturer_combo)
            manufacturer = self._manufacturer_for_model(models, profile.model_id)
            if manufacturer is not None:
                _set_combo_text(self._manufacturer_combo, manufacturer)
            self._populate_model_combo(
                models, self._manufacturer_combo.currentText(), profile.model_id
            )
            self._model_id_spin.setValue(profile.model_id)

            if not self._port_combo.count():
                self._refresh_ports()
            self._port_combo.setCurrentText(profile.port)
            baud_text = str(profile.serial_speed) if profile.serial_speed else ""
            self._baud_combo.setCurrentText(baud_text)

            self._usb_hotplug_checkbox.setChecked(profile.usb_hotplug)
            self._update_usb_hotplug_status(profile)

            self._civ_widget.setVisible(profile.kind == ProfileKind.RIG)
            self._civ_address_edit.setText(profile.civ_address or "")

            data_bits_text = str(profile.data_bits) if profile.data_bits else _unset_label()
            stop_bits_text = str(profile.stop_bits) if profile.stop_bits else _unset_label()
            _set_combo_text(self._data_bits_combo, data_bits_text)
            _set_combo_text(self._stop_bits_combo, stop_bits_text)
            _set_combo_text(self._parity_combo, profile.serial_parity or _unset_label())
            _set_combo_text(self._handshake_combo, profile.serial_handshake or _unset_label())

            self._listen_address_edit.setText(profile.listen_address)
            self._listen_port_spin.setValue(profile.listen_port)
            self._listen_port_spin.setToolTip(self._listen_port_tooltip(profile.kind))
            self._debug_level_combo.setCurrentIndex(profile.debug_level)
            self._log_file_edit.setText(profile.log_file or "")
            self._extra_args_edit.setText(shlex.join(profile.extra_args))
        finally:
            self._updating_form = False
        self._update_status_and_buttons()

    def _listen_port_tooltip(self, kind: ProfileKind) -> str:
        if kind == ProfileKind.RIG:
            return _(
                "Default is 4532 for rigs. Match your rig control software's TCP "
                "port to this number."
            )
        return _(
            "Default is 4533 for rotators. Match your rotator control software's "
            "TCP port to this number."
        )

    def _update_usb_hotplug_status(self, profile: Profile) -> None:
        if profile.usb_vid is not None and profile.usb_pid is not None:
            self._usb_hotplug_status_label.setText(_("(USB device identified)"))
        else:
            self._usb_hotplug_status_label.setText(_("(no USB device identified yet)"))

    def _models_for_kind(self, kind: ProfileKind) -> dict[str, list[tuple[int, str]]]:
        try:
            executable = self._executable_resolver(kind)
        except ExecutableNotFoundError:
            return {}
        return models_by_manufacturer(executable)

    def _manufacturer_for_model(
        self, models: dict[str, list[tuple[int, str]]], model_id: int
    ) -> str | None:
        for manufacturer, entries in models.items():
            if any(mid == model_id for mid, _name in entries):
                return manufacturer
        return None

    def _populate_model_combo(
        self,
        models: dict[str, list[tuple[int, str]]],
        manufacturer: str,
        model_id: int | None = None,
    ) -> None:
        """Rebuild the model dropdown for `manufacturer`.

        When `model_id` is given, the entry matching it is explicitly
        selected — without this, Qt just defaults to index 0 on every
        rebuild, so the displayed model name would drift away from the
        profile's actual model_id (e.g. reverting to some other model)
        every time the form is repopulated (profile reselect, language
        switch, USB hotplug reconnect), even though model_id itself never
        changed.
        """
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for mid, name in models.get(manufacturer, []):
            self._model_combo.addItem(name, userData=mid)
        _refresh_combo_search(self._model_combo)
        if model_id is not None:
            index = self._model_combo.findData(model_id)
            if index >= 0:
                self._model_combo.setCurrentIndex(index)
        self._model_combo.blockSignals(False)

    def _on_manufacturer_changed(self) -> None:
        if self._updating_form:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        models = self._models_for_kind(profile.kind)
        self._populate_model_combo(models, self._manufacturer_combo.currentText())
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

    def _set_test_connection_result(self, message: str, success: bool) -> None:
        self._test_connection_result.setText(message)
        self._test_connection_button.setStyleSheet(
            TEST_SUCCESS_STYLE if success else TEST_FAILURE_STYLE
        )

    def _on_test_connection(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return

        if self.is_running(profile.id):
            running_command = self._processes[profile.id].command
            actual_port = serial_port_from_command(running_command)
            if (
                profile.port
                and actual_port
                and profile.port.strip().casefold() != actual_port.strip().casefold()
            ):
                message = _(
                    "✗ The running process is using port {actual_port}, "
                    "but {selected_port} is selected. Restart to apply "
                    "the new port."
                ).format(actual_port=actual_port, selected_port=profile.port)
                self._set_test_connection_result(message, success=False)
                return
            # Once the daemon is running it already holds the serial port
            # open, so probe it directly over the network (probe_daemon())
            # instead of opening the port a second time -- see that
            # function's docstring for why this is a plain read, not
            # Hamlib's own NET rigctl/rotctl client.
            self._test_connection_button.setEnabled(False)
            self._test_connection_button.setText(_("Testing…"))
            self._test_connection_button.setStyleSheet("")
            self._test_connection_result.setText("")
            responded, output = probe_daemon(profile)
            if responded:
                self._set_test_connection_result(
                    _("✓ Response: {output}").format(output=output), success=True
                )
            else:
                self._set_test_connection_result(
                    _("✗ Timed out (no response from daemon)"), success=False
                )
            self._test_connection_button.setEnabled(True)
            self._test_connection_button.setText(_("Test connection"))
            return

        try:
            executable = self._test_executable_resolver(profile.kind)
        except ExecutableNotFoundError as exc:
            self._set_test_connection_result(_("✗ {error}").format(error=exc), success=False)
            return
        command = build_test_command(executable, profile)
        self._test_connection_button.setEnabled(False)
        self._test_connection_button.setText(_("Testing…"))
        self._test_connection_button.setStyleSheet("")
        self._test_connection_result.setText("")
        try:
            result = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=NO_WINDOW_FLAGS,
            )
        except subprocess.TimeoutExpired:
            self._set_test_connection_result(
                _("✗ Timed out (no response from port)"), success=False
            )
        except OSError as exc:
            self._set_test_connection_result(
                _("✗ Couldn't run: {error}").format(error=exc), success=False
            )
        else:
            output = (result.stdout or result.stderr).strip()
            if result.returncode == 0 and output:
                message = _("✓ Response: {output}").format(output=output)
                self._set_test_connection_result(message, success=True)
            else:
                self._set_test_connection_result(
                    _("✗ {output}").format(output=output or _("Error")), success=False
                )
        finally:
            self._test_connection_button.setEnabled(True)
            self._test_connection_button.setText(_("Test connection"))

    def _browse_log_file(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Select log file"),
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
        profile.usb_hotplug = self._usb_hotplug_checkbox.isChecked()
        if profile.usb_hotplug:
            identity = identity_for_port(profile.port, self._usb_ports_resolver())
            if identity is not None:
                profile.usb_vid = identity.vid
                profile.usb_pid = identity.pid
                profile.usb_serial_number = identity.serial_number
                profile.usb_preferred_device = profile.port
        self._update_usb_hotplug_status(profile)
        self._refresh_usb_tracking()
        profile.civ_address = self._civ_address_edit.text() or None
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
            self._crash_restart_attempts.pop(profile.id, None)
            self._start_profile(profile)

    def _on_stop(self) -> None:
        if self._current_id is not None:
            self._stop_profile(self._current_id)

    def _on_restart(self) -> None:
        profile = self._selected_profile()
        if profile is not None:
            self._crash_restart_attempts.pop(profile.id, None)
            self._stop_profile(profile.id)
            self._start_profile(profile)

    def toggle_process(self, profile_id: str) -> None:
        if self.is_running(profile_id):
            self._stop_profile(profile_id)
        else:
            profile = self._find_profile(profile_id)
            if profile is not None:
                self._crash_restart_attempts.pop(profile_id, None)
                self._start_profile(profile)

    def _start_profile(self, profile: Profile) -> None:
        if self.is_running(profile.id):
            return
        try:
            executable = self._executable_resolver(profile.kind)
        except ExecutableNotFoundError as exc:
            QMessageBox.warning(self, _("Can't start"), str(exc))
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
        # Tell _on_process_exited this exit was requested, not a crash, so
        # it doesn't try to "helpfully" restart what was just stopped.
        self._intentional_stop.add(profile_id)
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

    # ------------------------------------------------------------------ #
    # App self-update (see core/app_update.py)
    # ------------------------------------------------------------------ #
    def check_for_updates(self, manual: bool = False) -> None:
        """Kick off a background GitHub Releases check.

        Called once from main.py after startup (manual=False) so a slow/
        failed network check never delays showing the window, and again on
        every click of the sidebar button while it's in its idle "Check for
        updates" state (manual=True). Only manual checks report failure or
        "already up to date" back to the user via a dialog -- the automatic
        startup check stays silent either way, exactly as before.
        """
        self._update_check_is_manual = manual
        self._update_button_state = "checking"
        self._update_button.setEnabled(False)
        self._update_button.setText(_("Checking for updates…"))
        worker = UpdateCheckWorker(self)
        worker.result.connect(self._on_update_check_result)
        worker.not_found.connect(self._on_update_check_not_found)
        worker.start()
        self._update_check_worker = worker

    def _reset_update_button_idle(self) -> None:
        self._update_button_state = "idle"
        self._update_button.setText(_("Check for updates"))
        self._update_button.setEnabled(True)

    def _on_update_check_result(self, version: str, url: str) -> None:
        if not is_newer_version(version, get_version()):
            self._reset_update_button_idle()
            if self._update_check_is_manual:
                QMessageBox.information(
                    self,
                    _("Check for updates"),
                    _("You're already using the latest version."),
                )
            return
        self._update_latest_version = version
        self._update_download_url = url
        self._update_button_state = "available"
        self._update_button.setText(_("↑ Update to v{ver} available").format(ver=version))
        self._update_button.setEnabled(True)

    def _on_update_check_not_found(self, error: str = "") -> None:
        self._reset_update_button_idle()
        if not self._update_check_is_manual:
            return
        message = _("Couldn't check for updates. Please check your internet connection.")
        if error:
            message += "\n\n" + _("Details: {error}").format(error=error)
        message += "\n\n" + _("You can also check manually at {url}").format(url=GITHUB_RELEASES)
        QMessageBox.warning(self, _("Check for updates"), message)

    def _on_update_button_clicked(self) -> None:
        if self._update_button_state == "idle":
            self.check_for_updates(manual=True)
            return
        if self._update_button_state != "available":
            return
        self._start_update_install()

    def _start_update_install(self) -> None:
        if self._update_download_url is None or self._update_latest_version is None:
            return
        answer = QMessageBox.question(
            self,
            _("Update ctld-launcher"),
            _(
                "Download and install ctld-launcher v{ver} now? The app will "
                "need to restart to finish."
            ).format(ver=self._update_latest_version),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if platform.system() == "Windows":
            # The NSIS installer overwrites rigctld/rotctld and their Hamlib
            # DLLs in place; if a profile is still running when it starts,
            # those files stay locked and the install partially fails
            # (confirmed on real hardware: some DLLs couldn't be
            # overwritten). Stop everything now, well before the download
            # even finishes, rather than racing the installer's own
            # `taskkill` of ctld-launcher.exe itself, which never touches
            # rigctld.exe/rotctld.exe. Linux/macOS don't need this: their
            # install step replaces files in place while still running is
            # fine on POSIX, so profiles keep running until the user
            # actually chooses to restart (see _on_update_install_finished).
            self.stop_all()

        self._update_button_state = "downloading"
        self._update_button.setEnabled(False)
        self._update_button.setText(_("Downloading…"))
        worker = UpdateInstallWorker(self._update_download_url, self._update_latest_version)
        worker.progress.connect(self._on_update_install_progress)
        worker.finished.connect(self._on_update_install_finished)
        worker.start()
        self._update_install_worker = worker

    def _on_update_install_progress(self, message: str) -> None:
        self._update_button.setText(message)

    def _on_update_install_finished(self, success: bool, outcome: str, message: str) -> None:
        if not success:
            self._update_button_state = "available"
            self._update_button.setEnabled(True)
            self._update_button.setText(
                _("↑ Update to v{ver} available").format(ver=self._update_latest_version)
            )
            QMessageBox.warning(
                self,
                _("Update failed"),
                _(
                    "Couldn't install the update: {error}\n\nYou can also download "
                    "it manually from {url}"
                ).format(error=message, url=GITHUB_RELEASES),
            )
            return

        self._update_button_state = "installed"
        self._update_button.setText(_("✓ Updated — restart to finish"))

        if outcome == "installer_launched":
            QMessageBox.information(
                self,
                _("Update ready"),
                _(
                    "The installer has started. ctld-launcher needs to close now "
                    "so it can finish installing."
                ),
            )
            self._quit_app()
            return

        answer = QMessageBox.question(
            self,
            _("Update ready"),
            _(
                "The update is ready. Restart now to finish? Any running "
                "profiles will be stopped.\n(You can also restart later — the "
                "update is already applied.)"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._restart_app()

    def _restart_app(self) -> None:
        subprocess.Popen([sys.executable])  # noqa: S603
        self._quit_app()

    # ------------------------------------------------------------------ #
    # USB hotplug (see core/usb_watch.py for why this is app-level polling
    # rather than an OS-level service like Linux's udev+systemd)
    # ------------------------------------------------------------------ #
    def _refresh_usb_tracking(self) -> None:
        tracked = {
            profile.id: UsbIdentity(
                vid=profile.usb_vid,
                pid=profile.usb_pid,
                serial_number=profile.usb_serial_number,
                preferred_device=profile.usb_preferred_device,
            )
            for profile in self._profiles
            if profile.usb_hotplug and profile.usb_vid is not None and profile.usb_pid is not None
        }
        self._usb_tracker.set_tracked(tracked)
        if tracked:
            if not self._usb_timer.isActive():
                self._usb_timer.start(USB_POLL_INTERVAL_MS)
        else:
            self._usb_timer.stop()

    def _poll_usb_hotplug(self) -> None:
        # list_ports.comports() talks to the OS's device enumeration (IOKit
        # on macOS, WMI on Windows, udev on Linux); a wedged USB-serial
        # driver can make it block indefinitely. Running it here on the GUI
        # thread would freeze the whole window -- including the Stop/Restart
        # buttons someone would reach for to recover -- so it runs on a
        # throwaway thread instead and reports back via a queued signal.
        # in_flight guards against piling up threads if one poll is still
        # stuck when the next timer tick fires.
        if self._usb_poll_in_flight:
            return
        self._usb_poll_in_flight = True
        resolver = self._usb_ports_resolver
        signal = self._usb_ports_ready

        def _poll() -> None:
            try:
                ports = resolver()
            except OSError:
                ports = []
            signal.emit(ports)

        threading.Thread(target=_poll, daemon=True).start()

    def _on_usb_ports_ready(self, ports: list[ListPortInfo]) -> None:
        self._usb_poll_in_flight = False
        connected, disconnected = self._usb_tracker.poll(ports)
        for profile_id, port in connected.items():
            profile = self._find_profile(profile_id)
            if profile is None:
                continue
            if profile.port != port:
                profile.port = port
                self._store.save(self._profiles)
                if profile_id == self._current_id:
                    self._populate_form(profile)
            self._start_profile(profile)
        for profile_id in disconnected:
            self._stop_profile(profile_id)

    # ------------------------------------------------------------------ #
    # Health check / auto-restart -- a running rigctld/rotctld can go on
    # accepting the TCP connection while being wedged internally (typically
    # blocked in a kernel-level read on a stuck USB-serial driver), so
    # "process is still alive" alone doesn't mean "still working". This
    # periodically probes each running daemon the same way the "Test
    # connection" button does (a direct read against the daemon, see
    # probe_daemon()) and, if it stops responding, kills and respawns it
    # automatically -- the same remedy a user would otherwise have to
    # notice and apply by hand.
    #
    # probe_daemon() talks to the daemon directly instead of through
    # Hamlib's own NET rigctl/rotctl client (rigctl/rotctl -m 2, the
    # previous approach here) -- that client's connection setup sends a "v"
    # (get_vfo) query as a side effect, and rigctld answers it by querying
    # the physical rig's displayed VFO and overwriting the daemon's single,
    # connection-shared current_vfo with whatever it gets back. For rigs
    # like the FTX-1 that can end up displaying Sub mid-session during
    # continuous split/cross-band Doppler tracking, a health-check poll
    # landing at the wrong moment silently redirected every subsequent
    # VFO-less frequency write from every OTHER connected client (FBSAT59,
    # GPredict, ...) to Sub instead of Main. See probe_daemon()'s docstring
    # for the full trace (found via a live FO-29/FTX-1 investigation with
    # FBSAT59).
    # ------------------------------------------------------------------ #
    def _run_health_checks(self) -> None:
        signal = self._health_check_result
        for profile_id, process in list(self._processes.items()):
            if (
                not process.is_running
                or profile_id in self._health_check_in_flight
                or profile_id in self._auto_restarting
                or profile_id in self._intentional_stop
            ):
                # The last case is a profile someone (a person, or a prior
                # auto-restart attempt) tried to stop but couldn't reap yet
                # -- don't "helpfully" revive something that was asked to
                # stop just because it's still technically running.
                continue
            profile = self._find_profile(profile_id)
            if profile is None:
                continue
            self._health_check_in_flight.add(profile_id)

            def _check(profile_id: str = profile_id, profile: Profile = profile) -> None:
                responded, _output = probe_daemon(profile)
                signal.emit(profile_id, responded)

            threading.Thread(target=_check, daemon=True).start()

    def _on_health_check_result(self, profile_id: str, responded_ok: bool) -> None:
        self._health_check_in_flight.discard(profile_id)
        if responded_ok:
            self._health_check_failures.pop(profile_id, None)
            # Proof of life -- forgive any earlier unexpected-exit history
            # so a crash long ago doesn't count against a now-healthy run.
            self._crash_restart_attempts.pop(profile_id, None)
            return
        if not self.is_running(profile_id):
            self._health_check_failures.pop(profile_id, None)
            return
        failures = self._health_check_failures.get(profile_id, 0) + 1
        if failures < HEALTH_CHECK_FAILURE_THRESHOLD:
            self._health_check_failures[profile_id] = failures
            return
        self._health_check_failures.pop(profile_id, None)
        self._auto_restart_profile(profile_id)

    def _auto_restart_profile(self, profile_id: str) -> None:
        process = self._processes.get(profile_id)
        if process is None:
            return
        self._auto_restarting.add(profile_id)
        self._intentional_stop.add(profile_id)
        self._log_line.emit(
            profile_id,
            _("[ctld-launcher] Not responding to health checks -- restarting automatically…"),
        )
        signal = self._auto_restart_stopped

        def _stop_in_background() -> None:
            # process.stop() is safe to call off the GUI thread: it only
            # touches the subprocess.Popen object and joins the reader
            # thread, no Qt widgets. Doing it here instead of on the GUI
            # thread is the whole point -- a wedged process can still take
            # up to a few seconds (or, rarely, never) to actually die, and
            # that must not freeze the window the way a manual Restart
            # click could before.
            process.stop()
            signal.emit(profile_id)

        threading.Thread(target=_stop_in_background, daemon=True).start()

    def _on_auto_restart_stopped(self, profile_id: str) -> None:
        self._auto_restarting.discard(profile_id)
        profile = self._find_profile(profile_id)
        if profile is None:
            return
        if self.is_running(profile_id):
            # Killing it didn't work either -- almost certainly stuck in an
            # uninterruptible kernel wait that only the OS/driver can clear.
            # Nothing more to do from here; the next health check will try
            # again, and will keep retrying every cycle in case the OS lets
            # go later. Warn only once per stuck episode so the log doesn't
            # fill up with the same line every few seconds.
            if profile_id not in self._auto_restart_stuck_warned:
                self._auto_restart_stuck_warned.add(profile_id)
                self._log_line.emit(
                    profile_id,
                    _(
                        "[ctld-launcher] Still unresponsive after attempting to stop it. "
                        "This may require quitting the app entirely."
                    ),
                )
            return
        self._auto_restart_stuck_warned.discard(profile_id)
        self._start_profile(profile)

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

    def _on_process_exited(self, profile_id: str, exit_code: int) -> None:
        profile = self._find_profile(profile_id)
        if profile is not None:
            self._refresh_sidebar_item(profile)
            if profile_id == self._current_id:
                self._update_status_and_buttons()
        self.state_changed.emit()

        if profile_id in self._intentional_stop:
            # We (a person, or an auto-restart's own stop attempt) asked
            # for this -- not a crash, nothing to auto-restart here.
            self._intentional_stop.discard(profile_id)
            return
        if profile is None:
            return
        # Exited entirely on its own -- a genuine crash. Unlike a hang,
        # this is detected instantly (it's the process's own exit event,
        # not a poll), so restart it right away, same as systemd's
        # Restart=on-failure. CRASH_RESTART_LIMIT stops a persistently
        # broken launch (e.g. bad arguments) from restart-looping forever.
        attempts = self._crash_restart_attempts.get(profile_id, 0) + 1
        if attempts > CRASH_RESTART_LIMIT:
            self._log_line.emit(
                profile_id,
                _(
                    "[ctld-launcher] Exited unexpectedly {count} times in a row; "
                    "giving up on automatic restart. Check the log above and this "
                    "profile's settings."
                ).format(count=attempts - 1),
            )
            return
        self._crash_restart_attempts[profile_id] = attempts
        self._log_line.emit(
            profile_id,
            _(
                "[ctld-launcher] Exited unexpectedly (exit code {code}); restarting automatically…"
            ).format(code=exit_code),
        )
        self._start_profile(profile)

    def _update_status_and_buttons(self) -> None:
        profile = self._selected_profile()
        running = profile is not None and self.is_running(profile.id)
        if profile is None:
            self._status_label.setText("")
        elif running:
            process = self._processes[profile.id]
            self._status_label.setText(_("● Running · PID {pid}").format(pid=process.pid))
        else:
            self._status_label.setText(_("○ Stopped"))
        self._start_button.setEnabled(profile is not None and not running)
        self._update_start_button_label(running)
        self._stop_button.setEnabled(running)
        self._restart_button.setEnabled(running)
        self._update_command_preview()

    def _update_start_button_label(self, running: bool) -> None:
        if running:
            self._start_button.setText(_("Running"))
            self._start_button.setStyleSheet(START_BUTTON_RUNNING_STYLE)
        else:
            self._start_button.setText(_("Start"))
            self._start_button.setStyleSheet("")

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
