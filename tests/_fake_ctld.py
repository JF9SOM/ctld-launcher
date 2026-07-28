#!/usr/bin/env python3
"""Standalone helper process for process_manager tests: stands in for
rigctld/rotctld without needing a real Hamlib build. Prints one line then
idles until killed. Ignores all argv, so it can also stand in as the
"executable" build_command() invokes (see test_main_window.py's
test_start_autostart_profiles_starts_only_flagged_ones) — set the
executable bit at test time, same as tests/_fake_hamlib_list.py.
"""

import sys
import time


def main() -> None:
    print(f"fake ctld started args={sys.argv[1:]}", flush=True)
    while True:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
