"""Property schemas — read-only real-estate listing catalog.

Enums are imported from the model so the values are a single source of truth
and land in the OpenAPI contract (the frontend consumes them as typed unions).
Authoring uses the separate submission schemas; this module keeps the
authenticated and anonymous read surfaces explicit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.property import (
    ConstructionStatus,
    Furnishing,
    ListingIntent,
    PropertyCategory,
    PropertySubtype,
    ReraApplicability,
    ReraVerificationStatus,
)
from app.schemas.listing_links import StoredListingLinks
from app.schemas.property_details import PropertyStructuredDetails, SaleType


class PropertyMediaRead(BaseModel):
    kind: Literal["image", "panorama"]
    url: str
    content_type: str


class PropertyRead(BaseModel):
    id: UUID
    listing_intent: ListingIntent
    title: str
    type: str
    location: str
    developer_name: str | None = None
    price_display: str
    price_paise: int
    security_deposit_paise: int | None
    minimum_lease_months: int | None
    available_from: date | None
    listing_links: StoredListingLinks
    meta: str | None
    image: str | None
    media_urls: list[str] = Field(default_factory=list)
    media: list[PropertyMediaRead] = Field(default_factory=list)
    category: PropertyCategory
    property_subtype: PropertySubtype | None
    city: str
    locality: str
    state: str | None
    pincode: str
    bhk: int
    area_sqft: int
    furnishing: Furnishing | None
    construction_status: ConstructionStatus | None
    amenities: list[str]
    age_years: int
    rera_applicability: ReraApplicability
    rera_number: str | None
    rera_verification_status: ReraVerificationStatus
    structured_details: PropertyStructuredDetails | None
    active: bool
    created_at: datetime


class PropertyListResponse(BaseModel):
    properties: list[PropertyRead]


class AdminPropertyStatusUpdate(BaseModel):
    active: bool
    reason: str = Field(min_length=1, max_length=1000)


class PublicPropertySearch(BaseModel):
    mode: Literal["sale", "resale", "rent"] | None = None
    location: str | None = Field(default=None, max_length=120)
    property_type: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_]+$")
    budget_min: int | None = Field(default=None, ge=0, le=10**12)
    budget_max: int | None = Field(default=None, ge=0, le=10**12)
    area_min: int | None = Field(default=None, ge=1, le=10**9)
    area_max: int | None = Field(default=None, ge=1, le=10**9)
    bhk: Literal["1", "2", "2.5", "3", "3.5", "4", "5+"] | None = None
    page: int = Field(default=1, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_ranges(self):
        if (self.budget_min is not None or self.budget_max is not None) and not self.mode:
            raise ValueError("Choose sale, resale, or rent / lease before filtering by budget.")
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("The maximum budget must be at least the minimum.")
        if (
            self.area_min is not None
            and self.area_max is not None
            and self.area_min > self.area_max
        ):
            raise ValueError("The maximum area must be at least the minimum.")
        return self


class PropertyCatalogTypeWrite(BaseModel):
    label: str = Field(min_length=1, max_length=40, pattern=r"^\S(?:.*\S)?$")
    form_subtype: PropertySubtype


class PropertyCatalogTypeUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=40, pattern=r"^\S(?:.*\S)?$")
    active: bool


class PropertyCatalogTypeRead(PropertyCatalogTypeWrite):
    code: str
    active: bool


class PublicPropertyRead(BaseModel):
    """Anonymous-read shape (docs/specs/public-property-catalog.md).

    Deliberately NOT PropertyRead: a separate schema means a future sensitive
    column added to the authenticated read can never silently surface here.
    Excludes the dashboard's entire filter-facet vocabulary (price_paise, bhk,
    area_sqft, furnishing, construction_status, amenities, age_years, pincode,
    city, locality) and internal metadata (active, created_at). `rera_number`
    is included only after Admin verification; exemption-verified listings have
    no public registration number.

    ``listing_intent`` is included because the Rent/Sale badge is card-level
    information; the rent terms behind it stay on the detail shape.
    """

    id: UUID
    listing_intent: ListingIntent
    title: str
    type: str
    location: str
    developer_name: str | None = None
    price_display: str
    meta: str | None
    image: str | None
    media_urls: list[str] = Field(default_factory=list)
    media: list[PropertyMediaRead] = Field(default_factory=list)
    category: PropertyCategory
    property_subtype: PropertySubtype | None
    catalog_type_code: str | None = None
    sale_classification: SaleType | None = None
    rera_number: str | None
    rera_verification_status: ReraVerificationStatus
    structured_details: PropertyStructuredDetails | None


class PublicPropertyListResponse(BaseModel):
    properties: list[PublicPropertyRead]


class PublicPropertySearchResponse(PublicPropertyListResponse):
    page: int
    total: int
    page_size: int


class PublicPropertyDetailRead(BaseModel):
    """Anonymous detail shape for one Admin-published property.

    This remains deliberately separate from ``PropertyRead``. The detail page
    exposes useful buyer facets, but never internal publication state, exact
    minor-unit pricing, reviewer identity, or timestamps.

    The deposit therefore ships as a rendered ``security_deposit_display``
    string, derived the same way ``price_display`` is, rather than as paise.
    """

    id: UUID
    listing_intent: ListingIntent
    title: str
    type: str
    location: str
    developer_name: str | None = None
    price_display: str
    security_deposit_display: str | None = None
    minimum_lease_months: int | None
    available_from: date | None
    listing_links: StoredListingLinks
    meta: str | None
    image: str | None
    media_urls: list[str] = Field(default_factory=list)
    media: list[PropertyMediaRead] = Field(default_factory=list)
    category: PropertyCategory
    property_subtype: PropertySubtype | None
    catalog_type_code: str | None = None
    sale_classification: SaleType | None = None
    city: str
    locality: str
    state: str | None
    pincode: str
    bhk: int
    area_sqft: int
    furnishing: Furnishing | None
    construction_status: ConstructionStatus | None
    amenities: list[str]
    age_years: int
    rera_applicability: ReraApplicability
    rera_number: str | None
    rera_verification_status: ReraVerificationStatus
    structured_details: PropertyStructuredDetails | None
