from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

WebsiteKey = Annotated[
    str, StringConstraints(max_length=160, pattern=r"^[a-z0-9]+(?:[-/][a-z0-9]+)*$")
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=180)]
EntryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]


class WebsiteFAQ(BaseModel):
    question: EntryText
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]


class WebsiteEntry(BaseModel):
    title: EntryText
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]


class WebsiteContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: ShortText = ""
    summary: ShortText = ""
    body: str = Field(default="", max_length=40_000)
    sections: list[WebsiteEntry] = Field(default_factory=list, max_length=30)
    faq: list[WebsiteFAQ] | None = Field(default=None, max_length=30)
    form_copy: dict[
        Literal[
            "heading",
            "name",
            "mobile",
            "email",
            "message",
            "topic",
            "location",
            "submit",
            "help",
            "product",
            "property",
        ],
        ShortText,
    ] = Field(default_factory=dict)


class WebsiteDraftWrite(BaseModel):
    expected_version: int = Field(ge=0)
    content: WebsiteContent


class WebsitePublishWrite(BaseModel):
    expected_version: int = Field(ge=1)
    restore_revision: int | None = Field(default=None, ge=1)


class WebsiteDocumentRead(BaseModel):
    key: WebsiteKey
    draft: WebsiteContent
    version: int
    published_revision: int | None


class WebsiteRevisionRead(BaseModel):
    revision: int
    published_at: datetime
    actor_id: UUID


class PublicWebsiteContent(BaseModel):
    key: WebsiteKey
    content: WebsiteContent
    published_at: datetime


class WebsiteAccess(BaseModel):
    can_edit: bool
    can_publish: bool


class WebsiteEditor(BaseModel):
    profile_id: UUID
    staff_code: str
    role: Literal["admin", "sub_admin"]
    enabled: bool


class WebsiteGrantWrite(BaseModel):
    enabled: bool
