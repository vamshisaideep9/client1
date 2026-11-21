from datetime import date, datetime, time, timedelta

import pytest

from app.models.profile import StaffRole
from app.services import attendance
from app.services.attendance_sessions import IST, late_penalty_units, session_coverage
from app.tests.contest_support import (
    admin_token,
    headers,
    seed_staff,
    seed_team,
    sub_admin_token,
    token_for,
)

BASE = "/api/v1/attendance"
SESSION_POLICY = {
    "shift_start_minute": 570,
    "shift_minutes": 540,
    "grace_minutes": 15,
    "half_day_minutes": 240,
    "full_day_minutes": 480,
    "weekly_off": [6],
    "leave_quotas": {},
    "session_clock": True,
}


@pytest.mark.parametrize(
    ("start", "end", "morning", "afternoon", "late", "early_exit", "minutes"),
    [
        (time(9, 45, 59), time(18, 30), True, True, False, False, 464),
        (time(9, 46), time(18, 30), True, True, True, False, 464),
        (time(11, 30), time(18, 29), True, False, True, True, 359),
        (time(11, 31), time(18, 30), False, True, True, False, 359),
        (time(9, 30), time(23, 59), True, True, False, False, 480),
    ],
)
def test_session_coverage(start, end, morning, afternoon, late, early_exit, minutes):
    day = date(2027, 1, 4)
    result = session_coverage(
        day, datetime.combine(day, start, IST), datetime.combine(day, end, IST)
    )
    assert (result.morning, result.afternoon, result.late, result.early_exit) == (
        morning,
        afternoon,
        late,
        early_exit,
    )
    assert result.minutes_worked == minutes


def test_monthly_late_schedule_uses_quarter_days():
    assert [late_penalty_units(ordinal) for ordinal in range(1, 8)] == [0, 0, 0, 4, 2, 1, 1]


@pytest.mark.asyncio
async def test_session_clock_midnight_preserves_original_punch_and_monthly_lop(client, monkeypatch):
    now = datetime(2027, 1, 1, 9, tzinfo=IST)
    monkeypatch.setattr(attendance, "utc_now", lambda: now)
    admin, _ = await admin_token()
    response = await client.put(f"{BASE}/policy", headers=headers(admin), json=SESSION_POLICY)
    assert response.status_code == 200, response.text
    first = date.fromisoformat(response.json()["scheduled"]["effective_from"])
    assert first == date(2027, 2, 1)
    user, staff = await seed_staff(StaffRole.EMPLOYEE, created_at=now)
    employee = headers(token_for(user, "employee", business_line="loans", staff_profile=staff))

    for offset, expected in enumerate([0, 0, 0, 4, 2, 1]):
        day = first + timedelta(days=offset)
        now = datetime.combine(day, time(9, 46), IST)
        login = await client.post(f"{BASE}/check-in", headers=employee)
        assert login.status_code == 200, login.text
        now = datetime.combine(day + timedelta(days=1), time(0, 5), IST)
        logout = await client.post(f"{BASE}/check-out", headers=employee)
        assert logout.status_code == 200, logout.text
        result = logout.json()
        assert result["day"] == str(day)
        assert result["original_check_out"] is None
        assert datetime.fromisoformat(result["system_check_out"]) == now.replace(minute=0)
        assert result["worked_minutes"] == 464
        assert result["status"] == "present"
        assert result["lop_units"] == expected

    report = await client.get(f"{BASE}/me", params={"month": 2, "year": 2027}, headers=employee)
    assert report.status_code == 200, report.text
    assert sum(row["lop_units"] for row in report.json()["days"]) == 7

    recommend = {"stage": "recommendation", "note": "Verified request", "status": "approved"}
    decide = {"stage": "decision", "note": "Final approval", "status": "approved"}
    checker, _ = await admin_token()

    async def approve(kind: str, day: date, *, end: date) -> None:
        submission = await client.post(
            f"{BASE}/regularizations",
            headers=employee,
            json={"day": str(day), "adjustment_type": kind, "reason": "Verified exception"},
        )
        assert submission.status_code == 201, submission.text
        request = submission.json()
        assert request["end_day"] == str(end)
        endpoint = f"{BASE}/requests/{request['id']}/decision"
        premature = await client.post(
            endpoint, headers=headers(checker), json={**decide, "expected_decisions": 0}
        )
        assert premature.status_code == 409, premature.text
        result = await client.post(
            endpoint, headers=headers(admin), json={**recommend, "expected_decisions": 0}
        )
        assert result.status_code == 200 and result.json()["status"] == "pending", result.text
        self_check = await client.post(
            endpoint, headers=headers(admin), json={**decide, "expected_decisions": 1}
        )
        assert self_check.status_code == 403, self_check.text
        final = await client.post(
            endpoint, headers=headers(checker), json={**decide, "expected_decisions": 1}
        )
        assert final.status_code == 200 and final.json()["status"] == "approved", final.text

    fourth = first + timedelta(days=3)
    await approve("late_waiver", fourth, end=fourth)
    report = await client.get(f"{BASE}/me", params={"month": 2, "year": 2027}, headers=employee)
    assert sum(row["lop_units"] for row in report.json()["days"]) == 6

    sunday = first + timedelta(days=6)
    now = datetime.combine(sunday, time(9, 30), IST)
    assert (await client.post(f"{BASE}/check-in", headers=employee)).status_code == 200
    now = datetime.combine(sunday, time(18, 30), IST)
    assert (await client.post(f"{BASE}/check-out", headers=employee)).status_code == 200
    monday = sunday + timedelta(days=1)
    response = await client.put(
        f"{BASE}/holidays/{monday}", headers=headers(admin), json={"name": "Office holiday"}
    )
    assert response.status_code == 204, response.text
    tuesday = monday + timedelta(days=1)
    await approve("comp_off", sunday, end=tuesday)
    report = await client.get(f"{BASE}/me", params={"month": 2, "year": 2027}, headers=employee)
    dates = {row["day"]: row for row in report.json()["days"]}
    assert dates[str(sunday)]["adjustments"] == ["holiday_work"]
    assert dates[str(tuesday)]["adjustments"] == ["comp_off"]
    assert dates[str(tuesday)]["lop_units"] == 0

    loan_manager, _, loan_profile = await sub_admin_token()
    estate_manager, _, estate_profile = await sub_admin_token()
    dual_user, dual_profile = await seed_staff(
        StaffRole.EMPLOYEE, business_line="both", created_at=now
    )
    loans = await seed_team(loan_profile, "loans", "employee", [dual_profile])
    estate = await seed_team(estate_profile, "real_estate", "employee", [dual_profile])
    dual = headers(
        token_for(dual_user, "employee", business_line="both", staff_profile=dual_profile)
    )
    now = datetime.combine(tuesday, time(9, 30), IST)
    punch = await client.post(f"{BASE}/check-in", headers={**dual, "X-Business-Line": "loans"})
    assert punch.status_code == 200, punch.text
    for team, lead, expected in [(loans, loan_manager, 1), (estate, estate_manager, 0)]:
        roster = await client.get(
            f"{BASE}/roster",
            headers=headers(lead),
            params={"start": str(tuesday), "end": str(tuesday), "team_id": str(team.id)},
        )
        assert roster.status_code == 200, roster.text
        assert len(roster.json()["days"]) == expected
