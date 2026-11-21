"""Scheduler-owned attendance rollover."""

import logging
from time import monotonic

from app.services.attendance_rollover import run_attendance_rollover

logger = logging.getLogger("scheduler")


async def attendance_rollover() -> None:
    start = monotonic()
    logger.info("job.attendance_rollover.start")
    try:
        count = await run_attendance_rollover()
    except Exception:
        logger.exception("job.attendance_rollover.failed")
        raise
    logger.info(
        "job.attendance_rollover.success days=%d duration_ms=%d",
        count,
        (monotonic() - start) * 1000,
    )
