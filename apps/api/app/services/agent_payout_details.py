"""Agent-saved payout destination: encrypted storage, masked reads, audited reveal.

The Agent's own reads and writes run on the request-scoped RLS session
(owner-only policies). A payout maker's prefill read runs on the owner session
after the router proves payout-request access, the same shape as the payout
recipient search, and appends an ``agent_payout_details_viewed`` audit event.

Raw account numbers and UPI IDs never enter logs, audit details, or error text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core import field_crypto
from app.core.masking import mask_bank_account, mask_vpa
from app.models.agent_payout_details import AgentPayoutDetails
from app.models.audit_log import AuditAction
from app.schemas.agent_payout_details import AgentBankAccount, AgentPayoutDetailsUpdate
from app.services.audit_log import record as record_audit


class PayoutDetailsUnavailable(Exception):
    """This environment has no encryption key, so details cannot be stored or read."""


class PayoutDetailsEmpty(Exception):
    """The update would leave neither a UPI ID nor a bank account."""


class PayoutDetailsUnreadable(Exception):
    """A stored blob failed authentication (wrong key/version or tampering)."""


class SelfPayoutDetailsForbidden(Exception):
    """A payout maker asked for their own saved details."""


@dataclass(frozen=True)
class SavedDestination:
    upi_id: str | None
    bank: AgentBankAccount | None
    updated_at: datetime


def _aad(agent_profile_uuid: UUID, field: str) -> bytes:
    return f"agent-payout-details:{agent_profile_uuid}:{field}".encode()


def _bank_hint(bank: AgentBankAccount) -> str:
    return mask_bank_account(bank.ifsc, bank.account_number)


async def get_own(db: AsyncSession, agent_profile_uuid: UUID) -> AgentPayoutDetails | None:
    return await db.scalar(
        select(AgentPayoutDetails).where(
            AgentPayoutDetails.agent_profile_uuid == agent_profile_uuid
        )
    )


async def save_own(
    db: AsyncSession,
    *,
    agent_profile_uuid: UUID,
    auth_user_uuid: UUID,
    payload: AgentPayoutDetailsUpdate,
) -> AgentPayoutDetails:
    if not field_crypto.is_available():
        raise PayoutDetailsUnavailable
    row = await db.scalar(
        select(AgentPayoutDetails)
        .where(AgentPayoutDetails.agent_profile_uuid == agent_profile_uuid)
        .with_for_update()
    )
    created = row is None
    if row is None:
        row = AgentPayoutDetails(
            agent_profile_uuid=agent_profile_uuid,
            auth_user_uuid=auth_user_uuid,
            key_version=field_crypto.current_key_version(),
        )

    changes: dict[str, str] = {}
    if "upi_id" in payload.model_fields_set:
        if payload.upi_id is None:
            row.upi_ciphertext, row.upi_hint = None, None
            changes["upi"] = "removed"
        else:
            row.upi_ciphertext = field_crypto.encrypt(
                payload.upi_id, associated_data=_aad(agent_profile_uuid, "upi")
            )
            row.upi_hint = mask_vpa(payload.upi_id)[:40]
            changes["upi"] = "set"
    if "bank" in payload.model_fields_set:
        if payload.bank is None:
            row.bank_ciphertext, row.bank_hint = None, None
            changes["bank"] = "removed"
        else:
            row.bank_ciphertext = field_crypto.encrypt(
                payload.bank.model_dump_json(), associated_data=_aad(agent_profile_uuid, "bank")
            )
            row.bank_hint = _bank_hint(payload.bank)[:60]
            changes["bank"] = "set"

    if row.upi_ciphertext is None and row.bank_ciphertext is None:
        await db.rollback()
        raise PayoutDetailsEmpty
    row.key_version = field_crypto.current_key_version()
    row.updated_at = datetime.now(UTC)
    if created:
        db.add(row)
    await db.flush()
    await record_audit(
        db,
        action=AuditAction.AGENT_PAYOUT_DETAILS_UPDATED,
        entity_type="agent_payout_details",
        entity_uuid=agent_profile_uuid,
        actor_uuid=auth_user_uuid,
        actor_role="agent",
        detail=changes,
    )
    await db.commit()
    return row


async def delete_own(db: AsyncSession, *, agent_profile_uuid: UUID, auth_user_uuid: UUID) -> bool:
    row = await get_own(db, agent_profile_uuid)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    await record_audit(
        db,
        action=AuditAction.AGENT_PAYOUT_DETAILS_DELETED,
        entity_type="agent_payout_details",
        entity_uuid=agent_profile_uuid,
        actor_uuid=auth_user_uuid,
        actor_role="agent",
    )
    await db.commit()
    return True


def _decrypt_row(row: AgentPayoutDetails) -> SavedDestination:
    try:
        upi_id = (
            field_crypto.decrypt(
                row.upi_ciphertext, associated_data=_aad(row.agent_profile_uuid, "upi")
            )
            if row.upi_ciphertext is not None
            else None
        )
        bank = (
            AgentBankAccount.model_validate(
                json.loads(
                    field_crypto.decrypt(
                        row.bank_ciphertext, associated_data=_aad(row.agent_profile_uuid, "bank")
                    )
                )
            )
            if row.bank_ciphertext is not None
            else None
        )
    except (field_crypto.FieldDecryptionError, ValueError, ValidationError) as exc:
        raise PayoutDetailsUnreadable from exc
    return SavedDestination(upi_id=upi_id, bank=bank, updated_at=row.updated_at)


async def reveal_for_payout(
    *,
    actor_auth_user_uuid: UUID,
    actor_role: str,
    recipient_auth_user_uuid: UUID | None = None,
    agent_profile_uuid: UUID | None = None,
) -> SavedDestination | None:
    """Decrypt an Agent's saved destination for one payout maker, with audit.

    Look up by the recipient's account or by Agent profile (commission
    payouts carry only the profile). The caller (router) must already have
    proven payout-request access. A maker's own details are refused before
    anything is decrypted or audited. Returns None when nothing is saved.
    """
    if (recipient_auth_user_uuid is None) == (agent_profile_uuid is None):
        raise ValueError("Pass exactly one of recipient_auth_user_uuid or agent_profile_uuid.")
    if not field_crypto.is_available():
        raise PayoutDetailsUnavailable
    stmt = select(AgentPayoutDetails)
    if agent_profile_uuid is not None:
        stmt = stmt.where(AgentPayoutDetails.agent_profile_uuid == agent_profile_uuid)
    else:
        stmt = stmt.where(AgentPayoutDetails.auth_user_uuid == recipient_auth_user_uuid)
    async with db_session.AsyncSessionLocal() as session:
        row = await session.scalar(stmt.order_by(AgentPayoutDetails.updated_at.desc()).limit(1))
        if row is None:
            return None
        if row.auth_user_uuid == actor_auth_user_uuid:
            raise SelfPayoutDetailsForbidden
        saved = _decrypt_row(row)
        await record_audit(
            session,
            action=AuditAction.AGENT_PAYOUT_DETAILS_VIEWED,
            entity_type="agent_payout_details",
            entity_uuid=row.agent_profile_uuid,
            actor_uuid=actor_auth_user_uuid,
            actor_role=actor_role,
            detail={
                "recipient_auth_user_uuid": str(row.auth_user_uuid),
                "fields": [
                    name
                    for name, present in (("upi", saved.upi_id), ("bank", saved.bank))
                    if present
                ],
                "purpose": "payout_prefill",
            },
        )
        await session.commit()
    return saved
