CREATE TABLE knowledge_ai_pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    pipeline_key TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    extraction_ai_run_id INTEGER,
    review_ai_run_id INTEGER,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    ready_count INTEGER NOT NULL DEFAULT 0,
    exception_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(extraction_ai_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL,
    FOREIGN KEY(review_ai_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_knowledge_ai_pipeline_document ON knowledge_ai_pipeline_runs(document_id, id DESC);

CREATE TABLE knowledge_ai_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_run_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    source_section_id INTEGER NOT NULL,
    candidate_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    applicability TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    source_quote TEXT NOT NULL DEFAULT '',
    review_decision TEXT NOT NULL DEFAULT 'missing',
    review_confidence REAL NOT NULL DEFAULT 0,
    review_issues_json TEXT NOT NULL DEFAULT '[]',
    rule_findings_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'needs_review',
    unit_id INTEGER,
    reviewed_by TEXT,
    review_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    UNIQUE(pipeline_run_id, candidate_index),
    FOREIGN KEY(pipeline_run_id) REFERENCES knowledge_ai_pipeline_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE,
    FOREIGN KEY(source_section_id) REFERENCES document_sections(id) ON DELETE CASCADE,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL
);
CREATE INDEX idx_knowledge_ai_candidates_status ON knowledge_ai_candidates(status, id DESC);

CREATE TABLE knowledge_exception_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    issue_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    resolved_by TEXT,
    resolution TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    FOREIGN KEY(candidate_id) REFERENCES knowledge_ai_candidates(id) ON DELETE CASCADE
);
CREATE INDEX idx_knowledge_exception_tasks_status ON knowledge_exception_tasks(status, severity, id DESC);
