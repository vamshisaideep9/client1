"""Attendance assignments enforce employment, calendar and live reviewer scope."""

from datetime import date, datetime, time

import pytest
from sqlalchemy import delete

import app.db.session as db_session
from app.models.attendance import AttendanceDay, AttendanceLineHoliday, AttendancePolicy
from app.models.profile import StaffRole
from app.services import attendance
from app.tests.contest_support import admin_token, headers, seed_staff, sub_admin_token, token_for
from app.tests.test_attendance_session_clock import SESSION_POLICY

BASE = "/api/v1/attendance"


@pytest.mark.asyncio
async def test_employment_calendar_and_direct_review(client, monkeypatch):
    now = datetime(2032, 1, 1, 9, tzinfo=attendance.IST)
    monkeypatch.setattr(attendance, "utc_now", lambda: now)
    admin, _ = await admin_token()
    manager, _, manager_profile = await sub_admin_token()
    other, _, _ = await sub_admin_token()
    user, profile = await seed_staff(StaffRole.EMPLOYEE, business_line="both", created_at=now)
    staff = headers(token_for(user, "employee", business_line="both", staff_profile=profile))
    config = await client.put(f"{BASE}/policy", headers=headers(admin), json=SESSION_POLICY)
    assert config.status_code == 200, config.text
    scheduled = config.json()["scheduled"]
    first = date.fromisoformat(scheduled["effective_from"])
    holiday = first + attendance.DAY
    endpoint = f"{BASE}/employment/{profile.id}"
    body = {
        "start_day": str(holiday),
        "end_day": str(holiday + attendance.DAY),
        "business_line": "real_estate",
        "reviewer_id": str(manager_profile.id),
        "expected_version": 0,
    }
    try:
        assert (await client.put(endpoint, headers=headers(manager), json=body)).status_code == 403
        saved = await client.put(endpoint, headers=headers(admin), json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 1
        assert (await client.put(endpoint, headers=headers(admin), json=body)).status_code == 409
        assert (await client.get(endpoint, headers=headers(manager))).status_code == 403

        now = datetime.combine(first, time(9, 40), attendance.IST)
        calendar = await client.put(
            f"{BASE}/holidays/{holiday}",
            params={"business_line": "real_estate"},
            headers=headers(admin),
            json={"name": "Real estate holiday"},
        )
        assert calendar.status_code == 204, calendar.text
        assert (await client.post(f"{BASE}/check-in", headers=staff)).status_code == 422

        loans_user, loans_id = await seed_staff(StaffRole.EMPLOYEE, created_at=now)
        loans = headers(
            token_for(loans_user, "employee", business_line="loans", staff_profile=loans_id)
        )
        now = datetime.combine(holiday, time(9, 40), attendance.IST)
        punch = await client.post(f"{BASE}/check-in", headers={**staff, "X-Business-Line": "loans"})
        assert punch.status_code == 200, punch.text
        assert punch.json()["calendar_status"] == "holiday"
        other_punch = await client.post(f"{BASE}/check-in", headers=loans)
        assert other_punch.status_code == 200, other_punch.text
        assert other_punch.json()["calendar_status"] == "absent"
        assert not (await client.get(f"{BASE}/me", headers=loans)).json()["holidays"]
        assert (await client.get(f"{BASE}/me", headers=staff)).json()["holidays"] == [
            {"day": str(holiday), "name": "Real estate holiday"}
        ]

        roster = {"start": str(holiday), "end": str(holiday), "staff_id": str(profile.id)}
        reached = await client.get(f"{BASE}/roster", headers=headers(manager), params=roster)
        assert reached.status_code == 200, reached.text
        assert len(reached.json()["days"]) == 1
        unrelated = await client.get(f"{BASE}/roster", headers=headers(other), params=roster)
        assert unrelated.status_code == 200, unrelated.text
        assert unrelated.json()["members"] == []

        next_day = holiday + attendance.DAY
        request = await client.post(
            f"{BASE}/regularizations",
            headers={**staff, "X-Business-Line": "loans"},
            json={"day": str(next_day), "adjustment_type": "on_duty", "reason": "Office work"},
        )
        assert request.status_code == 201, request.text
        decision = f"{BASE}/requests/{request.json()['id']}/decision"
        review = {
            "status": "approved",
            "note": "Confirmed",
            "stage": "recommendation",
            "expected_decisions": 0,
        }
        assert (await client.post(decision, headers=headers(other), json=review)).status_code == 404
        reviewed = await client.post(decision, headers=headers(manager), json=review)
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "pending"

        removed = await client.put(
            endpoint,
            headers=headers(admin),
            json={
                **body,
                "reviewer_id": None,
                "expected_version": 1,
            },
        )
        assert removed.status_code == 200, removed.text
        revoked = await client.get(f"{BASE}/roster", headers=headers(manager), params=roster)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["members"] == []
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                delete(AttendanceDay).where(AttendanceDay.policy_version == scheduled["version"])
            )
            await db.execute(
                delete(AttendancePolicy).where(AttendancePolicy.version == scheduled["version"])
            )
            await db.execute(
                delete(AttendanceLineHoliday).where(AttendanceLineHoliday.day == holiday)
            )
            await db.commit()
