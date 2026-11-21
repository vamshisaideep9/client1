"""Sub Admin campaign Media Library; Admin has read-only preview access."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    check_assignment_line,
    require_assignment,
)
from app.db.session import get_db
from app.models.campaign_media import CampaignMediaAsset
from app.schemas.campaign_media import (
    CampaignMediaCreate,
    CampaignMediaListResponse,
    CampaignMediaRead,
    CampaignMediaUpdate,
    CampaignMediaUploadRequest,
    CampaignMediaUploadResponse,
    CampaignMediaUsageType,
)
from app.services.campaign_media import (
    CampaignMediaInUse,
    CampaignMediaInvalid,
    create_asset,
    delete_asset,
    presign_campaign_media,
    read_asset,
    update_asset,
    upload_limit,
    usage_counts,
)

media_view = require_assignment("media_sub_admin", "view")
media_edit = require_assignment("media_sub_admin", "edit")

router = APIRouter()


@router.post("/image-upload-url", response_model=CampaignMediaUploadResponse)
async def image_upload_url(
    payload: CampaignMediaUploadRequest,
    current_user: CurrentUser = Depends(media_edit),
) -> CampaignMediaUploadResponse:
    try:
        url, fields, object_key = presign_campaign_media(payload.content_type, payload.filename)
    except CampaignMediaInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported campaign media. Use JPEG, PNG, WEBP, or MP4.",
        ) from exc
    return CampaignMediaUploadResponse(
        object_key=object_key,
        upload_url=url,
        fields=fields,
        max_bytes=upload_limit(payload.content_type),
    )


@router.post("", response_model=CampaignMediaRead, status_code=status.HTTP_201_CREATED)
async def confirm_media(
    payload: CampaignMediaCreate,
    current_user: CurrentUser = Depends(media_edit),
    db: AsyncSession = Depends(get_db),
) -> CampaignMediaRead:
    check_assignment_line(current_user, "media_sub_admin", "edit", payload.business_line)
    try:
        asset = await create_asset(
            db, payload=payload, actor_uuid=current_user.id, actor_role=current_user.role
        )
        return await read_asset(db, asset)
    except CampaignMediaInvalid as exc:
        detail = (
            "Upload a valid MP4 banner video (H.264 with AAC audio) of up to 60 seconds."
            if payload.content_type == "video/mp4"
            else "Upload a valid landscape campaign image with the required placement dimensions."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
        ) from exc


@router.get("", response_model=CampaignMediaListResponse)
async def list_media(
    active_only: bool = False,
    usage_type: CampaignMediaUsageType | None = None,
    business_line: Literal["loans", "real_estate", "both"] | None = None,
    current_user: CurrentUser = Depends(media_view),
    db: AsyncSession = Depends(get_db),
) -> CampaignMediaListResponse:
    stmt = select(CampaignMediaAsset).order_by(CampaignMediaAsset.created_at.desc())
    if active_only:
        stmt = stmt.where(CampaignMediaAsset.active.is_(True))
    if usage_type:
        stmt = stmt.where(CampaignMediaAsset.usage_type == usage_type)
    if business_line:
        stmt = stmt.where(
            CampaignMediaAsset.business_line == business_line
            if business_line == "both"
            else CampaignMediaAsset.business_line.in_((business_line, "both"))
        )
    assets = (await db.scalars(stmt)).all()
    counts = await usage_counts(db, [item.id for item in assets])
    return CampaignMediaListResponse(
        assets=[await read_asset(db, item, usage_count=counts.get(item.id, 0)) for item in assets]
    )


@router.get("/{asset_id}", response_model=CampaignMediaRead)
async def get_media(
    asset_id: UUID,
    current_user: CurrentUser = Depends(media_view),
    db: AsyncSession = Depends(get_db),
) -> CampaignMediaRead:
    asset = await db.get(CampaignMediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    return await read_asset(db, asset)


@router.patch("/{asset_id}", response_model=CampaignMediaRead)
async def patch_media(
    asset_id: UUID,
    payload: CampaignMediaUpdate,
    current_user: CurrentUser = Depends(media_edit),
    db: AsyncSession = Depends(get_db),
) -> CampaignMediaRead:
    asset = await db.scalar(
        select(CampaignMediaAsset).where(CampaignMediaAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    check_assignment_line(current_user, "media_sub_admin", "edit", asset.business_line)
    updated = await update_asset(
        db,
        asset=asset,
        payload=payload,
        actor_uuid=current_user.id,
        actor_role=current_user.role,
    )
    return await read_asset(db, updated)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_media(
    asset_id: UUID,
    current_user: CurrentUser = Depends(media_edit),
    db: AsyncSession = Depends(get_db),
) -> None:
    asset = await db.scalar(
        select(CampaignMediaAsset).where(CampaignMediaAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    check_assignment_line(current_user, "media_sub_admin", "edit", asset.business_line)
    try:
        await delete_asset(
            db, asset=asset, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except CampaignMediaInUse as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This artwork is still used by a banner, offer, or governed template.",
        ) from exc
