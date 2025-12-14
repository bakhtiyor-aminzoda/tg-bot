"""Add subscription plans and user quotas tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20241214_02_add_subscription_tables"
down_revision = "20241213_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("plan", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("daily_quota", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("monthly_quota", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_parallel_downloads", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price_usd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "user_quotas",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("plan", sa.Text(), sa.ForeignKey("subscription_plans.plan", onupdate="CASCADE"), nullable=False),
        sa.Column("custom_daily_quota", sa.Integer()),
        sa.Column("custom_monthly_quota", sa.Integer()),
        sa.Column("daily_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_reset_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("current_period_start", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan"], ["subscription_plans.plan"], name="fk_user_quotas_plan"),
    )


def downgrade() -> None:
    op.drop_table("user_quotas")
    op.drop_table("subscription_plans")
