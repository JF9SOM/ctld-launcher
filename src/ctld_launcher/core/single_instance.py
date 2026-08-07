"""Detects whether another ctld-launcher instance is already running.

Uses a QLocalServer/QLocalSocket handshake (a Unix domain socket on Linux/
macOS, a named pipe on Windows) keyed by app name + user, rather than a PID
lockfile: a lockfile left behind by a killed/crashed process would otherwise
block every future launch until someone manually deletes it, whereas a
listen() on a stale socket path just succeeds after removeServer() clears it.
"""

from __future__ import annotations

import getpass

from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 500


def _server_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - exotic environments only
        user = "unknown"
    return f"ctld-launcher-single-instance-{user}"


class SingleInstanceGuard:
    """Call try_acquire() once at startup; keep the returned guard alive
    for the process lifetime so its QLocalServer keeps listening.
    """

    def __init__(self, key: str | None = None) -> None:
        self._key = key or _server_key()
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """Return True if this process is the sole instance, False if
        another instance already holds the lock.
        """
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        is_running = socket.waitForConnected(_CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        if is_running:
            return False

        # Clears a stale socket/pipe path left behind by a process that
        # never shut down cleanly (e.g. killed, crashed).
        QLocalServer.removeServer(self._key)

        server = QLocalServer()
        server.listen(self._key)
        self._server = server
        return True

    def close(self) -> None:
        """Stop listening, freeing the key for another process to acquire."""
        if self._server is not None:
            self._server.close()
            self._server = None
