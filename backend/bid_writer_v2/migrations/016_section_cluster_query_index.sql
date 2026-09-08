-- Accelerate corpus near-duplicate candidate lookup for long documents.
-- The query filters document_sections by LENGTH(content) before joining the
-- per-run representative set. Without this expression index PostgreSQL scans
-- every representative and performs a primary-key lookup for each row.
CREATE INDEX IF NOT EXISTS idx_document_sections_content_length
ON document_sections(LENGTH(content));
