from __future__ import annotations

from alembic import op


revision = "20260809_02"
down_revision = "20260808_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_status TEXT NOT NULL DEFAULT 'pending'")
    op.execute("ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_decision TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_confidence DOUBLE PRECISION NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_issues_json TEXT NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_run_id BIGINT REFERENCES ai_runs(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX idx_retrieval_eval_cases_ai_review ON retrieval_eval_cases(dataset_name, ai_review_status, status)")


def downgrade() -> None:
    raise RuntimeError("该迁移包含评测审核记录，不支持自动降级；请从升级前备份恢复")
