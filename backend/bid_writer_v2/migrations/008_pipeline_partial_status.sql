UPDATE knowledge_ai_pipeline_runs
SET status='completed_with_exceptions'
WHERE status='completed' AND error_message<>'';
