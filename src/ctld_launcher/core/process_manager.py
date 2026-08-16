from __future__ import annotations

import socket
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from ctld_launcher.core.profile import Profile, ProfileKind
from ctld_launcher.core.subprocess_utils import NO_WINDOW_FLAGS


class CtldProcessError(Exception):
    """Raised for invalid process lifecycle operations (e.g. starting twice)."""


@contextmanager
def _optional_log_file(path: str | None) -> Iterator[IO[str] | None]:
    if path is None:
        yield None
        return
    with open(path, "a", encoding="utf-8") as fh:
        yield fh


def _serial_conf_args(profile: Profile) -> list[str]:
    serial_conf = []
    if profile.data_bits:
        serial_conf.append(f"data_bits={profile.data_bits}")
    if profile.stop_bits:
        serial_conf.append(f"stop_bits={profile.stop_bits}")
    if profile.serial_parity:
        serial_conf.append(f"serial_parity={profile.serial_parity}")
    if profile.serial_handshake:
        serial_conf.append(f"serial_handshake={profile.serial_handshake}")
    return ["-C", ",".join(serial_conf)] if serial_conf else []


def _normalize_civ_address(value: str) -> str:
    """Accept the address as shown on the radio (e.g. "A2") as well as a
    "0x"-prefixed form; rigctld/rotctld's -c flag requires the 0x prefix to
    parse it as hexadecimal.
    """
    value = value.strip()
    return value if value.lower().startswith("0x") else f"0x{value}"


def build_command(executable: str, profile: Profile) -> list[str]:
    """Translate a Profile into rigctld/rotctld CLI arguments.

    Both daemons share the same -m/-r/-s/-c/-t/-T/-v flags; anything not
    covered goes through profile.extra_args verbatim.
    """
    command = [executable, "-m", str(profile.model_id)]
    if profile.port:
        command += ["-r", profile.port]
    if profile.serial_speed:
        command += ["-s", str(profile.serial_speed)]
    if profile.civ_address:
        command += ["-c", _normalize_civ_address(profile.civ_address)]
    command += _serial_conf_args(profile)
    command += ["-t", str(profile.listen_port)]
    if profile.listen_address:
        command += ["-T", profile.listen_address]
    if profile.debug_level > 0:
        command.append("-" + "v" * min(profile.debug_level, 5))
    command += list(profile.extra_args)
    return command


def build_test_command(executable: str, profile: Profile) -> list[str]:
    """Translate a Profile into a one-shot rigctl/rotctl connectivity check.

    Unlike build_command() (for rigctld/rotctld, which stay running as a TCP
    daemon), this runs a single read-only query directly against the serial
    port and exits — no network listener, no -t/-T. Uses "f" (get_freq) for
    rigs and "p" (get_pos) for rotators.
    """
    command = [executable, "-m", str(profile.model_id)]
    if profile.port:
        command += ["-r", profile.port]
    if profile.serial_speed:
        command += ["-s", str(profile.serial_speed)]
    if profile.civ_address:
        command += ["-c", _normalize_civ_address(profile.civ_address)]
    command += _serial_conf_args(profile)
    command.append("f" if profile.kind == ProfileKind.RIG else "p")
    return command


def serial_port_from_command(command: list[str]) -> str | None:
    """Extract the -r (serial port) argument from a build_command()-built
    command list -- the port a running rigctld/rotctld was actually launched
    with, which can differ from a profile's current `port` field if it was
    edited after the daemon started without a restart.
    """
    try:
        return command[command.index("-r") + 1]
    except ValueError:
        return None


def daemon_host_port(profile: Profile) -> tuple[str, int]:
    """Resolve the (host, port) an already-running rigctld/rotctld for this
    profile is reachable on, normalizing an all-interfaces bind address
    (0.0.0.0) to loopback for client use.
    """
    host = profile.listen_address
    if not host or host == "0.0.0.0":  # noqa: S104 (comparison, not a bind)
        host = "127.0.0.1"
    return host, profile.listen_port


def probe_daemon(profile: Profile, timeout: float = 5.0) -> tuple[bool, str]:
    """Read-only liveness probe for an already-running rigctld/rotctld.

    Talks to the daemon directly over its raw TCP text protocol -- sending
    a bare "f\\n" (get_freq) for rig profiles or "p\\n" (get_pos) for rotator
    profiles, exactly what FBSAT59 itself already sends routinely as a
    read -- instead of shelling out to Hamlib's own NET rigctl/rotctl client
    (rigctl/rotctl -m 2), which this function replaces.

    That client matters here because it's not just a thinner way to reach
    the same daemon: opening it (Hamlib's generic rig_open()) issues a "v"
    (get_vfo) query as an unavoidable side effect, and rigctld's server-side
    rig_get_vfo() handler doesn't just answer it -- it also overwrites the
    daemon's single, connection-shared current_vfo with whatever VFO the
    physical rig currently reports as displayed/active (Hamlib's rig.c
    vfo-cache logic; rig_get_freq(), used here instead, only ever *reads*
    current_vfo, confirmed from Hamlib 4.7.1/4.7.2 source -- so this
    couldn't happen for rigs that never reply to plain reads with a VFO
    switch either). For rigs like the FTX-1 that can end up displaying Sub
    mid-session during continuous split/cross-band Doppler tracking, a
    health-check poll landing at the wrong moment used to silently redirect
    every subsequent VFO-less "F" frequency write from every OTHER
    connected client (FBSAT59, GPredict, WSJT-X, ...) to Sub instead of
    Main -- found via a live FO-29/FTX-1 investigation with FBSAT59 (see
    its CLAUDE.md changelog for the full trace). Rotators have no VFO
    concept at all, so they were never at risk, but they get the same
    lighter-weight probe for consistency.

    Bypassing rigctl/rotctl entirely also means this no longer depends on
    locating that executable, and needs no subprocess at all.

    Returns (responded, output): output is the daemon's raw first-line
    reply (a frequency in Hz for rigs, azimuth/elevation for rotators),
    or "" if nothing came back before the timeout.
    """
    host, port = daemon_host_port(profile)
    command = b"f\n" if profile.kind == ProfileKind.RIG else b"p\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(command)
            sock.settimeout(timeout)
            data = sock.recv(256)
    except OSError:
        return False, ""
    text = data.decode("utf-8", errors="replace").strip()
    return bool(text), text


class CtldProcess:
    """Owns the lifecycle of a single rigctld/rotctld subprocess."""

    def __init__(
        self,
        command: list[str],
        log_file: str | None = None,
        on_output: Callable[[str], None] | None = None,
        on_exit: Callable[[int], None] | None = None,
    ) -> None:
        self._command = command
        self._log_file = log_file
        self._on_output = on_output
        self._on_exit = on_exit
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def command(self) -> list[str]:
        return list(self._command)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> None:
        if self.is_running:
            raise CtldProcessError(f"process already running (pid={self.pid})")
        if self._log_file:
            Path(self._log_file).parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(
            self._command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=NO_WINDOW_FLAGS,
        )
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

    def _read_output(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        with _optional_log_file(self._log_file) as log_fh:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\n")
                if log_fh:
                    log_fh.write(line + "\n")
                    log_fh.flush()
                if self._on_output:
                    self._on_output(line)
        exit_code = process.wait()
        if self._on_exit:
            self._on_exit(exit_code)

    def stop(self, timeout: float = 5.0) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Stuck in an uninterruptible kernel wait (e.g. a wedged
                # USB-serial driver) -- even SIGKILL can't reap it yet. Give
                # up rather than blocking the caller (often the GUI thread)
                # forever; is_running keeps reporting True until the OS
                # finishes reaping it, which is still correct.
                return
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=timeout)

    def restart(self) -> None:
        self.stop()
        self.start()
