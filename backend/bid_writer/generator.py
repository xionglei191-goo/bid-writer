from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any

from .bid_strategy import get_bid_strategy, section_strategy_focus, strategy_context_text
from .chapter_contracts import build_chapter_contract, contract_prompt, structured_generation_result, validate_chapter_contract
from .construction_methods import method_outline_for, method_summary
from .db import connect, row_to_dict, rows_to_dicts
from .draft_versions import record_draft_version
from .enterprise_profiles import enterprise_summary, get_enterprise_profile
from .llm_config import call_chat_completion, environment_value
from .project_profiles import get_project_profile, profile_summary
from .retrieval import search_chunks
from .section_templates import SectionTemplate, template_for
from .text_utils import summarize


REVIEW_SYSTEM_PROMPT = "你是技术标总工和终审专家。你的任务是重写初稿，消除历史项目污染和空泛表述，确保内容与给定项目资料及招标要求一致。"


def _project_name(tender: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    if profile and profile.get("project_name"):
        return str(profile["project_name"])
    try:
        parsed = json.loads(tender.get("parsed_json") or "{}")
        name = parsed.get("overview", {}).get("project_name")
        if name:
            return str(name)
    except json.JSONDecodeError:
        pass
    return str(tender.get("name") or "本项目")


def _historical_names(chunk: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("top_project",):
        value = str(chunk.get(key) or "").strip()
        if len(value) >= 5:
            names.add(value)
            names.add(re.sub(r"(技术标|施工组织设计|投标文件|项目)$", "", value).strip())
    source = str(chunk.get("source_path") or "")
    for part in re.split(r"[\\/]", source):
        stem = re.sub(r"\.[A-Za-z0-9]+$", "", part).strip()
        if 6 <= len(stem) <= 60 and any(term in stem for term in ("项目", "工程", "技术标", "施工组织")):
            names.add(stem)
    return {name for name in names if len(name) >= 5}


def _adapt_reference_text(text: str, chunk: dict[str, Any], target_project: str) -> str:
    adapted = text.replace("\\n", "\n").replace("\r\n", "\n").strip()
    for name in sorted(_historical_names(chunk), key=len, reverse=True):
        if name and name not in {target_project, "本项目"}:
            adapted = adapted.replace(name, "本项目")
    adapted = re.sub(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b", "按项目计划节点", adapted)
    adapted = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", adapted)
    adapted = re.sub(r"\n{3,}", "\n\n", adapted)
    return adapted[:1600].strip()


def _chunk_is_usable(chunk: dict[str, Any]) -> bool:
    heading = str(chunk.get("heading_text") or "").strip()
    if any(term in heading for term in ("封面", "目录", "投标函", "法定代表人", "授权委托")):
        return False
    content = str(chunk.get("content") or "").replace("\\n", "\n").strip()
    nonempty = [line.strip() for line in content.splitlines() if line.strip()]
    substantive = [
        line
        for line in nonempty
        if len(re.sub(r"^[#>*\-\d.、（）()\s]+", "", line)) >= 24
        and not re.fullmatch(r"[|:\-\s]+", line)
    ]
    plain = re.sub(r"[#>*|`\-\s\d.、，。；：:（）()]", "", content)
    return len(plain) >= 160 and (len(substantive) >= 2 or len(plain) >= 400)


def _clean_generated_content(content: str, section_title: str) -> str:
    text = content.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    heading_match = re.search(r"(?m)^#\s+", text)
    if heading_match and heading_match.start() > 0:
        text = text[heading_match.start():]
    if not re.match(r"^#\s+", text):
        text = f"# {section_title}\n\n{text}"
    text = re.sub(r"(?m)^#\s+.*$", f"# {section_title}", text, count=1)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _profile_field(profile: dict[str, Any], field: str) -> str:
    return str(profile.get(field) or "").strip()


def _project_control_points(
    profile: dict[str, Any],
    requirements: list[dict[str, Any]],
    section_title: str,
) -> list[str]:
    points: list[str] = []
    scale = _profile_field(profile, "building_area")
    structure = _profile_field(profile, "structure_type")
    floor_info = _profile_field(profile, "floor_info")
    duration = profile.get("duration_days")
    quality = _profile_field(profile, "quality_target")
    safety = _profile_field(profile, "safety_target")
    scope = _profile_field(profile, "contract_scope")
    site = _profile_field(profile, "site_conditions")
    constraints = _profile_field(profile, "key_constraints")
    special = _profile_field(profile, "special_requirements")
    if scale or structure or floor_info:
        points.append(f"工程参数按{scale or '招标文件规模'}、{structure or '招标结构形式'}、{floor_info or '招标层数'}组织章节内容，禁止沿用历史项目参数。")
    if duration:
        points.append(f"所有部署和资源安排应服务 {duration} 日历天工期目标，并预留过程纠偏和节点复核。")
    if quality:
        points.append(f"质量控制以“{quality}”为目标，措施需落到样板、交底、检查、验收和整改闭环。")
    if safety:
        points.append(f"安全文明施工以“{safety}”为底线，危大工程、临边洞口、临电消防和文明环保需逐项管控。")
    if scope:
        points.append(f"章节响应范围覆盖：{scope}；涉及界面交叉时应明确移交条件和责任边界。")
    if site:
        points.append(f"现场组织需结合：{site}；施工部署、运输组织、噪声扬尘和成品保护均应对应调整。")
    if constraints:
        points.append(f"关键约束按“{summarize(constraints, 140)}”设置专项措施、责任人和检查频次。")
    if special:
        points.append(f"专项要求按“{summarize(special, 140)}”设置深化、样板、旁站、检测和验收控制。")
    for item in requirements[:4]:
        content = str(item.get("content") or "").strip()
        if content:
            points.append(f"本章需响应招标条款：{summarize(content, 150)}")
    if not points:
        points.append(f"围绕《{section_title}》建立目标、责任、资源、实施、检查和整改闭环，正式投标前补齐项目参数。")
    return points[:10]


def _implementation_note(profile: dict[str, Any], outline_title: str) -> str:
    duration = profile.get("duration_days")
    quality = _profile_field(profile, "quality_target")
    safety = _profile_field(profile, "safety_target")
    site = _profile_field(profile, "site_conditions")
    special = _profile_field(profile, "special_requirements")
    parts: list[str] = []
    if duration:
        parts.append(f"服从 {duration} 日历天总体工期")
    if quality:
        parts.append(f"满足{quality}质量目标")
    if safety:
        parts.append(f"落实{safety}要求")
    if site:
        parts.append(f"适配现场条件：{summarize(site, 80)}")
    if special and any(term in outline_title for term in ("机电", "净化", "专项", "医疗", "接口", "工艺")):
        parts.append(f"响应专项要求：{summarize(special, 90)}")
    if not parts:
        return ""
    return "本项措施实施时应" + "，".join(parts) + "。"


def _local_draft(
    tender: dict[str, Any],
    profile: dict[str, Any],
    enterprise: dict[str, Any],
    section_title: str,
    requirements: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    template: SectionTemplate,
    strategy: dict[str, Any] | None = None,
) -> str:
    target_project = _project_name(tender, profile)
    lines: list[str] = [f"# {section_title}", ""]
    lines.append(f"> 生成策略：{template.name}；目标项目：{target_project}")
    lines.append("")
    summary = profile_summary(profile)
    if summary:
        lines.append("## 项目资料")
        lines.append(summary)
        lines.append("")
    enterprise_text = enterprise_summary(enterprise)
    if enterprise_text:
        lines.append("## 投标单位资料")
        lines.append(enterprise_text)
        lines.append("")
    strategy_text = strategy_context_text(strategy or {})
    if strategy_text:
        lines.append("## 投标响应策略")
        focus = section_strategy_focus(strategy or {}, section_title)
        if focus:
            lines.append(f"- 本章编制重点：{focus}")
        for line in strategy_text.splitlines()[:18]:
            lines.append(line)
        lines.append("")
    if requirements:
        lines.append("## 招标要求响应")
        for item in requirements[:12]:
            lines.append(f"- 响应条款：{item['content']}")
        lines.append("")

    lines.append("## 编制说明")
    lines.append(template.intent)
    lines.append("本节内容根据招标文件要求和历史同类技术标片段形成，已按本项目口径进行初步改写。正式投标前需复核工程规模、工期节点、现场条件和专用条款。")
    lines.append("")

    lines.append("## 项目化控制要点")
    for point in _project_control_points(profile, requirements, section_title):
        lines.append(f"- {point}")
    lines.append("")

    lines.append("## 主要措施")
    outline = method_outline_for(profile) if template.name == "施工工艺及主要施工方法" else template.outline
    for index, outline_title in enumerate(outline, 1):
        lines.append(f"### {index}. {outline_title}")
        source_chunk = chunks[(index - 1) % len(chunks)] if chunks else {}
        if source_chunk:
            adapted = _adapt_reference_text(str(source_chunk.get("content", "")), source_chunk, target_project)
            lines.append(adapted or f"围绕{outline_title}建立责任清单、实施计划、检查机制和闭环整改要求。")
        else:
            lines.append(f"围绕{outline_title}建立责任清单、实施计划、检查机制和闭环整改要求。")
        implementation_note = _implementation_note(profile, outline_title)
        if implementation_note:
            lines.append(implementation_note)
        lines.append("")

    if chunks:
        lines.append("## 参考来源摘要")
        for index, chunk in enumerate(chunks[:6], 1):
            lines.append(f"- 参考{index}：{chunk.get('top_category') or '未分类'} / {chunk.get('heading_text') or section_title} / {summarize(chunk.get('source_path', ''), 120)}")
        lines.append("")

    lines.append("## 需人工确认")
    for point in template.quality_points:
        lines.append(f"- {point}")
    lines.append("- 核对项目名称、建设地点、工期目标、质量目标和安全文明目标。")
    lines.append("- 根据最新招标文件调整章节编号、格式和响应矩阵。")
    return "\n".join(lines).strip() + "\n"


def build_prompt(
    tender: dict[str, Any],
    profile: dict[str, Any],
    enterprise: dict[str, Any],
    section_title: str,
    requirements: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    template: SectionTemplate,
    strategy: dict[str, Any] | None = None,
) -> str:
    contract = build_chapter_contract(section_title, profile, requirements, template)
    req_text = "\n".join(f"- {item['content']}" for item in requirements[:20]) or "无明确条款，按常规技术标要求编制。"
    refs = []
    for index, chunk in enumerate(chunks, 1):
        reference_text = _adapt_reference_text(str(chunk.get("content", "")), chunk, _project_name(tender, profile))
        refs.append(
            f"[素材{index}] 类型：{chunk.get('top_category') or '未分类'}；章节：{chunk.get('heading_text') or '未标注'}\n{reference_text[:1000]}"
        )
    project_info = profile_summary(profile) or "暂无补充项目资料，请按招标文件和通用技术标要求生成。"
    enterprise_info = enterprise_summary(enterprise) or "暂无投标单位资料，请避免编造资质、业绩、人员和设备参数。"
    construction_methods = ""
    if template.name == "施工工艺及主要施工方法":
        construction_methods = f"\n建议施工工艺清单：\n{method_summary(profile)}\n"
    strategy_text = strategy_context_text(strategy or {}) or "暂无单独策略，请按招标要求、项目资料和章节模板编制。"
    section_focus = section_strategy_focus(strategy or {}, section_title)
    minimum_length = 3200 if template.name == "施工工艺及主要施工方法" else 1800
    return f"""请生成技术标章节《{section_title}》。

目标项目：{_project_name(tender, profile)}
行业：{tender.get("industry") or "未填写"}
项目资料：
{project_info}

投标单位资料：
{enterprise_info}

投标响应策略：
{strategy_text}

本章策略重点：
{section_focus or "按章节模板和招标要求展开。"}

章节编制合同（必须逐项满足）：
{contract_prompt(contract)}

章节模板：{template.name}
章节意图：{template.intent}
建议结构：
{chr(10).join(f"- {item}" for item in template.outline)}
{construction_methods}

招标要求：
{req_text}

历史参考：
{chr(10).join(refs)}

编制规则：
1. 只输出可直接进入投标文件的 Markdown 正文，一级标题必须是“# {section_title}”。不要输出生成说明、参考来源、写作策略或“需人工确认”章节。
2. 以项目资料和招标要求为唯一事实边界。资料缺失时使用“【待确认：字段】”，严禁自行编造工程数量、日期、地点、企业资质、人员、设备数量和业绩。
3. 历史素材只用于借鉴工艺逻辑和管理方法，必须重新组织语言；删除其中的历史项目名、地名、楼栋数量、层数、日期、页码及不适用参数。
4. 每个二级或三级标题下必须有实质内容，禁止只有标题。措施应写明实施动作、责任岗位、资源条件、检查频次或节点、质量验收标准和异常处置闭环。
5. 对招标要求逐项形成可验证响应，但不要机械重复条款原文。
6. 施工工艺章节的每项主要工艺应覆盖工艺流程、施工准备、操作要点、质量控制、检查验收、安全环保和成品保护；不属于已知工程范围的工艺不得强行写入。
7. 正文目标不少于 {minimum_length} 个中文字符；信息不足时优先深化通用但可执行的控制流程，不得凑字或重复段落。
"""


def _dedupe_chunks(chunks: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    seen: set[tuple[str, int | str]] = set()
    seen_content: set[str] = set()
    source_counts: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for chunk in chunks:
        if not _chunk_is_usable(chunk):
            continue
        source_type = str(chunk.get("source_type") or "kb_chunk")
        key = (source_type, chunk.get("id") or chunk.get("source_path") or len(result))
        if key in seen:
            continue
        content_key = re.sub(r"\s+", "", str(chunk.get("content") or ""))[:240]
        if content_key in seen_content:
            continue
        source_key = f"{source_type}:{chunk.get('source_path') or chunk.get('id')}"
        if source_counts.get(source_key, 0) >= 2:
            continue
        seen.add(key)
        seen_content.add(content_key)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        result.append(chunk)
        if len(result) >= limit:
            break
    return result


def _retrieve_reference_chunks(
    tender: dict[str, Any],
    profile: dict[str, Any],
    enterprise: dict[str, Any],
    section_title: str,
    requirements: list[dict[str, Any]],
    selected_template: SectionTemplate,
    strategy: dict[str, Any],
    category: str,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    method_terms = " ".join(method_outline_for(profile)) if selected_template.name == "施工工艺及主要施工方法" else ""
    requirement_text = " ".join(item["content"] for item in requirements[:5])
    query = (
        section_title
        + " "
        + method_terms
        + " "
        + str(strategy.get("reference_keywords") or "")
        + " "
        + str(enterprise.get("bidder_name") or "")
        + " "
        + str(enterprise.get("qualification_summary") or "")
        + " "
        + requirement_text
    )
    industry = category or str(tender.get("industry") or "")
    chunks = _dedupe_chunks(search_chunks(
        query=query,
        category=industry,
        project_type=str(tender.get("name") or ""),
        heading=section_title,
        limit=20,
        conn=conn,
    ))
    if len(chunks) >= 3:
        return _dedupe_chunks(chunks)

    template_query = " ".join(
        [
            section_title,
            selected_template.name,
            selected_template.intent,
            " ".join(selected_template.outline),
            requirement_text,
        ]
    )
    chunks = _dedupe_chunks(
        [
            *chunks,
            *search_chunks(
                query=template_query,
                category=industry,
                project_type="",
                heading="",
                limit=20,
                conn=conn,
            ),
        ]
    )
    if len(chunks) >= 3:
        return chunks

    chunks = _dedupe_chunks(
        [
            *chunks,
            *search_chunks(
                query=f"{section_title} {selected_template.name} {requirement_text}",
                category="",
                project_type="",
                heading=section_title,
                limit=20,
                conn=conn,
            ),
        ]
    )
    if len(chunks) >= 3:
        return chunks

    return _dedupe_chunks(
        [
            *chunks,
            *search_chunks(
                query=f"{section_title} {selected_template.name} {selected_template.intent}",
                category="",
                project_type="",
                heading="",
                limit=20,
                conn=conn,
            ),
        ]
    )


def build_revision_prompt(
    tender: dict[str, Any],
    profile: dict[str, Any],
    section_title: str,
    requirements: list[dict[str, Any]],
    template: SectionTemplate,
    draft: str,
) -> str:
    contract = build_chapter_contract(section_title, profile, requirements, template)
    project_info = profile_summary(profile) or "仅确认项目名称，其他项目参数均未提供。"
    req_text = "\n".join(f"- {item['content']}" for item in requirements[:20]) or "- 未提取到明确条款。"
    quality_points = "\n".join(f"- {item}" for item in template.quality_points)
    minimum_length = 3000 if template.name == "施工工艺及主要施工方法" else 1600
    return f"""请对下面的技术标初稿执行终审并直接输出重写后的完整章节。

章节：{section_title}
目标项目：{_project_name(tender, profile)}
已确认项目资料：
{project_info}

必须响应的招标要求：
{req_text}

本章质量要点：
{quality_points}

章节编制合同：
{contract_prompt(contract)}

终审规则：
1. 保留有效技术内容，但删除历史项目名称、地名、日期、页码、楼栋层数、数量和无法由项目资料证明的参数。
2. 删除生成过程说明、参考来源摘要、需人工确认清单和重复的招标原文。
3. 修复只有标题没有正文、工艺错配、上下文跳跃、表格残缺和字面复制问题。
4. 将空泛承诺改成实施动作、责任岗位、检查节点或频次、验收标准和异常闭环。
5. 不得编造缺失事实；确有必要时使用“【待确认：字段】”。
6. 只输出 Markdown 正文，一级标题必须为“# {section_title}”，正文不少于 {minimum_length} 个中文字符。

待终审初稿：
{draft[:24000]}
"""


def generate_draft(
    tender_id: int,
    section_title: str,
    requirement_ids: list[int] | None = None,
    category: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    enterprise = get_enterprise_profile(conn=conn)

    if requirement_ids is not None:
        requirements: list[dict[str, Any]] = []
        if requirement_ids:
            placeholders = ",".join("?" for _ in requirement_ids)
            requirements = rows_to_dicts(
                conn.execute(
                    f"SELECT * FROM requirements WHERE tender_id = ? AND id IN ({placeholders})",
                    [tender_id, *requirement_ids],
                ).fetchall()
            )
    else:
        requirements = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM requirements
                WHERE tender_id = ?
                ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, id
                LIMIT 20
                """,
                (tender_id,),
            ).fetchall()
        )

    selected_template = template_for(section_title)
    chapter_contract = build_chapter_contract(section_title, profile, requirements, selected_template)
    strategy = get_bid_strategy(tender_id, conn=conn)
    chunks = _retrieve_reference_chunks(
        tender=tender,
        profile=profile,
        enterprise=enterprise,
        section_title=section_title,
        requirements=requirements,
        selected_template=selected_template,
        strategy=strategy,
        category=category,
        conn=conn,
    )
    prompt = build_prompt(tender, profile, enterprise, section_title, requirements, chunks, selected_template, strategy)
    output_limit = 6500 if selected_template.name == "施工工艺及主要施工方法" else 4500
    llm_result = call_chat_completion(prompt, timeout=240, max_output_tokens=output_limit)
    generation_mode = "llm" if llm_result.get("content") else "local_fallback"
    generation_model = str(llm_result.get("model") or "")
    generation_error = str(llm_result.get("error") or "")
    if llm_result.get("content"):
        content = _clean_generated_content(str(llm_result["content"]), section_title)
        review_enabled = environment_value("BID_WRITER_LLM_REVIEW", "1").strip().lower() not in {"0", "false", "no"}
        if review_enabled:
            revision_result = call_chat_completion(
                build_revision_prompt(tender, profile, section_title, requirements, selected_template, content),
                timeout=240,
                instructions=REVIEW_SYSTEM_PROMPT,
                max_output_tokens=output_limit,
            )
            if revision_result.get("content"):
                content = _clean_generated_content(str(revision_result["content"]), section_title)
            elif revision_result.get("error"):
                generation_error = f"二次终审未完成：{revision_result['error']}"
    else:
        content = _local_draft(
            tender,
            profile,
            enterprise,
            section_title,
            requirements,
            chunks,
            selected_template,
            strategy,
        )
    citations = [
        {
            "source_path": chunk.get("source_path", ""),
            "markdown_path": chunk.get("markdown_path", ""),
            "heading_text": chunk.get("heading_text", ""),
            "chunk_id": chunk.get("id"),
            "source_type": chunk.get("source_type", "kb_chunk"),
        }
        for chunk in chunks
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        cur = conn.execute(
            """
            INSERT INTO drafts (
                tender_id, section_title, requirements_json, content,
                citations_json, review_json, generation_mode, generation_model, generation_error,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                tender_id,
                section_title,
                json.dumps(requirements, ensure_ascii=False),
                content,
                json.dumps(citations, ensure_ascii=False),
                json.dumps(
                    {
                        "findings": [],
                        "chapter_contract": chapter_contract,
                        "contract_validation": validate_chapter_contract(content, chapter_contract),
                        "structured_result": structured_generation_result(content, chapter_contract),
                    },
                    ensure_ascii=False,
                ),
                generation_mode,
                generation_model,
                generation_error,
                now,
                now,
            ),
        )
        draft_id = int(cur.lastrowid)
    record_draft_version(draft_id, content, origin="generated", conn=conn)

    draft = row_to_dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()) or {}
    draft["citations"] = citations
    draft["requirements"] = requirements
    draft["generation"] = {
        "mode": generation_mode,
        "model": generation_model,
        "error": generation_error,
    }
    draft["chapter_contract"] = chapter_contract
    draft["contract_validation"] = validate_chapter_contract(content, chapter_contract)
    draft["structured_result"] = structured_generation_result(content, chapter_contract)
    if own_conn:
        conn.close()
    return draft
