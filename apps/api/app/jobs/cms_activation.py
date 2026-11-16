"""CMS activation job — writes BannerStatus.LIVE/ARCHIVED and OfferStatus.ACTIVE/EXPIRED.

Before this job existed, BannerStatus.LIVE and OfferStatus.EXPIRED were dead enum
values: services/offers.py's request transition maps give EXPIRED no incoming
edge (it is scheduler-owned by design, see that module's comment). This job is
that scheduler. Since 2026-11-16 services/banners.py's approve_banner also calls
activate_banner_if_due (below) in its own transaction, so a banner that is due
and whose slot is free goes live at approval; future-dated or blocked banners
still wait for this job.

NULL-timestamp semantics, one rule for both resources: a NULL bound is an OPEN
bound. NULL starts_at means "already started"; NULL ends_at means "never
ends". This is not the only defensible reading, but it is the only one that
does not ship dead: apps/web/features/sub-admin/banner-form.tsx has no
starts_at/ends_at inputs at all, so every UI-authored banner has NULL
timestamps. Reading NULL starts_at as "never activate" would make this job a
no-op on 100% of real banners; Admin approval is the intentional publish act,
and this job just completes it. Symmetrically, NULL ends_at as "auto-archive
immediately" would archive every evergreen banner/offer the moment it went
live, so NULL ends_at means "evergreen, never auto-expire".

Runs on a plain AsyncSessionLocal() session (app superuser, bypasses RLS) via
`import app.db.session as db_session` -- resolved at call time, NOT
`from app.db.session import AsyncSessionLocal` at module level. This is
deliberate: the module-level form is what forces a module onto
conftest._patch_db_null_pool's rebind list (see that fixture's docstring).
Resolving at call time means this job's tests get the NullPool engine for
free, same as prune_expired_refresh_tokens
(app/scheduler/main.py). Do NOT "fix" this to a top-level import; that would
break tests silently no more than it would break production, but it would
add an unneeded conftest edit.

Idempotent by construction: each operation selects only the exact source status
it then overwrites while holding row locks, so a second run finds nothing left
to do. max_instances=1 on the scheduler registration prevents overlapping
runs; the row locks make an overlap safe as well.

All four lifecycle operations run in ONE transaction (banners then offers, activate
before archive/expire within each): a single logical clock tick, so a banner
and its companion offer that were both due at this tick flip together. Activate-
before-archive also lets a banner or offer whose starts_at AND ends_at are
both already in the past (reachable via the API even though the banner-form UI
never sets these fields) converge in one tick -- approved -> live -> archived
in a single run, rather than sitting live for one extra interval.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

import app.db.session as db_session
from app.models.audit_log import AuditAction
from app.models.banner import Banner, BannerPlacement, BannerStatus
from app.models.offer import Offer, OfferStatus
from app.models.property import Property, ReraVerificationStatus
from app.services.audit_log import record as record_audit

logger = logging.getLogger("scheduler")


def _due_approved_banners(now: datetime | None = None) -> Select[tuple[Banner]]:
    """Approved, not removed, and started (NULL start = already started)."""
    start_bound = func.now() if now is None else now
    return select(Banner).where(
        Banner.status == BannerStatus.APPROVED,
        Banner.removed_at.is_(None),
        or_(Banner.starts_at.is_(None), Banner.starts_at <= start_bound),
    )


async def _activate_if_eligible(session: AsyncSession, banner: Banner) -> bool:
    """Flip one locked, due, approved banner to LIVE when its slot allows it.

    The caller must already hold the row lock on ``banner`` and have checked
    that it is due. Returns False, leaving the row untouched, when the linked
    property is no longer publishable or another campaign holds its slot.
    """
    if banner.property_id is not None:
        property_listing = await session.get(Property, banner.property_id)
        if (
            property_listing is None
            or not property_listing.active
            or property_listing.rera_verification_status
            not in {
                ReraVerificationStatus.VERIFIED,
                ReraVerificationStatus.EXEMPTION_VERIFIED,
            }
        ):
            return False
    # Offer links are legacy metadata only. Coupons are now authenticated
    # dashboard placements, so banner publication must not depend on the
    # linked offer state or expose its code.
    if banner.category_key is not None:
        live_scope = [
            Banner.status == BannerStatus.LIVE,
            Banner.removed_at.is_(None),
            Banner.placement == banner.placement,
        ]
        # Public sponsor themes share one physical slot. Every other
        # public placement still allows one live campaign per category.
        if banner.placement != BannerPlacement.HOMEPAGE_AD:
            live_scope.append(Banner.category_key == banner.category_key)
        current = await session.scalar(select(Banner).where(*live_scope).with_for_update())
        if current is not None:
            if banner.replaces_banner_id != current.id:
                return False
            current.status = BannerStatus.ARCHIVED
            current.updated_at = func.now()
            await record_audit(
                session,
                action=AuditAction.BANNER_ARCHIVED,
                entity_type="banner",
                entity_uuid=current.id,
                actor_uuid=None,
                actor_role="system",
                business_line=current.business_line,
                detail={"placement": current.placement.value, "replaced": True},
            )
    banner.status = BannerStatus.LIVE
    banner.updated_at = func.now()
    await record_audit(
        session,
        action=AuditAction.BANNER_ACTIVATED,
        entity_type="banner",
        entity_uuid=banner.id,
        actor_uuid=None,
        actor_role="system",
        business_line=banner.business_line,
        detail={"placement": banner.placement.value},
    )
    return True


async def activate_banner_if_due(
    session: AsyncSession, banner_id: UUID, now: datetime | None = None
) -> bool:
    """Run the job's activation rules for one banner, inside the caller's transaction.

    Used by Admin approval so a banner that is due and whose slot is free goes
    live in the same commit instead of waiting for the next job tick. A banner
    that is not due, has an unpublishable property, or whose slot is taken
    stays ``approved`` and the job picks it up later. ``now`` defaults to the
    database transaction time, exactly like the job. The caller must flush
    pending changes first (sessions here run with autoflush off).
    """
    banner = await session.scalar(
        _due_approved_banners(now).where(Banner.id == banner_id).with_for_update()
    )
    if banner is None:
        return False
    return await _activate_if_eligible(session, banner)


async def _activate_banners(session: AsyncSession) -> int:
    candidates = (
        await session.scalars(
            _due_approved_banners()
            .order_by(Banner.priority.desc(), Banner.created_at.asc(), Banner.id.asc())
            .with_for_update()
        )
    ).all()
    activated = 0
    for banner in candidates:
        if await _activate_if_eligible(session, banner):
            activated += 1
    return activated


async def _archive_banners(session: AsyncSession) -> int:
    banners = (
        await session.scalars(
            select(Banner)
            .where(
                Banner.status == BannerStatus.LIVE,
                Banner.removed_at.is_(None),
                Banner.ends_at.is_not(None),
                Banner.ends_at <= func.now(),
            )
            .with_for_update()
        )
    ).all()
    for banner in banners:
        banner.status = BannerStatus.ARCHIVED
        banner.updated_at = func.now()
        await record_audit(
            session,
            action=AuditAction.BANNER_ARCHIVED,
            entity_type="banner",
            entity_uuid=banner.id,
            actor_uuid=None,
            actor_role="system",
            business_line=banner.business_line,
            detail={"placement": banner.placement.value, "scheduled": True},
        )
    return len(banners)


async def _activate_offers(session: AsyncSession) -> int:
    offers = (
        await session.scalars(
            select(Offer)
            .where(
                Offer.status == OfferStatus.SCHEDULED,
                Offer.removed_at.is_(None),
                or_(Offer.starts_at.is_(None), Offer.starts_at <= func.now()),
            )
            .with_for_update()
        )
    ).all()
    for offer in offers:
        offer.status = OfferStatus.ACTIVE
        await record_audit(
            session,
            action=AuditAction.OFFER_ACTIVATED,
            entity_type="offer",
            entity_uuid=offer.id,
            actor_uuid=None,
            actor_role="system",
            business_line=offer.business_line,
            detail={"from_status": "scheduled", "to_status": "active", "scheduled": True},
        )
    return len(offers)


async def _expire_offers(session: AsyncSession) -> int:
    offers = (
        await session.scalars(
            select(Offer)
            .where(
                Offer.status == OfferStatus.ACTIVE,
                Offer.removed_at.is_(None),
                Offer.ends_at.is_not(None),
                Offer.ends_at <= func.now(),
            )
            .with_for_update()
        )
    ).all()
    for offer in offers:
        offer.status = OfferStatus.EXPIRED
        await record_audit(
            session,
            action=AuditAction.OFFER_EXPIRED,
            entity_type="offer",
            entity_uuid=offer.id,
            actor_uuid=None,
            actor_role="system",
            business_line=offer.business_line,
            detail={"from_status": "active", "to_status": "expired", "scheduled": True},
        )
    return len(offers)


async def cms_activation() -> dict[str, int]:
    started = time.monotonic()
    logger.info("job.cms_activation.start")
    try:
        async with db_session.AsyncSessionLocal() as session:
            banners_activated = await _activate_banners(session)
            banners_archived = await _archive_banners(session)
            offers_activated = await _activate_offers(session)
            offers_expired = await _expire_offers(session)
            await session.commit()
    except Exception:
        logger.exception("job.cms_activation.failed")
        raise
    else:
        summary = {
            "banners_activated": banners_activated,
            "banners_archived": banners_archived,
            "offers_activated": offers_activated,
            "offers_expired": offers_expired,
        }
        logger.info(
            "job.cms_activation.success banners_activated=%d banners_archived=%d "
            "offers_activated=%d offers_expired=%d duration_ms=%d",
            banners_activated,
            banners_archived,
            offers_activated,
            offers_expired,
            (time.monotonic() - started) * 1000,
        )
        return summary
