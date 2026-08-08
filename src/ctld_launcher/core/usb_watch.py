"""USB hotplug detection for auto-starting/stopping a profile.

There's no cross-platform equivalent of Linux's udev+systemd device-triggered
service activation — macOS (IOKit) and Windows (WM_DEVICECHANGE/WMI) would
each need a completely separate, OS-level implementation to react to a
device appearing even when ctld-launcher itself isn't running. Instead, this
polls pyserial's list_ports.comports() while the app is running and matches
ports by USB VID:PID (+ serial number when available, to disambiguate two
identical adapters) rather than by device path, since device paths
(/dev/ttyUSB0, COM3, ...) aren't stable across replugs on every platform.

This only works while ctld-launcher is running — accepted trade-off, see
CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _PortInfo(Protocol):
    device: str
    vid: int | None
    pid: int | None
    serial_number: str | None


@dataclass(frozen=True)
class UsbIdentity:
    vid: int
    pid: int
    serial_number: str | None = None
    # Device path pinned at the moment the user picked "this is the right
    # one" (see find_port()) -- some radios (e.g. Yaesu FTX-1/FT-991) expose
    # their CAT and non-CAT ports as two interfaces of one composite USB
    # device that report the same (or no) serial number, so vid/pid/serial
    # alone can't tell the two apart and either could be matched first.
    preferred_device: str | None = None


def identity_for_port(port: str, ports: list[_PortInfo]) -> UsbIdentity | None:
    """USB identity of a currently connected port, or None if it isn't one
    right now (unplugged, nonexistent path, or a non-USB serial port).
    """
    for info in ports:
        if info.device == port and info.vid is not None and info.pid is not None:
            return UsbIdentity(vid=info.vid, pid=info.pid, serial_number=info.serial_number)
    return None


def find_port(identity: UsbIdentity, ports: list[_PortInfo]) -> str | None:
    """Device path currently matching a USB identity, or None if unplugged.

    When more than one currently-connected port matches vid/pid(+serial) --
    two interfaces of the same composite device that can't be told apart by
    that metadata -- identity.preferred_device (if it's among the matches)
    breaks the tie instead of silently taking whichever sorts first.
    """
    candidates = []
    for info in ports:
        if info.vid == identity.vid and info.pid == identity.pid:
            serial_matches = (
                identity.serial_number is None or info.serial_number == identity.serial_number
            )
            if serial_matches:
                candidates.append(info.device)
    if not candidates:
        return None
    if identity.preferred_device in candidates:
        return identity.preferred_device
    return candidates[0]


class UsbHotplugTracker:
    """Tracks which of several profiles' USB devices are currently plugged
    in across successive poll() calls, so callers only react to *changes*.
    """

    def __init__(self) -> None:
        self._tracked: dict[str, UsbIdentity] = {}
        self._connected_port: dict[str, str] = {}

    def set_tracked(self, tracked: dict[str, UsbIdentity]) -> None:
        self._tracked = dict(tracked)
        self._connected_port = {
            profile_id: port
            for profile_id, port in self._connected_port.items()
            if profile_id in self._tracked
        }

    def poll(self, ports: list[_PortInfo]) -> tuple[dict[str, str], list[str]]:
        """Returns (newly_connected: {profile_id: port}, newly_disconnected: [profile_id])."""
        newly_connected: dict[str, str] = {}
        newly_disconnected: list[str] = []
        for profile_id, identity in self._tracked.items():
            port = find_port(identity, ports)
            if port is not None:
                if self._connected_port.get(profile_id) != port:
                    newly_connected[profile_id] = port
                self._connected_port[profile_id] = port
            elif profile_id in self._connected_port:
                del self._connected_port[profile_id]
                newly_disconnected.append(profile_id)
        return newly_connected, newly_disconnected
