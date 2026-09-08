from __future__ import annotations

from alembic import op


revision = "20260905_05"
down_revision = "20260813_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_runs ADD COLUMN effective_model TEXT")
    op.execute("ALTER TABLE ai_runs ADD COLUMN effective_base_url TEXT")
    op.execute("ALTER TABLE ai_runs ADD COLUMN effective_wire_api TEXT")
    op.execute("ALTER TABLE ai_runs ADD COLUMN fallback_used BIGINT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ai_runs ADD COLUMN primary_error TEXT NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX idx_ai_runs_effective_model ON ai_runs(effective_model, fallback_used, id DESC)")


def downgrade() -> None:
    raise RuntimeError("AI故障转移审计是运行证据，请从升级前备份恢复")
