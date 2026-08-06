CREATE TABLE source_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_source_id INTEGER,
    absolute_path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    family_key TEXT NOT NULL,
    industry TEXT,
    source_kind TEXT NOT NULL DEFAULT 'raw',
    duplicate_of INTEGER,
    status TEXT NOT NULL DEFAULT 'discovered',
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(parent_source_id) REFERENCES source_files(id) ON DELETE CASCADE,
    FOREIGN KEY(duplicate_of) REFERENCES source_files(id) ON DELETE SET NULL
);
CREATE INDEX idx_source_files_sha256 ON source_files(sha256);
CREATE INDEX idx_source_files_family ON source_files(family_key);
CREATE INDEX idx_source_files_status ON source_files(status);

CREATE TABLE processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'normalize',
    status TEXT NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    current_step TEXT,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE
);
CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);

CREATE TABLE standard_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    markdown_path TEXT NOT NULL,
    parser TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    text_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE
);

CREATE TABLE document_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    parent_id INTEGER,
    order_no INTEGER NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    heading TEXT NOT NULL,
    content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    content_fingerprint TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES standard_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(parent_id) REFERENCES document_sections(id) ON DELETE SET NULL
);
CREATE INDEX idx_document_sections_document ON document_sections(document_id, order_no);

CREATE TABLE knowledge_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    industry TEXT,
    unit_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_key TEXT NOT NULL UNIQUE,
    unit_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    cleaned_content TEXT NOT NULL,
    industry TEXT,
    project_type TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    risk_level TEXT NOT NULL DEFAULT 'textual',
    status TEXT NOT NULL DEFAULT 'draft',
    content_fingerprint TEXT NOT NULL,
    cluster_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(cluster_id) REFERENCES knowledge_clusters(id) ON DELETE SET NULL
);
CREATE INDEX idx_knowledge_units_status ON knowledge_units(status);
CREATE INDEX idx_knowledge_units_type ON knowledge_units(unit_type, industry);

CREATE TABLE knowledge_unit_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    section_id INTEGER,
    source_id INTEGER NOT NULL,
    excerpt TEXT,
    page_start INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(unit_id, source_id, section_id),
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES document_sections(id) ON DELETE SET NULL,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE
);

CREATE TABLE knowledge_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    origin TEXT NOT NULL DEFAULT 'extracted',
    model TEXT,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'review_required',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(unit_id, version_no),
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE CASCADE
);

CREATE TABLE knowledge_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES knowledge_versions(id) ON DELETE CASCADE
);

CREATE TABLE knowledge_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    publication_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'published',
    published_by TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retired_at TEXT,
    UNIQUE(unit_id, publication_version),
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES knowledge_versions(id) ON DELETE CASCADE
);
CREATE INDEX idx_knowledge_publications_status ON knowledge_publications(status);

CREATE VIRTUAL TABLE published_units_fts USING fts5(
    unit_id UNINDEXED,
    title,
    content,
    tags,
    industry,
    unit_type,
    tokenize='unicode61'
);

CREATE TABLE knowledge_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unit_id INTEGER,
    asset_type TEXT NOT NULL,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE SET NULL,
    FOREIGN KEY(unit_id) REFERENCES knowledge_units(id) ON DELETE SET NULL
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    industry TEXT,
    project_type TEXT,
    region TEXT,
    source_text TEXT,
    profile_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    requirement_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'technical',
    content TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',
    source_page INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE project_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    order_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    requirement_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'planned',
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE project_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    section_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    confirmations_json TEXT NOT NULL DEFAULT '[]',
    version_no INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES project_sections(id) ON DELETE CASCADE
);

CREATE TABLE requirement_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id INTEGER NOT NULL,
    draft_id INTEGER NOT NULL,
    evidence_text TEXT,
    coverage_score REAL NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending',
    content_fingerprint TEXT,
    FOREIGN KEY(requirement_id) REFERENCES project_requirements(id) ON DELETE CASCADE,
    FOREIGN KEY(draft_id) REFERENCES project_drafts(id) ON DELETE CASCADE
);

CREATE TABLE deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    quality_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
