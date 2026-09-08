ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_decision TEXT NOT NULL DEFAULT '';
ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_confidence REAL NOT NULL DEFAULT 0;
ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_issues_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE retrieval_eval_cases ADD COLUMN ai_review_run_id INTEGER REFERENCES ai_runs(id) ON DELETE SET NULL;
CREATE INDEX idx_retrieval_eval_cases_ai_review ON retrieval_eval_cases(dataset_name, ai_review_status, status);
