"""Database backstops for listing media (migration c7e9a1b3d5f7, CS-018).

The API already limits listings to ten 360 panoramas in JPEG/PNG/WebP/AVIF;
these tests check the database refuses the same violations on its own, for
both the private submission media and the published property media.

Requires: running Postgres (docker compose up -d).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.property import Property
from app.models.property_media import PropertyMedia, PropertySubmissionMedia
from app.tests.test_property_media_rls import _seed_submission, _user_uuid
from conftest import full_registration


def _submission_media(
    submission_id: uuid.UUID, owner: uuid.UUID, position: int, *, kind: str, content_type: str
) -> PropertySubmissionMedia:
    ext = content_type.split("/")[-1]
    return PropertySubmissionMedia(
        submission_uuid=submission_id,
        business_line="real_estate",
        kind=kind,
        content_type=content_type,
        object_key=f"private/property-submissions/canonical/{owner}/{uuid.uuid4()}/asset.{ext}",
        size_bytes=1024,
        position=position,
    )


async def _owner_and_submission(client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID]:
    _, mobile = await full_registration(client, lines=["real_estate"])
    owner = await _user_uuid(mobile)
    return owner, await _seed_submission(owner)


@pytest.mark.asyncio
async def test_submission_accepts_ten_panoramas_and_refuses_an_eleventh(
    client: AsyncClient,
) -> None:
    import app.db.session as session_module

    owner, submission_id = await _owner_and_submission(client)
    types = ["image/jpeg", "image/png", "image/webp", "image/avif"]
    async with session_module.AsyncSessionLocal() as session:
        for position in range(10):
            session.add(
                _submission_media(
                    submission_id,
                    owner,
                    position,
                    kind="panorama",
                    content_type=types[position % len(types)],
                )
            )
        await session.commit()

    async with session_module.AsyncSessionLocal() as session:
        session.add(
            _submission_media(submission_id, owner, 10, kind="panorama", content_type="image/jpeg")
        )
        with pytest.raises(DBAPIError, match="at most 10 360 panoramas"):
            await session.commit()


@pytest.mark.asyncio
async def test_submission_accepts_avif_images_and_the_widened_positions(
    client: AsyncClient,
) -> None:
    import app.db.session as session_module

    owner, submission_id = await _owner_and_submission(client)
    async with session_module.AsyncSessionLocal() as session:
        session.add(
            _submission_media(submission_id, owner, 21, kind="image", content_type="image/avif")
        )
        await session.commit()

    async with session_module.AsyncSessionLocal() as session:
        session.add(
            _submission_media(submission_id, owner, 22, kind="image", content_type="image/jpeg")
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_submission_still_refuses_unknown_image_types(client: AsyncClient) -> None:
    import app.db.session as session_module

    owner, submission_id = await _owner_and_submission(client)
    async with session_module.AsyncSessionLocal() as session:
        session.add(
            _submission_media(submission_id, owner, 0, kind="panorama", content_type="image/gif")
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_public_media_caps_panoramas_at_ten() -> None:
    import app.db.session as session_module

    async with session_module.AsyncSessionLocal() as session:
        prop = Property(
            business_line="real_estate",
            active=False,
            title="Panorama cap listing",
            type="Apartment",
            location="Baner, Pune",
            price_display="₹50 L",
            category="apartments",
            city="Pune",
            locality="Baner",
            pincode="411045",
            price_paise=5_000_000,
            furnishing="semi",
            construction_status="ready",
            rera_number="RERA/MEDIA/CAP",
        )
        session.add(prop)
        await session.flush()
        for position in range(10, 20):
            session.add(
                PropertyMedia(
                    property_uuid=prop.id,
                    business_line="real_estate",
                    kind="panorama",
                    content_type="image/avif",
                    object_key=f"public/properties/{prop.id}/{uuid.uuid4()}/asset.avif",
                    size_bytes=1024,
                    position=position,
                )
            )
        await session.commit()
        property_id = prop.id

    async with session_module.AsyncSessionLocal() as session:
        session.add(
            PropertyMedia(
                property_uuid=property_id,
                business_line="real_estate",
                kind="panorama",
                content_type="image/png",
                object_key=f"public/properties/{property_id}/{uuid.uuid4()}/asset.png",
                size_bytes=1024,
                position=0,
            )
        )
        with pytest.raises(DBAPIError, match="at most 10 360 panoramas"):
            await session.commit()
