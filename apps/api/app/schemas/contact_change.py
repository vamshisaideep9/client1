"""Wire contract for CS-025 phone/email changes and the contact history."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import DeliveryChannel

ContactFieldLiteral = Literal["mobile", "email"]
ContactChangeKindLiteral = Literal["self_service", "email_add", "staff_request"]
ContactChangeStatusLiteral = Literal[
    "awaiting_current_otp",
    "awaiting_new_value",
    "awaiting_new_otp",
    "pending_approval",
    "completed",
    "rejected",
    "cancelled",
    "expired",
]
Otp = Annotated[str, Field(pattern=r"^\d{6}$")]
CurrentPassword = Annotated[str, Field(min_length=1, max_length=128)]


def normalize_email(value: str) -> str:
    return value.strip().lower()


class EmailAddRequest(BaseModel):
    """Add an email to an account that has no verified one (CS-025)."""

    email: EmailStr
    current_password: CurrentPassword

    @field_validator("email")
    @classmethod
    def email_normalize(cls, value: str) -> str:
        return normalize_email(value)


class ContactChangeIdRequest(BaseModel):
    change_id: UUID


class ContactChangeOtpRequest(BaseModel):
    change_id: UUID
    otp: Otp


class ContactChangeChallengeResponse(BaseModel):
    """One step of a change: where the code went and what comes next."""

    change_id: UUID
    kind: ContactChangeKindLiteral
    field: ContactFieldLiteral
    status: ContactChangeStatusLiteral
    expires_at: datetime
    message: str
    # Masked destination of the code just sent (``***3210`` / ``j***@x.com``).
    destination_hint: str | None = None
    delivery_channel: DeliveryChannel | None = None
    otp_hint: str | None = None  # non-production mock delivery only


class RegisterEmailInitiateRequest(BaseModel):
    registration_token: str
    email: EmailStr

    @field_validator("email")
    @classmethod
    def email_normalize(cls, value: str) -> str:
        return normalize_email(value)


class RegisterEmailVerifyRequest(BaseModel):
    registration_token: str
    email: EmailStr
    otp: Otp

    @field_validator("email")
    @classmethod
    def email_normalize(cls, value: str) -> str:
        return normalize_email(value)


class RegisterEmailInitiateResponse(BaseModel):
    message: str
    delivery_channel: DeliveryChannel
    otp_hint: str | None = None


class ContactChangeStartRequest(BaseModel):
    field: ContactFieldLiteral
    current_password: CurrentPassword


class ContactChangeNewValueRequest(BaseModel):
    change_id: UUID
    # Validated against the change's field in the service (an E.164 number or
    # an email address), so one endpoint serves both journeys.
    value: Annotated[str, Field(min_length=3, max_length=320)]


class ContactChangeCompletedResponse(BaseModel):
    message: str
    # Every session was ended, this one included; the client signs in again.
    signed_out: bool = True


class ContactChangeRead(BaseModel):
    """The caller's own change in flight (to resume or cancel it)."""

    change_id: UUID
    kind: ContactChangeKindLiteral
    field: ContactFieldLiteral
    status: ContactChangeStatusLiteral
    new_value_hint: str | None
    expires_at: datetime
    created_at: datetime


class ActiveContactChangeResponse(BaseModel):
    change: ContactChangeRead | None


ContactChangeMethodLiteral = Literal[
    "self_service", "email_added", "admin_approved", "lost_number_recovery"
]


class ContactHistoryEntry(BaseModel):
    """One completed change, old value included (platform Admin only)."""

    id: UUID
    field: ContactFieldLiteral
    old_value: str | None
    new_value: str
    method: ContactChangeMethodLiteral
    proof_category: str | None
    proof_reference: str | None
    approved_by_name: str | None
    changed_at: datetime


class ContactHistoryResponse(BaseModel):
    entries: list[ContactHistoryEntry]
