"""Public lead-capture router (docs/specs/public-leads-endpoint.md).

Unauthenticated write, so every request passes: schema whitelists (lengths,
literal topic/origin, E.164 mobile) -> honeypot -> per-IP cap -> per-mobile
cap -> insert-or-enrich via services.leads.capture_lead (own superuser
session, bypasses RLS like the auth-flow captures).

Always answers 202 for accepted-shaped requests — including honeypot drops
and swallowed storage failures — so the response never discloses whether a
mobile already exists in the lead spine or which submissions were discarded.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import (
    TTL_CONTACT_INVITATION_RATE,
    TTL_LEAD_RATE,
    RedisCache,
    contact_invitation_rate_ip_key,
    lead_rate_ip_key,
    lead_rate_mobile_key,
)
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.deps import get_cache
from app.db.session import get_db
from app.schemas.chat_inquiries import ChatFlow, ChatInquiryCreate, ChatInquiryReceipt
from app.schemas.field_visibility import ContactInvitationRead
from app.schemas.leads import PublicLeadCreate, PublicLeadResponse
from app.services.chat_flows import available_flows
from app.services.chat_inquiries import ChatInquiryInvalid, create_chat_inquiry
from app.services.field_visibility import consume_invitation, invitation_is_valid
from app.services.leads import capture_lead
from app.services.properties import get_active_property

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/invitations/{token}", response_model=ContactInvitationRead)
async def get_contact_invitation(
    token: str,
    request: Request,
    cache: RedisCache = Depends(get_cache),
) -> ContactInvitationRead:
    ip = get_client_ip(request)
    if ip:
        count = await cache.incr_with_expire(
            contact_invitation_rate_ip_key(ip), TTL_CONTACT_INVITATION_RATE
        )
        if count > 120:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Please try again later.",
            )
    # Same response shape for unknown, expired, used, and revoked tokens; no
    # lead/contact metadata is exposed to a bearer or brute-force caller.
    return ContactInvitationRead(valid=await invitation_is_valid(token))


async def _check_lead_rates(cache: RedisCache, ip: str | None, mobile: str) -> None:
    if ip:
        ip_count = await cache.incr_with_expire(lead_rate_ip_key(ip), TTL_LEAD_RATE)
        if ip_count > settings.LEAD_RATE_LIMIT_PER_IP:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )
    mobile_count = await cache.incr_with_expire(lead_rate_mobile_key(mobile), TTL_LEAD_RATE)
    if mobile_count > settings.LEAD_RATE_LIMIT_PER_MOBILE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )


@router.post(
    "",
    response_model=PublicLeadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_lead(
    req: PublicLeadCreate,
    request: Request,
    cache: RedisCache = Depends(get_cache),
    db: AsyncSession = Depends(get_db),
) -> PublicLeadResponse:
    # Honeypot tripped: pretend success, write nothing, spend nothing.
    if req.company:
        logger.info("lead.honeypot origin=%s", req.origin)
        return PublicLeadResponse()

    await _check_lead_rates(cache, get_client_ip(request), req.mobile)

    property_listing = (
        await get_active_property(db, req.property_ref) if req.property_ref is not None else None
    )
    requirement = {
        "page": req.origin,
        **(
            {
                "property_ref": str(property_listing.id),
                "property_title": property_listing.title,
                "property_location": property_listing.location,
                "product": f"{property_listing.title}, {property_listing.location}"[:120],
            }
            if property_listing is not None
            else ({"product": req.product} if req.product and req.property_ref is None else {})
        ),
        **({"email": req.email} if req.email else {}),
        **({"message": req.message} if req.message else {}),
    }

    stored = await capture_lead(
        req.mobile,
        name=req.name,
        business_line=req.topic,
        origin="direct",  # LeadOrigin = referral source, not page; page is in requirement
        requirement=requirement,
    )
    if not stored:
        # Already logged with traceback inside capture_lead; no lead UUID to
        # log and never any PII here.
        logger.error("lead.public_capture_dropped origin=%s", req.origin)
    elif req.invitation_token:
        await consume_invitation(req.invitation_token, req.mobile)

    return PublicLeadResponse()


class ChatInquiryRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def sanitized(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError:
                raise HTTPException(422, "Check your answers and contact details.") from None
            except SQLAlchemyError:
                logger.error("lead.chat_inquiry_database_error")
                raise HTTPException(
                    503, "The inquiry service is temporarily unavailable."
                ) from None

        return sanitized


chat_router = APIRouter(prefix="/chat-inquiries", route_class=ChatInquiryRoute)


@chat_router.get("/flows", response_model=list[ChatFlow])
async def chat_flows(response: Response, db: AsyncSession = Depends(get_db)) -> list[ChatFlow]:
    response.headers["Cache-Control"] = "no-store"
    return await available_flows(db)


@chat_router.post("", response_model=ChatInquiryReceipt, status_code=status.HTTP_201_CREATED)
async def submit_chat_inquiry(
    payload: ChatInquiryCreate,
    request: Request,
    response: Response,
    cache: RedisCache = Depends(get_cache),
    db: AsyncSession = Depends(get_db),
) -> ChatInquiryReceipt:
    if payload.company:
        raise HTTPException(422, "Check your answers and contact details.")
    await _check_lead_rates(cache, get_client_ip(request), payload.mobile)
    try:
        reference = await create_chat_inquiry(db, payload)
    except ChatInquiryInvalid:
        raise HTTPException(422, "These options have changed. Please start again.") from None
    response.headers["Cache-Control"] = "no-store"
    return ChatInquiryReceipt(reference=reference)


router.include_router(chat_router)
