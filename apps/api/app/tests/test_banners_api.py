"""banners API — create, submit, approve, reject, guards.

Mints role-specific access tokens (sub_admin / admin) for an already-registered
auth_user: get_current_user reads the mobile from the row but takes role +
business_line + platform_scope from the JWT claims, so a client account can act
as a sub_admin/admin for the endpoint under test. Mirrors
test_property_submissions_api.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.banner_catalog import CATEGORIES_BY_PLACEMENT
from app.core.security import create_access_token
from conftest import full_registration

# Derived from the catalogue: this test is about template MATCHING, so a
# literal count would make every new placement fail here for no reason.
_SEEDED_TEMPLATES = sum(len(categories) for categories in CATEGORIES_BY_PLACEMENT.values())


async def _auth_user_uuid(mobile: str) -> str:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        row = (
            await db.execute(text("SELECT id FROM auth_users WHERE mobile = :m"), {"m": mobile})
        ).fetchone()
        return str(row[0])


def _sub_admin_token(uid: str) -> str:
    return create_access_token(
        {"sub": uid, "role": "sub_admin", "business_line": "both", "platform_scope": "true"}
    )


def _admin_token(uid: str) -> str:
    return create_access_token(
        {"sub": uid, "role": "admin", "business_line": "both", "platform_scope": "true"}
    )


_PAYLOAD = {
    "business_line": "loans",
    "banner_type": "default",
    "title": "Diwali Loan Offer",
    "audience_rules": {},
    "priority": 1,
}


async def _seed_property(*, active: bool, category: str = "villas") -> str:
    import app.db.session as _session_mod
    from app.models.property import Property

    async with _session_mod.AsyncSessionLocal() as db:
        property_listing = Property(
            business_line="real_estate",
            active=active,
            title=f"Campaign property {uuid.uuid4()}",
            type="Villa",
            location="Kokapet, Hyderabad",
            price_display="₹2 Cr",
            category=category,
            city="Hyderabad",
            locality="Kokapet",
            pincode="500075",
            price_paise=20_000_000_00,
            furnishing="furnished",
            construction_status="ready",
            rera_number="RERA/TS/2026/0044",
            rera_applicability="applicable",
            rera_verification_status="verified",
            rera_verified_at=datetime.now(UTC),
        )
        db.add(property_listing)
        await db.commit()
        return str(property_listing.id)


async def _delete_properties(*property_ids: str) -> None:
    import app.db.session as _session_mod
    from app.models.property import Property

    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(
            delete(Property).where(Property.id.in_([uuid.UUID(item) for item in property_ids]))
        )
        await db.commit()


async def _delete_banners(*banner_ids: str) -> None:
    """Superuser cleanup: approval now publishes due banners, and a leaked LIVE
    row would crowd test_public_banners.py's cap/presence assertions."""
    import app.db.session as _session_mod
    from app.models.banner import Banner

    ids = [uuid.UUID(item) for item in banner_ids]
    async with _session_mod.AsyncSessionLocal() as db:
        # Replacements first: replaces_banner_id is immutable, so the FK's
        # ON DELETE SET NULL cannot run while a replacement still points here.
        await db.execute(delete(Banner).where(Banner.replaces_banner_id.in_(ids)))
        await db.execute(delete(Banner).where(Banner.id.in_(ids)))
        await db.commit()


async def _audit_actions(banner_id: str) -> list[str]:
    import app.db.session as _session_mod
    from app.models.audit_log import AuditLog

    async with _session_mod.AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_type == "banner", AuditLog.entity_uuid == uuid.UUID(banner_id))
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
        return [action.value for action in rows.all()]


async def _banner_status(banner_id: str) -> str | None:
    import app.db.session as _session_mod
    from app.models.banner import Banner

    async with _session_mod.AsyncSessionLocal() as db:
        row = await db.scalar(select(Banner).where(Banner.id == uuid.UUID(banner_id)))
        return row.status.value if row is not None else None


_FUTURE_START = "2099-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_sub_admin_create_starts_draft(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    res = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "draft"
    assert body["created_by_uuid"] == uid
    assert body["approved_by_uuid"] is None


@pytest.mark.asyncio
async def test_client_cannot_create(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    token = create_access_token(
        {"sub": uid, "role": "client", "business_line": "loans", "platform_scope": "false"}
    )
    res = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_validation_error(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    bad = {**_PAYLOAD, "title": ""}  # min_length=1 fails
    res = await client.post(
        "/api/v1/banners",
        json=bad,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_personalized_banner_requires_typed_audience(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}

    missing = await client.post(
        "/api/v1/banners",
        json={**_PAYLOAD, "banner_type": "personalized", "audience_rules": {}},
        headers=headers,
    )
    assert missing.status_code == 422

    targeted = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "banner_type": "personalized",
            "audience_rules": {
                "version": 1,
                "user_types": ["client"],
                "client_journey_stages": ["not_started"],
            },
        },
        headers=headers,
    )
    assert targeted.status_code == 201, targeted.text
    assert targeted.json()["audience_rules"]["user_types"] == ["client"]


@pytest.mark.asyncio
async def test_default_banner_rejects_targeting_rules(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    response = await client.post(
        "/api/v1/banners",
        json={**_PAYLOAD, "audience_rules": {"version": 1, "user_types": ["client"]}},
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_moves_to_pending_approval(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    res = await client.post(
        f"/api/v1/banners/{banner_id}/submit",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_sub_admin_cannot_approve_own_banner(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    await client.post(
        f"/api/v1/banners/{banner_id}/submit",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    res = await client.post(
        f"/api/v1/banners/{banner_id}/approve",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_approve(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    await client.post(
        f"/api/v1/banners/{banner_id}/submit",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    try:
        res = await client.post(
            f"/api/v1/banners/{banner_id}/approve",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        # No start date and no category slot: due now, so approval publishes it.
        assert body["status"] == "live"
        assert body["approved_by_uuid"] == uid
        notifications = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
        )
        assert any(
            item["type"] == "campaign_approved"
            and item["href"] == "/dashboard/campaigns?type=banners"
            for item in notifications.json()["notifications"]
        )
        # Approval and activation share one transaction (same created_at).
        assert sorted(await _audit_actions(banner_id)) == [
            "banner_activated",
            "banner_approved",
            "banner_created",
            "banner_submitted",
        ]
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_platform_admin_cannot_author_or_patch_a_banner(client: AsyncClient) -> None:
    """PATCH is a sub_admin-only create-time-editing action (require_sub_admin);
    Admin's role in this flow is approve/reject only, never field edits."""
    _, owner_mobile = await full_registration(client, lines=["loans"])
    owner_uid = await _auth_user_uuid(owner_mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(owner_uid)}"},
    )
    banner_id = created.json()["id"]
    _, admin_mobile = await full_registration(client, lines=["loans"])
    admin_uid = await _auth_user_uuid(admin_mobile)
    create_res = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_admin_token(admin_uid)}"},
    )
    assert create_res.status_code == 403

    res = await client.patch(
        f"/api/v1/banners/{banner_id}",
        json={"title": "Admin correction"},
        headers={"Authorization": f"Bearer {_admin_token(admin_uid)}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_submit_an_already_approved_banner_conflicts(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    sub_admin_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_admin_headers)
    await client.post(
        f"/api/v1/banners/{banner_id}/approve",
        headers={"Authorization": f"Bearer {_admin_token(uid)}"},
    )
    res = await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_admin_headers)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_double_approve_conflicts(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    await client.post(
        f"/api/v1/banners/{banner_id}/submit",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    await client.post(f"/api/v1/banners/{banner_id}/approve", headers=headers)
    second = await client.post(f"/api/v1/banners/{banner_id}/approve", headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_reject_sets_note(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    await client.post(
        f"/api/v1/banners/{banner_id}/submit",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    res = await client.post(
        f"/api/v1/banners/{banner_id}/reject",
        json={"note": "Image asset missing."},
        headers={"Authorization": f"Bearer {_admin_token(uid)}"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["review_note"] == "Image asset missing."
    notifications = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert any(
        item["type"] == "campaign_changes_requested"
        for item in notifications.json()["notifications"]
    )


@pytest.mark.asyncio
async def test_reject_then_resubmit(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    sub_admin_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_admin_headers)
    await client.post(
        f"/api/v1/banners/{banner_id}/reject",
        json={"note": "Fix the deep link."},
        headers={"Authorization": f"Bearer {_admin_token(uid)}"},
    )
    edited = await client.patch(
        f"/api/v1/banners/{banner_id}",
        json={"deep_link": "https://example.com/loans"},
        headers=sub_admin_headers,
    )
    assert edited.status_code == 200, edited.text
    resubmit = await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_admin_headers)
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_edit_while_pending_approval_conflicts(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    banner_id = created.json()["id"]
    sub_admin_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_admin_headers)
    res = await client.patch(
        f"/api/v1/banners/{banner_id}",
        json={"title": "Edited while pending"},
        headers=sub_admin_headers,
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_approve_missing_is_404(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    res = await client.post(
        "/api/v1/banners/00000000-0000-0000-0000-000000000000/approve",
        headers={"Authorization": f"Bearer {_admin_token(uid)}"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_other_sub_admin_can_edit_and_submit_shared_draft(client: AsyncClient) -> None:
    """Shared visibility includes team-wide draft editing and submission."""
    _, owner_mobile = await full_registration(client, lines=["loans"])
    owner_uid = await _auth_user_uuid(owner_mobile)
    created = await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(owner_uid)}"},
    )
    banner_id = created.json()["id"]

    _, other_mobile = await full_registration(client, lines=["loans"])
    other_uid = await _auth_user_uuid(other_mobile)
    other_headers = {"Authorization": f"Bearer {_sub_admin_token(other_uid)}"}

    edit_res = await client.patch(
        f"/api/v1/banners/{banner_id}",
        json={"title": "Hijacked"},
        headers=other_headers,
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["title"] == "Hijacked"

    submit_res = await client.post(f"/api/v1/banners/{banner_id}/submit", headers=other_headers)
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_cross_line_banner_can_be_authored(client: AsyncClient) -> None:
    """A banner may target both lines, and saying so must not 500.

    ck_banners_business_line_content_audience allows 'both' for content rows,
    but create_banner forwards the banner's line into the audit entry and
    ck_audit_log_business_line_optional_operational allows only a concrete line
    or NULL. Every other banner test uses a concrete line, so this path was
    unexercised until now; services/audit_log.py::record normalizes it.
    """
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)

    created = await client.post(
        "/api/v1/banners",
        json={**_PAYLOAD, "business_line": "both"},
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["business_line"] == "both"


@pytest.mark.asyncio
async def test_sponsor_strip_campaign_is_not_locked_to_one_business_line(
    client: AsyncClient,
) -> None:
    """A sponsor slot serves either line, and still requires governed artwork.

    financial_services and properties force loans/real_estate respectively via
    expected_business_line(); homepage_ad deliberately falls through to None,
    so the same slot accepts a loans campaign and a real_estate one. That
    fall-through is easy to break, so pin it through the real authoring route.
    """
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}

    templates = await client.get("/api/v1/banners/templates", headers=headers)
    slots = [item for item in templates.json()["templates"] if item["placement"] == "homepage_ad"]
    expected_themes = next(
        categories
        for placement, categories in CATEGORIES_BY_PLACEMENT.items()
        if placement.value == "homepage_ad"
    )
    assert {item["category_key"] for item in slots} == set(expected_themes)
    sponsor_template = next(item for item in slots if item["category_key"] == "sponsor")

    for line in ("loans", "real_estate"):
        created = await client.post(
            "/api/v1/banners",
            json={
                **_PAYLOAD,
                "business_line": line,
                "placement": "homepage_ad",
                "template_id": sponsor_template["id"],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["placement"] == "homepage_ad"
        assert created.json()["business_line"] == line

    without_template = await client.post(
        "/api/v1/banners",
        json={**_PAYLOAD, "placement": "homepage_ad"},
        headers=headers,
    )
    assert without_template.status_code == 422


@pytest.mark.asyncio
async def test_public_campaign_requires_active_matching_template(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}

    templates = await client.get("/api/v1/banners/templates", headers=headers)
    assert templates.status_code == 200, templates.text
    assert len(templates.json()["templates"]) == _SEEDED_TEMPLATES
    template = next(
        item
        for item in templates.json()["templates"]
        if item["placement"] == "financial_services" and item["category_key"] == "personal-loan"
    )
    assert template["image_url"] == (
        f"/banner-templates/financial_services/personal-loan.webp?v={template['version']}"
    )

    missing = await client.post(
        "/api/v1/banners",
        json={**_PAYLOAD, "placement": "financial_services"},
        headers=headers,
    )
    assert missing.status_code == 422

    created = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "placement": "financial_services",
            "template_id": template["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["placement"] == "financial_services"
    assert created.json()["category_key"] == "personal-loan"

    wrong_line = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "business_line": "real_estate",
            "placement": "financial_services",
            "template_id": template["id"],
        },
        headers=headers,
    )
    assert wrong_line.status_code == 422

    offer_template = next(
        item
        for item in templates.json()["templates"]
        if item["placement"] == "homepage" and item["category_key"] == "offers"
    )
    generic_offer_artwork = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "placement": "homepage",
            "template_id": offer_template["id"],
        },
        headers=headers,
    )
    assert generic_offer_artwork.status_code == 201, generic_offer_artwork.text

    import app.db.session as _session_mod
    from app.models.offer import Offer, OfferStatus

    async with _session_mod.AsyncSessionLocal() as db:
        targeted_offer = Offer(
            business_line="loans",
            title="Private client incentive",
            discount_type="percentage",
            discount_value=10,
            status=OfferStatus.ACTIVE,
            audience_rules={"version": 1, "user_types": ["client"]},
            created_by_uuid=uuid.UUID(uid),
        )
        db.add(targeted_offer)
        await db.commit()
        targeted_offer_id = str(targeted_offer.id)
    targeted_offer_response = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "placement": "homepage",
            "template_id": offer_template["id"],
            "offer_id": targeted_offer_id,
        },
        headers=headers,
    )
    assert targeted_offer_response.status_code == 422
    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(delete(Offer).where(Offer.id == uuid.UUID(targeted_offer_id)))
        await db.commit()


@pytest.mark.asyncio
async def test_property_campaign_requires_active_category_match_and_copies_to_replacement(
    client: AsyncClient,
) -> None:
    _, mobile = await full_registration(client, lines=["real_estate"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    templates = (await client.get("/api/v1/banners/templates", headers=sub_headers)).json()[
        "templates"
    ]
    homepage_properties = next(
        item
        for item in templates
        if item["placement"] == "homepage" and item["category_key"] == "properties"
    )
    homepage_general = next(
        item
        for item in templates
        if item["placement"] == "homepage" and item["category_key"] == "general"
    )
    active_property_id = await _seed_property(active=True)
    inactive_property_id = await _seed_property(active=False)
    banner_ids: list[str] = []
    try:
        created = await client.post(
            "/api/v1/banners",
            json={
                **_PAYLOAD,
                "business_line": "real_estate",
                "placement": "homepage",
                "template_id": homepage_properties["id"],
                "property_id": active_property_id,
            },
            headers=sub_headers,
        )
        assert created.status_code == 201, created.text
        banner_id = created.json()["id"]
        banner_ids.append(banner_id)
        assert created.json()["property_id"] == active_property_id

        wrong_category = await client.post(
            "/api/v1/banners",
            json={
                **_PAYLOAD,
                "business_line": "real_estate",
                "placement": "homepage",
                "template_id": homepage_general["id"],
                "property_id": active_property_id,
            },
            headers=sub_headers,
        )
        assert wrong_category.status_code == 422

        inactive = await client.post(
            "/api/v1/banners",
            json={
                **_PAYLOAD,
                "business_line": "real_estate",
                "placement": "homepage",
                "template_id": homepage_properties["id"],
                "property_id": inactive_property_id,
            },
            headers=sub_headers,
        )
        assert inactive.status_code == 422

        assert (
            await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_headers)
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/banners/{banner_id}/approve", headers=admin_headers)
        ).status_code == 200
        replacement = await client.post(
            f"/api/v1/banners/{banner_id}/replacement", headers=sub_headers
        )
        assert replacement.status_code == 201, replacement.text
        banner_ids.append(replacement.json()["id"])
        assert replacement.json()["property_id"] == active_property_id
    finally:
        import app.db.session as _session_mod
        from app.models.banner import Banner

        async with _session_mod.AsyncSessionLocal() as db:
            await db.execute(
                delete(Banner).where(Banner.id.in_([uuid.UUID(item) for item in banner_ids]))
            )
            await db.commit()
        await _delete_properties(active_property_id, inactive_property_id)


@pytest.mark.asyncio
async def test_reviewed_campaign_replacement_archive_and_draft_delete(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    templates = await client.get("/api/v1/banners/templates", headers=sub_headers)
    template = next(
        item
        for item in templates.json()["templates"]
        if item["placement"] == "financial_services" and item["category_key"] == "business-loan"
    )
    created = await client.post(
        "/api/v1/banners",
        json={
            **_PAYLOAD,
            "placement": "financial_services",
            "template_id": template["id"],
            # Future start: approval leaves it approved (not live), so the
            # Sub Admin may still archive it below.
            "starts_at": _FUTURE_START,
        },
        headers=sub_headers,
    )
    banner_id = created.json()["id"]
    try:
        submitted = await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_headers)
        assert submitted.status_code == 200
        approved = await client.post(f"/api/v1/banners/{banner_id}/approve", headers=admin_headers)
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        replacement = await client.post(
            f"/api/v1/banners/{banner_id}/replacement", headers=sub_headers
        )
        assert replacement.status_code == 201, replacement.text
        replacement_id = replacement.json()["id"]
        assert replacement.json()["status"] == "draft"
        assert replacement.json()["replaces_banner_id"] == banner_id
        assert replacement.json()["template_id"] == template["id"]

        archived = await client.post(f"/api/v1/banners/{banner_id}/archive", headers=sub_headers)
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        deleted = await client.delete(f"/api/v1/banners/{replacement_id}", headers=sub_headers)
        assert deleted.status_code == 204
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_template_upload_is_sub_admin_only_and_uses_private_staging(
    client: AsyncClient,
) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    payload = {"content_type": "image/webp", "filename": "replacement.webp"}
    response = await client.post(
        "/api/v1/banners/templates/image-upload-url",
        json=payload,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["object_key"].startswith("private/banner-templates/staging/")

    denied = await client.post(
        "/api/v1/banners/templates/image-upload-url",
        json=payload,
        headers={"Authorization": f"Bearer {_admin_token(uid)}"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_banner_patch_rejects_a_stale_team_edit(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    created = await client.post("/api/v1/banners", json=_PAYLOAD, headers=headers)
    assert created.status_code == 201, created.text
    banner = created.json()

    first = await client.patch(
        f"/api/v1/banners/{banner['id']}",
        json={"title": "First team edit", "expected_version": banner["version"]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == banner["version"] + 1

    stale = await client.patch(
        f"/api/v1/banners/{banner['id']}",
        json={"title": "Stale overwrite", "expected_version": banner["version"]},
        headers=headers,
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_admin_soft_removes_reviewed_banner_and_it_leaves_queue(
    client: AsyncClient,
) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    created = await client.post("/api/v1/banners", json=_PAYLOAD, headers=sub_headers)
    banner_id = created.json()["id"]
    await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_headers)

    blank_reason = await client.post(
        f"/api/v1/banners/{banner_id}/remove",
        json={"note": "   "},
        headers=admin_headers,
    )
    assert blank_reason.status_code == 422

    removed = await client.post(
        f"/api/v1/banners/{banner_id}/remove",
        json={"note": "Campaign is no longer valid."},
        headers=admin_headers,
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed_at"] is not None
    assert removed.json()["removal_reason"] == "Campaign is no longer valid."

    queue = await client.get("/api/v1/banners", headers=admin_headers)
    assert banner_id not in {item["id"] for item in queue.json()["banners"]}


@pytest.mark.asyncio
async def test_non_sub_admin_non_admin_sees_empty_list(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    await client.post(
        "/api/v1/banners",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    token = create_access_token(
        {"sub": uid, "role": "telecaller", "business_line": "loans", "platform_scope": "false"}
    )
    res = await client.get(
        "/api/v1/banners",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["banners"] == []


@pytest.mark.asyncio
async def test_create_and_patch_carry_subtitle_and_cta_label(client: AsyncClient) -> None:
    """subtitle/cta_label (public-banner-serving PR B) round-trip through create and patch,
    same as every other free-text field on this schema."""
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    payload = {**_PAYLOAD, "subtitle": "Limited period offer", "cta_label": "Apply now"}
    created = await client.post(
        "/api/v1/banners",
        json=payload,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["subtitle"] == "Limited period offer"
    assert body["cta_label"] == "Apply now"

    banner_id = body["id"]
    patched = await client.patch(
        f"/api/v1/banners/{banner_id}",
        json={"cta_label": "Get started"},
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["cta_label"] == "Get started"
    assert patched.json()["subtitle"] == "Limited period offer"


@pytest.mark.asyncio
async def test_image_upload_url_returns_conforming_key(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    res = await client.post(
        "/api/v1/banners/image-upload-url",
        json={"content_type": "image/jpeg", "filename": "diwali-hero.jpg"},
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["object_key"].startswith("public/banners/")
    assert body["object_key"].endswith("diwali-hero.jpg")
    assert body["upload_url"].startswith("http")
    assert body["fields"]["key"] == body["object_key"]
    assert body["max_bytes"] == 5 * 1024 * 1024


@pytest.mark.asyncio
async def test_image_upload_url_rejects_unsupported_content_type(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    res = await client.post(
        "/api/v1/banners/image-upload-url",
        # image/svg+xml is deliberately not in the schema's Literal at all --
        # this is caught by Pydantic (422), not the service's UnsupportedImageType
        # branch (400). Both paths reject it; this asserts the 422 boundary.
        json={"content_type": "image/svg+xml", "filename": "logo.svg"},
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_image_upload_url_requires_sub_admin(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    token = create_access_token(
        {"sub": uid, "role": "client", "business_line": "loans", "platform_scope": "false"}
    )
    res = await client.post(
        "/api/v1/banners/image-upload-url",
        json={"content_type": "image/jpeg", "filename": "hero.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_accepts_a_conforming_image_key(client: AsyncClient) -> None:
    payload = {
        **_PAYLOAD,
        "image_key": "public/banners/11111111-1111-1111-1111-111111111111/hero.jpg",
    }
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    res = await client.post(
        "/api/v1/banners",
        json=payload,
        headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["image_key"] == payload["image_key"]


@pytest.mark.asyncio
async def test_create_rejects_a_non_conforming_image_key(client: AsyncClient) -> None:
    """The write-side half of the public/ security boundary: a free-text or
    mistyped image_key (or one pointing at a different, non-public prefix
    entirely) must never be accepted -- see schemas/banners.py's
    _IMAGE_KEY_PATTERN and services/storage.py::public_asset_url."""
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    for bad_key in [
        "agent-applications/abc-123/deadbeef-photo",  # a real KYC key shape
        "public/banners/not-a-uuid/hero.jpg",
        "public/banners/11111111-1111-1111-1111-111111111111/../evil.jpg",
        "public/banners/11111111-1111-1111-1111-111111111111/sub/hero.jpg",
    ]:
        res = await client.post(
            "/api/v1/banners",
            json={**_PAYLOAD, "image_key": bad_key},
            headers={"Authorization": f"Bearer {_sub_admin_token(uid)}"},
        )
        assert res.status_code == 422, f"expected 422 for {bad_key!r}, got {res.status_code}"


# --- 2026-11-16: delete until live, Admin-only take-down, instant go-live, CTA links ---


async def _banner_in_status(
    client: AsyncClient,
    uid: str,
    target: str,
    *,
    payload: dict | None = None,
) -> str:
    """Drive a banner through the real API to draft, pending, rejected,
    approved (future start, so it stays approved) or live (no start, no slot)."""
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    body = dict(payload or _PAYLOAD)
    if target == "approved":
        body["starts_at"] = _FUTURE_START
    created = await client.post("/api/v1/banners", json=body, headers=sub_headers)
    assert created.status_code == 201, created.text
    banner_id = created.json()["id"]
    if target == "draft":
        return banner_id
    submitted = await client.post(f"/api/v1/banners/{banner_id}/submit", headers=sub_headers)
    assert submitted.status_code == 200, submitted.text
    if target == "pending_approval":
        return banner_id
    if target == "rejected":
        rejected = await client.post(
            f"/api/v1/banners/{banner_id}/reject",
            json={"note": "Please tighten the copy."},
            headers=admin_headers,
        )
        assert rejected.status_code == 200, rejected.text
        return banner_id
    approved = await client.post(f"/api/v1/banners/{banner_id}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == target, approved.json()["status"]
    return banner_id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "pending_approval", "rejected", "approved"])
async def test_sub_admin_deletes_a_banner_until_it_goes_live(
    client: AsyncClient, status: str
) -> None:
    import app.db.session as _session_mod
    from app.models.audit_log import AuditAction, AuditLog

    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    banner_id = await _banner_in_status(client, uid, status)
    try:
        deleted = await client.delete(f"/api/v1/banners/{banner_id}", headers=headers)
        assert deleted.status_code == 204, deleted.text
        assert await _banner_status(banner_id) is None
        again = await client.delete(f"/api/v1/banners/{banner_id}", headers=headers)
        assert again.status_code == 404
        # The audit trail survives the hard delete and records where it was.
        async with _session_mod.AsyncSessionLocal() as db:
            entry = await db.scalar(
                select(AuditLog).where(
                    AuditLog.entity_uuid == uuid.UUID(banner_id),
                    AuditLog.action == AuditAction.BANNER_DELETED,
                )
            )
        assert entry is not None
        assert entry.actor_role == "sub_admin"
        assert entry.detail == {"placement": "homepage", "from_status": status}
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_live_banner_cannot_be_deleted_or_archived_by_sub_admin(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    banner_id = await _banner_in_status(client, uid, "live")
    try:
        deleted = await client.delete(f"/api/v1/banners/{banner_id}", headers=sub_headers)
        assert deleted.status_code == 409
        assert deleted.json()["detail"] == "Live banners can only be taken down by an Admin."
        archived = await client.post(f"/api/v1/banners/{banner_id}/archive", headers=sub_headers)
        assert archived.status_code == 409
        assert archived.json()["detail"] == "Live banners can only be taken down by an Admin."
        assert await _banner_status(banner_id) == "live"

        # The Admin soft Remove is the take-down path, and it keeps the row.
        removed = await client.post(
            f"/api/v1/banners/{banner_id}/remove",
            json={"note": "Campaign ended early."},
            headers=admin_headers,
        )
        assert removed.status_code == 200, removed.text
        assert await _banner_status(banner_id) == "archived"
        # Removed rows are gone from the Sub Admin view: 404, not 409.
        after = await client.delete(f"/api/v1/banners/{banner_id}", headers=sub_headers)
        assert after.status_code == 404
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_admin_cannot_hard_delete_a_banner(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    banner_id = await _banner_in_status(client, uid, "pending_approval")
    try:
        res = await client.delete(
            f"/api/v1/banners/{banner_id}",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        assert res.status_code == 403
        assert await _banner_status(banner_id) == "pending_approval"
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_archived_banner_cannot_be_deleted(client: AsyncClient) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    banner_id = await _banner_in_status(client, uid, "approved")
    try:
        archived = await client.post(f"/api/v1/banners/{banner_id}/archive", headers=headers)
        assert archived.status_code == 200, archived.text
        deleted = await client.delete(f"/api/v1/banners/{banner_id}", headers=headers)
        assert deleted.status_code == 409
        assert await _banner_status(banner_id) == "archived"
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_approval", "rejected"])
async def test_sub_admin_can_still_archive_before_live(client: AsyncClient, status: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    banner_id = await _banner_in_status(client, uid, status)
    try:
        archived = await client.post(f"/api/v1/banners/{banner_id}/archive", headers=headers)
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
async def test_banner_with_a_pending_replacement_is_deleted_after_it(client: AsyncClient) -> None:
    """replaces_banner_id is immutable campaign identity, so the FK SET NULL
    cannot run: deleting the source first must be a clear 409, never a 500."""
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    source_id = await _banner_in_status(client, uid, "approved")
    try:
        replacement = await client.post(f"/api/v1/banners/{source_id}/replacement", headers=headers)
        assert replacement.status_code == 201, replacement.text
        replacement_id = replacement.json()["id"]

        blocked = await client.delete(f"/api/v1/banners/{source_id}", headers=headers)
        assert blocked.status_code == 409
        assert "replace" in blocked.json()["detail"]
        assert await _banner_status(source_id) == "approved"

        assert (
            await client.delete(f"/api/v1/banners/{replacement_id}", headers=headers)
        ).status_code == 204
        assert (
            await client.delete(f"/api/v1/banners/{source_id}", headers=headers)
        ).status_code == 204
    finally:
        await _delete_banners(source_id)


@pytest.mark.asyncio
async def test_approval_publishes_when_due_and_waits_for_a_future_start(
    client: AsyncClient,
) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    live_id = await _banner_in_status(client, uid, "live")
    future_id = await _banner_in_status(client, uid, "approved")
    try:
        assert await _banner_status(live_id) == "live"
        assert await _banner_status(future_id) == "approved"
        assert "banner_activated" not in await _audit_actions(future_id)
    finally:
        await _delete_banners(live_id, future_id)


@pytest.mark.asyncio
async def test_approval_respects_the_live_slot_and_replacements(client: AsyncClient) -> None:
    """A category slot holds one live campaign. Approving a second campaign
    for an occupied slot leaves it approved; approving the occupant
    replacement swaps them (the old one is archived), like the job does."""
    import app.db.session as _session_mod
    from app.models.banner import Banner, BannerPlacement, BannerStatus

    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    admin_headers = {"Authorization": f"Bearer {_admin_token(uid)}"}
    templates = (await client.get("/api/v1/banners/templates", headers=sub_headers)).json()[
        "templates"
    ]
    template = next(
        item
        for item in templates
        if item["placement"] == "financial_services" and item["category_key"] == "education-loan"
    )
    slot = (
        Banner.placement == BannerPlacement.FINANCIAL_SERVICES,
        Banner.category_key == template["category_key"],
        Banner.status == BannerStatus.LIVE,
        Banner.removed_at.is_(None),
    )
    # Park any leftover occupant from earlier runs so the slot starts empty.
    async with _session_mod.AsyncSessionLocal() as db:
        parked = list((await db.scalars(select(Banner.id).where(*slot))).all())
        if parked:
            await db.execute(
                update(Banner).where(Banner.id.in_(parked)).values(status=BannerStatus.ARCHIVED)
            )
            await db.commit()
    payload = {**_PAYLOAD, "placement": "financial_services", "template_id": template["id"]}
    banner_ids: list[str] = []
    try:
        occupant_id = await _banner_in_status(client, uid, "live", payload=payload)
        banner_ids.append(occupant_id)

        competitor_id = await _banner_in_status(client, uid, "pending_approval", payload=payload)
        banner_ids.append(competitor_id)
        competitor = await client.post(
            f"/api/v1/banners/{competitor_id}/approve", headers=admin_headers
        )
        assert competitor.status_code == 200, competitor.text
        assert competitor.json()["status"] == "approved"

        replacement = await client.post(
            f"/api/v1/banners/{occupant_id}/replacement", headers=sub_headers
        )
        assert replacement.status_code == 201, replacement.text
        replacement_id = replacement.json()["id"]
        banner_ids.append(replacement_id)
        assert (
            await client.post(f"/api/v1/banners/{replacement_id}/submit", headers=sub_headers)
        ).status_code == 200
        swapped = await client.post(
            f"/api/v1/banners/{replacement_id}/approve", headers=admin_headers
        )
        assert swapped.status_code == 200, swapped.text
        assert swapped.json()["status"] == "live"
        assert await _banner_status(occupant_id) == "archived"
        assert await _banner_status(competitor_id) == "approved"
    finally:
        await _delete_banners(*banner_ids)
        if parked:
            async with _session_mod.AsyncSessionLocal() as db:
                await db.execute(
                    update(Banner).where(Banner.id.in_(parked)).values(status=BannerStatus.LIVE)
                )
                await db.commit()


@pytest.mark.asyncio
async def test_approval_stays_approved_when_activation_loses_a_slot_race(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another approval or the job can fill an empty slot between the slot
    check and the write. The live-slot unique index then rejects the write;
    approval must still succeed and leave the banner approved for the job."""
    import app.db.session as _session_mod
    import app.services.banners as banners_service
    from app.models.banner import Banner, BannerPlacement, BannerStatus, BannerType

    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    sub_headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    templates = (await client.get("/api/v1/banners/templates", headers=sub_headers)).json()[
        "templates"
    ]
    template = next(
        item
        for item in templates
        if item["placement"] == "financial_services" and item["category_key"] == "education-loan"
    )
    slot = (
        Banner.placement == BannerPlacement.FINANCIAL_SERVICES,
        Banner.category_key == template["category_key"],
        Banner.status == BannerStatus.LIVE,
        Banner.removed_at.is_(None),
    )
    async with _session_mod.AsyncSessionLocal() as db:
        parked = list((await db.scalars(select(Banner.id).where(*slot))).all())
        if parked:
            await db.execute(
                update(Banner).where(Banner.id.in_(parked)).values(status=BannerStatus.ARCHIVED)
            )
        occupant = Banner(
            business_line="loans",
            banner_type=BannerType.DEFAULT,
            placement=BannerPlacement.FINANCIAL_SERVICES,
            category_key=template["category_key"],
            title=f"Slot occupant {uuid.uuid4()}",
            status=BannerStatus.LIVE,
            created_by_uuid=uuid.UUID(uid),
        )
        db.add(occupant)
        await db.commit()
        occupant_id = str(occupant.id)

    async def _write_without_slot_check(
        session: AsyncSession, banner_id: uuid.UUID, now: datetime | None = None
    ) -> bool:
        banner = await session.get(Banner, banner_id)
        assert banner is not None
        banner.status = BannerStatus.LIVE
        return True

    payload = {**_PAYLOAD, "placement": "financial_services", "template_id": template["id"]}
    banner_ids = [occupant_id]
    try:
        pending_id = await _banner_in_status(client, uid, "pending_approval", payload=payload)
        banner_ids.append(pending_id)
        monkeypatch.setattr(banners_service, "activate_banner_if_due", _write_without_slot_check)
        approved = await client.post(
            f"/api/v1/banners/{pending_id}/approve",
            headers={"Authorization": f"Bearer {_admin_token(uid)}"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert await _banner_status(pending_id) == "approved"
        assert await _banner_status(occupant_id) == "live"
        assert "banner_approved" in await _audit_actions(pending_id)
    finally:
        await _delete_banners(*banner_ids)
        if parked:
            async with _session_mod.AsyncSessionLocal() as db:
                await db.execute(
                    update(Banner).where(Banner.id.in_(parked)).values(status=BannerStatus.LIVE)
                )
                await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "deep_link",
    ["/loans", "/real-estate?city=hyderabad#top", "https://youtu.be/dQw4w9WgXcQ"],
)
async def test_cta_accepts_a_site_path_or_https_link(client: AsyncClient, deep_link: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    created = await client.post(
        "/api/v1/banners", json={**_PAYLOAD, "deep_link": deep_link}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["deep_link"] == deep_link
    banner_id = created.json()["id"]
    try:
        cleared = await client.patch(
            f"/api/v1/banners/{banner_id}", json={"deep_link": "  "}, headers=headers
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["deep_link"] is None
    finally:
        await _delete_banners(banner_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "deep_link",
    [
        "http://example.com/offer",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "https://u:p@example.com",
        "https://user@example.com",
        "//evil.example.com",
        "/\\evil.example.com",
        "https:/example.com",
        "https://example.com:99999/",
        "https://exa mple.com",
        " https://example.com",
        "loans",
    ],
)
async def test_cta_rejects_unsafe_links(client: AsyncClient, deep_link: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    uid = await _auth_user_uuid(mobile)
    headers = {"Authorization": f"Bearer {_sub_admin_token(uid)}"}
    created = await client.post(
        "/api/v1/banners", json={**_PAYLOAD, "deep_link": deep_link}, headers=headers
    )
    assert created.status_code == 422, f"{deep_link!r} -> {created.status_code}"

    draft = await client.post("/api/v1/banners", json=_PAYLOAD, headers=headers)
    banner_id = draft.json()["id"]
    try:
        patched = await client.patch(
            f"/api/v1/banners/{banner_id}", json={"deep_link": deep_link}, headers=headers
        )
        assert patched.status_code == 422, f"{deep_link!r} -> {patched.status_code}"
    finally:
        await _delete_banners(banner_id)
