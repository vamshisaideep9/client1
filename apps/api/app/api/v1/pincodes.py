"""Pincode place names and "use my location" (CS-026).

Both routes need a signed-in account (any role may read the non-personal
reference list; only the roles that edit their own profile may map a position
to a pincode) and run on the RLS session like every other authenticated route.

The nearest-pincode route takes the position in a POST body, never the URL, so
it cannot reach access logs or proxies' request lines. It is used for one
in-process lookup and dropped: no query, table, audit row, auth event, Redis
key or log line receives it. The response carries the pincode and place name only; the person
confirms it and saves it through ``PATCH /auth/me`` like any profile field.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import (
    TTL_PINCODE_RATE,
    RedisCache,
    pincode_lookup_rate_key,
    pincode_nearest_rate_key,
)
from app.core.deps import CurrentUser, get_active_user, get_cache
from app.db.session import get_db
from app.models.pincode import Pincode
from app.schemas.pincodes import (
    PINCODE_PATTERN,
    NearestPincodeRequest,
    PincodeDistrictRead,
    PincodePlaceRead,
)
from app.services import pincodes
from app.services.auth_service import ensure_self_service_allowed

router = APIRouter()

PINCODE_LOOKUPS_PER_HOUR = 120
NEAREST_LOOKUPS_PER_HOUR = 10
_NO_STORE = {"Cache-Control": "private, no-store"}


def place_read(row: Pincode) -> PincodePlaceRead:
    return PincodePlaceRead(
        pincode=row.pincode, area=row.area, district=row.district, state=row.state
    )


async def _within_budget(cache: RedisCache, key: str, limit: int) -> None:
    if await cache.incr_with_expire(key, TTL_PINCODE_RATE) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many pincode lookups. Try again later.",
        )


@router.post("/nearest", response_model=PincodePlaceRead)
async def nearest_pincode(
    payload: NearestPincodeRequest,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
) -> PincodePlaceRead:
    """Suggest the pincode nearest to a one-time device position (not stored)."""
    ensure_self_service_allowed(current_user.role, "change your profile")
    await _within_budget(
        cache, pincode_nearest_rate_key(str(current_user.id)), NEAREST_LOOKUPS_PER_HOUR
    )
    row = await pincodes.nearest_pincode(db, payload.latitude, payload.longitude)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="We couldn't match your location to a pincode. Enter your pincode instead.",
            headers=_NO_STORE,
        )
    response.headers.update(_NO_STORE)
    return place_read(row)


@router.get("/districts", response_model=list[PincodeDistrictRead])
async def list_districts(
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
) -> list[PincodeDistrictRead]:
    """Every district (with its state) on the list: the cities a campaign can target.

    Declared before ``/{pincode}`` so the literal path is matched first.
    """
    await _within_budget(
        cache, pincode_lookup_rate_key(str(current_user.id)), PINCODE_LOOKUPS_PER_HOUR
    )
    rows = await pincodes.list_districts(db)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return [PincodeDistrictRead(district=district, state=state) for district, state in rows]


@router.get("/{pincode}", response_model=PincodePlaceRead)
async def get_pincode(
    response: Response,
    pincode: str = Path(pattern=PINCODE_PATTERN),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
) -> PincodePlaceRead:
    """Place name (area, district, state) for a pincode."""
    await _within_budget(
        cache, pincode_lookup_rate_key(str(current_user.id)), PINCODE_LOOKUPS_PER_HOUR
    )
    row = await pincodes.get_place(db, pincode)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="We don't recognise this pincode.",
            headers=_NO_STORE,
        )
    # Reference data: identical for every caller, but served to signed-in
    # callers only, so private caching.
    response.headers["Cache-Control"] = "private, max-age=86400"
    return place_read(row)
