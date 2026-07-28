from __future__ import annotations

import stat
from pathlib import Path

from ctld_launcher.core.hamlib_models import list_models, models_by_manufacturer, parse_model_list

FAKE_LIST = Path(__file__).parent / "_fake_hamlib_list.py"

# Captured verbatim from a real `rigctl --list` run against the Linux
# hamlib-bundle build (Hamlib 4.7.1) — including a multi-word manufacturer
# ("N2ADR James Ahlstrom") and a multi-word model name ("FT-1000MP MARK-V")
# to exercise the fixed-width slicing, not just simple whitespace-split cases.
REAL_SAMPLE = """\
 Rig #  Mfg                    Model                   Version         Status      Macro
     1  Hamlib                 Dummy                   20240709.0      Stable      DUMMY
     2  Hamlib                 NET rigctl              20250211.0      Stable      NETRIGCTL
    10  N2ADR James Ahlstrom   Quisk                   20230709.0      Stable      QUISK
  1004  Yaesu                  FT-1000MP MARK-V        20241105.1      Stable      FT1000MPMKV
"""


def test_parse_model_list_real_sample() -> None:
    models = parse_model_list(REAL_SAMPLE)
    assert len(models) == 4
    assert models[0].model_id == 1
    assert models[0].manufacturer == "Hamlib"
    assert models[0].name == "Dummy"
    assert models[0].status == "Stable"

    multi_word = next(m for m in models if m.model_id == 10)
    assert multi_word.manufacturer == "N2ADR James Ahlstrom"
    assert multi_word.name == "Quisk"

    multi_word_model = next(m for m in models if m.model_id == 1004)
    assert multi_word_model.manufacturer == "Yaesu"
    assert multi_word_model.name == "FT-1000MP MARK-V"


def test_parse_model_list_empty_output() -> None:
    assert parse_model_list("") == []


def test_parse_model_list_ignores_malformed_header() -> None:
    assert parse_model_list("not a table\nrandom text\n") == []


def test_list_models_via_fake_executable() -> None:
    FAKE_LIST.chmod(FAKE_LIST.stat().st_mode | stat.S_IXUSR)
    models = list_models(str(FAKE_LIST))
    assert {m.model_id for m in models} == {1, 2, 1001, 1035}
    dummy = next(m for m in models if m.model_id == 1)
    assert dummy.manufacturer == "Hamlib"
    assert dummy.name == "Dummy"


def test_list_models_missing_executable_returns_empty() -> None:
    assert list_models("/no/such/rigctld") == []


def test_models_by_manufacturer_groups_correctly() -> None:
    FAKE_LIST.chmod(FAKE_LIST.stat().st_mode | stat.S_IXUSR)
    grouped = models_by_manufacturer(str(FAKE_LIST))
    assert set(grouped["Yaesu"]) == {(1001, "FT-847"), (1035, "FT-991")}
    assert (1, "Dummy") in grouped["Hamlib"]
