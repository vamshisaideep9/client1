from datetime import date, datetime, time

import pytest
from sqlalchemy import delete, func, select

import app.db.session as db_session
from app.models.attendance import AttendanceDay, AttendanceMonthRevision, AttendancePolicy
from app.models.profile import StaffProfile, StaffRole
from app.services import attendance as clock
from app.services.attendance_rollover import run_attendance_rollover
from app.tests.contest_support import admin_token, headers, seed_staff, sub_admin_token, token_for
from app.tests.test_attendance_session_clock import SESSION_POLICY

BASE = "/api/v1/attendance"


@pytest.mark.asyncio
async def test_month_close_reopen_and_immutable_export(client, monkeypatch):
    month = date(2001, 1, 1)
    worked_day = date(2001, 1, 4)
    now = datetime(2001, 2, 1, 10, tzinfo=clock.IST)
    monkeypatch.setattr(clock, "utc_now", lambda: now)
    admin, _ = await admin_token()
    other_admin, _ = await admin_token()
    manager, _, _ = await sub_admin_token()
    user, profile = await seed_staff(
        StaffRole.EMPLOYEE,
        business_line="loans",
        created_at=datetime.combine(worked_day, time(8), clock.IST),
    )
    owner = headers(token_for(user, "employee", business_line="loans", staff_profile=profile))
    async with db_session.AsyncSessionLocal() as db:
        version = (await db.scalar(select(func.max(AttendancePolicy.version))) or 0) + 1
        db.add(AttendancePolicy(version=version, effective_from=month, **SESSION_POLICY))
        await db.commit()
    endpoint = f"{BASE}/months/{month}"
    note = {"expected_version": 0, "note": "Checked monthly attendance"}
    try:
        assert (await client.get(endpoint, headers=headers(manager))).status_code == 403
        assert (await client.get(endpoint, headers=owner)).status_code == 403
        waiting = await client.post(f"{endpoint}/close", headers=headers(admin), json=note)
        assert waiting.status_code == 409 and "rollover" in waiting.text
        for _ in range(3):
            await run_attendance_rollover(now)
        correction = {
            "day": str(worked_day),
            "check_in": f"{worked_day}T09:30:00+05:30",
            "check_out": f"{worked_day}T18:30:00+05:30",
            "reason": "Correct punches",
        }
        submitted = await client.post(f"{BASE}/corrections", headers=owner, json=correction)
        assert submitted.status_code == 201, submitted.text
        pending = await client.post(f"{endpoint}/close", headers=headers(admin), json=note)
        assert pending.status_code == 409 and "pending" in pending.text
        assert (
            await client.post(f"{BASE}/requests/{submitted.json()['id']}/cancel", headers=owner)
        ).status_code == 200
        closed = await client.post(f"{endpoint}/close", headers=headers(admin), json=note)
        assert closed.status_code == 200, closed.text
        assert closed.json()["revisions"][0]["version"] == 1
        assert sum(line["worked_minutes"] for line in closed.json()["totals"]) == 0
        locked = await client.post(f"{BASE}/corrections", headers=owner, json=correction)
        assert locked.status_code == 409 and "reopen" in locked.text
        assert (
            await client.post(f"{endpoint}/reopen", headers=headers(admin), json=note)
        ).status_code == 409
        note["expected_version"] = 1
        reopened = await client.post(f"{endpoint}/reopen", headers=headers(admin), json=note)
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["revisions"][0]["reopened_at"]
        corrected = await client.post(f"{BASE}/corrections", headers=owner, json=correction)
        assert corrected.status_code == 201, corrected.text
        review_path = f"{BASE}/requests/{corrected.json()['id']}/decision"
        decision = {"status": "approved", "note": "Reviewed work", "expected_decisions": 0}
        recommendation = await client.post(
            review_path, headers=headers(admin), json={**decision, "stage": "recommendation"}
        )
        assert recommendation.status_code == 200, recommendation.text
        finalized = await client.post(
            review_path, headers=headers(other_admin), json={**decision, "expected_decisions": 1}
        )
        assert finalized.status_code == 200, finalized.text
        reclosed = await client.post(f"{endpoint}/close", headers=headers(admin), json=note)
        assert reclosed.status_code == 200, reclosed.text
        second, first = reclosed.json()["revisions"]
        assert (second["version"], first["version"]) == (2, 1)
        assert sum(line["worked_minutes"] for line in second["totals"]) == 480
        assert first["totals"] == closed.json()["revisions"][0]["totals"]
        old_csv = await client.get(
            f"{endpoint}/export", headers=headers(admin), params={"version": 1}
        )
        assert (
            old_csv.status_code == 200
            and "revision-1.csv" in old_csv.headers["content-disposition"]
        )
        assert "worked_minutes" in old_csv.text and "480" not in old_csv.text
        assert (await client.get(f"{endpoint}/export", headers=headers(manager))).status_code == 403
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                delete(AttendanceMonthRevision).where(AttendanceMonthRevision.month == month)
            )
            await db.execute(delete(AttendanceDay).where(AttendanceDay.policy_version == version))
            await db.execute(delete(AttendancePolicy).where(AttendancePolicy.version == version))
            await db.execute(delete(StaffProfile).where(StaffProfile.id == profile.id))
            await db.commit()
