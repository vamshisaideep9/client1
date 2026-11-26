"""Client feedback round 3, slice 4: attendance filters, leave badges and
yearly holidays.

- ``/attendance/roster`` and ``/attendance/export`` filter by department
  (dual-line members match either), product specialty, role, Sub Admin group
  and approved leave type in the range; members carry department, product
  and Sub Admin groups. A reviewer still sees only members they reach.
- Approved leave of any type gets a badge (CL and SL unchanged).
- ``/attendance/holidays?year=`` returns a whole year; ``repeat_yearly``
  starts a yearly series from today or later; "stop repeating" ends it today
  so earlier occurrences and closed months never change; 29 February only
  repeats in leap years; future occurrences with attendance conflict.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import delete, select

import app.db.session as db_session
from app.models.attendance import (
    AttendanceDay,
    AttendancePolicy,
    AttendanceRecurringHoliday,
    AttendanceRequest,
)
from app.models.audit_log import AuditAction, AuditLog
from app.models.loan import LoanType
from app.models.profile import StaffProfile, StaffRole, SubAdminAccessProfile
from app.services import attendance
from app.services.attendance_views import leave_badge
from app.tests.contest_support import admin_token, headers, seed_staff, sub_admin_token, token_for
from app.tests.test_attendance_session_clock import SESSION_POLICY

BASE = "/api/v1/attendance"


@pytest.mark.parametrize(
    ("leave_type", "code", "label"),
    [
        ("casual", "CL", "Casual leave"),
        ("sick_leave", "SL", "Sick leave"),
        ("earned", "EL", "Earned leave"),
        ("maternity_leave", "ML", "Maternity leave"),
        ("work_from_home", "WFH", "Work from home"),
        ("loss_of_pay", "LOP", "Loss of pay"),
    ],
)
def test_every_leave_type_gets_a_short_badge(leave_type: str, code: str, label: str) -> None:
    badge = leave_badge(leave_type)
    assert (badge.code, badge.label) == (code, label)
    assert len(badge.code) <= 3


async def _member(client, token: str, start: date, end: date, staff_id, **filters) -> list[dict]:
    params = {"start": str(start), "end": str(end), "staff_id": str(staff_id), **filters}
    response = await client.get(f"{BASE}/roster", headers=headers(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()["members"]


@pytest.mark.asyncio
async def test_roster_filters_and_member_details(client) -> None:
    admin, _ = await admin_token()
    outsider, _, _ = await sub_admin_token()
    start = date(2033, 3, 1)
    end = date(2033, 3, 31)
    async with db_session.AsyncSessionLocal() as db:
        product = LoanType(name=f"att-{uuid.uuid4().hex[:8]}", label="Attendance Loan")
        db.add(product)
        await db.commit()
    telecaller_user, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    _, officer = await seed_staff(StaffRole.EMPLOYEE, business_line="real_estate")
    _, dual = await seed_staff(StaffRole.EMPLOYEE, business_line="both")
    _, _, manager = await sub_admin_token()
    async with db_session.AsyncSessionLocal() as db:
        profile = await db.get(StaffProfile, telecaller.id)
        profile.loan_specialty_id = product.id
        db.add(
            SubAdminAccessProfile(
                staff_profile_uuid=manager.id,
                status="active",
                version=1,
                grants=[
                    {
                        "assignment": "relationship_manager",
                        "business_line": "loans",
                        "actions": ["view"],
                        "agent_profile_ids": [],
                    }
                ],
            )
        )
        leave = AttendanceRequest(
            staff_profile_id=telecaller.id,
            requester_id=telecaller_user.id,
            kind="leave",
            status="approved",
            start_day=date(2033, 3, 10),
            end_day=date(2033, 3, 11),
            reason="Family function",
            leave_type="earned",
            created_at=datetime(2033, 3, 1, tzinfo=attendance.IST),
        )
        db.add(leave)
        await db.commit()
    try:
        (row,) = await _member(client, admin, start, end, telecaller.id)
        assert row["department"] == "loans"
        assert row["product_id"] == str(product.id)
        assert row["sub_admin_groups"] == []

        assert await _member(client, admin, start, end, telecaller.id, department="loans")
        assert not await _member(client, admin, start, end, telecaller.id, department="real_estate")
        assert await _member(client, admin, start, end, officer.id, department="real_estate")
        # A dual-line member matches either department.
        for line in ("loans", "real_estate"):
            assert await _member(client, admin, start, end, dual.id, department=line)

        assert await _member(client, admin, start, end, telecaller.id, product_id=str(product.id))
        assert not await _member(client, admin, start, end, officer.id, product_id=str(product.id))

        assert await _member(client, admin, start, end, telecaller.id, role="telecaller")
        assert not await _member(client, admin, start, end, telecaller.id, role="employee")

        (rm,) = await _member(
            client, admin, start, end, manager.id, sub_admin_group="relationship_manager"
        )
        assert rm["sub_admin_groups"] == ["relationship_manager"]
        assert not await _member(
            client, admin, start, end, manager.id, sub_admin_group="team_manager"
        )
        assert not await _member(
            client, admin, start, end, telecaller.id, sub_admin_group="relationship_manager"
        )

        assert await _member(client, admin, start, end, telecaller.id, leave_type="earned")
        assert not await _member(client, admin, start, end, telecaller.id, leave_type="sick")
        april = (date(2033, 4, 1), date(2033, 4, 30))
        assert not await _member(client, admin, *april, telecaller.id, leave_type="earned")
        invalid = await client.get(
            f"{BASE}/roster",
            headers=headers(admin),
            params={"start": str(start), "end": str(end), "leave_type": "Earned Leave!"},
        )
        assert invalid.status_code == 422

        # Filters never widen a reviewer's reach.
        assert not await _member(client, outsider, start, end, telecaller.id, department="loans")

        export = await client.get(
            f"{BASE}/export",
            headers=headers(admin),
            params={"start": str(start), "end": str(end), "role": "telecaller"},
        )
        # Without an active policy the export refuses, as before.
        assert export.status_code in (200, 409), export.text
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(delete(AttendanceRequest).where(AttendanceRequest.id == leave.id))
            await db.execute(
                delete(SubAdminAccessProfile).where(
                    SubAdminAccessProfile.staff_profile_uuid == manager.id
                )
            )
            profile = await db.get(StaffProfile, telecaller.id)
            profile.loan_specialty_id = None
            await db.commit()


@pytest.mark.asyncio
async def test_yearly_holidays(client, monkeypatch) -> None:
    now = datetime(2034, 2, 1, 9, tzinfo=attendance.IST)
    monkeypatch.setattr(attendance, "utc_now", lambda: now)
    admin, admin_user = await admin_token()
    staff_user, staff = await seed_staff(StaffRole.EMPLOYEE, business_line="loans", created_at=now)
    config = await client.put(f"{BASE}/policy", headers=headers(admin), json=SESSION_POLICY)
    assert config.status_code == 200, config.text
    scheduled = config.json()["scheduled"]
    first = date.fromisoformat(scheduled["effective_from"])
    now = datetime.combine(first, time(9, 40), attendance.IST)
    founders = first + timedelta(days=5)
    leap = date(2036, 2, 29)
    try:
        # Only today or later; never a past work date.
        past = await client.put(
            f"{BASE}/holidays/{first - timedelta(days=1)}",
            headers=headers(admin),
            json={"name": "Too late", "repeat_yearly": True},
        )
        assert past.status_code == 422, past.text
        created = await client.put(
            f"{BASE}/holidays/{founders}",
            headers=headers(admin),
            json={"name": "Founders day", "repeat_yearly": True},
        )
        assert created.status_code == 204, created.text
        # One open series per date and line.
        again = await client.put(
            f"{BASE}/holidays/{founders.replace(year=founders.year + 2)}",
            headers=headers(admin),
            json={"name": "Founders day", "repeat_yearly": True},
        )
        assert again.status_code == 409, again.text

        def _year(year: int):
            return client.get(f"{BASE}/holidays", headers=headers(admin), params={"year": year})

        for year in (founders.year, founders.year + 1, founders.year + 5):
            response = await _year(year)
            assert response.status_code == 200, response.text
            (occurrence,) = [h for h in response.json() if h["name"] == "Founders day"]
            assert occurrence["day"] == str(founders.replace(year=year))
            assert occurrence["repeats_yearly"] is True
            assert occurrence["business_line"] is None
            recurring_id = occurrence["recurring_id"]
        both = await client.get(
            f"{BASE}/holidays",
            headers=headers(admin),
            params={"year": founders.year, "start": str(first)},
        )
        assert both.status_code == 422
        too_long = await client.get(
            f"{BASE}/holidays",
            headers=headers(admin),
            params={"start": str(first), "end": str(first + timedelta(days=60))},
        )
        assert too_long.status_code == 422

        # Attendance calculations treat every occurrence as a holiday.
        async with db_session.AsyncSessionLocal() as db:
            policy = await db.get(AttendancePolicy, scheduled["version"])
            next_year = founders.replace(year=founders.year + 1)
            assert await attendance.day_without_clock(db, next_year, policy, "loans") == "holiday"
            assert await attendance.day_without_clock(db, next_year, policy, None) == "holiday"
            other_day = next_year + timedelta(days=1)
            assert await attendance.day_without_clock(db, other_day, policy, "loans") != "holiday"

        # Staff calendars include the occurrence.
        staff_headers = headers(
            token_for(staff_user, "employee", business_line="loans", staff_profile=staff)
        )
        me = await client.get(
            f"{BASE}/me",
            headers=staff_headers,
            params={"year": founders.year, "month": founders.month},
        )
        assert me.status_code == 200, me.text
        assert any(h["day"] == str(founders) for h in me.json()["holidays"])

        # 29 February repeats only in leap years.
        leap_created = await client.put(
            f"{BASE}/holidays/{leap}",
            headers=headers(admin),
            params={"business_line": "loans"},
            json={"name": "Leap day", "repeat_yearly": True},
        )
        assert leap_created.status_code == 204, leap_created.text
        for year, expected in ((2036, True), (2037, False), (2040, True)):
            response = await _year(year)
            names = {h["name"] for h in response.json()}
            loans = await client.get(
                f"{BASE}/holidays",
                headers=headers(admin),
                params={"year": year, "business_line": "loans"},
            )
            line_names = {h["name"] for h in loans.json()}
            assert "Leap day" not in names
            assert ("Leap day" in line_names) is expected

        # A future occurrence that already has attendance conflicts.
        async with db_session.AsyncSessionLocal() as db:
            busy = first + timedelta(days=9)
            db.add(
                AttendanceDay(
                    staff_profile_id=staff.id,
                    day=busy.replace(year=busy.year + 1),
                    policy_version=scheduled["version"],
                    status="present",
                    source="clock",
                    business_line="loans",
                )
            )
            await db.commit()
        conflict = await client.put(
            f"{BASE}/holidays/{busy}",
            headers=headers(admin),
            params={"business_line": "loans"},
            json={"name": "Busy day", "repeat_yearly": True},
        )
        assert conflict.status_code == 409, conflict.text

        # Stopping a series that started keeps earlier occurrences.
        now = datetime.combine(
            founders.replace(year=founders.year + 1) + timedelta(days=3), time(10), attendance.IST
        )
        stopped = await client.delete(
            f"{BASE}/holidays/recurring/{recurring_id}", headers=headers(admin)
        )
        assert stopped.status_code == 204, stopped.text
        for year, expected in (
            (founders.year, True),
            (founders.year + 1, True),
            (founders.year + 2, False),
        ):
            response = await _year(year)
            assert any(h["name"] == "Founders day" for h in response.json()) is expected
        again = await client.delete(
            f"{BASE}/holidays/recurring/{recurring_id}", headers=headers(admin)
        )
        assert again.status_code == 409
        missing = await client.delete(
            f"{BASE}/holidays/recurring/{uuid.uuid4()}", headers=headers(admin)
        )
        assert missing.status_code == 404

        # Only a platform Admin manages the calendar.
        refused = await client.put(
            f"{BASE}/holidays/{founders.replace(year=founders.year + 3)}",
            headers=staff_headers,
            json={"name": "Staff holiday", "repeat_yearly": True},
        )
        assert refused.status_code == 403

        async with db_session.AsyncSessionLocal() as db:
            operations = (
                await db.scalars(
                    select(AuditLog.detail["operation"].astext).where(
                        AuditLog.action == AuditAction.ATTENDANCE_UPDATED,
                        AuditLog.actor_uuid == admin_user.id,
                    )
                )
            ).all()
        assert "start_yearly_holiday" in operations
        assert "stop_yearly_holiday" in operations
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                delete(AttendanceRecurringHoliday).where(
                    AttendanceRecurringHoliday.created_by == admin_user.id
                )
            )
            await db.execute(
                delete(AttendanceDay).where(AttendanceDay.policy_version == scheduled["version"])
            )
            await db.execute(
                delete(AttendancePolicy).where(AttendancePolicy.version == scheduled["version"])
            )
            await db.commit()
