"""CS-026: audience rules version 2 (pincode and city targets).

Version-one rules keep parsing, storing and matching exactly as before.
Version two adds `pincodes` and `cities` (district + state from the reference
list). Circles, pincodes and cities form one "where" dimension. Location
matching uses the Client's profile pincode (its centroid for circles) and only
while the Client has consented; the profile pincode wins over the legacy
coarse point.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select, text

from app.core.security import create_access_token
from app.models.offer import Offer, OfferStatus
from app.models.personalization import PersonalizationPreference
from app.schemas.personalization import AudienceRules, audience_rules_to_storage
from app.services.personalization import AudienceContext, matches_audience
from conftest import full_registration

HYDERABAD = {"district": "Hyderabad", "state": "Telangana"}

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_version_one_rules_parse_and_store_unchanged() -> None:
    raw = {
        "version": 1,
        "user_types": ["client"],
        "client_journey_stages": ["not_started"],
        "locations": [{"label": "Hyd", "latitude": 17.39, "longitude": 78.49, "radius_km": 20}],
    }
    rules = AudienceRules.model_validate(raw)
    assert rules.version == 1
    assert rules.pincodes == [] and rules.cities == []
    assert audience_rules_to_storage(rules) == raw
    assert audience_rules_to_storage(AudienceRules()) == {}


def test_version_two_round_trips_and_stores_the_minimum_version() -> None:
    rules = AudienceRules.model_validate(
        {"version": 2, "user_types": ["client"], "pincodes": ["500001"], "cities": [HYDERABAD]}
    )
    assert audience_rules_to_storage(rules) == {
        "version": 2,
        "user_types": ["client"],
        "pincodes": ["500001"],
        "cities": [HYDERABAD],
    }
    # Version two without its new targets is stored as version one.
    plain = AudienceRules.model_validate({"version": 2, "user_types": ["agent"]})
    assert audience_rules_to_storage(plain) == {"version": 1, "user_types": ["agent"]}


@pytest.mark.parametrize(
    "raw",
    [
        {"version": 1, "user_types": ["client"], "pincodes": ["500001"]},
        {"version": 1, "user_types": ["client"], "cities": [HYDERABAD]},
        {"version": 2, "user_types": ["agent"], "pincodes": ["500001"]},
        {"version": 2, "user_types": ["client", "agent"], "cities": [HYDERABAD]},
        {"version": 2, "pincodes": ["500001"]},
        {"version": 2, "user_types": ["client"], "pincodes": ["012345"]},
        {"version": 2, "user_types": ["client"], "pincodes": ["500001", "500001"]},
        {
            "version": 2,
            "user_types": ["client"],
            "cities": [HYDERABAD, {"district": "hyderabad", "state": "TELANGANA"}],
        },
        {"version": 2, "user_types": ["client"], "cities": [{"district": " ", "state": "X"}]},
        {"version": 2, "user_types": ["client"], "cities": [{**HYDERABAD, "extra": 1}]},
        {"version": 3, "user_types": ["client"]},
        {"user_types": ["client"], "pincodes": ["500001"]},
    ],
)
def test_invalid_rules_fail_closed(raw: dict) -> None:
    with pytest.raises(ValidationError):
        AudienceRules.model_validate(raw)


def test_target_list_caps() -> None:
    too_many = [f"5000{n:02d}" for n in range(1, 102)]
    with pytest.raises(ValidationError):
        AudienceRules.model_validate({"version": 2, "user_types": ["client"], "pincodes": too_many})


# ---------------------------------------------------------------------------
# Matching (pure)
# ---------------------------------------------------------------------------


def _client(**overrides) -> AudienceContext:
    values = {"role": "client", "business_line": "loans", "personalization_enabled": True}
    values.update(overrides)
    return AudienceContext(**values)


def _rules(**overrides) -> AudienceRules:
    return AudienceRules.model_validate({"version": 2, "user_types": ["client"], **overrides})


def test_pincode_and_city_targets_match_the_profile_place() -> None:
    context = _client(pincode="500001", city=("hyderabad", "telangana"), location=(17.3862, 78.462))
    assert matches_audience(_rules(pincodes=["500001"]), context)
    assert not matches_audience(_rules(pincodes=["400001"]), context)
    assert matches_audience(_rules(cities=[HYDERABAD]), context)
    assert not matches_audience(
        _rules(cities=[{"district": "Mumbai", "state": "Maharashtra"}]), context
    )
    # Same district name in another state is a different city.
    assert not matches_audience(
        _rules(cities=[{"district": "Hyderabad", "state": "Sindh"}]), context
    )


def test_location_targets_are_one_dimension() -> None:
    context = _client(pincode="500001", city=("hyderabad", "telangana"), location=(17.38, 78.46))
    far_circle = {"label": "Mumbai", "latitude": 19.07, "longitude": 72.87, "radius_km": 20}
    assert matches_audience(
        _rules(pincodes=["400001"], locations=[far_circle], cities=[HYDERABAD]), context
    )
    assert not matches_audience(_rules(pincodes=["400001"], locations=[far_circle]), context)


def test_location_needs_consent_and_a_profile_place() -> None:
    rules = _rules(pincodes=["500001"])
    assert not matches_audience(rules, _client(personalization_enabled=False, pincode="500001"))
    assert not matches_audience(rules, _client(pincode=None))
    # Other dimensions still AND with the place.
    staged = _rules(pincodes=["500001"], client_journey_stages=["in_progress"])
    assert not matches_audience(staged, _client(pincode="500001"))
    assert matches_audience(
        staged, _client(pincode="500001", client_journey_stages=frozenset({"in_progress"}))
    )


def test_version_one_matching_is_unchanged() -> None:
    circle = {"label": "Hyd", "latitude": 17.39, "longitude": 78.49, "radius_km": 20}
    rules = AudienceRules.model_validate(
        {"version": 1, "user_types": ["client"], "locations": [circle]}
    )
    assert matches_audience(rules, _client(location=(17.40, 78.48)))
    assert not matches_audience(rules, _client(location=(19.07, 72.87)))
    assert not matches_audience(rules, _client(location=None))
    assert not matches_audience(
        rules, _client(personalization_enabled=False, location=(17.4, 78.48))
    )
    role_only = AudienceRules.model_validate({"version": 1, "user_types": ["agent"]})
    assert matches_audience(
        role_only,
        AudienceContext(role="agent", business_line="loans", personalization_enabled=False),
    )


# ---------------------------------------------------------------------------
# End to end: profile pincode, consent, precedence
# ---------------------------------------------------------------------------


async def _user_uuid(mobile: str) -> uuid.UUID:
    import app.db.session as session_module

    async with session_module.AsyncSessionLocal() as db:
        value = await db.scalar(text("SELECT id FROM auth_users WHERE mobile = :m"), {"m": mobile})
        return uuid.UUID(str(value))


def _offer(title: str, author: uuid.UUID, rules: dict, priority: int) -> Offer:
    return Offer(
        business_line="loans",
        title=title,
        discount_type="flat",
        discount_value=Decimal("250"),
        code="PIN250",
        partner_name="Local Partner",
        redemption_url="https://partner.example/local",
        terms_summary="Valid in the selected service area.",
        image_key=f"public/banners/{uuid.uuid4()}/local.webp",
        audience_rules=rules,
        priority=priority,
        status=OfferStatus.ACTIVE,
        created_by_uuid=author,
    )


async def _offer_titles(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    resp = await client.get(
        "/api/v1/personalization/placements?business_line=loans", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return {row["title"] for row in resp.json()["offers"]}


@pytest.mark.asyncio
async def test_profile_pincode_drives_location_offers_only_with_consent(
    client: AsyncClient,
) -> None:
    import app.db.session as session_module

    token, mobile = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    user_id = await _user_uuid(mobile)
    tag = uuid.uuid4().hex[:8]
    pincode_title = f"Pincode offer {tag}"
    city_title = f"City offer {tag}"
    circle_title = f"Circle offer {tag}"
    offers = [
        _offer(
            pincode_title,
            user_id,
            {"version": 2, "user_types": ["client"], "pincodes": ["500001"]},
            9_000_003,
        ),
        _offer(
            city_title,
            user_id,
            {"version": 2, "user_types": ["client"], "cities": [HYDERABAD]},
            9_000_002,
        ),
        _offer(
            circle_title,
            user_id,
            {
                "version": 1,
                "user_types": ["client"],
                "locations": [
                    {"label": "Hyd", "latitude": 17.3862, "longitude": 78.462, "radius_km": 5}
                ],
            },
            9_000_001,
        ),
    ]
    async with session_module.AsyncSessionLocal() as db:
        db.add_all(offers)
        await db.commit()
    ids = [offer.id for offer in offers]
    targeted = {pincode_title, city_title, circle_title}
    try:
        saved = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"first_name": "Pin", "last_name": "Code", "pincode": "500001"},
        )
        assert saved.status_code == 200, saved.text
        # A profile pincode alone, without consent, never targets.
        assert not (await _offer_titles(client, headers)) & targeted

        consent = await client.patch(
            "/api/v1/personalization/preferences",
            headers=headers,
            json={"personalization_enabled": True},
        )
        assert consent.status_code == 200
        # Personalization alone is not location consent: no pincode, city or
        # circle match until the separate location consent is given.
        assert not (await _offer_titles(client, headers)) & targeted

        located = await client.put("/api/v1/personalization/location/consent", headers=headers)
        assert located.status_code == 200, located.text
        assert located.json()["location_enabled"] is True
        assert located.json()["location_captured_at"] is None
        assert (await _offer_titles(client, headers)) >= targeted

        # Revoking location consent stops every location match at once.
        withdrawn = await client.delete("/api/v1/personalization/location", headers=headers)
        assert withdrawn.status_code == 200
        assert withdrawn.json()["location_enabled"] is False
        assert not (await _offer_titles(client, headers)) & targeted
        regranted = await client.put("/api/v1/personalization/location/consent", headers=headers)
        assert regranted.status_code == 200
        assert (await _offer_titles(client, headers)) >= targeted

        # Another pincode in the same city: city still matches, the pincode
        # target and the 5 km circle around 500001's centroid do not.
        moved = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"first_name": "Pin", "last_name": "Code", "pincode": "500032"},
        )
        assert moved.status_code == 200
        district = await _scalar_text("SELECT district FROM pincodes WHERE pincode = '500032'")
        titles = await _offer_titles(client, headers)
        assert pincode_title not in titles
        assert (city_title in titles) is (district == "Hyderabad")

        # Turning personalized content off also ends location consent.
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"first_name": "Pin", "last_name": "Code", "pincode": "500001"},
        )
        revoked = await client.patch(
            "/api/v1/personalization/preferences",
            headers=headers,
            json={"personalization_enabled": False},
        )
        assert revoked.status_code == 200
        assert revoked.json()["location_enabled"] is False
        assert not (await _offer_titles(client, headers)) & targeted
        # Turning it back on does not silently restore location consent.
        await client.patch(
            "/api/v1/personalization/preferences",
            headers=headers,
            json={"personalization_enabled": True},
        )
        assert not (await _offer_titles(client, headers)) & targeted
    finally:
        async with session_module.AsyncSessionLocal() as db:
            await db.execute(delete(Offer).where(Offer.id.in_(ids)))
            await db.commit()


async def _scalar_text(sql: str) -> str | None:
    import app.db.session as session_module

    async with session_module.AsyncSessionLocal() as db:
        return await db.scalar(text(sql))


@pytest.mark.asyncio
async def test_profile_pincode_wins_over_the_legacy_coarse_point(client: AsyncClient) -> None:
    import app.db.session as session_module

    token, mobile = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    user_id = await _user_uuid(mobile)
    tag = uuid.uuid4().hex[:8]
    mumbai_title = f"Mumbai circle {tag}"
    hyderabad_title = f"Hyderabad circle {tag}"

    def circle(lat: float, lon: float) -> dict:
        return {
            "version": 1,
            "user_types": ["client"],
            "locations": [{"label": "c", "latitude": lat, "longitude": lon, "radius_km": 25}],
        }

    offers = [
        _offer(mumbai_title, user_id, circle(19.07, 72.87), 9_100_002),
        _offer(hyderabad_title, user_id, circle(17.3862, 78.462), 9_100_001),
    ]
    now = datetime.now(UTC)
    async with session_module.AsyncSessionLocal() as db:
        db.add_all(offers)
        # A still-valid legacy coarse point in Mumbai (CS-008).
        db.add(
            PersonalizationPreference(
                auth_user_uuid=user_id,
                personalization_enabled=True,
                personalization_consented_at=now,
                location_enabled=True,
                latitude_e2=1907,
                longitude_e2=7287,
                location_captured_at=now,
                location_consented_at=now,
                updated_at=now,
            )
        )
        await db.commit()
    ids = [offer.id for offer in offers]
    try:
        titles = await _offer_titles(client, headers)
        assert mumbai_title in titles and hyderabad_title not in titles

        saved = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"first_name": "Pin", "last_name": "Code", "pincode": "500001"},
        )
        assert saved.status_code == 200
        titles = await _offer_titles(client, headers)
        assert hyderabad_title in titles and mumbai_title not in titles
    finally:
        async with session_module.AsyncSessionLocal() as db:
            await db.execute(delete(Offer).where(Offer.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
async def test_agents_never_match_location_targets(client: AsyncClient) -> None:
    """Only Clients consent (CS-021), so an Agent's pincode never targets."""
    rules = AudienceRules.model_validate(
        {
            "version": 1,
            "user_types": ["agent"],
            "locations": [
                {"label": "c", "latitude": 17.3862, "longitude": 78.462, "radius_km": 25}
            ],
        }
    )
    context = AudienceContext(role="agent", business_line="loans", personalization_enabled=False)
    assert not matches_audience(rules, context)


# ---------------------------------------------------------------------------
# Authoring: every pincode and city must exist; cities are stored canonically
# ---------------------------------------------------------------------------


def _sub_admin_headers(uid: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        {"sub": str(uid), "role": "sub_admin", "business_line": "both", "platform_scope": "true"}
    )
    return {"Authorization": f"Bearer {token}"}


_OFFER_PAYLOAD = {
    "business_line": "loans",
    "title": "Local cashback",
    "discount_type": "flat",
    "discount_value": "100",
    "code": "LOCAL100",
    "partner_name": "Example Partner",
    "redemption_url": "https://partner.example/checkout",
    "terms_summary": "Valid once per customer while campaign inventory lasts.",
    "image_key": "public/banners/11111111-1111-1111-1111-111111111111/offer.webp",
}


@pytest.mark.asyncio
async def test_offer_authoring_validates_and_canonicalises_places(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = _sub_admin_headers(await _user_uuid(mobile))

    unknown_pincode = await client.post(
        "/api/v1/offers",
        headers=headers,
        json={
            **_OFFER_PAYLOAD,
            "audience_rules": {"version": 2, "user_types": ["client"], "pincodes": ["999999"]},
        },
    )
    assert unknown_pincode.status_code == 422
    assert "999999" in unknown_pincode.text

    unknown_city = await client.post(
        "/api/v1/offers",
        headers=headers,
        json={
            **_OFFER_PAYLOAD,
            "audience_rules": {
                "version": 2,
                "user_types": ["client"],
                "cities": [{"district": "Atlantis", "state": "Telangana"}],
            },
        },
    )
    assert unknown_city.status_code == 422
    assert "Atlantis" in unknown_city.text

    created = await client.post(
        "/api/v1/offers",
        headers=headers,
        json={
            **_OFFER_PAYLOAD,
            "audience_rules": {
                "version": 2,
                "user_types": ["client"],
                "pincodes": ["500001"],
                "cities": [{"district": " hyderabad ", "state": "TELANGANA"}],
            },
        },
    )
    assert created.status_code == 201, created.text
    read_rules = created.json()["audience_rules"]
    assert read_rules["version"] == 2
    assert read_rules["user_types"] == ["client"]
    assert read_rules["pincodes"] == ["500001"]
    assert read_rules["cities"] == [HYDERABAD]

    updated = await client.patch(
        f"/api/v1/offers/{created.json()['id']}",
        headers=headers,
        json={"audience_rules": {"version": 2, "user_types": ["client"], "pincodes": ["999999"]}},
    )
    assert updated.status_code == 422

    async with __import__("app.db.session", fromlist=["x"]).AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(Offer.audience_rules).where(Offer.id == uuid.UUID(created.json()["id"]))
        )
        await db.execute(delete(Offer).where(Offer.id == uuid.UUID(created.json()["id"])))
        await db.commit()
    assert stored["cities"] == [HYDERABAD]


@pytest.mark.asyncio
async def test_banner_authoring_refuses_unknown_places(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = _sub_admin_headers(await _user_uuid(mobile))
    resp = await client.post(
        "/api/v1/banners",
        headers=headers,
        json={
            "business_line": "loans",
            "banner_type": "personalized",
            "title": "Local banner",
            "audience_rules": {"version": 2, "user_types": ["client"], "pincodes": ["999999"]},
        },
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# City list for the campaign form
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_district_list(client: AsyncClient) -> None:
    token, _ = await full_registration(client, lines=["loans"])
    resp = await client.get(
        "/api/v1/pincodes/districts", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert HYDERABAD in rows
    assert len(rows) == len({(row["district"], row["state"]) for row in rows})
    assert rows == sorted(
        rows, key=lambda row: (row["state"].casefold(), row["district"].casefold())
    )
    assert (await client.get("/api/v1/pincodes/districts")).status_code == 401


# ---------------------------------------------------------------------------
# Location consent without a device point (CS-026, migration f6b8d0a2c4e7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_location_consent_needs_personalization_and_a_profile_pincode(
    client: AsyncClient,
) -> None:
    import app.db.session as session_module
    from app.models.auth import AuthEvent

    token, mobile = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    user_id = await _user_uuid(mobile)
    url = "/api/v1/personalization/location/consent"

    assert (await client.put(url, headers=headers)).status_code == 409
    await client.patch(
        "/api/v1/personalization/preferences",
        headers=headers,
        json={"personalization_enabled": True},
    )
    no_pincode = await client.put(url, headers=headers)
    assert no_pincode.status_code == 409
    assert "pincode" in no_pincode.json()["detail"]

    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Pin", "last_name": "Code", "pincode": "500001"},
    )
    granted = await client.put(url, headers=headers)
    assert granted.status_code == 200, granted.text
    assert granted.headers["cache-control"] == "private, no-store"
    assert granted.json() == {
        "personalization_enabled": True,
        "location_enabled": True,
        "location_captured_at": None,
    }
    again = await client.put(url, headers=headers)
    assert again.status_code == 200

    async with session_module.AsyncSessionLocal() as db:
        stored = await db.get(PersonalizationPreference, user_id)
        assert stored is not None
        assert stored.location_consented_at is not None
        assert (stored.latitude_e2, stored.longitude_e2) == (None, None)
        events = (
            await db.scalars(
                select(AuthEvent).where(
                    AuthEvent.auth_user_uuid == user_id,
                    AuthEvent.event_type == "location_personalization_consent_updated",
                )
            )
        ).all()
    # One consent event (the repeat is a no-op) carrying only the decision.
    assert [event.detail for event in events] == [{"enabled": True}]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agent", "telecaller", "employee", "sub_admin", "admin"])
async def test_location_consent_is_client_only(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    token = create_access_token(
        {
            "sub": str(await _user_uuid(mobile)),
            "role": role,
            "business_line": "loans",
            "platform_scope": "true" if role in ("admin", "sub_admin") else "false",
        }
    )
    resp = await client.put(
        "/api/v1/personalization/location/consent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_location_consent_rows_are_consistent(client: AsyncClient) -> None:
    import app.db.session as session_module

    _, mobile = await full_registration(client, lines=["loans"])
    user_id = await _user_uuid(mobile)
    now = datetime.now(UTC)
    base = {
        "auth_user_uuid": user_id,
        "personalization_enabled": True,
        "personalization_consented_at": now,
        "updated_at": now,
    }
    invalid = [
        # consent without a consent time
        {"location_enabled": True},
        # a partial point
        {"location_enabled": True, "location_consented_at": now, "latitude_e2": 1738},
        # a point without consent
        {"location_enabled": False, "latitude_e2": 1738, "longitude_e2": 7846},
    ]
    for values in invalid:
        async with session_module.AsyncSessionLocal() as db:
            db.add(PersonalizationPreference(**base, **values))
            with pytest.raises(Exception, match="location_consistent"):
                await db.commit()
    async with session_module.AsyncSessionLocal() as db:
        db.add(PersonalizationPreference(**base, location_enabled=True, location_consented_at=now))
        await db.commit()


@pytest.mark.asyncio
async def test_retention_purge_keeps_pincode_only_location_consent(client: AsyncClient) -> None:
    import app.db.session as session_module
    from app.services.personalization import purge_stale_locations

    token, mobile = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    user_id = await _user_uuid(mobile)
    await client.patch(
        "/api/v1/personalization/preferences",
        headers=headers,
        json={"personalization_enabled": True},
    )
    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Pin", "last_name": "Code", "pincode": "500001"},
    )
    granted = await client.put("/api/v1/personalization/location/consent", headers=headers)
    assert granted.status_code == 200

    await purge_stale_locations(now=datetime.now(UTC) + timedelta(days=365))
    async with session_module.AsyncSessionLocal() as db:
        stored = await db.get(PersonalizationPreference, user_id)
        assert stored is not None and stored.location_enabled is True
