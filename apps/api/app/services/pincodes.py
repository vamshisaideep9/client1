"""Pincode place names and nearest-pincode lookup (CS-026).

Reads only the non-personal ``pincodes`` reference table. The nearest-pincode
lookup receives a one-time device position. It is matched in this process
against an in-memory grid of pincode centroids, so the position (or a box
derived from it) never reaches the database, a log line, an audit row, Redis
or a table; it is dropped when the request ends.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pincode import Pincode
from app.schemas.personalization import AudienceCity, AudienceRules, audience_rules_to_storage

EARTH_RADIUS_KM = 6371.0088
# Search radii (km). Pincode centroids are typically 5-20 km apart; sparse
# regions need the wider passes. Past the last radius there is no credible
# match (the position is probably outside India), so none is returned.
NEAREST_SEARCH_RADII_KM = (15.0, 40.0, 100.0)
MAX_NEAREST_DISTANCE_KM = NEAREST_SEARCH_RADII_KM[-1]
_KM_PER_DEGREE_LATITUDE = 111.32
_CELL_DEGREES = 0.5


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Great-circle (Haversine) distance between two (latitude, longitude) points."""
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(min(1.0, math.sqrt(value)))


async def get_place(db: AsyncSession, pincode: str) -> Pincode | None:
    return await db.get(Pincode, pincode)


async def list_districts(db: AsyncSession) -> list[tuple[str, str]]:
    """Every (district, state) pair on the list: the cities a campaign can target."""
    rows = (await db.execute(select(Pincode.district, Pincode.state).distinct())).all()
    # Sorted here rather than by the database collation so the order is the
    # same in every environment.
    return sorted(
        ((district, state) for district, state in rows),
        key=lambda row: (row[1].casefold(), row[0].casefold()),
    )


class UnknownAudiencePlaces(ValueError):
    """A campaign targets a pincode or city that is not on the reference list."""


async def canonical_audience_places(db: AsyncSession, rules: AudienceRules) -> AudienceRules:
    """Check every pincode and city target exists; return cities in list spelling.

    Matching compares cities case-insensitively, but storing the reference
    spelling keeps campaign forms and previews consistent.
    """
    if not (rules.pincodes or rules.cities):
        return rules
    problems: list[str] = []
    if rules.pincodes:
        known = set(
            (
                await db.scalars(select(Pincode.pincode).where(Pincode.pincode.in_(rules.pincodes)))
            ).all()
        )
        missing = [pincode for pincode in rules.pincodes if pincode not in known]
        if missing:
            problems.append("pincodes not on the list: " + ", ".join(missing))
    cities: list[AudienceCity] = []
    for city in rules.cities:
        row = (
            await db.execute(
                select(Pincode.district, Pincode.state)
                .where(
                    func.lower(Pincode.district) == city.district.lower(),
                    func.lower(Pincode.state) == city.state.lower(),
                )
                .limit(1)
            )
        ).first()
        if row is None:
            problems.append(f"city not on the list: {city.district}, {city.state}")
        else:
            cities.append(AudienceCity(district=row[0], state=row[1]))
    if problems:
        raise UnknownAudiencePlaces("; ".join(problems))
    return rules.model_copy(update={"cities": cities})


async def audience_rules_for_storage(db: AsyncSession, rules: AudienceRules) -> dict:
    """Validate place targets against the list, then the canonical JSONB value."""
    return audience_rules_to_storage(await canonical_audience_places(db, rules))


@dataclass(frozen=True)
class _Centroid:
    pincode: str
    latitude: float
    longitude: float


class CentroidGrid:
    """Pincode centroids bucketed into 0.5 degree cells (a bounding-box index)."""

    def __init__(self, centroids: list[_Centroid]) -> None:
        self._cells: dict[tuple[int, int], list[_Centroid]] = defaultdict(list)
        for centroid in centroids:
            self._cells[self._cell(centroid.latitude, centroid.longitude)].append(centroid)
        self.size = len(centroids)

    @staticmethod
    def _cell(latitude: float, longitude: float) -> tuple[int, int]:
        return math.floor(latitude / _CELL_DEGREES), math.floor(longitude / _CELL_DEGREES)

    def _within_box(self, latitude: float, longitude: float, radius_km: float) -> list[_Centroid]:
        lat_delta = radius_km / _KM_PER_DEGREE_LATITUDE
        # Longitude degrees shrink with latitude; India stays far from the poles.
        lon_delta = radius_km / (
            _KM_PER_DEGREE_LATITUDE * max(math.cos(math.radians(latitude)), 0.1)
        )
        low = self._cell(latitude - lat_delta, longitude - lon_delta)
        high = self._cell(latitude + lat_delta, longitude + lon_delta)
        found: list[_Centroid] = []
        for row in range(low[0], high[0] + 1):
            for column in range(low[1], high[1] + 1):
                found.extend(self._cells.get((row, column), ()))
        return found

    def nearest(self, latitude: float, longitude: float) -> str | None:
        """The pincode whose centroid is closest, if one is within 100 km.

        Each pass ranks only the centroids in the cells covering a bounding box
        around the position. A candidate is accepted only when it lies within
        that pass's radius; otherwise a centroid just outside the box could be
        closer, so the next pass widens it. Ties break on the pincode so the
        answer is deterministic.
        """
        origin = (latitude, longitude)
        for radius in NEAREST_SEARCH_RADII_KM:
            candidates = self._within_box(latitude, longitude, radius)
            if not candidates:
                continue
            distance, pincode = min(
                (distance_km(origin, (c.latitude, c.longitude)), c.pincode) for c in candidates
            )
            if distance <= radius:
                return pincode
        return None


_grid: CentroidGrid | None = None


async def centroid_grid(db: AsyncSession) -> CentroidGrid:
    """Load the centroid grid once per process (the table changes only by migration).

    Two concurrent first requests may both load it; the second simply replaces
    the first with an identical grid, so no lock is needed.
    """
    global _grid
    if _grid is None:
        rows = (
            await db.execute(
                select(Pincode.pincode, Pincode.latitude, Pincode.longitude).where(
                    Pincode.latitude.is_not(None), Pincode.longitude.is_not(None)
                )
            )
        ).all()
        _grid = CentroidGrid([_Centroid(p, lat, lon) for p, lat, lon in rows])
    return _grid


def reset_centroid_grid() -> None:
    """Drop the cached grid (tests, or after a reference refresh in-process)."""
    global _grid
    _grid = None


async def nearest_pincode(db: AsyncSession, latitude: float, longitude: float) -> Pincode | None:
    grid = await centroid_grid(db)
    if grid.size == 0:
        # An empty table is never cached as the answer for the process.
        reset_centroid_grid()
        return None
    pincode = grid.nearest(latitude, longitude)
    return await get_place(db, pincode) if pincode is not None else None
