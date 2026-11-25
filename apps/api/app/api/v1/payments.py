"""Payout administration — delegated requests and Admin disbursement actions.

Create/list/recipient search admit a platform Admin or an explicitly granted
Sub Admin. Approval, rejection, reconciliation, and manual-cheque actions remain
Admin-only. These gates are enforced in the app layer and by payout RLS. The webhook
receiver is UNAUTHENTICATED but signature-gated (HMAC-SHA256, fail-closed) — it
carries no JWT/RLS context because settle writes run on the bypass session.

Every write goes through services.payments on the app-superuser bypass session;
this router authenticates, validates the actor, and shapes the masked response.
RazorpayX's webhook remains provider-specific and fail-closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import (
    CurrentUser,
    check_assignment_line,
    get_active_user,
    is_platform_admin,
    require_assignment,
)
from app.db.session import get_db
from app.models.payout import Payout, PayoutProvider, PayoutStatus, PayoutType
from app.schemas.agent_payout_details import CancelledChequeRead, SavedPayoutDestinationRead
from app.schemas.payments import (
    ManualChequeIssue,
    PayoutCreate,
    PayoutGatewaySimulation,
    PayoutLinkDivergenceRead,
    PayoutLinkDivergencesRead,
    PayoutListResponse,
    PayoutRead,
    PayoutRecipientListResponse,
    PayoutRecipientRead,
    PayoutReject,
    WebhookAck,
)
from app.services import agent_payout_cheque, agent_payout_details, storage
from app.services import payments as payments_service
from app.services.payout_leads import payout_lead_refs
from app.services.payout_links import list_link_divergences
from app.services.payout_recipients import resolve_payout_identities, search_payout_recipients

logger = logging.getLogger(__name__)

finance_view = require_assignment("account_manager", "view", include_admin=True)
finance_prepare = require_assignment("account_manager", "prepare", include_admin=True)


router = APIRouter()

# Typed domain error → HTTP status.
_ERROR_STATUS = {
    payments_service.RecipientNotFound: status.HTTP_404_NOT_FOUND,
    payments_service.PayoutNotFound: status.HTTP_404_NOT_FOUND,
    payments_service.RecipientInactive: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.RecipientLineMismatch: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutAmountExceeded: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutDailyCapExceeded: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutCapNotConfigured: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.DuplicatePayout: status.HTTP_409_CONFLICT,
    payments_service.DuplicateManualReference: status.HTTP_409_CONFLICT,
    payments_service.PayoutStateError: status.HTTP_409_CONFLICT,
    payments_service.MakerCheckerViolation: status.HTTP_403_FORBIDDEN,
    payments_service.SelfPayoutForbidden: status.HTTP_403_FORBIDDEN,
    payments_service.GatewayError: status.HTTP_502_BAD_GATEWAY,
}


def _map_error(exc: payments_service.PayoutError) -> HTTPException:
    code = _ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code=code, detail=str(exc))


def _require_payout_requester(current_user: CurrentUser) -> None:
    """Admin, or a platform Sub Admin with the explicit request grant."""
    is_admin = is_platform_admin(current_user)
    is_granted_sub_admin = (
        current_user.role == "sub_admin"
        and current_user.platform_scope == "true"
        and "payout_requests" in current_user.staff_features
    )
    if not (is_admin or is_granted_sub_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payout requests require an Admin grant.",
        )


def _require_admin(current_user: CurrentUser, action: str = "Approving a payout") -> None:
    """Full-Admin-only actions (checker approve, recipient lookup). Thin
    wrapper around deps.is_platform_admin (feature-status.md §2-20) — kept
    local only for this per-call custom error message; the condition itself
    is no longer duplicated."""
    if not is_platform_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action} is restricted to platform admins.",
        )


async def _get_payout_or_404(db: AsyncSession, payout_id: UUID) -> Payout:
    payout = await db.scalar(select(Payout).where(Payout.id == payout_id))
    if payout is None:
        # RLS already scopes to platform admins; a miss reads as "not found".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found.")
    return payout


async def _to_read(
    payouts: Sequence[Payout],
    current_user: CurrentUser,
    db: AsyncSession,
) -> list[PayoutRead]:
    """Enrich payout rows with display identity in a small, bounded batch.

    Resolves identities once per distinct business_line present in the batch
    (at most 3: None/loans/real_estate), never once per row. A single shared
    uuid->identity map would let the same recipient's displayed code leak
    across two payouts on different lines within one page, since
    resolve_identities picks exactly one code per uuid; grouping by line keeps
    each payout's own business_line driving its own code choice.
    """
    uuids: set[UUID] = set()
    for p in payouts:
        for uid in (
            p.recipient_user_uuid,
            p.maker_user_uuid,
            p.checker_user_uuid,
            p.rejected_by_user_uuid,
        ):
            if uid is not None:
                uuids.add(uid)

    lines_present: set[str | None] = {p.business_line for p in payouts}
    identities_by_line: dict[str | None, dict[UUID, object]] = {}
    for line in lines_present:
        prefer_line = {p.recipient_user_uuid: line for p in payouts if p.business_line == line}
        identities_by_line[line] = await resolve_payout_identities(
            uuids,
            prefer_line=prefer_line,
            profile_line=line if current_user.sub_admin_access is not None else None,
        )

    # On the caller's RLS session: only leads the caller can already read.
    lead_refs = await payout_lead_refs(db, [p.id for p in payouts])
    reads: list[PayoutRead] = []
    for p in payouts:
        identities = identities_by_line[p.business_line]
        recipient = identities.get(p.recipient_user_uuid)
        maker = identities.get(p.maker_user_uuid)
        checker = identities.get(p.checker_user_uuid) if p.checker_user_uuid else None
        rejected_by = identities.get(p.rejected_by_user_uuid) if p.rejected_by_user_uuid else None
        read = PayoutRead.model_validate(p, from_attributes=True)
        read.recipient_name = recipient.name if recipient else None
        read.recipient_code = recipient.code if recipient else None
        read.maker_name = maker.name if maker else None
        read.checker_name = checker.name if checker else None
        read.rejected_by_name = rejected_by.name if rejected_by else None
        read.lead_refs = lead_refs.get(p.id, [])
        read.viewer_is_maker = p.maker_user_uuid == current_user.id
        read.viewer_can_approve = (
            p.status == PayoutStatus.PENDING_APPROVAL
            and is_platform_admin(current_user)
            and p.maker_user_uuid != current_user.id
            and p.recipient_user_uuid != current_user.id
        )
        if is_platform_admin(current_user) and p.recipient_user_uuid != current_user.id:
            read.simulate_events = payments_service.simulator_events_for(p)
        reads.append(read)
    return reads


@router.post("", response_model=PayoutRead, status_code=status.HTTP_201_CREATED)
async def create_payout(
    req: PayoutCreate,
    current_user: CurrentUser = Depends(finance_prepare),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    if current_user.sub_admin_access is None:
        _require_payout_requester(current_user)
    else:
        check_assignment_line(current_user, "account_manager", "prepare", req.business_line)
    try:
        payout_id = await payments_service.create_payout(
            recipient_user_uuid=req.recipient_user_uuid,
            payout_type=req.type,
            business_line=req.business_line,
            amount_paise=req.amount_paise,
            destination_type=req.destination_type,
            destination=req.destination.model_dump(),
            idempotency_key=req.idempotency_key,
            maker_user_uuid=current_user.id,
            actor_role=current_user.role,
            scoped_staff_id=(
                current_user.staff_profile_uuid
                if current_user.sub_admin_access is not None
                else None
            ),
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None

    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/approve", response_model=PayoutRead)
async def approve_payout(
    payout_id: UUID,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user)
    try:
        await payments_service.approve_payout(
            payout_id=payout_id,
            checker_user_uuid=current_user.id,
            checker_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None

    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/simulate-gateway", response_model=PayoutRead)
async def simulate_gateway(
    payout_id: UUID,
    body: PayoutGatewaySimulation,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    """Development-only RazorpayX test mode: an Admin picks the gateway outcome.

    404 unless PAYOUT_GATEWAY_SIMULATOR is on, ENV is development and no live
    Razorpay credentials exist; the outcome then runs through settle_from_webhook.
    """
    _require_admin(current_user, "Simulating a gateway outcome")
    try:
        await payments_service.simulate_gateway_event(
            payout_id=payout_id,
            event=body.event,
            actor_user_uuid=current_user.id,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None

    payout = await _get_payout_or_404(db, payout_id)
    # The settle ran on another session; read the committed state, not a cached row.
    await db.refresh(payout)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/reject", response_model=PayoutRead)
async def reject_payout(
    payout_id: UUID,
    req: PayoutReject,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user, action="Rejecting a payout")
    payout = await _get_payout_or_404(db, payout_id)
    if payout.type == PayoutType.REFERRAL_BONUS:
        # FR-9.5 (referrals.py's module docstring): Sub Admin manages
        # referral bonus RULES only, never referral activity — referrals_rls
        # has no sub_admin branch. Rejecting a referral_bonus payout runs
        # services.referrals.release_payout_link on the bypass session,
        # which writes to that table; the looser _require_platform_admin
        # check above would otherwise be a side door around that boundary
        # for this one payout type.
        _require_admin(current_user, action="Rejecting a referral bonus payout")
    elif payout.type == PayoutType.COMMISSION:
        # Same side-door shape as REFERRAL_BONUS above: commissions_update
        # RLS is full-Admin only (IDR §5.5, no Sub Admin reading/writing
        # counterpart), but rejecting a commission payout runs
        # services.commissions.release_payout_link on the bypass session —
        # the looser _require_platform_admin check would let a Sub Admin
        # indirectly write to a table they have no direct RLS access to.
        _require_admin(current_user, action="Rejecting a commission payout")
    elif payout.type == PayoutType.CONTEST_REWARD:
        # CS-027: same shape; the release hook writes contest_results on the
        # bypass session, which api_user cannot write at all.
        _require_admin(current_user, action="Rejecting a contest prize payout")
    try:
        await payments_service.reject_payout(
            payout_id=payout_id,
            rejector_user_uuid=current_user.id,
            reason=req.reason,
            rejector_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None

    # reject_payout mutates through a DIFFERENT session (the bypass
    # AsyncSessionLocal) than this request's `db`. Without expiring first,
    # `db`'s identity map still holds the `payout` object loaded by the
    # pre-check above and a re-SELECT on the same primary key returns that
    # same stale in-memory object rather than re-reading the row (the same
    # class of gotcha as the post-commit re-query note in
    # services/payments.py's own module — here it bites the request session
    # instead of the ORM-vs-Core split there).
    db.expire(payout)
    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/manual/issue", response_model=PayoutRead)
async def issue_manual_cheque(
    payout_id: UUID,
    req: ManualChequeIssue,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user, action="Issuing a cheque payout")
    try:
        await payments_service.issue_manual_cheque(
            payout_id=payout_id,
            reference=req.reference,
            actor_user_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None
    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/manual/clear", response_model=PayoutRead)
async def clear_manual_cheque(
    payout_id: UUID,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user, action="Clearing a cheque payout")
    try:
        await payments_service.clear_manual_cheque(
            payout_id=payout_id,
            actor_user_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None
    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/manual/fail", response_model=PayoutRead)
async def fail_manual_cheque(
    payout_id: UUID,
    req: PayoutReject,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user, action="Failing a cheque payout")
    try:
        await payments_service.fail_manual_cheque(
            payout_id=payout_id,
            reason=req.reason,
            actor_user_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None
    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.post("/{payout_id}/manual/reverse", response_model=PayoutRead)
async def reverse_manual_cheque(
    payout_id: UUID,
    req: PayoutReject,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> PayoutRead:
    _require_admin(current_user, action="Reversing a cheque payout")
    try:
        await payments_service.reverse_manual_cheque(
            payout_id=payout_id,
            reason=req.reason,
            actor_user_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except payments_service.PayoutError as exc:
        raise _map_error(exc) from None
    payout = await _get_payout_or_404(db, payout_id)
    return (await _to_read([payout], current_user, db))[0]


@router.get("/recipients", response_model=PayoutRecipientListResponse)
async def list_payout_recipients(
    q: str = Query(min_length=2, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    business_line: Literal["loans", "real_estate"] | None = None,
    current_user: CurrentUser = Depends(finance_prepare),
) -> PayoutRecipientListResponse:
    """Minimal recipient picker for an authorized payout requester."""
    line = None
    if current_user.sub_admin_access is None:
        _require_payout_requester(current_user)
    else:
        if business_line is None:
            raise HTTPException(
                422, detail="Choose a business line before searching for a recipient."
            )
        check_assignment_line(current_user, "account_manager", "prepare", business_line)
        line = business_line
    hits = await search_payout_recipients(
        q=q, limit=limit, exclude_user_uuid=current_user.id, line=line
    )
    return PayoutRecipientListResponse(
        recipients=[
            PayoutRecipientRead(
                auth_user_uuid=h.auth_user_uuid,
                name=h.name,
                codes=h.codes,
                kind=h.kind,
                mobile_last4=h.mobile_last4,
            )
            for h in hits
        ]
    )


async def _reveal_saved_destination(
    current_user: CurrentUser,
    *,
    recipient_auth_user_uuid: UUID | None = None,
    agent_profile_uuid: UUID | None = None,
) -> SavedPayoutDestinationRead:
    _require_payout_requester(current_user)
    if recipient_auth_user_uuid == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot create a payout to yourself.",
        )
    try:
        saved = await agent_payout_details.reveal_for_payout(
            actor_auth_user_uuid=current_user.id,
            actor_role=current_user.role,
            recipient_auth_user_uuid=recipient_auth_user_uuid,
            agent_profile_uuid=agent_profile_uuid,
        )
    except agent_payout_details.SelfPayoutDetailsForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot create a payout to yourself.",
        ) from exc
    except agent_payout_details.PayoutDetailsUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Saved payout details are not available right now.",
        ) from exc
    except agent_payout_details.PayoutDetailsUnreadable as exc:
        logger.error("payout.saved_destination_unreadable")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The saved payout details could not be read. Ask the Agent to save them again.",
        ) from exc
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This recipient has not saved payout details.",
        )
    return SavedPayoutDestinationRead(
        upi_id=saved.upi_id,
        bank=saved.bank,
        updated_at=saved.updated_at,
        cheque_uploaded_at=saved.cheque_uploaded_at,
    )


async def _view_cancelled_cheque(
    current_user: CurrentUser,
    *,
    recipient_auth_user_uuid: UUID | None = None,
    agent_profile_uuid: UUID | None = None,
) -> CancelledChequeRead:
    _require_payout_requester(current_user)
    if recipient_auth_user_uuid == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot create a payout to yourself.",
        )
    try:
        view = await agent_payout_cheque.view_for_payout(
            actor_auth_user_uuid=current_user.id,
            actor_role=current_user.role,
            recipient_auth_user_uuid=recipient_auth_user_uuid,
            agent_profile_uuid=agent_profile_uuid,
        )
    except agent_payout_cheque.SelfChequeViewForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot create a payout to yourself.",
        ) from exc
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This recipient has not uploaded a cancelled cheque.",
        )
    # A sanitized image may open inline; a PDF always downloads (it can carry
    # active content), the same split as loan-document previews.
    url = (
        storage.presign_preview(view.object_key)
        if view.content_type.startswith("image/")
        else storage.presign_download(view.object_key)
    )
    return CancelledChequeRead(
        url=url,
        content_type=view.content_type,
        uploaded_at=view.uploaded_at,
        expires_in_seconds=storage.PRESIGN_EXPIRE_SECONDS,
    )


@router.get(
    "/recipients/{user_uuid}/cancelled-cheque",
    response_model=CancelledChequeRead,
)
async def get_recipient_cancelled_cheque(
    user_uuid: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
) -> CancelledChequeRead:
    """Open the cancelled cheque an Agent attached to their payout details.

    Same access as the saved-destination prefill; every successful view is
    audited (agent_payout_details_viewed, purpose cheque_view).
    """
    response.headers["Cache-Control"] = "private, no-store"
    return await _view_cancelled_cheque(current_user, recipient_auth_user_uuid=user_uuid)


@router.get(
    "/agents/{agent_profile_uuid}/cancelled-cheque",
    response_model=CancelledChequeRead,
)
async def get_agent_cancelled_cheque(
    agent_profile_uuid: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
) -> CancelledChequeRead:
    """Same as the recipient cheque view, keyed by Agent profile (commission payouts)."""
    response.headers["Cache-Control"] = "private, no-store"
    return await _view_cancelled_cheque(current_user, agent_profile_uuid=agent_profile_uuid)


@router.get(
    "/recipients/{user_uuid}/saved-destination",
    response_model=SavedPayoutDestinationRead,
)
async def get_recipient_saved_destination(
    user_uuid: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
) -> SavedPayoutDestinationRead:
    """Prefill a payout from the bank account / UPI ID an Agent saved.

    Same access as the recipient picker. Every successful read is audited
    (agent_payout_details_viewed); a maker's own details are refused.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return await _reveal_saved_destination(current_user, recipient_auth_user_uuid=user_uuid)


@router.get(
    "/agents/{agent_profile_uuid}/saved-destination",
    response_model=SavedPayoutDestinationRead,
)
async def get_agent_saved_destination(
    agent_profile_uuid: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
) -> SavedPayoutDestinationRead:
    """Same as the recipient prefill, keyed by Agent profile (commission payouts)."""
    response.headers["Cache-Control"] = "private, no-store"
    return await _reveal_saved_destination(current_user, agent_profile_uuid=agent_profile_uuid)


@router.get("/link-divergences", response_model=PayoutLinkDivergencesRead)
async def get_payout_link_divergences(
    current_user: CurrentUser = Depends(finance_view),
    db: AsyncSession = Depends(get_db),
) -> PayoutLinkDivergencesRead:
    """Read-only: payouts whose linked referral/commission/fee_cashback row
    hasn't caught up yet (services/payout_links.py's scheduled sweep repairs
    these automatically — this is visibility, not a manual trigger). No
    mutating counterpart exists on purpose: see payout_links.py's docstring
    for why a force-unlink endpoint would convert a display bug into a money
    bug."""
    if current_user.sub_admin_access is None:
        _require_admin(current_user, action="Viewing payout reconciliation")
    result = await list_link_divergences(db)
    return PayoutLinkDivergencesRead(
        paid_direction=[PayoutLinkDivergenceRead(**row) for row in result["paid_direction"]],
        release_direction=[PayoutLinkDivergenceRead(**row) for row in result["release_direction"]],
    )


@router.get("", response_model=PayoutListResponse)
async def list_payouts(
    status_filter: PayoutStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(finance_view),
    db: AsyncSession = Depends(get_db),
) -> PayoutListResponse:
    if current_user.sub_admin_access is None:
        _require_payout_requester(current_user)
    stmt = select(Payout).order_by(Payout.created_at.desc()).limit(limit).offset(offset)
    if current_user.role == "sub_admin" and current_user.sub_admin_access is None:
        # Defence in depth over payouts_rls: delegated Sub Admins are makers and
        # may only see the requests they raised, never another maker's queue.
        stmt = stmt.where(Payout.maker_user_uuid == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(Payout.status == status_filter)
    result = await db.execute(stmt)
    payouts = result.scalars().all()
    return PayoutListResponse(payouts=await _to_read(payouts, current_user, db))


@router.post("/webhook/razorpay", response_model=WebhookAck)
async def razorpay_webhook(request: Request) -> WebhookAck:
    """RazorpayX payout webhook — fail-closed HMAC-SHA256 verification.

    No auth dependency: authenticity comes from the signature, not a JWT. A
    missing secret or a bad signature is rejected with 400 and NO state change.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    # Fail closed: without a configured secret we cannot trust any payload.
    if not secret or not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unverified webhook.")

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad signature.")

    try:
        payload = json.loads(raw_body)
        event = payload["event"]
        entity = payload["payload"]["payout"]["entity"]
        gateway_payout_id = entity["id"]
    except (ValueError, KeyError, TypeError):
        # Signature was valid but the shape is unexpected — ack so RazorpayX stops
        # retrying, but change nothing.
        logger.warning("payout.webhook_malformed")
        return WebhookAck()

    await payments_service.settle_from_webhook(
        event=event,
        gateway_payout_id=gateway_payout_id,
        provider=PayoutProvider.RAZORPAYX,
    )
    return WebhookAck()
