from __future__ import annotations

from pathlib import Path

from alembic import op

from bid_writer_v2.database import postgres_migration_statements


revision = "20260813_04"
down_revision = "20260812_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "bid_writer_v2" / "migrations"
    for statement in postgres_migration_statements(root, through="015_source_disposition_audit.sql"):
        if statement.startswith(("CREATE TABLE knowledge_source_dispositions", "CREATE INDEX idx_knowledge_source_dispositions")):
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("逐来源AI处置包含正式审计记录，请从升级前备份恢复")
