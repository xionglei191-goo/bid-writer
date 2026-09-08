CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO organizations(name) VALUES ('默认组织');

CREATE TABLE app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    auth_source TEXT NOT NULL DEFAULT 'local',
    oidc_subject TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
);

CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);
INSERT INTO roles(code,name) VALUES
    ('admin','系统管理员'),
    ('author','编制人员'),
    ('reviewer','审核人员'),
    ('viewer','只读用户');

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY(user_id,role_id),
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE,
    FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE
);

CREATE TABLE auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    FOREIGN KEY(user_id) REFERENCES app_users(id) ON DELETE CASCADE
);
CREATE INDEX idx_auth_sessions_user ON auth_sessions(user_id,expires_at);

CREATE TABLE oidc_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_hash TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    remote_address TEXT NOT NULL DEFAULT '',
    succeeded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_login_attempts_recent ON login_attempts(username,created_at);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    actor_user_id INTEGER,
    actor_name TEXT NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'success',
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_hash TEXT NOT NULL DEFAULT '',
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(actor_user_id) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_audit_events_target ON audit_events(target_type,target_id,id DESC);

CREATE TABLE app_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_app_jobs_status ON app_jobs(status,created_at);

CREATE TABLE job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES app_jobs(id) ON DELETE CASCADE
);
CREATE INDEX idx_job_events_job ON job_events(job_id,id);

CREATE TABLE object_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_key TEXT NOT NULL UNIQUE,
    bucket TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    local_mirror_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    section_id INTEGER,
    parent_chunk_id INTEGER,
    order_no INTEGER NOT NULL,
    heading TEXT NOT NULL,
    content TEXT NOT NULL,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    page_start INTEGER,
    page_end INTEGER,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id,order_no,content_hash),
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES document_sections(id) ON DELETE SET NULL,
    FOREIGN KEY(parent_chunk_id) REFERENCES document_chunks(id) ON DELETE SET NULL
);
CREATE INDEX idx_document_chunks_document ON document_chunks(document_id,order_no);

CREATE TABLE candidate_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    related_candidate_id INTEGER,
    related_unit_id INTEGER,
    relation_type TEXT NOT NULL,
    lexical_score REAL NOT NULL DEFAULT 0,
    semantic_score REAL NOT NULL DEFAULT 0,
    explanation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(candidate_id) REFERENCES knowledge_ai_candidates(id) ON DELETE CASCADE,
    FOREIGN KEY(related_candidate_id) REFERENCES knowledge_ai_candidates(id) ON DELETE CASCADE,
    FOREIGN KEY(related_unit_id) REFERENCES knowledge_units(id) ON DELETE CASCADE
);
CREATE INDEX idx_candidate_relations_candidate ON candidate_relations(candidate_id,relation_type);

CREATE TABLE knowledge_auto_publish_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    failed_sample_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'sampling_required',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE retrieval_indexes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    embedding_model TEXT NOT NULL,
    reranker_model TEXT NOT NULL,
    bm25_object_key TEXT NOT NULL DEFAULT '',
    qdrant_collection TEXT NOT NULL,
    publication_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'building',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at TEXT
);

CREATE TABLE retrieval_runs_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    query TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    index_version TEXT NOT NULL,
    bm25_count INTEGER NOT NULL DEFAULT 0,
    dense_count INTEGER NOT NULL DEFAULT 0,
    result_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    results_json TEXT NOT NULL DEFAULT '[]',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES app_users(id) ON DELETE SET NULL
);

CREATE TABLE retrieval_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieval_run_id INTEGER NOT NULL,
    unit_id INTEGER,
    action TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(retrieval_run_id) REFERENCES retrieval_runs_v2(id) ON DELETE CASCADE,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES app_users(id) ON DELETE SET NULL
);

CREATE TABLE generation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    section_id INTEGER,
    draft_id INTEGER,
    retrieval_run_id INTEGER,
    input_hash TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    rule_version TEXT NOT NULL DEFAULT '',
    knowledge_snapshot_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES project_sections(id) ON DELETE SET NULL,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE SET NULL,
    FOREIGN KEY(retrieval_run_id) REFERENCES retrieval_runs_v2(id) ON DELETE SET NULL
);

CREATE TABLE claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_run_id INTEGER NOT NULL,
    draft_id INTEGER NOT NULL,
    claim_index INTEGER NOT NULL,
    claim_type TEXT NOT NULL,
    text TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'low',
    support_status TEXT NOT NULL DEFAULT 'pending',
    confidence REAL NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(draft_id,claim_index,content_hash),
    FOREIGN KEY(generation_run_id) REFERENCES generation_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE
);
CREATE INDEX idx_claims_draft ON claims(draft_id,support_status,risk_level);

CREATE TABLE evidence_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    unit_id INTEGER,
    publication_id INTEGER,
    retrieval_run_id INTEGER,
    source_excerpt TEXT NOT NULL DEFAULT '',
    source_page INTEGER,
    support_level TEXT NOT NULL DEFAULT 'unsupported',
    score REAL NOT NULL DEFAULT 0,
    evidence_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL,
    FOREIGN KEY(publication_id) REFERENCES knowledge_publications(id) ON DELETE SET NULL,
    FOREIGN KEY(retrieval_run_id) REFERENCES retrieval_runs_v2(id) ON DELETE SET NULL
);

CREATE TABLE quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    draft_id INTEGER,
    issue_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    resolution TEXT NOT NULL DEFAULT '',
    resolved_by INTEGER,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE,
    FOREIGN KEY(resolved_by) REFERENCES app_users(id) ON DELETE SET NULL
);
CREATE INDEX idx_quality_issues_project ON quality_issues(project_id,status,severity);

CREATE TABLE delivery_manifests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    delivery_id INTEGER,
    project_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'frozen',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    invalidated_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(delivery_id) REFERENCES deliveries(id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES app_users(id) ON DELETE SET NULL
);

ALTER TABLE source_files ADD COLUMN classification TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE knowledge_units ADD COLUMN classification TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE projects ADD COLUMN classification TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE deliveries ADD COLUMN classification TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE knowledge_ai_candidates ADD COLUMN chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL;
ALTER TABLE knowledge_ai_candidates ADD COLUMN adjudication_decision TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_ai_candidates ADD COLUMN adjudication_confidence REAL NOT NULL DEFAULT 0;
ALTER TABLE knowledge_ai_candidates ADD COLUMN auto_publish_batch_id INTEGER REFERENCES knowledge_auto_publish_batches(id) ON DELETE SET NULL;
ALTER TABLE project_drafts ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'pending';
