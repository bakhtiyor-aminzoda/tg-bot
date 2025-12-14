"""Add referral tables for invite tracking"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20241214_03_add_referral_tables"
down_revision = "20241214_02_add_subscription_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("boost_daily_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boost_monthly_quota", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_referral_codes_user_id", "referral_codes", ["user_id"])

    op.create_table(
        "referral_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code_id", sa.Integer(), sa.ForeignKey("referral_codes.id", ondelete="SET NULL")),
        sa.Column("referrer_user_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reward_daily_bonus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reward_monthly_bonus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reward_expires_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_referral_events_code_id", "referral_events", ["code_id"])
    op.create_index("ix_referral_events_referrer_user_id", "referral_events", ["referrer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_events_referrer_user_id", table_name="referral_events")
    op.drop_index("ix_referral_events_code_id", table_name="referral_events")
    op.drop_table("referral_events")

    op.drop_index("ix_referral_codes_user_id", table_name="referral_codes")
    op.drop_table("referral_codes")
