from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import hashlib
import zipfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..ai_runtime import AiRuntime, SECTION_DRAFT_PROMPT
from ..database import Database
from ..audit import AuditService
from ..evidence import EvidenceService
from ..knowledge.service import KnowledgeService
from ..llm import LlmClient
from ..settings import Settings
from ..storage import ObjectStorage
from ..utils import content_hash, normalize_text, parse_json, write_text_atomic


DEFAULT_OUTLINE = [
    "工程概况与编制依据",
    "施工总体部署",
    "施工准备与资源配置",
    "主要施工方案与技术措施",
    "工程重点难点分析及对策",
    "质量保证体系与措施",
    "安全文明施工与环境保护",
    "施工进度计划及保证措施",
    "施工总平面布置",
    "季节性施工与应急预案",
    "BIM及新技术应用",
]


class ProductionService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        knowledge: KnowledgeService,
        llm: LlmClient | None = None,
        ai_runtime: AiRuntime | None = None,
        evidence: EvidenceService | None = None,
        storage: ObjectStorage | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.knowledge = knowledge
        self.llm = llm or LlmClient()
        self.ai_runtime = ai_runtime or AiRuntime(db, self.llm)
        self.evidence = evidence or EvidenceService(db)
        self.storage = storage or ObjectStorage(db, settings)
        self.audit = audit or AuditService(db)

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("项目名称不能为空")
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO projects(name,industry,project_type,region,source_text,profile_json) VALUES (?,?,?,?,?,?)",
                (
                    name,
                    payload.get("industry") or "通用",
                    payload.get("project_type") or "",
                    payload.get("region") or "",
                    payload.get("source_text") or "",
                    json.dumps(profile, ensure_ascii=False),
                ),
            )
            project_id = int(cursor.lastrowid)
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                    (SELECT COUNT(*) FROM project_requirements r WHERE r.project_id=p.id) AS requirement_count,
                    (SELECT COUNT(*) FROM project_sections s WHERE s.project_id=p.id) AS section_count,
                    (SELECT COUNT(*) FROM project_drafts d WHERE d.project_id=p.id) AS draft_count
                FROM projects p ORDER BY p.id DESC
                """
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["profile"] = parse_json(item.pop("profile_json", "{}"), {})
        return items

    def get_project(self, project_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError("项目不存在")
            item = dict(row)
            item["profile"] = parse_json(item.pop("profile_json", "{}"), {})
            item["requirements"] = [dict(value) for value in conn.execute("SELECT * FROM project_requirements WHERE project_id=? ORDER BY id", (project_id,))]
            sections = [dict(value) for value in conn.execute("SELECT * FROM project_sections WHERE project_id=? ORDER BY order_no", (project_id,))]
            for section in sections:
                section["requirement_ids"] = parse_json(section.pop("requirement_ids_json", "[]"), [])
                draft = conn.execute("SELECT * FROM project_drafts WHERE section_id=? ORDER BY version_no DESC LIMIT 1", (section["id"],)).fetchone()
                section["draft"] = dict(draft) if draft else None
                if section["draft"]:
                    section["draft"]["citations"] = parse_json(section["draft"].pop("citations_json", "[]"), [])
                    section["draft"]["confirmations"] = parse_json(section["draft"].pop("confirmations_json", "[]"), [])
                    section["draft"]["content_hash"] = section["draft"].get("content_hash") or content_hash(section["draft"]["content"])
                    section["draft"]["confirmation_resolutions"] = [
                        dict(value)
                        for value in conn.execute(
                            "SELECT confirmation_index,confirmation_text,resolution,resolver,created_at "
                            "FROM confirmation_resolutions WHERE draft_id=? AND target_hash=? ORDER BY confirmation_index",
                            (section["draft"]["id"], section["draft"]["content_hash"]),
                        )
                    ]
                    section["draft"]["claims"] = self.evidence.list_claims(int(section["draft"]["id"]))
            item["sections"] = sections
            item["quality_issues"] = [
                dict(value)
                for value in conn.execute(
                    "SELECT * FROM quality_issues WHERE project_id=? ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,id DESC",
                    (project_id,),
                )
            ]
        return item

    def update_project(self, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_project(project_id)
        profile = current["profile"]
        if isinstance(payload.get("profile"), dict):
            profile.update(payload["profile"])
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE projects SET name=?,industry=?,project_type=?,region=?,source_text=?,profile_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    payload.get("name", current["name"]),
                    payload.get("industry", current["industry"]),
                    payload.get("project_type", current["project_type"]),
                    payload.get("region", current["region"]),
                    payload.get("source_text", current["source_text"]),
                    json.dumps(profile, ensure_ascii=False),
                    project_id,
                ),
            )
            conn.execute("UPDATE delivery_manifests SET invalidated_at=CURRENT_TIMESTAMP,status='invalidated' WHERE project_id=? AND invalidated_at IS NULL", (project_id,))
            conn.execute("UPDATE generation_runs SET status='invalidated' WHERE project_id=? AND status='completed'", (project_id,))
        return self.get_project(project_id)

    def parse_requirements(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        source_text = normalize_text(project.get("source_text") or "")
        candidates = [line.strip(" -\t") for line in source_text.splitlines() if len(line.strip()) >= 8]
        requirements: list[dict[str, Any]] = []
        seen: set[str] = set()
        keywords = ["项目", "工程", "应", "须", "不得", "评分", "要求", "工期", "质量", "安全", "施工", "技术", "方案", "响应"]
        for line in candidates:
            if line in seen:
                continue
            if not any(keyword in line for keyword in keywords):
                continue
            seen.add(line)
            priority = "high" if any(keyword in line for keyword in ["评分", "必须", "不得", "废标", "否决"]) else "normal"
            if any(keyword in line for keyword in ["废标", "否决", "不得"]):
                kind = "veto"
            elif any(keyword in line for keyword in ["评分", "得分", "分值"]):
                kind = "scoring"
            elif any(keyword in line for keyword in ["资质", "资格", "业绩", "证书"]):
                kind = "qualification"
            elif any(keyword in line for keyword in ["承诺", "保证"]):
                kind = "commitment"
            elif any(keyword in line for keyword in ["参数", "不低于", "不少于", "不大于", "工期"]):
                kind = "parameter"
            elif any(keyword in line for keyword in ["提交", "交付", "附件", "表格"]):
                kind = "deliverable"
            elif any(keyword in line for keyword in ["待定", "另行", "未明确"]):
                kind = "confirmation"
            else:
                kind = "technical"
            requirements.append({"content": line[:1000], "priority": priority, "kind": kind})
        if not requirements and source_text:
            requirements.append({"content": source_text[:1000], "priority": "normal", "kind": "technical"})
        with self.db.connect() as conn:
            conn.execute("DELETE FROM project_requirements WHERE project_id=?", (project_id,))
            for index, requirement in enumerate(requirements, 1):
                conn.execute(
                    "INSERT INTO project_requirements(project_id,requirement_key,kind,content,priority) VALUES (?,?,?,?,?)",
                    (project_id, f"REQ-{index:04d}", requirement["kind"], requirement["content"], requirement["priority"]),
                )
        return {"project_id": project_id, "requirements": self.get_project(project_id)["requirements"]}

    def build_outline(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        requirements = project["requirements"]
        with self.db.connect() as conn:
            conn.execute("DELETE FROM project_sections WHERE project_id=?", (project_id,))
            for order_no, title in enumerate(DEFAULT_OUTLINE, 1):
                ids = [item["id"] for item in requirements if self._requirement_matches(title, item["content"])]
                conn.execute(
                    "INSERT INTO project_sections(project_id,order_no,title,requirement_ids_json) VALUES (?,?,?,?)",
                    (project_id, order_no, title, json.dumps(ids)),
                )
        return {"project_id": project_id, "sections": self.get_project(project_id)["sections"]}

    def coverage_matrix(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        rows = []
        for requirement in project["requirements"]:
            matched = [
                {"section_id": section["id"], "title": section["title"]}
                for section in project["sections"]
                if requirement["id"] in section["requirement_ids"]
            ]
            rows.append({"requirement": requirement, "sections": matched, "covered": bool(matched)})
        return {
            "project_id": project_id,
            "items": rows,
            "covered": sum(1 for row in rows if row["covered"]),
            "total": len(rows),
            "unmapped_high": [row["requirement"]["id"] for row in rows if not row["covered"] and row["requirement"]["priority"] == "high"],
        }

    @staticmethod
    def _requirement_matches(title: str, content: str) -> bool:
        mappings = {
            "质量": ["质量", "验收"],
            "安全": ["安全", "文明", "环保"],
            "进度": ["进度", "工期"],
            "资源": ["资源", "人员", "机械", "材料"],
            "施工方案": ["施工", "工艺", "技术"],
            "重点难点": ["重点", "难点", "风险"],
            "平面": ["平面", "临建", "场地"],
        }
        for key, keywords in mappings.items():
            if key in title and any(keyword in content for keyword in keywords):
                return True
        return False

    def generate_section(self, project_id: int, section_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        section = next((item for item in project["sections"] if item["id"] == section_id), None)
        if not section:
            raise KeyError("章节不存在")
        requirement_map = {item["id"]: item for item in project["requirements"]}
        requirements = [requirement_map[value] for value in section["requirement_ids"] if value in requirement_map]
        query = " ".join([section["title"], *[item["content"] for item in requirements[:5]]])
        sources = self.knowledge.search(query, project.get("industry") or "", limit=8)
        if not sources:
            raise ValueError("已发布知识库没有匹配内容，章节生成已阻断")
        source_text = "\n\n".join(
            f"[知识{index}] {item['title']} / 发布v{item['publication_version']}\n{item['content'][:4000]}"
            for index, item in enumerate(sources, 1)
        )
        profile = project["profile"]
        retrieval_run_id = int(sources[0]["retrieval_run_id"]) if sources and sources[0].get("retrieval_run_id") else None
        generation_input_hash = content_hash(
            json.dumps(
                {
                    "project": {"id": project_id, "updated_at": project.get("updated_at"), "profile": profile},
                    "section": {"id": section_id, "title": section["title"]},
                    "requirements": requirements,
                    "knowledge": [item["content_hash"] for item in sources],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        generation_run_id = self.evidence.create_generation_run(
            project_id,
            section_id,
            generation_input_hash,
            str(self.llm.settings().get("model") or ""),
            SECTION_DRAFT_PROMPT.version,
            "evidence-2.0.0",
            retrieval_run_id,
            [
                {
                    "unit_id": item["unit_id"],
                    "publication_id": item["publication_id"],
                    "publication_version": item["publication_version"],
                    "content_hash": item["content_hash"],
                    "index_version": item.get("index_version", ""),
                }
                for item in sources
            ],
        )
        source_text = source_text[:28000]
        prompt = SECTION_DRAFT_PROMPT.render(
            project_name=project["name"],
            industry=project["industry"],
            profile=json.dumps(profile, ensure_ascii=False),
            section_title=section["title"],
            requirements=json.dumps(requirements, ensure_ascii=False),
            source_text=source_text,
        )
        result = self.ai_runtime.execute(
            SECTION_DRAFT_PROMPT,
            prompt,
            {
                "project": {"id": project_id, "name": project["name"], "industry": project["industry"], "profile": profile},
                "section": {"id": section_id, "title": section["title"]},
                "requirements": requirements,
                "sources": [
                    {
                        "publication_id": item["publication_id"],
                        "content_hash": item["content_hash"],
                        "content": item["content"][:4000],
                    }
                    for item in sources
                ],
            },
            task_type="section_draft",
            target_type="project_section",
            target_id=section_id,
            max_output_tokens=12000,
        )
        payload = result.get("payload")
        if payload:
            content = normalize_text(str(payload.get("content") or ""))
            confirmations = [
                normalize_text(str(item))
                for item in (payload.get("confirmations") if isinstance(payload.get("confirmations"), list) else [])
                if normalize_text(str(item))
            ]
            evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        else:
            content = self._fallback_section(project, section, requirements, sources)
            confirmations = ["大模型不可用，当前章节为基于已审核知识的结构化草稿，需人工复核"]
            evidence = [
                {"requirement_id": item["id"], "text": f"{item['requirement_key']}：{item['content']}"}
                for item in requirements
            ]
        content = content.replace("[项目名称]", project["name"])
        citations = [
            {
                "unit_id": item["unit_id"],
                "publication_id": item["publication_id"],
                "publication_version": item["publication_version"],
                "title": item["title"],
                "content_hash": item["content_hash"],
                "sources": item["sources"],
            }
            for item in sources
        ]
        draft_hash = content_hash(content)
        allowed_requirement_ids = {int(item["id"]) for item in requirements}
        with self.db.connect() as conn:
            version_no = int(conn.execute("SELECT COALESCE(MAX(version_no),0)+1 FROM project_drafts WHERE section_id=?", (section_id,)).fetchone()[0])
            cursor = conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,citations_json,confirmations_json,version_no,status,content_hash) VALUES (?,?,?,?,?,?,'draft',?)",
                (project_id, section_id, content, json.dumps(citations, ensure_ascii=False), json.dumps(confirmations, ensure_ascii=False), version_no, draft_hash),
            )
            draft_id = int(cursor.lastrowid)
            conn.execute("UPDATE project_sections SET status='drafted' WHERE id=?", (section_id,))
            for item in evidence:
                requirement_id = int(item.get("requirement_id") or 0)
                if requirement_id not in allowed_requirement_ids and 1 <= requirement_id <= len(requirements):
                    requirement_id = int(requirements[requirement_id - 1]["id"])
                if requirement_id not in allowed_requirement_ids:
                    continue
                text = normalize_text(str(item.get("text") or ""))
                coverage_score = 1.0 if text and text in content else 0.0
                conn.execute(
                    "INSERT INTO requirement_responses(requirement_id,draft_id,evidence_text,coverage_score,content_fingerprint) VALUES (?,?,?,?,?)",
                    (requirement_id, draft_id, text, coverage_score, draft_hash),
                )
        evidence_sources = [
            *sources,
            *[
                {
                    "title": item["requirement_key"],
                    "content": item["content"],
                    "content_hash": content_hash(item["content"]),
                    "sources": [{"page_start": item.get("source_page")}],
                }
                for item in requirements
            ],
        ]
        evidence_report = self.evidence.analyze_draft(generation_run_id, draft_id, content, evidence_sources)
        if evidence_report["unsupported_high"]:
            confirmations.extend(
                f"高风险表述缺少充分证据：{text[:160]}"
                for text in evidence_report["unsupported_high"]
            )
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE project_drafts SET confirmations_json=? WHERE id=?",
                    (json.dumps(confirmations, ensure_ascii=False), draft_id),
                )
        return {
            "draft_id": draft_id,
            "section_id": section_id,
            "version_no": version_no,
            "content": content,
            "citations": citations,
            "confirmations": confirmations,
            "model": result.get("model"),
            "ai_run_id": result.get("run_id"),
            "cached": bool(result.get("cached")),
            "error": result.get("error", ""),
            "generation_run_id": generation_run_id,
            "evidence": evidence_report,
            "claims": self.evidence.list_claims(draft_id),
        }

    def generate_all(self, project_id: int, progress=None, cancelled=None) -> dict[str, Any]:
        progress = progress or (lambda *_args, **_kwargs: None)
        cancelled = cancelled or (lambda: False)
        project = self.get_project(project_id)
        if not project["sections"]:
            raise ValueError("请先生成目录")
        matrix = self.coverage_matrix(project_id)
        if matrix["unmapped_high"]:
            raise ValueError(f"高优先级要求尚未映射章节: {matrix['unmapped_high']}")
        results: list[dict[str, Any]] = []
        for index, section in enumerate(project["sections"]):
            if cancelled():
                break
            progress("generating", int(index / len(project["sections"]) * 95), f"生成章节 {index + 1}/{len(project['sections'])}", {"section_id": section["id"]})
            try:
                results.append(self.generate_section(project_id, int(section["id"])))
            except Exception as exc:  # noqa: BLE001
                results.append({"section_id": section["id"], "section_title": section["title"], "error": f"{type(exc).__name__}: {exc}"})
        output = {
            "project_id": project_id,
            "generated": sum(1 for item in results if item.get("draft_id")),
            "failed": sum(1 for item in results if not item.get("draft_id")),
            "results": results,
        }
        progress("completed", 100, "批量章节生成完成", {"generated": output["generated"], "failed": output["failed"]})
        return output

    @staticmethod
    def _fallback_section(project: dict[str, Any], section: dict[str, Any], requirements: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
        parts = [f"# {section['title']}", f"本章结合{project['name']}的招标要求和已审核知识进行编制。"]
        if requirements:
            parts.append("## 条款响应")
            parts.extend(f"- {item['requirement_key']}：{item['content']}" for item in requirements)
        for source in sources[:5]:
            parts.append(f"## {source['title']}")
            parts.append(source["content"])
        return "\n\n".join(parts)

    def update_draft(self, draft_id: int, content: str) -> dict[str, Any]:
        normalized = normalize_text(content)
        updated_hash = content_hash(normalized)
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise KeyError("章节草稿不存在")
            current_hash = row["content_hash"] or content_hash(row["content"])
            if current_hash == updated_hash:
                return {"draft_id": draft_id, "status": row["status"], "changed": False, "quality_confirmations_invalidated": False}
            conn.execute(
                "UPDATE project_drafts SET content=?,content_hash=?,status='draft',evidence_status='pending',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (normalized, updated_hash, draft_id),
            )
            conn.execute("UPDATE project_sections SET status='drafted' WHERE id=?", (row["section_id"],))
            conn.execute("UPDATE requirement_responses SET review_status='invalidated' WHERE draft_id=?", (draft_id,))
            conn.execute("UPDATE claims SET support_status='invalidated',updated_at=CURRENT_TIMESTAMP WHERE draft_id=?", (draft_id,))
            conn.execute("UPDATE generation_runs SET status='invalidated' WHERE draft_id=?", (draft_id,))
            conn.execute("UPDATE delivery_manifests SET status='invalidated',invalidated_at=CURRENT_TIMESTAMP WHERE project_id=? AND invalidated_at IS NULL", (row["project_id"],))
        return {"draft_id": draft_id, "status": "draft", "changed": True, "quality_confirmations_invalidated": True}

    def confirm_draft(
        self,
        draft_id: int,
        reviewer: str,
        resolutions: list[dict[str, Any]] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        if not reviewer.strip():
            raise ValueError("确认人不能为空")
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise KeyError("章节草稿不存在")
            confirmations = parse_json(row["confirmations_json"], [])
            unsupported_high = int(
                conn.execute(
                    "SELECT COUNT(*) FROM claims WHERE draft_id=? AND risk_level='high' AND support_status='unsupported'",
                    (draft_id,),
                ).fetchone()[0]
            )
            if unsupported_high:
                raise ValueError(f"仍有{unsupported_high}条高风险Claim缺少证据，不能签审")
            target_hash = row["content_hash"] or content_hash(row["content"])
            supplied: dict[int, str] = {}
            for item in resolutions or []:
                index = int(item.get("index", -1))
                resolution = normalize_text(str(item.get("resolution") or ""))
                if index < 0 or index >= len(confirmations):
                    raise ValueError("待确认项序号无效")
                if not resolution:
                    raise ValueError(f"第{index + 1}项待确认事项缺少处理结论")
                if index in supplied:
                    raise ValueError(f"第{index + 1}项待确认事项重复提交")
                supplied[index] = resolution
            missing = [index + 1 for index in range(len(confirmations)) if index not in supplied]
            if missing:
                raise ValueError(f"待确认事项必须逐项处理：缺少第{','.join(map(str, missing))}项")
            conn.execute("UPDATE project_drafts SET content_hash=? WHERE id=?", (target_hash, draft_id))
            for index, confirmation in enumerate(confirmations):
                conn.execute(
                    """
                    INSERT INTO confirmation_resolutions(
                        draft_id,confirmation_index,confirmation_text,resolution,resolver,target_hash
                    ) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(draft_id,confirmation_index,target_hash) DO UPDATE SET
                        confirmation_text=excluded.confirmation_text,
                        resolution=excluded.resolution,
                        resolver=excluded.resolver,
                        created_at=CURRENT_TIMESTAMP
                    """,
                    (draft_id, index, str(confirmation), supplied[index], reviewer.strip(), target_hash),
                )
            conn.execute(
                "INSERT INTO draft_review_decisions(draft_id,reviewer,target_hash,decision,notes) VALUES (?,?,?,'approved',?)",
                (draft_id, reviewer.strip(), target_hash, normalize_text(notes)),
            )
            conn.execute(
                "UPDATE project_drafts SET status='reviewed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft_id,),
            )
            conn.execute("UPDATE project_sections SET status='reviewed' WHERE id=?", (row["section_id"],))
            conn.execute("UPDATE requirement_responses SET review_status='invalidated' WHERE draft_id=?", (draft_id,))
            conn.execute(
                """
                UPDATE requirement_responses SET review_status='confirmed'
                WHERE draft_id=? AND content_fingerprint=? AND coverage_score>=0.8
                    AND TRIM(COALESCE(evidence_text,''))<>''
                """,
                (draft_id, target_hash),
            )
        return {
            "draft_id": draft_id,
            "status": "reviewed",
            "reviewer": reviewer.strip(),
            "target_hash": target_hash,
            "resolved_confirmations": len(confirmations),
        }

    def quality_gate(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        sections = project["sections"]
        drafts = [item["draft"] for item in sections if item.get("draft")]
        text = "\n".join(item["content"] for item in drafts)
        blockers: list[dict[str, str]] = []
        if len(drafts) < len(sections):
            blockers.append({"key": "missing_sections", "title": "章节未全部生成", "detail": f"{len(drafts)}/{len(sections)}章已有草稿"})
        confirmation_count = 0
        unreviewed_drafts = 0
        with self.db.connect() as conn:
            for draft in drafts:
                target_hash = draft["content_hash"]
                resolved = {
                    int(row[0])
                    for row in conn.execute(
                        "SELECT confirmation_index FROM confirmation_resolutions WHERE draft_id=? AND target_hash=?",
                        (draft["id"], target_hash),
                    )
                }
                confirmation_count += sum(1 for index, _ in enumerate(draft.get("confirmations") or []) if index not in resolved)
                reviewed = conn.execute(
                    "SELECT 1 FROM draft_review_decisions WHERE draft_id=? AND target_hash=? AND decision='approved' LIMIT 1",
                    (draft["id"], target_hash),
                ).fetchone()
                if not reviewed:
                    unreviewed_drafts += 1
        if confirmation_count:
            blockers.append({"key": "confirmations", "title": "存在待确认事项", "detail": f"共{confirmation_count}项"})
        if unreviewed_drafts:
            blockers.append({"key": "unreviewed_drafts", "title": "章节尚未绑定当前版本签审", "detail": f"共{unreviewed_drafts}章"})
        invalid_citations = 0
        with self.db.connect() as conn:
            for draft in drafts:
                for citation in draft.get("citations") or []:
                    valid = conn.execute(
                        "SELECT 1 FROM knowledge_publications WHERE id=? AND status='published' AND content_hash=?",
                        (citation.get("publication_id"), citation.get("content_hash")),
                    ).fetchone()
                    if not valid:
                        invalid_citations += 1
        if invalid_citations:
            blockers.append({"key": "invalid_citations", "title": "引用已失效", "detail": f"共{invalid_citations}项"})
        evidence_metrics = self.evidence.metrics(project_id)
        if evidence_metrics["high_unsupported"]:
            blockers.append({"key": "unsupported_high_claims", "title": "高风险表述缺少证据", "detail": f"共{evidence_metrics['high_unsupported']}项"})
        placeholders = re.findall(r"\[(?:项目名称|联系电话|待确认[^\]]*)\]|<[^>]+>|TODO", text, flags=re.IGNORECASE)
        if placeholders:
            blockers.append({"key": "placeholders", "title": "存在占位符", "detail": f"共{len(placeholders)}处"})
        coverage_total = len(project["requirements"])
        with self.db.connect() as conn:
            covered = int(conn.execute(
                """
                SELECT COUNT(DISTINCT rr.requirement_id) FROM requirement_responses rr
                JOIN project_requirements r ON r.id=rr.requirement_id
                JOIN project_drafts d ON d.id=rr.draft_id
                WHERE r.project_id=?
                    AND rr.coverage_score>=0.8
                    AND rr.review_status='confirmed'
                    AND rr.content_fingerprint=d.content_hash
                    AND TRIM(COALESCE(rr.evidence_text,''))<>''
                    AND NOT EXISTS (
                        SELECT 1 FROM project_drafts newer
                        WHERE newer.section_id=d.section_id AND newer.version_no>d.version_no
                    )
                    AND EXISTS (
                        SELECT 1 FROM draft_review_decisions rd
                        WHERE rd.draft_id=d.id AND rd.target_hash=d.content_hash AND rd.decision='approved'
                    )
                """,
                (project_id,),
            ).fetchone()[0])
        coverage = round(covered / coverage_total * 100, 2) if coverage_total else 100.0
        if coverage < 95:
            blockers.append({"key": "coverage", "title": "条款证据覆盖不足", "detail": f"当前{coverage}%"})
        consistency_issues = self._consistency_issues(project)
        warnings = [item for item in consistency_issues if item["key"] == "duplicate_sections"]
        blockers.extend(item for item in consistency_issues if item["key"] != "duplicate_sections")
        score = max(0, 100 - len(blockers) * 12)
        report = {
            "project_id": project_id,
            "ready": not blockers and score >= 90,
            "score": score,
            "blockers": blockers,
            "warnings": warnings,
            "metrics": {
                "sections": len(sections),
                "drafts": len(drafts),
                "requirements": coverage_total,
                "covered_requirements": covered,
                "coverage": coverage,
                "confirmations": confirmation_count,
                "unreviewed_drafts": unreviewed_drafts,
                "invalid_citations": invalid_citations,
                "claims": evidence_metrics,
            },
        }
        self._sync_quality_issues(project_id, [*blockers, *warnings])
        return report

    @staticmethod
    def _consistency_issues(project: dict[str, Any]) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        drafts = [section["draft"] for section in project["sections"] if section.get("draft")]
        combined = "\n".join(draft["content"] for draft in drafts)
        label_patterns = {
            "工期": r"工期.{0,12}?(\d+\s*(?:天|日历天))",
            "质量目标": r"质量目标.{0,12}?([^，。；\n]{2,20})",
            "安全目标": r"安全目标.{0,12}?([^，。；\n]{2,20})",
        }
        for label, pattern in label_patterns.items():
            values = {normalize_text(value) for value in re.findall(pattern, combined, flags=re.IGNORECASE)}
            if len(values) > 1:
                issues.append({"key": f"conflict_{label}", "title": f"{label}存在冲突", "detail": "、".join(sorted(values))[:300]})
        normalized = [set(re.findall(r"[\u4e00-\u9fff]{2,4}", draft["content"])) for draft in drafts]
        for left in range(len(normalized)):
            for right in range(left + 1, len(normalized)):
                union = normalized[left] | normalized[right]
                similarity = len(normalized[left] & normalized[right]) / len(union) if union else 0
                if similarity >= 0.92:
                    issues.append({"key": "duplicate_sections", "title": "章节内容高度重复", "detail": f"第{left + 1}章与第{right + 1}章相似度{similarity:.0%}"})
        return issues

    def _sync_quality_issues(self, project_id: int, blockers: list[dict[str, str]]) -> None:
        active_fingerprints: set[str] = set()
        with self.db.connect() as conn:
            for blocker in blockers:
                fingerprint = content_hash(f"{project_id}|{blocker['key']}|{blocker['detail']}")
                active_fingerprints.add(fingerprint)
                exists = conn.execute(
                    "SELECT id FROM quality_issues WHERE project_id=? AND fingerprint=? AND status='open'",
                    (project_id, fingerprint),
                ).fetchone()
                if not exists:
                    severity = "high" if blocker["key"] in {"unsupported_high_claims", "invalid_citations", "missing_sections", "coverage"} or blocker["key"].startswith("conflict_") else "medium"
                    conn.execute(
                        """
                        INSERT INTO quality_issues(project_id,issue_code,severity,source,message,fingerprint)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (project_id, blocker["key"], severity, "quality_gate", f"{blocker['title']}：{blocker['detail']}", fingerprint),
                    )
            open_rows = conn.execute("SELECT id,fingerprint FROM quality_issues WHERE project_id=? AND source='quality_gate' AND status='open'", (project_id,)).fetchall()
            for row in open_rows:
                if row["fingerprint"] not in active_fingerprints:
                    conn.execute(
                        "UPDATE quality_issues SET status='resolved',resolution='后续质量检查已不再复现',resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                        (row["id"],),
                    )

    def resolve_quality_issue(self, issue_id: int, resolution: str, user_id: int | None = None) -> dict[str, Any]:
        issue = self.db.row("SELECT * FROM quality_issues WHERE id=?", (issue_id,))
        if not issue:
            raise KeyError("质量问题不存在")
        if not normalize_text(resolution):
            raise ValueError("处理结论不能为空")
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE quality_issues SET status='resolved',resolution=?,resolved_by=?,resolved_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (normalize_text(resolution), user_id, issue_id),
            )
        self.audit.record("quality.resolve", "quality_issue", issue_id, actor_user_id=user_id, details={"project_id": issue["project_id"]})
        return self.db.row("SELECT * FROM quality_issues WHERE id=?", (issue_id,)) or {}

    def list_manifests(self, project_id: int) -> list[dict[str, Any]]:
        rows = self.db.rows("SELECT * FROM delivery_manifests WHERE project_id=? ORDER BY id DESC", (project_id,))
        for row in rows:
            row["manifest"] = parse_json(row.pop("manifest_json", "{}"), {})
        return rows

    def export_project(self, project_id: int, file_format: str, progress=None) -> dict[str, Any]:
        progress = progress or (lambda *_args, **_kwargs: None)
        project = self.get_project(project_id)
        quality = self.quality_gate(project_id)
        if not quality["ready"]:
            raise ValueError("质量门禁未通过，不能正式导出")
        safe_name = re.sub(r"[\\/:*?\"<>|]", "_", project["name"])
        progress("rendering", 20, "生成交付文件")
        files: list[Path] = []
        if file_format == "markdown":
            path = self.settings.export_root / f"{safe_name}_{project_id}.md"
            content = self._project_markdown(project)
            write_text_atomic(path, content)
            files.append(path)
        elif file_format == "docx":
            path = self.settings.export_root / f"{safe_name}_{project_id}.docx"
            self._write_docx(project, path)
            self._preflight_docx(path)
            files.append(path)
        elif file_format in {"pdf", "package"}:
            docx_path = self.settings.export_root / f"{safe_name}_{project_id}.docx"
            self._write_docx(project, docx_path)
            self._preflight_docx(docx_path)
            pdf_path = self._convert_pdf(docx_path)
            self._preflight_pdf(pdf_path)
            files.extend([docx_path, pdf_path])
            path = pdf_path
        else:
            raise ValueError("仅支持markdown、docx、pdf或package")
        project_hash = self._project_hash(project)
        file_items = [
            {"name": item.name, "size_bytes": item.stat().st_size, "sha256": hashlib.sha256(item.read_bytes()).hexdigest()}
            for item in files
        ]
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO deliveries(project_id,format,file_path,quality_json) VALUES (?,?,?,?)",
                (project_id, file_format, str(path), json.dumps(quality, ensure_ascii=False)),
            )
            delivery_id = int(cursor.lastrowid)
        manifest = {
            "schema_version": "1.0",
            "project_id": project_id,
            "project_name": project["name"],
            "project_hash": project_hash,
            "quality": quality,
            "files": file_items,
            "drafts": [
                {"draft_id": section["draft"]["id"], "content_hash": section["draft"]["content_hash"], "evidence_status": section["draft"].get("evidence_status")}
                for section in project["sections"] if section.get("draft")
            ],
            "knowledge": sorted(
                {
                    (citation["publication_id"], citation["publication_version"], citation["content_hash"])
                    for section in project["sections"] if section.get("draft")
                    for citation in section["draft"].get("citations") or []
                }
            ),
        }
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
        manifest_hash = content_hash(manifest_json)
        manifest_path = self.settings.export_root / f"{safe_name}_{project_id}_manifest.json"
        write_text_atomic(manifest_path, manifest_json)
        files.append(manifest_path)
        if file_format == "package":
            package_path = self.settings.export_root / f"{safe_name}_{project_id}_delivery.zip"
            with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in files:
                    archive.write(item, item.name)
                archive.writestr("质量门禁报告.json", json.dumps(quality, ensure_ascii=False, indent=2))
                archive.writestr("要求覆盖矩阵.json", json.dumps(self.coverage_matrix(project_id), ensure_ascii=False, indent=2))
                archive.writestr("证据审计.json", json.dumps({section["title"]: section["draft"].get("claims", []) for section in project["sections"] if section.get("draft")}, ensure_ascii=False, indent=2))
            path = package_path
            file_items.append({"name": package_path.name, "size_bytes": package_path.stat().st_size, "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest()})
        stored = []
        for item in files + ([path] if path not in files else []):
            stored.append(self.storage.put_file(f"deliveries/{project_id}/{manifest_hash[:12]}/{item.name}", item))
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO delivery_manifests(project_id,delivery_id,project_hash,manifest_json,manifest_hash)
                VALUES (?,?,?,?,?)
                """,
                (project_id, delivery_id, project_hash, manifest_json, manifest_hash),
            )
            manifest_id = int(cursor.lastrowid)
        self.audit.record("delivery.freeze", "project", project_id, details={"delivery_id": delivery_id, "manifest_id": manifest_id, "manifest_hash": manifest_hash})
        progress("completed", 100, "交付包已冻结", {"manifest_hash": manifest_hash})
        return {
            "project_id": project_id,
            "delivery_id": delivery_id,
            "manifest_id": manifest_id,
            "manifest_hash": manifest_hash,
            "format": file_format,
            "file_path": str(path),
            "object_key": stored[-1]["object_key"] if stored else "",
            "files": file_items,
            "quality": quality,
        }

    @staticmethod
    def _project_hash(project: dict[str, Any]) -> str:
        return content_hash(
            json.dumps(
                {
                    "id": project["id"],
                    "updated_at": project.get("updated_at"),
                    "requirements": [(item["id"], item["content"], item["kind"]) for item in project["requirements"]],
                    "drafts": [(section["draft"]["id"], section["draft"]["content_hash"]) for section in project["sections"] if section.get("draft")],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    @staticmethod
    def _preflight_docx(path: Path) -> dict[str, Any]:
        document = Document(path)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        issues = []
        if not text.strip():
            issues.append("文档正文为空")
        if re.search(r"\[(?:项目名称|待确认[^\]]*)\]|TODO", text, flags=re.IGNORECASE):
            issues.append("文档包含未处理占位符")
        if not document.sections:
            issues.append("文档缺少页面设置")
        if issues:
            raise ValueError("DOCX预检失败：" + "；".join(issues))
        return {"paragraphs": len(document.paragraphs), "tables": len(document.tables), "size_bytes": path.stat().st_size}

    @staticmethod
    def _convert_pdf(docx_path: Path) -> Path:
        executable = shutil.which("libreoffice") or shutil.which("soffice")
        if not executable:
            windows_soffice = Path("C:/Program Files/LibreOffice/program/soffice.exe")
            if windows_soffice.exists():
                executable = str(windows_soffice)
        if not executable:
            raise ValueError("未安装LibreOffice，无法生成和预检PDF")
        result = subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        pdf_path = docx_path.with_suffix(".pdf")
        if result.returncode or not pdf_path.exists():
            raise ValueError("LibreOffice生成PDF失败")
        return pdf_path

    @staticmethod
    def _preflight_pdf(path: Path) -> dict[str, Any]:
        from pypdf import PdfReader

        reader = PdfReader(path)
        if not reader.pages:
            raise ValueError("PDF预检失败：没有页面")
        blank_pages = [index + 1 for index, page in enumerate(reader.pages) if not (page.extract_text() or "").strip()]
        if blank_pages:
            raise ValueError(f"PDF预检失败：发现空白页{blank_pages[:10]}")
        return {"pages": len(reader.pages), "size_bytes": path.stat().st_size}

    @staticmethod
    def _project_markdown(project: dict[str, Any]) -> str:
        parts = [f"# {project['name']}"]
        for section in project["sections"]:
            if section.get("draft"):
                parts.append(section["draft"]["content"])
        return "\n\n".join(parts)

    def _write_docx(self, project: dict[str, Any], path: Path) -> None:
        document = Document()
        section = document.sections[0]
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.8)
        section.right_margin = Cm(2.5)
        normal = document.styles["Normal"]
        normal.font.name = "宋体"
        normal.font.size = Pt(12)
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        title = document.add_heading(project["name"], level=0)
        title.alignment = 1
        subtitle = document.add_paragraph("技术标")
        subtitle.alignment = 1
        document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        toc_title = document.add_heading("目录", level=1)
        toc_title.alignment = 0
        toc = document.add_paragraph()
        run = toc.add_run()
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), 'TOC \\o "1-3" \\h \\z \\u')
        run._r.addnext(field)
        document.add_page_break()
        for section_index, item in enumerate(project["sections"], 1):
            draft = item.get("draft")
            if not draft:
                continue
            if section_index > 1:
                document.add_page_break()
            document.add_heading(item["title"], level=1)
            self._append_markdown(document, draft["content"], item["title"])
        footer = document.sections[0].footer.paragraphs[0]
        footer.alignment = 1
        footer.add_run(f"{project['name']}  |  ")
        page_field = OxmlElement("w:fldSimple")
        page_field.set(qn("w:instr"), "PAGE")
        footer._p.append(page_field)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)

    def _append_markdown(self, document: Document, markdown: str, section_title: str) -> None:
        lines = markdown.splitlines()
        index = 0
        first_heading_skipped = False
        while index < len(lines):
            line = lines[index].strip()
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                title = heading.group(2).strip()
                if not first_heading_skipped and title == section_title:
                    first_heading_skipped = True
                else:
                    document.add_heading(title, level=min(len(heading.group(1)) + 1, 9))
                index += 1
                continue
            image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line)
            if image:
                image_path = Path(image.group(2).strip())
                if image_path.exists() and image_path.is_file():
                    paragraph = document.add_paragraph()
                    paragraph.alignment = 1
                    paragraph.add_run().add_picture(str(image_path), width=Cm(15.5))
                    caption = document.add_paragraph(f"图 {image.group(1).strip() or '施工技术示意图'}")
                    caption.alignment = 1
                index += 1
                continue
            if self._is_table_start(lines, index):
                index = self._append_markdown_table(document, lines, index)
                continue
            if line.startswith("- ") or line.startswith("* "):
                document.add_paragraph(line[2:].strip(), style="List Bullet")
            elif re.match(r"^\d+[.、]\s*", line):
                text = re.sub(r"^\d+[.、]\s*", "", line)
                document.add_paragraph(text, style="List Number")
            elif line in {"---pagebreak---", "<!-- pagebreak -->"}:
                document.add_page_break()
            elif line and not line.startswith("<!--"):
                paragraph = document.add_paragraph(line)
                paragraph.paragraph_format.first_line_indent = Cm(0.74)
                paragraph.paragraph_format.line_spacing = 1.5
                paragraph.paragraph_format.space_after = Pt(3)
            index += 1

    @staticmethod
    def _is_table_start(lines: list[str], index: int) -> bool:
        separator_index = index + 1
        while separator_index < len(lines) and not lines[separator_index].strip():
            separator_index += 1
        if separator_index >= len(lines):
            return False
        current = lines[index].strip()
        separator = lines[separator_index].strip()
        return current.startswith("|") and current.endswith("|") and bool(re.match(r"^\|[\s:|-]+\|$", separator))

    @staticmethod
    def _table_cells(line: str) -> list[str]:
        return [value.strip().replace("\\|", "|") for value in line.strip().strip("|").split("|")]

    def _append_markdown_table(self, document: Document, lines: list[str], index: int) -> int:
        headers = self._table_cells(lines[index])
        rows: list[list[str]] = []
        separator_index = index + 1
        while separator_index < len(lines) and not lines[separator_index].strip():
            separator_index += 1
        cursor = separator_index + 1
        while cursor < len(lines):
            line = lines[cursor].strip()
            if not line:
                next_index = cursor + 1
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                if next_index < len(lines) and lines[next_index].strip().startswith("|"):
                    cursor = next_index
                    line = lines[cursor].strip()
                else:
                    break
            if not (line.startswith("|") and line.endswith("|")):
                break
            rows.append(self._table_cells(line))
            cursor += 1
        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        header_row = table.rows[0]
        header_properties = header_row._tr.get_or_add_trPr()
        header_properties.append(OxmlElement("w:tblHeader"))
        for cell_index, value in enumerate(headers):
            cell = header_row.cells[cell_index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = value
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "DDEBE8")
            cell._tc.get_or_add_tcPr().append(shading)
            for run in cell.paragraphs[0].runs:
                run.bold = True
                run.font.size = Pt(9)
        for values in rows:
            row = table.add_row()
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            for cell_index, cell in enumerate(row.cells):
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                cell.text = values[cell_index] if cell_index < len(values) else ""
                for run in cell.paragraphs[0].runs:
                    run.font.size = Pt(8.5)
        document.add_paragraph()
        return cursor
