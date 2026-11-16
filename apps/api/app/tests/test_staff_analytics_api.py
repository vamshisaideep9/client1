"""GET /api/v1/me/analytics — personal analytics per role.

Covers: the caller's own numbers only (another person's calls/tasks never
count), role gating (Client gets 403), the period clamp, and the response
shape every role shares.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from conftest import full_registration, unique_mobile


async def _seed_staff(role: str, business_line: str = "loans") -> tuple[str, str]:
    import app.db.session as _session_mod
    from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
    from app.models.user import User

    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name=role.title(),
            mobile=unique_mobile(),
            email=f"an_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole(role),
            scope=ProfileScope.LINE,
            business_line=business_line,
            staff_code=f"AN-{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return str(user.id), str(profile.id)


def _token(auth_uuid: str, role: str, **claims: str) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": auth_uuid,
            "role": role,
            "business_line": "loans",
            "platform_scope": "false",
            **claims,
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_lead_with_calls(staff_uuid: str, dispositions: list[str]) -> str:
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity

    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            name="Analytics Lead",
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.WORKING,
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=uuid.UUID(staff_uuid),
        )
        db.add(lead)
        await db.flush()
        for disposition in dispositions:
            db.add(
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=uuid.UUID(staff_uuid),
                    business_line="loans",
                    disposition=CallDisposition(disposition),
                    interest_level=InterestLevel.HOT if disposition == "connected" else None,
                )
            )
        await db.commit()
        return str(lead.id)


def _kpis(body: dict) -> dict[str, float | None]:
    return {kpi["key"]: kpi["value"] for kpi in body["kpis"]}


@pytest.mark.asyncio
async def test_telecaller_sees_only_own_calls_and_leads(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    _, other_staff = await _seed_staff("telecaller")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy", "no_answer", "connected"])
    await _seed_lead_with_calls(other_staff, ["connected", "connected", "connected"])

    res = await client.get(
        "/api/v1/me/analytics",
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["role"] == "telecaller"
    assert body["range_days"] == 30
    kpis = _kpis(body)
    assert kpis["calls"] == 4
    assert kpis["connect_rate"] == 50.0
    assert kpis["active_leads"] == 1

    points = body["trend"]["points"]
    assert len(points) == 30
    today = points[-1]["values"]
    assert today["connected"] == 2
    assert today["not_reached"] == 2
    assert [step["value"] for step in body["funnel"]["steps"]] == [1, 1, 0]
    interest = next(b for b in body["breakdowns"] if b["key"] == "interest")
    assert interest["items"] == [{"key": "hot", "label": "Hot", "value": 2.0}]


@pytest.mark.asyncio
async def test_period_is_clamped_to_supported_ranges(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    headers = _token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid)

    week = await client.get("/api/v1/me/analytics?days=7", headers=headers)
    assert week.json()["range_days"] == 7
    assert len(week.json()["trend"]["points"]) == 7
    odd = await client.get("/api/v1/me/analytics?days=45", headers=headers)
    assert odd.json()["range_days"] == 30
    too_big = await client.get("/api/v1/me/analytics?days=999", headers=headers)
    assert too_big.status_code == 422


@pytest.mark.asyncio
async def test_employee_sees_own_tasks_with_on_time_rate(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.task import Task, TaskStatus, TaskType

    auth_uuid, employee_uuid = await _seed_staff("employee")
    _, other_employee = await _seed_staff("employee")
    _, raiser = await _seed_staff("telecaller")
    now = datetime.now(UTC)

    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.WORKING,
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=uuid.UUID(raiser),
        )
        db.add(lead)
        await db.flush()

        def task(employee: str, status: TaskStatus, due: datetime | None) -> Task:
            return Task(
                raised_by_staff_profile_uuid=uuid.UUID(raiser),
                assigned_employee_profile_uuid=uuid.UUID(employee),
                business_line="loans",
                task_type=TaskType.DOCUMENT_COLLECTION,
                lead_uuid=lead.id,
                status=status,
                due_at=due,
            )

        db.add_all(
            [
                task(employee_uuid, TaskStatus.COMPLETED, now + timedelta(days=1)),
                task(employee_uuid, TaskStatus.COMPLETED, now - timedelta(days=1)),
                task(employee_uuid, TaskStatus.ASSIGNED, None),
                task(other_employee, TaskStatus.ASSIGNED, None),
            ]
        )
        await db.commit()

    res = await client.get(
        "/api/v1/me/analytics",
        headers=_token(auth_uuid, "employee", staff_profile_uuid=employee_uuid),
    )
    assert res.status_code == 200, res.text
    kpis = _kpis(res.json())
    assert kpis["open_tasks"] == 1
    assert kpis["completed"] == 2
    assert kpis["on_time"] == 50.0
    assert res.json()["trend"]["points"][-1]["values"] == {"assigned": 3, "completed": 2}


@pytest.mark.asyncio
async def test_agent_and_sub_admin_get_their_shape(client: AsyncClient) -> None:
    agent_auth, _ = await _seed_staff("telecaller")
    sub_admin_auth, _ = await _seed_staff("telecaller")
    agent = await client.get(
        "/api/v1/me/analytics",
        headers=_token(agent_auth, "agent", agent_profile_uuid=str(uuid.uuid4())),
    )
    assert agent.status_code == 200, agent.text
    assert agent.json()["role"] == "agent"
    assert {kpi["key"] for kpi in agent.json()["kpis"]} >= {"introduced", "paid", "pending"}

    sub_admin = await client.get(
        "/api/v1/me/analytics", headers=_token(sub_admin_auth, "sub_admin")
    )
    assert sub_admin.status_code == 200, sub_admin.text
    assert sub_admin.json()["role"] == "sub_admin"
    assert sub_admin.json()["funnel"] is None


@pytest.mark.asyncio
async def test_agent_commission_breakdown_leaves_out_cancelled(client: AsyncClient) -> None:
    """CS-021: "Commission by status" shows pending and paid money only."""
    from sqlalchemy import text

    import app.db.session as _session_mod

    from .test_commission_rls import _seed_agent, _seed_commission

    agent_auth, agent_profile = await _seed_agent("loans")
    statuses = {"pending": None, "paid": None, "cancelled": None}
    for status in statuses:
        statuses[status] = await _seed_commission(agent_auth, agent_profile, "loans")
    async with _session_mod.AsyncSessionLocal() as db:
        for status, commission_id in statuses.items():
            await db.execute(
                text(
                    "UPDATE commissions SET status = CAST(:status AS commission_status) "
                    "WHERE id = :id"
                ),
                {"status": status, "id": commission_id},
            )
        await db.commit()

    res = await client.get(
        "/api/v1/me/analytics",
        headers=_token(agent_auth, "agent", agent_profile_uuid=agent_profile),
    )
    assert res.status_code == 200, res.text
    breakdown = next(b for b in res.json()["breakdowns"] if b["key"] == "commission")
    assert {item["key"] for item in breakdown["items"]} == {"pending", "paid"}
    kpis = _kpis(res.json())
    assert kpis["paid"] == 500
    assert kpis["pending"] == 500


@pytest.mark.asyncio
async def test_clients_and_unauthenticated_callers_are_refused(client: AsyncClient) -> None:
    staff_auth, _ = await _seed_staff("telecaller")
    assert (await client.get("/api/v1/me/analytics")).status_code == 401
    token, _ = await full_registration(client, lines=["loans"])
    res = await client.get("/api/v1/me/analytics", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403

    staff_without_profile = await client.get(
        "/api/v1/me/analytics", headers=_token(staff_auth, "telecaller")
    )
    assert staff_without_profile.status_code == 403


# --- Calendar date range and filters ------------------------------------------


def _ist_today():
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


@pytest.mark.asyncio
async def test_explicit_date_range_sets_the_period_and_daily_points(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy"])
    today = _ist_today()
    start = today - timedelta(days=13)

    res = await client.get(
        "/api/v1/me/analytics",
        params={"date_from": start.isoformat(), "date_to": today.isoformat()},
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["date_from"], body["date_to"]) == (start.isoformat(), today.isoformat())
    assert body["range_days"] == 14
    assert body["bucket"] == "day"
    assert len(body["trend"]["points"]) == 14
    assert _kpis(body)["calls"] == 2


@pytest.mark.asyncio
async def test_past_range_excludes_todays_calls(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy"])
    end = _ist_today() - timedelta(days=1)

    res = await client.get(
        "/api/v1/me/analytics",
        params={"date_from": (end - timedelta(days=6)).isoformat(), "date_to": end.isoformat()},
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )

    assert res.status_code == 200, res.text
    assert _kpis(res.json())["calls"] == 0


@pytest.mark.asyncio
async def test_long_ranges_switch_to_weekly_points(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    today = _ist_today()
    start = today - timedelta(days=199)

    res = await client.get(
        "/api/v1/me/analytics",
        params={"date_from": start.isoformat(), "date_to": today.isoformat()},
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bucket"] == "week"
    days = [point["day"] for point in body["trend"]["points"]]
    assert days[0] == start.isoformat()
    assert 28 <= len(days) <= 30
    # Every point after the first starts on a Monday.
    assert all(datetime.fromisoformat(day).weekday() == 0 for day in days[1:])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-01-10"},
        {"date_from": "2026-02-01", "date_to": "2026-01-01"},
        {"date_from": "2024-01-01", "date_to": "2025-06-30"},
        {"date_from": "2026-01-01", "date_to": "2099-01-01"},
    ],
)
async def test_invalid_ranges_are_rejected(client: AsyncClient, params: dict[str, str]) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")

    res = await client.get(
        "/api/v1/me/analytics",
        params=params,
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_telecaller_call_status_and_interest_filters_narrow_calls(
    client: AsyncClient,
) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy", "no_answer", "connected"])
    headers = _token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid)

    busy = await client.get("/api/v1/me/analytics?call_status=busy", headers=headers)
    hot = await client.get("/api/v1/me/analytics?interest=hot", headers=headers)
    cold = await client.get("/api/v1/me/analytics?interest=cold", headers=headers)

    assert _kpis(busy.json())["calls"] == 1
    assert _kpis(hot.json())["calls"] == 2
    assert _kpis(cold.json())["calls"] == 0


@pytest.mark.asyncio
async def test_telecaller_loan_status_and_source_filters_narrow_leads(
    client: AsyncClient,
) -> None:
    from app.tests.test_telecaller_api import _seed_client_referral, _seed_loan_application

    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    with_loan = await _seed_lead_with_calls(staff_uuid, ["connected"])
    referred = await _seed_lead_with_calls(staff_uuid, ["busy", "busy"])
    await _seed_loan_application(with_loan)
    await _seed_client_referral(referred)
    headers = _token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid)

    by_loan = await client.get("/api/v1/me/analytics?loan_status=new", headers=headers)
    by_client = await client.get("/api/v1/me/analytics?lead_source=client", headers=headers)
    by_agent = await client.get("/api/v1/me/analytics?lead_source=agent", headers=headers)

    assert by_loan.status_code == 200, by_loan.text
    assert (_kpis(by_loan.json())["calls"], _kpis(by_loan.json())["active_leads"]) == (1, 1)
    assert (_kpis(by_client.json())["calls"], _kpis(by_client.json())["active_leads"]) == (2, 1)
    assert _kpis(by_agent.json())["active_leads"] == 0


@pytest.mark.asyncio
async def test_filters_outside_the_role_are_rejected(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("employee")

    res = await client.get(
        "/api/v1/me/analytics?call_status=busy",
        headers=_token(auth_uuid, "employee", staff_profile_uuid=staff_uuid),
    )

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_business_line_follows_the_selected_line(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller", "both")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy"])  # loans calls
    token = _token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid, business_line="both")

    loans = await client.get("/api/v1/me/analytics", headers={**token, "X-Business-Line": "loans"})
    real_estate = await client.get(
        "/api/v1/me/analytics", headers={**token, "X-Business-Line": "real_estate"}
    )

    assert _kpis(loans.json())["calls"] == 2
    assert _kpis(real_estate.json())["calls"] == 0


# --- Sub Admin content filters ------------------------------------------------


async def _seed_sub_admin_content(author: str) -> None:
    """Four banners and six offers with mixed status, placement, type and discount."""
    import app.db.session as _session_mod
    from app.models.banner import Banner, BannerPlacement, BannerStatus, BannerType
    from app.models.offer import Offer, OfferStatus

    banners = [
        (BannerStatus.LIVE, BannerPlacement.HOMEPAGE, BannerType.DEFAULT),
        (BannerStatus.PENDING_APPROVAL, BannerPlacement.DASHBOARD, BannerType.PERSONALIZED),
        (BannerStatus.ARCHIVED, BannerPlacement.HOMEPAGE, BannerType.ACTION),
        (BannerStatus.APPROVED, BannerPlacement.PROPERTIES, BannerType.DEFAULT),
    ]
    offers = [
        (OfferStatus.ACTIVE, "percentage"),
        (OfferStatus.SCHEDULED, "flat"),
        (OfferStatus.APPROVED, "percentage"),
        (OfferStatus.EXPIRED, "cashback-tie"),
        (OfferStatus.DRAFT, "flat"),
        (OfferStatus.REJECTED, "percentage"),
    ]
    async with _session_mod.AsyncSessionLocal() as db:
        for status, placement, banner_type in banners:
            db.add(
                Banner(
                    business_line="loans",
                    placement=placement,
                    banner_type=banner_type,
                    title="Analytics banner",
                    audience_rules={},
                    status=status,
                    created_by_uuid=uuid.UUID(author),
                )
            )
        for status, discount_type in offers:
            db.add(
                Offer(
                    business_line="loans",
                    title="Analytics offer",
                    discount_type=discount_type,
                    discount_value=10,
                    status=status,
                    created_by_uuid=uuid.UUID(author),
                )
            )
        await db.commit()


def _trend_totals(body: dict) -> dict[str, int]:
    totals: dict[str, int] = {}
    for point in body["trend"]["points"]:
        for key, value in point["values"].items():
            totals[key] = totals.get(key, 0) + value
    return totals


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "created"),
    [
        ("", 10),
        ("content_type=banners", 4),
        ("content_type=offers", 6),
        ("content_status=draft", 1),
        ("content_status=pending_approval", 1),
        ("content_status=rejected", 1),
        # Offers fold into the shared vocabulary: scheduled is approved,
        # active is live and expired is archived.
        ("content_status=approved", 3),
        ("content_status=live", 2),
        ("content_status=archived", 2),
        ("placement=homepage", 2),
        ("banner_type=default", 2),
        ("discount_type=percentage", 3),
        ("discount_type=cashback-tie", 1),
        ("content_type=offers&content_status=approved", 2),
        ("placement=homepage&content_status=live", 1),
        # Contradictions return nothing rather than an error.
        ("content_type=offers&placement=homepage", 0),
        ("content_type=banners&discount_type=flat", 0),
        ("placement=homepage&discount_type=flat", 0),
    ],
)
async def test_sub_admin_content_filters_narrow_own_content(
    client: AsyncClient, query: str, created: int
) -> None:
    auth_uuid, _ = await _seed_staff("telecaller")
    other_auth, _ = await _seed_staff("telecaller")
    await _seed_sub_admin_content(auth_uuid)
    await _seed_sub_admin_content(other_auth)

    res = await client.get(f"/api/v1/me/analytics?{query}", headers=_token(auth_uuid, "sub_admin"))

    assert res.status_code == 200, res.text
    body = res.json()
    assert _kpis(body)["created"] == created
    assert sum(_trend_totals(body).values()) == created


@pytest.mark.asyncio
async def test_sub_admin_filters_narrow_kpis_trend_and_breakdowns(client: AsyncClient) -> None:
    auth_uuid, _ = await _seed_staff("telecaller")
    await _seed_sub_admin_content(auth_uuid)
    headers = _token(auth_uuid, "sub_admin")

    offers = (await client.get("/api/v1/me/analytics?content_type=offers", headers=headers)).json()
    assert _trend_totals(offers) == {"banners": 0, "offers": 6}
    banner_status = next(b for b in offers["breakdowns"] if b["key"] == "banner_status")
    assert banner_status["items"] == []
    kpis = _kpis(offers)
    assert (kpis["live"], kpis["pending"]) == (1, 0)
    # Reviewed offers: approved, scheduled and active against one rejected.
    assert kpis["approval_rate"] == 75.0

    live = (await client.get("/api/v1/me/analytics?content_status=live", headers=headers)).json()
    assert _kpis(live)["live"] == 2
    offer_status = next(b for b in live["breakdowns"] if b["key"] == "offer_status")
    assert offer_status["items"] == [{"key": "active", "label": "Active", "value": 1.0}]


@pytest.mark.asyncio
async def test_sub_admin_never_counts_another_sub_admins_content(client: AsyncClient) -> None:
    auth_uuid, _ = await _seed_staff("telecaller")
    other_auth, _ = await _seed_staff("telecaller")
    await _seed_sub_admin_content(other_auth)

    for query in ("", "content_type=banners", "content_status=live", "placement=homepage"):
        res = await client.get(
            f"/api/v1/me/analytics?{query}", headers=_token(auth_uuid, "sub_admin")
        )
        assert res.status_code == 200, res.text
        assert _kpis(res.json())["created"] == 0
        assert _kpis(res.json())["live"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "query"),
    [
        ("telecaller", "content_status=live"),
        ("telecaller", "discount_type=flat"),
        ("employee", "placement=homepage"),
        ("agent", "content_type=banners"),
        ("sub_admin", "call_status=busy"),
        ("sub_admin", "task_type=property_visit"),
        # Values outside the shared vocabulary are rejected, not ignored.
        ("sub_admin", "content_status=active"),
        ("sub_admin", "content_type=properties"),
    ],
)
async def test_sub_admin_filters_are_role_gated(client: AsyncClient, role: str, query: str) -> None:
    auth_uuid, staff_uuid = await _seed_staff("employee" if role == "employee" else "telecaller")
    claims = {
        "telecaller": {"staff_profile_uuid": staff_uuid},
        "employee": {"staff_profile_uuid": staff_uuid},
        "agent": {"agent_profile_uuid": str(uuid.uuid4())},
        "sub_admin": {},
    }[role]

    res = await client.get(
        f"/api/v1/me/analytics?{query}", headers=_token(auth_uuid, role, **claims)
    )

    assert res.status_code == 422
