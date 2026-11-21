"""Attendance checks against Postgres, including cross-team and no-policy gates."""

import asyncio
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select, text

import app.db.session as db_session
from app.models.attendance import AttendancePolicy
from app.models.audit_log import AuditAction, AuditLog
from app.models.profile import StaffRole
from app.models.staff_team import StaffTeam
from app.services import attendance
from app.services.attendance_rollover import run_attendance_rollover
from app.tests.contest_support import (
    admin_token,
    headers,
    seed_staff,
    seed_team,
    sub_admin_token,
    token_for,
)

BASE = "/api/v1/attendance"
POLICY = {
    "shift_start_minute": 22 * 60,
    "shift_minutes": 480,
    "grace_minutes": 10,
    "half_day_minutes": 180,
    "full_day_minutes": 360,
    "weekly_off": [],
    "leave_quotas": {"annual": 3},
}
pytestmark = pytest.mark.asyncio


async def test_attendance_clock_review_roster_and_export(client, monkeypatch):
    admin, admin_user = await admin_token()
    manager, _, manager_profile = await sub_admin_token()
    other_manager, _, _ = await sub_admin_token()
    async with db_session.AsyncSessionLocal() as db:
        latest = await db.scalar(
            select(AttendancePolicy).order_by(AttendancePolicy.version.desc()).limit(1)
        )
    day = attendance.work_date(attendance.utc_now())
    if latest:
        day = max(day, latest.effective_from + attendance.DAY)
    checked_in = datetime.combine(day, time(22, 30), attendance.IST)
    monkeypatch.setattr(attendance, "utc_now", lambda: checked_in)
    user, staff = await seed_staff(
        StaffRole.TELECALLER, first_name="=Synthetic", created_at=checked_in - attendance.DAY
    )
    token = token_for(user, "telecaller", business_line="loans", staff_profile=staff)
    team = await seed_team(manager_profile, "loans", "telecaller", [staff])
    read = await client.get(f"{BASE}/me", headers=headers(token))
    assert read.status_code == 200, read.text
    if latest is None:
        assert read.json()["policy"] is None
        unconfigured = await client.post(f"{BASE}/check-in", headers=headers(token))
        assert unconfigured.status_code == 409
        assert await run_attendance_rollover(checked_in) == 0
    assert (
        await client.put(f"{BASE}/policy", headers=headers(manager), json=POLICY)
    ).status_code == 403
    result = await client.put(f"{BASE}/policy", headers=headers(admin), json=POLICY)
    assert result.status_code == 200, result.text
    if result.json()["scheduled"]:
        day += attendance.DAY
        checked_in += attendance.DAY

    clocks = await asyncio.gather(
        *(client.post(f"{BASE}/check-in", headers=headers(token)) for _ in range(2))
    )
    assert all(result.status_code == 200 for result in clocks), [result.text for result in clocks]
    assert all(
        datetime.fromisoformat(result.json()["original_check_in"]) == checked_in
        for result in clocks
    )
    assert clocks[0].json()["late"]
    checked_out = checked_in + timedelta(hours=7)
    monkeypatch.setattr(attendance, "utc_now", lambda: checked_out)
    await run_attendance_rollover(checked_out)
    for _ in range(2):
        response = await client.post(f"{BASE}/check-out", headers=headers(token))
        assert response.status_code == 200, response.text
        assert response.json()["day"] == str(day)
        assert response.json()["worked_minutes"] == 420

    leave_day = attendance.work_date(checked_out) + timedelta(days=2)
    response = await client.post(
        f"{BASE}/leave",
        headers=headers(token),
        json={
            "start_day": str(leave_day),
            "end_day": str(leave_day),
            "leave_type": "annual",
            "half_day": True,
            "reason": "Appointment",
        },
    )
    assert response.status_code == 201, response.text
    request_id = response.json()["id"]
    command = f"{BASE}/requests/{request_id}/decision"
    body = {"status": "approved", "note": "Schedule confirmed", "expected_decisions": 0}
    assert (
        await client.post(command, headers=headers(other_manager), json=body)
    ).status_code == 404
    assert (await client.post(command, headers=headers(token), json=body)).status_code == 403
    response = await client.post(command, headers=headers(manager), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["approved_units"] == {str(leave_day): 1}
    assert response.json()["decisions"][0]["actor_role"] == "sub_admin"

    params = {"start": str(day), "end": str(leave_day), "team_id": str(team.id)}
    response = await client.get(f"{BASE}/roster", headers=headers(manager), params=params)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert {row["status"] for row in response.json()["days"]} == {"present", "on_leave"}
    other = await client.get(f"{BASE}/roster", headers=headers(other_manager), params=params)
    assert other.json()["members"] == [] and other.json()["days"] == []
    assert (
        await client.get(f"{BASE}/export", headers=headers(manager), params=params)
    ).status_code == 403
    response = await client.get(f"{BASE}/export", headers=headers(admin), params=params)
    assert response.status_code == 200, response.text
    assert "'=Synthetic" in response.text and "mobile" not in response.text

    async with db_session.AsyncSessionLocal() as db:
        exported = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.ATTENDANCE_EXPORTED,
                AuditLog.actor_uuid == admin_user.id,
            )
        )
        assert exported.detail["rows"] == 2
        record = await db.get(StaffTeam, team.id)
        record.archived_at = checked_out
        await db.commit()
    response = await client.get(f"{BASE}/roster", headers=headers(manager), params=params)
    assert response.json()["days"] == []
    response = await client.post(f"{BASE}/requests/{request_id}/cancel", headers=headers(token))
    assert response.status_code == 200
    assert len(response.json()["decisions"]) == 2
    response = await client.get(f"{BASE}/me", headers=headers(token))
    assert response.json()["balances"] == [
        {"leave_type": "annual", "allocated_units": 3, "used_units": 0}
    ]

    corrected = await client.post(
        f"{BASE}/corrections",
        headers=headers(token),
        json={
            "day": str(day),
            "check_in": checked_in.isoformat(),
            "check_out": (checked_out - timedelta(minutes=30)).isoformat(),
            "reason": "Clock correction",
        },
    )
    assert corrected.status_code == 201, corrected.text
    decision_url = f"{BASE}/requests/{corrected.json()['id']}/decision"
    assert (await client.post(decision_url, headers=headers(manager), json=body)).status_code == 404
    response = await client.post(decision_url, headers=headers(admin), json=body)
    assert response.status_code == 200, response.text
    response = await client.get(
        f"{BASE}/me",
        headers=headers(token),
        params={
            "year": day.year,
            "month": day.month,
        },
    )
    personal = next(row for row in response.json()["days"] if row["day"] == str(day))
    assert personal["worked_minutes"] == 390 and personal["source"] == "correction"
    assert datetime.fromisoformat(personal["original_check_out"]) == checked_out
    override = {"status": "rejected", "note": "Original record confirmed", "expected_decisions": 0}
    assert (
        await client.post(decision_url, headers=headers(admin), json=override)
    ).status_code == 409
    response = await client.post(
        decision_url, headers=headers(admin), json={**override, "expected_decisions": 1}
    )
    assert response.status_code == 200, response.text
    assert [item["status"] for item in response.json()["decisions"]] == ["approved", "rejected"]
    response = await client.get(
        f"{BASE}/me",
        headers=headers(token),
        params={
            "year": day.year,
            "month": day.month,
        },
    )
    personal = next(row for row in response.json()["days"] if row["day"] == str(day))
    assert personal["worked_minutes"] == 420 and personal["source"] == "clock"


async def test_runtime_role_has_no_direct_attendance_writes(client):
    async with db_session.AsyncSessionLocal() as db:
        count = await db.scalar(
            text("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name LIKE 'attendance_%'
            AND (
              has_table_privilege('api_user', 'public.' || table_name, 'INSERT')
              OR has_table_privilege('api_user', 'public.' || table_name, 'UPDATE')
              OR has_table_privilege('api_user', 'public.' || table_name, 'DELETE')
            )
        """)
        )
        assert count == 0
