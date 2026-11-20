"""Contests (CS-027): authoring, maker-checker review and lifecycle commands.

Authoring runs on the caller's request session under RLS: only a Sub Admin
inserts, and only the maker edits, submits, withdraws, cancels or deletes
their own contest while it is a draft, awaiting review or rejected (the
``contests_*`` policies enforce the same). Admin commands (approve, reject)
run on the bypass session with a row lock, like ``services/banners.py``:
the reviewer is never the maker (checked here and by
``ck_contests_checker_not_maker``).

Dates are inclusive India Standard Time calendar days. A contest may not be
submitted or approved once its start date has passed, so its window never
predates its approval.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.models.audit_log import AuditAction
from app.models.contest import Contest, ContestStatus
from app.models.loan import Bank, LoanType
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.schemas.contests import (
    ContestAdminUpdate,
    ContestCriteria,
    ContestDefinition,
    ContestRead,
)
from app.services.admin_notify import notify_admins
from app.services.audit_log import record as record_audit
from app.services.notifications import emit_notification

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_EDITABLE = (ContestStatus.DRAFT.value, ContestStatus.REJECTED.value)
_MAKER_CANCELLABLE = (
    ContestStatus.DRAFT.value,
    ContestStatus.PENDING_APPROVAL.value,
    ContestStatus.REJECTED.value,
)
_ADMIN_EDITABLE = (
    ContestStatus.PENDING_APPROVAL.value,
    ContestStatus.APPROVED.value,
    ContestStatus.LIVE.value,
)
_ITEM_PRIZES = ("item_prize", "manager_item_prize", "member_item_prize")
_LIVE_TEXT = {"title", "description", "terms", "ends_on", "end_time"}


class ContestError(Exception):
    """Base for contest service errors; the router maps subclasses to HTTP."""


class ContestNotFound(ContestError):
    pass


class ContestNotOwned(ContestError):
    """Only the Sub Admin who created the contest may change it."""


class ContestStateError(ContestError):
    """The command does not apply to the contest's current status."""


class ContestMakerChecker(ContestError):
    """The reviewer is the maker."""


class ContestInvalid(ContestError):
    """The definition refers to something that does not exist or is out of date."""


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def parse_criteria(contest: Contest) -> ContestCriteria:
    """The stored grammar, re-parsed (fail closed on anything unexpected)."""
    return ContestCriteria.model_validate(contest.criteria)


def _definition_values(definition: ContestDefinition) -> dict:
    return {
        "title": definition.title,
        "description": definition.description or None,
        "terms": definition.terms or None,
        "business_line": definition.business_line,
        "audience": definition.audience.value,
        "team_member_role": (
            definition.team_member_role.value if definition.team_member_role else None
        ),
        "metric": definition.metric.value,
        "criteria": definition.criteria.model_dump(mode="json"),
        "criteria_version": definition.criteria.version,
        "win_mode": definition.win_mode.value,
        "top_n": definition.top_n,
        "prize_paise": definition.prize_paise,
        "manager_prize_paise": definition.manager_prize_paise,
        "member_prize_paise": definition.member_prize_paise,
        "member_min_contribution": definition.member_min_contribution,
        "budget_cap_paise": definition.budget_cap_paise,
        "starts_on": definition.starts_on,
        "ends_on": definition.ends_on,
        "start_time": definition.start_time,
        "end_time": definition.end_time,
        "prize_kind": definition.prize_kind.value,
        **{
            field: getattr(definition, field).model_dump() if getattr(definition, field) else None
            for field in _ITEM_PRIZES
        },
    }


def _stored_definition(contest: Contest) -> ContestDefinition:
    return ContestDefinition.model_validate(contest, from_attributes=True)


async def _check_references(db: AsyncSession, criteria: ContestCriteria) -> None:
    """Loan types and banks named in the criteria must exist."""
    if criteria.loans is None:
        return
    if criteria.loans.loan_type_ids:
        found = set(
            await db.scalars(
                select(LoanType.id).where(LoanType.id.in_(criteria.loans.loan_type_ids))
            )
        )
        if found != set(criteria.loans.loan_type_ids):
            raise ContestInvalid("A chosen loan product does not exist.")
    if criteria.loans.bank_ids:
        found = set(await db.scalars(select(Bank.id).where(Bank.id.in_(criteria.loans.bank_ids))))
        if found != set(criteria.loans.bank_ids):
            raise ContestInvalid("A chosen bank does not exist.")


def revalidate(contest: Contest) -> ContestCriteria:
    """Re-check a stored contest before it moves forward."""
    try:
        return _stored_definition(contest).criteria
    except ValueError as exc:
        raise ContestInvalid("The contest rules are no longer valid. Edit and resubmit.") from exc


def _require_future_start(contest: Contest) -> None:
    from app.services.contest_scoring import ContestWindow

    now = datetime.now(UTC)
    window = ContestWindow.of(contest)
    # Older all-day contests historically allowed same-day submission and approval.
    custom_window = contest.start_time != time.min or contest.end_time != time(23, 59)
    if contest.starts_on < today_ist(now):
        raise ContestStateError("The start date has passed. Choose new dates and resubmit.")
    if now >= window.end or (now > window.start and custom_window):
        raise ContestStateError("The start time has passed. Choose a new start and resubmit.")


async def _audit(
    db: AsyncSession,
    contest: Contest,
    action: AuditAction,
    *,
    actor_uuid: uuid.UUID | None,
    actor_role: str | None,
    detail: dict | None = None,
) -> None:
    await record_audit(
        db,
        action=action,
        entity_type="contest",
        entity_uuid=contest.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=contest.business_line,
        detail={"status": contest.status, "audience": contest.audience, **(detail or {})},
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def display_names(user_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """First name and last name of staff actors, read on the bypass session.

    A Sub Admin cannot read another account's row under ``auth_users`` RLS,
    yet the maker and checker names belong on a contest. Only the two name
    columns are selected.
    """
    ids = {value for value in user_ids if value is not None}
    if not ids:
        return {}
    async with db_session.AsyncSessionLocal() as session:
        rows = await session.execute(
            select(User.id, User.first_name, User.last_name).where(User.id.in_(ids))
        )
        return {
            row.id: " ".join(part for part in (row.first_name, row.last_name) if part).strip()
            for row in rows
        }


def to_read(contest: Contest, names: dict[uuid.UUID, str], viewer_uuid: uuid.UUID) -> ContestRead:
    return ContestRead(
        id=contest.id,
        title=contest.title,
        description=contest.description,
        terms=contest.terms,
        business_line=contest.business_line,
        audience=contest.audience,
        team_member_role=contest.team_member_role,
        metric=contest.metric,
        criteria=parse_criteria(contest),
        win_mode=contest.win_mode,
        top_n=contest.top_n,
        prize_paise=contest.prize_paise,
        manager_prize_paise=contest.manager_prize_paise,
        member_prize_paise=contest.member_prize_paise,
        member_min_contribution=contest.member_min_contribution,
        budget_cap_paise=contest.budget_cap_paise,
        starts_on=contest.starts_on,
        ends_on=contest.ends_on,
        **schedule_and_prize(contest),
        status=contest.status,
        created_by_uuid=contest.created_by_uuid,
        created_by_name=names.get(contest.created_by_uuid) or None,
        is_mine=contest.created_by_uuid == viewer_uuid,
        submitted_at=contest.submitted_at,
        checker_name=names.get(contest.checker_uuid) if contest.checker_uuid else None,
        reviewed_at=contest.reviewed_at,
        review_note=contest.review_note,
        live_at=contest.live_at,
        ended_at=contest.ended_at,
        finalized_at=contest.finalized_at,
        cancelled_at=contest.cancelled_at,
        cancel_reason=contest.cancel_reason,
        version=contest.version,
        created_at=contest.created_at,
        updated_at=contest.updated_at,
    )


def schedule_and_prize(contest: Contest) -> dict:
    return {
        "start_time": contest.start_time,
        "end_time": contest.end_time,
        "prize_kind": contest.prize_kind,
        **{field: getattr(contest, field) for field in _ITEM_PRIZES},
    }


async def reads_for(contests: list[Contest], viewer_uuid: uuid.UUID) -> list[ContestRead]:
    names = await display_names(
        {c.created_by_uuid for c in contests} | {c.checker_uuid for c in contests}
    )
    return [to_read(contest, names, viewer_uuid) for contest in contests]


async def list_contests(
    db: AsyncSession,
    *,
    statuses: list[str] | None = None,
    audience: str | None = None,
    business_line: str | None = None,
    search: str | None = None,
    mine_only_for: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Contest], int]:
    """Management list (Sub Admin, platform Admin) on the caller's RLS session."""
    filters = []
    if statuses:
        filters.append(Contest.status.in_(statuses))
    if audience:
        filters.append(Contest.audience == audience)
    if business_line:
        filters.append(Contest.business_line == business_line)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(or_(Contest.title.ilike(pattern), Contest.description.ilike(pattern)))
    if mine_only_for is not None:
        filters.append(Contest.created_by_uuid == mine_only_for)
    total = await db.scalar(select(func.count()).select_from(Contest).where(*filters)) or 0
    rows = await db.scalars(
        select(Contest)
        .where(*filters)
        .order_by(Contest.updated_at.desc(), Contest.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


async def get_contest(db: AsyncSession, contest_id: uuid.UUID) -> Contest:
    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise ContestNotFound("Contest not found.")
    return contest


# ---------------------------------------------------------------------------
# Maker commands (request session, RLS)
# ---------------------------------------------------------------------------


async def create_contest(
    db: AsyncSession,
    definition: ContestDefinition,
    *,
    actor_uuid: uuid.UUID,
    actor_role: str,
) -> Contest:
    await _check_references(db, definition.criteria)
    contest = Contest(
        **_definition_values(definition),
        status=ContestStatus.DRAFT.value,
        created_by_uuid=actor_uuid,
    )
    db.add(contest)
    await db.flush()
    await _audit(
        db, contest, AuditAction.CONTEST_CREATED, actor_uuid=actor_uuid, actor_role=actor_role
    )
    await db.commit()
    await db.refresh(contest)
    return contest


async def _owned_for_update(
    db: AsyncSession, contest_id: uuid.UUID, actor_uuid: uuid.UUID, allowed: tuple[str, ...]
) -> Contest:
    """Read, check ownership and status, then lock and re-check.

    The UPDATE policy also applies to SELECT ... FOR UPDATE, so the first
    read (plain SELECT policy) lets a non-owner or a wrong status get a 403 or
    409 rather than a misleading 404.
    """
    contest = await db.get(Contest, contest_id)
    if contest is None:
        raise ContestNotFound("Contest not found.")
    if contest.created_by_uuid != actor_uuid:
        raise ContestNotOwned("Only the Sub Admin who created this contest can change it.")
    if contest.status not in allowed:
        raise ContestStateError("This contest cannot be changed in its current status.")
    locked = await db.scalar(
        select(Contest)
        .where(Contest.id == contest_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.status not in allowed:
        raise ContestStateError("This contest cannot be changed in its current status.")
    return locked


async def update_contest(
    db: AsyncSession,
    contest_id: uuid.UUID,
    definition: ContestDefinition,
    *,
    actor_uuid: uuid.UUID,
    actor_role: str,
) -> Contest:
    """Replace a draft's or a rejected contest's definition; a rejected
    contest returns to draft (its review note stays until resubmission)."""
    contest = await _owned_for_update(db, contest_id, actor_uuid, _EDITABLE)
    await _check_references(db, definition.criteria)
    for field, value in _definition_values(definition).items():
        setattr(contest, field, value)
    contest.status = ContestStatus.DRAFT.value
    contest.checker_uuid = None
    contest.reviewed_at = None
    contest.version += 1
    await db.flush()
    await _audit(
        db, contest, AuditAction.CONTEST_UPDATED, actor_uuid=actor_uuid, actor_role=actor_role
    )
    await db.commit()
    await db.refresh(contest)
    return contest


async def submit_contest(
    db: AsyncSession, contest_id: uuid.UUID, *, actor_uuid: uuid.UUID, actor_role: str
) -> Contest:
    contest = await _owned_for_update(db, contest_id, actor_uuid, _EDITABLE)
    criteria = revalidate(contest)
    await _check_references(db, criteria)
    _require_future_start(contest)
    contest.status = ContestStatus.PENDING_APPROVAL.value
    contest.submitted_at = datetime.now(UTC)
    contest.checker_uuid = None
    contest.reviewed_at = None
    contest.review_note = None
    contest.version += 1
    await db.flush()
    await _audit(
        db, contest, AuditAction.CONTEST_SUBMITTED, actor_uuid=actor_uuid, actor_role=actor_role
    )
    await db.commit()
    await db.refresh(contest)
    await notify_admins(
        notification_type=NotificationType.CONTEST_SUBMITTED,
        title="Contest awaiting approval",
        body=f"“{contest.title}” was submitted for approval.",
        href="/dashboard/contest-approvals",
        exclude_user_uuid=actor_uuid,
    )
    return contest


async def withdraw_contest(
    db: AsyncSession, contest_id: uuid.UUID, *, actor_uuid: uuid.UUID, actor_role: str
) -> Contest:
    """The maker takes a contest back from review to edit it."""
    contest = await _owned_for_update(
        db, contest_id, actor_uuid, (ContestStatus.PENDING_APPROVAL.value,)
    )
    contest.status = ContestStatus.DRAFT.value
    contest.submitted_at = None
    contest.version += 1
    await db.flush()
    await _audit(
        db,
        contest,
        AuditAction.CONTEST_UPDATED,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        detail={"withdrawn": True},
    )
    await db.commit()
    await db.refresh(contest)
    return contest


async def cancel_by_maker(
    db: AsyncSession,
    contest_id: uuid.UUID,
    *,
    reason: str,
    actor_uuid: uuid.UUID,
    actor_role: str,
) -> Contest:
    contest = await _owned_for_update(db, contest_id, actor_uuid, _MAKER_CANCELLABLE)
    contest.status = ContestStatus.CANCELLED.value
    contest.checker_uuid = None
    contest.cancelled_by_uuid = actor_uuid
    contest.cancelled_at = datetime.now(UTC)
    contest.cancel_reason = reason
    contest.version += 1
    await db.flush()
    await _audit(
        db, contest, AuditAction.CONTEST_CANCELLED, actor_uuid=actor_uuid, actor_role=actor_role
    )
    await db.commit()
    await db.refresh(contest)
    return contest


async def delete_contest(
    db: AsyncSession, contest_id: uuid.UUID, *, actor_uuid: uuid.UUID, actor_role: str
) -> None:
    contest = await _owned_for_update(db, contest_id, actor_uuid, (ContestStatus.DRAFT.value,))
    await _audit(
        db, contest, AuditAction.CONTEST_DELETED, actor_uuid=actor_uuid, actor_role=actor_role
    )
    await db.delete(contest)
    await db.commit()


# ---------------------------------------------------------------------------
# Checker commands (bypass session, row lock)
# ---------------------------------------------------------------------------


async def _locked(session: AsyncSession, contest_id: uuid.UUID) -> Contest:
    contest = await session.scalar(
        select(Contest).where(Contest.id == contest_id).with_for_update()
    )
    if contest is None:
        raise ContestNotFound("Contest not found.")
    return contest


async def admin_update_contest(
    contest_id: uuid.UUID, definition: ContestAdminUpdate, *, actor_uuid: uuid.UUID, actor_role: str
) -> Contest:
    from app.services.contest_lifecycle import contest_recipients
    from app.services.contest_scoring import ContestWindow

    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id)
        if contest.status not in _ADMIN_EDITABLE:
            raise ContestStateError("This contest cannot be edited in its current status.")
        if contest.created_by_uuid == actor_uuid:
            raise ContestMakerChecker("You cannot use Admin editing on a contest you created.")
        if contest.version != definition.expected_version:
            raise ContestStateError("The contest changed. Reload it before editing again.")
        now = datetime.now(UTC)
        window = ContestWindow.of(contest)
        proposed = ContestWindow(
            definition.starts_on, definition.ends_on, definition.start_time, definition.end_time
        )
        if now >= window.end:
            raise ContestStateError("The contest has ended.")
        previous = _stored_definition(contest)
        before = _definition_values(previous)
        after = _definition_values(definition)
        changed = {key for key in after if before[key] != after[key]}
        has_started = contest.status == ContestStatus.LIVE.value or now >= window.start
        if has_started:
            for field in changed.intersection(_ITEM_PRIZES):
                old, new = before[field], after[field]
                if (
                    not old
                    or not new
                    or old["estimated_value_paise"] != new["estimated_value_paise"]
                ):
                    raise ContestStateError("Only item prize text can change after the start.")
            if changed.difference(_LIVE_TEXT, _ITEM_PRIZES) or proposed.end < window.end:
                raise ContestStateError("After the start, edit only text or extend the end.")
        else:
            if proposed.start < now:
                raise ContestStateError("Choose a start time that has not passed.")
            await _check_references(session, definition.criteria)
            if datetime.now(UTC) >= min(window.start, proposed.start):
                raise ContestStateError("A start time has arrived. Reload before editing again.")
        if not changed:
            return contest

        for field in changed:
            setattr(contest, field, after[field])
        contest.version += 1
        await session.flush()
        recipients = (
            await contest_recipients(session, contest, now)
            if has_started and contest.status != ContestStatus.PENDING_APPROVAL.value
            else set()
        )
        session.add_all(
            Notification(
                user_uuid=user_uuid,
                type=NotificationType.CONTEST_UPDATED,
                title="Contest updated",
                body=f"“{contest.title}” has updated details. Open the contest to review them.",
                href=f"/dashboard/contests?contest={contest.id}",
            )
            for user_uuid in recipients
        )
        audit_before = previous.model_dump(mode="json")
        audit_after = definition.model_dump(mode="json", exclude={"expected_version"})
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_UPDATED,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            detail={"before": audit_before, "after": audit_after, "notified": len(recipients)},
        )
        await session.commit()
        await session.refresh(contest)
        return contest


async def approve_contest(
    contest_id: uuid.UUID, *, reviewer_uuid: uuid.UUID, reviewer_role: str
) -> Contest:
    """pending_approval -> approved by a platform Admin who is not the maker,
    and live at once when the start date is today."""
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id)
        if contest.status != ContestStatus.PENDING_APPROVAL.value:
            raise ContestStateError("This contest is not awaiting approval.")
        if contest.created_by_uuid == reviewer_uuid:
            raise ContestMakerChecker("You cannot approve a contest you created.")
        revalidate(contest)
        _require_future_start(contest)
        now = datetime.now(UTC)
        contest.status = ContestStatus.APPROVED.value
        contest.checker_uuid = reviewer_uuid
        contest.reviewed_at = now
        contest.review_note = None
        contest.version += 1
        await session.flush()
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_APPROVED,
            actor_uuid=reviewer_uuid,
            actor_role=reviewer_role,
        )
        # A contest approved on its start date goes live now (same rules and
        # transaction as the lifecycle job); a later start waits for the job.
        from app.services.contest_lifecycle import activate_if_due

        await activate_if_due(session, contest, now)
        await session.commit()
        await session.refresh(contest)
    await emit_notification(
        user_uuid=contest.created_by_uuid,
        notification_type=NotificationType.CONTEST_REVIEWED,
        title="Contest approved",
        body=f"“{contest.title}” was approved.",
        href=f"/dashboard/contests?contest={contest.id}",
    )
    return contest


async def reject_contest(
    contest_id: uuid.UUID, *, reviewer_uuid: uuid.UUID, reviewer_role: str, note: str
) -> Contest:
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id)
        if contest.status != ContestStatus.PENDING_APPROVAL.value:
            raise ContestStateError("This contest is not awaiting approval.")
        if contest.created_by_uuid == reviewer_uuid:
            raise ContestMakerChecker("You cannot review a contest you created.")
        contest.status = ContestStatus.REJECTED.value
        contest.checker_uuid = reviewer_uuid
        contest.reviewed_at = datetime.now(UTC)
        contest.review_note = note
        contest.version += 1
        await session.flush()
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_REJECTED,
            actor_uuid=reviewer_uuid,
            actor_role=reviewer_role,
        )
        await session.commit()
        await session.refresh(contest)
    await emit_notification(
        user_uuid=contest.created_by_uuid,
        notification_type=NotificationType.CONTEST_REVIEWED,
        title="Changes requested for contest",
        body=f"Admin left feedback on “{contest.title}”.",
        href=f"/dashboard/contests?contest={contest.id}",
    )
    return contest
