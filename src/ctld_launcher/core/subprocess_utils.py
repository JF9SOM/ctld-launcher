"""Shared subprocess helpers."""

from __future__ import annotations

import subprocess
import sys

if sys.platform == "win32":
    # rigctld/rotctld/rigctl/rotctl are console-subsystem executables, so
    # plain subprocess.Popen()/run() pops up a visible console window on
    # Windows for each one — no such concept on Linux/macOS, which is why
    # this went unnoticed there. Pass this via creationflags to suppress it;
    # stdout/stderr piping is unaffected.
    NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW
else:
    NO_WINDOW_FLAGS = 0
