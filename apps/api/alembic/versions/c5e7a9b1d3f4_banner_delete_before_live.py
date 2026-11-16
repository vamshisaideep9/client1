"""Sub Admin may delete a banner until it goes live.

Revision ID: c5e7a9b1d3f4
Revises: b2d4f6a8c0e1

2026-11-16 product decision (client-reported CMS bugs): a Sub Admin can delete
a banner while it is ``draft``, ``pending_approval``, ``rejected`` or
``approved`` (approved but not yet serving). Once a banner is ``live`` it can
only be taken down by the platform Admin's existing soft Remove, which keeps
the row and its review/audit history. ``archived`` rows and rows already soft
removed are never hard-deleted.

Only the DELETE policy changes. The predicate stays role-only for Sub Admin
(the shared content-team queue has no owner scope) and adds no
``app.platform_scope`` branch, so no Admin or any other role gains a delete
path. ``DELETE ... RETURNING`` additionally needs the existing
``banners_select`` policy, which already admits Sub Admin.

The API route issues one conditional ``DELETE ... WHERE status IN (...)
RETURNING id`` under this policy, so a banner the activation job or an Admin
approval flips to ``live`` in the meantime is not deleted.

Rollback restores the previous draft-only policy from ee56ff78aa90.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5e7a9b1d3f4"
down_revision: str | Sequence[str] | None = "b2d4f6a8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS banners_delete ON banners")
    op.execute(
        """CREATE POLICY banners_delete ON banners FOR DELETE USING (
        current_setting('app.role', true) = 'sub_admin'
        AND removed_at IS NULL
        AND status::text IN ('draft', 'pending_approval', 'rejected', 'approved'))"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS banners_delete ON banners")
    op.execute(
        """CREATE POLICY banners_delete ON banners FOR DELETE USING (
        current_setting('app.role', true) = 'sub_admin' AND status::text = 'draft')"""
    )
