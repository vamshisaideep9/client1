"""Atomic commission payout creation and platform Admin membership reads."""

from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.lead_reference import format_optional_lead_ref
from app.models.commission import Commission, CommissionPayoutItem, CommissionStatus
from app.models.lead import Lead
from app.models.payout import PayoutType
from app.models.profile import AgentProfile
from app.models.user import User
from app.schemas.commissions import (
    CommissionPayoutGroup,
    CommissionPayoutGroupList,
    CommissionPayoutRequest,
    CoveredCommission,
)
from app.services import payments
from app.services.commissions import CommissionAlreadyResolved, CommissionNotFound


async def create_for_commissions(
    ids: list[UUID],
    request: CommissionPayoutRequest,
    *,
    maker_uuid: UUID,
    maker_role: str,
    bulk: bool,
) -> UUID:
    """Claim all selected sources in the same transaction as the payout."""
    async with db_session.AsyncSessionLocal() as db, db.begin():
        rows = (
            await db.scalars(
                select(Commission)
                .where(
                    Commission.id.in_(ids),
                    Commission.status == CommissionStatus.PENDING,
                    Commission.payout_uuid.is_(None),
                )
                .order_by(Commission.id)
                .with_for_update()
            )
        ).all()
        if len(rows) != len(ids):
            found = await db.scalar(
                select(func.count()).select_from(Commission).where(Commission.id.in_(ids))
            )
            if found != len(ids):
                raise CommissionNotFound("One or more commissions were not found.")
            raise CommissionAlreadyResolved("A selected commission is not awaiting payout.")

        first = rows[0]
        for row in rows:
            if (
                row.agent_profile_uuid != first.agent_profile_uuid
                or row.agent_auth_user_uuid != first.agent_auth_user_uuid
                or row.business_line != first.business_line
            ):
                raise CommissionAlreadyResolved(
                    "Select commissions for one Agent and business line."
                )

        # PostgreSQL orders UUIDs consistently across all overlapping requests.
        # Keep the single-route key so legacy retries use the same natural key.
        digest = sha256(b"".join(row.id.bytes for row in rows)).hexdigest()[:59]
        payout = await payments.prepare_payout(
            db,
            recipient_user_uuid=first.agent_auth_user_uuid,
            payout_type=PayoutType.COMMISSION,
            business_line=first.business_line,
            amount_paise=sum(row.agreed_amount_paise for row in rows),
            destination_type=request.destination_type,
            destination=request.destination.model_dump(),
            idempotency_key=f"comb-{digest}" if bulk else f"com-{first.id.hex}",
            maker_user_uuid=maker_uuid,
            actor_role=maker_role,
        )
        for row in rows:
            row.payout_uuid = payout.id
            db.add(
                CommissionPayoutItem(
                    payout_uuid=payout.id,
                    commission_uuid=row.id,
                    amount_paise=row.agreed_amount_paise,
                )
            )

    await payments.initiate_standalone_payout(payout)
    return payout.id


async def list_pending_groups(
    db: AsyncSession, *, limit: int, offset: int
) -> CommissionPayoutGroupList:
    grouped = (
        select(
            Commission.agent_profile_uuid,
            Commission.business_line,
            func.count().label("pending_count"),
            func.sum(Commission.agreed_amount_paise).label("pending_amount_paise"),
        )
        .where(Commission.status == CommissionStatus.PENDING, Commission.payout_uuid.is_(None))
        .group_by(Commission.agent_profile_uuid, Commission.business_line)
        .subquery()
    )
    total = await db.scalar(select(func.count()).select_from(grouped)) or 0
    rows = await db.execute(
        select(
            grouped,
            AgentProfile.agent_code,
            func.nullif(func.trim(func.concat_ws(" ", User.first_name, User.last_name)), "").label(
                "agent_name"
            ),
        )
        .join(AgentProfile, AgentProfile.id == grouped.c.agent_profile_uuid)
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .order_by(AgentProfile.agent_code, grouped.c.business_line, grouped.c.agent_profile_uuid)
        .limit(limit)
        .offset(offset)
    )
    return CommissionPayoutGroupList(
        groups=[CommissionPayoutGroup.model_validate(row) for row in rows.mappings()], total=total
    )


async def list_items(db: AsyncSession, payout_id: UUID) -> list[CoveredCommission]:
    rows = await db.execute(
        select(
            Commission.id,
            Commission.loan_application_uuid,
            Commission.property_deal_uuid,
            CommissionPayoutItem.amount_paise,
            Lead.lead_number,
        )
        .join(CommissionPayoutItem, CommissionPayoutItem.commission_uuid == Commission.id)
        .outerjoin(Lead, Lead.id == Commission.lead_uuid)
        .where(CommissionPayoutItem.payout_uuid == payout_id)
        .order_by(Commission.created_at, Commission.id)
    )
    return [
        CoveredCommission(
            id=row.id,
            deal_type="loan_application" if row.loan_application_uuid else "property_deal",
            deal_uuid=row.loan_application_uuid or row.property_deal_uuid,
            lead_ref=format_optional_lead_ref(row.lead_number),
            amount_paise=row.amount_paise,
        )
        for row in rows
    ]
