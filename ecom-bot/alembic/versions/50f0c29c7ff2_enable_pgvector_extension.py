"""enable pgvector extension

Baseline migration for TASK-008: makes the PostgreSQL+pgvector capability available
before any tables are created. Table schema (DATA-001) is added by TASK-010 and the
embedding column/index by TASK-018.

Revision ID: 50f0c29c7ff2
Revises:
Create Date: 2026-10-17 05:43:15.074426

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50f0c29c7ff2"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable the pgvector extension (idempotent)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Drop the pgvector extension.

    Safe as the baseline revision: no earlier migration or table can depend on it.
    """
    op.execute("DROP EXTENSION IF EXISTS vector")
