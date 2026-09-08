from __future__ import annotations

from alembic import op


revision = "20260908_07"
down_revision = "20260908_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE generation_runs ADD COLUMN project_source_hash TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE claims ADD COLUMN analysis_json TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE evidence_links ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'legacy'")
    op.execute("ALTER TABLE evidence_links ADD COLUMN source_title TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE evidence_links ADD COLUMN source_meta_json TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE evidence_links ADD COLUMN project_source_hash TEXT NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX idx_generation_runs_project_source ON generation_runs(project_id,draft_id,project_source_hash)")
    op.execute("""
        CREATE TABLE claim_review_events (
            id BIGSERIAL PRIMARY KEY,
            claim_id BIGINT REFERENCES claims(id) ON DELETE SET NULL,
            draft_id BIGINT NOT NULL REFERENCES project_drafts(id) ON DELETE CASCADE,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            claim_text TEXT NOT NULL,
            claim_hash TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            resolution TEXT NOT NULL,
            target_hash TEXT NOT NULL,
            project_source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX idx_claim_review_events_draft ON claim_review_events(draft_id,id)")


def downgrade() -> None:
    raise RuntimeError("项目证据与人工核验历史不可直接删除，请从升级前备份恢复")
