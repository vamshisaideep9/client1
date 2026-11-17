"""Mobile-number identity rules shared by every path that replaces a number.

The support-assisted recovery (``services/mobile_change.py``) and the CS-025
contact-change journeys (``services/contact_change.py``) must refuse the same
conflicts and carry a new number into the same open records, so both use these
helpers. Every function runs on the caller's bypass session inside its
transaction; none commits.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import (
    RedisCache,
    login_fail_key,
    login_lock_key,
    otp_email_verify_key,
    otp_email_verify_target_key,
    otp_lock_key,
    otp_mobile_change_key,
    otp_register_email_key,
    otp_register_email_target_key,
    otp_register_key,
    otp_resend_key,
    otp_reset_key,
    reg_data_key,
)
from app.models.enquiry import Enquiry, EnquiryStatus
from app.models.lead import Lead, LeadStatus
from app.models.profile import AgentApplication, ClientProfile, SubmissionStatus
from app.models.referral import Referral, ReferralStatus
from app.models.site_visit import SiteVisit, SiteVisitStatus
from app.models.user import User

logger = logging.getLogger(__name__)


async def mobile_conflicts(
    db: AsyncSession, *, user_uuid: UUID, requested_mobile: str
) -> list[str]:
    """Reasons the number cannot become this account's login number.

    Codes only, never the other record: another account's login number, or an
    open lead, referral or Agent application on that number that is not this
    account's own.
    """
    conflicts: list[str] = []
    replacement_owner = await db.scalar(
        select(User.id).where(User.mobile == requested_mobile, User.id != user_uuid)
    )
    if replacement_owner is not None:
        conflicts.append("replacement_number_in_use")

    profile_ids = set(
        await db.scalars(select(ClientProfile.id).where(ClientProfile.auth_user_uuid == user_uuid))
    )
    lead_conflict = select(Lead.id).where(Lead.mobile == requested_mobile)
    if profile_ids:
        lead_conflict = lead_conflict.where(
            or_(
                Lead.client_profile_uuid.is_(None),
                Lead.client_profile_uuid.not_in(profile_ids),
            )
        )
    if await db.scalar(lead_conflict.limit(1)) is not None:
        conflicts.append("replacement_number_has_unlinked_lead")
    referral_conflict = await db.scalar(
        select(Referral.id)
        .where(
            Referral.referred_mobile == requested_mobile,
            or_(
                Referral.referred_auth_user_uuid.is_(None),
                Referral.referred_auth_user_uuid != user_uuid,
            ),
        )
        .limit(1)
    )
    if referral_conflict is not None:
        conflicts.append("replacement_number_has_unlinked_referral")
    application_rows = (
        await db.scalars(
            select(AgentApplication).where(
                AgentApplication.mobile == requested_mobile,
                AgentApplication.status == SubmissionStatus.PENDING,
            )
        )
    ).all()
    if any(row.applicant_auth_user_uuid != user_uuid for row in application_rows):
        conflicts.append("replacement_number_has_unlinked_application")
    return conflicts


async def propagate_mobile(db: AsyncSession, *, user_uuid: UUID, new_mobile: str) -> None:
    """Carry the new number into the account's own open records."""
    profile_ids = set(
        await db.scalars(select(ClientProfile.id).where(ClientProfile.auth_user_uuid == user_uuid))
    )
    if profile_ids:
        await db.execute(
            update(Lead)
            .where(
                Lead.client_profile_uuid.in_(profile_ids),
                Lead.status.not_in((LeadStatus.CONVERTED, LeadStatus.CLOSED)),
            )
            .values(mobile=new_mobile)
        )
    await db.execute(
        update(Referral)
        .where(
            Referral.referred_auth_user_uuid == user_uuid,
            Referral.conversion_status == ReferralStatus.PENDING,
        )
        .values(referred_mobile=new_mobile)
    )
    await db.execute(
        update(Enquiry)
        .where(Enquiry.user_uuid == user_uuid, Enquiry.status != EnquiryStatus.CLOSED)
        .values(contact_mobile=new_mobile)
    )
    await db.execute(
        update(SiteVisit)
        .where(
            SiteVisit.user_uuid == user_uuid,
            SiteVisit.status.in_((SiteVisitStatus.REQUESTED, SiteVisitStatus.CONFIRMED)),
        )
        .values(contact_mobile=new_mobile)
    )
    await db.execute(
        update(AgentApplication)
        .where(
            AgentApplication.applicant_auth_user_uuid == user_uuid,
            AgentApplication.status == SubmissionStatus.PENDING,
        )
        .values(mobile=new_mobile)
    )


async def clear_identity_caches(cache: RedisCache, old_mobile: str, new_mobile: str) -> None:
    """Drop short-lived number-keyed caches after a number changed hands."""
    keys: list[str] = []
    for number in (old_mobile, new_mobile):
        keys.extend(
            [
                otp_mobile_change_key(number),
                f"{otp_mobile_change_key(number)}:attempts",
                otp_register_key(number),
                f"{otp_register_key(number)}:attempts",
                otp_register_email_key(number),
                f"{otp_register_email_key(number)}:attempts",
                otp_register_email_target_key(number),
                otp_reset_key(number),
                f"{otp_reset_key(number)}:attempts",
                otp_email_verify_key(number),
                f"{otp_email_verify_key(number)}:attempts",
                otp_email_verify_target_key(number),
                otp_resend_key(number),
                otp_lock_key(number),
                login_fail_key(number),
                login_lock_key(number),
                reg_data_key(number),
            ]
        )
    try:
        await cache.delete(*keys)
    except Exception:
        # The database transaction is authoritative and already committed.
        # These are short-lived defensive caches; a Redis outage must not turn
        # a successful identity update into a misleading API failure/retry.
        logger.warning("identity.cache_cleanup_failed", exc_info=True)
