#!/usr/bin/env python3
"""Fake rigctld/rotctld that exits immediately, for
test_main_window.py's crash-auto-restart test. Ignores all argv, like
_fake_ctld.py, but exits with a nonzero status right away instead of
idling -- standing in for a daemon that crashes on every launch.
"""

import sys


def main() -> None:
    print(f"fake ctld crashing args={sys.argv[1:]}", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
