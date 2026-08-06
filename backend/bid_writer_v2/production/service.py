from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..database import Database
from ..knowledge.service import KnowledgeService
from ..llm import LlmClient
from ..settings import Settings
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
    def __init__(self, db: Database, settings: Settings, knowledge: KnowledgeService, llm: LlmClient | None = None) -> None:
        self.db = db
        self.settings = settings
        self.knowledge = knowledge
        self.llm = llm or LlmClient()

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
            item["sections"] = sections
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
        return self.get_project(project_id)

    def parse_requirements(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        source_text = normalize_text(project.get("source_text") or "")
        candidates = [line.strip(" -\t") for line in source_text.splitlines() if len(line.strip()) >= 8]
        requirements: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line in candidates:
            if line in seen:
                continue
            if not any(keyword in line for keyword in ["应", "须", "不得", "评分", "要求", "工期", "质量", "安全", "施工", "技术"]):
                continue
            seen.add(line)
            priority = "high" if any(keyword in line for keyword in ["评分", "必须", "不得", "废标", "否决"]) else "normal"
            kind = "compliance" if any(keyword in line for keyword in ["不得", "废标", "否决", "承诺"]) else "technical"
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
        prompt = (
            "请根据项目事实、条款和已审核知识编制技术标章节。不得编造人员数量、设备型号、工程参数和承诺。"
            "缺失参数写入confirmations。输出JSON："
            '{"content":"Markdown正文","evidence":[{"requirement_id":1,"text":"正文证据"}],'
            '"confirmations":["待确认事项"],"visual_suggestions":["图表建议"]}。\n\n'
            f"项目：{project['name']}\n行业：{project['industry']}\n参数：{json.dumps(profile, ensure_ascii=False)}\n"
            f"章节：{section['title']}\n条款：{json.dumps(requirements, ensure_ascii=False)}\n\n已审核知识：\n{source_text[:28000]}"
        )
        result = self.llm.generate("你是建设工程技术标编制专家。正文必须逐条响应要求并保留知识来源，不得复制旧项目事实。", prompt, 12000)
        payload = self.llm.json_payload(result.get("content", "")) if result.get("content") else None
        if payload:
            content = normalize_text(str(payload.get("content") or ""))
            confirmations = payload.get("confirmations") if isinstance(payload.get("confirmations"), list) else []
            evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        else:
            content = self._fallback_section(project, section, requirements, sources)
            confirmations = ["大模型不可用，当前章节为基于已审核知识的结构化草稿，需人工复核"]
            evidence = [
                {"requirement_id": item["id"], "text": f"本章条款响应：{item['content']}"}
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
        with self.db.connect() as conn:
            version_no = int(conn.execute("SELECT COALESCE(MAX(version_no),0)+1 FROM project_drafts WHERE section_id=?", (section_id,)).fetchone()[0])
            cursor = conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,citations_json,confirmations_json,version_no,status) VALUES (?,?,?,?,?,?,'draft')",
                (project_id, section_id, content, json.dumps(citations, ensure_ascii=False), json.dumps(confirmations, ensure_ascii=False), version_no),
            )
            draft_id = int(cursor.lastrowid)
            conn.execute("UPDATE project_sections SET status='drafted' WHERE id=?", (section_id,))
            for item in evidence:
                requirement_id = int(item.get("requirement_id") or 0)
                if requirement_id not in requirement_map and 1 <= requirement_id <= len(requirements):
                    requirement_id = int(requirements[requirement_id - 1]["id"])
                if requirement_id not in requirement_map:
                    continue
                text = str(item.get("text") or "")
                conn.execute(
                    "INSERT INTO requirement_responses(requirement_id,draft_id,evidence_text,coverage_score,content_fingerprint) VALUES (?,?,?,?,?)",
                    (requirement_id, draft_id, text, 1.0 if text else 0.0, content_hash(content)),
                )
        return {"draft_id": draft_id, "section_id": section_id, "version_no": version_no, "content": content, "citations": citations, "confirmations": confirmations, "model": result.get("model"), "error": result.get("error", "")}

    def generate_all(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project["sections"]:
            raise ValueError("请先生成目录")
        results: list[dict[str, Any]] = []
        for section in project["sections"]:
            try:
                results.append(self.generate_section(project_id, int(section["id"])))
            except Exception as exc:  # noqa: BLE001
                results.append({"section_id": section["id"], "section_title": section["title"], "error": f"{type(exc).__name__}: {exc}"})
        return {
            "project_id": project_id,
            "generated": sum(1 for item in results if item.get("draft_id")),
            "failed": sum(1 for item in results if not item.get("draft_id")),
            "results": results,
        }

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
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise KeyError("章节草稿不存在")
            conn.execute("UPDATE project_drafts SET content=?,status='draft',updated_at=CURRENT_TIMESTAMP WHERE id=?", (normalize_text(content), draft_id))
            conn.execute("UPDATE requirement_responses SET review_status='invalidated' WHERE draft_id=?", (draft_id,))
        return {"draft_id": draft_id, "status": "draft", "quality_confirmations_invalidated": True}

    def confirm_draft(self, draft_id: int, reviewer: str) -> dict[str, Any]:
        if not reviewer.strip():
            raise ValueError("确认人不能为空")
        with self.db.connect() as conn:
            row = conn.execute("SELECT id FROM project_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise KeyError("章节草稿不存在")
            conn.execute(
                "UPDATE project_drafts SET confirmations_json='[]',status='reviewed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (draft_id,),
            )
            conn.execute(
                "UPDATE requirement_responses SET review_status='confirmed' WHERE draft_id=?",
                (draft_id,),
            )
        return {"draft_id": draft_id, "status": "reviewed", "reviewer": reviewer.strip()}

    def quality_gate(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        sections = project["sections"]
        drafts = [item["draft"] for item in sections if item.get("draft")]
        text = "\n".join(item["content"] for item in drafts)
        blockers: list[dict[str, str]] = []
        if len(drafts) < len(sections):
            blockers.append({"key": "missing_sections", "title": "章节未全部生成", "detail": f"{len(drafts)}/{len(sections)}章已有草稿"})
        confirmation_count = sum(len(item.get("confirmations") or []) for item in drafts)
        if confirmation_count:
            blockers.append({"key": "confirmations", "title": "存在待确认事项", "detail": f"共{confirmation_count}项"})
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
        placeholders = re.findall(r"\[(?:项目名称|联系电话|待确认[^\]]*)\]|<[^>]+>|TODO", text, flags=re.IGNORECASE)
        if placeholders:
            blockers.append({"key": "placeholders", "title": "存在占位符", "detail": f"共{len(placeholders)}处"})
        coverage_total = len(project["requirements"])
        with self.db.connect() as conn:
            covered = int(conn.execute(
                """
                SELECT COUNT(DISTINCT rr.requirement_id) FROM requirement_responses rr
                JOIN project_requirements r ON r.id=rr.requirement_id WHERE r.project_id=? AND rr.coverage_score>=0.8
                """,
                (project_id,),
            ).fetchone()[0])
        coverage = round(covered / coverage_total * 100, 2) if coverage_total else 100.0
        if coverage < 95:
            blockers.append({"key": "coverage", "title": "条款证据覆盖不足", "detail": f"当前{coverage}%"})
        score = max(0, 100 - len(blockers) * 12)
        return {
            "project_id": project_id,
            "ready": not blockers and score >= 90,
            "score": score,
            "blockers": blockers,
            "metrics": {
                "sections": len(sections),
                "drafts": len(drafts),
                "requirements": coverage_total,
                "covered_requirements": covered,
                "coverage": coverage,
                "confirmations": confirmation_count,
                "invalid_citations": invalid_citations,
            },
        }

    def export_project(self, project_id: int, file_format: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        quality = self.quality_gate(project_id)
        if not quality["ready"]:
            raise ValueError("质量门禁未通过，不能正式导出")
        safe_name = re.sub(r"[\\/:*?\"<>|]", "_", project["name"])
        if file_format == "markdown":
            path = self.settings.export_root / f"{safe_name}_{project_id}.md"
            content = self._project_markdown(project)
            write_text_atomic(path, content)
        elif file_format == "docx":
            path = self.settings.export_root / f"{safe_name}_{project_id}.docx"
            self._write_docx(project, path)
        else:
            raise ValueError("仅支持markdown或docx")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO deliveries(project_id,format,file_path,quality_json) VALUES (?,?,?,?)",
                (project_id, file_format, str(path), json.dumps(quality, ensure_ascii=False)),
            )
        return {"project_id": project_id, "format": file_format, "file_path": str(path), "quality": quality}

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

    def parse_requirements(self, project_id: int) -> dict[str, Any]:
        project = self.get_project(project_id)
        source_text = normalize_text(project.get("source_text") or "")
        candidates = [line.strip(" -\t") for line in source_text.splitlines() if len(line.strip()) >= 8]
        requirements: list[dict[str, Any]] = []
        seen: set[str] = set()
        keywords = ["项目", "工程", "不得", "评分", "要求", "工期", "质量", "安全", "施工", "技术", "方案", "响应"]
        high_keywords = ["评分", "必须", "不得", "废标", "否决", "强制"]
        compliance_keywords = ["不得", "废标", "否决", "承诺", "资质"]
        for line in candidates:
            if line in seen or not any(keyword in line for keyword in keywords):
                continue
            seen.add(line)
            priority = "high" if any(keyword in line for keyword in high_keywords) else "normal"
            kind = "compliance" if any(keyword in line for keyword in compliance_keywords) else "technical"
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
        outline = [
            "工程概况与编制依据", "施工总体部署", "施工准备与资源配置", "主要施工方案与技术措施",
            "工程重点难点分析及对策", "质量保证体系与措施", "安全文明施工与环境保护",
            "施工进度计划及保证措施", "施工总平面布置", "季节性施工与应急预案", "BIM及新技术应用",
        ]
        with self.db.connect() as conn:
            conn.execute("DELETE FROM project_sections WHERE project_id=?", (project_id,))
            for order_no, title in enumerate(outline, 1):
                ids = [item["id"] for item in requirements if self._requirement_matches_clean(title, item["content"])]
                conn.execute(
                    "INSERT INTO project_sections(project_id,order_no,title,requirement_ids_json) VALUES (?,?,?,?)",
                    (project_id, order_no, title, json.dumps(ids, ensure_ascii=False)),
                )
        return {"project_id": project_id, "sections": self.get_project(project_id)["sections"]}

    @staticmethod
    def _requirement_matches_clean(title: str, content: str) -> bool:
        mappings = {
            "质量": ["质量", "验收"], "安全": ["安全", "文明", "环保"], "进度": ["进度", "工期"],
            "资源": ["资源", "人员", "机械", "材料"], "施工方案": ["施工", "工艺", "技术", "方案"],
            "重点难点": ["重点", "难点", "风险"], "平面": ["平面", "临建", "场地"],
        }
        return any(key in title and any(word in content for word in words) for key, words in mappings.items())

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
