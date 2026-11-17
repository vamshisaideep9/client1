"""Delete orphaned Agent cancelled-cheque objects (CS-022).

The presign endpoint hands out a signed URL before any row points at the
object, a replaced or removed cheque is deleted best-effort after commit, and
account erasure deletes the row before the object. This sweep removes every
staging or canonical cheque object no row references, once it is older than
the presign window. Mirrors jobs/purge_loan_document_orphans.py.
"""

from __future__ import annotations

import logging
import time

from app.services import agent_payout_cheque

logger = logging.getLogger("scheduler")


async def purge_agent_cheque_orphans() -> None:
    """Sweep unreferenced cheque uploads. Logs start/success/failure/duration."""
    started = time.monotonic()
    logger.info("job.purge_agent_cheque_orphans.start")
    try:
        summary = await agent_payout_cheque.purge_orphaned_uploads()
    except Exception:
        logger.exception("job.purge_agent_cheque_orphans.failed")
        raise
    else:
        logger.info(
            "job.purge_agent_cheque_orphans.success scanned=%d deleted=%d duration_ms=%d",
            summary.get("scanned", 0),
            summary.get("deleted", 0),
            (time.monotonic() - started) * 1000,
        )
