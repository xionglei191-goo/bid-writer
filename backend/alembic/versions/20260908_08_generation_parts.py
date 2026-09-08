from __future__ import annotations

from alembic import op

revision = "20260908_08"
down_revision = "20260908_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_drafts ADD COLUMN generation_json TEXT NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    raise RuntimeError("章节分包记录是生成审计依据，请使用升级前备份恢复")
