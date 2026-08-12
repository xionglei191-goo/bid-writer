from __future__ import annotations

from pathlib import Path

from alembic import op

from bid_writer_v2.database import postgres_migration_statements


revision = "20260812_03"
down_revision = "20260809_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "bid_writer_v2" / "migrations"
    for statement in postgres_migration_statements(root):
        if statement.startswith(("CREATE TABLE corpus_", "CREATE TABLE knowledge_review_decisions", "CREATE TABLE governance_tasks", "CREATE TABLE governance_task_sources", "CREATE INDEX idx_corpus_", "CREATE INDEX idx_knowledge_review", "CREATE INDEX idx_governance", "ALTER TABLE standard_documents ADD COLUMN source_hash", "ALTER TABLE standard_documents ADD COLUMN parser_version", "ALTER TABLE knowledge_assets ADD COLUMN")):
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("全库收口迁移包含审计与人工待办记录，请从升级前备份恢复")
