CREATE TABLE retrieval_eval_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT NOT NULL DEFAULT 'default',
    source_type TEXT NOT NULL DEFAULT 'silver',
    query TEXT NOT NULL,
    query_kind TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT '',
    unit_type TEXT NOT NULL DEFAULT '',
    expected_unit_ids_json TEXT NOT NULL DEFAULT '[]',
    excluded_unit_ids_json TEXT NOT NULL DEFAULT '[]',
    source_unit_id INTEGER,
    status TEXT NOT NULL DEFAULT 'proposed',
    generated_by_run_id INTEGER,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dataset_name, query),
    FOREIGN KEY(source_unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL,
    FOREIGN KEY(generated_by_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_retrieval_eval_cases_dataset ON retrieval_eval_cases(dataset_name, source_type, status);

CREATE TABLE retrieval_eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    case_count INTEGER NOT NULL,
    publication_snapshot_hash TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_retrieval_eval_runs_dataset ON retrieval_eval_runs(dataset_name, source_type, id DESC);
