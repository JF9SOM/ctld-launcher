"""Placeholder rig/rotator model list, keyed by manufacturer.

TODO(step 5): replace with dynamic enumeration via Hamlib.rig_list_foreach()
/ Hamlib.rot_list_foreach() from the bundled Python bindings (see
.github/workflows/build-hamlib.yml), so the list always matches whichever
Hamlib version ships with the app instead of this hand-picked snapshot.
Only "Dummy" (model 1) has been verified directly against a real rigctld;
the rest are illustrative and may be off by a version or two.
"""

from __future__ import annotations

from ctld_launcher.core.profile import ProfileKind

# manufacturer -> [(hamlib model_id, model name), ...]
RIG_MODELS: dict[str, list[tuple[int, str]]] = {
    "Hamlib": [(1, "Dummy")],
    "Icom": [(3081, "IC-9700"), (3073, "IC-7300"), (3085, "IC-705")],
    "Yaesu": [(1035, "FT-991A"), (1042, "FTX-1")],
    "Kenwood": [(229, "TS-2000")],
}

ROTATOR_MODELS: dict[str, list[tuple[int, str]]] = {
    "Hamlib": [(1, "Dummy")],
    "SPID": [(401, "Rot2Prog")],
    "Yaesu": [(603, "GS-232A")],
}


def models_for(kind: ProfileKind) -> dict[str, list[tuple[int, str]]]:
    return RIG_MODELS if kind == ProfileKind.RIG else ROTATOR_MODELS
