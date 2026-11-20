"""Agent router — home summary, lead introduction/tracking (Agent Dashboard slice 1).

Every route depends on require_agent (app-layer gate) on top of the leads_rls
own-origin RLS predicate (defense in depth, same posture as every other
role-gated router in this codebase).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import TTL_AGENT_LEAD_BULK_RATE, RedisCache, agent_lead_bulk_rate_key
from app.core import field_crypto
from app.core.config import settings
from app.core.deps import CurrentUser, get_cache, require_agent
from app.db.session import get_db
from app.models.agent_payout_details import AgentPayoutDetails
from app.models.audit_log import AuditAction
from app.models.field_visibility import FieldTargetRole, FieldVisibilityMode
from app.models.lead import Lead
from app.models.lead_intake_attempt import IntakeActorType
from app.schemas.agent import (
    AgentHomeResponse,
    AgentLeadBulkRequest,
    AgentLeadBulkResponse,
    AgentLeadCreate,
    AgentLeadHistoryRead,
    AgentLeadRead,
    AgentLeadUpdate,
    AgentProfileStatusRead,
)
from app.schemas.agent_payout_details import (
    AgentChequeConfirm,
    AgentChequePresignRequest,
    AgentChequePresignResponse,
    AgentPayoutDetailsRead,
    AgentPayoutDetailsUpdate,
)
from app.schemas.commission_rates import AgentCommissionRatesResponse
from app.schemas.commissions import (
    AgentEarningsResponse,
    AgentTransactionDetail,
    CommissionStatusLiteral,
    DealType,
)
from app.schemas.eligibility import EligibilitySummary, IntakeAttemptListResponse
from app.services import agent_dashboard, agent_lead_bulk, lead_intake_attempts
from app.services import agent_payout_cheque as payout_cheque
from app.services import agent_payout_details as payout_details
from app.services import commission_rates as commission_rate_service
from app.services.agent import (
    AgentProfileNotFound,
    InvalidLeadInterest,
    InvalidStatusFilter,
    LeadCaptureFailed,
    LeadCaptureUnavailable,
    LeadLocked,
    LeadNotResubmittable,
    get_home_summary,
    get_lead_for_agent,
    introduce_lead,
    lead_eligibility_summary,
    list_my_leads,
    resubmit_lead_for_agent,
    update_lead_for_agent,
)
from app.services.audit_log import record as record_audit
from app.services.eligibility import agent_lead_eligibility, reason_label
from app.services.field_visibility import effective_modes, project_values
from app.services.lead_details import visible_requirement
from app.services.lead_signals import EMPTY_SIGNALS, LeadSignals, facets, lead_signals
from app.services.leads import is_agent_lead_resubmittable

logger = logging.getLogger(__name__)

router = APIRouter()


def _agent_profile_uuid(current_user: CurrentUser) -> UUID:
    if current_user.agent_profile_uuid is None:
        # pragma: no cover — every agent JWT carries one
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No agent profile on this account.")
    return current_user.agent_profile_uuid


def _to_agent_lead_read(
    lead: Lead,
    modes: dict[tuple[str, str], FieldVisibilityMode],
    signals: LeadSignals | None = None,
    *,
    agent_profile_uuid: UUID,
) -> AgentLeadRead:
    within_window = lead.expires_at is None or lead.expires_at > datetime.now(UTC)
    eligibility, reason = agent_lead_eligibility(lead.agent_expired_at)
    extra = {"facets": facets(signals)} if signals is not None else {}
    return AgentLeadRead(
        eligibility=eligibility,
        eligibility_reason=reason,
        eligibility_reason_label=reason_label(reason),
        **extra,
        id=lead.id,
        mobile=lead.mobile,
        business_line=lead.business_line,
        status="expired" if lead.agent_expired_at is not None else lead.status,
        registered=lead.client_profile_uuid is not None,
        editable=(
            lead.status in {"new", "assigned"} and lead.agent_expired_at is None and within_window
        ),
        resubmittable=is_agent_lead_resubmittable(lead),
        resubmit_count=lead.resubmit_count,
        last_resubmitted_at=lead.last_resubmitted_at,
        expires_at=lead.expires_at,
        expired_at=lead.agent_expired_at,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        **project_values(
            modes,
            "lead",
            {
                "name": lead.name,
                # Only the requirement keys this Agent owns (CS-028).
                "requirement": visible_requirement(
                    lead, "agent", agent_profile_uuid=agent_profile_uuid
                ),
            },
        ),
    )


@router.get("/home", response_model=AgentHomeResponse)
async def home(
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentHomeResponse:
    agent_profile_uuid = _agent_profile_uuid(current_user)
    try:
        profile, counts = await get_home_summary(db, agent_profile_uuid)
    except AgentProfileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent profile not found.") from exc
    return AgentHomeResponse(
        profile=AgentProfileStatusRead(
            agent_code=profile.agent_code,
            business_line=profile.business_line,
            kyc_status=profile.kyc_status,
            status=profile.status,
            rera_code=profile.rera_code,
            approved_at=profile.approved_at,
        ),
        counts_by_status=counts,
    )


@router.post(
    "/leads",
    response_model=AgentLeadRead,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_lead(
    payload: AgentLeadCreate,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadRead:
    agent_profile_uuid = _agent_profile_uuid(current_user)
    business_line = current_user.business_line
    if business_line not in ("loans", "real_estate"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your agent profile has no business line set."
        )
    try:
        lead = await introduce_lead(
            db,
            agent_profile_uuid=agent_profile_uuid,
            business_line=business_line,
            payload=payload,
        )
    except LeadCaptureUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Lead capture is temporarily unavailable. Please try again.",
        ) from exc
    except LeadCaptureFailed as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This mobile number is already linked to an existing enquiry.",
        ) from exc
    except InvalidLeadInterest as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a published property or product from your business line.",
        ) from exc
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    return _to_agent_lead_read(lead, modes, agent_profile_uuid=agent_profile_uuid)


@router.post("/leads/bulk", response_model=AgentLeadBulkResponse)
async def bulk_create_leads(
    payload: AgentLeadBulkRequest,
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
) -> AgentLeadBulkResponse:
    """Validate (``dry_run``) or submit up to 200 parsed spreadsheet rows.

    Each submitted row goes through the single-introduction path in its own
    transaction; the response reports every row's outcome. A dry run checks
    the rows only (format, repeated numbers, product / property type) and
    never looks up, creates or records anything about a number.
    """
    response.headers["Cache-Control"] = "private, no-store"
    agent_profile_uuid = _agent_profile_uuid(current_user)
    business_line = current_user.business_line
    if business_line not in ("loans", "real_estate"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your agent profile has no business line set."
        )
    mode = "dry_run" if payload.dry_run else "submit"
    limit = (
        settings.AGENT_LEAD_BULK_DRY_RUNS_PER_HOUR
        if payload.dry_run
        else settings.AGENT_LEAD_BULK_SUBMITS_PER_HOUR
    )
    count = await cache.incr_with_expire(
        agent_lead_bulk_rate_key(mode, str(agent_profile_uuid)), TTL_AGENT_LEAD_BULK_RATE
    )
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many bulk uploads. Please try again later.",
        )

    results = await agent_lead_bulk.run_bulk(
        db,
        payload.rows,
        dry_run=payload.dry_run,
        agent_profile_uuid=agent_profile_uuid,
        business_line=business_line,
    )
    totals = agent_lead_bulk.totals(results)
    if not payload.dry_run:
        # One audit entry per real upload, counts only (no mobile, name or
        # email). The leads are already committed row by row, so a failure
        # here is logged rather than turned into an error the Agent would
        # answer by uploading again.
        try:
            await record_audit(
                db,
                action=AuditAction.AGENT_LEADS_BULK_SUBMITTED,
                entity_type="agent_profile",
                entity_uuid=agent_profile_uuid,
                actor_uuid=current_user.id,
                actor_role="agent",
                business_line=business_line,
                detail=totals.model_dump(),
            )
            await db.commit()
        except Exception:
            logger.exception("agent.bulk_audit_failed agent_profile=%s", agent_profile_uuid)
            await db.rollback()
    return AgentLeadBulkResponse(dry_run=payload.dry_run, rows=results, totals=totals)


@router.get("/leads", response_model=list[AgentLeadRead], response_model_exclude_unset=True)
async def list_leads(
    status_filter: str | None = None,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> list[AgentLeadRead]:
    agent_profile_uuid = _agent_profile_uuid(current_user)
    try:
        leads = await list_my_leads(db, agent_profile_uuid, status_filter)
    except InvalidStatusFilter as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown status_filter value."
        ) from exc
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    # Product and property facts for the list filters, through the confined
    # reader's Agent branch (own introduced leads on the Agent's line only).
    signals = await lead_signals(db, leads)
    return [
        _to_agent_lead_read(
            lead,
            modes,
            signals.get(lead.id, EMPTY_SIGNALS),
            agent_profile_uuid=agent_profile_uuid,
        )
        for lead in leads
    ]


@router.get("/lead-eligibility", response_model=EligibilitySummary)
async def lead_eligibility(
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> EligibilitySummary:
    """Eligible / Not eligible / Duplicate counts for the Agent's leads (CS-024)."""
    return await lead_eligibility_summary(db, _agent_profile_uuid(current_user))


@router.get("/lead-attempts", response_model=IntakeAttemptListResponse)
async def list_lead_attempts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> IntakeAttemptListResponse:
    """Introductions that were not accepted, newest first (recorded from CS-024 on)."""
    attempts, total = await lead_intake_attempts.list_attempts(
        db,
        IntakeActorType.AGENT,
        _agent_profile_uuid(current_user),
        limit=limit,
        offset=offset,
    )
    return IntakeAttemptListResponse(attempts=attempts, total=total)


@router.get("/leads/{lead_id}", response_model=AgentLeadRead, response_model_exclude_unset=True)
async def get_lead(
    lead_id: UUID,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadRead:
    agent_profile_uuid = _agent_profile_uuid(current_user)
    lead = await get_lead_for_agent(db, lead_id, agent_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    return _to_agent_lead_read(lead, modes, agent_profile_uuid=agent_profile_uuid)


@router.patch("/leads/{lead_id}", response_model=AgentLeadRead, response_model_exclude_unset=True)
async def patch_lead(
    lead_id: UUID,
    payload: AgentLeadUpdate,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadRead:
    agent_profile_uuid = _agent_profile_uuid(current_user)
    lead = await get_lead_for_agent(db, lead_id, agent_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    try:
        lead = await update_lead_for_agent(
            db,
            lead,
            payload,
            auth_user_uuid=current_user.id,
            agent_profile_uuid=agent_profile_uuid,
        )
    except LeadLocked as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This lead is already being worked or its Agent window has ended "
            "and it can no longer be edited.",
        ) from exc
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    return _to_agent_lead_read(lead, modes, agent_profile_uuid=agent_profile_uuid)


@router.post(
    "/leads/{lead_id}/resubmit",
    response_model=AgentLeadRead,
    response_model_exclude_unset=True,
)
async def resubmit_lead(
    lead_id: UUID,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadRead:
    """Resubmit this Agent's expired lead for a fresh 30-day window."""
    agent_profile_uuid = _agent_profile_uuid(current_user)
    if await get_lead_for_agent(db, lead_id, agent_profile_uuid) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    try:
        lead = await resubmit_lead_for_agent(
            db,
            lead_id,
            agent_profile_uuid=agent_profile_uuid,
            auth_user_uuid=current_user.id,
        )
    except LeadNotResubmittable as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This lead can't be resubmitted. Only an expired lead whose client "
            "hasn't registered can be resubmitted.",
        ) from exc
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    return _to_agent_lead_read(lead, modes, agent_profile_uuid=agent_profile_uuid)


@router.get("/commission-rates", response_model=AgentCommissionRatesResponse)
async def commission_rates(
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentCommissionRatesResponse:
    """Approved indicative commission rates of the active loan products, keyed
    by product slug (CS-028). Empty for a real-estate Agent: RLS returns
    approved rows to loans-line Agents only."""
    response.headers["Cache-Control"] = "private, no-store"
    _agent_profile_uuid(current_user)
    if current_user.business_line != "loans":
        return AgentCommissionRatesResponse(rates={})
    return AgentCommissionRatesResponse(
        rates=await commission_rate_service.approved_rates_for_agent(db)
    )


@router.get("/earnings", response_model=AgentEarningsResponse)
async def earnings(
    response: Response,
    status_filter: CommissionStatusLiteral | None = Query(default=None, alias="status"),
    deal_type: DealType | None = None,
    product_id: UUID | None = None,
    bank_id: UUID | None = None,
    property_category: str | None = Query(default=None, max_length=60),
    amount_min_paise: int | None = Query(default=None, ge=0, le=10_000_000_000),
    amount_max_paise: int | None = Query(default=None, ge=0, le=10_000_000_000),
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentEarningsResponse:
    """The Agent's commission history on their line with client and deal
    details, filtered; totals always cover every commission. Read through the
    confined ``agent_commission_ledger()`` function (caller's account, Agent
    profile and line only). Dates are IST calendar days on the entry date;
    amounts filter the commission amount."""
    response.headers["Cache-Control"] = "private, no-store"
    _agent_profile_uuid(current_user)
    if (
        amount_min_paise is not None
        and amount_max_paise is not None
        and amount_min_paise > amount_max_paise
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Minimum amount is above the maximum."
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "From date is after To date.")
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    return await agent_dashboard.list_earnings(
        db,
        filters=agent_dashboard.EarningsFilters(
            status=status_filter,
            deal_type=deal_type,
            product_id=product_id,
            bank_id=bank_id,
            property_category=property_category,
            amount_min_paise=amount_min_paise,
            amount_max_paise=amount_max_paise,
            date_from=date_from,
            date_to=date_to,
            q=q,
        ),
        modes=modes,
    )


@router.get("/transactions/{transaction_id}", response_model=AgentTransactionDetail)
async def get_transaction_detail(
    transaction_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentTransactionDetail:
    """One of the Agent's own ledger rows with its payout trail and the
    commission it paid. Another account's transaction reads as not found."""
    response.headers["Cache-Control"] = "private, no-store"
    _agent_profile_uuid(current_user)
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    detail = await agent_dashboard.transaction_detail(
        db, transaction_id=transaction_id, owner_uuid=current_user.id, modes=modes
    )
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found.")
    return detail


@router.get("/leads/{lead_id}/history", response_model=AgentLeadHistoryRead)
async def get_lead_history(
    lead_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadHistoryRead:
    """Applications, deals, enquiries, visits, calls and the status timeline
    of a lead this Agent introduced. Any other lead reads as not found."""
    response.headers["Cache-Control"] = "private, no-store"
    agent_profile_uuid = _agent_profile_uuid(current_user)
    lead = await get_lead_for_agent(db, lead_id, agent_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    modes = await effective_modes(db, FieldTargetRole.AGENT)
    history = await agent_dashboard.lead_history(db, lead, modes)
    if history is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    return history


def _payout_details_read(row: AgentPayoutDetails | None) -> AgentPayoutDetailsRead:
    available = field_crypto.is_available()
    if row is None:
        return AgentPayoutDetailsRead(saved=False, available=available)
    return AgentPayoutDetailsRead(
        saved=True,
        upi_hint=row.upi_hint,
        bank_hint=row.bank_hint,
        updated_at=row.updated_at,
        available=available,
        cheque_uploaded_at=row.cheque_uploaded_at,
        cheque_content_type=row.cheque_content_type,
    )


@router.get("/payout-details", response_model=AgentPayoutDetailsRead)
async def get_payout_details(
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentPayoutDetailsRead:
    """The Agent's saved payout destination, masked."""
    response.headers["Cache-Control"] = "private, no-store"
    row = await payout_details.get_own(db, _agent_profile_uuid(current_user))
    return _payout_details_read(row)


@router.put("/payout-details", response_model=AgentPayoutDetailsRead)
async def put_payout_details(
    payload: AgentPayoutDetailsUpdate,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentPayoutDetailsRead:
    """Save or change the bank account and/or UPI ID commissions are paid to."""
    try:
        row = await payout_details.save_own(
            db,
            agent_profile_uuid=_agent_profile_uuid(current_user),
            auth_user_uuid=current_user.id,
            payload=payload,
        )
    except payout_details.PayoutDetailsUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Saving payout details is not available right now.",
        ) from exc
    except payout_details.PayoutDetailsEmpty as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Keep at least a UPI ID or a bank account, or remove all payout details.",
        ) from exc
    return _payout_details_read(row)


@router.delete("/payout-details", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payout_details(
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove every saved payout destination (and any cancelled cheque)."""
    await payout_details.delete_own(
        db,
        agent_profile_uuid=_agent_profile_uuid(current_user),
        auth_user_uuid=current_user.id,
    )


_CHEQUE_ERROR_STATUS = {
    payout_cheque.PayoutDetailsMissing: status.HTTP_409_CONFLICT,
    payout_cheque.UploadRateExceeded: status.HTTP_429_TOO_MANY_REQUESTS,
    payout_cheque.ObjectKeyMismatch: status.HTTP_400_BAD_REQUEST,
    payout_cheque.UploadMissing: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payout_cheque.ContentTypeMismatch: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payout_cheque.StorageUnavailable: status.HTTP_502_BAD_GATEWAY,
    payout_cheque.ChequeNotFound: status.HTTP_404_NOT_FOUND,
}


def _cheque_error(exc: payout_cheque.ChequeError) -> HTTPException:
    code = _CHEQUE_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(code, str(exc) or "The cancelled cheque could not be saved.")


@router.post("/payout-details/cheque/presign", response_model=AgentChequePresignResponse)
async def presign_payout_cheque(
    payload: AgentChequePresignRequest,
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
) -> AgentChequePresignResponse:
    """Signed upload for an optional cancelled cheque (JPEG, PNG or PDF, up to
    5 MB). Requires saved payout details."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        object_key, upload_url, fields, max_bytes = await payout_cheque.presign_upload(
            db,
            cache,
            agent_profile_uuid=_agent_profile_uuid(current_user),
            auth_user_uuid=current_user.id,
            content_type=payload.content_type,
        )
    except payout_cheque.ChequeError as exc:
        raise _cheque_error(exc) from exc
    return AgentChequePresignResponse(
        object_key=object_key, upload_url=upload_url, fields=fields, max_bytes=max_bytes
    )


@router.put("/payout-details/cheque", response_model=AgentPayoutDetailsRead)
async def confirm_payout_cheque(
    payload: AgentChequeConfirm,
    response: Response,
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentPayoutDetailsRead:
    """Attach (or replace) the cancelled cheque after the browser uploaded it."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        row = await payout_cheque.confirm_upload(
            db,
            agent_profile_uuid=_agent_profile_uuid(current_user),
            auth_user_uuid=current_user.id,
            object_key=payload.object_key,
            content_type=payload.content_type,
        )
    except payout_cheque.ChequeError as exc:
        raise _cheque_error(exc) from exc
    return _payout_details_read(row)


@router.delete("/payout-details/cheque", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payout_cheque(
    current_user: CurrentUser = Depends(require_agent),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the cancelled cheque; the saved bank account and UPI ID stay."""
    try:
        await payout_cheque.delete_own(
            db,
            agent_profile_uuid=_agent_profile_uuid(current_user),
            auth_user_uuid=current_user.id,
        )
    except payout_cheque.ChequeError as exc:
        raise _cheque_error(exc) from exc
