"""Telecaller router — assigned-lead list/detail, status update, call log, home.

Every route depends on require_telecaller (app-layer gate) on top of the
leads_rls / lead_activities_rls own-assignment RLS predicates (defense in depth,
same posture as every other role-gated router in this codebase).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_telecaller
from app.db.session import get_db
from app.models.field_visibility import FieldTargetRole, FieldVisibilityMode
from app.schemas.loans import LoanApplicationProgressUpdate
from app.schemas.property_deals import PropertyDealProgressUpdate
from app.schemas.telecaller import (
    ClientHistoryLead,
    LeadActivityCreate,
    LeadActivityRead,
    LeadStatusLiteral,
    LoanTxnCreate,
    LoanTxnRead,
    PropertyDealCreate,
    TaskCreate,
    TaskRead,
    TelecallerClientHistoryResponse,
    TelecallerFinancialEnquiryRead,
    TelecallerFollowUpItem,
    TelecallerHomeResponse,
    TelecallerLeadDetailRead,
    TelecallerLeadRead,
    TelecallerLeadUpdate,
    TelecallerLoanApplicationRead,
    TelecallerPropertyDealRead,
    TelecallerPropertyEnquiryRead,
    TelecallerSiteVisitRead,
)
from app.services.chat_inquiries import list_chat_inquiries
from app.services.field_visibility import effective_modes, project_values
from app.services.lead_details import visible_requirement
from app.services.lead_signals import facets, lead_signals, transaction_summary
from app.services.loan_applications import (
    BankNotAvailableForLoanType,
    SanctionTermsRequired,
    StatusReasonRequired,
    TerminalApplication,
    TermsNotAllowedAtStage,
    UnknownBank,
    apply_progress_update,
)
from app.services.loan_applications import InvalidStatusTransition as InvalidLoanStatusTransition
from app.services.profile_metadata import task_staff_for_ids
from app.services.property_deals import (
    ClientNotRegistered,
    LeadNotRealEstateLine,
    PropertyNotFound,
    TerminalDeal,
    UnknownSiteVisit,
    create_deal_for_lead,
)
from app.services.property_deals import InvalidStatusTransition as InvalidDealStatusTransition
from app.services.property_deals import (
    StatusReasonRequired as DealStatusReasonRequired,
)
from app.services.property_deals import (
    TermsNotAllowedAtStage as DealTermsNotAllowedAtStage,
)
from app.services.property_deals import (
    apply_progress_update as apply_deal_progress_update,
)
from app.services.team_manager import work_notes
from app.services.telecaller import (
    LoanApplicationNotFound,
    LoanApplicationNotLoansLine,
    PropertyDealNotFound,
    PropertyDealNotRealEstateLine,
    RequestNotOnLead,
    add_txn_history,
    get_application_for_telecaller,
    get_deal_for_telecaller,
    get_home_summary,
    get_last_activities,
    get_lead_for_telecaller,
    list_activities_for_lead,
    list_activities_for_leads,
    list_assigned_leads,
    list_client_journeys,
    list_financial_enquiries_for_lead,
    list_loan_applications_for_lead,
    list_property_deals_for_lead,
    list_property_enquiries_for_lead,
    list_site_visits_for_lead,
    list_tasks_for_lead,
    list_txns_for_applications,
    log_call_activity,
    raise_task,
    request_summaries_for_leads,
    to_activity_read,
    update_lead,
)

router = APIRouter()


def _to_telecaller_property_deal_read(
    deal,
    modes: dict[tuple[str, str], FieldVisibilityMode],  # noqa: ANN001
) -> TelecallerPropertyDealRead:
    return TelecallerPropertyDealRead(
        id=deal.id,
        property_title=deal.property.title,
        property_location=deal.property.location,
        status=deal.status,
        site_visit_uuid=deal.site_visit_uuid,
        opened_at=deal.opened_at,
        closed_at=deal.closed_at,
        **project_values(
            modes,
            "property_deal",
            {
                "price_quoted": deal.price_quoted,
                "booking_amount": deal.booking_amount,
                "status_reason": deal.status_reason,
            },
        ),
    )


def _to_telecaller_loan_application_read(
    application,  # noqa: ANN001
    txns: list[LoanTxnRead],
    modes: dict[tuple[str, str], FieldVisibilityMode],
) -> TelecallerLoanApplicationRead:
    return TelecallerLoanApplicationRead(
        id=application.id,
        loan_type_id=application.loan_type_id,
        loan_type_name=application.loan_type.label,
        bank_id=application.bank_id,
        bank_name=application.bank.name if application.bank else None,
        fee_outcome=application.fee_outcome,
        status=application.status,
        opened_at=application.opened_at,
        closed_at=application.closed_at,
        form_version=application.form_version,
        form_schema_snapshot=application.form_schema_snapshot,
        form_answers=application.form_answers,
        txns=txns,
        **project_values(
            modes,
            "loan_application",
            {
                "amount_requested": application.amount_requested,
                "amount_sanctioned": application.amount_sanctioned,
                "interest_rate": application.interest_rate,
                "processing_fee": application.processing_fee,
                "status_reason": application.status_reason,
            },
        ),
    )


def _to_loan_txn_read(
    txn,
    modes: dict[tuple[str, str], FieldVisibilityMode],  # noqa: ANN001
) -> LoanTxnRead:
    return LoanTxnRead(
        id=txn.id,
        loan_application_uuid=txn.loan_application_uuid,
        created_at=txn.created_at,
        **project_values(
            modes,
            "loan_transaction",
            {
                "bank_name": txn.bank_name,
                "amount": txn.amount,
                "interest_rate": txn.interest_rate,
                "txn_date": txn.txn_date,
            },
        ),
    )


def _staff_profile_uuid(current_user: CurrentUser) -> UUID:
    if current_user.staff_profile_uuid is None:
        # pragma: no cover — every telecaller JWT carries one
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No staff profile on this account.")
    return current_user.staff_profile_uuid


@router.get("/leads", response_model=list[TelecallerLeadRead], response_model_exclude_unset=True)
async def list_leads(
    status_filter: LeadStatusLiteral | None = None,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> list[TelecallerLeadRead]:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    leads = await list_assigned_leads(db, staff_profile_uuid, status_filter)
    lead_ids = [lead.id for lead in leads]
    last_by_lead = await get_last_activities(db, lead_ids)
    requests_by_lead = await request_summaries_for_leads(db, lead_ids)
    signals_by_lead = await lead_signals(db, leads)
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    out: list[TelecallerLeadRead] = []
    for lead in leads:
        activity = last_by_lead.get(lead.id)
        requests = requests_by_lead.get(lead.id) or []
        signals = signals_by_lead[lead.id]
        out.append(
            TelecallerLeadRead(
                id=lead.id,
                mobile=lead.mobile,
                business_line=lead.business_line,
                status=lead.status,
                last_disposition=activity.disposition if activity else None,
                last_interest_level=activity.interest_level if activity else None,
                next_follow_up_at=activity.follow_up_at if activity else None,
                created_at=lead.created_at,
                updated_at=lead.updated_at,
                latest_request=requests[0] if requests else None,
                loan_statuses=signals.loan_statuses,
                facets=facets(signals),
                transactions=transaction_summary(signals.transactions, modes, lead.business_line),
                resubmit_count=lead.resubmit_count,
                last_resubmitted_at=lead.last_resubmitted_at,
                **project_values(
                    modes,
                    "lead",
                    {
                        "name": lead.name,
                        "requirement": visible_requirement(lead, "telecaller"),
                        "referrer": signals.referrer,
                    },
                ),
            )
        )
    return out


@router.get(
    "/leads/{lead_id}",
    response_model=TelecallerLeadDetailRead,
    response_model_exclude_unset=True,
)
async def get_lead(
    lead_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerLeadDetailRead:
    response.headers["Cache-Control"] = "private, no-store"
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    activities = await list_activities_for_lead(db, lead_id)
    last = activities[0] if activities else None
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)

    loan_applications: list[TelecallerLoanApplicationRead] = []
    if lead.business_line == "loans":
        applications = await list_loan_applications_for_lead(db, lead_id)
        txns_by_application = await list_txns_for_applications(
            db, [application.id for application in applications]
        )
        loan_applications = [
            _to_telecaller_loan_application_read(
                application,
                [
                    _to_loan_txn_read(txn, modes)
                    for txn in txns_by_application.get(application.id, [])
                ],
                modes,
            )
            for application in applications
        ]

    financial_enquiries: list[TelecallerFinancialEnquiryRead] = []
    if lead.business_line == "loans":
        financial_enquiries = [
            TelecallerFinancialEnquiryRead(
                id=enquiry.id,
                product_name=enquiry.product.label,
                product_category=enquiry.product_category,
                status=enquiry.status,
                submitted_at=enquiry.submitted_at,
            )
            for enquiry in await list_financial_enquiries_for_lead(db, lead_id)
        ]

    property_deals: list[TelecallerPropertyDealRead] = []
    property_enquiries: list[TelecallerPropertyEnquiryRead] = []
    site_visits: list[TelecallerSiteVisitRead] = []
    if lead.business_line == "real_estate":
        deals = await list_property_deals_for_lead(db, lead_id)
        property_deals = [_to_telecaller_property_deal_read(d, modes) for d in deals]
        property_enquiries = [
            TelecallerPropertyEnquiryRead.model_validate(enquiry, from_attributes=True)
            for enquiry in await list_property_enquiries_for_lead(db, lead_id)
        ]
        site_visits = [
            TelecallerSiteVisitRead.model_validate(visit, from_attributes=True)
            for visit in await list_site_visits_for_lead(db, lead_id)
        ]

    tasks = await list_tasks_for_lead(db, lead_id)
    task_staff = await task_staff_for_ids(db, (task.id for task in tasks))
    requests = (await request_summaries_for_leads(db, [lead_id]))[lead_id]
    signals = (await lead_signals(db, [lead]))[lead.id]

    return TelecallerLeadDetailRead(
        id=lead.id,
        mobile=lead.mobile,
        business_line=lead.business_line,
        status=lead.status,
        last_disposition=last.disposition if last else None,
        last_interest_level=last.interest_level if last else None,
        next_follow_up_at=last.follow_up_at if last else None,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        latest_request=requests[0] if requests else None,
        loan_statuses=signals.loan_statuses,
        facets=facets(signals),
        transactions=transaction_summary(signals.transactions, modes, lead.business_line),
        resubmit_count=lead.resubmit_count,
        last_resubmitted_at=lead.last_resubmitted_at,
        activities=[to_activity_read(a) for a in activities],
        loan_applications=loan_applications,
        financial_enquiries=financial_enquiries,
        chat_inquiries=(
            await list_chat_inquiries(
                db, lead.id, include_name=modes.get(("lead", "name")) == FieldVisibilityMode.ALLOW
            )
            if modes.get(("lead", "requirement")) == FieldVisibilityMode.ALLOW
            else []
        ),
        property_enquiries=property_enquiries,
        site_visits=site_visits,
        property_deals=property_deals,
        tasks=[
            TaskRead.model_validate(t, from_attributes=True).model_copy(
                update=task_staff[t.id].model_dump() if t.id in task_staff else {}
            )
            for t in tasks
        ],
        manager_notes=await work_notes(db, lead_id=lead.id),
        **project_values(
            modes,
            "lead",
            {
                "name": lead.name,
                "requirement": visible_requirement(lead, "telecaller"),
                "referrer": signals.referrer,
            },
        ),
    )


@router.patch(
    "/leads/{lead_id}",
    response_model=TelecallerLeadRead,
    response_model_exclude_unset=True,
)
async def patch_lead(
    lead_id: UUID,
    payload: TelecallerLeadUpdate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerLeadRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    lead = await update_lead(db, lead, payload)
    activity = (await get_last_activities(db, [lead.id])).get(lead.id)
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return TelecallerLeadRead(
        id=lead.id,
        mobile=lead.mobile,
        business_line=lead.business_line,
        status=lead.status,
        last_disposition=activity.disposition if activity else None,
        next_follow_up_at=activity.follow_up_at if activity else None,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        resubmit_count=lead.resubmit_count,
        last_resubmitted_at=lead.last_resubmitted_at,
        **project_values(
            modes,
            "lead",
            {"name": lead.name, "requirement": visible_requirement(lead, "telecaller")},
        ),
    )


@router.post(
    "/leads/{lead_id}/activities",
    response_model=LeadActivityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_activity(
    lead_id: UUID,
    payload: LeadActivityCreate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> LeadActivityRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    try:
        activity = await log_call_activity(db, lead, staff_profile_uuid, payload)
    except RequestNotOnLead as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That application or enquiry is not on this lead.",
        ) from exc
    return to_activity_read(activity)


@router.get(
    "/leads/{lead_id}/client-history",
    response_model=TelecallerClientHistoryResponse,
)
async def client_history(
    lead_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerClientHistoryResponse:
    """All of this client's journeys on the line that are assigned to the
    caller, each with its requests and the caller's own calls."""
    response.headers["Cache-Control"] = "private, no-store"
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    journeys = await list_client_journeys(db, lead, staff_profile_uuid)
    journey_ids = [journey.id for journey in journeys]
    requests_by_lead = await request_summaries_for_leads(db, journey_ids)
    activities_by_lead = await list_activities_for_leads(db, journey_ids, staff_profile_uuid)
    return TelecallerClientHistoryResponse(
        business_line=lead.business_line,
        leads=[
            ClientHistoryLead(
                lead_id=journey.id,
                status=journey.status,
                created_at=journey.created_at,
                requests=requests_by_lead[journey.id],
                activities=[to_activity_read(a) for a in activities_by_lead[journey.id]],
            )
            for journey in journeys
        ],
    )


@router.post(
    "/loan-applications/{application_id}/txn-history",
    response_model=LoanTxnRead,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_loan_txn(
    application_id: UUID,
    payload: LoanTxnCreate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> LoanTxnRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    try:
        application = await get_application_for_telecaller(db, application_id, staff_profile_uuid)
    except LoanApplicationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan application not found.") from exc
    except LoanApplicationNotLoansLine as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Transaction history is loans-line only."
        ) from exc
    txn = await add_txn_history(db, application, staff_profile_uuid, payload)
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return _to_loan_txn_read(txn, modes)


@router.patch(
    "/loan-applications/{application_id}",
    response_model=TelecallerLoanApplicationRead,
    response_model_exclude_unset=True,
)
async def update_loan_application_progress(
    application_id: UUID,
    payload: LoanApplicationProgressUpdate,
    response: Response,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerLoanApplicationRead:
    response.headers["Cache-Control"] = "private, no-store"
    staff_profile_uuid = _staff_profile_uuid(current_user)
    try:
        application = await get_application_for_telecaller(db, application_id, staff_profile_uuid)
    except LoanApplicationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loan application not found.") from exc
    except LoanApplicationNotLoansLine as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Loan status can only be updated on a loans-line application."
        ) from exc

    try:
        application = await apply_progress_update(
            db,
            application,
            payload,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except TerminalApplication as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This application is already closed."
        ) from exc
    except InvalidLoanStatusTransition as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That status change is not allowed from the current status."
        ) from exc
    except StatusReasonRequired as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A reason is required when moving to rejected or on hold.",
        ) from exc
    except TermsNotAllowedAtStage as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Deal terms can only be set once the application has been submitted to a bank.",
        ) from exc
    except SanctionTermsRequired as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Add the approved amount and bank before moving the loan to Approved or a later stage.",
        ) from exc
    except UnknownBank as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown or inactive bank."
        ) from exc
    except BankNotAvailableForLoanType as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This bank does not offer that loan type."
        ) from exc

    txns_by_application = await list_txns_for_applications(db, [application.id])
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return _to_telecaller_loan_application_read(
        application,
        [_to_loan_txn_read(txn, modes) for txn in txns_by_application.get(application.id, [])],
        modes,
    )


@router.post(
    "/leads/{lead_id}/property-deals",
    response_model=TelecallerPropertyDealRead,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_property_deal(
    lead_id: UUID,
    payload: PropertyDealCreate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerPropertyDealRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    try:
        deal = await create_deal_for_lead(db, lead, payload.property_id)
    except LeadNotRealEstateLine as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Property deals are real-estate-line only."
        ) from exc
    except PropertyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or inactive property.") from exc
    except ClientNotRegistered as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This lead isn't linked to a registered client yet.",
        ) from exc
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return _to_telecaller_property_deal_read(deal, modes)


@router.patch(
    "/property-deals/{deal_id}",
    response_model=TelecallerPropertyDealRead,
    response_model_exclude_unset=True,
)
async def update_property_deal_progress(
    deal_id: UUID,
    payload: PropertyDealProgressUpdate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerPropertyDealRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    try:
        deal = await get_deal_for_telecaller(db, deal_id, staff_profile_uuid)
    except PropertyDealNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Property deal not found.") from exc
    except PropertyDealNotRealEstateLine as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Deal status can only be updated on a real-estate-line deal.",
        ) from exc

    try:
        deal = await apply_deal_progress_update(
            db,
            deal,
            payload,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except TerminalDeal as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "This deal is already closed.") from exc
    except InvalidDealStatusTransition as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That status change is not allowed from the current status."
        ) from exc
    except DealStatusReasonRequired as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A reason is required when moving to rejected or on hold.",
        ) from exc
    except DealTermsNotAllowedAtStage as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Deal terms can only be set once the deal has been booked.",
        ) from exc
    except UnknownSiteVisit as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown site visit for this client."
        ) from exc

    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return _to_telecaller_property_deal_read(deal, modes)


@router.post(
    "/leads/{lead_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    lead_id: UUID,
    payload: TaskCreate,
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    lead = await get_lead_for_telecaller(db, lead_id, staff_profile_uuid)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found.")
    task = await raise_task(db, lead, staff_profile_uuid, payload)
    staff = await task_staff_for_ids(db, [task.id])
    return TaskRead.model_validate(task, from_attributes=True).model_copy(
        update=staff[task.id].model_dump() if task.id in staff else {}
    )


@router.get("/home", response_model=TelecallerHomeResponse, response_model_exclude_unset=True)
async def home(
    current_user: CurrentUser = Depends(require_telecaller),
    db: AsyncSession = Depends(get_db),
) -> TelecallerHomeResponse:
    staff_profile_uuid = _staff_profile_uuid(current_user)
    due, counts = await get_home_summary(db, staff_profile_uuid)
    requests_by_lead = await request_summaries_for_leads(db, [lead.id for lead, _ in due])
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    return TelecallerHomeResponse(
        follow_ups_due=[
            TelecallerFollowUpItem(
                lead_uuid=lead.id,
                mobile=lead.mobile,
                follow_up_at=follow_up_at,
                latest_request=next(iter(requests_by_lead.get(lead.id) or []), None),
                **project_values(modes, "lead", {"name": lead.name}),
            )
            for lead, follow_up_at in due
        ],
        counts_by_status=counts,
    )
