"""lead_list_signals — confined SECURITY DEFINER read (migration f3a5c7e9b1d2).

The function runs with the owner's rights, so these tests pin its own scope
checks: only the assigned Telecaller or an Employee holding a task on the lead,
only on the request's business line, only four narrow columns, and a
Telecaller's call signals stay limited to calls they logged (matching
lead_activities RLS).

Requires the Docker stack with migrations applied; auto-skips without Redis.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from conftest import unique_mobile


async def _staff(role: str, business_line: str = "loans") -> str:
    import app.db.session as _session_mod
    from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
    from app.models.user import User

    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name=role.title(),
            mobile=unique_mobile(),
            email=f"{role[:2]}_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole(role),
            scope=ProfileScope.LINE,
            business_line=business_line,
            staff_code=f"{role[:2].upper()}-{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return str(profile.id)


async def _seed_world() -> dict[str, str]:
    """Lead L (loans) assigned to telecaller A, referred by client R's code.

    Calls on L: A logged ``connected/hot`` first, B (an earlier assignee)
    logged ``no_answer`` later. Employee E holds a task on L; employee F does
    not. Lead P sits on real_estate, assigned to A.
    """
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity
    from app.models.referral import Referral, ReferralCode
    from app.models.task import Task, TaskStatus, TaskType
    from app.models.user import User

    a = await _staff("telecaller")
    b = await _staff("telecaller")
    e = await _staff("employee")
    f = await _staff("employee")
    # Crockford base32, the referral_codes format check.
    code = "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(8))
    now = datetime.now(UTC)

    async with _session_mod.AsyncSessionLocal() as db:
        referrer = User(
            first_name="Ref",
            last_name="Errer",
            mobile=unique_mobile(),
            email=f"ref_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(referrer)
        await db.flush()
        db.add(ReferralCode(auth_user_uuid=referrer.id, code=code))

        lead = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.ASSIGNED,
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=uuid.UUID(a),
        )
        other_line = Lead(
            mobile=unique_mobile(),
            business_line="real_estate",
            status=LeadStatus.ASSIGNED,
            origin=LeadOrigin.DIRECT,
        )
        db.add_all([lead, other_line])
        await db.flush()
        db.add(Referral(referrer_auth_user_uuid=referrer.id, referred_mobile=lead.mobile))
        db.add_all(
            [
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=uuid.UUID(a),
                    business_line="loans",
                    disposition=CallDisposition.CONNECTED,
                    interest_level=InterestLevel.HOT,
                    notes="private call note",
                    created_at=now - timedelta(hours=2),
                ),
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=uuid.UUID(b),
                    business_line="loans",
                    disposition=CallDisposition.NO_ANSWER,
                    created_at=now - timedelta(hours=1),
                ),
            ]
        )
        db.add(
            Task(
                lead_uuid=lead.id,
                business_line="loans",
                task_type=TaskType.DOCUMENT_COLLECTION,
                status=TaskStatus.ASSIGNED,
                raised_by_staff_profile_uuid=uuid.UUID(a),
                assigned_employee_profile_uuid=uuid.UUID(e),
            )
        )
        await db.commit()
        return {
            "a": a,
            "b": b,
            "e": e,
            "f": f,
            "lead": str(lead.id),
            "other_line": str(other_line.id),
            "code": code,
        }


async def _signals_as(
    lead_ids: list[str], *, role: str, staff: str, business_line: str = "loans"
) -> list[dict]:
    raw_url = settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432")
    engine = create_async_engine(
        raw_url,
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(
                text(
                    "SELECT "
                    "set_config('app.auth_user_uuid', :uuid, true),"
                    "set_config('app.role', :role, true),"
                    "set_config('app.business_line', :line, true),"
                    "set_config('app.client_profile_uuid', '', true),"
                    "set_config('app.agent_profile_uuid', '', true),"
                    "set_config('app.staff_profile_uuid', :staff, true),"
                    "set_config('app.platform_scope', 'false', true)"
                ),
                {"uuid": str(uuid.uuid4()), "role": role, "staff": staff, "line": business_line},
            )
            result = await conn.execute(
                text("SELECT * FROM lead_list_signals(CAST(:ids AS uuid[]))"),
                {"ids": lead_ids},
            )
            keys = list(result.keys())
            return [dict(zip(keys, row, strict=True)) for row in result.fetchall()]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_assigned_telecaller_gets_code_and_only_their_own_latest_call(
    client: AsyncClient,
) -> None:
    world = await _seed_world()

    rows = await _signals_as([world["lead"]], role="telecaller", staff=world["a"])

    assert rows == [
        {
            "lead_uuid": uuid.UUID(world["lead"]),
            "client_referral_code": world["code"],
            # B's later no_answer is not A's call, exactly as lead_activities RLS.
            "last_disposition": "connected",
            "last_interest_level": "hot",
        }
    ]


@pytest.mark.asyncio
async def test_employee_with_a_task_sees_the_leads_latest_call_by_anyone(
    client: AsyncClient,
) -> None:
    world = await _seed_world()

    rows = await _signals_as([world["lead"]], role="employee", staff=world["e"])

    assert [(r["client_referral_code"], r["last_disposition"]) for r in rows] == [
        (world["code"], "no_answer")
    ]
    assert rows[0]["last_interest_level"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "who", "line"),
    [
        ("telecaller", "b", "loans"),  # not the assigned telecaller
        ("employee", "f", "loans"),  # no task on the lead
        ("telecaller", "a", "real_estate"),  # wrong business line for the lead
        ("telecaller", "a", ""),  # no business line set
        ("agent", "a", "loans"),
        ("client", "a", "loans"),
        ("sub_admin", "a", "loans"),
    ],
)
async def test_out_of_scope_callers_get_nothing(
    client: AsyncClient, role: str, who: str, line: str
) -> None:
    world = await _seed_world()

    rows = await _signals_as([world["lead"]], role=role, staff=world[who], business_line=line)

    assert rows == []


@pytest.mark.asyncio
async def test_unassigned_lead_on_another_line_is_never_returned(client: AsyncClient) -> None:
    world = await _seed_world()

    rows = await _signals_as(
        [world["lead"], world["other_line"]], role="telecaller", staff=world["a"]
    )

    assert [str(r["lead_uuid"]) for r in rows] == [world["lead"]]


@pytest.mark.asyncio
async def test_only_four_narrow_columns_are_exposed(client: AsyncClient) -> None:
    world = await _seed_world()

    rows = await _signals_as([world["lead"]], role="telecaller", staff=world["a"])

    assert set(rows[0]) == {
        "lead_uuid",
        "client_referral_code",
        "last_disposition",
        "last_interest_level",
    }
    assert "private call note" not in repr(rows)
