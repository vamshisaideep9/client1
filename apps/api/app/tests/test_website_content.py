from uuid import uuid4

import pytest
from sqlalchemy import delete, update

import app.db.session as db_session
from app.models.profile import StaffProfile, StaffRole
from app.models.website_content import WebsiteDocument, WebsiteEditorGrant, WebsiteRevision
from app.tests.contest_support import headers, seed_staff, token_for


@pytest.mark.asyncio
async def test_delegated_draft_publication_and_restore(client):
    main_user, main_staff = await seed_staff(StaffRole.ADMIN)
    other_user, other_staff = await seed_staff(StaffRole.ADMIN)
    editor_user, editor_staff = await seed_staff(StaffRole.SUB_ADMIN)
    main = headers(token_for(main_user, "admin", platform_scope="true", staff_profile=main_staff))
    other = headers(
        token_for(other_user, "admin", platform_scope="true", staff_profile=other_staff)
    )
    editor = headers(
        token_for(editor_user, "sub_admin", platform_scope="true", staff_profile=editor_staff)
    )
    key = f"article/test-{uuid4().hex}"
    api = "/api/v1/website-content"
    document = f"{api}/documents/{key}"
    publish = f"{api}/publish/{key}"
    public = f"/api/v1/public/website-content/{key}"
    grant = f"{api}/editors/{editor_staff.id}"
    first = {"expected_version": 0, "content": {"title": "First", "body": "Test article."}}
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == main_staff.id)
            .values(is_primary_admin=True)
        )
        await db.commit()
    try:
        assert (await client.get(document, headers=editor)).status_code == 403
        assert (await client.put(grant, headers=other, json={"enabled": True})).status_code == 403
        assert (await client.put(grant, headers=main, json={"enabled": True})).status_code == 204
        assert (await client.get(f"{api}/access", headers=editor)).json() == {
            "can_edit": True,
            "can_publish": False,
        }
        saved = await client.put(document, headers=editor, json=first)
        assert saved.status_code == 200, saved.text
        assert (await client.put(document, headers=editor, json=first)).status_code == 409
        assert (await client.get(public)).status_code == 404
        assert (
            await client.post(publish, headers=editor, json={"expected_version": 1})
        ).status_code == 403
        published = await client.post(publish, headers=main, json={"expected_version": 1})
        assert published.status_code == 200, published.text
        assert (await client.get(public)).json()["content"]["title"] == "First"
        second = await client.put(
            document,
            headers=editor,
            json={
                "expected_version": 2,
                "content": {"title": "Second", "body": "Updated copy."},
            },
        )
        assert second.status_code == 200, second.text
        assert (await client.get(public)).json()["content"]["title"] == "First"
        assert (
            await client.post(publish, headers=main, json={"expected_version": 3})
        ).status_code == 200
        assert (await client.get(public)).json()["content"]["title"] == "Second"
        restored = await client.post(
            publish,
            headers=main,
            json={
                "expected_version": 4,
                "restore_revision": 2,
            },
        )
        assert restored.status_code == 200, restored.text
        assert (await client.get(public)).json()["content"]["title"] == "First"
        assert restored.json()["draft"]["title"] == "Second"
        assert (await client.put(grant, headers=main, json={"enabled": False})).status_code == 204
        assert (await client.get(document, headers=editor)).status_code == 403
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                delete(WebsiteEditorGrant).where(WebsiteEditorGrant.profile_id == editor_staff.id)
            )
            await db.execute(delete(WebsiteRevision).where(WebsiteRevision.key == key))
            await db.execute(delete(WebsiteDocument).where(WebsiteDocument.key == key))
            await db.execute(
                update(StaffProfile)
                .where(StaffProfile.id == main_staff.id)
                .values(is_primary_admin=False)
            )
            await db.commit()
