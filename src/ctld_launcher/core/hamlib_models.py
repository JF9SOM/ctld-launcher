"""Enumerates rig/rotator models supported by the bundled Hamlib build.

Runs `rigctld/rotctld --list` as a subprocess and parses its fixed-width
table, rather than calling into the Hamlib Python bindings directly.

This is deliberate, not just convenient: testing every RIG_MODEL_* constant
against a locally-built Python binding (same Hamlib 4.7.1 source as the CI
bundle) showed that constructing Hamlib.Rig(model_id) for some registered
model IDs (e.g. RIG_MODEL_ARMSTRONG, id 3) triggers a fatal, unrecoverable
"Hash collision!!! Fatal error!!" abort() inside libhamlib itself — not a
Python exception, so it cannot be caught and takes the whole process down
with it. `--list` uses Hamlib's internal rig_list_foreach()/
rot_list_foreach(), which only reads already-registered rig_caps/rot_caps
structs and does not hit that path. Subprocess isolation is the safety net
either way: even a future, still-undiscovered crash during listing only
kills that subprocess, never the GUI.
"""

from __future__ import annotations

import functools
import subprocess
from dataclasses import dataclass

from ctld_launcher.core.profile import ProfileKind
from ctld_launcher.core.subprocess_utils import NO_WINDOW_FLAGS


@dataclass(frozen=True)
class HamlibModel:
    model_id: int
    manufacturer: str
    name: str
    status: str


def parse_model_list(output: str) -> list[HamlibModel]:
    """Parse the fixed-width table printed by `rigctl(d)/rotctl(d) --list`.

    Column start offsets are read from the header line itself (rather than
    hardcoded) so this tolerates minor width changes across Hamlib versions.
    """
    lines = output.splitlines()
    if not lines:
        return []
    header = lines[0]
    try:
        mfg_start = header.index("Mfg")
        model_start = header.index("Model")
        version_start = header.index("Version")
        status_start = header.index("Status")
        macro_start = header.index("Macro")
    except ValueError:
        return []

    models = []
    for line in lines[1:]:
        rig_num_text = line[:mfg_start].strip()
        if not rig_num_text.isdigit():
            continue
        models.append(
            HamlibModel(
                model_id=int(rig_num_text),
                manufacturer=line[mfg_start:model_start].strip(),
                name=line[model_start:version_start].strip(),
                status=line[status_start:macro_start].strip(),
            )
        )
    return models


def list_models(executable: str) -> list[HamlibModel]:
    """Run `<executable> --list` and parse its output. Empty list on any failure."""
    try:
        result = subprocess.run(  # noqa: S603
            [executable, "--list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            creationflags=NO_WINDOW_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_model_list(result.stdout)


@functools.lru_cache(maxsize=8)
def _cached_list_models(executable: str) -> tuple[HamlibModel, ...]:
    return tuple(list_models(executable))


def models_by_manufacturer(executable: str) -> dict[str, list[tuple[int, str]]]:
    """Group `--list` output as {manufacturer: [(model_id, name), ...]}, cached
    per executable path for the lifetime of the process.

    Manufacturers are sorted alphabetically (case-insensitive) — `--list`
    itself prints them in Hamlib's internal backend-registration order,
    which is not alphabetical and made e.g. "Yaesu" hard to find in a long
    dropdown.
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for model in _cached_list_models(executable):
        grouped.setdefault(model.manufacturer, []).append((model.model_id, model.name))
    return dict(sorted(grouped.items(), key=lambda item: item[0].casefold()))


def default_model_id(kind: ProfileKind) -> int:
    """Hamlib model 1 is "Dummy" for both rigs and rotators — a safe default
    that needs no real hardware, verified against a real bundled rigctld.
    """
    del kind
    return 1
