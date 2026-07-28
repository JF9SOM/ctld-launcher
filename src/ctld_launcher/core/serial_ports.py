from __future__ import annotations

from serial.tools import list_ports


def list_serial_ports() -> list[str]:
    """Return device paths of currently connected serial ports (cross-platform)."""
    return [port.device for port in list_ports.comports()]
