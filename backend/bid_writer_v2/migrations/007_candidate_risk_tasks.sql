INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source)
SELECT c.id,'candidate_risk',c.risk_level,
    CASE c.risk_level WHEN 'high' THEN '模型将候选标记为高风险，需要人工复核适用性'
         ELSE '模型将候选标记为中风险，需要人工抽检适用性' END,
    'risk_router'
FROM knowledge_ai_candidates c
WHERE c.risk_level IN ('medium','high')
  AND c.status='needs_review'
  AND NOT EXISTS (
      SELECT 1 FROM knowledge_exception_tasks t
      WHERE t.candidate_id=c.id AND t.issue_code='candidate_risk' AND t.status='open'
  );

UPDATE knowledge_ai_pipeline_runs
SET exception_count=(
    SELECT COUNT(*) FROM knowledge_exception_tasks t
    JOIN knowledge_ai_candidates c ON c.id=t.candidate_id
    WHERE c.pipeline_run_id=knowledge_ai_pipeline_runs.id
);
