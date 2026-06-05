from __future__ import annotations

import os
import time


def main() -> None:
    """Worker entrypoint placeholder.

    The production worker must claim jobs with FOR UPDATE SKIP LOCKED, validate
    URLs, run douyin_chong with fixed arguments, write schema-valid results and
    clean temporary files. It is intentionally not wired to production state
    until the actual video tool is supplied.
    """

    interval = int(os.environ.get("WORKER_IDLE_SECONDS", "5"))
    while True:
        time.sleep(interval)


if __name__ == "__main__":
    main()

