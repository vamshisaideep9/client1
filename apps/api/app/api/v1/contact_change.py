"""CS-025 phone and email change routes (mounted at /api/v1/auth/contact-change).

Every route authenticates and installs the RLS context through the usual
dependencies; the service then works on a bypass session with its own actor
checks (``services/contact_change.py``), as ``api/v1/mobile_change.py`` does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.cache.redis_keys import RedisCache
from app.core.client_ip import get_client_ip
from app.core.deps import (
    CurrentUser,
    get_active_user,
    get_active_user_allow_email_pending,
    get_cache,
)
from app.schemas.auth import MessageResponse
from app.schemas.contact_change import (
    ActiveContactChangeResponse,
    ContactChangeChallengeResponse,
    ContactChangeCompletedResponse,
    ContactChangeIdRequest,
    ContactChangeNewValueRequest,
    ContactChangeOtpRequest,
    ContactChangeStartRequest,
)
from app.services import contact_change as service

router = APIRouter()


def _actor(current_user: CurrentUser) -> service.Actor:
    return service.Actor(user_uuid=current_user.id, role=current_user.role)


@router.get("/active", response_model=ActiveContactChangeResponse)
async def active(
    current_user: CurrentUser = Depends(get_active_user_allow_email_pending),
) -> ActiveContactChangeResponse:
    """The caller's own change in flight, if any (to resume or cancel it)."""
    return ActiveContactChangeResponse(change=await service.active_for(_actor(current_user)))


@router.post("/start", response_model=ContactChangeChallengeResponse)
async def start(
    payload: ContactChangeStartRequest,
    request: Request,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user),
) -> ContactChangeChallengeResponse:
    """Client, Agent or Admin: password, then a code to the current value."""
    try:
        return await service.start_self_service(
            cache,
            actor=_actor(current_user),
            field=payload.field,
            current_password=payload.current_password,
            ip=get_client_ip(request),
        )
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc


@router.post("/resend", response_model=ContactChangeChallengeResponse)
async def resend(
    payload: ContactChangeIdRequest,
    request: Request,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user),
) -> ContactChangeChallengeResponse:
    try:
        return await service.resend_self_service(
            cache,
            actor=_actor(current_user),
            change_id=payload.change_id,
            ip=get_client_ip(request),
        )
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc


@router.post("/verify-current", response_model=ContactChangeChallengeResponse)
async def verify_current(
    payload: ContactChangeOtpRequest,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user),
) -> ContactChangeChallengeResponse:
    try:
        return await service.verify_current(
            cache, actor=_actor(current_user), change_id=payload.change_id, otp=payload.otp
        )
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc


@router.post("/new-value", response_model=ContactChangeChallengeResponse)
async def new_value(
    payload: ContactChangeNewValueRequest,
    request: Request,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user),
) -> ContactChangeChallengeResponse:
    try:
        return await service.submit_new_value(
            cache,
            actor=_actor(current_user),
            change_id=payload.change_id,
            value=payload.value,
            ip=get_client_ip(request),
        )
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc


@router.post("/verify-new", response_model=ContactChangeCompletedResponse)
async def verify_new(
    payload: ContactChangeOtpRequest,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user),
) -> ContactChangeCompletedResponse:
    """Verify the new-value code; the change applies and every session ends."""
    try:
        await service.verify_new_and_apply(
            cache, actor=_actor(current_user), change_id=payload.change_id, otp=payload.otp
        )
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc
    return ContactChangeCompletedResponse(
        message="Changed. Every device was signed out; sign in again to continue."
    )


@router.post("/cancel", response_model=MessageResponse)
async def cancel(
    payload: ContactChangeIdRequest,
    cache: RedisCache = Depends(get_cache),
    current_user: CurrentUser = Depends(get_active_user_allow_email_pending),
) -> MessageResponse:
    """Withdraw the caller's own change (any kind) while it is still active."""
    try:
        await service.cancel_change(cache, actor=_actor(current_user), change_id=payload.change_id)
    except service.ContactChangeError as exc:
        raise service.http_error(exc) from exc
    return MessageResponse(message="Change cancelled.")
