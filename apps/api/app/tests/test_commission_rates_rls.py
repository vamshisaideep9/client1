"""CS-028 product_commission_rates RLS, grants and trigger (migration e4a6c8d0f2b3).

Platform Admins read every row; Sub Admins read approved and own workflow
rows; eligible loans/both-line staff and loans Agents read approved only.
Only the maker Sub Admin inserts a
pending proposal and withdraws it (column grant: status, version,
updated_at); nobody deletes; terms never change and statuses only move
forward; a recorded checker never equals the maker, including Admin rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.db.session as db_session
from app.models.commission_rate import ProductCommissionRate
from app.models.loan import LoanType
from app.models.profile import StaffRole
from app.tests.contest_support import as_role, seed_agent, seed_staff, seed_user

pytestmark = pytest.mark.asyncio


async def _product() -> uuid.UUID:
    async with db_session.AsyncSessionLocal() as db:
        product = LoanType(name=f"rls-{uuid.uuid4().hex[:8]}", label="RLS Loan", active=True)
        db.add(product)
        await db.commit()
        return product.id


async def _rate(loan_type_id: uuid.UUID, status: str, maker: uuid.UUID, role: str, **extra):  # noqa: ANN003, ANN202
    reviewed = status in ("approved", "rejected", "superseded")
    checker = extra.pop("checker", None)
    async with db_session.AsyncSessionLocal() as db:
        rate = ProductCommissionRate(
            loan_type_id=loan_type_id,
            kind="percent",
            percent_bps=100,
            status=status,
            created_by_uuid=maker,
            created_by_role=role,
            checker_uuid=checker if reviewed else None,
            reviewed_at=datetime.now(UTC) if reviewed and checker is not None else None,
            review_note="No" if status == "rejected" else None,
            **extra,
        )
        db.add(rate)
        await db.commit()
        return rate.id


async def _seeded() -> dict:
    product = await _product()
    admin = await seed_user("Platform", "Admin")
    maker_user, maker = await seed_staff(StaffRole.SUB_ADMIN)
    return {
        "product": product,
        "admin": admin,
        "maker_user": maker_user,
        "maker": maker,
        "approved": await _rate(product, "approved", admin.id, "admin"),
        "pending": await _rate(product, "pending_approval", maker_user.id, "sub_admin"),
        "rejected": await _rate(product, "rejected", maker_user.id, "sub_admin", checker=admin.id),
        "withdrawn": await _rate(product, "withdrawn", maker_user.id, "sub_admin"),
    }


async def _visible(product: uuid.UUID, **context) -> set[uuid.UUID]:
    rows = await as_role(
        "SELECT id FROM product_commission_rates WHERE loan_type_id = :p",
        params={"p": product},
        **context,
    )
    return {row[0] for row in rows}


async def test_who_reads_which_rows(client) -> None:
    s = await _seeded()
    every = {s["approved"], s["pending"], s["rejected"], s["withdrawn"]}

    assert (
        await _visible(s["product"], user_uuid=s["admin"].id, role="admin", platform_scope="true")
        == every
    )

    assert (
        await _visible(
            s["product"],
            user_uuid=s["maker_user"].id,
            role="sub_admin",
            staff_profile_uuid=s["maker"].id,
        )
        == every
    )
    assert (
        await _visible(s["product"], user_uuid=s["admin"].id, role="admin", platform_scope="line")
        == set()
    )
    sub_user, sub = await seed_staff(StaffRole.SUB_ADMIN)
    assert await _visible(
        s["product"], user_uuid=sub_user.id, role="sub_admin", staff_profile_uuid=sub.id
    ) == {s["approved"]}

    loans_user, loans_agent = await seed_agent("loans")
    assert await _visible(
        s["product"],
        user_uuid=loans_user.id,
        role="agent",
        business_line="loans",
        agent_profile_uuid=loans_agent.id,
    ) == {s["approved"]}
    re_user, re_agent = await seed_agent("real_estate")
    assert (
        await _visible(
            s["product"],
            user_uuid=re_user.id,
            role="agent",
            business_line="real_estate",
            agent_profile_uuid=re_agent.id,
        )
        == set()
    )
    # An "agent" context without an Agent profile reads nothing either.
    assert (
        await _visible(s["product"], user_uuid=loans_user.id, role="agent", business_line="loans")
        == set()
    )

    for role in ("telecaller", "employee"):
        for line in ("loans", "both", "real_estate"):
            staff_user, staff = await seed_staff(StaffRole(role), business_line=line)
            assert await _visible(
                s["product"],
                user_uuid=staff_user.id,
                role=role,
                business_line=line,
                staff_profile_uuid=staff.id,
            ) == ({s["approved"]} if line in ("loans", "both") else set())
        assert (
            await _visible(
                s["product"],
                user_uuid=staff_user.id,
                role=role,
                business_line="loans",
            )
            == set()
        )
    client_user = await seed_user("Some", "Client")
    assert (
        await _visible(s["product"], user_uuid=client_user.id, role="client", business_line="loans")
        == set()
    )
    assert await _visible(s["product"], user_uuid="", role="") == set()


_INSERT = (
    "INSERT INTO product_commission_rates (id, loan_type_id, kind, percent_bps, status, "
    "created_by_uuid, created_by_role, checker_uuid, reviewed_at, version, created_at, "
    "updated_at) VALUES (gen_random_uuid(), :product, 'percent', 100, :status, :maker, "
    ":role, :checker, :reviewed, 1, now(), now()) RETURNING id"
)


async def test_only_the_maker_sub_admin_inserts_a_pending_proposal(client) -> None:
    product = await _product()
    maker_user, maker = await seed_staff(StaffRole.SUB_ADMIN)
    admin = await seed_user("Platform", "Admin")
    context = {"user_uuid": maker_user.id, "role": "sub_admin", "staff_profile_uuid": maker.id}
    base = {
        "product": product,
        "status": "pending_approval",
        "maker": maker_user.id,
        "role": "sub_admin",
        "checker": None,
        "reviewed": None,
    }

    for forged in (
        {"status": "approved", "checker": admin.id, "reviewed": datetime.now(UTC)},
        {"maker": (await seed_user("Other", "Person")).id},
        {"role": "admin"},
    ):
        with pytest.raises(DBAPIError):
            await as_role(_INSERT, params={**base, **forged}, **context)

    agent_user, agent = await seed_agent("loans")
    denied_contexts = [
        ({"user_uuid": admin.id, "role": "admin", "platform_scope": "true"}, admin.id),
        (
            {
                "user_uuid": agent_user.id,
                "role": "agent",
                "business_line": "loans",
                "agent_profile_uuid": agent.id,
            },
            agent_user.id,
        ),
    ]
    for role in (StaffRole.TELECALLER, StaffRole.EMPLOYEE):
        staff_user, staff = await seed_staff(role, business_line="loans")
        denied_contexts.append(
            (
                {
                    "user_uuid": staff_user.id,
                    "role": role.value,
                    "business_line": "loans",
                    "staff_profile_uuid": staff.id,
                },
                staff_user.id,
            )
        )
    for other_context, maker_id in denied_contexts:
        with pytest.raises(DBAPIError):
            await as_role(
                _INSERT,
                params={
                    **base,
                    "maker": maker_id,
                    "role": "admin",
                    "status": "approved",
                    "checker": None,
                    "reviewed": None,
                },
                **other_context,
            )

    rows = await as_role(_INSERT, params=base, **context)
    assert len(rows) == 1


async def test_maker_may_only_withdraw_their_own_pending_row(client) -> None:
    s = await _seeded()
    context = {
        "user_uuid": s["maker_user"].id,
        "role": "sub_admin",
        "staff_profile_uuid": s["maker"].id,
    }
    # Approving their own proposal through RLS is refused.
    with pytest.raises(DBAPIError):
        await as_role(
            "UPDATE product_commission_rates SET status = 'approved' WHERE id = :id",
            params={"id": s["pending"]},
            **context,
        )
    # Changing the terms is outside the column grant.
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_role(
            "UPDATE product_commission_rates SET percent_bps = 9000 WHERE id = :id",
            params={"id": s["pending"]},
            **context,
        )
    # Another Sub Admin and a platform Admin update nothing through RLS.
    other_user, other = await seed_staff(StaffRole.SUB_ADMIN)
    for other_context in (
        {"user_uuid": other_user.id, "role": "sub_admin", "staff_profile_uuid": other.id},
        {"user_uuid": s["admin"].id, "role": "admin", "platform_scope": "true"},
    ):
        rows = await as_role(
            "UPDATE product_commission_rates SET status = 'withdrawn' WHERE id = :id RETURNING id",
            params={"id": s["pending"]},
            **other_context,
        )
        assert rows == []
    # Nobody deletes.
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_role(
            "DELETE FROM product_commission_rates WHERE id = :id",
            params={"id": s["withdrawn"]},
            user_uuid=s["admin"].id,
            role="admin",
            platform_scope="true",
        )
    rows = await as_role(
        "UPDATE product_commission_rates SET status = 'withdrawn', version = version + 1 "
        "WHERE id = :id RETURNING id",
        params={"id": s["pending"]},
        **context,
    )
    assert [row[0] for row in rows] == [s["pending"]]


async def test_constraints_and_trigger_hold_on_the_bypass_session(client) -> None:
    s = await _seeded()

    async def _refused(sql: str, **params: object) -> None:
        async with db_session.AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql), params)
            await db.rollback()

    # A Sub Admin's proposal is never checked by its maker.
    await _refused(
        "UPDATE product_commission_rates SET status = 'approved', checker_uuid = "
        "created_by_uuid, reviewed_at = now() WHERE id = :id",
        id=s["pending"],
    )
    # The bypass connection cannot fabricate an Admin self-checker either.
    await _refused(
        "UPDATE product_commission_rates SET checker_uuid = created_by_uuid, "
        "reviewed_at = now() WHERE id = :id",
        id=s["approved"],
    )
    # A Sub Admin's reviewed row cannot use the standalone Admin exception.
    await _refused(
        "UPDATE product_commission_rates SET status = 'approved' WHERE id = :id",
        id=s["pending"],
    )
    # Terms never change; final statuses stay final.
    await _refused(
        "UPDATE product_commission_rates SET percent_bps = 50 WHERE id = :id", id=s["approved"]
    )
    await _refused(
        "UPDATE product_commission_rates SET status = 'approved' WHERE id = :id", id=s["rejected"]
    )
    await _refused(
        "UPDATE product_commission_rates SET status = 'pending_approval', checker_uuid = NULL, "
        "reviewed_at = NULL WHERE id = :id",
        id=s["approved"],
    )
    # One approved and one pending row per product.
    with pytest.raises(DBAPIError):
        await _rate(s["product"], "approved", s["admin"].id, "admin")
    with pytest.raises(DBAPIError):
        await _rate(s["product"], "pending_approval", s["maker_user"].id, "sub_admin")
    # Amount shape: percent XOR fixed.
    with pytest.raises(DBAPIError):
        await _rate(s["product"], "withdrawn", s["maker_user"].id, "sub_admin", amount_paise=10)
