from __future__ import annotations

import json
import re
from contextlib import nullcontext
from typing import Any

from .database import Database
from .project_evidence import PROJECT_EVIDENCE_VERSION, ProjectEvidenceIndex, number_bindings, project_source_snapshot
from .utils import content_hash, normalize_text, parse_json


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
    if re.search(r"(?:确保|保证|承诺|必须|不得|禁止|严禁|零事故|零投诉|100%)", text):
        return "commitment", "high"
    if number_bindings(text):
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
        if not stripped or stripped.startswith("---"):
            continue
        if stripped.startswith("本章结合") and "进行编制" in stripped:
            continue
        for sentence in re.split(r"(?<=[。！？；])", stripped):
            sentence = normalize_text(sentence)
            _, risk = classify_claim(sentence)
            is_heading = bool(re.match(r"^\s{0,3}#{1,6}\s", line))
            if sentence and (len(sentence) >= 12 or risk == "high") and (not is_heading or risk == "high") and sentence not in seen:
                seen.add(sentence)
                output.append(sentence)
    return output


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
        *, conn=None,
    ) -> int:
        with (nullcontext(conn) if conn is not None else self.db.connect()) as conn:
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

    def _lock_project(self, conn, project_id: int) -> None:
        if self.db.backend == "sqlite":
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            return
        if not conn.execute("SELECT id FROM projects WHERE id=? FOR UPDATE", (project_id,)).fetchone():
            raise KeyError("项目不存在")

    def analyze_draft(self, generation_run_id: int, draft_id: int, content: str, sources: list[dict[str, Any]], *, conn=None) -> dict[str, Any]:
        analyzed_hash = content_hash(content)
        sentences = claim_sentences(content)
        unsupported_high: list[str] = []
        supported = 0
        with (nullcontext(conn) if conn is not None else self.db.connect()) as conn:
            # Compare the actual saved body while holding its write lock, so a
            # slower analysis cannot replace evidence for a newer saved edit.
            if self.db.backend == "sqlite" and conn.in_transaction is not True:
                conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute("SELECT project_id,section_id FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            if not owner:
                raise KeyError("章节草稿不存在")
            project_id = int(owner["project_id"])
            # All editing/freeze paths acquire the parent first. Taking only
            # the draft lock here can deadlock against an in-flight freeze.
            if self.db.backend == "postgresql":
                self._lock_project(conn, project_id)
            lock_clause = " FOR UPDATE" if self.db.backend == "postgresql" else ""
            draft = conn.execute(
                f"SELECT content FROM project_drafts WHERE id=?{lock_clause}", (draft_id,),
            ).fetchone()
            if not draft:
                raise KeyError("章节草稿不存在")
            generation = conn.execute("SELECT project_id,section_id FROM generation_runs WHERE id=?", (generation_run_id,)).fetchone()
            if not generation or generation["project_id"] != project_id or generation["section_id"] not in (None, owner["section_id"]):
                raise ValueError("证据分析任务与当前项目或章节不匹配")
            current_hash = content_hash(draft["content"])
            if current_hash != analyzed_hash:
                conn.execute(
                    "UPDATE generation_runs SET draft_id=?,status='invalidated',completed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (draft_id, generation_run_id),
                )
                return {
                    "claims": 0, "supported": 0, "support_rate": 0.0, "unsupported_high": [],
                    "evidence_status": "stale", "stale": True,
                    "analyzed_content_hash": analyzed_hash, "current_content_hash": current_hash,
                }
            project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                raise KeyError("项目不存在")
            matcher = ProjectEvidenceIndex(dict(project), sources)
            project_hash = matcher.snapshot["project_source_hash"]
            conn.execute("DELETE FROM claims WHERE draft_id=?", (draft_id,))
            for index, sentence in enumerate(sentences):
                claim_type, risk = classify_claim(sentence)
                binding = matcher.evaluate(sentence)
                best_score = binding["score"]
                status = "supported" if binding["supported"] else "unsupported"
                if status == "supported":
                    supported += 1
                elif risk == "high":
                    unsupported_high.append(sentence)
                cursor = conn.execute(
                    """
                    INSERT INTO claims(
                        generation_run_id,draft_id,claim_index,claim_type,text,risk_level,support_status,
                        confidence,content_hash,analysis_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
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
                        json.dumps({key: binding[key] for key in ("reason", "assertions", "project_source_hash")}, ensure_ascii=False),
                    ),
                )
                claim_id = int(cursor.lastrowid)
                for match in binding["matches"]:
                    excerpt = normalize_text(str(match.get("source_excerpt") or ""))
                    source_meta = {key: match.get(key) for key in ("project_id", "source_hash", "page_hash", "assertion", "supported", "match_reason", "objects", "numbers", "conditions")}
                    source_meta["project_source_hash"] = project_hash
                    conn.execute(
                        """
                        INSERT INTO evidence_links(
                            claim_id,unit_id,publication_id,retrieval_run_id,source_excerpt,source_page,
                            support_level,score,evidence_hash,source_kind,source_title,source_meta_json,project_source_hash
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            claim_id,
                            match.get("unit_id"),
                            match.get("publication_id"),
                            match.get("retrieval_run_id"),
                            excerpt,
                            match.get("source_page"),
                            status,
                            match["score"],
                            content_hash(f"{project_hash}|{match.get('source_hash', '')}|{excerpt}"),
                            match["source_kind"], match["source_title"], json.dumps(source_meta, ensure_ascii=False), project_hash,
                        ),
                    )
            evidence_status = "blocked" if unsupported_high or matcher.profile_conflicts else ("supported" if sentences else "not_applicable")
            conn.execute("UPDATE project_drafts SET evidence_status=? WHERE id=?", (evidence_status, draft_id))
            conn.execute(
                "UPDATE generation_runs SET draft_id=?,project_source_hash=?,rule_version=?,status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft_id, project_hash, PROJECT_EVIDENCE_VERSION, generation_run_id),
            )
        return {
            "claims": len(sentences),
            "supported": supported,
            "support_rate": round(supported / len(sentences), 4) if sentences else 1.0,
            "unsupported_high": unsupported_high,
            "evidence_status": evidence_status,
            "stale": False,
            "draft_id": draft_id, "run_id": generation_run_id, "generation_run_id": generation_run_id,
            "analyzed_content_hash": analyzed_hash, "current_content_hash": current_hash,
            "project_source_hash": project_hash, "current_project_source_hash": project_hash,
            "source_hash": matcher.snapshot["source_hash"], "profile_conflicts": matcher.profile_conflicts,
        }

    def list_claims(self, draft_id: int, *, conn=None) -> list[dict[str, Any]]:
        with (nullcontext(conn) if conn is not None else self.db.connect()) as conn:
            project = conn.execute("SELECT p.* FROM projects p JOIN project_drafts d ON d.project_id=p.id WHERE d.id=?", (draft_id,)).fetchone()
            if not project:
                return []
            snapshot = project_source_snapshot(dict(project))
            draft = conn.execute("SELECT content FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            current_hash = content_hash(draft["content"])
            claims = [dict(row) for row in conn.execute(
                "SELECT c.*,g.project_source_hash,g.rule_version AS analyzed_rule_version FROM claims c JOIN generation_runs g ON g.id=c.generation_run_id WHERE c.draft_id=? ORDER BY c.claim_index",
                (draft_id,),
            ).fetchall()]
            for claim in claims:
                claim["analysis"] = parse_json(claim.pop("analysis_json", "{}"), {})
                rule_stale = claim["analyzed_rule_version"] != PROJECT_EVIDENCE_VERSION
                claim["current_rule_version"] = PROJECT_EVIDENCE_VERSION
                claim["source_stale"] = claim["project_source_hash"] != snapshot["project_source_hash"] or rule_stale
                claim["source_stale_reason"] = ("证据核验规则已更新，必须重新分析证据" if rule_stale else "项目原文或资料已变化，必须重新分析证据") if claim["source_stale"] else ""
                claim["current_project_source_hash"] = snapshot["project_source_hash"]
                claim["draft_content_hash"] = current_hash
                if claim["source_stale"]:
                    claim["stored_support_status"] = claim["support_status"]
                    claim["support_status"] = "invalidated"
                links = [dict(row) for row in conn.execute(
                    """SELECT e.*,u.title AS unit_title,p.publication_version,
                        (SELECT s.file_name FROM knowledge_unit_sources us JOIN source_files s ON s.id=us.source_id WHERE us.unit_id=e.unit_id ORDER BY us.id LIMIT 1) AS file_name,
                        (SELECT s.relative_path FROM knowledge_unit_sources us JOIN source_files s ON s.id=us.source_id WHERE us.unit_id=e.unit_id ORDER BY us.id LIMIT 1) AS relative_path
                    FROM evidence_links e LEFT JOIN knowledge_units u ON u.id=e.unit_id
                    LEFT JOIN knowledge_publications p ON p.id=e.publication_id
                    WHERE e.claim_id=? ORDER BY e.score DESC,e.id""", (claim["id"],),
                ).fetchall()]
                for link in links:
                    link["source_meta"] = parse_json(link.pop("source_meta_json", "{}"), {})
                    link["title"] = link.get("source_title") or link.get("unit_title") or link.get("file_name") or "历史来源"
                    link["page"] = link.get("source_page")
                    link["excerpt"] = link["source_excerpt"]
                    link["match_reason"] = link["source_meta"].get("match_reason") or "历史证据尚无完整对象绑定"
                    link["source_stale"] = claim["source_stale"] or link["project_source_hash"] != snapshot["project_source_hash"]
                    if link["source_stale"]:
                        link["support_level"] = "invalidated"
                claim["evidence"] = links
            return claims

    def project_source_status(self, project_id: int, *, conn=None) -> dict[str, Any]:
        """Read-only comparison, safe inside the caller's project transaction."""
        with (nullcontext(conn) if conn is not None else self.db.connect()) as conn:
            project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project:
                raise KeyError("项目不存在")
            matcher = ProjectEvidenceIndex(dict(project))
            snapshot = matcher.snapshot
            drafts = []
            rows = conn.execute(
                """SELECT d.id,d.content,d.evidence_status FROM project_drafts d WHERE d.project_id=?
                AND NOT EXISTS (SELECT 1 FROM project_drafts newer WHERE newer.section_id=d.section_id AND newer.version_no>d.version_no)
                ORDER BY d.id""", (project_id,),
            ).fetchall()
            for row in rows:
                run = conn.execute("SELECT id,project_source_hash,rule_version,status FROM generation_runs WHERE draft_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
                analyzed = str(run["project_source_hash"] or "") if run else ""
                rule_stale = bool(run and run["rule_version"] != PROJECT_EVIDENCE_VERSION)
                stale = not run or run["status"] != "completed" or analyzed != snapshot["project_source_hash"] or rule_stale
                drafts.append({"draft_id": row["id"], "run_id": run["id"] if run else None,
                               "project_source_hash": analyzed, "current_project_source_hash": snapshot["project_source_hash"],
                               "analyzed_rule_version": run["rule_version"] if run else "", "current_rule_version": PROJECT_EVIDENCE_VERSION,
                               "current_content_hash": content_hash(row["content"]), "stale": stale,
                               "reason": "证据核验规则已更新，必须重新分析证据" if rule_stale else ("项目原文或资料已变化，必须重新分析证据" if analyzed and analyzed != snapshot["project_source_hash"] else ("当前草稿缺少完成的证据分析" if stale else "证据绑定当前项目来源"))})
            return {"project_id": project_id, "current_project_source_hash": snapshot["project_source_hash"],
                    "project_source_hash": snapshot["project_source_hash"], "source_hash": snapshot["source_hash"],
                    "stale_draft_ids": [item["draft_id"] for item in drafts if item["stale"]],
                    "stale": any(item["stale"] for item in drafts), "drafts": drafts,
                    "profile_conflicts": matcher.profile_conflicts, "rule_version": PROJECT_EVIDENCE_VERSION}

    def refresh_project_evidence(self, project_id: int, *, draft_ids: list[int] | None = None, conn=None) -> dict[str, Any]:
        """Reanalyze saved latest drafts; never edit text or apply a sign-off."""
        with (nullcontext(conn) if conn is not None else self.db.connect()) as conn:
            self._lock_project(conn, project_id)
            latest = [dict(row) for row in conn.execute(
                """SELECT d.* FROM project_drafts d WHERE d.project_id=? AND NOT EXISTS (
                SELECT 1 FROM project_drafts newer WHERE newer.section_id=d.section_id AND newer.version_no>d.version_no) ORDER BY d.id""", (project_id,),
            ).fetchall()]
            if draft_ids is not None:
                selected = {int(value) for value in draft_ids}
                if not selected or not selected.issubset({row["id"] for row in latest}):
                    raise ValueError("只能刷新本项目的当前章节草稿")
                latest = [row for row in latest if row["id"] in selected]
            results = []
            for draft in latest:
                citations = parse_json(draft["citations_json"], [])
                sources = []
                for citation in citations:
                    source = conn.execute(
                        """SELECT p.unit_id,p.id AS publication_id,p.content_hash,v.content,u.title
                        FROM knowledge_publications p JOIN knowledge_versions v ON v.id=p.version_id
                        JOIN knowledge_units u ON u.id=p.unit_id WHERE p.id=? AND p.status='published' AND p.content_hash=?""",
                        (citation.get("publication_id"), citation.get("content_hash")),
                    ).fetchone()
                    if source:
                        sources.append({**dict(source), "sources": citation.get("sources") or []})
                run_id = self.create_generation_run(project_id, int(draft["section_id"]), content_hash(draft["content"]),
                                                    "deterministic-project-evidence", "reanalysis-1", PROJECT_EVIDENCE_VERSION, None, citations, conn=conn)
                results.append(self.analyze_draft(run_id, int(draft["id"]), draft["content"], sources, conn=conn))
            status = self.project_source_status(project_id, conn=conn)
            return {"project_id": project_id, "drafts": results, "analyzed_count": len(results),
                    "current_project_source_hash": status["current_project_source_hash"],
                    "profile_conflicts": status["profile_conflicts"], "source_status": status}

    def resolve_claim(self, claim_id: int, action: str, resolution: str, *, reviewer: str = "", target_hash: str = "", project_source_hash: str = "") -> dict[str, Any]:
        if action not in {"confirm", "weaken", "remove", "reopen"}:
            raise ValueError("未知Claim处理动作")
        if action in {"weaken", "remove"}:
            raise ValueError("弱化或删除必须先编辑草稿正文，不能保留原句后仅改处理状态")
        if not normalize_text(reviewer) or not normalize_text(resolution):
            raise ValueError("必须填写实际核验人和具体核验依据")
        status = "confirmed" if action == "confirm" else "unsupported"
        with self.db.connect() as conn:
            if self.db.backend == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute("SELECT d.project_id,c.draft_id FROM claims c JOIN project_drafts d ON d.id=c.draft_id WHERE c.id=?", (claim_id,)).fetchone()
            if not owner:
                raise KeyError("Claim不存在")
            self._lock_project(conn, int(owner["project_id"]))
            lock = " FOR UPDATE" if self.db.backend == "postgresql" else ""
            draft = conn.execute(f"SELECT content FROM project_drafts WHERE id=?{lock}", (owner["draft_id"],)).fetchone()
            if conn.execute("""SELECT newer.id FROM project_drafts current JOIN project_drafts newer
                ON newer.section_id=current.section_id AND newer.version_no>current.version_no WHERE current.id=? LIMIT 1""", (owner["draft_id"],)).fetchone():
                raise ValueError("历史草稿不能处理Claim，请切换到当前章节版本")
            row = conn.execute("SELECT c.*,g.project_source_hash AS analyzed_project_source_hash,g.rule_version AS analyzed_rule_version FROM claims c JOIN generation_runs g ON g.id=c.generation_run_id WHERE c.id=?", (claim_id,)).fetchone()
            if not row:
                raise ValueError("证据已重新分析，请刷新页面后核验当前条目")
            current_hash = content_hash(draft["content"])
            project = conn.execute("SELECT * FROM projects WHERE id=?", (owner["project_id"],)).fetchone()
            current_source_hash = project_source_snapshot(dict(project))["project_source_hash"]
            if not target_hash or target_hash != current_hash:
                raise ValueError("草稿正文已变化，请按当前版本重新核验")
            if not project_source_hash or project_source_hash != current_source_hash or row["analyzed_project_source_hash"] != current_source_hash:
                raise ValueError("项目来源已变化或证据未绑定来源，请先重新分析")
            if row["analyzed_rule_version"] != PROJECT_EVIDENCE_VERSION:
                raise ValueError("证据核验规则已更新，请先重新分析")
            if row["support_status"] == "invalidated" or row["text"] not in claim_sentences(draft["content"]):
                raise ValueError("该表述已不属于当前草稿证据，请先重新分析")
            conn.execute(
                "UPDATE claims SET support_status=?,resolution=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, normalize_text(resolution), claim_id),
            )
            conn.execute(
                """INSERT INTO claim_review_events(claim_id,draft_id,project_id,claim_text,claim_hash,action,reviewer,resolution,target_hash,project_source_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (claim_id, row["draft_id"], owner["project_id"], row["text"], row["content_hash"], action, normalize_text(reviewer), normalize_text(resolution), current_hash, current_source_hash),
            )
            blocked = conn.execute(
                "SELECT COUNT(*) FROM claims WHERE draft_id=? AND risk_level='high' AND support_status NOT IN ('supported','confirmed')",
                (row["draft_id"],),
            ).fetchone()[0]
            conn.execute(
                "UPDATE project_drafts SET evidence_status=? WHERE id=?",
                ("blocked" if blocked else "supported", row["draft_id"]),
            )
            conn.execute("UPDATE project_drafts SET status='draft',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["draft_id"],))
            conn.execute("UPDATE project_sections SET status='drafted' WHERE id=(SELECT section_id FROM project_drafts WHERE id=?)", (row["draft_id"],))
            conn.execute("UPDATE draft_review_decisions SET decision='invalidated' WHERE draft_id=? AND decision='approved'", (row["draft_id"],))
            conn.execute("UPDATE requirement_responses SET review_status='invalidated' WHERE draft_id=?", (row["draft_id"],))
            conn.execute("UPDATE delivery_manifests SET status='invalidated',invalidated_at=CURRENT_TIMESTAMP WHERE project_id=? AND invalidated_at IS NULL", (owner["project_id"],))
        return {"claim_id": claim_id, "support_status": status, "evidence_status": "blocked" if blocked else "supported",
                "reviewer": normalize_text(reviewer), "target_hash": current_hash, "project_source_hash": current_source_hash}

    def metrics(self, project_id: int, *, conn=None) -> dict[str, Any]:
        query = """
            SELECT COUNT(*) AS total,
                SUM(CASE WHEN c.support_status IN ('supported','confirmed') THEN 1 ELSE 0 END) AS supported,
                SUM(CASE WHEN c.risk_level='high' THEN 1 ELSE 0 END) AS high_total,
                SUM(CASE WHEN c.risk_level='high' AND c.support_status NOT IN ('supported','confirmed') THEN 1 ELSE 0 END) AS high_unsupported
            FROM claims c JOIN project_drafts d ON d.id=c.draft_id WHERE d.project_id=?
                AND NOT EXISTS (SELECT 1 FROM project_drafts newer
                    WHERE newer.section_id=d.section_id AND newer.version_no>d.version_no)
            """
        row = (conn.execute(query, (project_id,)).fetchone() if conn is not None else self.db.row(query, (project_id,))) or {"total": 0, "supported": 0, "high_total": 0, "high_unsupported": 0}
        row = dict(row)
        metrics = {key: int(row[key] or 0) for key in row}
        metrics["support_rate"] = round(metrics["supported"] / metrics["total"] * 100, 2) if metrics["total"] else 100.0
        return metrics
