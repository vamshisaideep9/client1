"""Closed contracts for authenticated marketing personalization.

Audience rules remain JSONB on the CMS tables, but they are never arbitrary
JSON: every authoring and serving path parses this module's versioned grammar.
Unknown keys and invalid role/signal combinations fail closed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.banner import BannerType
from app.schemas.pincodes import PincodeValue

UserType = Literal["client", "agent", "employee", "telecaller"]
ClientJourneyStage = Literal[
    "not_started",
    "in_progress",
    "on_hold",
    "completed",
    "rejected",
    "closed",
]
AgentSignal = Literal[
    "no_leads",
    "has_active_leads",
    "has_converted_leads",
    "has_pending_commission",
    "has_paid_commission",
]


class AudienceLocationCircle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(ge=5, le=500)


PlaceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

MAX_PINCODE_TARGETS = 100
MAX_CITY_TARGETS = 50


class AudienceCity(BaseModel):
    """A city target: a district and its state from the pincode reference list."""

    model_config = ConfigDict(extra="forbid")

    district: PlaceName
    state: PlaceName


class AudienceRules(BaseModel):
    """Versioned rule grammar (version 1, and version 2 since CS-026).

    Populated dimensions are ANDed. Values within one dimension are ORed.
    Circles (`locations`), `pincodes` and `cities` together form one "where"
    dimension: a match on any of them counts. `pincodes` and `cities` exist
    only in version 2 and target Clients only. An empty object is the
    canonical generic-content representation.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1, 2] = 1
    user_types: list[UserType] = Field(default_factory=list, max_length=4)
    client_journey_stages: list[ClientJourneyStage] = Field(default_factory=list, max_length=6)
    agent_signals: list[AgentSignal] = Field(default_factory=list, max_length=5)
    locations: list[AudienceLocationCircle] = Field(default_factory=list, max_length=10)
    pincodes: list[PincodeValue] = Field(default_factory=list, max_length=MAX_PINCODE_TARGETS)
    cities: list[AudienceCity] = Field(default_factory=list, max_length=MAX_CITY_TARGETS)

    @model_validator(mode="before")
    @classmethod
    def populated_rules_require_explicit_version(cls, data: object) -> object:
        # `{}` is the canonical generic/public representation. Every targeted
        # rule must identify its grammar version explicitly so a legacy object
        # is never silently reinterpreted under version one.
        if isinstance(data, dict) and data and "version" not in data:
            raise ValueError("Targeted audience rules require an explicit version.")
        return data

    @field_validator("user_types", "client_journey_stages", "agent_signals", "pincodes")
    @classmethod
    def values_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Audience rule values must be unique.")
        return values

    @field_validator("cities")
    @classmethod
    def cities_are_unique(cls, values: list[AudienceCity]) -> list[AudienceCity]:
        keys = {(city.district.casefold(), city.state.casefold()) for city in values}
        if len(keys) != len(values):
            raise ValueError("Audience rule values must be unique.")
        return values

    @model_validator(mode="after")
    def role_dimensions_are_consistent(self) -> AudienceRules:
        if self.version == 1 and (self.pincodes or self.cities):
            raise ValueError("Pincode and city targets need audience rules version 2.")
        if self.client_journey_stages and self.user_types != ["client"]:
            raise ValueError("Client journey stages require a Client-only audience.")
        if self.agent_signals and self.user_types != ["agent"]:
            raise ValueError("Agent signals require an Agent-only audience.")
        if self.client_journey_stages and self.agent_signals:
            raise ValueError("Client journey and Agent activity cannot be combined.")
        if (self.pincodes or self.cities) and self.user_types != ["client"]:
            # Only Clients can consent to personalization (CS-021), so a place
            # target could never reach any other role.
            raise ValueError("Pincode and city targets require a Client-only audience.")
        if (
            self.client_journey_stages or self.agent_signals or self.has_location_targets
        ) and not self.user_types:
            raise ValueError("Audience signals require at least one user type.")
        return self

    @property
    def has_location_targets(self) -> bool:
        return bool(self.locations or self.pincodes or self.cities)

    @property
    def is_empty(self) -> bool:
        return not (
            self.user_types
            or self.client_journey_stages
            or self.agent_signals
            or self.has_location_targets
        )


def audience_rules_to_storage(rules: AudienceRules) -> dict:
    """Keep generic rows as exactly `{}` so the public allowlist is simple.

    The stored version is the lowest one that can express the rule, so a rule
    without pincode or city targets stays byte-identical to version one.
    """
    if rules.is_empty:
        return {}
    data = rules.model_dump(mode="json", exclude_defaults=True)
    data["version"] = 2 if (rules.pincodes or rules.cities) else 1
    return data


def audience_rules_valid_for_banner(banner_type: BannerType, rules: AudienceRules) -> bool:
    if banner_type == BannerType.PERSONALIZED:
        return bool(rules.user_types)
    return rules.is_empty


def audience_rules_valid_for_offer(rules: AudienceRules) -> bool:
    """Every coupon campaign names at least one authenticated dashboard role."""
    return bool(rules.user_types)


class PersonalizationPreferenceRead(BaseModel):
    personalization_enabled: bool
    location_enabled: bool
    location_captured_at: datetime | None


class PersonalizationPreferenceUpdate(BaseModel):
    personalization_enabled: bool


class LocationCaptureRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AuthenticatedBannerRead(BaseModel):
    id: UUID
    banner_type: BannerType
    title: str
    subtitle: str | None
    cta_label: str | None
    deep_link: str | None
    image_url: str | None


class AuthenticatedOfferRead(BaseModel):
    id: UUID
    title: str
    description: str | None
    discount_type: str
    discount_value: Decimal
    code: str | None
    partner_name: str
    redemption_url: str
    terms_summary: str
    terms_url: str | None
    image_url: str


class AuthenticatedPlacementResponse(BaseModel):
    banners: list[AuthenticatedBannerRead]
    offers: list[AuthenticatedOfferRead]
