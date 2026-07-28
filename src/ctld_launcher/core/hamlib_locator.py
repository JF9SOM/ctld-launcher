"""Locates the rigctld/rotctld executables to launch.

TODO: extend to auto-download/extract the hamlib-bundle release (see
.github/workflows/build-hamlib.yml) into the platformdirs user data dir,
the way FBSAT59's "Help > Hamlib Update" flow does, so users don't have to
have Hamlib installed system-wide. For now this only searches PATH.
"""

from __future__ import annotations

import shutil

from ctld_launcher.core.profile import ProfileKind

_EXECUTABLE_NAME = {
    ProfileKind.RIG: "rigctld",
    ProfileKind.ROTATOR: "rotctld",
}


class ExecutableNotFoundError(Exception):
    """Raised when rigctld/rotctld cannot be located."""


def find_executable(kind: ProfileKind) -> str:
    name = _EXECUTABLE_NAME[kind]
    path = shutil.which(name)
    if path is None:
        raise ExecutableNotFoundError(f"{name} not found on PATH")
    return path
