"""Batch 3: independent routing pools and specialty authorization."""

import asyncio
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

import app.db.session as sessions
from app.models.audit_log import AuditAction, AuditLog
from app.models.lead import Lead, LeadAssignmentCursor, LeadStatus
from app.models.loan import LoanApplication, LoanType
from app.models.profile import ProfileStatus, StaffProfile
from app.models.user import User, UserStatus
from app.services.leads import auto_assign_locked_lead, ensure_client_line_lead
from app.tests.test_admin_hierarchy_api import _headers, _primary_admin, _sub_admin
from app.tests.test_lead_auto_assignment import (
    _isolate_eligible_telecallers,  # noqa: F401 - reuse the isolation fixture
    _seed_telecaller,
)
from conftest import unique_email, unique_mobile


async def product(*, active: bool = True, category: str = "loan") -> LoanType:
    async with sessions.AsyncSessionLocal() as db:
        row = LoanType(
            name=f"specialty-{uuid4().hex}",
            label=f"Specialty {uuid4().hex}",
            active=active,
            category=category,
        )
        db.add(row)
        await db.commit()
        return row


async def specialize(profile: StaffProfile, product_id) -> None:
    async with sessions.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == profile.id)
            .values(loan_specialty_id=product_id)
        )
        await db.commit()


async def assign(*, requirement=None, line="loans", product_id=None, commit=True):
    async with sessions.AsyncSessionLocal() as db:
        row = Lead(mobile=unique_mobile(), business_line=line, requirement=requirement)
        db.add(row)
        await db.flush()
        await auto_assign_locked_lead(db, row, product_id=product_id)
        result = row.assigned_telecaller_profile_uuid
        if commit:
            await db.commit()
        else:
            await db.rollback()
        return result


@pytest.mark.asyncio
async def test_specialist_pools_rotate_independently_and_rollback() -> None:
    first, second = await product(), await product()
    a, b, c, d = [await _seed_telecaller() for _ in range(4)]
    for tc in (a, b):
        await specialize(tc, first.id)
    for tc in (c, d):
        await specialize(tc, second.id)
    assert await assign(product_id=first.id, commit=False) == a.id
    assert await assign(product_id=first.id) == a.id
    assert await assign(requirement={"product_slug": second.name}) == c.id
    assert await assign(requirement={"product": first.label.upper()}) == b.id
    assert await assign(product_id=second.id) == d.id
    assert await assign(product_id=first.id) == a.id
    async with sessions.AsyncSessionLocal() as db:
        pools = list(
            await db.scalars(
                select(LeadAssignmentCursor.pool).where(
                    LeadAssignmentCursor.pool.in_([f"product:{first.id}", f"product:{second.id}"])
                )
            )
        )
        assert len(pools) == 2


@pytest.mark.asyncio
async def test_shared_unspecialised_and_all_fallbacks_have_separate_cursors() -> None:
    first, second, third = await product(), await product(), await product()
    specialist, a, b = [await _seed_telecaller() for _ in range(3)]
    await specialize(specialist, third.id)
    assert await assign(product_id=first.id) == a.id
    assert await assign(product_id=second.id) == b.id
    assert await assign(requirement={"product_slug": "unknown"}) == specialist.id
    assert await assign(product_id=first.id) == a.id
    assert await assign() == a.id  # the all-pool advances independently
    for tc in (a, b):
        await specialize(tc, third.id)
    assert await assign(product_id=first.id) == b.id  # no generalists: all pool


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["inactive", "suspended", "deleted", "cross_line"])
async def test_ineligible_specialists_fall_back(invalid: str) -> None:
    p = await product()
    tc = await _seed_telecaller("real_estate" if invalid == "cross_line" else "loans")
    if invalid != "cross_line":
        await specialize(tc, p.id)
    fallback = await _seed_telecaller("both")
    async with sessions.AsyncSessionLocal() as db:
        if invalid == "inactive":
            await db.execute(
                update(StaffProfile)
                .where(StaffProfile.id == tc.id)
                .values(status=ProfileStatus.INACTIVE)
            )
        elif invalid in ("suspended", "deleted"):
            await db.execute(
                update(User)
                .where(User.id == tc.auth_user_uuid)
                .values(
                    status=UserStatus.SUSPENDED
                    if invalid == "suspended"
                    else UserStatus.SOFT_DELETED
                )
            )
        await db.commit()
    assert await assign(product_id=p.id) == fallback.id


@pytest.mark.asyncio
async def test_dual_line_specialist_does_not_restrict_real_estate() -> None:
    p = await product()
    both = await _seed_telecaller("both")
    await specialize(both, p.id)
    await _seed_telecaller("loans")
    assert await assign(line="real_estate", product_id=p.id) == both.id


@pytest.mark.asyncio
async def test_concurrent_specialist_turns_commit_once() -> None:
    p = await product()
    a, b = await _seed_telecaller(), await _seed_telecaller()
    await specialize(a, p.id)
    await specialize(b, p.id)
    results = await asyncio.gather(*(assign(product_id=p.id) for _ in range(8)))
    assert Counter(results) == {a.id: 4, b.id: 4}


@pytest.mark.asyncio
async def test_retry_resolves_existing_application_and_preserves_assignment() -> None:
    from app.jobs.assign_unassigned_leads import _assign_batch
    from app.models.profile import ClientProfile

    p = await product()
    async with sessions.AsyncSessionLocal() as db:
        user = User(
            first_name="Synthetic",
            last_name="Client",
            mobile=unique_mobile(),
            email=unique_email(),
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = ClientProfile(
            auth_user_uuid=user.id, business_line="loans", customer_code=f"C-{uuid4().hex}"
        )
        db.add(profile)
        await db.commit()
    lead_id = await ensure_client_line_lead(
        mobile=user.mobile, client_profile_uuid=profile.id, business_line="loans"
    )
    async with sessions.AsyncSessionLocal() as db:
        queued = await db.get(Lead, lead_id)
        # The retry worker intentionally visits only the oldest 200 leads.
        # Give this scenario priority over earlier integration-test data.
        queued.created_at = datetime(2000, 1, 1, tzinfo=UTC)
        db.add(
            LoanApplication(
                lead_uuid=lead_id,
                client_profile_uuid=profile.id,
                business_line="loans",
                loan_type_id=p.id,
                amount_requested=100000,
            )
        )
        await db.commit()
    general, specialist = await _seed_telecaller(), await _seed_telecaller()
    await specialize(specialist, p.id)
    async with sessions.AsyncSessionLocal() as db:
        _, notices = await _assign_batch(db)
        assert any(notice.lead_id == lead_id for notice in notices)
    async with sessions.AsyncSessionLocal() as db:
        lead = await db.get(Lead, lead_id)
        assert lead.assigned_telecaller_profile_uuid == specialist.id
        await specialize(specialist, None)
        notice = await auto_assign_locked_lead(db, lead, product_id=p.id)
        assert notice is None
        assert lead.assigned_telecaller_profile_uuid != general.id


@pytest.mark.asyncio
async def test_trusted_initial_product_hint_and_ambiguous_public_label() -> None:
    from app.models.profile import ClientProfile

    p = await product()
    await _seed_telecaller()
    specialist = await _seed_telecaller()
    await specialize(specialist, p.id)
    async with sessions.AsyncSessionLocal() as db:
        user = User(
            first_name="Synthetic",
            last_name="Client",
            mobile=unique_mobile(),
            email=unique_email(),
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = ClientProfile(
            auth_user_uuid=user.id, business_line="loans", customer_code=f"C-{uuid4().hex}"
        )
        db.add(profile)
        await db.commit()
    lead_id = await ensure_client_line_lead(
        mobile=user.mobile, client_profile_uuid=profile.id, business_line="loans", product_id=p.id
    )
    async with sessions.AsyncSessionLocal() as db:
        assert (await db.get(Lead, lead_id)).assigned_telecaller_profile_uuid == specialist.id
        duplicate = await product()
        await db.execute(update(LoanType).where(LoanType.id == duplicate.id).values(label=p.label))
        await db.commit()
    async with sessions.AsyncSessionLocal() as db:
        from app.services.leads import _routing_product_id

        assert (
            await _routing_product_id(
                db, Lead(business_line="loans", requirement={"product": p.label}), None
            )
            is None
        )


@pytest.mark.asyncio
async def test_admin_specialty_create_edit_clear_and_denials(client: AsyncClient) -> None:
    token, _, _ = await _primary_admin(client)
    p, other = await product(), await product()
    res = await client.post(
        "/api/v1/admin/users/create",
        headers=_headers(token),
        json={
            "first_name": "Synthetic",
            "last_name": "Specialist",
            "mobile": unique_mobile(),
            "email": unique_email(),
            "role": "telecaller",
            "business_line": "both",
            "loan_specialty_id": str(p.id),
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["loan_specialty_id"] == str(p.id)
    user_id = res.json()["auth_user_uuid"]
    path = f"/api/v1/admin/users/{user_id}/loan-specialty"
    sub, *_ = await _sub_admin(client)
    denied = await client.patch(
        path, headers=_headers(sub), json={"loan_specialty_id": str(other.id)}
    )
    assert denied.status_code == 403
    for value in (str(other.id), None):
        changed = await client.patch(
            path, headers=_headers(token), json={"loan_specialty_id": value}
        )
        assert changed.status_code == 200, changed.text
        assert changed.headers["cache-control"] == "private, no-store"
        assert changed.json()[0]["loan_specialty_id"] == value
    directory = await client.get(
        "/api/v1/admin/users", headers=_headers(token), params={"search": res.json()["mobile"]}
    )
    assert directory.status_code == 200
    assert directory.json()["users"][0]["role_profiles"][0]["code"] == res.json()["staff_code"]
    async with sessions.AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(AuditLog.action).where(
                    AuditLog.action == AuditAction.STAFF_SPECIALTY_UPDATED
                )
            )
        )
        assert len(actions) >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["inactive", "card", "missing", "wrong_role", "wrong_line"])
async def test_specialty_validation_rejects_invalid_targets(
    client: AsyncClient, invalid: str
) -> None:
    token, *_ = await _primary_admin(client)
    p = await product(
        active=invalid != "inactive", category="credit_card" if invalid == "card" else "loan"
    )
    res = await client.post(
        "/api/v1/admin/users/create",
        headers=_headers(token),
        json={
            "first_name": "Synthetic",
            "last_name": "Invalid",
            "mobile": unique_mobile(),
            "email": unique_email(),
            "role": "employee" if invalid == "wrong_role" else "telecaller",
            "business_line": "real_estate" if invalid == "wrong_line" else "loans",
            "loan_specialty_id": str(uuid4() if invalid == "missing" else p.id),
        },
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_database_rejects_non_admin_specialty_write() -> None:
    tc = await _seed_telecaller()
    p = await product()
    async with sessions.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        await db.execute(
            text(
                "SELECT set_config('app.auth_user_uuid', :u, true), "
                "set_config('app.role', 'telecaller', true), "
                "set_config('app.business_line', 'loans', true), "
                "set_config('app.staff_profile_uuid', :p, true), "
                "set_config('app.platform_scope', 'false', true)"
            ),
            {"u": str(tc.auth_user_uuid), "p": str(tc.id)},
        )
        with pytest.raises(DBAPIError):
            await db.execute(
                update(StaffProfile).where(StaffProfile.id == tc.id).values(loan_specialty_id=p.id)
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_public_agent_and_application_capture_route_by_product(client: AsyncClient) -> None:
    from app.services.leads import capture_agent_lead, capture_lead
    from app.tests.test_lead_auto_assignment import _seed_agent
    from conftest import full_registration, loan_application_payload

    auth, _ = await full_registration(client, lines=["loans"])
    payload = await loan_application_payload(client, auth)
    await _seed_telecaller()
    specialist = await _seed_telecaller()
    await specialize(specialist, UUID(payload["loan_type_id"]))
    application = await client.post(
        "/api/v1/loans/applications", headers=_headers(auth), json=payload
    )
    assert application.status_code == 201, application.text
    async with sessions.AsyncSessionLocal() as db:
        row = await db.get(LoanApplication, UUID(application.json()["id"]))
        assert (await db.get(Lead, row.lead_uuid)).assigned_telecaller_profile_uuid == specialist.id
        p = await db.get(LoanType, UUID(payload["loan_type_id"]))
    mobile = unique_mobile()
    assert await capture_lead(mobile, business_line="loans", requirement={"product": p.label})
    agent = await _seed_agent()
    introduced = await capture_agent_lead(
        mobile=unique_mobile(),
        business_line="loans",
        agent_profile_uuid=agent.id,
        name="Synthetic prospect",
        requirement={"product_slug": p.name},
    )
    async with sessions.AsyncSessionLocal() as db:
        public = await db.scalar(select(Lead).where(Lead.mobile == mobile))
        assert public.assigned_telecaller_profile_uuid == specialist.id
        assert (await db.get(Lead, introduced.id)).assigned_telecaller_profile_uuid == specialist.id


@pytest.mark.asyncio
async def test_sticky_resubmit_ignores_changed_specialty_and_leaves_pools_unchanged() -> None:
    from app.services.leads import sticky_assign_locked_lead

    p, other = await product(), await product()
    tc = await _seed_telecaller()
    await specialize(tc, other.id)
    async with sessions.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(), business_line="loans", requirement={"product_slug": p.name}
        )
        db.add(lead)
        await db.flush()
        # Remembering the released assignee requires the guarded clear transition.
        lead.assigned_telecaller_profile_uuid = tc.id
        lead.status = LeadStatus.ASSIGNED
        await db.flush()
        lead.last_telecaller_profile_uuid = tc.id
        lead.assigned_telecaller_profile_uuid = None
        lead.status = LeadStatus.RELEASED
        await db.flush()
        before = list(
            (
                await db.execute(
                    select(
                        LeadAssignmentCursor.business_line,
                        LeadAssignmentCursor.pool,
                        LeadAssignmentCursor.last_telecaller_profile_uuid,
                    )
                )
            ).all()
        )
        assert await sticky_assign_locked_lead(db, lead)
        assert lead.assigned_telecaller_profile_uuid == tc.id
        after = list(
            (
                await db.execute(
                    select(
                        LeadAssignmentCursor.business_line,
                        LeadAssignmentCursor.pool,
                        LeadAssignmentCursor.last_telecaller_profile_uuid,
                    )
                )
            ).all()
        )
        assert before == after


@pytest.mark.asyncio
async def test_card_enquiry_uses_all_pool_despite_an_existing_unassigned_loan(
    client: AsyncClient,
) -> None:
    from app.tests.test_financial_product_forms_api import _credit_card_answers, _products
    from conftest import full_registration, loan_application_payload

    auth, _ = await full_registration(client, lines=["loans"])
    payload = await loan_application_payload(client, auth)
    application = await client.post(
        "/api/v1/loans/applications", headers=_headers(auth), json=payload
    )
    assert application.status_code == 201, application.text
    general, specialist = await _seed_telecaller(), await _seed_telecaller()
    await specialize(specialist, UUID(payload["loan_type_id"]))
    card = next(item for item in await _products(client, auth) if item["name"] == "credit-cards")
    enquiry = await client.post(
        "/api/v1/loans/enquiries",
        headers=_headers(auth),
        json={
            "product_id": card["id"],
            "form_version": card["form_version"],
            "answers": _credit_card_answers(),
        },
    )
    assert enquiry.status_code == 201, enquiry.text
    async with sessions.AsyncSessionLocal() as db:
        row = await db.get(LoanApplication, UUID(application.json()["id"]))
        lead = await db.get(Lead, row.lead_uuid)
        assert lead.assigned_telecaller_profile_uuid == general.id
