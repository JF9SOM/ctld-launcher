"""Standalone helper process for process_manager tests: stands in for
rigctld/rotctld without needing a real Hamlib build. Prints one line then
idles until killed.
"""

import sys
import time


def main() -> None:
    print(f"fake ctld started args={sys.argv[1:]}", flush=True)
    while True:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
