"""India pincode reference table and the profile pincode (CS-026).

Revision ID: e5a7c9b1d3f6
Revises: d4f6a8c0e2b4

2026-11-17 product decision (CS-026, batch F of the stakeholder feedback;
amends CS-005/CS-008's "no browser geolocation"): a profile carries an
optional six-digit pincode, its place name (area, district, state) comes from
a built-in reference list rather than free text, and a one-time GPS position
can be mapped to the nearest pincode on the server. Coordinates are never
stored; only the pincode the person then saves.

``pincodes`` is non-personal reference data: one row per pincode with an area
name, district, state and the centroid of its offices' coordinates. It is
seeded here from ``app/data/pincodes.csv.gz`` (GeoNames, CC BY 4.0; source,
licence, attribution and the normalisation are recorded in
``app/data/SOURCES.md``). The loader validates every row and fails the
migration on anything malformed. It is an idempotent upsert, so a later
refresh migration can re-run it against an updated file.

Access (``api_user``): RLS enabled and forced, one ``SELECT USING (true)``
policy (any signed-in caller may read reference data, as with ``loan_types``),
SELECT grant only; no write grant, so only migrations change it.

``auth_users.pincode`` is nullable, CHECK-constrained to a valid Indian pincode
format (six digits, first digit 1-9) and deliberately has no foreign key: a
genuine pincode missing from the reference list is still accepted, it just has
no place name. It sits under the existing ``auth_users_rls`` owner policy and
is cleared with the other optional profile fields on account deletion.

Rollback drops the column and the table; saved profile pincodes are lost.
"""

from __future__ import annotations

import csv
import gzip
import math
import re
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision: str = "e5a7c9b1d3f6"
down_revision: str | Sequence[str] | None = "d4f6a8c0e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "pincodes.csv.gz"
SEED_COLUMNS = ["pincode", "area", "district", "state", "latitude", "longitude"]
_PINCODE = re.compile(r"[1-9][0-9]{5}")
_PINCODE_SQL = "'^[1-9][0-9]{5}$'"
# India's bounding box, shared with the API's coordinate validation.
_LAT = (6.0, 37.6)
_LON = (68.0, 97.6)
_LIMITS = {"area": 120, "district": 80, "state": 80}
_BATCH = 2000

_UPSERT = sa.text(
    "INSERT INTO pincodes (pincode, area, district, state, latitude, longitude) "
    "VALUES (:pincode, :area, :district, :state, :latitude, :longitude) "
    "ON CONFLICT (pincode) DO UPDATE SET "
    "area = EXCLUDED.area, district = EXCLUDED.district, state = EXCLUDED.state, "
    "latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude "
    "WHERE (pincodes.area, pincodes.district, pincodes.state, pincodes.latitude, "
    "pincodes.longitude) IS DISTINCT FROM (EXCLUDED.area, EXCLUDED.district, "
    "EXCLUDED.state, EXCLUDED.latitude, EXCLUDED.longitude)"
)


def _coordinate(raw: str, bounds: tuple[float, float], pincode: str) -> float:
    value = float(raw)
    if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
        raise ValueError(f"pincode seed row {pincode}: coordinate outside India")
    return value


def read_seed(path: Path = SEED_PATH) -> list[dict[str, object]]:
    """Parse and validate the committed seed; any malformed row aborts."""
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SEED_COLUMNS:
            raise ValueError("pincode seed: unexpected header")
        for record in reader:
            pincode = record["pincode"] or ""
            if not _PINCODE.fullmatch(pincode) or pincode in seen:
                raise ValueError(f"pincode seed: invalid or duplicate pincode {pincode!r}")
            seen.add(pincode)
            row: dict[str, object] = {"pincode": pincode}
            for column, limit in _LIMITS.items():
                value = (record[column] or "").strip()
                if not value or len(value) > limit:
                    raise ValueError(f"pincode seed row {pincode}: bad {column}")
                row[column] = value
            latitude, longitude = record["latitude"] or "", record["longitude"] or ""
            if latitude == "" and longitude == "":
                row["latitude"] = row["longitude"] = None
            else:
                row["latitude"] = _coordinate(latitude, _LAT, pincode)
                row["longitude"] = _coordinate(longitude, _LON, pincode)
            rows.append(row)
    if len(rows) < 15000:
        raise ValueError(f"pincode seed: only {len(rows)} rows")
    return rows


def load_pincodes(connection: sa.engine.Connection, path: Path = SEED_PATH) -> int:
    """Upsert every seed row; re-running leaves the table unchanged."""
    rows = read_seed(path)
    for start in range(0, len(rows), _BATCH):
        connection.execute(_UPSERT, rows[start : start + _BATCH])
    return len(rows)


def upgrade() -> None:
    op.create_table(
        "pincodes",
        sa.Column("pincode", sa.String(length=6), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=False),
        sa.Column("district", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("pincode", name=op.f("pk_pincodes")),
        sa.CheckConstraint(f"pincode ~ {_PINCODE_SQL}", name=op.f("ck_pincodes_pincode_valid")),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            f"(latitude BETWEEN {_LAT[0]} AND {_LAT[1]} "
            f"AND longitude BETWEEN {_LON[0]} AND {_LON[1]})",
            name=op.f("ck_pincodes_centroid_in_india"),
        ),
    )
    op.create_index("ix_pincodes_state_district", "pincodes", ["state", "district"])
    op.create_index("ix_pincodes_latitude_longitude", "pincodes", ["latitude", "longitude"])

    op.execute("GRANT SELECT ON pincodes TO api_user")
    op.execute("ALTER TABLE pincodes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pincodes FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY pincodes_read ON pincodes FOR SELECT USING (true)")

    load_pincodes(op.get_bind())

    op.add_column("auth_users", sa.Column("pincode", sa.String(length=6), nullable=True))
    op.create_check_constraint(
        op.f("ck_auth_users_profile_pincode_valid"),
        "auth_users",
        f"pincode IS NULL OR pincode ~ {_PINCODE_SQL}",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_auth_users_profile_pincode_valid"), "auth_users", type_="check")
    op.drop_column("auth_users", "pincode")

    op.execute("DROP POLICY IF EXISTS pincodes_read ON pincodes")
    op.execute("REVOKE SELECT ON pincodes FROM api_user")
    op.drop_index("ix_pincodes_latitude_longitude", table_name="pincodes")
    op.drop_index("ix_pincodes_state_district", table_name="pincodes")
    op.drop_table("pincodes")
