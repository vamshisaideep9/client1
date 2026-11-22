from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_platform_admin
from app.db.session import get_db
from app.models.property import PropertyCatalogType
from app.schemas.properties import (
    PropertyCatalogTypeRead,
    PropertyCatalogTypeUpdate,
    PropertyCatalogTypeWrite,
)

router = APIRouter()
public_router = APIRouter()

Database = Annotated[AsyncSession, Depends(get_db)]
PlatformAdmin = Annotated[CurrentUser, Depends(require_platform_admin)]


@public_router.get("", response_model=list[PropertyCatalogTypeRead])
async def public_types(db: Database):
    return (
        await db.scalars(
            select(PropertyCatalogType)
            .where(PropertyCatalogType.active.is_(True))
            .order_by(PropertyCatalogType.label, PropertyCatalogType.code)
        )
    ).all()


@router.get("", response_model=list[PropertyCatalogTypeRead])
async def managed_types(db: Database, _user: PlatformAdmin):
    return (await db.scalars(select(PropertyCatalogType).order_by(PropertyCatalogType.label))).all()


@router.post("", response_model=PropertyCatalogTypeRead, status_code=201)
async def add_type(payload: PropertyCatalogTypeWrite, db: Database, _user: PlatformAdmin):
    item = PropertyCatalogType(
        code=uuid4().hex, label=payload.label, form_subtype=payload.form_subtype, active=True
    )
    db.add(item)
    await db.commit()
    return item


@router.patch("/{code}", response_model=PropertyCatalogTypeRead)
async def update_type(
    code: str, payload: PropertyCatalogTypeUpdate, db: Database, _user: PlatformAdmin
):
    item = await db.get(PropertyCatalogType, code, with_for_update=True)
    if item is None:
        raise HTTPException(404, "Property type not found.")
    item.label = payload.label
    item.active = payload.active
    await db.commit()
    return item
