from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from ctld_launcher.core.process_manager import (
    CtldProcess,
    CtldProcessError,
    build_command,
    build_test_command,
    daemon_host_port,
    probe_daemon,
    serial_port_from_command,
)
from ctld_launcher.core.profile import Profile, ProfileKind

FAKE_CTLD = Path(__file__).parent / "_fake_ctld.py"


def test_build_command_rig() -> None:
    profile = Profile(
        name="IC-9700",
        kind=ProfileKind.RIG,
        model_id=3081,
        port="/dev/ttyUSB0",
        serial_speed=19200,
        listen_port=4532,
        debug_level=2,
        extra_args=["-c", "0xa4"],
    )
    assert build_command("rigctld", profile) == [
        "rigctld",
        "-m",
        "3081",
        "-r",
        "/dev/ttyUSB0",
        "-s",
        "19200",
        "-t",
        "4532",
        "-T",
        "127.0.0.1",
        "-vv",
        "-c",
        "0xa4",
    ]


def test_build_command_with_serial_conf() -> None:
    profile = Profile(
        name="IC-9700",
        kind=ProfileKind.RIG,
        model_id=3081,
        port="/dev/ttyUSB0",
        data_bits=8,
        stop_bits=1,
        serial_parity="None",
        serial_handshake="Hardware",
    )
    command = build_command("rigctld", profile)
    assert "-C" in command
    conf = command[command.index("-C") + 1]
    assert conf == "data_bits=8,stop_bits=1,serial_parity=None,serial_handshake=Hardware"


def test_build_command_minimal_rig() -> None:
    profile = Profile(name="Dummy", kind=ProfileKind.RIG, model_id=1)
    assert build_command("rigctld", profile) == [
        "rigctld",
        "-m",
        "1",
        "-t",
        "4532",
        "-T",
        "127.0.0.1",
    ]


def test_build_test_command_rig_queries_get_freq() -> None:
    profile = Profile(
        name="IC-9700",
        kind=ProfileKind.RIG,
        model_id=3081,
        port="/dev/ttyUSB0",
        serial_speed=19200,
    )
    assert build_test_command("rigctl", profile) == [
        "rigctl",
        "-m",
        "3081",
        "-r",
        "/dev/ttyUSB0",
        "-s",
        "19200",
        "f",
    ]


def test_build_command_includes_civ_address() -> None:
    profile = Profile(
        name="IC-9700",
        kind=ProfileKind.RIG,
        model_id=3081,
        port="/dev/ttyUSB0",
        civ_address="0x94",
    )
    command = build_command("rigctld", profile)
    assert "-c" in command
    assert command[command.index("-c") + 1] == "0x94"


def test_build_test_command_includes_civ_address() -> None:
    profile = Profile(
        name="IC-9700",
        kind=ProfileKind.RIG,
        model_id=3081,
        port="/dev/ttyUSB0",
        civ_address="0x94",
    )
    command = build_test_command("rigctl", profile)
    assert "-c" in command
    assert command[command.index("-c") + 1] == "0x94"


def test_build_command_omits_civ_flag_when_unset() -> None:
    profile = Profile(name="Dummy", kind=ProfileKind.RIG, model_id=1)
    assert "-c" not in build_command("rigctld", profile)


def test_build_command_civ_address_without_0x_prefix_is_normalized() -> None:
    profile = Profile(name="IC-9700", kind=ProfileKind.RIG, model_id=3081, civ_address="A2")
    command = build_command("rigctld", profile)
    assert command[command.index("-c") + 1] == "0xA2"


def test_build_test_command_civ_address_without_0x_prefix_is_normalized() -> None:
    profile = Profile(name="IC-9700", kind=ProfileKind.RIG, model_id=3081, civ_address="a2")
    command = build_test_command("rigctl", profile)
    assert command[command.index("-c") + 1] == "0xa2"


def test_build_test_command_rotator_queries_get_pos() -> None:
    profile = Profile(name="SPID", kind=ProfileKind.ROTATOR, model_id=401, port="/dev/ttyUSB1")
    assert build_test_command("rotctl", profile) == [
        "rotctl",
        "-m",
        "401",
        "-r",
        "/dev/ttyUSB1",
        "p",
    ]


def test_build_test_command_omits_network_flags() -> None:
    profile = Profile(name="Dummy", kind=ProfileKind.RIG, model_id=1, listen_port=4599)
    command = build_test_command("rigctl", profile)
    assert "-t" not in command
    assert "-T" not in command


def test_daemon_host_port_normalizes_all_interfaces_to_localhost() -> None:
    profile = Profile(
        name="Dummy",
        kind=ProfileKind.RIG,
        model_id=1,
        listen_address="0.0.0.0",
        listen_port=4532,
    )
    assert daemon_host_port(profile) == ("127.0.0.1", 4532)


def test_daemon_host_port_uses_configured_address() -> None:
    profile = Profile(
        name="Dummy",
        kind=ProfileKind.RIG,
        model_id=1,
        listen_address="192.168.1.5",
        listen_port=4532,
    )
    assert daemon_host_port(profile) == ("192.168.1.5", 4532)


def _serve_one_query(sock: socket.socket, expected: bytes, reply: bytes) -> None:
    conn, _addr = sock.accept()
    with conn:
        if conn.recv(64) == expected:
            conn.sendall(reply)


def test_probe_daemon_sends_bare_f_for_rig_and_returns_response() -> None:
    # Regression test: probe_daemon() must talk to the daemon over a plain
    # socket with a bare "f" (get_freq) -- not through Hamlib's own NET
    # rigctl client (rigctl -m 2), whose connection setup sends a "v"
    # (get_vfo) query as a side effect and, on rigctld's end, overwrites
    # the daemon's shared current_vfo with whatever the physical rig
    # reports as displayed -- silently corrupting every other connected
    # client's plain frequency writes for rigs like the FTX-1 that can
    # show Sub mid-session. See probe_daemon()'s docstring for the full
    # trace (found via a live FO-29/FTX-1 investigation with FBSAT59).
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    thread = threading.Thread(
        target=_serve_one_query, args=(server, b"f\n", b"145000000\n"), daemon=True
    )
    thread.start()
    try:
        profile = Profile(
            name="Dummy",
            kind=ProfileKind.RIG,
            model_id=1,
            listen_address="127.0.0.1",
            listen_port=port,
        )
        responded, output = probe_daemon(profile, timeout=2.0)
        assert responded is True
        assert output == "145000000"
    finally:
        thread.join(timeout=2.0)
        server.close()


def test_probe_daemon_sends_bare_p_for_rotator() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    thread = threading.Thread(
        target=_serve_one_query, args=(server, b"p\n", b"180.0 45.0\n"), daemon=True
    )
    thread.start()
    try:
        profile = Profile(
            name="Dummy",
            kind=ProfileKind.ROTATOR,
            model_id=401,
            listen_address="127.0.0.1",
            listen_port=port,
        )
        responded, output = probe_daemon(profile, timeout=2.0)
        assert responded is True
        assert output == "180.0 45.0"
    finally:
        thread.join(timeout=2.0)
        server.close()


def test_probe_daemon_returns_false_when_nothing_listening() -> None:
    # Grab an unused port and close it immediately -- nothing is listening
    # there, a fast and portable way to get a connection failure.
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind(("127.0.0.1", 0))
    port = reserved.getsockname()[1]
    reserved.close()

    profile = Profile(
        name="Dummy",
        kind=ProfileKind.RIG,
        model_id=1,
        listen_address="127.0.0.1",
        listen_port=port,
    )
    responded, output = probe_daemon(profile, timeout=1.0)
    assert responded is False
    assert output == ""


def test_serial_port_from_command_extracts_r_flag_value() -> None:
    profile = Profile(name="IC-9700", kind=ProfileKind.RIG, model_id=3081, port="COM4")
    command = build_command("rigctld", profile)
    assert serial_port_from_command(command) == "COM4"


def test_serial_port_from_command_none_when_no_port() -> None:
    profile = Profile(name="Dummy", kind=ProfileKind.RIG, model_id=1)
    command = build_command("rigctld", profile)
    assert serial_port_from_command(command) is None


def test_process_start_stop_captures_output() -> None:
    lines: list[str] = []
    process = CtldProcess(
        command=[sys.executable, str(FAKE_CTLD), "-m", "1"],
        on_output=lines.append,
    )
    process.start()
    assert process.is_running
    time.sleep(0.3)
    process.stop()
    assert not process.is_running
    assert any("fake ctld started" in line for line in lines)


def test_process_writes_log_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    log_file = tmp_path / "rig.log"
    process = CtldProcess(command=[sys.executable, str(FAKE_CTLD)], log_file=str(log_file))
    process.start()
    time.sleep(0.3)
    process.stop()
    assert log_file.exists()
    assert "fake ctld started" in log_file.read_text()


def test_start_twice_raises() -> None:
    process = CtldProcess(command=[sys.executable, str(FAKE_CTLD)])
    process.start()
    try:
        with pytest.raises(CtldProcessError):
            process.start()
    finally:
        process.stop()
