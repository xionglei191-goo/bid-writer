from __future__ import annotations

import json
import math
import re
from typing import Any

from ..ai_runtime import (
    AiRuntime,
    KNOWLEDGE_ADJUDICATION_PROMPT,
    KNOWLEDGE_BATCH_EXTRACTION_PROMPT,
    KNOWLEDGE_BATCH_REVIEW_PROMPT,
    KNOWLEDGE_EXTRACTION_PROMPT,
    KNOWLEDGE_REVIEW_PROMPT,
)
from ..database import Database
from ..utils import content_hash, normalize_text, parse_json
from .service import KnowledgeService


PIPELINE_RULE_VERSION = "2.3.0"
CHUNK_MAX_CHARS = 90000
CHUNK_OVERLAP_CHARS = 1200


class RetryableAiAdjudicationError(RuntimeError):
    pass


class KnowledgePipelineService:
    def __init__(self, db: Database, knowledge: KnowledgeService, ai_runtime: AiRuntime) -> None:
        self.db = db
        self.knowledge = knowledge
        self.ai_runtime = ai_runtime

    def process_document(
        self,
        document_id: int,
        max_candidates: int = 12,
        progress=None,
        cancelled=None,
        auto_publish: bool | None = None,
        section_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        progress = progress or (lambda *_args, **_kwargs: None)
        cancelled = cancelled or (lambda: False)
        max_candidates = max(1, min(int(max_candidates), 20))
        should_auto_publish = self.knowledge.settings.auto_publish_low_risk if auto_publish is None else auto_publish
        document, sections = self._document_context(document_id)
        if section_ids is not None:
            selected = {int(value) for value in section_ids}
            sections = [section for section in sections if int(section["id"]) in selected]
            if not sections:
                raise ValueError("所选章节均已由重复章节代表覆盖")
        chunks = self.prepare_chunks(document_id, sections)
        progress("chunking", 5, "文档切片完成", {"chunks": len(chunks), "coverage_rate": 1.0})
        if len(chunks) > 1:
            return self._process_chunked(
                document,
                sections,
                chunks,
                max_candidates,
                progress,
                cancelled,
                should_auto_publish,
            )
        section_text = self._section_text(sections, max_chars=CHUNK_MAX_CHARS)
        model_settings = self.ai_runtime.llm.settings()
        pipeline_key = content_hash(
            "|".join(
                [
                    str(document_id),
                    str(document["text_fingerprint"]),
                    KNOWLEDGE_BATCH_EXTRACTION_PROMPT.prompt_hash,
                    KNOWLEDGE_BATCH_REVIEW_PROMPT.prompt_hash,
                    PIPELINE_RULE_VERSION,
                    str(max_candidates),
                    ",".join(str(section["id"]) for section in sections),
                    json.dumps(
                        {
                            "model": model_settings.get("model", ""),
                            "base_url": model_settings.get("base_url", ""),
                            "wire_api": model_settings.get("wire_api", ""),
                        },
                        sort_keys=True,
                    ),
                ]
            )
        )
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id,status FROM knowledge_ai_pipeline_runs WHERE pipeline_key=?",
                (pipeline_key,),
            ).fetchone()
            if existing and existing["status"] == "completed":
                if should_auto_publish:
                    self.auto_publish_low_risk(int(existing["id"]))
                return {**self.get_run(int(existing["id"])), "reused": True}
            if existing:
                run_id = int(existing["id"])
                conn.execute(
                    "UPDATE knowledge_ai_pipeline_runs SET status='running',error_message='' WHERE id=?",
                    (run_id,),
                )
                conn.execute("DELETE FROM knowledge_ai_candidates WHERE pipeline_run_id=?", (run_id,))
            else:
                cursor = conn.execute(
                    "INSERT INTO knowledge_ai_pipeline_runs(document_id,pipeline_key,input_hash,rule_version) VALUES (?,?,?,?)",
                    (document_id, pipeline_key, document["text_fingerprint"], PIPELINE_RULE_VERSION),
                )
                run_id = int(cursor.lastrowid)

        extraction_prompt = KNOWLEDGE_EXTRACTION_PROMPT.render(
            max_candidates=str(max_candidates),
            document_title=str(document["title"]),
            industry=str(document["industry"] or "通用"),
            section_text=section_text,
        )
        extraction = self.ai_runtime.execute(
            KNOWLEDGE_EXTRACTION_PROMPT,
            extraction_prompt,
            {
                "document_id": document_id,
                "text_fingerprint": document["text_fingerprint"],
                "max_candidates": max_candidates,
                "section_ids": [int(item["id"]) for item in sections],
                "section_text": section_text,
            },
            task_type="knowledge_candidate_extraction",
            target_type="standard_document",
            target_id=document_id,
            max_output_tokens=10000,
        )
        candidates = (extraction.get("payload") or {}).get("candidates") or []
        if not candidates:
            return self._fail_run(run_id, extraction.get("run_id"), extraction.get("error") or "AI未生成候选知识")

        candidate_json = json.dumps(candidates, ensure_ascii=False, indent=2)
        review_prompt = KNOWLEDGE_REVIEW_PROMPT.render(
            section_text=section_text,
            candidate_json=candidate_json,
        )
        review = self.ai_runtime.execute(
            KNOWLEDGE_REVIEW_PROMPT,
            review_prompt,
            {
                "document_id": document_id,
                "section_text": section_text,
                "candidates": candidates,
            },
            task_type="knowledge_candidate_review",
            target_type="standard_document",
            target_id=document_id,
            max_output_tokens=8000,
        )
        reviews = {
            int(item["candidate_index"]): item
            for item in ((review.get("payload") or {}).get("reviews") or [])
            if int(item["candidate_index"]) < len(candidates)
        }
        section_map = {int(item["id"]): item for item in sections}
        ready_count = 0
        exception_count = 0
        with self.db.connect() as conn:
            for index, candidate in enumerate(candidates):
                try:
                    requested_section_id = int(candidate.get("source_section_id") or 0)
                except (TypeError, ValueError):
                    requested_section_id = 0
                section = section_map.get(requested_section_id) or sections[0]
                model_review = reviews.get(index)
                model_issues = list((model_review or {}).get("issues") or [])
                if not model_review:
                    model_issues.append(
                        {"code": "review_missing", "severity": "high", "message": "独立复核未返回该候选的结论"}
                    )
                rule_findings = self._rule_findings(candidate, section, requested_section_id in section_map)
                if candidate["risk_level"] == "high":
                    rule_findings.append(
                        {
                            "code": "candidate_risk",
                            "severity": "high",
                            "message": "模型将候选标记为高风险，需要人工复核适用性",
                            "source": "risk_router",
                        }
                    )
                decision = str((model_review or {}).get("decision") or "missing")
                confidence = float((model_review or {}).get("confidence") or 0)
                corrected = normalize_text(str((model_review or {}).get("corrected_content") or ""))
                content = corrected if decision == "revise" and corrected else normalize_text(candidate["content"])
                blocking = [
                    item for item in [*model_issues, *rule_findings]
                    if item.get("severity") in {"medium", "high"}
                ]
                ready = (
                    decision == "pass"
                    and confidence >= (0.92 if candidate["risk_level"] == "medium" else 0.85)
                    and candidate["risk_level"] in {"low", "medium"}
                    and not blocking
                )
                status = "ready" if ready else "needs_review"
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_ai_candidates(
                        pipeline_run_id,document_id,source_id,source_section_id,candidate_index,title,unit_type,
                        content,summary,tags_json,applicability,risk_level,source_quote,review_decision,
                        review_confidence,review_issues_json,rule_findings_json,status
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        document_id,
                        document["source_id"],
                        section["id"],
                        index,
                        candidate["title"],
                        candidate["unit_type"],
                        content,
                        candidate["summary"],
                        json.dumps(candidate.get("tags") or [], ensure_ascii=False),
                        candidate["applicability"],
                        candidate["risk_level"],
                        candidate["source_quote"],
                        decision,
                        confidence,
                        json.dumps(model_issues, ensure_ascii=False),
                        json.dumps(rule_findings, ensure_ascii=False),
                        status,
                    ),
                )
                candidate_id = int(cursor.lastrowid)
                findings = [*model_issues, *rule_findings]
                if decision != "pass" and not findings:
                    findings.append(
                        {"code": f"review_{decision}", "severity": "medium", "message": "独立复核未判定直接通过"}
                    )
                for finding in findings:
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,?,?,?,?)",
                        (
                            candidate_id,
                            str(finding.get("code") or "unspecified"),
                            str(finding.get("severity") or "medium"),
                            str(finding.get("message") or "需要人工复核"),
                            str(finding.get("source") or ("rule" if finding in rule_findings else "model_review")),
                        ),
                    )
                ready_count += int(ready)
                exception_count += len(findings)
            conn.execute(
                """
                UPDATE knowledge_ai_pipeline_runs SET status=?,extraction_ai_run_id=?,review_ai_run_id=?,
                    candidate_count=?,ready_count=?,exception_count=?,error_message=?,completed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    "completed" if not review.get("error") else "completed_with_exceptions",
                    extraction["run_id"],
                    review.get("run_id"),
                    len(candidates),
                    ready_count,
                    exception_count,
                    review.get("error") or "",
                    run_id,
                ),
            )
            if not review.get("error"):
                prior_run_ids = [
                    int(row[0])
                    for row in conn.execute(
                        """
                        SELECT id FROM knowledge_ai_pipeline_runs
                        WHERE document_id=? AND id<>? AND status IN ('completed','completed_with_exceptions')
                        """,
                        (document_id, run_id),
                    ).fetchall()
                ]
                if prior_run_ids:
                    placeholders = ",".join("?" for _ in prior_run_ids)
                    conn.execute(
                        f"""
                        UPDATE knowledge_exception_tasks SET status='resolved',resolved_by='system',
                            resolution='同一文档的新成功运行已替代该候选',resolved_at=CURRENT_TIMESTAMP
                        WHERE status='open' AND candidate_id IN (
                            SELECT id FROM knowledge_ai_candidates WHERE pipeline_run_id IN ({placeholders})
                        )
                        """,
                        prior_run_ids,
                    )
                    conn.execute(
                        f"UPDATE knowledge_ai_candidates SET status='superseded' WHERE status IN ('ready','needs_review') AND pipeline_run_id IN ({placeholders})",
                        prior_run_ids,
                    )
                    conn.execute(
                        f"UPDATE knowledge_ai_pipeline_runs SET status='superseded' WHERE id IN ({placeholders})",
                        prior_run_ids,
                    )
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE document_chunks SET status='completed',attempt_count=attempt_count+1,updated_at=CURRENT_TIMESTAMP WHERE document_id=?",
                (document_id,),
            )
            conn.execute(
                "UPDATE knowledge_ai_pipeline_runs SET completed_chunks=1,coverage_rate=1 WHERE id=?",
                (run_id,),
            )
        if should_auto_publish:
            self.auto_publish_low_risk(run_id)
        progress("completed", 100, "知识加工完成", {"candidates": len(candidates), "ready": ready_count})
        return {**self.get_run(run_id), "reused": False}

    def process_document_batch(
        self,
        document_sections: list[tuple[int, list[int]]],
        max_candidates: int = 20,
        progress=None,
        cancelled=None,
    ) -> dict[str, Any]:
        """Process several short documents with one extraction/review pair.

        The pipeline run is shared only as an execution envelope.  Every
        candidate keeps the real document, source and section foreign keys, so
        batching does not weaken provenance or source-level disposition.
        """
        progress = progress or (lambda *_args, **_kwargs: None)
        cancelled = cancelled or (lambda: False)
        max_candidates = max(1, min(int(max_candidates), 20))
        if len(document_sections) < 2:
            document_id, section_ids = document_sections[0]
            return self.process_document(
                document_id,
                max_candidates=max_candidates,
                progress=progress,
                cancelled=cancelled,
                auto_publish=False,
                section_ids=section_ids,
            )

        documents: list[dict[str, Any]] = []
        sections: list[dict[str, Any]] = []
        for document_id, section_ids in document_sections:
            document, available = self._document_context(int(document_id))
            selected = {int(value) for value in section_ids}
            chosen = [section for section in available if int(section["id"]) in selected]
            if not chosen:
                raise ValueError(f"document {document_id} has no representative sections")
            documents.append(document)
            for section in chosen:
                sections.append(
                    {
                        **section,
                        "document_id": int(document["id"]),
                        "source_id": int(document["source_id"]),
                        "document_title": str(document["title"]),
                    }
                )

        blocks: list[str] = []
        used = 0
        included_section_ids: set[int] = set()
        last_document_id = 0
        for section in sections:
            prefix = ""
            if int(section["document_id"]) != last_document_id:
                prefix = f"[DOCUMENT:{section['document_id']}] {section['document_title']}\n"
                last_document_id = int(section["document_id"])
            block = (
                f"{prefix}[SECTION:{section['id']}] {section['heading']}\n"
                        f"{normalize_text(section['content'])}"
            )
            if used + len(block) > CHUNK_MAX_CHARS:
                remaining = CHUNK_MAX_CHARS - used
                if remaining >= 500:
                    blocks.append(block[:remaining])
                    included_section_ids.add(int(section["id"]))
                break
            blocks.append(block)
            included_section_ids.add(int(section["id"]))
            used += len(block)
        section_text = "\n\n".join(blocks)
        if not section_text:
            raise ValueError("short-document batch has no processable text")
        sections = [section for section in sections if int(section["id"]) in included_section_ids]

        model_settings = self.ai_runtime.llm.settings()
        fingerprint = content_hash(
            "|".join(f"{document['id']}:{document['text_fingerprint']}" for document in documents)
        )
        pipeline_key = content_hash(
            "|".join(
                [
                    "short-document-batch",
                    fingerprint,
                    KNOWLEDGE_BATCH_EXTRACTION_PROMPT.prompt_hash,
                    KNOWLEDGE_BATCH_REVIEW_PROMPT.prompt_hash,
                    PIPELINE_RULE_VERSION,
                    str(max_candidates),
                    ",".join(str(section["id"]) for section in sections),
                    json.dumps(
                        {
                            "model": model_settings.get("model", ""),
                            "base_url": model_settings.get("base_url", ""),
                            "wire_api": model_settings.get("wire_api", ""),
                        },
                        sort_keys=True,
                    ),
                ]
            )
        )
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id,status FROM knowledge_ai_pipeline_runs WHERE pipeline_key=?",
                (pipeline_key,),
            ).fetchone()
            if existing and existing["status"] == "completed":
                return {**self.get_run(int(existing["id"])), "reused": True}
            if existing:
                run_id = int(existing["id"])
                conn.execute(
                    "UPDATE knowledge_ai_pipeline_runs SET status='running',error_message='',completed_at=NULL WHERE id=?",
                    (run_id,),
                )
                conn.execute("DELETE FROM knowledge_ai_candidates WHERE pipeline_run_id=?", (run_id,))
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_ai_pipeline_runs(
                        document_id,pipeline_key,input_hash,rule_version,chunk_count
                    ) VALUES (?,?,?,?,?)
                    """,
                    (int(documents[0]["id"]), pipeline_key, fingerprint, PIPELINE_RULE_VERSION, len(documents)),
                )
                run_id = int(cursor.lastrowid)

        if cancelled():
            return self._fail_run(run_id, None, "batch cancelled before extraction")
        title = "全库短文档批次：" + "；".join(str(document["title"]) for document in documents)
        extraction = self.ai_runtime.execute(
            KNOWLEDGE_BATCH_EXTRACTION_PROMPT,
            KNOWLEDGE_BATCH_EXTRACTION_PROMPT.render(
                max_candidates=str(max_candidates),
                document_title=title,
                industry="多来源；必须按 SECTION 编号逐条回挂",
                section_text=section_text,
            ),
            {
                "document_ids": [int(document["id"]) for document in documents],
                "text_fingerprint": fingerprint,
                "max_candidates": max_candidates,
                "section_ids": [int(section["id"]) for section in sections],
                "section_text": section_text,
            },
            task_type="knowledge_batch_candidate_extraction",
            target_type="standard_document_batch",
            target_id=int(documents[0]["id"]),
            max_output_tokens=12000,
        )
        extraction_payload = extraction.get("payload") or {}
        candidates = extraction_payload.get("candidates") or []
        extraction_dispositions = extraction_payload.get("source_dispositions") or []
        expected_document_ids = {int(document["id"]) for document in documents}
        extraction_document_ids = [int(item["document_id"]) for item in extraction_dispositions]
        if set(extraction_document_ids) != expected_document_ids or len(extraction_document_ids) != len(expected_document_ids):
            return self._fail_run(
                run_id,
                extraction.get("run_id"),
                extraction.get("error") or "AI returned incomplete source dispositions for short-document batch",
            )
        review = self.ai_runtime.execute(
            KNOWLEDGE_BATCH_REVIEW_PROMPT,
            KNOWLEDGE_BATCH_REVIEW_PROMPT.render(
                section_text=section_text,
                candidate_json=json.dumps(extraction_payload, ensure_ascii=False, indent=2),
            ),
            {
                "document_ids": [int(document["id"]) for document in documents],
                "section_text": section_text,
                "candidates": candidates,
                "source_dispositions": extraction_dispositions,
            },
            task_type="knowledge_batch_candidate_review",
            target_type="standard_document_batch",
            target_id=int(documents[0]["id"]),
            max_output_tokens=10000,
        )
        reviews = {
            int(item["candidate_index"]): item
            for item in ((review.get("payload") or {}).get("reviews") or [])
            if int(item["candidate_index"]) < len(candidates)
        }
        review_dispositions = (review.get("payload") or {}).get("source_dispositions") or []
        review_document_ids = [int(item["document_id"]) for item in review_dispositions]
        if set(review_document_ids) != expected_document_ids or len(review_document_ids) != len(expected_document_ids):
            return self._fail_run(
                run_id,
                extraction.get("run_id"),
                review.get("error") or "independent review returned incomplete source dispositions",
            )
        section_map = {int(section["id"]): section for section in sections}
        ready_count = 0
        exception_count = 0
        with self.db.connect() as conn:
            for index, candidate in enumerate(candidates):
                try:
                    requested_section_id = int(candidate.get("source_section_id") or 0)
                except (TypeError, ValueError):
                    requested_section_id = 0
                section = section_map.get(requested_section_id) or sections[0]
                model_review = reviews.get(index)
                model_issues = list((model_review or {}).get("issues") or [])
                if not model_review:
                    model_issues.append(
                        {"code": "review_missing", "severity": "high", "message": "独立复核未返回该候选结论"}
                    )
                rule_findings = self._rule_findings(
                    candidate,
                    section,
                    requested_section_id in section_map,
                )
                if candidate["risk_level"] == "high":
                    rule_findings.append(
                        {
                            "code": "candidate_risk",
                            "severity": "high",
                            "message": "模型将候选标记为高风险，需执行双重复核和最终裁决",
                            "source": "risk_router",
                        }
                    )
                decision = str((model_review or {}).get("decision") or "missing")
                confidence = float((model_review or {}).get("confidence") or 0)
                corrected = normalize_text(str((model_review or {}).get("corrected_content") or ""))
                content = corrected if decision == "revise" and corrected else normalize_text(candidate["content"])
                blocking = [
                    finding
                    for finding in [*model_issues, *rule_findings]
                    if finding.get("severity") in {"medium", "high"}
                ]
                ready = (
                    decision == "pass"
                    and confidence >= (0.92 if candidate["risk_level"] == "medium" else 0.85)
                    and candidate["risk_level"] in {"low", "medium"}
                    and not blocking
                )
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_ai_candidates(
                        pipeline_run_id,document_id,source_id,source_section_id,candidate_index,title,unit_type,
                        content,summary,tags_json,applicability,risk_level,source_quote,review_decision,
                        review_confidence,review_issues_json,rule_findings_json,status
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        int(section["document_id"]),
                        int(section["source_id"]),
                        int(section["id"]),
                        index,
                        candidate["title"],
                        candidate["unit_type"],
                        content,
                        candidate["summary"],
                        json.dumps(candidate.get("tags") or [], ensure_ascii=False),
                        candidate["applicability"],
                        candidate["risk_level"],
                        candidate["source_quote"],
                        decision,
                        confidence,
                        json.dumps(model_issues, ensure_ascii=False),
                        json.dumps(rule_findings, ensure_ascii=False),
                        "ready" if ready else "needs_review",
                    ),
                )
                candidate_id = int(cursor.lastrowid)
                findings = [*model_issues, *rule_findings]
                if decision != "pass" and not findings:
                    findings.append(
                        {"code": f"review_{decision}", "severity": "medium", "message": "独立复核未判定直接通过"}
                    )
                for finding in findings:
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,?,?,?,?)",
                        (
                            candidate_id,
                            str(finding.get("code") or "unspecified"),
                            str(finding.get("severity") or "medium"),
                            str(finding.get("message") or "需要自动复核"),
                            str(finding.get("source") or "model_or_rule"),
                        ),
                    )
                ready_count += int(ready)
                exception_count += len(findings)
            conn.execute(
                """
                UPDATE knowledge_ai_pipeline_runs SET status=?,extraction_ai_run_id=?,review_ai_run_id=?,
                    candidate_count=?,ready_count=?,exception_count=?,completed_chunks=?,failed_chunks=0,
                    coverage_rate=1,error_message=?,completed_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (
                    "completed" if not review.get("error") else "completed_with_exceptions",
                    extraction.get("run_id"),
                    review.get("run_id"),
                    len(candidates),
                    ready_count,
                    exception_count,
                    len(documents),
                    review.get("error") or "",
                    run_id,
                ),
            )
            conn.execute("DELETE FROM knowledge_source_dispositions WHERE pipeline_run_id=?", (run_id,))
            extraction_map = {int(item["document_id"]): item for item in extraction_dispositions}
            review_map = {int(item["document_id"]): item for item in review_dispositions}
            for document in documents:
                document_id = int(document["id"])
                for stage, disposition, ai_run_id, prompt in (
                    ("extraction", extraction_map.get(document_id), extraction.get("run_id"), KNOWLEDGE_BATCH_EXTRACTION_PROMPT),
                    ("independent_review", review_map.get(document_id), review.get("run_id"), KNOWLEDGE_BATCH_REVIEW_PROMPT),
                ):
                    if not disposition:
                        continue
                    conn.execute(
                        """
                        INSERT INTO knowledge_source_dispositions(
                            pipeline_run_id,document_id,source_id,decision_stage,decision,confidence,reason,
                            evidence_quote,actor_type,ai_run_id,prompt_key,prompt_version
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id,
                            document_id,
                            int(document["source_id"]),
                            stage,
                            disposition["decision"],
                            float(disposition["confidence"]),
                            disposition["reason"],
                            disposition.get("evidence_quote") or "",
                            "ai",
                            ai_run_id,
                            prompt.key,
                            prompt.version,
                        ),
                    )
            document_ids = [int(document["id"]) for document in documents]
            placeholders = ",".join("?" for _ in document_ids)
            prior_candidates = [
                int(row[0])
                for row in conn.execute(
                    f"""
                    SELECT c.id FROM knowledge_ai_candidates c
                    WHERE c.document_id IN ({placeholders}) AND c.pipeline_run_id<>?
                      AND c.status IN ('ready','needs_review')
                    """,
                    (*document_ids, run_id),
                ).fetchall()
            ]
            if prior_candidates:
                candidate_placeholders = ",".join("?" for _ in prior_candidates)
                conn.execute(
                    f"""
                    UPDATE knowledge_exception_tasks SET status='resolved',resolved_by='system',
                        resolution='新成功批次已替代旧候选',resolved_at=CURRENT_TIMESTAMP
                    WHERE status='open' AND candidate_id IN ({candidate_placeholders})
                    """,
                    prior_candidates,
                )
                conn.execute(
                    f"UPDATE knowledge_ai_candidates SET status='superseded' WHERE id IN ({candidate_placeholders})",
                    prior_candidates,
                )
            conn.execute(
                f"UPDATE document_chunks SET status='completed',attempt_count=attempt_count+1,updated_at=CURRENT_TIMESTAMP WHERE document_id IN ({placeholders})",
                document_ids,
            )
        self._deduplicate_candidates(run_id)
        progress(
            "completed",
            100,
            "短文档合批知识加工完成",
            {"documents": len(documents), "candidates": len(candidates), "ready": ready_count},
        )
        return {**self.get_run(run_id), "reused": False, "batched_documents": len(documents)}

    def prepare_chunks(self, document_id: int, sections: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if sections is None:
            _document, sections = self._document_context(document_id)
        blocks: list[dict[str, Any]] = []
        absolute_offset = 0
        for section in sections:
            body = normalize_text(str(section["content"]))
            marker = f"[SECTION:{section['id']}] {section['heading']}\n"
            if len(marker) + len(body) <= CHUNK_MAX_CHARS:
                blocks.append(
                    {
                        "section_id": int(section["id"]),
                        "heading": str(section["heading"]),
                        "content": marker + body,
                        "char_start": absolute_offset,
                        "char_end": absolute_offset + len(body),
                        "page_start": section.get("page_start"),
                        "page_end": section.get("page_end"),
                    }
                )
            else:
                cursor = 0
                while cursor < len(body):
                    end = min(len(body), cursor + CHUNK_MAX_CHARS - len(marker))
                    if end < len(body):
                        paragraph_break = body.rfind("\n", cursor + CHUNK_MAX_CHARS // 2, end)
                        sentence_break = max(body.rfind("。", cursor + CHUNK_MAX_CHARS // 2, end), body.rfind("；", cursor + CHUNK_MAX_CHARS // 2, end))
                        end = max(paragraph_break + 1, sentence_break + 1, end)
                    part = body[cursor:end]
                    blocks.append(
                        {
                            "section_id": int(section["id"]),
                            "heading": str(section["heading"]),
                            "content": marker + part,
                            "char_start": absolute_offset + cursor,
                            "char_end": absolute_offset + end,
                            "page_start": section.get("page_start"),
                            "page_end": section.get("page_end"),
                        }
                    )
                    if end >= len(body):
                        break
                    cursor = max(cursor + 1, end - CHUNK_OVERLAP_CHARS)
            absolute_offset += len(body)

        grouped: list[dict[str, Any]] = []
        for block in blocks:
            if grouped and len(grouped[-1]["content"]) + len(block["content"]) + 2 <= CHUNK_MAX_CHARS:
                current = grouped[-1]
                current["content"] += "\n\n" + block["content"]
                current["heading"] = f"{current['heading']} / {block['heading']}"
                current["section_id"] = None
                current["char_end"] = block["char_end"]
                current["page_end"] = block["page_end"]
            else:
                grouped.append(dict(block))
        desired = [(index, content_hash(item["content"])) for index, item in enumerate(grouped, 1)]
        existing = self.db.rows(
            "SELECT order_no,content_hash FROM document_chunks WHERE document_id=? ORDER BY order_no",
            (document_id,),
        )
        if [(int(item["order_no"]), item["content_hash"]) for item in existing] != desired:
            with self.db.connect() as conn:
                conn.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
                for index, item in enumerate(grouped, 1):
                    conn.execute(
                        """
                        INSERT INTO document_chunks(
                            document_id,section_id,order_no,heading,content,char_start,char_end,page_start,page_end,content_hash
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            document_id,
                            item["section_id"],
                            index,
                            item["heading"],
                            item["content"],
                            item["char_start"],
                            item["char_end"],
                            item["page_start"],
                            item["page_end"],
                            content_hash(item["content"]),
                        ),
                    )
        return self.db.rows("SELECT * FROM document_chunks WHERE document_id=? ORDER BY order_no", (document_id,))

    def _process_chunked(
        self,
        document: dict[str, Any],
        sections: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        max_candidates: int,
        progress,
        cancelled,
        should_auto_publish: bool,
    ) -> dict[str, Any]:
        model_settings = self.ai_runtime.llm.settings()
        document_id = int(document["id"])
        pipeline_key = content_hash(
            "|".join(
                [
                    str(document_id),
                    str(document["text_fingerprint"]),
                    KNOWLEDGE_EXTRACTION_PROMPT.prompt_hash,
                    KNOWLEDGE_REVIEW_PROMPT.prompt_hash,
                    PIPELINE_RULE_VERSION,
                    str(max_candidates),
                    "chunked",
                    ",".join(str(section["id"]) for section in sections),
                    str(model_settings.get("model", "")),
                ]
            )
        )
        with self.db.connect() as conn:
            existing = conn.execute("SELECT id,status FROM knowledge_ai_pipeline_runs WHERE pipeline_key=?", (pipeline_key,)).fetchone()
            if existing and existing["status"] == "completed":
                return {**self.get_run(int(existing["id"])), "reused": True}
            if existing:
                run_id = int(existing["id"])
                conn.execute(
                    "UPDATE knowledge_ai_pipeline_runs SET status='running',error_message='',completed_at=NULL WHERE id=?",
                    (run_id,),
                )
                conn.execute("DELETE FROM knowledge_ai_candidates WHERE pipeline_run_id=?", (run_id,))
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_ai_pipeline_runs(
                        document_id,pipeline_key,input_hash,rule_version,chunk_count
                    ) VALUES (?,?,?,?,?)
                    """,
                    (document_id, pipeline_key, document["text_fingerprint"], PIPELINE_RULE_VERSION, len(chunks)),
                )
                run_id = int(cursor.lastrowid)
        section_map = {int(item["id"]): item for item in sections}
        global_candidates: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any], int]] = []
        failed_chunks = 0
        extraction_run_id = None
        review_run_id = None
        for chunk_index, chunk in enumerate(chunks):
            if cancelled():
                break
            percentage = 10 + int(70 * chunk_index / max(1, len(chunks)))
            progress("extracting", percentage, f"处理切片 {chunk_index + 1}/{len(chunks)}", {"chunk_id": chunk["id"]})
            cached_extraction = parse_json(chunk.get("extraction_json"), {}) if chunk.get("status") == "completed" else {}
            cached_review = parse_json(chunk.get("review_json"), {}) if chunk.get("status") == "completed" else {}
            if cached_extraction and cached_review:
                candidates = cached_extraction.get("candidates") or []
                reviews_list = cached_review.get("reviews") or []
            else:
                extraction = self.ai_runtime.execute(
                    KNOWLEDGE_EXTRACTION_PROMPT,
                    KNOWLEDGE_EXTRACTION_PROMPT.render(
                        max_candidates=str(max_candidates),
                        document_title=f"{document['title']} - 切片{chunk_index + 1}",
                        industry=str(document["industry"] or "通用"),
                        section_text=chunk["content"],
                    ),
                    {
                        "document_id": document_id,
                        "chunk_id": chunk["id"],
                        "content_hash": chunk["content_hash"],
                        "max_candidates": max_candidates,
                        "section_text": chunk["content"],
                    },
                    task_type="knowledge_chunk_extraction",
                    target_type="document_chunk",
                    target_id=int(chunk["id"]),
                    max_output_tokens=10000,
                )
                extraction_run_id = extraction.get("run_id") or extraction_run_id
                candidates = (extraction.get("payload") or {}).get("candidates") or []
                if not candidates:
                    failed_chunks += 1
                    with self.db.connect() as conn:
                        conn.execute(
                            "UPDATE document_chunks SET status='failed',attempt_count=attempt_count+1,error_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            ((extraction.get("error") or "AI未生成候选")[:1000], chunk["id"]),
                        )
                    continue
                review = self.ai_runtime.execute(
                    KNOWLEDGE_REVIEW_PROMPT,
                    KNOWLEDGE_REVIEW_PROMPT.render(
                        section_text=chunk["content"],
                        candidate_json=json.dumps(candidates, ensure_ascii=False, indent=2),
                    ),
                    {"document_id": document_id, "chunk_id": chunk["id"], "section_text": chunk["content"], "candidates": candidates},
                    task_type="knowledge_chunk_review",
                    target_type="document_chunk",
                    target_id=int(chunk["id"]),
                    max_output_tokens=8000,
                )
                review_run_id = review.get("run_id") or review_run_id
                reviews_list = (review.get("payload") or {}).get("reviews") or []
                with self.db.connect() as conn:
                    conn.execute(
                        """
                        UPDATE document_chunks SET status='completed',attempt_count=attempt_count+1,error_message='',
                            extraction_json=?,review_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (
                            json.dumps({"candidates": candidates}, ensure_ascii=False),
                            json.dumps({"reviews": reviews_list}, ensure_ascii=False),
                            chunk["id"],
                        ),
                    )
            reviews = {int(item["candidate_index"]): item for item in reviews_list if int(item["candidate_index"]) < len(candidates)}
            for local_index, candidate in enumerate(candidates):
                requested = int(candidate["source_section_id"])
                section = section_map.get(requested) or sections[0]
                global_candidates.append((candidate, reviews.get(local_index), section, int(chunk["id"])))

        ready_count = 0
        exception_count = 0
        with self.db.connect() as conn:
            for candidate_index, (candidate, model_review, section, chunk_id) in enumerate(global_candidates):
                model_issues = list((model_review or {}).get("issues") or [])
                if not model_review:
                    model_issues.append({"code": "review_missing", "severity": "high", "message": "独立复核未返回该候选的结论"})
                try:
                    requested_section_id = int(candidate.get("source_section_id") or 0)
                except (TypeError, ValueError):
                    requested_section_id = 0
                rule_findings = self._rule_findings(candidate, section, requested_section_id in section_map)
                if candidate["risk_level"] == "high":
                    rule_findings.append({"code": "candidate_risk", "severity": "high", "message": "高风险候选必须人工复核", "source": "risk_router"})
                decision = str((model_review or {}).get("decision") or "missing")
                confidence = float((model_review or {}).get("confidence") or 0)
                corrected = normalize_text(str((model_review or {}).get("corrected_content") or ""))
                candidate_content = corrected if decision == "revise" and corrected else normalize_text(candidate["content"])
                blocking = [item for item in [*model_issues, *rule_findings] if item.get("severity") in {"medium", "high"}]
                ready = decision == "pass" and confidence >= (0.92 if candidate["risk_level"] == "medium" else 0.85) and candidate["risk_level"] in {"low", "medium"} and not blocking
                cursor = conn.execute(
                    """
                    INSERT INTO knowledge_ai_candidates(
                        pipeline_run_id,document_id,source_id,source_section_id,candidate_index,title,unit_type,
                        content,summary,tags_json,applicability,risk_level,source_quote,review_decision,
                        review_confidence,review_issues_json,rule_findings_json,status,chunk_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id, document_id, document["source_id"], section["id"], candidate_index,
                        candidate["title"], candidate["unit_type"], candidate_content, candidate["summary"],
                        json.dumps(candidate.get("tags") or [], ensure_ascii=False), candidate["applicability"],
                        candidate["risk_level"], candidate["source_quote"], decision, confidence,
                        json.dumps(model_issues, ensure_ascii=False), json.dumps(rule_findings, ensure_ascii=False),
                        "ready" if ready else "needs_review", chunk_id,
                    ),
                )
                candidate_id = int(cursor.lastrowid)
                findings = [*model_issues, *rule_findings]
                if decision != "pass" and not findings:
                    findings.append({"code": f"review_{decision}", "severity": "medium", "message": "独立复核未判定直接通过"})
                for finding in findings:
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,?,?,?,?)",
                        (candidate_id, str(finding.get("code") or "unspecified"), str(finding.get("severity") or "medium"), str(finding.get("message") or "需要人工复核"), str(finding.get("source") or "model_or_rule")),
                    )
                ready_count += int(ready)
                exception_count += len(findings)
        self._deduplicate_candidates(run_id)
        completed_chunks = len(chunks) - failed_chunks
        coverage_rate = round(completed_chunks / len(chunks), 4) if chunks else 0
        final_status = "completed" if not failed_chunks and not cancelled() else "completed_with_exceptions"
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_ai_pipeline_runs SET status=?,extraction_ai_run_id=?,review_ai_run_id=?,
                    candidate_count=?,ready_count=?,exception_count=?,completed_chunks=?,failed_chunks=?,
                    coverage_rate=?,error_message=?,completed_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (
                    final_status, extraction_run_id, review_run_id, len(global_candidates), ready_count,
                    exception_count, completed_chunks, failed_chunks, coverage_rate,
                    "任务被取消" if cancelled() else (f"{failed_chunks}个切片失败" if failed_chunks else ""), run_id,
                ),
            )
        if should_auto_publish and not cancelled():
            self.auto_publish_low_risk(run_id)
        progress("completed", 100, "分批知识加工完成", {"chunks": len(chunks), "failed_chunks": failed_chunks, "coverage_rate": coverage_rate})
        return {**self.get_run(run_id), "reused": False}

    def _deduplicate_candidates(self, run_id: int) -> None:
        candidates = self.db.rows(
            "SELECT id,document_id,title,content,status FROM knowledge_ai_candidates WHERE pipeline_run_id=? ORDER BY id",
            (run_id,),
        )
        seen: dict[str, int] = {}
        with self.db.connect() as conn:
            for candidate in candidates:
                normalized_title = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", candidate["title"]).lower()
                # Cross-document similarities are handled by corpus clusters,
                # which preserve every source attachment.  This local pass
                # removes only duplicate candidates emitted for one document.
                key = content_hash(
                    f"{candidate['document_id']}|{normalized_title}|{normalize_text(candidate['content'])}"
                )
                if key in seen:
                    conn.execute(
                        "INSERT INTO candidate_relations(candidate_id,related_candidate_id,relation_type,lexical_score,explanation) VALUES (?,?, 'duplicate',1,'标题和正文完全重复')",
                        (candidate["id"], seen[key]),
                    )
                    conn.execute("UPDATE knowledge_ai_candidates SET status='superseded' WHERE id=?", (candidate["id"],))
                else:
                    seen[key] = int(candidate["id"])

    def auto_publish_low_risk(self, run_id: int) -> dict[str, Any]:
        resumable = self._candidate_rows(
            """
            WHERE c.pipeline_run_id=? AND c.auto_publish_batch_id IS NOT NULL
              AND c.status IN ('ready','accepted') AND c.adjudication_decision='pass'
              AND c.adjudication_confidence>=0.92
            """,
            (run_id,),
            500,
        )
        if resumable:
            batch_ids = {int(item["auto_publish_batch_id"]) for item in resumable}
            if len(batch_ids) != 1:
                raise RuntimeError("自动发布恢复数据包含多个批次")
            return self._publish_adjudicated_candidates(
                resumable,
                batch_ids.pop(),
                (self.db.row("SELECT adjudication_ai_run_id FROM knowledge_ai_pipeline_runs WHERE id=?", (run_id,)) or {}).get("adjudication_ai_run_id"),
            )
        candidates = self._candidate_rows(
            "WHERE c.pipeline_run_id=? AND c.status='ready' AND c.risk_level='low' AND c.review_confidence>=0.92",
            (run_id,),
            500,
        )
        if not candidates:
            return {"published": 0, "batch_id": None}
        section_ids = sorted({int(item["source_section_id"]) for item in candidates})
        placeholders = ",".join("?" for _ in section_ids)
        sections = self.db.rows(
            f"SELECT id,heading,content FROM document_sections WHERE id IN ({placeholders}) ORDER BY id",
            section_ids,
        )
        adjudication_input = [
            {
                "candidate_index": index,
                "title": item["title"],
                "content": item["content"],
                "applicability": item["applicability"],
                "risk_level": item["risk_level"],
                "source_quote": item["source_quote"],
                "source_section_id": item["source_section_id"],
            }
            for index, item in enumerate(candidates)
        ]
        adjudication = self.ai_runtime.execute(
            KNOWLEDGE_ADJUDICATION_PROMPT,
            KNOWLEDGE_ADJUDICATION_PROMPT.render(
                section_text=self._section_text(sections, max_chars=50000),
                candidate_json=json.dumps(adjudication_input, ensure_ascii=False, indent=2),
            ),
            {"pipeline_run_id": run_id, "candidates": adjudication_input, "section_text": self._section_text(sections, max_chars=50000)},
            task_type="knowledge_low_risk_adjudication",
            target_type="knowledge_pipeline_run",
            target_id=run_id,
            max_output_tokens=6000,
            use_cache=False,
        )
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE knowledge_ai_pipeline_runs SET adjudication_ai_run_id=? WHERE id=?",
                (adjudication.get("run_id"), run_id),
            )
        if adjudication.get("payload") is None:
            raise RetryableAiAdjudicationError(
                f"Low-risk AI adjudication is unavailable; ai_run_id={adjudication.get('run_id') or 'none'}"
            )
        decisions = {
            int(item["candidate_index"]): item
            for item in ((adjudication.get("payload") or {}).get("reviews") or [])
            if int(item["candidate_index"]) < len(candidates)
        }
        approved_candidates: list[dict[str, Any]] = []
        with self.db.connect() as conn:
            for index, candidate in enumerate(candidates):
                decision = decisions.get(index) or {}
                passed = decision.get("decision") == "pass" and float(decision.get("confidence") or 0) >= 0.92 and not [
                    issue for issue in (decision.get("issues") or []) if issue.get("severity") in {"medium", "high"}
                ]
                conn.execute(
                    "UPDATE knowledge_ai_candidates SET adjudication_decision=?,adjudication_confidence=? WHERE id=?",
                    (str(decision.get("decision") or "missing"), float(decision.get("confidence") or 0), candidate["id"]),
                )
                if passed:
                    approved_candidates.append(candidate)
                else:
                    conn.execute("UPDATE knowledge_ai_candidates SET status='needs_review' WHERE id=?", (candidate["id"],))
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,'adjudication_failed','medium','最终独立裁决未达到自动发布门槛','ai_adjudication')",
                        (candidate["id"],),
                    )
        candidates = approved_candidates
        if not candidates:
            return {"published": 0, "batch_id": None, "adjudication_ai_run_id": adjudication.get("run_id")}
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO knowledge_auto_publish_batches(rule_version,candidate_count,sample_count) VALUES (?,?,?)",
                (PIPELINE_RULE_VERSION, len(candidates), max(1, math.ceil(len(candidates) * 0.1))),
            )
            batch_id = int(cursor.lastrowid)
            candidate_ids = [int(candidate["id"]) for candidate in candidates]
            placeholders = ",".join("?" for _ in candidate_ids)
            conn.execute(
                f"UPDATE knowledge_ai_candidates SET auto_publish_batch_id=? WHERE id IN ({placeholders})",
                (batch_id, *candidate_ids),
            )
        published = 0
        for index, candidate in enumerate(candidates):
            accepted = self.review_candidate(int(candidate["id"]), "accept", "AI双检自动接收", "低风险候选通过来源和独立复核门禁")
            unit = self.knowledge.get_unit(int(accepted["unit_id"]))
            version_id = int(unit["versions"][0]["id"])
            self.knowledge.review_unit(int(accepted["unit_id"]), version_id, "approve", "AI双检自动审核", "按低风险自动发布策略批准")
            self.knowledge.publish_unit(int(accepted["unit_id"]), version_id, "AI低风险自动发布")
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE knowledge_ai_candidates SET auto_publish_batch_id=?,adjudication_decision='pass' WHERE id=?",
                    (batch_id, candidate["id"]),
                )
                if index < max(1, math.ceil(len(candidates) * 0.1)):
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,'auto_publish_sample','low','自动发布抽检：核对原文忠实性和跨项目适用性','sampling')",
                        (candidate["id"],),
                    )
            published += 1
        return {"published": published, "batch_id": batch_id, "adjudication_ai_run_id": adjudication.get("run_id")}

    def _publish_adjudicated_candidates(
        self,
        candidates: list[dict[str, Any]],
        batch_id: int,
        adjudication_ai_run_id: int | None,
    ) -> dict[str, Any]:
        published = 0
        sample_count = max(1, math.ceil(len(candidates) * 0.1))
        for index, candidate in enumerate(candidates):
            accepted = self.review_candidate(
                int(candidate["id"]),
                "accept",
                "AI双检自动接收",
                "低风险候选通过来源和独立复核门槛",
            )
            unit_id = int(accepted["unit_id"])
            unit = self.knowledge.get_unit(unit_id)
            version_id = int(unit["versions"][0]["id"])
            if unit["status"] == "review_required":
                self.knowledge.review_unit(unit_id, version_id, "approve", "AI双检自动审核", "按低风险自动发布策略批准")
            self.knowledge.publish_unit(unit_id, version_id, "AI低风险自动发布")
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE knowledge_ai_candidates SET auto_publish_batch_id=?,adjudication_decision='pass' WHERE id=?",
                    (batch_id, candidate["id"]),
                )
                sample_exists = conn.execute(
                    "SELECT id FROM knowledge_exception_tasks WHERE candidate_id=? AND issue_code='auto_publish_sample' AND status='open'",
                    (candidate["id"],),
                ).fetchone()
                if index < sample_count and not sample_exists:
                    conn.execute(
                        "INSERT INTO knowledge_exception_tasks(candidate_id,issue_code,severity,message,source) VALUES (?,'auto_publish_sample','low','自动发布抽检：核对原文忠实性和跨项目适用性','sampling')",
                        (candidate["id"],),
                    )
            published += 1
        return {"published": published, "batch_id": batch_id, "adjudication_ai_run_id": adjudication_ai_run_id}

    def _fail_run(self, run_id: int, extraction_ai_run_id: int | None, message: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE knowledge_ai_pipeline_runs SET status='failed',extraction_ai_run_id=?,error_message=?,completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (extraction_ai_run_id, message, run_id),
            )
        return self.get_run(run_id)

    def _document_context(self, document_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT d.*,s.industry,s.file_name,s.relative_path
                FROM standard_documents d JOIN source_files s ON s.id=d.source_id WHERE d.id=?
                """,
                (document_id,),
            ).fetchone()
            if not row:
                raise KeyError("标准文档不存在")
            sections = [
                dict(item)
                for item in conn.execute(
                    "SELECT id,heading,content,page_start,page_end FROM document_sections WHERE document_id=? ORDER BY order_no",
                    (document_id,),
                ).fetchall()
                if len(normalize_text(item["content"])) >= 30
            ]
        if not sections:
            raise ValueError("标准文档没有可加工的正文")
        return dict(row), sections

    @staticmethod
    def _section_text(sections: list[dict[str, Any]], max_chars: int = CHUNK_MAX_CHARS) -> str:
        blocks: list[str] = []
        used = 0
        for section in sections:
            block = f"[SECTION:{section['id']}] {section['heading']}\n{normalize_text(section['content'])}"
            if used + len(block) > max_chars:
                remaining = max_chars - used
                if remaining > 300:
                    blocks.append(block[:remaining])
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)

    @staticmethod
    def _rule_findings(candidate: dict[str, Any], section: dict[str, Any], section_valid: bool) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        content = normalize_text(candidate["content"])
        quote = normalize_text(candidate["source_quote"])
        source = normalize_text(section["content"])
        if not section_valid:
            findings.append({"code": "invalid_section", "severity": "high", "message": "候选引用了不存在的章节编号"})
        compact_source = re.sub(r"\s+", "", source)
        compact_quote = re.sub(r"\s+", "", quote)
        quote_lines = [re.sub(r"\s+", "", line) for line in quote.splitlines() if len(re.sub(r"\s+", "", line)) >= 8]
        matched_chars = sum(len(line) for line in quote_lines if line in compact_source)
        quoted_chars = sum(len(line) for line in quote_lines)
        quote_coverage = matched_chars / quoted_chars if quoted_chars else 0
        if compact_quote not in compact_source and quote_coverage < 0.85:
            findings.append({"code": "quote_mismatch", "severity": "high", "message": "来源引文无法在对应章节中逐字定位"})
        if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", content):
            findings.append({"code": "personal_phone", "severity": "high", "message": "候选内容包含疑似联系电话"})
        if re.search(r"\[(?:项目名称|联系电话|待确认|公司名称)\]", content):
            findings.append({"code": "unresolved_placeholder", "severity": "medium", "message": "候选内容仍包含未处理占位符"})
        if re.search(r"(?:确保|保证).{0,12}(?:100%|零事故|绝不|全部)|完全避免", content):
            findings.append({"code": "absolute_commitment", "severity": "medium", "message": "候选内容包含需要核验的绝对承诺"})
        if re.search(r"\d+(?:\.\d+)?\s*(?:天|人|台|万元|%|mm|cm|m|MPa)\b", content, re.IGNORECASE):
            findings.append({"code": "numeric_parameter", "severity": "medium", "message": "候选内容包含项目相关数值，应人工确认适用性"})
        return findings

    def review_candidate(self, candidate_id: int, action: str, reviewer: str, notes: str = "") -> dict[str, Any]:
        if action not in {"accept", "reject"}:
            raise ValueError("action必须为accept或reject")
        if not reviewer.strip():
            raise ValueError("审核人不能为空")
        candidate = self.get_candidate(candidate_id)
        if candidate["status"] in {"accepted", "rejected"}:
            return candidate
        unit_id: int | None = None
        if action == "accept":
            promoted = self.knowledge.create_unit_from_ai_candidate(candidate)
            unit_id = int(promoted["unit_id"])
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_ai_candidates SET status=?,unit_id=?,reviewed_by=?,review_notes=?,reviewed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                ("accepted" if action == "accept" else "rejected", unit_id, reviewer.strip(), notes, candidate_id),
            )
            conn.execute(
                """
                UPDATE knowledge_exception_tasks SET status='resolved',resolved_by=?,resolution=?,resolved_at=CURRENT_TIMESTAMP
                WHERE candidate_id=? AND status='open'
                """,
                (reviewer.strip(), notes or ("接收候选" if action == "accept" else "退回候选"), candidate_id),
            )
        return self.get_candidate(candidate_id)

    def accept_ready(self, reviewer: str, limit: int = 100) -> dict[str, Any]:
        candidates = self.list_candidates(status="ready", limit=limit)
        accepted = [self.review_candidate(int(item["id"]), "accept", reviewer) for item in candidates]
        return {"accepted": len(accepted), "unit_ids": [item["unit_id"] for item in accepted]}

    def get_candidate(self, candidate_id: int) -> dict[str, Any]:
        items = self._candidate_rows("WHERE c.id=?", (candidate_id,), 1)
        if not items:
            raise KeyError("候选知识不存在")
        items[0]["relations"] = self.db.rows(
            "SELECT * FROM candidate_relations WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        )
        return items[0]

    def list_chunks(self, document_id: int) -> list[dict[str, Any]]:
        return self.db.rows(
            """
            SELECT id,document_id,section_id,order_no,heading,char_start,char_end,page_start,page_end,
                content_hash,status,attempt_count,error_message,created_at,updated_at
            FROM document_chunks WHERE document_id=? ORDER BY order_no
            """,
            (document_id,),
        )

    def list_auto_publish_batches(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT * FROM knowledge_auto_publish_batches ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )

    def review_auto_publish_sample(self, batch_id: int, candidate_id: int, passed: bool, reviewer: str, notes: str) -> dict[str, Any]:
        if not reviewer.strip():
            raise ValueError("抽检人不能为空")
        candidate = self.db.row(
            "SELECT * FROM knowledge_ai_candidates WHERE id=? AND auto_publish_batch_id=?",
            (candidate_id, batch_id),
        )
        if not candidate:
            raise KeyError("自动发布批次中不存在该候选")
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_exception_tasks SET status='resolved',resolved_by=?,resolution=?,resolved_at=CURRENT_TIMESTAMP
                WHERE candidate_id=? AND issue_code='auto_publish_sample' AND status='open'
                """,
                (reviewer.strip(), notes or ("抽检通过" if passed else "抽检失败"), candidate_id),
            )
            if not passed:
                conn.execute(
                    "UPDATE knowledge_auto_publish_batches SET failed_sample_count=failed_sample_count+1,status='rolled_back',completed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (batch_id,),
                )
                unit_rows = conn.execute(
                    "SELECT unit_id FROM knowledge_ai_candidates WHERE auto_publish_batch_id=? AND unit_id IS NOT NULL",
                    (batch_id,),
                ).fetchall()
                for row in unit_rows:
                    conn.execute("UPDATE knowledge_publications SET status='retired',retired_at=CURRENT_TIMESTAMP WHERE unit_id=? AND status='published'", (row[0],))
                    self.knowledge._delete_sqlite_fts(conn, int(row[0]))
                    conn.execute("UPDATE knowledge_units SET status='approved',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row[0],))
                conn.execute("UPDATE knowledge_ai_candidates SET status='needs_review' WHERE auto_publish_batch_id=?", (batch_id,))
            else:
                remaining = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) FROM knowledge_exception_tasks t
                        JOIN knowledge_ai_candidates c ON c.id=t.candidate_id
                        WHERE c.auto_publish_batch_id=? AND t.issue_code='auto_publish_sample' AND t.status='open'
                        """,
                        (batch_id,),
                    ).fetchone()[0]
                )
                if not remaining:
                    conn.execute(
                        "UPDATE knowledge_auto_publish_batches SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (batch_id,),
                    )
        if not passed and self.knowledge.on_publication_changed:
            self.knowledge.on_publication_changed("batch_rolled_back", {"batch_id": batch_id})
        return self.db.row("SELECT * FROM knowledge_auto_publish_batches WHERE id=?", (batch_id,)) or {}

    def list_candidates(self, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        where = "WHERE c.status=?" if status else "WHERE c.status<>'superseded'"
        params: tuple[Any, ...] = (status,) if status else ()
        return self._candidate_rows(where, params, limit)

    def _candidate_rows(self, where: str, params: tuple[Any, ...], limit: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,d.title AS document_title,s.file_name,s.industry,ds.heading AS source_heading,ar.model,
                    pr.review_ai_run_id
                FROM knowledge_ai_candidates c
                JOIN standard_documents d ON d.id=c.document_id
                JOIN source_files s ON s.id=c.source_id
                JOIN document_sections ds ON ds.id=c.source_section_id
                JOIN knowledge_ai_pipeline_runs pr ON pr.id=c.pipeline_run_id
                LEFT JOIN ai_runs ar ON ar.id=pr.extraction_ai_run_id
                {where} ORDER BY c.id DESC LIMIT ?
                """,
                (*params, max(1, min(limit, 500))),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["tags"] = parse_json(item.pop("tags_json"), [])
            item["review_issues"] = parse_json(item.pop("review_issues_json"), [])
            item["rule_findings"] = parse_json(item.pop("rule_findings_json"), [])
        return items

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.rows(
            """
            SELECT r.*,d.title AS document_title,s.file_name
            FROM knowledge_ai_pipeline_runs r JOIN standard_documents d ON d.id=r.document_id
            JOIN source_files s ON s.id=d.source_id ORDER BY r.id DESC LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        )

    def get_run(self, run_id: int) -> dict[str, Any]:
        row = self.db.row(
            """
            SELECT r.*,d.title AS document_title,s.file_name
            FROM knowledge_ai_pipeline_runs r JOIN standard_documents d ON d.id=r.document_id
            JOIN source_files s ON s.id=d.source_id WHERE r.id=?
            """,
            (run_id,),
        )
        if not row:
            raise KeyError("知识加工记录不存在")
        return row

    def list_tasks(self, status: str = "open", limit: int = 200) -> list[dict[str, Any]]:
        where = "WHERE t.status=?" if status else ""
        params: list[Any] = [status] if status else []
        return self.db.rows(
            f"""
            SELECT t.*,c.title,c.document_id,c.risk_level,c.status AS candidate_status
            FROM knowledge_exception_tasks t JOIN knowledge_ai_candidates c ON c.id=t.candidate_id
            {where} ORDER BY CASE t.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,t.id DESC LIMIT ?
            """,
            [*params, max(1, min(limit, 500))],
        )

    def metrics(self) -> dict[str, int]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS candidates,
                    SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) AS ready,
                    SUM(CASE WHEN status='needs_review' THEN 1 ELSE 0 END) AS needs_review,
                    SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted
                FROM knowledge_ai_candidates WHERE status<>'superseded'
                """
            ).fetchone()
            open_tasks = int(conn.execute("SELECT COUNT(*) FROM knowledge_exception_tasks WHERE status='open'").fetchone()[0])
        return {**{key: int(row[key] or 0) for key in row.keys()}, "open_tasks": open_tasks}
