"""Add health alerts table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20241214_04_add_health_alerts"
down_revision = "20241214_03_add_referral_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_health_alerts_code", "health_alerts", ["code"])


def downgrade() -> None:
    op.drop_index("ix_health_alerts_code", table_name="health_alerts")
    op.drop_table("health_alerts")
