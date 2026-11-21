"""Optional cancelled cheque on an Agent's saved payout details (CS-022).

Same upload discipline as client loan documents (services/loan_documents.py):

- presign hands out a signed multipart POST with a storage-enforced size cap
  for one private staging key bound to the Agent profile;
- confirmation re-checks the claimed key, the size and the leading bytes
  (JPEG, PNG or PDF only), then scans/sanitizes it into an immutable canonical
  object before the row points at it; every rejected or replaced object is
  removed best-effort and the scheduled orphan sweep removes anything left;
- the Agent's own writes run on the request session (owner-only RLS);
- a payout maker opens the cheque only through ``view_for_payout`` on the
  bypass session, after the router has proven payout-request access, and every
  successful view is audited (``agent_payout_details_viewed``, purpose
  ``cheque_view``).

The cheque proves one bank account, so replacing or removing the saved bank
account clears it (services/agent_payout_details.py). Object keys never enter
logs, audit details, error text or Agent-facing responses.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.cache.redis_keys import (
    TTL_AGENT_CHEQUE_PRESIGN,
    RedisCache,
    agent_cheque_presign_key,
)
from app.core.config import settings
from app.models.agent_payout_details import AgentPayoutDetails
from app.models.audit_log import AuditAction
from app.services import storage
from app.services.audit_log import record as record_audit
from app.services.media_processing import (
    MalwareDetected,
    MediaProcessingError,
    ScannerUnavailable,
    canonicalize_object,
)

logger = logging.getLogger(__name__)

PRESIGN_LIMIT_PER_HOUR = 10
CHEQUE_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
_PREFIX = "private/agent-payout-cheques/"
_STAGING_PREFIX = f"{_PREFIX}staging/"
_CANONICAL_PREFIX = f"{_PREFIX}canonical/"
_STAGING_KEY_RE = re.compile(
    r"^private/agent-payout-cheques/staging/"
    r"(?P<owner>[0-9a-f-]{36})/(?P<media>[0-9a-f-]{36})/cheque(?P<extension>\.jpg|\.png|\.pdf)$"
)
# Well clear of the 300 s presign TTL, same margin as the loan-media sweep.
_ORPHAN_MIN_AGE = timedelta(hours=1)


class ChequeError(Exception):
    """Base for cancelled-cheque errors; the router maps subclasses to HTTP."""


class PayoutDetailsMissing(ChequeError):
    """No saved bank account or UPI ID to attach a cheque to."""


class UploadRateExceeded(ChequeError):
    pass


class ObjectKeyMismatch(ChequeError):
    """The claimed key was not issued to this Agent or does not match the type."""


class UploadMissing(ChequeError):
    """No object (or an empty/oversize one) behind the claimed key."""


class ContentTypeMismatch(ChequeError):
    """The bytes are not the declared JPEG/PNG/PDF, or failed sanitizing/scanning."""


class StorageUnavailable(ChequeError):
    """Storage or the scanner was unreachable. Fail closed."""


class ChequeNotFound(ChequeError):
    pass


class SelfChequeViewForbidden(ChequeError):
    """A payout maker asked for their own cheque."""


@dataclass(frozen=True)
class ChequeView:
    object_key: str
    content_type: str
    uploaded_at: datetime


def _staging_key(agent_profile_uuid: uuid.UUID, media_id: uuid.UUID, content_type: str) -> str:
    return (
        f"{_STAGING_PREFIX}{agent_profile_uuid}/{media_id}/cheque{CHEQUE_EXTENSION[content_type]}"
    )


def _canonical_key(agent_profile_uuid: uuid.UUID, media_id: uuid.UUID, content_type: str) -> str:
    return (
        f"{_CANONICAL_PREFIX}{agent_profile_uuid}/{media_id}/cheque{CHEQUE_EXTENSION[content_type]}"
    )


async def _own_row(
    db: AsyncSession, agent_profile_uuid: uuid.UUID, *, for_update: bool = False
) -> AgentPayoutDetails | None:
    stmt = select(AgentPayoutDetails).where(
        AgentPayoutDetails.agent_profile_uuid == agent_profile_uuid
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def best_effort_delete(object_key: str | None) -> None:
    if not object_key:
        return
    try:
        await asyncio.to_thread(storage.delete_object, object_key)
    except Exception:
        # Never log a private key; the orphan sweep retries cleanup.
        logger.warning("agent_cheque.object_cleanup_failed", exc_info=True)


async def presign_upload(
    db: AsyncSession,
    cache: RedisCache,
    *,
    agent_profile_uuid: uuid.UUID,
    auth_user_uuid: uuid.UUID,
    content_type: str,
) -> tuple[str, str, dict[str, str], int]:
    """Returns (object_key, upload_url, fields, max_bytes). No DB write."""
    if content_type not in CHEQUE_EXTENSION:
        raise ContentTypeMismatch("Upload a JPEG, PNG or PDF.")
    if await _own_row(db, agent_profile_uuid) is None:
        raise PayoutDetailsMissing("Save a bank account or UPI ID first.")
    count = await cache.incr_with_expire(
        agent_cheque_presign_key(str(auth_user_uuid)), TTL_AGENT_CHEQUE_PRESIGN
    )
    if count > PRESIGN_LIMIT_PER_HOUR:
        raise UploadRateExceeded("Too many upload attempts. Try again later.")
    object_key = _staging_key(agent_profile_uuid, uuid.uuid4(), content_type)
    max_bytes = settings.AGENT_PAYOUT_CHEQUE_MAX_UPLOAD_BYTES
    url, fields = storage.presign_upload_post(object_key, content_type, max_bytes=max_bytes)
    return object_key, url, fields, max_bytes


def _check_claimed_key(
    object_key: str, agent_profile_uuid: uuid.UUID, content_type: str
) -> uuid.UUID:
    match = _STAGING_KEY_RE.fullmatch(object_key)
    if match is None:
        raise ObjectKeyMismatch("This upload was not issued to you.")
    try:
        owner = uuid.UUID(match.group("owner"))
        media_id = uuid.UUID(match.group("media"))
    except ValueError as exc:
        raise ObjectKeyMismatch("This upload was not issued to you.") from exc
    if owner != agent_profile_uuid or match.group("extension") != CHEQUE_EXTENSION.get(
        content_type
    ):
        raise ObjectKeyMismatch("This upload was not issued to you.")
    return media_id


async def _verify_object(object_key: str, content_type: str) -> int:
    try:
        size = await asyncio.to_thread(storage.head_object, object_key)
    except Exception as exc:  # transport failure: fail closed
        raise StorageUnavailable("Storage is unavailable. Try again.") from exc
    if size is None or size <= 0 or size > settings.AGENT_PAYOUT_CHEQUE_MAX_UPLOAD_BYTES:
        raise UploadMissing("The upload is missing or larger than 5 MB.")
    try:
        matches = await asyncio.to_thread(
            storage.content_matches_declared_type, object_key, content_type
        )
    except Exception as exc:
        raise StorageUnavailable("Storage is unavailable. Try again.") from exc
    if not matches:
        raise ContentTypeMismatch("The file is not a valid JPEG, PNG or PDF.")
    return size


async def confirm_upload(
    db: AsyncSession,
    *,
    agent_profile_uuid: uuid.UUID,
    auth_user_uuid: uuid.UUID,
    object_key: str,
    content_type: str,
) -> AgentPayoutDetails:
    """Attach (or replace) the cancelled cheque after verifying the upload."""
    if content_type not in CHEQUE_EXTENSION:
        raise ContentTypeMismatch("Upload a JPEG, PNG or PDF.")
    media_id = _check_claimed_key(object_key, agent_profile_uuid, content_type)

    row = await _own_row(db, agent_profile_uuid, for_update=True)
    if row is None:
        await db.rollback()
        raise PayoutDetailsMissing("Save a bank account or UPI ID first.")
    canonical_key = _canonical_key(agent_profile_uuid, media_id, content_type)
    if row.cheque_object_key == canonical_key:
        await db.rollback()
        raise ObjectKeyMismatch("This upload has already been confirmed.")

    try:
        await _verify_object(object_key, content_type)
    except ContentTypeMismatch:
        await db.rollback()
        await best_effort_delete(object_key)
        raise
    except ChequeError:
        await db.rollback()
        raise

    try:
        written = await asyncio.to_thread(
            canonicalize_object,
            object_key,
            canonical_key,
            content_type,
            max_bytes=settings.AGENT_PAYOUT_CHEQUE_MAX_UPLOAD_BYTES,
        )
        if written <= 0:
            raise StorageUnavailable("Storage is unavailable. Try again.")
        await _verify_object(canonical_key, content_type)
    except (MalwareDetected, MediaProcessingError) as exc:
        await db.rollback()
        await best_effort_delete(canonical_key)
        await best_effort_delete(object_key)
        if isinstance(exc, ScannerUnavailable):
            raise StorageUnavailable("The file could not be checked. Try again.") from exc
        raise ContentTypeMismatch("The file is not a valid JPEG, PNG or PDF.") from exc
    except ChequeError:
        await db.rollback()
        await best_effort_delete(canonical_key)
        raise
    except Exception as exc:
        await db.rollback()
        await best_effort_delete(canonical_key)
        raise StorageUnavailable("Storage is unavailable. Try again.") from exc
    previous_key = row.cheque_object_key
    row.cheque_object_key = canonical_key
    row.cheque_content_type = content_type
    row.cheque_uploaded_at = datetime.now(UTC)
    try:
        await db.flush()
        await record_audit(
            db,
            action=AuditAction.AGENT_PAYOUT_DETAILS_UPDATED,
            entity_type="agent_payout_details",
            entity_uuid=agent_profile_uuid,
            actor_uuid=auth_user_uuid,
            actor_role="agent",
            detail={"cheque": "replaced" if previous_key else "set", "content_type": content_type},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        await best_effort_delete(canonical_key)
        raise ObjectKeyMismatch("This upload has already been confirmed.") from exc
    except Exception:
        await db.rollback()
        await best_effort_delete(canonical_key)
        raise
    await best_effort_delete(object_key)
    if previous_key and previous_key != canonical_key:
        await best_effort_delete(previous_key)
    return row


async def delete_own(
    db: AsyncSession, *, agent_profile_uuid: uuid.UUID, auth_user_uuid: uuid.UUID
) -> None:
    row = await _own_row(db, agent_profile_uuid, for_update=True)
    if row is None or row.cheque_object_key is None:
        await db.rollback()
        raise ChequeNotFound("No cancelled cheque is saved.")
    object_key = clear_columns(row)
    await db.flush()
    await record_audit(
        db,
        action=AuditAction.AGENT_PAYOUT_DETAILS_UPDATED,
        entity_type="agent_payout_details",
        entity_uuid=agent_profile_uuid,
        actor_uuid=auth_user_uuid,
        actor_role="agent",
        detail={"cheque": "removed"},
    )
    await db.commit()
    await best_effort_delete(object_key)


def clear_columns(row: AgentPayoutDetails) -> str | None:
    """Detach the cheque from a row; returns the object key to delete after commit."""
    object_key = row.cheque_object_key
    row.cheque_object_key = None
    row.cheque_content_type = None
    row.cheque_uploaded_at = None
    return object_key


async def view_for_payout(
    *,
    actor_auth_user_uuid: uuid.UUID,
    actor_role: str,
    recipient_auth_user_uuid: uuid.UUID | None = None,
    agent_profile_uuid: uuid.UUID | None = None,
) -> ChequeView | None:
    """Return the cheque object for one payout maker, with audit.

    The router must already have proven payout-request access. A maker's own
    cheque is refused before anything is audited. Returns None when no cheque
    is saved.
    """
    if (recipient_auth_user_uuid is None) == (agent_profile_uuid is None):
        raise ValueError("Pass exactly one of recipient_auth_user_uuid or agent_profile_uuid.")
    stmt = select(AgentPayoutDetails).where(AgentPayoutDetails.cheque_object_key.is_not(None))
    if agent_profile_uuid is not None:
        stmt = stmt.where(AgentPayoutDetails.agent_profile_uuid == agent_profile_uuid)
    else:
        stmt = stmt.where(AgentPayoutDetails.auth_user_uuid == recipient_auth_user_uuid)
    async with db_session.AsyncSessionLocal() as session:
        row = await session.scalar(stmt.order_by(AgentPayoutDetails.updated_at.desc()).limit(1))
        if row is None or row.cheque_object_key is None or row.cheque_uploaded_at is None:
            return None
        if row.auth_user_uuid == actor_auth_user_uuid:
            raise SelfChequeViewForbidden
        view = ChequeView(
            object_key=row.cheque_object_key,
            content_type=row.cheque_content_type or "application/pdf",
            uploaded_at=row.cheque_uploaded_at,
        )
        await record_audit(
            session,
            action=AuditAction.AGENT_PAYOUT_DETAILS_VIEWED,
            entity_type="agent_payout_details",
            entity_uuid=row.agent_profile_uuid,
            actor_uuid=actor_auth_user_uuid,
            actor_role=actor_role,
            detail={
                "recipient_auth_user_uuid": str(row.auth_user_uuid),
                "fields": ["cheque"],
                "purpose": "cheque_view",
            },
        )
        await session.commit()
    return view


async def object_keys_for_account(auth_user_uuid: uuid.UUID) -> list[str]:
    """Cheque objects of one account, read before account erasure deletes the row.

    Bypass session: an Admin removing an Agent cannot SELECT the row under RLS.
    The caller (services/account_deletion.py) has already authorized the erasure.
    """
    async with db_session.AsyncSessionLocal() as session:
        keys = await session.scalars(
            select(AgentPayoutDetails.cheque_object_key).where(
                AgentPayoutDetails.auth_user_uuid == auth_user_uuid,
                AgentPayoutDetails.cheque_object_key.is_not(None),
            )
        )
        return [key for key in keys.all() if key]


async def purge_orphaned_uploads(*, min_age: timedelta = _ORPHAN_MIN_AGE) -> dict[str, int]:
    """Delete staging and canonical cheque objects no row references."""
    cutoff = datetime.now(UTC) - min_age
    objects = await asyncio.to_thread(storage.list_objects, _PREFIX)
    candidates = [o for o in objects if o["last_modified"] < cutoff]
    if not candidates:
        return {"scanned": len(objects), "deleted": 0}
    async with db_session.AsyncSessionLocal() as session:
        referenced = set(
            (
                await session.scalars(
                    select(AgentPayoutDetails.cheque_object_key).where(
                        AgentPayoutDetails.cheque_object_key.is_not(None)
                    )
                )
            ).all()
        )
    deleted = 0
    for obj in candidates:
        if obj["key"] not in referenced:
            await asyncio.to_thread(storage.delete_object, obj["key"])
            deleted += 1
    return {"scanned": len(objects), "deleted": deleted}
