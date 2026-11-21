"""CS-026: pincode reference data, profile pincode and "use my location".

Covers the seeded reference table (provenance checksum, idempotent loader,
read-only RLS), the lookup and nearest-pincode routes (validation, auth, role
and rate limits, nearest-centroid correctness against a brute-force scan) and
the privacy promise that a GPS position is never logged, stored or audited.

Requires: running Postgres + Redis with migrations applied.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import random
import re
from pathlib import Path

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient
from sqlalchemy import text

from app.api.v1 import pincodes as pincodes_router
from app.core.config import settings
from app.services import pincodes as pincode_service
from conftest import full_registration

API_ROOT = Path(__file__).resolve().parents[2]
SEED = API_ROOT / "app" / "data" / "pincodes.csv.gz"
SOURCES = API_ROOT / "app" / "data" / "SOURCES.md"
MIGRATION = (
    API_ROOT / "alembic" / "versions" / "e5a7c9b1d3f6_pincode_reference_and_profile_pincode.py"
)

# A distinctive position in Gachibowli, Hyderabad. Its digits must never
# appear in a log line, a Redis key or a stored row.
PROBE_LATITUDE = 17.44123
PROBE_LONGITUDE = 78.34871
PROBE_MARKERS = ("17.44123", "78.34871", "17.4412", "78.3487")


def _migration_module():
    spec = importlib.util.spec_from_file_location("pincode_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _scalar(sql: str, params: dict | None = None):
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        return (await db.execute(text(sql), params or {})).scalar()


async def _auth_user_uuid(mobile: str) -> str:
    return str(await _scalar("SELECT id FROM auth_users WHERE mobile = :m", {"m": mobile}))


async def _role_headers(mobile: str, role: str) -> dict[str, str]:
    from app.core.security import create_access_token

    uid = await _auth_user_uuid(mobile)
    token = create_access_token(
        {
            "sub": uid,
            "role": role,
            "business_line": "loans",
            "platform_scope": "true" if role in ("admin", "sub_admin") else "false",
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _client_headers(client: AsyncClient) -> tuple[dict[str, str], str]:
    token, mobile = await full_registration(client, lines=["loans"])
    return {"Authorization": f"Bearer {token}"}, mobile


# ---------------------------------------------------------------------------
# Reference data and provenance
# ---------------------------------------------------------------------------


def test_seed_checksum_matches_the_sources_record() -> None:
    digest = hashlib.sha256(SEED.read_bytes()).hexdigest()
    recorded = re.findall(r"`([0-9a-f]{64})`", SOURCES.read_text(encoding="utf-8"))
    assert digest in recorded, "pincodes.csv.gz changed: update app/data/SOURCES.md"
    assert "CC BY 4.0" in SOURCES.read_text(encoding="utf-8")


def test_seed_parses_one_valid_row_per_pincode() -> None:
    rows = _migration_module().read_seed()
    assert len(rows) == 19238
    pincodes = [row["pincode"] for row in rows]
    assert len(set(pincodes)) == len(pincodes)
    assert all(re.fullmatch(r"[1-9][0-9]{5}", p) for p in pincodes)
    assert all(
        6.0 <= row["latitude"] <= 37.6 and 68.0 <= row["longitude"] <= 97.6
        for row in rows
        if row["latitude"] is not None
    )


@pytest.mark.parametrize(
    "bad_line",
    [
        "012345,Area,District,State,17.1,78.1",
        "50001,Area,District,State,17.1,78.1",
        "500001,,District,State,17.1,78.1",
        "500001,Area,District,State,51.5,-0.1",
        "500001,Area,District,State,nan,78.1",
        "500001,Area,District,State,17.1,",
    ],
)
def test_seed_reader_rejects_malformed_rows(tmp_path: Path, bad_line: str) -> None:
    import gzip

    path = tmp_path / "bad.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("pincode,area,district,state,latitude,longitude\n")
        handle.write(bad_line + "\n")
    with pytest.raises(ValueError):
        _migration_module().read_seed(path)


@pytest.mark.asyncio
async def test_reference_table_is_seeded(client: AsyncClient) -> None:
    assert await _scalar("SELECT count(*) FROM pincodes") == 19238
    assert await _scalar("SELECT count(*) FROM pincodes WHERE latitude IS NULL") == 0
    assert await _scalar("SELECT district FROM pincodes WHERE pincode = '500001'") == "Hyderabad"


@pytest.mark.asyncio
async def test_seed_load_is_idempotent(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    module = _migration_module()
    async with _session_mod.AsyncSessionLocal() as db:
        original = (
            await db.execute(text("SELECT area FROM pincodes WHERE pincode = '110001'"))
        ).scalar()
        await db.execute(text("UPDATE pincodes SET area = 'Drifted' WHERE pincode = '110001'"))
        await db.commit()
        conn = await db.connection()
        loaded = await conn.run_sync(lambda sync_conn: module.load_pincodes(sync_conn))
        again = await conn.run_sync(lambda sync_conn: module.load_pincodes(sync_conn))
        await db.commit()
        assert loaded == again == 19238
        assert (await db.execute(text("SELECT count(*) FROM pincodes"))).scalar() == 19238
        restored = (
            await db.execute(text("SELECT area FROM pincodes WHERE pincode = '110001'"))
        ).scalar()
    assert restored == original == "New Delhi"


@pytest.mark.asyncio
async def test_api_user_reads_but_cannot_write_reference_data(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        assert (await db.execute(text("SELECT count(*) FROM pincodes"))).scalar() == 19238
        await db.rollback()
    for statement in (
        "UPDATE pincodes SET area = 'x' WHERE pincode = '110001'",
        "DELETE FROM pincodes WHERE pincode = '110001'",
        "INSERT INTO pincodes (pincode, area, district, state) VALUES ('999998', 'a', 'b', 'c')",
    ):
        async with _session_mod.AsyncSessionLocal() as db:
            await db.execute(text("SET LOCAL ROLE api_user"))
            with pytest.raises(Exception, match="permission denied"):
                await db.execute(text(statement))
            await db.rollback()


# ---------------------------------------------------------------------------
# GET /pincodes/{pincode}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_requires_sign_in(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/pincodes/500001")).status_code == 401


@pytest.mark.asyncio
async def test_lookup_returns_the_place_name(client: AsyncClient) -> None:
    headers, _ = await _client_headers(client)
    resp = await client.get("/api/v1/pincodes/110001", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "pincode": "110001",
        "area": "New Delhi",
        "district": "Central Delhi",
        "state": "Delhi",
    }
    assert resp.headers["cache-control"] == "private, max-age=86400"


@pytest.mark.asyncio
async def test_lookup_unknown_pincode_is_404(client: AsyncClient) -> None:
    headers, _ = await _client_headers(client)
    assert await _scalar("SELECT count(*) FROM pincodes WHERE pincode = '999999'") == 0
    resp = await client.get("/api/v1/pincodes/999999", headers=headers)
    assert resp.status_code == 404
    assert resp.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["012345", "50001", "5000011", "50a001", "abcdef"])
async def test_lookup_rejects_malformed_pincodes(client: AsyncClient, value: str) -> None:
    headers, _ = await _client_headers(client)
    assert (await client.get(f"/api/v1/pincodes/{value}", headers=headers)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agent", "telecaller", "employee", "sub_admin", "admin"])
async def test_every_signed_in_role_may_look_up(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_headers(mobile, role)
    assert (await client.get("/api/v1/pincodes/560001", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_lookup_budget(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pincodes_router, "PINCODE_LOOKUPS_PER_HOUR", 2)
    headers, _ = await _client_headers(client)
    for _ in range(2):
        assert (await client.get("/api/v1/pincodes/500001", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/pincodes/500001", headers=headers)).status_code == 429


# ---------------------------------------------------------------------------
# POST /pincodes/nearest
# ---------------------------------------------------------------------------


async def _all_centroids() -> list[tuple[str, float, float]]:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        rows = await db.execute(
            text("SELECT pincode, latitude, longitude FROM pincodes WHERE latitude IS NOT NULL")
        )
        return [(r[0], r[1], r[2]) for r in rows]


def _brute_force(
    centroids: list[tuple[str, float, float]], latitude: float, longitude: float
) -> str | None:
    distance, pincode = min(
        (pincode_service.distance_km((latitude, longitude), (lat, lon)), p)
        for p, lat, lon in centroids
    )
    return pincode if distance <= pincode_service.MAX_NEAREST_DISTANCE_KM else None


@pytest.mark.asyncio
async def test_nearest_requires_sign_in(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/pincodes/nearest", json={"latitude": 17.4, "longitude": 78.4})
    assert resp.status_code == 401


_FIXED_POSITIONS = [
    (28.6419, 77.2176),  # the New Delhi GPO centroid itself
    (19.0760, 72.8777),  # Mumbai
    (12.9716, 77.5946),  # Bengaluru
    (26.1445, 91.7362),  # Guwahati
    (34.1526, 77.5771),  # Leh (sparse)
    (11.6234, 92.7265),  # Port Blair
    (8.0883, 77.5385),  # Kanyakumari
    (23.0225, 72.5714),  # Ahmedabad
    (15.0, 69.0),  # Arabian Sea, inside the box: no pincode within 100 km
]


@pytest.mark.asyncio
async def test_nearest_matches_a_brute_force_scan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The grid prefilter returns exactly what a full Haversine scan returns."""
    import app.db.session as _session_mod

    centroids = await _all_centroids()
    pincode_service.reset_centroid_grid()
    async with _session_mod.AsyncSessionLocal() as db:
        grid = await pincode_service.centroid_grid(db)
    assert grid.size == len(centroids) == 19238

    rng = random.Random(20261117)
    positions = _FIXED_POSITIONS + [
        (rng.uniform(6.0, 37.6), rng.uniform(68.0, 97.6)) for _ in range(300)
    ]
    for latitude, longitude in positions:
        assert grid.nearest(latitude, longitude) == _brute_force(centroids, latitude, longitude), (
            latitude,
            longitude,
        )

    # And through the route, for the fixed positions.
    monkeypatch.setattr(pincodes_router, "NEAREST_LOOKUPS_PER_HOUR", 100)
    headers, _ = await _client_headers(client)
    for latitude, longitude in _FIXED_POSITIONS:
        expected = _brute_force(centroids, latitude, longitude)
        resp = await client.post(
            "/api/v1/pincodes/nearest",
            headers=headers,
            json={"latitude": latitude, "longitude": longitude},
        )
        assert resp.status_code == (200 if expected else 404), (latitude, longitude, resp.text)
        if expected:
            assert resp.json()["pincode"] == expected
    assert _brute_force(centroids, 28.6419, 77.2176) is not None
    assert _brute_force(centroids, 15.0, 69.0) is None


@pytest.mark.asyncio
async def test_nearest_returns_pincode_and_place_only(client: AsyncClient) -> None:
    headers, _ = await _client_headers(client)
    resp = await client.post(
        "/api/v1/pincodes/nearest",
        headers=headers,
        json={"latitude": 28.6419, "longitude": 77.2176},
    )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"pincode", "area", "district", "state"}
    assert resp.json()["state"] == "Delhi"
    assert resp.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_nearest_far_from_any_pincode_is_404(client: AsyncClient) -> None:
    """Inside the box but in the Arabian Sea: no credible pincode."""
    headers, _ = await _client_headers(client)
    resp = await client.post(
        "/api/v1/pincodes/nearest", headers=headers, json={"latitude": 15.0, "longitude": 69.0}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        '{"latitude": 51.5, "longitude": -0.12}',
        '{"latitude": 40.0, "longitude": 77.0}',
        '{"latitude": 5.9, "longitude": 77.0}',
        '{"latitude": 20.0, "longitude": 67.9}',
        '{"latitude": 20.0, "longitude": 97.7}',
        '{"latitude": NaN, "longitude": 77.0}',
        '{"latitude": 20.0, "longitude": Infinity}',
        '{"latitude": "x", "longitude": 77.0}',
        '{"latitude": 20.0}',
        '{"latitude": 20.0, "longitude": 77.0, "accuracy": 5}',
    ],
)
async def test_nearest_rejects_positions_outside_india(client: AsyncClient, body: str) -> None:
    headers, _ = await _client_headers(client)
    resp = await client.post(
        "/api/v1/pincodes/nearest",
        headers={**headers, "Content-Type": "application/json"},
        content=body,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["telecaller", "employee", "sub_admin"])
async def test_admin_managed_staff_cannot_use_location(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_headers(mobile, role)
    resp = await client.post(
        "/api/v1/pincodes/nearest", headers=headers, json={"latitude": 17.4, "longitude": 78.4}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agent", "admin"])
async def test_agents_and_admins_may_use_location(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_headers(mobile, role)
    resp = await client.post(
        "/api/v1/pincodes/nearest", headers=headers, json={"latitude": 17.4, "longitude": 78.4}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_nearest_budget(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pincodes_router, "NEAREST_LOOKUPS_PER_HOUR", 1)
    headers, _ = await _client_headers(client)
    body = {"latitude": 17.4, "longitude": 78.4}
    assert (
        await client.post("/api/v1/pincodes/nearest", headers=headers, json=body)
    ).status_code == 200
    assert (
        await client.post("/api/v1/pincodes/nearest", headers=headers, json=body)
    ).status_code == 429


@pytest.mark.asyncio
async def test_coordinates_are_never_logged_stored_or_audited(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    headers, mobile = await _client_headers(client)
    uid = await _auth_user_uuid(mobile)
    events_before = await _scalar(
        "SELECT count(*) FROM auth_events WHERE auth_user_uuid = :u", {"u": uid}
    )
    audit_before = await _scalar("SELECT count(*) FROM audit_log")
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        keys_before = {key async for key in redis_client.scan_iter(match=f"*{uid}*")}
    finally:
        await redis_client.aclose()

    caplog.set_level(logging.DEBUG)
    resp = await client.post(
        "/api/v1/pincodes/nearest",
        headers=headers,
        json={"latitude": PROBE_LATITUDE, "longitude": PROBE_LONGITUDE},
    )
    assert resp.status_code == 200, resp.text
    suggested = resp.json()["pincode"]

    # Logs (every logger, debug and up).
    for marker in PROBE_MARKERS:
        assert marker not in caplog.text
    # Audit and auth events: nothing new for this lookup, no coordinates anywhere.
    assert (
        await _scalar("SELECT count(*) FROM auth_events WHERE auth_user_uuid = :u", {"u": uid})
        == events_before
    )
    assert await _scalar("SELECT count(*) FROM audit_log") == audit_before
    for marker in PROBE_MARKERS:
        like = {"m": f"%{marker}%"}
        events = "SELECT count(*) FROM auth_events WHERE CAST(detail AS text) LIKE :m"
        audits = "SELECT count(*) FROM audit_log WHERE CAST(audit_log AS text) LIKE :m"
        assert await _scalar(events, like) == 0
        assert await _scalar(audits, like) == 0
    # Nothing written for the account: no profile pincode, no personalization row.
    assert await _scalar("SELECT pincode FROM auth_users WHERE id = :u", {"u": uid}) is None
    assert (
        await _scalar(
            "SELECT count(*) FROM personalization_preferences WHERE auth_user_uuid = :u",
            {"u": uid},
        )
        == 0
    )
    # Redis: only a counter keyed by the account id.
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        keys = {key async for key in redis_client.scan_iter(match=f"*{uid}*")} - keys_before
        assert keys == {f"pincode_nearest_rate:{uid}"}
        assert await redis_client.get(f"pincode_nearest_rate:{uid}") == "1"
        for marker in PROBE_MARKERS:
            assert [key async for key in redis_client.scan_iter(match=f"*{marker}*")] == []
    finally:
        await redis_client.aclose()

    # Saving is a separate, explicit profile edit; only the pincode is kept.
    saved = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Gps", "last_name": "User", "pincode": suggested},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["pincode"] == suggested


# ---------------------------------------------------------------------------
# Profile pincode (PATCH/GET /auth/me)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_pincode_saves_with_derived_place_and_clears(client: AsyncClient) -> None:
    headers, _ = await _client_headers(client)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["pincode"] is None and me.json()["place"] is None

    saved = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "pincode": " 500001 "},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["pincode"] == "500001"
    assert saved.json()["place"] == {
        "pincode": "500001",
        "area": "Hyderabad",
        "district": "Hyderabad",
        "state": "Telangana",
    }

    kept = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"first_name": "Aarav", "last_name": "Sharma"}
    )
    assert kept.json()["pincode"] == "500001"

    cleared = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "pincode": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["pincode"] is None and cleared.json()["place"] is None


@pytest.mark.asyncio
async def test_unlisted_but_valid_pincode_is_kept_without_a_place(client: AsyncClient) -> None:
    headers, _ = await _client_headers(client)
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "pincode": "999999"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pincode"] == "999999"
    assert resp.json()["place"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["012345", "50001", "5000011", "50a001", "", "      ", 500001])
async def test_profile_pincode_validation(client: AsyncClient, value: object) -> None:
    headers, _ = await _client_headers(client)
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "pincode": value},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_database_rejects_a_malformed_profile_pincode(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    _, mobile = await full_registration(client, lines=["loans"])
    async with _session_mod.AsyncSessionLocal() as db:
        with pytest.raises(Exception, match="profile_pincode_valid"):
            await db.execute(
                text("UPDATE auth_users SET pincode = '012345' WHERE mobile = :m"), {"m": mobile}
            )
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["telecaller", "employee", "sub_admin"])
async def test_admin_managed_staff_cannot_set_a_pincode(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_headers(mobile, role)
    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Staff", "last_name": "Member", "pincode": "500001"},
    )
    assert resp.status_code == 403
    uid = await _auth_user_uuid(mobile)
    assert await _scalar("SELECT pincode FROM auth_users WHERE id = :u", {"u": uid}) is None
