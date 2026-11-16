"""Local HTTP -> rigctld TCP relay for browser apps (e.g. DeepCW's CW macros).

Browsers cannot open raw TCP sockets, so they cannot talk to rigctld's text
protocol directly. This relay accepts ``POST /cmd`` with a single rigctld
command as the body, forwards it to the running rigctld over TCP and returns
rigctld's reply. It is started and stopped together with the rigctld process
of the profile that enables it.

Safety: it binds to loopback only, rejects browser requests whose ``Origin``
is not on the allow-list (a plain-text POST is a CORS "simple request", so the
check must happen before the command is executed, not just in the CORS
headers), and only forwards a small allow-list of keying commands.
"""

from __future__ import annotations

import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND_ADDRESS = "127.0.0.1"
MAX_BODY_BYTES = 1024

# Commands the browser may send: CW keying only. Anything else (frequency,
# mode, PTT, ...) is refused so a web page can never retune the rig.
_ALLOWED = re.compile(
    r"^(?:\\send_morse\s.+|\\stop_morse|L\s+KEYSPD\s+\d{1,3}|\\get_level\s+KEYSPD)$",
    re.IGNORECASE,
)
_RPRT = re.compile(r"RPRT\s+-?\d+\s*$")


def parse_origins(value: str) -> frozenset[str]:
    return frozenset(o.strip().rstrip("/") for o in value.split(",") if o.strip())


def is_command_allowed(command: str) -> bool:
    return bool(_ALLOWED.match(command))


def forward_to_rigctld(host: str, port: int, command: str, timeout: float = 3.0) -> str:
    """Send one command line to rigctld and return its reply text."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(command.encode("utf-8") + b"\n")
        chunks: list[bytes] = []
        sock.settimeout(timeout)
        while True:
            try:
                data = sock.recv(4096)
            except TimeoutError:
                break
            if not data:
                break
            chunks.append(data)
            if _RPRT.search(b"".join(chunks).decode("utf-8", errors="replace")):
                break
            sock.settimeout(0.3)  # value replies carry no RPRT; stop after a short idle
    return b"".join(chunks).decode("utf-8", errors="replace")


class WebBridge:
    """Owns one relay HTTP server thread. start() is idempotent (restarts)."""

    def __init__(self, rig_host: str, rig_port: int, port: int, origins: str) -> None:
        self._rig_host = rig_host
        self._rig_port = rig_port
        self._port = port
        self._origins = parse_origins(origins)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._port

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        self.stop()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

            def _reply(self, status: int, body: str = "", origin: str | None = None) -> None:
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                if origin is not None:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Vary", "Origin")
                self.end_headers()
                self.wfile.write(payload)

            def _origin(self) -> str | None:
                raw = self.headers.get("Origin")
                return raw.rstrip("/") if raw else None

            def do_OPTIONS(self) -> None:  # noqa: N802
                origin = self._origin()
                if origin is not None and origin not in bridge._origins:
                    self._reply(403, "origin not allowed")
                    return
                self._reply(204, origin=origin)

            def do_POST(self) -> None:  # noqa: N802
                origin = self._origin()
                if origin is not None and origin not in bridge._origins:
                    self._reply(403, "origin not allowed")
                    return
                if self.path != "/cmd":
                    self._reply(404, origin=origin)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    self._reply(413, origin=origin)
                    return
                command = " ".join(self.rfile.read(length).decode("utf-8", "replace").split())
                if not is_command_allowed(command):
                    self._reply(403, "command not allowed", origin)
                    return
                try:
                    reply = forward_to_rigctld(bridge._rig_host, bridge._rig_port, command)
                except OSError as exc:
                    self._reply(502, str(exc), origin)
                    return
                self._reply(200, reply, origin)

        self._server = ThreadingHTTPServer((BIND_ADDRESS, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
