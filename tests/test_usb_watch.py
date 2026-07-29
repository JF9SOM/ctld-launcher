from __future__ import annotations

from dataclasses import dataclass

from ctld_launcher.core.usb_watch import (
    UsbHotplugTracker,
    UsbIdentity,
    find_port,
    identity_for_port,
)


@dataclass
class FakePortInfo:
    device: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None


def test_identity_for_port_returns_none_when_not_connected() -> None:
    assert identity_for_port("/dev/ttyUSB0", []) is None


def test_identity_for_port_returns_none_for_non_usb_serial_port() -> None:
    ports = [FakePortInfo(device="/dev/ttyS0", vid=None, pid=None)]
    assert identity_for_port("/dev/ttyS0", ports) is None


def test_identity_for_port_returns_identity_for_matching_usb_device() -> None:
    ports = [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial_number="AB12")]
    identity = identity_for_port("/dev/ttyUSB0", ports)
    assert identity == UsbIdentity(vid=0x0403, pid=0x6001, serial_number="AB12")


def test_find_port_matches_by_vid_pid_and_serial() -> None:
    identity = UsbIdentity(vid=0x0403, pid=0x6001, serial_number="AB12")
    ports = [
        FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial_number="ZZ99"),
        FakePortInfo(device="/dev/ttyUSB1", vid=0x0403, pid=0x6001, serial_number="AB12"),
    ]
    assert find_port(identity, ports) == "/dev/ttyUSB1"


def test_find_port_ignores_serial_number_when_not_captured() -> None:
    identity = UsbIdentity(vid=0x0403, pid=0x6001, serial_number=None)
    ports = [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001, serial_number="ZZ99")]
    assert find_port(identity, ports) == "/dev/ttyUSB0"


def test_find_port_returns_none_when_unplugged() -> None:
    identity = UsbIdentity(vid=0x0403, pid=0x6001)
    assert find_port(identity, []) is None


def test_tracker_reports_new_connection() -> None:
    tracker = UsbHotplugTracker()
    tracker.set_tracked({"profile-1": UsbIdentity(vid=0x0403, pid=0x6001)})

    connected, disconnected = tracker.poll(
        [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)]
    )

    assert connected == {"profile-1": "/dev/ttyUSB0"}
    assert disconnected == []


def test_tracker_does_not_re_report_already_connected_device() -> None:
    tracker = UsbHotplugTracker()
    tracker.set_tracked({"profile-1": UsbIdentity(vid=0x0403, pid=0x6001)})
    ports = [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)]
    tracker.poll(ports)

    connected, disconnected = tracker.poll(ports)

    assert connected == {}
    assert disconnected == []


def test_tracker_reports_disconnection() -> None:
    tracker = UsbHotplugTracker()
    tracker.set_tracked({"profile-1": UsbIdentity(vid=0x0403, pid=0x6001)})
    tracker.poll([FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)])

    connected, disconnected = tracker.poll([])

    assert connected == {}
    assert disconnected == ["profile-1"]


def test_tracker_reports_reconnect_on_different_port_path() -> None:
    # e.g. the device came back as /dev/ttyUSB1 instead of /dev/ttyUSB0.
    tracker = UsbHotplugTracker()
    tracker.set_tracked({"profile-1": UsbIdentity(vid=0x0403, pid=0x6001)})
    tracker.poll([FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)])
    tracker.poll([])

    connected, _disconnected = tracker.poll(
        [FakePortInfo(device="/dev/ttyUSB1", vid=0x0403, pid=0x6001)]
    )

    assert connected == {"profile-1": "/dev/ttyUSB1"}


def test_set_tracked_drops_state_for_untracked_profiles() -> None:
    tracker = UsbHotplugTracker()
    tracker.set_tracked({"profile-1": UsbIdentity(vid=0x0403, pid=0x6001)})
    tracker.poll([FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)])

    tracker.set_tracked({})
    connected, disconnected = tracker.poll(
        [FakePortInfo(device="/dev/ttyUSB0", vid=0x0403, pid=0x6001)]
    )

    assert connected == {}
    assert disconnected == []
