CREATE TABLE source_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    related_source_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, related_source_id, relation_type),
    FOREIGN KEY(source_id) REFERENCES source_files(id) ON DELETE CASCADE,
    FOREIGN KEY(related_source_id) REFERENCES source_files(id) ON DELETE CASCADE
);
CREATE INDEX idx_source_relations_source ON source_relations(source_id, relation_type);
