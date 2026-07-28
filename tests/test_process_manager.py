from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from ctld_launcher.core.process_manager import CtldProcess, CtldProcessError, build_command
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
        "-m", "3081",
        "-r", "/dev/ttyUSB0",
        "-s", "19200",
        "-t", "4532",
        "-T", "127.0.0.1",
        "-vv",
        "-c", "0xa4",
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
        "-m", "1",
        "-t", "4532",
        "-T", "127.0.0.1",
    ]


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
