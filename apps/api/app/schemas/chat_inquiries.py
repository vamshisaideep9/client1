from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import UUID4, BaseModel, Field, StringConstraints

ChatSection = Literal["loans", "credit_cards", "insurance", "real_estate"]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ChatQuestion(BaseModel):
    prompt: str
    options: list[str]


class ChatAction(BaseModel):
    id: str
    label: str


class ChatFlow(BaseModel):
    id: str
    section: ChatSection
    label: str
    questions: list[ChatQuestion]
    actions: list[ChatAction]
    browse_href: str | None = None


class ChatInquiryCreate(BaseModel):
    idempotency_key: UUID4
    flow: ShortText
    action: ShortText
    answers: Annotated[list[ShortText], Field(min_length=3, max_length=3)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    mobile: Annotated[str, Field(pattern=r"^\+91[6-9]\d{9}$")]
    location: ShortText
    company: Annotated[str | None, Field(max_length=200)] = None


class ChatInquiryReceipt(BaseModel):
    reference: UUID


class ChatInquiryRead(ChatInquiryReceipt):
    service: str
    action: str
    name: str | None = None
    location: str
    preferences: dict[str, str]
    created_at: datetime
