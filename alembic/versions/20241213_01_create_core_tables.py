"""Create core history tables

Revision ID: 20241213_01
Revises: 
Create Date: 2025-12-13 21:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20241213_01"
down_revision = None
branch_labels = None
depends_on = None


CURRENT_TS = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True, server_default=sa.text("'success'")),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True, server_default=CURRENT_TS),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "user_stats",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("total_downloads", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_download", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_download", sa.DateTime(timezone=True), nullable=True, server_default=CURRENT_TS),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "platform_stats",
        sa.Column("platform", sa.Text(), primary_key=True),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "authorized_admins",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True, server_default=CURRENT_TS),
    )

    op.create_table(
        "chats",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("chat_type", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=CURRENT_TS),
    )


def downgrade() -> None:
    op.drop_table("chats")
    op.drop_table("authorized_admins")
    op.drop_table("platform_stats")
    op.drop_table("user_stats")
    op.drop_table("downloads")
