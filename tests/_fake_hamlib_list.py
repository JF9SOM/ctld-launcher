#!/usr/bin/env python3
"""Standalone helper for hamlib_models tests: emits a `--list`-style fixed
width table without needing a real Hamlib build. list_models() runs this
path directly (no interpreter prefix), so it needs the shebang above and
the executable bit set at test time (see test_hamlib_models.py).
"""

import sys


def _row(num: str, mfg: str, model: str, version: str, status: str, macro: str) -> str:
    return f"{num:>6}  {mfg:<23}{model:<24}{version:<16}{status:<12}{macro}"


ROWS = [
    _row("Rig #", "Mfg", "Model", "Version", "Status", "Macro"),
    _row("1", "Hamlib", "Dummy", "20240709.0", "Stable", "RIG_MODEL_DUMMY"),
    _row("2", "Hamlib", "NET rigctl", "20250211.0", "Stable", "RIG_MODEL_NETRIGCTL"),
    _row("1001", "Yaesu", "FT-847", "20230512.0", "Stable", "RIG_MODEL_FT847"),
    _row("1035", "Yaesu", "FT-991", "20240101.0", "Stable", "RIG_MODEL_FT991"),
]


def main() -> None:
    if "--list" in sys.argv:
        print("\n".join(ROWS))


if __name__ == "__main__":
    main()
