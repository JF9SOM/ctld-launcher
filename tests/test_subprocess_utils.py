from __future__ import annotations

import sys

from ctld_launcher.core import subprocess_utils


def test_no_window_flags_is_zero_on_non_windows() -> None:
    if sys.platform != "win32":
        assert subprocess_utils.NO_WINDOW_FLAGS == 0
