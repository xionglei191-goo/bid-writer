from __future__ import annotations

from pathlib import Path

from alembic import op

from bid_writer_v2.database import postgres_migration_statements


revision = "20260908_06"
down_revision = "20260905_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "bid_writer_v2" / "migrations"
    prefixes = (
        "CREATE TABLE requirement_classifications", "CREATE TABLE requirement_workflow_events",
        "CREATE INDEX idx_requirement_classifications", "CREATE INDEX idx_requirement_workflow_events",
    )
    for statement in postgres_migration_statements(root, through="018_requirement_classification.sql"):
        if statement.startswith(prefixes):
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("条款分类与响应包含人工审核记录，请从升级前备份恢复")
