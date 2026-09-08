from __future__ import annotations

import json
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any

from ..utils import content_hash, normalize_text, parse_json
from .response_text import copies_requirement
from .generation_state import bind_response_to_generation, context_fingerprint, read_generation


CATEGORIES = {"technical", "qualification", "commercial", "contract", "reference", "unclassified"}
CHECKLIST_CATEGORIES = {"qualification", "commercial", "contract"}
RULE_VERSION = "requirements-scope-1.0.0"


def suggest_classification(requirement: dict[str, Any]) -> dict[str, Any]:
    """Give a conservative proposal; this never constitutes human approval."""
    text = normalize_text(str(requirement.get("content") or ""))
    kind = str(requirement.get("kind") or "")
    technical = re.search(
        r"水性漆|水性涂料|涂装|竣工资料|竣工文件|技术档案|施工方案|施工组织设计|施工工艺|技术措施|"
        r"质量(?:管理|体系|目标|措施)|安全(?:管理|防护|生产(?!许可证)|措施)|进度(?:计划|保证|管理)|"
        r"总平面|BIM|应急预案|劳动力计划|材料试验|混凝土|钢筋|基坑|防水|养护|保通措施",
        text, re.IGNORECASE,
    )
    heading = re.fullmatch(
        r"[\d.、（）()\s]*(?:评分办法前附表条款号\s*评审因素\s*评审标准|分值构成与评分标准|"
        r"(?:施工组织设计|技术标)?评分标准(?:[（(]总分\s*\d+\s*分[)）])?|评分因素|评审标准|标准分)", text,
    )
    evaluator = re.search(
        r"对评标委员会成员的纪律|对招标人的纪律|评标委员会成员不得|招标人不得泄漏|"
        r"评分分值计算保留|小数点后.*四舍五入|评标委员会.*(?:推荐中标候选人|进行打分|确定中标人)|"
        r"重新招标后投标人仍少于|评标委员会.*(?:算术平均|评分汇总|汇总评分)", text,
    )
    qualification = re.search(
        r"营业执照|安全生产许可证|投标人.*(?:资质|资格|证书|业绩|失信|信誉|撤销|投标有效期)|"
        r"单位负责人为同一人|控股、管理关系|联合体各方|不得参加.*投标|"
        r"投标人不得存在下列情形|被列入.*(?:失信|黑名单)|资质证书|资格审查|资格条件", text,
    )
    commercial = re.search(
        r"投标报价|招标控制价|拦标价|投标价格|清单偏差率|规费和税金|规费、税金|"
        r"竞争性费用|投标保证金|报价明细|计价表", text,
    )
    contract = re.search(
        r"不得.*(?:转让中标项目|再次分包)|禁止分包|分包前必须|违约金|违约责任|"
        r"进度款|预付款|合同价款|支付证书|结算|质保金|保修金|赔偿|"
        r"延期最长不得超过|发包人.*(?:取消、确认|改变设计变更)|连带责任", text,
    )
    if heading:
        category, reason = "reference", "原文为评分表标题或结构标签，建议保留为参考原文，须人工确认其适用范围"
    elif technical and (qualification or commercial or contract):
        category, reason = "unclassified", "原条款同时包含具体技术内容及资格、商务或合同条件，不能仅按关键词排除；请人工核对其主要响应清单"
    elif technical:
        category, matched = "technical", technical.group(0)
        reason = f"原条款包含具体技术响应内容“{matched}”，保留在技术章节范围"
    elif evaluator:
        category, reason = "reference", f"原条款描述招标人或评标机构程序“{evaluator.group(0)}”，建议进入参考清单，须人工确认"
    elif qualification:
        category, reason = "qualification", f"原条款涉及投标主体资格或投标行为“{qualification.group(0)}”，应单独提交资格响应及依据"
    elif commercial:
        category, reason = "commercial", f"原条款涉及报价或计价条件“{commercial.group(0)}”，应进入商务响应清单"
    elif contract:
        category, reason = "contract", f"原条款涉及合同履行责任“{contract.group(0)}”，应进入合同响应清单"
    elif kind in {"scoring", "veto"} or re.search(r"废标|否决|不得|严禁|必须", text):
        category, reason = "unclassified", "原条款含评分、否决或强制条件，适用专业尚不明确；保留技术规划范围并等待人工分类"
    elif re.search(r"工程|施工|工期|质量|安全|技术|机械|材料|人员|验收|图纸|现场", text):
        category, reason = "technical", "原条款涉及工程实施内容，暂按技术要求规划，最终分类仍须人工确认"
    else:
        category, reason = "unclassified", "现有明确规则无法确定适用清单，保留原条款并等待人工分类"
    return {"suggested_category": category, "suggestion_reason": reason,
            "suggestion_excerpt": text[:500], "source_page": requirement.get("source_page"), "rule_version": RULE_VERSION}


def requirement_hash(requirement: dict[str, Any]) -> str:
    return content_hash(json.dumps({key: requirement.get(key) for key in
        ("id", "project_id", "requirement_key", "kind", "content", "priority", "source_page")}, ensure_ascii=False, sort_keys=True))


class RequirementsWorkflow:
    def __init__(self, production) -> None:
        self.production = production
        self.db = production.db

    def enrich(self, project: dict[str, Any], conn=None) -> dict[str, Any]:
        source_hash = content_hash(str(project.get("source_text") or ""))
        with (nullcontext(conn) if conn is not None else self.db.connect()) as connection:
            records = {int(row["requirement_id"]): dict(row) for row in connection.execute(
                "SELECT * FROM requirement_classifications WHERE project_id=?", (project["id"],),
            ).fetchall()}
        for requirement in project.get("requirements", []):
            original_hash = requirement_hash(requirement)
            record = records.get(int(requirement["id"]), {})
            suggestion = suggest_classification(requirement)
            reviewed = bool(record.get("reviewer") and record.get("review_category"))
            fresh = reviewed and record.get("review_source_hash") == source_hash and record.get("review_requirement_hash") == original_hash
            status = "confirmed" if fresh else "stale" if reviewed else "pending"
            category = str(record.get("review_category") or "")
            response_status = "pending"
            if fresh and category in CHECKLIST_CATEGORIES:
                if record.get("applicability") == "not_applicable" and self._meaningful(record.get("basis_text"), 8):
                    response_status = "not_applicable"
                elif self._meaningful(record.get("response_text"), 8) and self._meaningful(record.get("basis_text"), 8):
                    response_status = "responded"
            section_ids = sorted(int(section["id"]) for section in project.get("sections", [])
                                 if requirement["id"] in section.get("requirement_ids", []))
            fingerprint = content_hash(json.dumps([source_hash, original_hash, int(record.get("revision") or 0), section_ids]))
            requirement.update({
                "requirement_fingerprint": fingerprint, "section_ids": section_ids,
                "planning_category": category if fresh else suggestion["suggested_category"],
                "formal_technical": not (fresh and category in (CHECKLIST_CATEGORIES | {"reference"})),
                "classification": {
                    **suggestion, "status": status, "category": category, "source_hash": source_hash,
                    "requirement_hash": original_hash, "revision": int(record.get("revision") or 0),
                    "reviewer": record.get("reviewer") or "", "review_reason": record.get("review_reason") or "",
                    "reviewed_at": record.get("reviewed_at"), "applicability": record.get("applicability") or "applicable",
                    "response_text": record.get("response_text") or "", "basis_text": record.get("basis_text") or "",
                    "response_status": response_status,
                },
            })
        project["requirements_workflow"] = self.metrics(project.get("requirements", []))
        return project

    @staticmethod
    def _meaningful(value: Any, minimum: int = 6) -> bool:
        text = normalize_text(str(value or ""))
        return len(text) >= minimum and text not in {"待补充", "待确认", "暂无依据", "默认符合", "全部符合要求", "全部满足要求"}

    @staticmethod
    def metrics(requirements: list[dict[str, Any]]) -> dict[str, Any]:
        # Clear technical proposals keep every clause in the technical
        # denominator and still require the ordinary chapter signoff. A separate
        # scope decision is required before excluding anything, and after any
        # previously reviewed source has changed.
        pending = [item["id"] for item in requirements if item["classification"]["status"] == "stale"
                   or (item["classification"]["status"] != "confirmed" and item["planning_category"] != "technical")]
        checklist_pending = [item["id"] for item in requirements if item["classification"]["status"] == "confirmed"
                             and item["classification"]["category"] in CHECKLIST_CATEGORIES
                             and item["classification"]["response_status"] == "pending"]
        planning = [item for item in requirements if item["planning_category"] in {"technical", "unclassified"}]
        formal = [item["id"] for item in requirements if item["formal_technical"]]
        blockers = []
        if pending:
            blockers.append({"key": "requirement_classification", "title": "条款分类尚未完成人工确认",
                             "detail": f"共{len(pending)}条分类待确认或来源已变化", "requirement_ids": pending})
        if checklist_pending:
            blockers.append({"key": "requirement_checklists", "title": "资格、商务或合同响应尚未完成",
                             "detail": f"共{len(checklist_pending)}条缺少实际响应或依据", "requirement_ids": checklist_pending})
        return {
            "total_requirements": len(requirements), "planning_technical_total": len(planning),
            "formal_technical_total": len(formal), "formal_technical_ids": formal,
            "planning_technical_ids": [item["id"] for item in planning],
            "classification_pending": len(pending), "classification_pending_ids": pending,
            "scope_pending": len(pending), "scope_pending_ids": pending,
            "classification_unreviewed": sum(item["classification"]["status"] != "confirmed" for item in requirements),
            "checklist_pending": len(checklist_pending), "checklist_pending_ids": checklist_pending,
            "mapped_technical": sum(bool(item["section_ids"]) for item in planning),
            "unmapped_high": [item["id"] for item in planning if item.get("priority") == "high" and not item["section_ids"]],
            "counts": {category: sum(item["planning_category"] == category for item in requirements) for category in sorted(CATEGORIES)},
            "blockers": blockers,
        }

    def snapshot(self, project_id: int) -> dict[str, Any]:
        project = self.enrich(self.production.get_project(project_id))
        return {"project_id": project_id, "project_hash": self.production._project_hash(project),
                "source_hash": content_hash(str(project.get("source_text") or "")), "items": project["requirements"],
                "metrics": project["requirements_workflow"], "blockers": project["requirements_workflow"]["blockers"]}

    def _locked_project(self, conn, project_id: int) -> dict[str, Any]:
        self.production._lock_project_for_update(conn, project_id)
        return self.enrich(self.production._get_project_from_connection(conn, project_id), conn)

    def _record(self, conn, requirement: dict[str, Any]) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM requirement_classifications WHERE requirement_id=? AND project_id=?",
                           (requirement["id"], requirement["project_id"])).fetchone()
        record = dict(row) if row else {
            "requirement_id": requirement["id"], "project_id": requirement["project_id"],
            "review_category": "", "review_source_hash": "", "review_requirement_hash": "", "reviewer": "",
            "review_reason": "", "reviewed_at": None, "applicability": "applicable", "response_text": "", "basis_text": "", "revision": 0,
        }
        classification = requirement["classification"]
        for field in ("source_hash", "requirement_hash", "suggested_category", "suggestion_reason", "suggestion_excerpt", "rule_version"):
            record[field] = classification[field]
        return record

    @staticmethod
    def _write_record(conn, record: dict[str, Any], actor: str, event_type: str, extra: dict[str, Any] | None = None) -> None:
        record["revision"] = int(record["revision"]) + 1
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        columns = tuple(record)
        assignments = ",".join(f"{column}=excluded.{column}" for column in columns if column != "requirement_id")
        conn.execute(
            f"INSERT INTO requirement_classifications({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            f"ON CONFLICT(requirement_id) DO UPDATE SET {assignments}", tuple(record[column] for column in columns),
        )
        conn.execute("INSERT INTO requirement_workflow_events(requirement_id,revision,project_id,event_type,actor,record_json) VALUES (?,?,?,?,?,?)",
                     (record["requirement_id"], record["revision"], record["project_id"], event_type, actor,
                      json.dumps({"record": record, **(extra or {})}, ensure_ascii=False, sort_keys=True)))

    def refresh_suggestions(self, project_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            project = self._locked_project(conn, project_id)
            for requirement in project["requirements"]:
                existing = conn.execute("SELECT * FROM requirement_classifications WHERE requirement_id=?", (requirement["id"],)).fetchone()
                record = self._record(conn, requirement)
                proposal_fields = ("source_hash", "requirement_hash", "suggested_category", "suggestion_reason", "suggestion_excerpt", "rule_version")
                if existing and all(existing[field] == record[field] for field in proposal_fields):
                    continue
                self._write_record(conn, record, "", "suggested")
        return self.snapshot(project_id)

    def review(self, project_id: int, reviewer: str, items: list[dict[str, Any]], expected_project_hash: str | None = None) -> dict[str, Any]:
        reviewer = normalize_text(reviewer)
        if not reviewer:
            raise ValueError("请填写实际分类复核人")
        if not items or len(items) > 1000:
            raise ValueError("每次须确认1至1000条要求")
        with self.db.connect() as conn:
            project = self._locked_project(conn, project_id)
            if expected_project_hash is not None and expected_project_hash != self.production._project_hash(project):
                raise ValueError("项目内容已变化，请刷新后重新确认分类")
            requirements = {item["id"]: item for item in project["requirements"]}
            validated = []
            seen = set()
            for incoming in items:
                requirement_id = int(incoming["requirement_id"])
                requirement = requirements.get(requirement_id)
                if not requirement:
                    raise KeyError("条款不属于当前项目")
                if requirement_id in seen:
                    raise ValueError("同一批次不能重复确认同一条款")
                seen.add(requirement_id)
                if incoming.get("expected_fingerprint") != requirement["requirement_fingerprint"]:
                    raise ValueError("条款来源、分类或章节映射已变化，请刷新后重新确认")
                category = str(incoming.get("category") or "")
                if category not in CATEGORIES - {"unclassified"}:
                    raise ValueError("请选择已明确的条款类别，待识别条款不能视为确认完成")
                reason = normalize_text(str(incoming.get("reason") or ""))
                if not self._meaningful(reason):
                    raise ValueError("请填写结合条款原文的分类理由，至少6个字")
                applicability = str(incoming.get("applicability") or "applicable")
                if applicability not in {"applicable", "not_applicable"}:
                    raise ValueError("适用性取值无效")
                response = normalize_text(str(incoming.get("response_text") or ""))
                basis = normalize_text(str(incoming.get("basis_text") or ""))
                if category == "technical" and applicability != "applicable":
                    raise ValueError("技术条款必须保留适用响应；需排除时请明确类别及原文理由")
                if category in CHECKLIST_CATEGORIES:
                    if applicability == "not_applicable" and not self._meaningful(basis, 8):
                        raise ValueError("非技术条款不适用也必须填写可核对的实际依据，至少8个字")
                    if applicability == "applicable" and (response or basis) and not (self._meaningful(response, 8) and self._meaningful(basis, 8)):
                        raise ValueError("请同时填写实际响应和可核对依据，各至少8个字；不能用默认符合代替")
                validated.append((requirement, category, reason, applicability, response, basis))
            affected = set()
            for requirement, category, reason, applicability, response, basis in validated:
                record = self._record(conn, requirement)
                record.update({"review_category": category, "review_source_hash": record["source_hash"],
                               "review_requirement_hash": record["requirement_hash"], "reviewer": reviewer, "review_reason": reason,
                               "reviewed_at": datetime.now(timezone.utc).isoformat(), "applicability": applicability,
                               "response_text": response, "basis_text": basis})
                self._write_record(conn, record, reviewer, "classified")
                affected.update(requirement["section_ids"])
                if category != "technical":
                    self._replace_mapping(conn, project, int(requirement["id"]), [])
            self.invalidate(conn, project_id, affected)
        return self.snapshot(project_id)

    def map_requirement(self, project_id: int, requirement_id: int, reviewer: str, expected_fingerprint: str, section_ids: list[int]) -> dict[str, Any]:
        reviewer = normalize_text(reviewer)
        if not reviewer:
            raise ValueError("请填写实际映射复核人")
        with self.db.connect() as conn:
            project = self._locked_project(conn, project_id)
            requirement = next((item for item in project["requirements"] if item["id"] == requirement_id), None)
            if not requirement:
                raise KeyError("条款不属于当前项目")
            if expected_fingerprint != requirement["requirement_fingerprint"]:
                raise ValueError("条款来源、分类或章节映射已变化，请刷新后重新映射")
            if requirement["planning_category"] not in {"technical", "unclassified"}:
                raise ValueError("仅技术范围条款可以映射章节；请先确认该条款的技术类别")
            selected = sorted(set(int(value) for value in section_ids))
            available = {int(section["id"]) for section in project["sections"]}
            if not set(selected) <= available:
                raise KeyError("目标章节不属于当前项目")
            if selected != requirement["section_ids"]:
                old = list(requirement["section_ids"])
                self._replace_mapping(conn, project, requirement_id, selected)
                self._write_record(conn, self._record(conn, requirement), reviewer, "mapped", {"previous_section_ids": old, "section_ids": selected})
                self.invalidate(conn, project_id, set(old) | set(selected))
        return self.snapshot(project_id)

    def bind_response(self, project_id: int, requirement_id: int, draft_id: int, reviewer: str,
                      target_hash: str, requirement_fingerprint: str, evidence_text: str) -> dict[str, Any]:
        reviewer = normalize_text(reviewer)
        quote = normalize_text(evidence_text)
        if not reviewer:
            raise ValueError("请填写实际响应复核人")
        if not 12 <= len(quote) <= 500:
            raise ValueError("正文证据片段须为12至500字的完整响应")
        with self.db.connect() as conn:
            project = self._locked_project(conn, project_id)
            requirement = next((item for item in project["requirements"] if item["id"] == requirement_id), None)
            if not requirement:
                raise KeyError("条款不属于当前项目")
            if requirement_fingerprint != requirement["requirement_fingerprint"]:
                raise ValueError("条款来源、分类或章节映射已变化，请刷新后重新绑定响应")
            if requirement["planning_category"] not in {"technical", "unclassified"}:
                raise ValueError("非技术清单应填写对应响应及依据，不能绑定技术正文代替")
            if copies_requirement(quote, requirement):
                raise ValueError("招标条款原文不能直接作为已完成的技术响应，请先补写实际方案或措施")
            section = next((item for item in project["sections"] if item.get("draft") and item["draft"]["id"] == draft_id), None)
            if section is None:
                if conn.execute("SELECT id FROM project_drafts WHERE id=? AND project_id=?", (draft_id, project_id)).fetchone():
                    raise ValueError("只能为当前最新章节草稿绑定响应，请刷新后重试")
                raise KeyError("草稿不属于当前项目")
            if section["id"] not in requirement["section_ids"]:
                raise ValueError("该条款尚未映射到当前草稿章节，请先确认章节映射")
            actual_hash = content_hash(section["draft"]["content"])
            if target_hash != actual_hash:
                raise ValueError("章节正文已变化，请查看当前正文后重新绑定响应")
            if quote not in normalize_text(section["draft"]["content"]):
                raise ValueError("证据片段未在当前章节正文中逐字找到，请先补写实际响应")
            # Public project drafts omit the full generation snapshot. Re-read
            # the original inside the same parent/draft lock before changing it.
            raw_draft = dict(conn.execute("SELECT * FROM project_drafts WHERE id=?", (draft_id,)).fetchone())
            recorded = read_generation(raw_draft)
            sources = recorded.get("sources") or []
            current_requirements = [item for rid in section["requirement_ids"] for item in project["requirements"] if item["id"] == rid]
            sources_current = True
            if recorded.get("parts"):
                try:
                    self.production._check_generation_sources(conn, sources, lock=True)
                except ValueError:
                    sources_current = False
            generation, confirmations, generation_binding = bind_response_to_generation(
                raw_draft, requirement_id, quote, reviewer,
                current_context_fingerprint=context_fingerprint(project, section, current_requirements, sources),
                sources_current=sources_current,
            )
            previous = [dict(row) for row in conn.execute("SELECT * FROM requirement_responses WHERE requirement_id=? AND draft_id=?", (requirement_id, draft_id)).fetchall()]
            self.invalidate(conn, project_id, [section["id"]])
            conn.execute("DELETE FROM requirement_responses WHERE requirement_id=? AND draft_id=?", (requirement_id, draft_id))
            conn.execute("INSERT INTO requirement_responses(requirement_id,draft_id,evidence_text,coverage_score,content_fingerprint,review_status) VALUES (?,?,?,1.0,?,'pending')",
                         (requirement_id, draft_id, quote, actual_hash))
            conn.execute("UPDATE project_drafts SET generation_json=?,confirmations_json=? WHERE id=?",
                         (json.dumps(generation, ensure_ascii=False), json.dumps(confirmations, ensure_ascii=False), draft_id))
            self._write_record(conn, self._record(conn, requirement), reviewer, "response_bound", {
                "draft_id": draft_id, "target_hash": actual_hash, "evidence_text": quote, "previous_responses": previous,
                "generation_binding": generation_binding,
            })
        return self.snapshot(project_id)

    @staticmethod
    def _replace_mapping(conn, project: dict[str, Any], requirement_id: int, section_ids: list[int]) -> None:
        for section in project["sections"]:
            previous = list(section["requirement_ids"])
            current = [value for value in previous if value != requirement_id]
            if section["id"] in section_ids:
                current.append(requirement_id)
            current = sorted(set(current))
            if current != previous:
                conn.execute("UPDATE project_sections SET requirement_ids_json=? WHERE id=? AND project_id=?",
                             (json.dumps(current), section["id"], project["id"]))
                section["requirement_ids"] = current

    @staticmethod
    def invalidate(conn, project_id: int, section_ids) -> None:
        for section_id in sorted(set(section_ids)):
            conn.execute("UPDATE project_drafts SET status='draft',updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND section_id=?", (project_id, section_id))
            conn.execute("UPDATE project_sections SET status=CASE WHEN EXISTS (SELECT 1 FROM project_drafts d WHERE d.section_id=project_sections.id) THEN 'drafted' ELSE 'planned' END WHERE id=? AND project_id=?", (section_id, project_id))
            conn.execute("UPDATE draft_review_decisions SET decision='invalidated' WHERE draft_id IN (SELECT id FROM project_drafts WHERE project_id=? AND section_id=?) AND decision='approved'", (project_id, section_id))
            conn.execute("UPDATE requirement_responses SET review_status='invalidated' WHERE draft_id IN (SELECT id FROM project_drafts WHERE project_id=? AND section_id=?)", (project_id, section_id))
        conn.execute("UPDATE delivery_manifests SET status='invalidated',invalidated_at=CURRENT_TIMESTAMP WHERE project_id=? AND invalidated_at IS NULL", (project_id,))
        # Retain the reviewer and all original approval data in audit history;
        # the current profile is explicitly marked for another whole review.
        row = conn.execute("SELECT profile_json FROM projects WHERE id=?", (project_id,)).fetchone()
        profile = parse_json(row["profile_json"], {}) if row else {}
        if profile.get("delivery_confirmation") or profile.get("manual_finalized") or profile.get("final_approved"):
            profile["manual_finalized"] = False
            profile["final_approved"] = False
            conn.execute("UPDATE projects SET profile_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(profile, ensure_ascii=False), project_id))

    def build_outline(self, project_id: int, titles: list[str], matches) -> dict[str, Any]:
        with self.db.connect() as conn:
            project = self._locked_project(conn, project_id)
            technical = [item for item in project["requirements"] if item["planning_category"] in {"technical", "unclassified"}]
            technical_ids = {item["id"] for item in technical}
            by_title = {section["title"]: section for section in project["sections"]}
            next_order = max((section["order_no"] for section in project["sections"]), default=0)
            affected = set()
            for title in titles:
                section = by_title.get(title)
                if section is None:
                    next_order += 1
                    section_id = int(conn.execute("INSERT INTO project_sections(project_id,order_no,title) VALUES (?,?,?)", (project_id, next_order, title)).lastrowid)
                    section = {"id": section_id, "title": title, "order_no": next_order, "requirement_ids": []}
                    project["sections"].append(section)
                    by_title[title] = section
                    affected.add(section_id)
                previous = list(section["requirement_ids"])
                ids = sorted({value for value in previous if value in technical_ids} | {item["id"] for item in technical if matches(title, item["content"])})
                if ids != previous:
                    conn.execute("UPDATE project_sections SET requirement_ids_json=? WHERE id=?", (json.dumps(ids), section["id"]))
                    section["requirement_ids"] = ids
                    affected.add(section["id"])
            if affected:
                self.invalidate(conn, project_id, affected)
        return {"project_id": project_id, "sections": self.production.get_project(project_id)["sections"]}
