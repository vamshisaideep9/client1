"""Pincode lookup contracts (CS-026).

A place is the non-personal reference row for a pincode. The nearest-pincode
request carries a one-time GPS position; it is validated against India's
bounding box, used for a single lookup and never stored, logged or audited.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# Indian pincodes are six digits and never start with 0 (matches the CHECK on
# auth_users.pincode and pincodes.pincode).
PINCODE_PATTERN = r"^[1-9][0-9]{5}$"

# India's bounding box (mainland, Andaman & Nicobar, Lakshadweep, Ladakh). It
# matches the reference table's CHECK and the seed loader.
INDIA_LATITUDE = (6.0, 37.6)
INDIA_LONGITUDE = (68.0, 97.6)

PincodeValue = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PINCODE_PATTERN)]


class PincodePlaceRead(BaseModel):
    """Place name for a pincode: area, district (treated as the city) and state."""

    pincode: str
    area: str
    district: str
    state: str


class PincodeDistrictRead(BaseModel):
    """A city for campaign targeting: a district and its state."""

    district: str
    state: str


class NearestPincodeRequest(BaseModel):
    """A one-time device position. Used for one lookup, then discarded."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def non_finite_numbers_are_missing(cls, data: object) -> object:
        # Python's JSON parser accepts NaN/Infinity. Left in place they would
        # be echoed in the 422 body, which cannot be serialised (a 500). Treat
        # them as absent so the request fails validation cleanly.
        if isinstance(data, dict):
            return {
                key: None if isinstance(value, float) and not math.isfinite(value) else value
                for key, value in data.items()
            }
        return data

    latitude: float = Field(ge=INDIA_LATITUDE[0], le=INDIA_LATITUDE[1], allow_inf_nan=False)
    longitude: float = Field(ge=INDIA_LONGITUDE[0], le=INDIA_LONGITUDE[1], allow_inf_nan=False)
