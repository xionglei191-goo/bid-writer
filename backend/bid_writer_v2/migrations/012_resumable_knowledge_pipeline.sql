ALTER TABLE document_chunks ADD COLUMN extraction_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE document_chunks ADD COLUMN review_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE knowledge_ai_pipeline_runs ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE knowledge_ai_pipeline_runs ADD COLUMN completed_chunks INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_ai_pipeline_runs ADD COLUMN failed_chunks INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_ai_pipeline_runs ADD COLUMN coverage_rate REAL NOT NULL DEFAULT 0;
ALTER TABLE knowledge_ai_pipeline_runs ADD COLUMN adjudication_ai_run_id INTEGER REFERENCES ai_runs(id) ON DELETE SET NULL;
