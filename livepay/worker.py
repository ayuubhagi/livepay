"""Standalone worker: consume punches from the Redis Stream and process them.

Run with:  uv run python -m livepay.worker
"""

from __future__ import annotations

from livepay.db import SessionLocal
from livepay.pipeline import consume_once, ensure_group, get_redis


def main() -> None:
    r = get_redis()
    ensure_group(r)
    print("livepay worker: consuming punches (Ctrl-C to stop)")
    while True:
        # block=5000ms: wait up to 5s for new messages, then loop.
        consume_once(r, SessionLocal, block=5000)


if __name__ == "__main__":
    main()
