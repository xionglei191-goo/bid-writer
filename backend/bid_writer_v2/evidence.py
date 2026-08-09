from __future__ import annotations

import json
import re
from typing import Any

from .database import Database
from .utils import content_hash, normalize_text


def _ngrams(text: str, size: int = 2) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    return {compact[index:index + size] for index in range(max(0, len(compact) - size + 1))}


def support_score(claim: str, evidence: str) -> float:
    claim_terms = _ngrams(claim)
    if not claim_terms:
        return 0.0
    compact_claim = re.sub(r"\s+", "", claim)
    compact_evidence = re.sub(r"\s+", "", evidence)
    if len(compact_claim) >= 12 and compact_claim in compact_evidence:
        return 1.0
    return round(len(claim_terms & _ngrams(evidence)) / len(claim_terms), 4)


def classify_claim(text: str) -> tuple[str, str]:
    if re.search(r"(?:确保|保证|承诺|必须|不得|严禁|零事故|100%)", text):
        return "commitment", "high"
    if re.search(r"\d+(?:\.\d+)?\s*(?:天|日|人|台|套|万元|%|mm|cm|m|MPa|kN|℃)", text, re.IGNORECASE):
        return "numeric", "high"
    if re.search(r"(?:GB|JGJ|CJJ|DBJ|规范|规程|标准)\s*[-A-Za-z0-9/]*", text, re.IGNORECASE):
        return "standard", "high"
    if re.search(r"(?:建议|宜|可采用|拟采用)", text):
        return "proposal", "low"
    if re.search(r"(?:曾|已完成|业绩|经验|具备)", text):
        return "experience", "medium"
    return "fact", "medium"


def claim_sentences(markdown: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for line in normalize_text(markdown).splitlines():
        stripped = line.strip().lstrip("#*-| ").strip()
        if not stripped or stripped.startswith("---") or len(stripped) < 12:
            continue
        if stripped.startswith("本章结合") and "进行编制" in stripped:
            continue
        for sentence in re.split(r"(?<=[。！？；])", stripped):
            sentence = normalize_text(sentence)
            if 12 <= len(sentence) <= 500 and sentence not in seen:
                seen.add(sentence)
                output.append(sentence)
    return output[:300]


class EvidenceService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_generation_run(
        self,
        project_id: int,
        section_id: int,
        input_hash: str,
        model: str,
        prompt_version: str,
        rule_version: str,
        retrieval_run_id: int | None,
        knowledge_snapshot: list[dict[str, Any]],
    ) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO generation_runs(
                    project_id,section_id,retrieval_run_id,input_hash,model,prompt_version,rule_version,
                    knowledge_snapshot_json
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    section_id,
                    retrieval_run_id,
                    input_hash,
                    model,
                    prompt_version,
                    rule_version,
                    json.dumps(knowledge_snapshot, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def analyze_draft(self, generation_run_id: int, draft_id: int, content: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        sentences = claim_sentences(content)
        unsupported_high: list[str] = []
        supported = 0
        with self.db.connect() as conn:
            conn.execute("DELETE FROM claims WHERE draft_id=?", (draft_id,))
            for index, sentence in enumerate(sentences):
                claim_type, risk = classify_claim(sentence)
                ranked = sorted(
                    ((support_score(sentence, str(source.get("content") or "")), source) for source in sources),
                    key=lambda item: item[0],
                    reverse=True,
                )
                best_score, best_source = ranked[0] if ranked else (0.0, {})
                threshold = 0.42 if risk == "high" else 0.32
                status = "supported" if best_score >= threshold else "unsupported"
                if status == "supported":
                    supported += 1
                elif risk == "high":
                    unsupported_high.append(sentence)
                cursor = conn.execute(
                    """
                    INSERT INTO claims(
                        generation_run_id,draft_id,claim_index,claim_type,text,risk_level,support_status,
                        confidence,content_hash
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        generation_run_id,
                        draft_id,
                        index,
                        claim_type,
                        sentence,
                        risk,
                        status,
                        best_score,
                        content_hash(sentence),
                    ),
                )
                claim_id = int(cursor.lastrowid)
                if best_source:
                    excerpt = normalize_text(str(best_source.get("content") or ""))[:1200]
                    conn.execute(
                        """
                        INSERT INTO evidence_links(
                            claim_id,unit_id,publication_id,retrieval_run_id,source_excerpt,source_page,
                            support_level,score,evidence_hash
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            claim_id,
                            best_source.get("unit_id"),
                            best_source.get("publication_id"),
                            best_source.get("retrieval_run_id"),
                            excerpt,
                            ((best_source.get("sources") or [{}])[0]).get("page_start"),
                            status,
                            best_score,
                            content_hash(f"{best_source.get('content_hash', '')}|{excerpt}"),
                        ),
                    )
            evidence_status = "blocked" if unsupported_high else ("supported" if sentences else "not_applicable")
            conn.execute("UPDATE project_drafts SET evidence_status=? WHERE id=?", (evidence_status, draft_id))
            conn.execute(
                "UPDATE generation_runs SET draft_id=?,status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft_id, generation_run_id),
            )
        return {
            "claims": len(sentences),
            "supported": supported,
            "support_rate": round(supported / len(sentences), 4) if sentences else 1.0,
            "unsupported_high": unsupported_high,
            "evidence_status": evidence_status,
        }

    def list_claims(self, draft_id: int) -> list[dict[str, Any]]:
        claims = self.db.rows("SELECT * FROM claims WHERE draft_id=? ORDER BY claim_index", (draft_id,))
        for claim in claims:
            claim["evidence"] = self.db.rows(
                """
                SELECT e.*,u.title AS unit_title,p.publication_version,s.file_name,s.relative_path
                FROM evidence_links e
                LEFT JOIN knowledge_units u ON u.id=e.unit_id
                LEFT JOIN knowledge_publications p ON p.id=e.publication_id
                LEFT JOIN knowledge_unit_sources us ON us.unit_id=e.unit_id
                LEFT JOIN source_files s ON s.id=us.source_id
                WHERE e.claim_id=? ORDER BY e.score DESC
                """,
                (claim["id"],),
            )
        return claims

    def resolve_claim(self, claim_id: int, action: str, resolution: str) -> dict[str, Any]:
        if action not in {"confirm", "weaken", "remove", "reopen"}:
            raise ValueError("未知Claim处理动作")
        row = self.db.row("SELECT * FROM claims WHERE id=?", (claim_id,))
        if not row:
            raise KeyError("Claim不存在")
        status = "confirmed" if action == "confirm" else ("resolved" if action in {"weaken", "remove"} else "unsupported")
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE claims SET support_status=?,resolution=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, normalize_text(resolution), claim_id),
            )
            blocked = conn.execute(
                "SELECT COUNT(*) FROM claims WHERE draft_id=? AND risk_level='high' AND support_status='unsupported'",
                (row["draft_id"],),
            ).fetchone()[0]
            conn.execute(
                "UPDATE project_drafts SET evidence_status=? WHERE id=?",
                ("blocked" if blocked else "supported", row["draft_id"]),
            )
        return {"claim_id": claim_id, "support_status": status, "evidence_status": "blocked" if blocked else "supported"}

    def metrics(self, project_id: int) -> dict[str, Any]:
        row = self.db.row(
            """
            SELECT COUNT(*) AS total,
                SUM(CASE WHEN c.support_status IN ('supported','confirmed','resolved') THEN 1 ELSE 0 END) AS supported,
                SUM(CASE WHEN c.risk_level='high' THEN 1 ELSE 0 END) AS high_total,
                SUM(CASE WHEN c.risk_level='high' AND c.support_status='unsupported' THEN 1 ELSE 0 END) AS high_unsupported
            FROM claims c JOIN project_drafts d ON d.id=c.draft_id WHERE d.project_id=?
            """,
            (project_id,),
        ) or {"total": 0, "supported": 0, "high_total": 0, "high_unsupported": 0}
        metrics = {key: int(row[key] or 0) for key in row}
        metrics["support_rate"] = round(metrics["supported"] / metrics["total"] * 100, 2) if metrics["total"] else 100.0
        return metrics
