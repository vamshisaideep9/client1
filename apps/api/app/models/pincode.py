"""India pincode reference data (CS-026).

Read-only to the API: one row per pincode with its area, district, state and
the centroid of its offices. Seeded by migration ``e5a7c9b1d3f6`` from
``app/data/pincodes.csv.gz`` (GeoNames, CC BY 4.0; see ``app/data/SOURCES.md``).
No personal data lives here.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Pincode(Base):
    __tablename__ = "pincodes"
    __table_args__ = (
        CheckConstraint("pincode ~ '^[1-9][0-9]{5}$'", name="pincode_valid"),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude BETWEEN 6.0 AND 37.6 AND longitude BETWEEN 68.0 AND 97.6)",
            name="centroid_in_india",
        ),
        Index("ix_pincodes_state_district", "state", "district"),
        Index("ix_pincodes_latitude_longitude", "latitude", "longitude"),
    )

    pincode: Mapped[str] = mapped_column(String(6), primary_key=True)
    area: Mapped[str] = mapped_column(String(120), nullable=False)
    district: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(80), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
