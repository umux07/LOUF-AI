"""Persist generated media jobs and their private file locations.

Revision ID: 0003_media_jobs
Revises: 0002_guests_password_reset
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_media_jobs"
down_revision = "0002_guests_password_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(10), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("provider_prompt_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_media_jobs_user_id", "media_jobs", ["user_id"])
    op.create_index(
        "ix_media_jobs_user_created", "media_jobs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_media_jobs_provider_prompt_id",
        "media_jobs",
        ["provider_prompt_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_media_jobs_provider_prompt_id", table_name="media_jobs")
    op.drop_index("ix_media_jobs_user_created", table_name="media_jobs")
    op.drop_index("ix_media_jobs_user_id", table_name="media_jobs")
    op.drop_table("media_jobs")
