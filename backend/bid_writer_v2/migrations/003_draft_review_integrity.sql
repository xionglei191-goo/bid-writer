ALTER TABLE project_drafts ADD COLUMN content_hash TEXT;

CREATE TABLE draft_review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'approved',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE
);
CREATE INDEX idx_draft_review_target ON draft_review_decisions(draft_id, target_hash, decision);

CREATE TABLE confirmation_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL,
    confirmation_index INTEGER NOT NULL,
    confirmation_text TEXT NOT NULL,
    resolution TEXT NOT NULL,
    resolver TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(draft_id, confirmation_index, target_hash),
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE
);
CREATE INDEX idx_confirmation_resolution_target ON confirmation_resolutions(draft_id, target_hash);
