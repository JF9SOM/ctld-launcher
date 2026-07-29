from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from ctld_launcher.core.process_manager import (
    CtldProcess,
    CtldProcessError,
    build_command,
    build_test_command,
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
