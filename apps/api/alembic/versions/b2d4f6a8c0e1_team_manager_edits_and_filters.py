"""Sub Admin managers edit their team's open work and filter it (CS-020).

Revision ID: b2d4f6a8c0e1
Revises: e4f6a8c0b2d5

2026-11-15 product decision (CS-020, follow-up to CS-019): a manager may

- set an open team lead's status to working / converted / closed (the same
  choices a Telecaller has; client details stay creator-owned);
- change an open team task's due date, or cancel it (completion stays with the
  Employee, who must record the outcome and evidence);
- add an append-only note to a team lead or task, with an optional follow-up
  date on leads. The assigned Telecaller / Employee reads it on their own page.

Managers still have NO UPDATE or INSERT policy on any operational table. Every
write goes through a confined SECURITY DEFINER function that re-checks, under a
row lock, the caller's live team reach (``team_manager_reaches``), the row's
line, that the work is open and that the requested change is allowed:

- ``team_manager_set_lead_status(lead, status)``
- ``team_manager_update_task(task, due_at, cancel)``
- ``team_manager_add_note(lead, task, body, follow_up_at)`` (author and name
  are taken from the caller's own session, never from arguments)

Filters: ``team_lead_signals(uuid[])`` returns, for leads the calling manager
reaches only, the same identifiers the Telecaller and Employee lists filter on
(client referral code, introducing Agent code, loan statuses, latest call
outcome and interest). It never returns names, mobiles, notes or rewards.
Upstream's ``lead_list_signals`` is left untouched.

Field visibility: a manager may read the Admin's field rules for the member
role of a live team they manage, so manager views apply the same rules the
member's own screens do.

Rollback drops the functions, policies and table. Added ``audit_action`` values
stay, as PostgreSQL cannot drop enum values.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: str | Sequence[str] | None = "e4f6a8c0b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_VALUES = (
    "team_lead_status_updated",
    "team_task_updated",
    "team_note_added",
    "team_task_viewed",
)

_PLATFORM_ADMIN = (
    "(current_setting('app.platform_scope', true) = 'true' "
    "AND current_setting('app.role', true) = 'admin')"
)

_DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp"

_FUNCTIONS = (
    "team_lead_signals(uuid[])",
    "team_manager_add_note(uuid, uuid, text, timestamp with time zone)",
    "team_manager_update_task(uuid, timestamp with time zone, boolean)",
    "team_manager_set_lead_status(uuid, text)",
    "team_manager_reaches_lead(uuid)",
)


def upgrade() -> None:
    for value in _AUDIT_VALUES:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    business_line = postgresql.ENUM(name="business_line_enum", create_type=False)
    op.create_table(
        "team_work_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lead_uuid", sa.UUID(), nullable=True),
        sa.Column("task_uuid", sa.UUID(), nullable=True),
        sa.Column("business_line", business_line, nullable=False),
        sa.Column("author_staff_profile_uuid", sa.UUID(), nullable=True),
        sa.Column("author_auth_user_uuid", sa.UUID(), nullable=True),
        sa.Column("author_name", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(lead_uuid, task_uuid) = 1",
            name=op.f("ck_team_work_notes_one_subject"),
        ),
        sa.CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_team_work_notes_business_line_operational"),
        ),
        sa.CheckConstraint(
            "length(btrim(body)) BETWEEN 1 AND 10000",
            name=op.f("ck_team_work_notes_body_length"),
        ),
        sa.CheckConstraint(
            "follow_up_at IS NULL OR lead_uuid IS NOT NULL",
            name=op.f("ck_team_work_notes_follow_up_on_leads"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_uuid"],
            ["leads.id"],
            name=op.f("fk_team_work_notes_lead_uuid_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_uuid"],
            ["tasks.id"],
            name=op.f("fk_team_work_notes_task_uuid_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_staff_profile_uuid"],
            ["staff_profiles.id"],
            name=op.f("fk_team_work_notes_author_staff_profile_uuid_staff_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["author_auth_user_uuid"],
            ["auth_users.id"],
            name=op.f("fk_team_work_notes_author_auth_user_uuid_auth_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_work_notes")),
    )
    op.create_index(
        op.f("ix_team_work_notes_lead_uuid"), "team_work_notes", ["lead_uuid", "created_at"]
    )
    op.create_index(
        op.f("ix_team_work_notes_task_uuid"), "team_work_notes", ["task_uuid", "created_at"]
    )

    # A lead is reached when its Telecaller, or the Employee holding a task on
    # it, is a member of one of the caller's live teams in the lead's line.
    op.execute(
        f"""
        CREATE FUNCTION team_manager_reaches_lead(target_lead_uuid uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        {_DEFINER}
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM public.leads AS l
                WHERE l.id = target_lead_uuid
                  AND (
                      team_manager_reaches(
                          l.assigned_telecaller_profile_uuid, l.business_line::text
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM public.tasks AS t
                          WHERE t.lead_uuid = l.id
                            AND t.business_line = l.business_line
                            AND team_manager_reaches(
                                t.assigned_employee_profile_uuid, t.business_line::text
                            )
                      )
                  )
            )
        $$
        """
    )

    op.execute("GRANT SELECT ON team_work_notes TO api_user")
    op.execute("ALTER TABLE team_work_notes ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY team_work_notes_select ON team_work_notes
        FOR SELECT
        USING (
            {_PLATFORM_ADMIN}
            OR (lead_uuid IS NOT NULL AND team_manager_reaches_lead(lead_uuid))
            OR (
                task_uuid IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM public.tasks AS t
                    WHERE t.id = team_work_notes.task_uuid
                      AND team_manager_reaches(
                          t.assigned_employee_profile_uuid, t.business_line::text
                      )
                )
            )
            OR (
                current_setting('app.role', true) = 'telecaller'
                AND lead_uuid IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM public.leads AS l
                    WHERE l.id = team_work_notes.lead_uuid
                      AND l.assigned_telecaller_profile_uuid IS NOT NULL
                      AND l.assigned_telecaller_profile_uuid::text
                          = current_setting('app.staff_profile_uuid', true)
                )
            )
            OR (
                current_setting('app.role', true) = 'employee'
                AND task_uuid IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM public.tasks AS t
                    WHERE t.id = team_work_notes.task_uuid
                      AND t.assigned_employee_profile_uuid IS NOT NULL
                      AND t.assigned_employee_profile_uuid::text
                          = current_setting('app.staff_profile_uuid', true)
                )
            )
        )
        """
    )

    op.execute(
        """
        CREATE POLICY field_visibility_config_team_manager_select ON field_visibility_config
        FOR SELECT
        USING (
            current_setting('app.role', true) = 'sub_admin'
            AND current_setting('app.staff_profile_uuid', true) <> ''
            AND target_role::text IN ('telecaller', 'employee')
            AND EXISTS (
                SELECT 1 FROM public.staff_teams AS team
                WHERE team.manager_staff_profile_uuid::text
                      = current_setting('app.staff_profile_uuid', true)
                  AND team.archived_at IS NULL
                  AND team.member_role = field_visibility_config.target_role::text
            )
        )
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION team_manager_set_lead_status(target_lead_uuid uuid, new_status text)
        RETURNS text
        LANGUAGE plpgsql
        {_DEFINER}
        AS $$
        DECLARE
            lead_row public.leads%ROWTYPE;
        BEGIN
            SELECT * INTO lead_row FROM public.leads WHERE id = target_lead_uuid FOR UPDATE;
            IF NOT FOUND OR NOT team_manager_reaches(
                lead_row.assigned_telecaller_profile_uuid, lead_row.business_line::text
            ) THEN
                RAISE EXCEPTION 'lead is not in the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF lead_row.status::text NOT IN ('assigned', 'working') THEN
                RAISE EXCEPTION 'only open leads can be changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF new_status IS NULL
               OR new_status NOT IN ('working', 'converted', 'closed')
               OR new_status = lead_row.status::text THEN
                RAISE EXCEPTION 'unsupported lead status change'
                    USING ERRCODE = 'check_violation';
            END IF;
            UPDATE public.leads
               SET status = new_status::lead_status, updated_at = now()
             WHERE id = target_lead_uuid;
            RETURN lead_row.status::text;
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION team_manager_update_task(
            target_task_uuid uuid, new_due_at timestamptz, cancel boolean
        )
        RETURNS text
        LANGUAGE plpgsql
        {_DEFINER}
        AS $$
        DECLARE
            task_row public.tasks%ROWTYPE;
        BEGIN
            SELECT * INTO task_row FROM public.tasks WHERE id = target_task_uuid FOR UPDATE;
            IF NOT FOUND OR NOT team_manager_reaches(
                task_row.assigned_employee_profile_uuid, task_row.business_line::text
            ) THEN
                RAISE EXCEPTION 'task is not in the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF task_row.status::text NOT IN ('assigned', 'in_progress', 'blocked') THEN
                RAISE EXCEPTION 'only open tasks can be changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF coalesce(cancel, false) = (new_due_at IS NOT NULL) THEN
                RAISE EXCEPTION 'change the due date or cancel, one at a time'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF coalesce(cancel, false) THEN
                UPDATE public.tasks
                   SET status = 'cancelled'::task_status, updated_at = now()
                 WHERE id = target_task_uuid;
            ELSE
                IF new_due_at <= now() THEN
                    RAISE EXCEPTION 'due date must be in the future'
                        USING ERRCODE = 'check_violation';
                END IF;
                UPDATE public.tasks
                   SET due_at = new_due_at, updated_at = now()
                 WHERE id = target_task_uuid;
            END IF;
            RETURN task_row.status::text;
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION team_manager_add_note(
            target_lead_uuid uuid, target_task_uuid uuid, note_body text, note_follow_up timestamptz
        )
        RETURNS uuid
        LANGUAGE plpgsql
        {_DEFINER}
        AS $$
        DECLARE
            note_line text;
            author_label text;
            new_id uuid := gen_random_uuid();
        BEGIN
            IF (target_lead_uuid IS NULL) = (target_task_uuid IS NULL) THEN
                RAISE EXCEPTION 'a note belongs to one lead or one task'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF target_lead_uuid IS NOT NULL THEN
                IF NOT team_manager_reaches_lead(target_lead_uuid) THEN
                    RAISE EXCEPTION 'lead is not in the caller''s team'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                SELECT business_line::text INTO note_line
                  FROM public.leads WHERE id = target_lead_uuid;
            ELSE
                SELECT t.business_line::text INTO note_line
                  FROM public.tasks AS t
                 WHERE t.id = target_task_uuid
                   AND team_manager_reaches(
                       t.assigned_employee_profile_uuid, t.business_line::text
                   );
                IF note_line IS NULL THEN
                    RAISE EXCEPTION 'task is not in the caller''s team'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF note_follow_up IS NOT NULL THEN
                    RAISE EXCEPTION 'follow-up dates belong on leads'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            IF note_follow_up IS NOT NULL AND note_follow_up <= now() THEN
                RAISE EXCEPTION 'follow-up must be in the future'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT btrim(u.first_name || ' ' || u.last_name) INTO author_label
              FROM public.auth_users AS u
             WHERE u.id::text = current_setting('app.auth_user_uuid', true);
            INSERT INTO public.team_work_notes (
                id, lead_uuid, task_uuid, business_line, author_staff_profile_uuid,
                author_auth_user_uuid, author_name, body, follow_up_at
            ) VALUES (
                new_id, target_lead_uuid, target_task_uuid, note_line::business_line_enum,
                current_setting('app.staff_profile_uuid', true)::uuid,
                current_setting('app.auth_user_uuid', true)::uuid,
                coalesce(author_label, 'Manager'), btrim(note_body), note_follow_up
            );
            RETURN new_id;
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION team_lead_signals(p_lead_uuids uuid[])
        RETURNS TABLE (
            lead_uuid uuid,
            client_referral_code text,
            agent_code text,
            loan_statuses text[],
            last_disposition text,
            last_interest_level text
        )
        LANGUAGE plpgsql
        STABLE
        {_DEFINER}
        AS $$
        #variable_conflict use_column
        BEGIN
            IF coalesce(current_setting('app.role', true), '') <> 'sub_admin' THEN
                RETURN;
            END IF;
            IF coalesce(array_length(p_lead_uuids, 1), 0) > 1000 THEN
                RAISE EXCEPTION 'too many leads requested' USING ERRCODE = '22023';
            END IF;

            RETURN QUERY
            WITH visible AS (
                SELECT l.id, l.mobile, l.client_profile_uuid, l.origin,
                       l.origin_agent_profile_uuid, l.business_line
                FROM public.leads AS l
                WHERE l.id = ANY (p_lead_uuids)
                  AND team_manager_reaches_lead(l.id)
            )
            SELECT
                v.id,
                (
                    SELECT rc.code
                    FROM public.referrals AS r
                    JOIN public.referral_codes AS rc
                      ON rc.auth_user_uuid = r.referrer_auth_user_uuid
                    WHERE r.referred_lead_uuid = v.id
                       OR r.referred_mobile = v.mobile
                       OR (
                           r.referred_auth_user_uuid IS NOT NULL
                           AND r.referred_auth_user_uuid = (
                               SELECT cp.auth_user_uuid
                               FROM public.client_profiles AS cp
                               WHERE cp.id = v.client_profile_uuid
                           )
                       )
                    ORDER BY r.created_at DESC
                    LIMIT 1
                ),
                (
                    SELECT ap.agent_code::text
                    FROM public.agent_profiles AS ap
                    WHERE v.origin::text = 'agent' AND ap.id = v.origin_agent_profile_uuid
                ),
                ARRAY(
                    SELECT DISTINCT la.status::text
                    FROM public.loan_applications AS la
                    WHERE la.lead_uuid = v.id
                    ORDER BY 1
                ),
                last_call.disposition::text,
                last_call.interest_level::text
            FROM visible AS v
            LEFT JOIN LATERAL (
                SELECT a.disposition, a.interest_level
                FROM public.lead_activities AS a
                WHERE a.lead_uuid = v.id AND a.business_line = v.business_line
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 1
            ) AS last_call ON true;
        END;
        $$
        """
    )

    for function in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO api_user")


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS field_visibility_config_team_manager_select "
        "ON field_visibility_config"
    )
    op.execute("DROP POLICY IF EXISTS team_work_notes_select ON team_work_notes")
    for function in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("REVOKE ALL PRIVILEGES ON team_work_notes FROM api_user")
    op.drop_index(op.f("ix_team_work_notes_task_uuid"), table_name="team_work_notes")
    op.drop_index(op.f("ix_team_work_notes_lead_uuid"), table_name="team_work_notes")
    op.drop_table("team_work_notes")
