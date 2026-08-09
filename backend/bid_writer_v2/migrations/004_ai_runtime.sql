CREATE TABLE ai_prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_key TEXT NOT NULL,
    version TEXT NOT NULL,
    instructions TEXT NOT NULL,
    template TEXT NOT NULL,
    output_schema_json TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prompt_key, version)
);

CREATE TABLE ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    prompt_key TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    model TEXT,
    base_url TEXT,
    wire_api TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    input_json TEXT NOT NULL DEFAULT '{}',
    output_text TEXT NOT NULL DEFAULT '',
    output_json TEXT,
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_from_run_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(cached_from_run_id) REFERENCES ai_runs(id) ON DELETE SET NULL
);
CREATE INDEX idx_ai_runs_cache ON ai_runs(cache_key, status, id DESC);
CREATE INDEX idx_ai_runs_target ON ai_runs(target_type, target_id, id DESC);
CREATE INDEX idx_ai_runs_task ON ai_runs(task_type, id DESC);
