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
from app.models.loan import LoanApplication, LoanStatus, LoanType
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
        from app.services.leads import resolve_lead_product_id

        assert (
            await resolve_lead_product_id(
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
@pytest.mark.parametrize(
    "invalid",
    ["inactive", "missing", "sub_admin", "non_staff", "wrong_line", "officer_wrong_line"],
)
async def test_specialty_validation_rejects_invalid_targets(
    client: AsyncClient, invalid: str
) -> None:
    token, *_ = await _primary_admin(client)
    p = await product(active=invalid != "inactive", category="insurance")
    role = {"sub_admin": "sub_admin", "non_staff": "agent", "officer_wrong_line": "employee"}
    line = {"sub_admin": None, "wrong_line": "real_estate", "officer_wrong_line": "real_estate"}
    res = await client.post(
        "/api/v1/admin/users/create",
        headers=_headers(token),
        json={
            "first_name": "Synthetic",
            "last_name": "Invalid",
            "mobile": unique_mobile(),
            "email": unique_email(),
            "role": role.get(invalid, "telecaller"),
            "business_line": line.get(invalid, "loans"),
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
    # Other integration scenarios deliberately share the Personal Loan label.
    # Public label routing needs its own unambiguous catalogue fixture.
    p = await product()
    await specialize(specialist, p.id)
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
async def test_card_enquiry_routes_to_card_specialist_and_keeps_first_product(
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
    card_specialist = await _seed_telecaller()
    await specialize(specialist, UUID(payload["loan_type_id"]))
    card = next(item for item in await _products(client, auth) if item["name"] == "credit-cards")
    await specialize(card_specialist, UUID(card["id"]))
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
        # Cards are specialties now: the enquiry's trusted product routes it.
        assert lead.assigned_telecaller_profile_uuid == card_specialist.id
        assert lead.assigned_telecaller_profile_uuid != general.id
        # The first application already classified the lead; it is kept.
        assert lead.product_id == UUID(payload["loan_type_id"])


# ---------------------------------------------------------------------------
# Product specialists (2026-11-26): every category, Officers, stored products
# ---------------------------------------------------------------------------


async def _client_profile():
    from app.models.profile import ClientProfile

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
        return user, profile


async def _lead_product(lead_id) -> UUID | None:
    async with sessions.AsyncSessionLocal() as db:
        return (await db.get(Lead, lead_id)).product_id


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["credit_card", "insurance"])
async def test_card_and_insurance_specialists_receive_their_leads(category: str) -> None:
    p, loan = await product(category=category), await product()
    general, specialist, loan_specialist = [await _seed_telecaller() for _ in range(3)]
    await specialize(specialist, p.id)
    await specialize(loan_specialist, loan.id)
    assert await assign(product_id=p.id) == specialist.id
    assert await assign(requirement={"product_slug": p.name}) == specialist.id
    assert await assign(requirement={"product": p.label}) == specialist.id
    # Loans still reach their own specialist; unknown products the generalists.
    assert await assign(product_id=loan.id) == loan_specialist.id
    assert await assign(requirement={"product_slug": "unknown"}) == general.id


@pytest.mark.asyncio
async def test_inactive_product_hint_routes_to_unspecialised_staff() -> None:
    p = await product()
    general, specialist = await _seed_telecaller(), await _seed_telecaller()
    await specialize(specialist, p.id)
    async with sessions.AsyncSessionLocal() as db:
        await db.execute(update(LoanType).where(LoanType.id == p.id).values(active=False))
        await db.commit()
    assert await assign(product_id=p.id) == general.id


@pytest.mark.asyncio
async def test_capture_stores_the_product_even_without_staff() -> None:
    from app.services.leads import capture_agent_lead, capture_lead
    from app.tests.test_lead_auto_assignment import _seed_agent

    p, insurance = await product(), await product(category="insurance")
    mobile, estate = unique_mobile(), unique_mobile()
    assert await capture_lead(mobile, business_line="loans", requirement={"product_slug": p.name})
    agent = await _seed_agent()
    introduced = await capture_agent_lead(
        mobile=unique_mobile(),
        business_line="loans",
        agent_profile_uuid=agent.id,
        name="Synthetic prospect",
        requirement={"product_slug": insurance.name},
    )
    assert await capture_lead(estate, business_line="real_estate", requirement={"notes": "plot"})
    async with sessions.AsyncSessionLocal() as db:
        public = await db.scalar(select(Lead).where(Lead.mobile == mobile))
        assert public.assigned_telecaller_profile_uuid is None  # nobody eligible yet
        assert public.product_id == p.id
        assert (await db.get(Lead, introduced.id)).product_id == insurance.id
        assert (await db.scalar(select(Lead).where(Lead.mobile == estate))).product_id is None


@pytest.mark.asyncio
async def test_first_application_classifies_an_assigned_lead_once() -> None:
    tc = await _seed_telecaller()
    first, second = await product(), await product(category="credit_card")
    user, profile = await _client_profile()
    lead_id = await ensure_client_line_lead(
        mobile=user.mobile, client_profile_uuid=profile.id, business_line="loans"
    )
    async with sessions.AsyncSessionLocal() as db:
        lead = await db.get(Lead, lead_id)
        assert lead.assigned_telecaller_profile_uuid == tc.id
        assert lead.product_id is None
    for hint in (first.id, second.id):
        await ensure_client_line_lead(
            mobile=user.mobile,
            client_profile_uuid=profile.id,
            business_line="loans",
            product_id=hint,
        )
    # The first application or enquiry classifies the lead; later ones never overwrite.
    assert await _lead_product(lead_id) == first.id


@pytest.mark.asyncio
async def test_ambiguous_existing_requests_leave_the_lead_unclassified() -> None:
    first, second, third = await product(), await product(), await product()
    user, profile = await _client_profile()
    async with sessions.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=user.mobile,
            business_line="loans",
            client_profile_uuid=profile.id,
            status=LeadStatus.CONVERTED,
        )
        db.add(lead)
        await db.flush()
        for p in (first, second):
            db.add(
                LoanApplication(
                    lead_uuid=lead.id,
                    client_profile_uuid=profile.id,
                    business_line="loans",
                    loan_type_id=p.id,
                    amount_requested=100000,
                    status=LoanStatus.CLOSED,
                )
            )
        await db.commit()
    async with sessions.AsyncSessionLocal() as db:
        locked = await db.get(Lead, lead.id)
        # Two earlier products: neither resolution nor a conflicting hint classifies it.
        assert await auto_assign_locked_lead(db, locked) is None
        assert await auto_assign_locked_lead(db, locked, product_id=third.id) is None
        assert locked.product_id is None
        await db.commit()
    assert await _lead_product(lead.id) is None


@pytest.mark.asyncio
async def test_admin_creates_and_edits_officer_specialties(client: AsyncClient) -> None:
    token, _, _ = await _primary_admin(client)
    insurance, card = await product(category="insurance"), await product(category="credit_card")
    created = {}
    for role, line, p in (("employee", "loans", insurance), ("telecaller", "both", card)):
        res = await client.post(
            "/api/v1/admin/users/create",
            headers=_headers(token),
            json={
                "first_name": "Synthetic",
                "last_name": "Specialist",
                "mobile": unique_mobile(),
                "email": unique_email(),
                "role": role,
                "business_line": line,
                "loan_specialty_id": str(p.id),
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["loan_specialty_id"] == str(p.id)
        created[role] = res.json()
    path = f"/api/v1/admin/users/{created['employee']['auth_user_uuid']}/loan-specialty"
    labels = {str(card.id): card.label, str(insurance.id): insurance.label}
    for value in (str(card.id), None, str(insurance.id)):
        changed = await client.patch(
            path, headers=_headers(token), json={"loan_specialty_id": value}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()[0]["loan_specialty_id"] == value
        assert changed.json()[0].get("loan_specialty_label") == labels.get(value)
    async with sessions.AsyncSessionLocal() as db:
        officer = await db.scalar(
            select(StaffProfile).where(
                StaffProfile.auth_user_uuid == UUID(created["employee"]["auth_user_uuid"])
            )
        )
        audits = list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.STAFF_SPECIALTY_UPDATED,
                    AuditLog.entity_uuid == officer.id,
                )
            )
        )
        assert len(audits) == 3
    sub, *_ = await _sub_admin(client)
    denied = await client.patch(path, headers=_headers(sub), json={"loan_specialty_id": None})
    assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["real_estate_officer", "inactive", "sub_admin_target"])
async def test_specialty_update_rejections(client: AsyncClient, invalid: str) -> None:
    from app.models.profile import StaffRole
    from app.tests.test_employee_auto_assignment import _seed_staff

    token, *_ = await _primary_admin(client)
    p = await product(active=invalid != "inactive", category="insurance")
    if invalid == "sub_admin_target":
        _, user_id, *_ = await _sub_admin(client)
    else:
        line = "real_estate" if invalid == "real_estate_officer" else "loans"
        user_id = (await _seed_staff(StaffRole.EMPLOYEE, line)).auth_user_uuid
    res = await client.patch(
        f"/api/v1/admin/users/{user_id}/loan-specialty",
        headers=_headers(token),
        json={"loan_specialty_id": str(p.id)},
    )
    assert res.status_code == (404 if invalid == "sub_admin_target" else 422), res.text


@pytest.mark.asyncio
async def test_database_rules_for_officer_specialties() -> None:
    from app.models.profile import StaffRole
    from app.tests.test_employee_auto_assignment import _seed_staff

    estate = await _seed_staff(StaffRole.EMPLOYEE, "real_estate")
    officer = await _seed_staff(StaffRole.EMPLOYEE, "loans")
    inactive, insurance = await product(active=False), await product(category="insurance")
    for profile, value in ((estate, insurance.id), (officer, inactive.id)):
        async with sessions.AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(
                    update(StaffProfile)
                    .where(StaffProfile.id == profile.id)
                    .values(loan_specialty_id=value)
                )
            await db.rollback()
    await specialize(officer, insurance.id)  # an active insurance product on a Loans Officer
    async with sessions.AsyncSessionLocal() as db:
        assert (await db.get(StaffProfile, officer.id)).loan_specialty_id == insurance.id


@pytest.mark.asyncio
async def test_product_with_leads_or_specialists_cannot_be_deleted(client: AsyncClient) -> None:
    token, *_ = await _primary_admin(client)
    with_lead, with_specialist = await product(), await product()
    await assign(product_id=with_lead.id)
    await specialize(await _seed_telecaller(), with_specialist.id)
    for p in (with_lead, with_specialist):
        res = await client.delete(f"/api/v1/admin/loan-types/{p.id}", headers=_headers(token))
        assert res.status_code == 409, res.text
