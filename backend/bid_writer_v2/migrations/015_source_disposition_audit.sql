CREATE TABLE knowledge_source_dispositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_run_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    decision_stage TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    evidence_quote TEXT NOT NULL DEFAULT '',
    actor_type TEXT NOT NULL DEFAULT 'ai',
    ai_run_id INTEGER,
    prompt_key TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pipeline_run_id, document_id, decision_stage),
    FOREIGN KEY(pipeline_run_id) REFERENCES knowledge_ai_pipeline_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE,
    FOREIGN KEY(ai_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_knowledge_source_dispositions_source
ON knowledge_source_dispositions(source_id, decision_stage, id DESC);
