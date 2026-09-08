ALTER TABLE ai_runs ADD COLUMN effective_model TEXT;
ALTER TABLE ai_runs ADD COLUMN effective_base_url TEXT;
ALTER TABLE ai_runs ADD COLUMN effective_wire_api TEXT;
ALTER TABLE ai_runs ADD COLUMN fallback_used INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_runs ADD COLUMN primary_error TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_ai_runs_effective_model ON ai_runs(effective_model, fallback_used, id DESC);
