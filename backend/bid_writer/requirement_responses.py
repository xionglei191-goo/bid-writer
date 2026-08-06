from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts


COMPLIANCE_TERMS = (
    "暗标",
    "废标",
    "否决投标",
    "无效投标",
    "投标保证金",
    "投标截止",
    "投标文件递交",
    "电子投标文件",
    "CA锁",
    "签章",
    "开标程序",
)

BUSINESS_TERMS = (
    "投标人资质",
    "资质要求",
    "类似业绩",
    "施工业绩",
    "财务要求",
    "投标报价",
    "综合单价",
    "材料费基准价",
    "偏差率",
    "合同金额",
    "已标价工程量清单",
    "工程量清单报价",
    "措施项目清单报价",
    "合同价格",
    "费用增加",
    "费用由承包人承担",
    "赔偿",
    "工程款申请",
    "发包人和承包人",
)

PROJECT_FACT_TERMS = (
    "项目名称",
    "工程名称",
    "项目概况",
    "建设地点",
    "建设规模",
    "建筑面积",
    "承包范围",
    "招标范围",
    "计划工期",
    "总工期",
    "质量要求",
    "质量目标",
    "安全目标",
    "特殊质量标准和要求",
)

TECHNICAL_TERMS = (
    "施工方案",
    "技术措施",
    "管理体系",
    "保证措施",
    "施工方法",
    "施工工艺",
    "进度计划",
    "资源配备",
    "风险管理",
    "总平面",
    "BIM",
    "新技术",
    "文明施工",
    "环境保护",
    "安全管理",
    "安全防护",
    "安全施工",
    "保通措施",
    "交通畅通",
    "扬尘污染防治",
    "建筑垃圾处置",
    "非道路移动机械",
)

COMPLIANCE_PATTERNS = (
    r"手写签名",
    r"扫描图片替换",
    r"加盖.{0,12}(?:公章|执业资格章)",
    r"投标文件格式",
    r"报价唯一",
    r"联合体协议",
    r"解释顺序",
    r"评标委员会",
    r"评标标准和方法",
)

BUSINESS_PATTERNS = (
    r"发包人.{0,12}承包人",
    r"招标人.{0,12}投标人",
)

TECHNICAL_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("施工方案", ("施工方案", "施工组织设计", "技术方案")),
    ("技术措施", ("技术措施", "技术组织措施", "控制措施")),
    ("施工工艺", ("施工工艺", "工艺流程", "施工方法", "操作要点")),
    ("流水组织", ("流水段", "施工区段", "流水组织", "流水施工")),
    ("交叉作业", ("交叉作业", "穿插施工", "专业穿插", "工序穿插")),
    ("质量管理", ("质量管理", "质量保证", "质量体系", "质量控制", "实测实量", "验收标准", "验收规范", "验收评定标准", "技术规范", "技术规程")),
    ("安全管理", ("安全管理", "安全生产", "安全防护", "危险源", "安全检查", "人身安全", "施工秩序")),
    ("文明施工", ("文明施工", "场容场貌", "文明工地")),
    ("环境保护", ("环境保护", "绿色施工", "环境管理", "环保")),
    ("工期进度", ("工期", "进度计划", "关键线路", "进度控制", "节点计划")),
    ("交通保通", ("保通", "交通畅通", "交通组织", "车辆疏导")),
    ("新技术", ("新工艺", "新技术", "新设备", "新材料", "四新技术")),
    ("风险管理", ("风险管理", "风险防控", "风险预控", "风险识别", "应急措施")),
    ("资源配置", ("资源配备", "资源配置", "劳动力计划", "机械设备", "人材机")),
    ("项目班子", ("项目管理班子", "项目经理", "技术负责人", "项目组织机构")),
    ("扬尘治理", ("扬尘", "八个百分百", "8个100%", "喷淋", "雾炮")),
    ("建筑垃圾", ("建筑垃圾", "固体废物", "垃圾分类", "垃圾清运")),
    ("非道路机械", ("非道路移动机械", "排放污染", "环保编码", "进出场核验")),
    ("总平面", ("总平面", "平面布置", "临建设施", "临水临电", "施工道路")),
    ("总承包协调", ("总承包管理", "协调管理", "界面管理", "专业分包")),
    ("水性漆", ("水性漆", "涂饰工程", "基层处理", "涂料施工")),
)

STOP_WORDS = {
    "本工程",
    "本项目",
    "要求",
    "措施",
    "方案",
    "施工",
    "管理",
    "进行",
    "相关",
    "确保",
    "合理",
    "可行",
    "符合",
}


def requirement_key(content: str) -> str:
    normalized = re.sub(r"\s+", "", content)
    normalized = re.sub(r"^[A-Za-z]?\d+(?:\.\d+)*[、.：:]?", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _score_weight(content: str) -> float:
    match = re.search(r"(?:（|\()?\s*(\d+(?:\.\d+)?)\s*分(?:）|\))?", content)
    return float(match.group(1)) if match else 0.0


def _source_page(source_hint: str) -> int | None:
    match = re.search(r"(?:page|页)[:：]?\s*(\d+)", source_hint, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _keywords(content: str) -> list[str]:
    candidates: list[str] = []
    for term in (*TECHNICAL_TERMS, *PROJECT_FACT_TERMS):
        if term in content and term not in candidates:
            candidates.append(term)
    for _, aliases in TECHNICAL_CONCEPTS:
        if any(alias in content for alias in aliases):
            for alias in aliases:
                if alias not in candidates:
                    candidates.append(alias)
            if len(candidates) >= 12:
                break
    for phrase in re.split(r"[，。；：、（）()\s]+", content):
        phrase = re.sub(r"^\d+(?:\.\d+)*", "", phrase).strip()
        if 3 <= len(phrase) <= 10 and phrase not in STOP_WORDS and phrase not in candidates:
            candidates.append(phrase)
        if len(candidates) >= 12:
            break
    return candidates[:12]


def classify_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    content = str(requirement.get("content") or "").strip()
    kind = str(requirement.get("kind") or "technical").lower()
    if kind == "risk" or any(term in content for term in COMPLIANCE_TERMS) or any(re.search(pattern, content) for pattern in COMPLIANCE_PATTERNS):
        scope = "compliance"
    elif any(term in content for term in BUSINESS_TERMS) or any(re.search(pattern, content) for pattern in BUSINESS_PATTERNS):
        scope = "business"
    elif any(term in content for term in PROJECT_FACT_TERMS) and not any(term in content for term in TECHNICAL_TERMS):
        scope = "project_fact"
    else:
        scope = "chapter"
    weight = _score_weight(content)
    priority = str(requirement.get("priority") or "normal")
    if kind == "scoring" or weight > 0:
        priority = "high"
    return {
        "requirement_key": requirement_key(content),
        "response_scope": scope,
        "score_weight": weight,
        "source_page": _source_page(str(requirement.get("source_hint") or "")),
        "section_path": str(requirement.get("section_path") or "").strip(),
        "applicable": int(requirement.get("applicable", 1) not in {False, 0, "0", "false"}),
        "classification_source": str(requirement.get("classification_source") or "auto"),
        "review_status": str(requirement.get("review_status") or "pending"),
        "review_notes": str(requirement.get("review_notes") or ""),
        "acceptance_keywords": _keywords(content),
        "priority": priority,
    }


def classify_tender_requirements(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    counts: dict[str, int] = defaultdict(int)
    with conn:
        for row in rows:
            classified = classify_requirement(row)
            counts[classified["response_scope"]] += 1
            conn.execute(
                """
                UPDATE requirements
                SET requirement_key = ?, response_scope = ?, score_weight = ?, source_page = ?,
                    section_path = ?, applicable = ?, classification_source = ?, review_status = ?,
                    review_notes = ?, acceptance_keywords_json = ?, priority = ?
                WHERE id = ?
                """,
                (
                    classified["requirement_key"],
                    classified["response_scope"],
                    classified["score_weight"],
                    classified["source_page"],
                    classified["section_path"],
                    classified["applicable"],
                    classified["classification_source"],
                    classified["review_status"],
                    classified["review_notes"],
                    json.dumps(classified["acceptance_keywords"], ensure_ascii=False),
                    classified["priority"],
                    row["id"],
                ),
            )
    result = {"tender_id": tender_id, "total": len(rows), "scopes": dict(counts)}
    if own_conn:
        conn.close()
    return result


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _content_signature(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _segments(content: str) -> list[tuple[str, str]]:
    heading = ""
    segments: list[tuple[str, str]] = []
    buffer: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if buffer:
                segments.append((heading, "\n".join(buffer).strip()))
                buffer = []
            heading = stripped.lstrip("#").strip()
        elif stripped:
            buffer.append(stripped)
    if buffer:
        segments.append((heading, "\n".join(buffer).strip()))
    return [(title, text) for title, text in segments if text]


def _concept_groups(content: str) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    for _, aliases in TECHNICAL_CONCEPTS:
        if any(alias in content for alias in aliases):
            groups.append(aliases)
    return groups


def _best_evidence(requirement: dict[str, Any], content: str, section_title: str = "") -> tuple[str, str, float]:
    keywords = [str(item) for item in _json_list(requirement.get("acceptance_keywords_json")) if str(item)]
    if not keywords:
        keywords = _keywords(str(requirement.get("content") or ""))
    concept_groups = _concept_groups(str(requirement.get("content") or ""))
    requirement_template = _template_name(str(requirement.get("content") or ""))
    section_template = _template_name(section_title)
    section_matches = bool(requirement_template and requirement_template == section_template)
    best = ("", "", 0.0)
    for heading, text in _segments(content):
        searchable = f"{heading}\n{text}"
        if concept_groups:
            hits = sum(1 for group in concept_groups if any(term in searchable for term in group))
            score = hits / len(concept_groups)
        else:
            hits = sum(1 for keyword in keywords if keyword in searchable)
            score = hits / len(keywords) if keywords else 0.0
        if section_matches:
            score += 0.22
        if len(text) >= 180:
            score += 0.12
        if len(text) >= 500:
            score += 0.08
        score = min(score, 1.0)
        if score > best[2]:
            excerpt = re.sub(r"\s+", " ", text)[:360]
            best = (heading, excerpt, score)
    return best


def _template_name(text: str) -> str:
    # Local import avoids coupling database migration/import paths to template setup.
    from .section_templates import template_for

    return template_for(text).name


def rebuild_requirement_responses(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    classify_tender_requirements(tender_id, conn=conn)
    requirements = rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    plans = rows_to_dicts(conn.execute("SELECT * FROM section_plans WHERE tender_id = ? ORDER BY order_no, id", (tender_id,)).fetchall())
    drafts = rows_to_dicts(conn.execute("SELECT * FROM drafts WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())
    draft_by_id = {int(row["id"]): row for row in drafts}
    linked: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for plan in plans:
        draft = draft_by_id.get(int(plan["draft_id"])) if plan.get("draft_id") else None
        if not draft:
            continue
        for req_id in _json_list(plan.get("requirement_ids_json")):
            try:
                linked[int(req_id)].append((plan, draft))
            except (TypeError, ValueError):
                continue
    existing = {
        (int(row["requirement_id"]), int(row["draft_id"]) if row.get("draft_id") else None): row
        for row in rows_to_dicts(conn.execute("SELECT * FROM requirement_responses WHERE tender_id = ?", (tender_id,)).fetchall())
    }
    keep_ids: set[int] = set()
    counts: dict[str, int] = defaultdict(int)
    with conn:
        for requirement in requirements:
            req_id = int(requirement["id"])
            scope = str(requirement.get("response_scope") or "chapter")
            targets = linked.get(req_id, [])
            if scope == "project_fact" and not targets:
                targets = [(None, draft) for draft in drafts]
            if not targets:
                status = "not_applicable" if not int(requirement.get("applicable", 1)) else "unlinked"
                counts[status] += 1
                continue
            for plan, draft in targets:
                signature = _content_signature(str(draft.get("content") or ""))
                heading, evidence, score = _best_evidence(
                    requirement,
                    str(draft.get("content") or ""),
                    str(draft.get("section_title") or ""),
                )
                previous = existing.get((req_id, int(draft["id"])))
                review_status = str(previous.get("review_status") or "pending") if previous else "pending"
                if previous and previous.get("content_signature") != signature and review_status == "approved":
                    review_status = "stale"
                if review_status == "approved":
                    status = "verified"
                elif score >= 0.72:
                    status = "verified"
                elif score >= 0.4:
                    status = "needs_review"
                else:
                    status = "missing"
                values = (
                    tender_id,
                    req_id,
                    int(plan["id"]) if plan else None,
                    int(draft["id"]),
                    str(draft.get("section_title") or ""),
                    heading,
                    evidence,
                    round(score, 4),
                    status,
                    review_status,
                    str(previous.get("reviewed_by") or "") if previous else "",
                    str(previous.get("review_notes") or "") if previous else "",
                    signature,
                )
                conn.execute(
                    """
                    INSERT INTO requirement_responses (
                        tender_id, requirement_id, section_plan_id, draft_id, section_title,
                        heading_path, evidence_text, coverage_score, response_status,
                        review_status, reviewed_by, review_notes, content_signature
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(requirement_id, draft_id) DO UPDATE SET
                        section_plan_id = excluded.section_plan_id,
                        section_title = excluded.section_title,
                        heading_path = excluded.heading_path,
                        evidence_text = excluded.evidence_text,
                        coverage_score = excluded.coverage_score,
                        response_status = excluded.response_status,
                        review_status = excluded.review_status,
                        reviewed_by = excluded.reviewed_by,
                        review_notes = excluded.review_notes,
                        content_signature = excluded.content_signature,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
                saved = row_to_dict(conn.execute("SELECT id FROM requirement_responses WHERE requirement_id = ? AND draft_id = ?", (req_id, draft["id"])).fetchone())
                if saved:
                    keep_ids.add(int(saved["id"]))
                counts[status] += 1
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            conn.execute(
                f"DELETE FROM requirement_responses WHERE tender_id = ? AND id NOT IN ({placeholders})",
                (tender_id, *sorted(keep_ids)),
            )
        else:
            conn.execute("DELETE FROM requirement_responses WHERE tender_id = ?", (tender_id,))
    result = {"tender_id": tender_id, "responses": sum(counts.values()), "statuses": dict(counts)}
    if own_conn:
        conn.close()
    return result


def list_requirement_responses(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT rr.*, r.kind, r.content AS requirement_content, r.priority,
                   r.response_scope, r.score_weight, r.source_hint, r.source_page,
                   r.applicable, r.acceptance_keywords_json
            FROM requirement_responses rr
            JOIN requirements r ON r.id = rr.requirement_id
            WHERE rr.tender_id = ?
            ORDER BY r.id, rr.coverage_score DESC, rr.id
            """,
            (tender_id,),
        ).fetchall()
    )
    for row in rows:
        row["acceptance_keywords"] = _json_list(row.get("acceptance_keywords_json"))
    if own_conn:
        conn.close()
    return rows


def update_requirement_response(response_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = row_to_dict(conn.execute("SELECT * FROM requirement_responses WHERE id = ?", (response_id,)).fetchone())
    if not current:
        raise ValueError(f"Requirement response not found: {response_id}")
    review_status = str(data.get("review_status") or current.get("review_status") or "pending")
    if review_status not in {"pending", "approved", "rejected", "stale"}:
        raise ValueError("Unsupported review status")
    response_status = str(data.get("response_status") or current.get("response_status") or "needs_review")
    if review_status == "approved":
        response_status = "verified"
    with conn:
        conn.execute(
            """
            UPDATE requirement_responses
            SET response_status = ?, review_status = ?, reviewed_by = ?, review_notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                response_status,
                review_status,
                str(data.get("reviewed_by") or current.get("reviewed_by") or ""),
                str(data.get("review_notes") or current.get("review_notes") or ""),
                response_id,
            ),
        )
    row = row_to_dict(conn.execute("SELECT * FROM requirement_responses WHERE id = ?", (response_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row
