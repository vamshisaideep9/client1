"""Record when a task was completed (CS-027 security review).

Revision ID: b9e1a3c5d7f0
Revises: a8d0f2b4c6e9

Contest scoring credits an Employee for a case only when they completed a
task on its lead before the case reached the counted stage, and counts tasks
completed / on time inside the contest dates. Tasks had no completion time
(staff analytics used ``updated_at``, which any later edit moves), so:

- ``tasks.completed_at`` (nullable timestamptz);
- backfill: an existing completed task gets its ``updated_at`` (the best
  record available; contests cannot start before their approval, so older
  completions never decide a contest);
- trigger ``trg_tasks_completed_at`` (BEFORE INSERT OR UPDATE): entering
  ``completed`` stamps ``now()`` (a request-session write can never
  backdate it; a bypass-session insert may carry its own value), a completed
  task keeps its first completion time, and any other status clears it.
  Completed is terminal in every task path today (only a cancelled task can
  be reopened), so the column is set once.

``api_user`` already holds a table-wide UPDATE grant on ``tasks``; no grant
change. Rollback drops the trigger, its function and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9e1a3c5d7f0"
down_revision: str | Sequence[str] | None = "a8d0f2b4c6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'completed'")
    op.create_index(
        "ix_tasks_completed_at",
        "tasks",
        ["completed_at"],
        postgresql_where=sa.text("completed_at IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION tasks_stamp_completed_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        BEGIN
            IF NEW.status::text = 'completed' THEN
                IF TG_OP = 'UPDATE' AND OLD.status::text = 'completed' THEN
                    NEW.completed_at := OLD.completed_at;
                ELSIF NEW.completed_at IS NULL OR current_user = 'api_user' THEN
                    NEW.completed_at := now();
                END IF;
            ELSE
                NEW.completed_at := NULL;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_tasks_completed_at BEFORE INSERT OR UPDATE ON tasks "
        "FOR EACH ROW EXECUTE FUNCTION tasks_stamp_completed_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tasks_completed_at ON tasks")
    op.execute("DROP FUNCTION IF EXISTS tasks_stamp_completed_at()")
    op.drop_index("ix_tasks_completed_at", table_name="tasks")
    op.drop_column("tasks", "completed_at")
