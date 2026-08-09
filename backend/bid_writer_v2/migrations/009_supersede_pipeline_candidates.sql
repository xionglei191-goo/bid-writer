UPDATE knowledge_exception_tasks
SET status='resolved',resolved_by='system',resolution='同一文档的新成功运行已替代该候选',resolved_at=CURRENT_TIMESTAMP
WHERE status='open' AND candidate_id IN (
    SELECT c.id FROM knowledge_ai_candidates c
    JOIN knowledge_ai_pipeline_runs r ON r.id=c.pipeline_run_id
    WHERE c.status IN ('ready','needs_review')
      AND EXISTS (
          SELECT 1 FROM knowledge_ai_pipeline_runs newer
          WHERE newer.document_id=r.document_id AND newer.id>r.id
            AND newer.status='completed' AND newer.error_message=''
      )
);

UPDATE knowledge_ai_candidates
SET status='superseded'
WHERE status IN ('ready','needs_review') AND pipeline_run_id IN (
    SELECT r.id FROM knowledge_ai_pipeline_runs r
    WHERE EXISTS (
        SELECT 1 FROM knowledge_ai_pipeline_runs newer
        WHERE newer.document_id=r.document_id AND newer.id>r.id
          AND newer.status='completed' AND newer.error_message=''
    )
);

UPDATE knowledge_ai_pipeline_runs
SET status='superseded'
WHERE status IN ('completed','completed_with_exceptions')
  AND EXISTS (
      SELECT 1 FROM knowledge_ai_pipeline_runs newer
      WHERE newer.document_id=knowledge_ai_pipeline_runs.document_id
        AND newer.id>knowledge_ai_pipeline_runs.id
        AND newer.status='completed' AND newer.error_message=''
  );
