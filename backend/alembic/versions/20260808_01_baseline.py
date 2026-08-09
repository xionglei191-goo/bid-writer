from __future__ import annotations

from pathlib import Path

from alembic import op

from bid_writer_v2.database import postgres_migration_statements


revision = "20260808_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "bid_writer_v2" / "migrations"
    for statement in postgres_migration_statements(root, through="012_resumable_knowledge_pipeline.sql"):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("基线迁移不可自动回退；请从执行迁移前的备份恢复")
