from datetime import date, datetime, time, timedelta
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import delete, update

import app.db.session as db_session
from app.models.attendance import AttendanceDay, AttendancePolicy, AttendanceRequest
from app.models.profile import StaffProfile, StaffRole
from app.services import attendance as clock
from app.services import attendance_certificates, media_processing, storage
from app.tests.contest_support import (
    admin_token,
    headers,
    seed_staff,
    seed_team,
    sub_admin_token,
    token_for,
)
from app.tests.test_attendance_session_clock import SESSION_POLICY

BASE = "/api/v1/attendance"


@pytest.mark.asyncio
async def test_monthly_accrual_and_certificate_access(client, monkeypatch):
    now = datetime(2033, 1, 1, 10, tzinfo=clock.IST)
    monkeypatch.setattr(clock, "utc_now", lambda: now)
    objects = {}
    monkeypatch.setattr(
        storage, "put_object_bytes", lambda key, payload, _: objects.update({key: payload})
    )
    monkeypatch.setattr(
        storage, "head_object", lambda key: len(objects[key]) if key in objects else None
    )
    monkeypatch.setattr(storage, "read_object_bytes", lambda key, **_: objects.get(key))
    monkeypatch.setattr(storage, "delete_object", lambda key: objects.pop(key, None))
    primary_user, primary_staff = await seed_staff(StaffRole.ADMIN)
    primary = headers(
        token_for(primary_user, "admin", platform_scope="true", staff_profile=primary_staff)
    )
    checker, _ = await admin_token()
    manager, _, manager_profile = await sub_admin_token()
    user, profile = await seed_staff(StaffRole.EMPLOYEE, business_line="loans", created_at=now)
    other_user, other_profile = await seed_staff(StaffRole.EMPLOYEE, business_line="loans")
    owner = headers(token_for(user, "employee", business_line="loans", staff_profile=profile))
    other = headers(
        token_for(other_user, "employee", business_line="loans", staff_profile=other_profile)
    )
    policy = {
        **SESSION_POLICY,
        "leave_quotas": {"sick": 0, "annual": 24},
        "monthly_leave_rules": {
            "sick": {
                "accrual_units": 8,
                "carry_units": 2,
                "sandwich": True,
                "certificate_after_days": 2,
            }
        },
        "certificate_retention_days": 2,
    }
    assert (
        await client.put(f"{BASE}/policy", headers=headers(checker), json=policy)
    ).status_code == 403
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == primary_staff.id)
            .values(is_primary_admin=True)
        )
        await db.commit()
    version = None
    try:
        configured = await client.put(f"{BASE}/policy", headers=primary, json=policy)
        assert configured.status_code == 200, configured.text
        assert configured.json()["can_configure_leave_rules"]
        scheduled = configured.json()["scheduled"]
        version = scheduled["version"]
        first = date.fromisoformat(scheduled["effective_from"])
        sunday = first + timedelta(days=7 + (6 - first.weekday()) % 7)
        friday = sunday - timedelta(days=2)
        now = datetime.combine(friday, time(10), clock.IST)
        submission = await client.post(
            f"{BASE}/leave",
            headers=owner,
            json={
                "start_day": str(sunday - clock.DAY),
                "end_day": str(sunday + clock.DAY),
                "leave_type": "sick",
                "half_day": False,
                "reason": "Medical leave",
            },
        )
        assert submission.status_code == 201, submission.text
        entry = submission.json()
        assert entry["certificate_required"]
        endpoint = f"{BASE}/requests/{entry['id']}"
        decision = {"status": "approved", "note": "Leave reviewed", "expected_decisions": 0}
        recommended = await client.post(
            f"{endpoint}/decision", headers=primary, json={**decision, "stage": "recommendation"}
        )
        assert recommended.status_code == 200, recommended.text
        decision["expected_decisions"] = 1
        missing = await client.post(f"{endpoint}/decision", headers=headers(checker), json=decision)
        assert missing.status_code == 409, missing.text
        files = {
            "file": ("private-test.pdf", b"%PDF-1.7\nSynthetic copy\n%%EOF", "application/pdf")
        }
        assert (
            await client.post(f"{endpoint}/certificate", headers=other, files=files)
        ).status_code == 404
        with monkeypatch.context() as scan:

            def scanner_unavailable(_):
                raise media_processing.ScannerUnavailable

            scan.setattr(media_processing, "scan_bytes", scanner_unavailable)
            rejected = await client.post(f"{endpoint}/certificate", headers=owner, files=files)
            assert rejected.status_code == 503, rejected.text
            assert objects == {}
        attached = await client.post(f"{endpoint}/certificate", headers=owner, files=files)
        assert attached.status_code == 204, attached.text
        for viewer in (owner, headers(checker)):
            result = await client.get(f"{endpoint}/certificate", headers=viewer)
            assert result.status_code == 200, result.text
            assert result.content == files["file"][1]
            assert result.headers["cache-control"] == "private, no-store"
            assert "private-test" not in result.headers["content-disposition"]
        for denied in (headers(manager), other):
            assert (await client.get(f"{endpoint}/certificate", headers=denied)).status_code == 404
        png = BytesIO()
        Image.new("I;16", (4, 4), 1024).save(png, format="PNG")
        replacement = await client.post(
            f"{endpoint}/certificate",
            headers=owner,
            files={"file": ("certificate.png", png.getvalue(), "image/png")},
        )
        assert replacement.status_code == 204, replacement.text
        refreshed = await client.get(f"{endpoint}/certificate", headers=headers(checker))
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.headers["content-type"] == "image/png"
        assert len(objects) == 2
        approved = await client.post(
            f"{endpoint}/decision", headers=headers(checker), json=decision
        )
        assert approved.status_code == 200, approved.text
        assert sorted(approved.json()["approved_units"].values()) == [2, 2]
        await seed_team(manager_profile, "loans", "employee", [profile])
        assert (
            await client.get(f"{endpoint}/certificate", headers=headers(manager))
        ).status_code == 404
        personal = await client.get(f"{BASE}/me", headers=owner)
        assert personal.status_code == 200, personal.text
        sick = next(
            balance for balance in personal.json()["balances"] if balance["leave_type"] == "sick"
        )
        assert (sick["allocated_units"], sick["used_units"]) == (8, 6)

        now = datetime(2033, 3, 1, 10, tzinfo=clock.IST)
        personal = await client.get(f"{BASE}/me", headers=owner)
        sick = next(
            balance for balance in personal.json()["balances"] if balance["leave_type"] == "sick"
        )
        assert (sick["allocated_units"], sick["used_units"]) == (10, 0)
        assert (await client.get(f"{endpoint}/certificate", headers=owner)).status_code == 404
        assert await attendance_certificates.purge_expired() == 2
        assert objects == {}
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                update(StaffProfile)
                .where(StaffProfile.id == primary_staff.id)
                .values(is_primary_admin=False)
            )
            await db.execute(
                delete(AttendanceDay).where(AttendanceDay.staff_profile_id == profile.id)
            )
            await db.execute(
                delete(AttendanceRequest).where(AttendanceRequest.staff_profile_id == profile.id)
            )
            if version is not None:
                await db.execute(
                    delete(AttendancePolicy).where(AttendancePolicy.version == version)
                )
            await db.commit()
