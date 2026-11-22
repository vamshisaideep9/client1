"""Private leave evidence. Detached upload reservations make cleanup retryable."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.cache.redis_keys import RedisCache
from app.core.deps import CurrentUser, is_platform_admin
from app.models.attendance import AttendanceCertificate, AttendanceRequest
from app.services import attendance as clock
from app.services import storage
from app.services.media_processing import (
    MediaProcessingError,
    ScannerUnavailable,
    sanitize_private_document,
)

MAX_BYTES = 5 * 1024 * 1024
_TYPES = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


class CertificateUnavailable(clock.AttendanceError):
    status = 503


class CertificateRateExceeded(clock.AttendanceError):
    status = 429


async def _uploadable(db: AsyncSession, actor: CurrentUser, request_id: UUID) -> AttendanceRequest:
    profile = await clock.lock_actor(db, actor)
    request = await db.get(AttendanceRequest, request_id, with_for_update=True)
    if (
        request is None
        or request.requester_id != actor.id
        or request.staff_profile_id != profile.id
    ):
        raise clock.AttendanceNotFound("Leave request not found.")
    if request.status != "pending" or not request.certificate_required:
        raise clock.AttendanceError("This request cannot accept a certificate.")
    return request


async def upload(
    actor: CurrentUser, request_id: UUID, upload_file: UploadFile, cache: RedisCache
) -> None:
    content_type = upload_file.content_type
    async with db_session.AsyncSessionLocal() as db:
        await _uploadable(db, actor, request_id)
        count = await cache.incr_with_expire(f"attendance:certificate:upload:{actor.id}", 3600)
        if count > 8:
            raise CertificateRateExceeded("Try uploading a certificate again later.")
        if content_type not in _TYPES:
            raise clock.AttendanceInvalid("Choose a PDF, JPEG, or PNG certificate.")
        content = await upload_file.read(MAX_BYTES + 1)
        try:
            canonical = await asyncio.to_thread(
                sanitize_private_document, content, content_type, max_bytes=MAX_BYTES
            )
        except ScannerUnavailable as exc:
            raise CertificateUnavailable(
                "The certificate scanner is temporarily unavailable."
            ) from exc
        except MediaProcessingError as exc:
            raise clock.AttendanceInvalid("Choose a valid PDF, JPEG, or PNG up to 5 MB.") from exc
        identifier = uuid4()
        candidate = AttendanceCertificate(
            id=identifier,
            object_key=f"attendance-certificates/{request_id}/{identifier}",
            content_type=content_type,
            expires_at=clock.utc_now() + timedelta(minutes=30),
        )
        db.add(candidate)
        await db.commit()

    async with db_session.AsyncSessionLocal() as db:
        request = await _uploadable(db, actor, request_id)
        certificate = await db.get(AttendanceCertificate, identifier, with_for_update=True)
        now = clock.utc_now()
        if certificate is None or certificate.expires_at <= now:
            raise CertificateUnavailable("The certificate upload expired. Please retry.")
        try:
            await asyncio.to_thread(
                storage.put_object_bytes, certificate.object_key, canonical, content_type
            )
            size = await asyncio.to_thread(storage.head_object, certificate.object_key)
            if size != len(canonical):
                raise CertificateUnavailable("Certificate storage is temporarily unavailable.")
        except Exception as exc:
            raise CertificateUnavailable("Certificate storage is temporarily unavailable.") from exc
        previous = await db.scalar(
            select(AttendanceCertificate)
            .where(AttendanceCertificate.request_id == request.id)
            .with_for_update()
        )
        if previous is not None:
            previous.request_id = None
            previous.expires_at = now
            await db.flush()
        certificate.request_id = request.id
        certificate.expires_at = now + timedelta(days=request.certificate_retention_days)
        await clock.audit(db, actor, "attach_certificate", entity_id=request.id)
        await db.commit()


async def has_certificate(db: AsyncSession, request_id: UUID, now: datetime) -> bool:
    return bool(
        await db.scalar(
            select(AttendanceCertificate.id).where(
                AttendanceCertificate.request_id == request_id,
                AttendanceCertificate.expires_at > now,
            )
        )
    )


async def download(
    db: AsyncSession, actor: CurrentUser, request_id: UUID
) -> tuple[bytes, str, str]:
    query = select(AttendanceCertificate).where(
        AttendanceCertificate.request_id == request_id,
        AttendanceCertificate.expires_at > clock.utc_now(),
    )
    if not is_platform_admin(actor):
        query = query.join(
            AttendanceRequest, AttendanceRequest.id == AttendanceCertificate.request_id
        ).where(
            AttendanceRequest.requester_id == actor.id,
            AttendanceRequest.staff_profile_id == actor.staff_profile_uuid,
        )
    certificate = await db.scalar(query)
    if certificate is None:
        raise clock.AttendanceNotFound("Certificate not found.")
    try:
        content = await asyncio.to_thread(
            storage.read_object_bytes, certificate.object_key, max_bytes=MAX_BYTES
        )
    except Exception as exc:
        raise CertificateUnavailable("Certificate storage is temporarily unavailable.") from exc
    if not content:
        raise CertificateUnavailable("Certificate storage is temporarily unavailable.")
    await clock.audit(db, actor, "read_certificate", entity_id=request_id)
    await db.commit()
    return content, certificate.content_type, _TYPES[certificate.content_type]


async def purge_expired() -> int:
    now = clock.utc_now()
    async with db_session.AsyncSessionLocal() as db:
        certificates = list(
            await db.scalars(
                select(AttendanceCertificate)
                .where(
                    AttendanceCertificate.expires_at <= now,
                )
                .order_by(AttendanceCertificate.expires_at, AttendanceCertificate.id)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        deleted = 0
        for certificate in certificates:
            try:
                await asyncio.to_thread(storage.delete_object, certificate.object_key)
                if await asyncio.to_thread(storage.head_object, certificate.object_key) is not None:
                    continue
            except Exception:
                continue
            await db.delete(certificate)
            deleted += 1
        await db.commit()
        return deleted
