ALTER TABLE generation_runs ADD COLUMN project_source_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN analysis_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE evidence_links ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE evidence_links ADD COLUMN source_title TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_links ADD COLUMN source_meta_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE evidence_links ADD COLUMN project_source_hash TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_generation_runs_project_source ON generation_runs(project_id,draft_id,project_source_hash);
CREATE TABLE claim_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER,
    draft_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    claim_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    resolution TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    project_source_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE SET NULL,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX idx_claim_review_events_draft ON claim_review_events(draft_id,id);
