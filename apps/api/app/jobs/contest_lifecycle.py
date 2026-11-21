"""Contest lifecycle job (CS-027): approved -> live -> ended with the end snapshot.

Thin scheduler wrapper around ``services.contest_lifecycle.run_contest_lifecycle``,
which moves each due contest in its own locked transaction and re-checks the
status it overwrites, so a rerun or an overlap with an Admin approval is a
no-op. Logs start / success / failure / duration like every other job.
"""

from __future__ import annotations

import logging
import time

from app.services.contest_lifecycle import run_contest_lifecycle

logger = logging.getLogger("scheduler")


async def contest_lifecycle() -> None:
    started = time.monotonic()
    logger.info("job.contest_lifecycle.start")
    try:
        summary = await run_contest_lifecycle()
    except Exception:
        logger.exception("job.contest_lifecycle.failed")
        raise
    logger.info(
        "job.contest_lifecycle.success scanned=%d activated=%d ended=%d failed=%d duration_ms=%d",
        summary["scanned"],
        summary["activated"],
        summary["ended"],
        summary["failed"],
        (time.monotonic() - started) * 1000,
    )
