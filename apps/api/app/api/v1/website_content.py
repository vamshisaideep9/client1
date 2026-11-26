from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user
from app.db.session import get_db
from app.models.website_content import WebsiteDocument, WebsiteRevision
from app.schemas.website_content import (
    PublicWebsiteContent,
    WebsiteAccess,
    WebsiteDocumentRead,
    WebsiteDraftWrite,
    WebsiteEditor,
    WebsiteGrantWrite,
    WebsitePublishWrite,
    WebsiteRevisionRead,
)
from app.services.website_content import (
    eligible_editors,
    load_document,
    publish_document,
    published_documents,
    save_draft,
    set_grant,
    validate_key,
    website_access,
)

router = APIRouter()
public_router = APIRouter()


async def require_editor(db: AsyncSession, user: CurrentUser) -> None:
    if not (await website_access(db, user, lock=True)).can_edit:
        raise HTTPException(403, "Website draft access is required.")


async def require_publisher(db: AsyncSession, user: CurrentUser) -> None:
    if not (await website_access(db, user)).can_publish:
        raise HTTPException(403, "Only Main Admin can manage website publishing and access.")


@router.get("/access", response_model=WebsiteAccess)
async def access(
    response: Response,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"
    return await website_access(db, user)


@router.get("/editors", response_model=list[WebsiteEditor])
async def editors(
    response: Response,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_publisher(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    return [
        WebsiteEditor(profile_id=p.id, staff_code=p.staff_code, role=p.role, enabled=g is not None)
        for p, g in await eligible_editors(db)
    ]


@router.put("/editors/{profile_id}", status_code=204)
async def update_editor(
    profile_id: UUID,
    payload: WebsiteGrantWrite,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_publisher(db, user)
    await set_grant(db, user, profile_id, enabled=payload.enabled)


@router.get("/documents", response_model=list[str])
async def documents(
    response: Response,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_editor(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    return (await db.scalars(select(WebsiteDocument.key).order_by(WebsiteDocument.key))).all()


@router.get("/revisions/{key:path}", response_model=list[WebsiteRevisionRead])
async def revisions(
    key: str,
    response: Response,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_editor(db, user)
    validate_key(key)
    response.headers["Cache-Control"] = "private, no-store"
    return (
        await db.scalars(
            select(WebsiteRevision)
            .where(WebsiteRevision.key == key)
            .order_by(WebsiteRevision.revision.desc())
        )
    ).all()


@router.post("/publish/{key:path}", response_model=WebsiteDocumentRead)
async def publish(
    key: str,
    payload: WebsitePublishWrite,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_publisher(db, user)
    return await publish_document(db, user, key, payload)


@router.get("/documents/{key:path}", response_model=WebsiteDocumentRead)
async def document(
    key: str,
    response: Response,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_editor(db, user)
    doc = await load_document(db, key)
    if doc is None:
        raise HTTPException(404, "Website document not found.")
    response.headers["Cache-Control"] = "private, no-store"
    return doc


@router.put("/documents/{key:path}", response_model=WebsiteDocumentRead)
async def update_document(
    key: str,
    payload: WebsiteDraftWrite,
    user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_editor(db, user)
    return await save_draft(db, key, payload)


@public_router.get("/articles", response_model=list[PublicWebsiteContent])
async def public_articles(db: AsyncSession = Depends(get_db)):
    return (
        await db.scalars(
            published_documents()
            .where(WebsiteRevision.key.startswith("article/"))
            .order_by(WebsiteRevision.published_at.desc(), WebsiteRevision.key)
        )
    ).all()


@public_router.get("/{key:path}", response_model=PublicWebsiteContent)
async def public_document(key: str, db: AsyncSession = Depends(get_db)):
    validate_key(key)
    item = await db.scalar(published_documents().where(WebsiteRevision.key == key))
    if item is None:
        raise HTTPException(404, "Published content not found.")
    return item
