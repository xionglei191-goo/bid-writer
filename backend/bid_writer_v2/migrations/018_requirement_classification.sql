CREATE TABLE requirement_classifications (
    requirement_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    requirement_hash TEXT NOT NULL,
    suggested_category TEXT NOT NULL,
    suggestion_reason TEXT NOT NULL,
    suggestion_excerpt TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    review_category TEXT NOT NULL DEFAULT '',
    review_source_hash TEXT NOT NULL DEFAULT '',
    review_requirement_hash TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    review_reason TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    applicability TEXT NOT NULL DEFAULT 'applicable',
    response_text TEXT NOT NULL DEFAULT '',
    basis_text TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(requirement_id) REFERENCES project_requirements(id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX idx_requirement_classifications_project ON requirement_classifications(project_id, requirement_id);

CREATE TABLE requirement_workflow_events (
    requirement_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(requirement_id, revision),
    FOREIGN KEY(requirement_id) REFERENCES project_requirements(id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX idx_requirement_workflow_events_project ON requirement_workflow_events(project_id, requirement_id, revision);
