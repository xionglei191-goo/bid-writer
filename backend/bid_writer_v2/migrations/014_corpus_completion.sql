CREATE TABLE corpus_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    stage TEXT NOT NULL DEFAULT 'inventory',
    progress INTEGER NOT NULL DEFAULT 0,
    policy_json TEXT NOT NULL DEFAULT '{}',
    counters_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    recent_results_json TEXT NOT NULL DEFAULT '[]',
    pause_reason TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_corpus_runs_status ON corpus_runs(status,id DESC);

CREATE TABLE corpus_run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'inventory',
    status TEXT NOT NULL DEFAULT 'pending',
    terminal_reason TEXT NOT NULL DEFAULT '',
    processing_job_id INTEGER,
    document_id INTEGER,
    pipeline_run_id INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    next_retry_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    UNIQUE(run_id,source_id),
    FOREIGN KEY(run_id) REFERENCES corpus_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE,
    FOREIGN KEY(processing_job_id) REFERENCES processing_jobs(id) ON DELETE SET NULL,
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE SET NULL,
    FOREIGN KEY(pipeline_run_id) REFERENCES knowledge_ai_pipeline_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_corpus_run_items_work ON corpus_run_items(run_id,status,stage,id);

CREATE TABLE knowledge_review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    candidate_id INTEGER,
    unit_id INTEGER,
    decision_stage TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    findings_json TEXT NOT NULL DEFAULT '[]',
    ai_run_id INTEGER,
    prompt_key TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES corpus_runs(id) ON DELETE SET NULL,
    FOREIGN KEY(candidate_id) REFERENCES knowledge_ai_candidates(id) ON DELETE SET NULL,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL,
    FOREIGN KEY(ai_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_knowledge_review_decisions_target ON knowledge_review_decisions(candidate_id,unit_id,id);

CREATE TABLE governance_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    source_id INTEGER,
    task_key TEXT NOT NULL,
    task_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    requires_human INTEGER NOT NULL DEFAULT 1,
    resolution TEXT NOT NULL DEFAULT '',
    resolved_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    UNIQUE(run_id,task_key),
    FOREIGN KEY(run_id) REFERENCES corpus_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE SET NULL,
    FOREIGN KEY(resolved_by) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_governance_tasks_open ON governance_tasks(status,task_type,id);

CREATE TABLE governance_task_sources (
    task_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    PRIMARY KEY(task_id,source_id),
    FOREIGN KEY(task_id) REFERENCES governance_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE
);
CREATE INDEX idx_governance_task_sources_source ON governance_task_sources(source_id,task_id);

CREATE TABLE corpus_section_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    representative_section_id INTEGER NOT NULL,
    member_section_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    lexical_score REAL NOT NULL DEFAULT 0,
    semantic_score REAL NOT NULL DEFAULT 0,
    conflict_detected INTEGER NOT NULL DEFAULT 0,
    explanation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id,member_section_id),
    FOREIGN KEY(run_id) REFERENCES corpus_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(representative_section_id) REFERENCES document_sections(id) ON DELETE CASCADE,
    FOREIGN KEY(member_section_id) REFERENCES document_sections(id) ON DELETE CASCADE
);
CREATE INDEX idx_corpus_section_clusters_representative ON corpus_section_clusters(run_id,representative_section_id);

ALTER TABLE standard_documents ADD COLUMN source_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE standard_documents ADD COLUMN parser_version TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_assets ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_assets ADD COLUMN perceptual_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_assets ADD COLUMN width INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_assets ADD COLUMN height INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_assets ADD COLUMN governance_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE knowledge_assets ADD COLUMN exclusion_reason TEXT NOT NULL DEFAULT '';
