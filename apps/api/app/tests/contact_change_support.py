"""Shared helpers for the CS-025 email and contact-change test modules."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token
from conftest import full_registration


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def user_id(mobile: str) -> str:
    import app.db.session as session_mod

    async with session_mod.AsyncSessionLocal() as db:
        value = await db.scalar(text("SELECT id FROM auth_users WHERE mobile = :m"), {"m": mobile})
        assert value is not None
        return str(value)


async def fetch_one(sql: str, params: dict, *, commit: bool = False) -> dict | None:
    import app.db.session as session_mod

    async with session_mod.AsyncSessionLocal() as db:
        row = (await db.execute(text(sql), params)).mappings().first()
        result = dict(row) if row else None
        if commit:
            await db.commit()
        return result


async def fetch_all(sql: str, params: dict) -> list[dict]:
    import app.db.session as session_mod

    async with session_mod.AsyncSessionLocal() as db:
        return [dict(row) for row in (await db.execute(text(sql), params)).mappings().all()]


async def execute(sql: str, params: dict) -> None:
    import app.db.session as session_mod

    async with session_mod.AsyncSessionLocal() as db:
        await db.execute(text(sql), params)
        await db.commit()


def role_token(uid: str, role: str, *, platform_scope: str = "false", version: int = 1) -> str:
    """A signed session for an account under a role (claims only)."""
    return create_access_token(
        {
            "sub": uid,
            "role": role,
            "business_line": "" if role in ("admin", "sub_admin") else "loans",
            "platform_scope": platform_scope,
            "session_version": version,
        }
    )


async def make_staff(
    client: AsyncClient, role: str, *, scope: str = "line", email: str | None = None
) -> tuple[str, str, str]:
    """A real active staff profile. Returns (token, auth_user_uuid, mobile)."""
    _, mobile = await full_registration(client, email=email)
    uid = await user_id(mobile)
    business_line = None if scope == "platform" else "loans"
    await execute(
        "INSERT INTO staff_profiles "
        "(id, auth_user_uuid, role, scope, business_line, staff_code, status, "
        "created_at, updated_at) VALUES "
        "(:id, :uid, :role, :scope, :line, :code, 'active', now(), now())",
        {
            "id": uuid.uuid4(),
            "uid": uid,
            "role": role,
            "scope": scope,
            "line": business_line,
            "code": f"ST-{uuid.uuid4().hex[:10].upper()}",
        },
    )
    platform_scope = "true" if scope == "platform" else "false"
    return role_token(uid, role, platform_scope=platform_scope), uid, mobile


async def make_admin(client: AsyncClient) -> tuple[str, str, str]:
    return await make_staff(client, "admin", scope="platform")


def _engine():  # noqa: ANN202
    return create_async_engine(
        settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432"),
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )


async def as_api_user(
    sql: str,
    params: dict,
    *,
    auth_user_uuid: str,
    role: str,
    platform_scope: str = "false",
) -> list:
    """Run one statement as api_user under a given RLS context."""
    engine = _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(
                text(
                    "SELECT set_config('app.auth_user_uuid', :uid, true),"
                    "set_config('app.role', :role, true),"
                    "set_config('app.business_line', '', true),"
                    "set_config('app.client_profile_uuid', '', true),"
                    "set_config('app.agent_profile_uuid', '', true),"
                    "set_config('app.staff_profile_uuid', '', true),"
                    "set_config('app.platform_scope', :ps, true)"
                ),
                {"uid": auth_user_uuid, "role": role, "ps": platform_scope},
            )
            return (await conn.execute(text(sql), params)).fetchall()
    finally:
        await engine.dispose()
