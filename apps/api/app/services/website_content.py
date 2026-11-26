import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, is_platform_admin
from app.models.audit_log import AuditAction
from app.models.profile import ProfileStatus, StaffProfile, StaffRole
from app.models.user import User, UserStatus
from app.models.website_content import WebsiteDocument, WebsiteEditorGrant, WebsiteRevision
from app.schemas.website_content import WebsiteAccess, WebsiteDraftWrite, WebsitePublishWrite
from app.services.admin import is_primary_admin
from app.services.audit_log import record

_ELIGIBLE_ROLES = (StaffRole.ADMIN, StaffRole.SUB_ADMIN)
_KEY_PATTERN = re.compile(
    r"(?:page/[a-z0-9-]+(?:/[a-z0-9-]+)*|article/[a-z0-9][a-z0-9-]*|"
    r"property/[0-9a-f-]{36}|property-type/[a-z0-9][a-z0-9-]*)"
)


async def website_access(
    db: AsyncSession, user: CurrentUser, *, lock: bool = False
) -> WebsiteAccess:
    profile_id = user.staff_profile_uuid
    if user.role not in _ELIGIBLE_ROLES or profile_id is None:
        return WebsiteAccess(can_edit=False, can_publish=False)
    if lock:
        await lock_profile(db, profile_id)
    valid_profile = await db.scalar(
        select(StaffProfile.id).where(
            StaffProfile.id == profile_id,
            StaffProfile.auth_user_uuid == user.id,
            StaffProfile.role == user.role,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if valid_profile is None:
        return WebsiteAccess(can_edit=False, can_publish=False)
    can_publish = is_platform_admin(user) and await is_primary_admin(
        db, auth_user_uuid=user.id, staff_profile_uuid=profile_id
    )
    if can_publish:
        await db.execute(select(func.set_config("app.website_main_admin", "true", True)))
    can_edit = can_publish or await db.get(WebsiteEditorGrant, profile_id) is not None
    return WebsiteAccess(can_edit=can_edit, can_publish=can_publish)


async def lock_profile(db: AsyncSession, profile_id: UUID) -> None:
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(profile_id), 813)))
    )


def validate_key(key: str) -> None:
    if (
        len(key) > 160
        or not _KEY_PATTERN.fullmatch(key)
        or not re.fullmatch(r"[a-z0-9]+(?:[-/][a-z0-9]+)*", key)
    ):
        raise HTTPException(422, "Choose a valid content key.")


async def eligible_editors(db: AsyncSession):
    stmt = (
        select(StaffProfile, WebsiteEditorGrant.profile_id)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .outerjoin(WebsiteEditorGrant, WebsiteEditorGrant.profile_id == StaffProfile.id)
        .where(
            StaffProfile.role.in_(_ELIGIBLE_ROLES),
            StaffProfile.is_primary_admin.is_(False),
            StaffProfile.status == ProfileStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
        )
        .order_by(StaffProfile.staff_code)
    )
    return (await db.execute(stmt)).all()


async def set_grant(
    db: AsyncSession, user: CurrentUser, profile_id: UUID, *, enabled: bool
) -> None:
    await lock_profile(db, profile_id)
    grant = await db.get(WebsiteEditorGrant, profile_id)
    if enabled:
        if not any(profile.id == profile_id for profile, _ in await eligible_editors(db)):
            raise HTTPException(404, "Active Admin or Sub Admin profile not found.")
        if grant is None:
            db.add(WebsiteEditorGrant(profile_id=profile_id))
        else:
            return
    elif grant is not None:
        await db.delete(grant)
    else:
        return
    await record(
        db,
        action=AuditAction.WEBSITE_CONTENT_CHANGED,
        entity_type="website_editor_grant",
        entity_uuid=profile_id,
        actor_uuid=user.id,
        actor_role=user.role,
        detail={"event": "granted" if enabled else "revoked"},
    )
    await db.commit()


async def load_document(
    db: AsyncSession, key: str, *, for_update: bool = False
) -> WebsiteDocument | None:
    validate_key(key)
    return await db.get(WebsiteDocument, key, with_for_update=for_update)


async def save_draft(db: AsyncSession, key: str, payload: WebsiteDraftWrite) -> WebsiteDocument:
    # Also serialize creation of a key before the row is available to lock.
    validate_key(key)
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 814))))
    doc = await load_document(db, key, for_update=True)
    if (doc.version if doc else 0) != payload.expected_version:
        raise HTTPException(409, "This draft has changed. Reload it before saving.")
    if doc is None:
        doc = WebsiteDocument(key=key, version=0)
        db.add(doc)
    doc.version += 1
    doc.draft = payload.content.model_dump(mode="json")
    await db.commit()
    return doc


async def publish_document(
    db: AsyncSession, user: CurrentUser, key: str, payload: WebsitePublishWrite
) -> WebsiteDocument:
    doc = await load_document(db, key, for_update=True)
    if doc is None:
        raise HTTPException(404, "Website document not found.")
    if doc.version != payload.expected_version:
        raise HTTPException(409, "This draft has changed. Reload it before publishing.")
    content = doc.draft
    if payload.restore_revision is not None:
        old = await db.get(WebsiteRevision, (key, payload.restore_revision))
        if old is None:
            raise HTTPException(404, "Website revision not found.")
        content = old.content
    if key.startswith("article/") and not (content["title"] and content["body"].strip()):
        raise HTTPException(422, "An article needs a title and body before publishing.")
    doc.version += 1
    doc.published_revision = doc.version
    db.add(
        WebsiteRevision(
            key=key,
            revision=doc.version,
            content=content,
            published_at=datetime.now(UTC),
            actor_id=user.id,
        )
    )
    await record(
        db,
        action=AuditAction.WEBSITE_CONTENT_CHANGED,
        entity_type="website_document",
        entity_uuid=None,
        actor_uuid=user.id,
        actor_role=user.role,
        detail={
            "event": "restored" if payload.restore_revision else "published",
            "key": key,
            "revision": doc.version,
        },
    )
    await db.commit()
    return doc


def published_documents():
    return select(WebsiteRevision).join(
        WebsiteDocument,
        and_(
            WebsiteDocument.key == WebsiteRevision.key,
            WebsiteDocument.published_revision == WebsiteRevision.revision,
        ),
    )
