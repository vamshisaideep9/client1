"""Add effective-dated monthly rules and isolated leave certificate references."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c5e7a9b1d3f7"
down_revision = "b4d6f8a0c2e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attendance_policies",
        sa.Column("monthly_leave_rules", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("attendance_policies", sa.Column("certificate_retention_days", sa.SmallInteger()))
    op.add_column(
        "attendance_requests",
        sa.Column("monthly_charges", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("attendance_requests", sa.Column("certificate_retention_days", sa.SmallInteger()))
    for table in ("attendance_policies", "attendance_requests"):
        op.create_check_constraint(
            f"{table}_certificate_retention",
            table,
            "certificate_retention_days BETWEEN 1 AND 3660",
        )
    op.create_table(
        "attendance_certificates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("request_id", sa.UUID(), unique=True),
        sa.Column("object_key", sa.String(144), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["attendance_requests.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png')",
            name="attendance_certificate_content_type",
        ),
    )
    op.create_index("ix_attendance_certificate_expiry", "attendance_certificates", ["expires_at"])
    op.execute("GRANT SELECT ON attendance_certificates TO api_user")
    op.execute("ALTER TABLE attendance_certificates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY attendance_certificate_read ON attendance_certificates
        FOR SELECT TO api_user USING (
            request_id IS NOT NULL AND expires_at > now()
            AND (
                (current_setting('app.role', true) = 'admin'
                    AND current_setting('app.platform_scope', true) = 'true')
                OR EXISTS (
                    SELECT 1 FROM public.attendance_requests AS r
                    WHERE r.id = attendance_certificates.request_id
                      AND r.requester_id::text = current_setting('app.auth_user_uuid', true)
                      AND r.staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
                )
            )
        )
    """)


def downgrade() -> None:
    with_data = op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM attendance_certificates)
            OR EXISTS (SELECT 1 FROM attendance_requests
                WHERE monthly_charges <> '{}'::jsonb OR certificate_retention_days IS NOT NULL)
            OR EXISTS (SELECT 1 FROM attendance_policies
                WHERE monthly_leave_rules <> '{}'::jsonb OR certificate_retention_days IS NOT NULL)
    """)
    )
    if with_data:
        raise RuntimeError(
            "Rollback would discard leave rules, charges, or certificate references."
        )
    op.drop_table("attendance_certificates")
    for table in ("attendance_requests", "attendance_policies"):
        op.drop_constraint(f"{table}_certificate_retention", table, type_="check")
        op.drop_column(table, "certificate_retention_days")
    op.drop_column("attendance_requests", "monthly_charges")
    op.drop_column("attendance_policies", "monthly_leave_rules")
