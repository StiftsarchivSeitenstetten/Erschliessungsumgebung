"""Make user email optional and non-unique.

Revision ID: 20260915_0002
Revises: 20260911_0001
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260915_0002"
down_revision = "20260911_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    null_count = connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE email IS NULL"))
    duplicate_email = connection.execute(
        sa.text("SELECT email FROM users GROUP BY email HAVING COUNT(*) > 1 LIMIT 1")
    ).first()
    if null_count or duplicate_email is not None:
        raise RuntimeError(
            "Downgrade nicht moeglich: NULL- oder doppelte E-Mail-Adressen sind vorhanden."
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.create_index("ix_users_email", ["email"], unique=True)
