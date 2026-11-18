from __future__ import annotations

import socket
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from ctld_launcher.core.profile import Profile, ProfileKind
from ctld_launcher.core.web_bridge import (
    WebBridge,
    is_command_allowed,
    normalize_command,
    parse_origins,
)


@pytest.fixture
def fake_rigctld() -> Iterator[tuple[int, list[str]]]:
    """A one-line-in, 'RPRT 0'-out stand-in for rigctld; records commands."""
    received: list[str] = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except (TimeoutError, OSError):
                continue
            with conn:
                received.append(conn.recv(1024).decode().rstrip("\r\n"))
                conn.sendall(b"RPRT 0\n")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield srv.getsockname()[1], received
    stop.set()
    thread.join(timeout=2)
    srv.close()


def _post(port: int, body: str, origin: str | None = None) -> tuple[int, str, dict[str, str]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/cmd", data=body.encode(), method="POST"
    )
    if origin:
        request.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def test_profile_roundtrip_and_old_profiles_default_off() -> None:
    profile = Profile(name="r", kind=ProfileKind.RIG, model_id=1, web_bridge_enabled=True)
    restored = Profile.from_dict(profile.to_dict())
    assert restored.web_bridge_enabled is True
    assert restored.web_bridge_port == 4540
    legacy = profile.to_dict()
    for key in ("web_bridge_enabled", "web_bridge_port", "web_bridge_origins"):
        legacy.pop(key)
    assert Profile.from_dict(legacy).web_bridge_enabled is False


def test_parse_origins_normalizes() -> None:
    assert parse_origins(" http://a.example/ , http://b.example ,") == frozenset(
        {"http://a.example", "http://b.example"}
    )


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("\\send_morse CQ DE JF9SOM", True),
        ("\\stop_morse", True),
        ("L KEYSPD 20", True),
        ("F 14074000", False),
        ("T 1", False),
        ("\\set_freq 7000000", False),
        ("L KEYSPD 20\nF 1", False),
    ],
)
def test_command_allow_list(command: str, allowed: bool) -> None:
    assert is_command_allowed(command) is allowed


def test_bridge_forwards_allowed_command(fake_rigctld: tuple[int, list[str]]) -> None:
    rig_port, received = fake_rigctld
    bridge = WebBridge("127.0.0.1", rig_port, 0, "http://localhost:5173")
    bridge.start()
    try:
        status, body, headers = _post(bridge.port, "\\send_morse CQ", "http://localhost:5173")
    finally:
        bridge.stop()
    assert status == 200
    assert "RPRT 0" in body
    assert received == ["\\send_morse CQ"]
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_bridge_rejects_foreign_origin_and_disallowed_command(
    fake_rigctld: tuple[int, list[str]],
) -> None:
    rig_port, received = fake_rigctld
    bridge = WebBridge("127.0.0.1", rig_port, 0, "http://localhost:5173")
    bridge.start()
    try:
        assert _post(bridge.port, "\\stop_morse", "https://evil.example")[0] == 403
        assert _post(bridge.port, "F 7000000", "http://localhost:5173")[0] == 403
    finally:
        bridge.stop()
    assert received == []


def test_bridge_reports_502_when_rigctld_down() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    bridge = WebBridge("127.0.0.1", dead_port, 0, "http://localhost:5173")
    bridge.start()
    try:
        assert _post(bridge.port, "\\stop_morse")[0] == 502
    finally:
        bridge.stop()


def test_start_is_idempotent_and_stop_releases() -> None:
    bridge = WebBridge("127.0.0.1", 1, 0, "")
    bridge.start()
    bridge.start()
    assert bridge.is_running
    bridge.stop()
    assert not bridge.is_running


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("\\send_morse CQ   DE\tJF9SOM\n", "\\send_morse CQ DE JF9SOM "),
        ("\\send_morse ? ", "\\send_morse ? "),
        ("\\send_morse ?", "\\send_morse ?"),
        ("L KEYSPD 20 ", "L KEYSPD 20"),
        ("\\stop_morse  ", "\\stop_morse"),
    ],
)
def test_normalize_command_keeps_send_morse_trailing_space(raw: str, expected: str) -> None:
    assert normalize_command(raw) == expected
    assert is_command_allowed(normalize_command(raw))


def test_bridge_keeps_padding_space_for_single_char_morse(
    fake_rigctld: tuple[int, list[str]],
) -> None:
    rig_port, received = fake_rigctld
    bridge = WebBridge("127.0.0.1", rig_port, 0, "http://localhost:5173")
    bridge.start()
    try:
        _post(bridge.port, "\\send_morse ? ", "http://localhost:5173")
    finally:
        bridge.stop()
    assert received == ["\\send_morse ? "]
