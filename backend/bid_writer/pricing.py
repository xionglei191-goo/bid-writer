from __future__ import annotations

import json
import re
import sqlite3
from math import ceil
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .production_tasks import get_production_task
from .project_profiles import get_project_profile


RUSH_WORDS = ("加急", "今晚", "今天", "明天", "24小时", "24 小时", "48小时", "48 小时", "马上", "尽快", "当天")
COMPLEX_WORDS = ("BIM", "鲁班奖", "省优", "装配式", "深基坑", "超高层", "不停产", "不停诊", "交通导改", "洁净", "医疗专项", "涉水", "泵站")
LIGHT_WORDS = ("目录", "框架", "大纲", "润色", "修改", "补充")


DEFAULT_PRICING_RULES = (
    ("base_price", "基础起步价", "基础", "number", "700", "元", "普通技术标初稿的起步价。"),
    ("included_sections", "基础包含章节", "章节", "number", "8", "章", "起步价默认覆盖的章节数量。"),
    ("section_price", "超出章节单价", "章节", "number", "90", "元/章", "超过基础章节数后的每章加价。"),
    ("requirement_threshold", "基础条款数量", "条款", "number", "10", "条", "起步价默认覆盖的招标要求数量。"),
    ("requirement_price", "超出条款单价", "条款", "number", "25", "元/条", "超过基础条款数后的每条加价。"),
    ("long_doc_chars", "长文档阈值", "文档", "number", "5000", "字", "原始招标文本超过该长度时视为长文档。"),
    ("long_doc_fee", "长文档加价", "文档", "number", "200", "元", "长招标文件的阅读和解析加价。"),
    ("complex_fee", "复杂项目加价", "复杂度", "number", "260", "元", "存在 BIM、深基坑、医疗专项等复杂关键词时加价。"),
    ("rush_fee", "加急加价", "时效", "number", "360", "元", "客户要求当天、明天、24/48 小时等加急交付时加价。"),
    ("material_gap_fee", "资料缺口加价", "资料", "number", "80", "元/项", "必要资料缺口带来的沟通和返工预留。"),
    ("light_discount", "轻量需求折扣", "折扣", "number", "220", "元", "只做目录、框架、润色且资料较少时的折扣。"),
    ("min_price", "最低接单价", "基础", "number", "350", "元", "系统给出的最低报价下限。"),
    ("high_multiplier", "报价上浮系数", "区间", "number", "1.45", "倍", "建议报价上限相对于测算低价的系数。"),
    ("standard_turnaround", "普通交付周期", "时效", "text", "2-4 天", "", "普通订单建议交付周期。"),
    ("rush_turnaround", "加急交付周期", "时效", "text", "24-48 小时", "", "加急订单建议交付周期。"),
    ("hour_low_per_section", "低工作量系数", "工作量", "number", "0.7", "小时/章", "估算工作量下限。"),
    ("hour_high_per_section", "高工作量系数", "工作量", "number", "1.2", "小时/章", "估算工作量上限。"),
    ("complex_extra_hours", "复杂项目额外工时", "工作量", "number", "4", "小时", "复杂项目额外预留工时。"),
)


def _text_blob(*items: Any) -> str:
    return "\n".join(str(item or "") for item in items if item not in (None, ""))


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    normalized = text.lower().replace(" ", "")
    return any(word.lower().replace(" ", "") in normalized for word in words)


def _round_price(value: float) -> int:
    return int(ceil(value / 50) * 50)


def _to_number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_default_pricing_rules(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        for rule_key, name, category, value_type, value, unit, description in DEFAULT_PRICING_RULES:
            conn.execute(
                """
                INSERT INTO pricing_rules (rule_key, name, category, value_type, value, unit, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_key) DO NOTHING
                """,
                (rule_key, name, category, value_type, value, unit, description),
            )
    rules = list_pricing_rules(conn=conn)
    if own_conn:
        conn.close()
    return rules


def list_pricing_rules(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM pricing_rules
            ORDER BY category, id
            """
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def update_pricing_rule(rule_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    current = row_to_dict(conn.execute("SELECT * FROM pricing_rules WHERE id = ?", (rule_id,)).fetchone())
    if not current:
        raise ValueError(f"Pricing rule not found: {rule_id}")
    allowed = {"name", "category", "value_type", "value", "unit", "enabled", "description"}
    cleaned: dict[str, Any] = {}
    for field in allowed:
        if field not in data:
            continue
        if field == "enabled":
            cleaned[field] = 1 if bool(data[field]) else 0
        else:
            cleaned[field] = str(data[field] or "").strip()
    if cleaned:
        assignments = ", ".join(f"{field} = ?" for field in cleaned)
        with conn:
            conn.execute(
                f"""
                UPDATE pricing_rules
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [*cleaned.values(), rule_id],
            )
    row = row_to_dict(conn.execute("SELECT * FROM pricing_rules WHERE id = ?", (rule_id,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return row


def _rules_map(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_default_pricing_rules(conn=conn)
    rules = rows_to_dicts(conn.execute("SELECT * FROM pricing_rules WHERE enabled = 1").fetchall())
    values: dict[str, Any] = {}
    for rule in rules:
        key = str(rule.get("rule_key") or "")
        if rule.get("value_type") == "number":
            values[key] = _to_number(rule.get("value"), 0)
        else:
            values[key] = str(rule.get("value") or "")
    return values


def _requirements(conn: sqlite3.Connection, tender_id: int) -> list[dict[str, Any]]:
    return rows_to_dicts(conn.execute("SELECT * FROM requirements WHERE tender_id = ? ORDER BY id", (tender_id,)).fetchall())


def _plan_count(conn: sqlite3.Connection, tender_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM section_plans WHERE tender_id = ?", (tender_id,)).fetchone()[0])


def _material_gap_count(conn: sqlite3.Connection, tender_id: int) -> int:
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM material_items
            WHERE tender_id = ? AND required = 1 AND status NOT IN ('已具备', '已识别', '已登记')
            """,
            (tender_id,),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.OperationalError:
        return 0


def calculate_price_quote_from_context(
    tender: dict[str, Any],
    profile: dict[str, Any],
    requirements: list[dict[str, Any]],
    plan_count: int,
    customer_message: str,
    material_gap_count: int = 0,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    rules = _rules_map(conn)
    raw_text = str(tender.get("raw_text") or "")
    blob = _text_blob(tender.get("name"), raw_text, profile.get("special_requirements"), customer_message)
    requirement_count = len(requirements)
    estimated_sections = plan_count or max(8, min(14, 6 + requirement_count // 4))
    raw_length = len(raw_text)
    rush = _contains_any(blob, RUSH_WORDS)
    complex_work = _contains_any(blob, COMPLEX_WORDS)
    light_work = _contains_any(customer_message, LIGHT_WORDS) and raw_length < 2000
    line_items: list[dict[str, Any]] = []

    base = _to_number(rules.get("base_price"), 700)
    total = base
    line_items.append({"name": "基础起步价", "amount": round(base, 2), "detail": "默认技术标初稿起步价"})

    included_sections = int(_to_number(rules.get("included_sections"), 8))
    extra_sections = max(0, estimated_sections - included_sections)
    section_fee = extra_sections * _to_number(rules.get("section_price"), 90)
    if section_fee:
        total += section_fee
        line_items.append({"name": "章节加价", "amount": round(section_fee, 2), "detail": f"超出 {extra_sections} 章"})

    requirement_threshold = int(_to_number(rules.get("requirement_threshold"), 10))
    extra_requirements = max(0, requirement_count - requirement_threshold)
    requirement_fee = extra_requirements * _to_number(rules.get("requirement_price"), 25)
    if requirement_fee:
        total += requirement_fee
        line_items.append({"name": "条款加价", "amount": round(requirement_fee, 2), "detail": f"超出 {extra_requirements} 条"})

    if raw_length > int(_to_number(rules.get("long_doc_chars"), 5000)):
        long_doc_fee = _to_number(rules.get("long_doc_fee"), 200)
        total += long_doc_fee
        line_items.append({"name": "长文档加价", "amount": round(long_doc_fee, 2), "detail": f"招标文本 {raw_length} 字"})

    if complex_work:
        complex_fee = _to_number(rules.get("complex_fee"), 260)
        total += complex_fee
        line_items.append({"name": "复杂项目加价", "amount": round(complex_fee, 2), "detail": "命中复杂工程关键词"})

    if rush:
        rush_fee = _to_number(rules.get("rush_fee"), 360)
        total += rush_fee
        line_items.append({"name": "加急加价", "amount": round(rush_fee, 2), "detail": "命中加急交付关键词"})

    if material_gap_count:
        material_fee = material_gap_count * _to_number(rules.get("material_gap_fee"), 80)
        total += material_fee
        line_items.append({"name": "资料缺口预留", "amount": round(material_fee, 2), "detail": f"{material_gap_count} 项必要资料待补"})

    if light_work:
        discount = _to_number(rules.get("light_discount"), 220)
        total -= discount
        line_items.append({"name": "轻量需求折扣", "amount": -round(discount, 2), "detail": "只做目录、框架、润色或补充"})

    min_price = _to_number(rules.get("min_price"), 350)
    total = max(min_price, total)
    low = _round_price(total)
    high = _round_price(total * _to_number(rules.get("high_multiplier"), 1.45))
    hours_low = max(4, int(estimated_sections * _to_number(rules.get("hour_low_per_section"), 0.7)))
    hours_high = max(
        hours_low + 2,
        int(estimated_sections * _to_number(rules.get("hour_high_per_section"), 1.2))
        + (int(_to_number(rules.get("complex_extra_hours"), 4)) if complex_work else 0),
    )
    turnaround = str(rules.get("rush_turnaround") if rush else rules.get("standard_turnaround") or ("24-48 小时" if rush else "2-4 天"))
    factors = {
        "estimated_sections": estimated_sections,
        "requirement_count": requirement_count,
        "raw_text_chars": raw_length,
        "material_gap_count": material_gap_count,
        "rush": rush,
        "complex_work": complex_work,
        "light_work": light_work,
        "extra_sections": extra_sections,
        "extra_requirements": extra_requirements,
    }
    snapshot = list_pricing_rules(conn=conn)
    result = {
        **factors,
        "price_low": low,
        "price_high": high,
        "suggested_price": f"{low}-{high} 元",
        "workload": f"{hours_low}-{hours_high} 小时",
        "turnaround": turnaround,
        "line_items": line_items,
        "rules_snapshot": snapshot,
    }
    if own_conn:
        conn.close()
    return result


def build_price_quote(
    tender_id: int,
    data: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
    save_record: bool = False,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    payload = data or {}
    task = get_production_task(tender_id, conn=conn)
    profile = get_project_profile(tender_id, conn=conn)
    customer_message = str(payload.get("customer_message") or task.get("delivery_notes") or tender.get("raw_text") or "")
    source_platform = str(payload.get("source_platform") or task.get("source_platform") or "闲鱼")
    quote = calculate_price_quote_from_context(
        tender,
        profile,
        _requirements(conn, tender_id),
        _plan_count(conn, tender_id),
        customer_message,
        material_gap_count=_material_gap_count(conn, tender_id),
        conn=conn,
    )
    quote["tender"] = {"id": tender["id"], "name": tender["name"], "industry": tender.get("industry") or ""}
    quote["task"] = task
    quote["input"] = {"customer_message": customer_message, "source_platform": source_platform}
    quote["customer_message"] = render_quote_message(quote)
    quote["markdown"] = render_quote_markdown(quote)
    if save_record:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO quotation_records (
                    tender_id, customer_message, source_platform, quote_low, quote_high,
                    suggested_price, workload, turnaround, factors_json, pricing_snapshot_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tender_id,
                    customer_message,
                    source_platform,
                    quote["price_low"],
                    quote["price_high"],
                    quote["suggested_price"],
                    quote["workload"],
                    quote["turnaround"],
                    json.dumps({key: quote[key] for key in ("estimated_sections", "requirement_count", "raw_text_chars", "material_gap_count", "rush", "complex_work", "light_work")}, ensure_ascii=False),
                    json.dumps(quote.get("rules_snapshot") or [], ensure_ascii=False),
                ),
            )
        quote["record"] = row_to_dict(conn.execute("SELECT * FROM quotation_records WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}
    if own_conn:
        conn.close()
    return quote


def list_quotation_records(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM quotation_records
            WHERE tender_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (tender_id,),
        ).fetchall()
    )
    if own_conn:
        conn.close()
    return rows


def render_quote_message(report: dict[str, Any]) -> str:
    tender = report.get("tender") or {}
    return "\n".join(
        [
            f"{tender.get('name') or '本项目'} 技术标编制报价测算如下：",
            f"建议报价区间：{report.get('suggested_price')}。",
            f"预计工作量：{report.get('workload')}；建议交付周期：{report.get('turnaround')}。",
            "报价已包含目录规划、章节初稿、基础审查和交付包归档；客户补充资料或招标范围变化较大时，需要重新确认费用和工期。",
        ]
    )


def render_quote_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 报价测算",
        "",
        f"- 项目名称：{(report.get('tender') or {}).get('name') or ''}",
        f"- 建议报价：{report.get('suggested_price') or ''}",
        f"- 预计工作量：{report.get('workload') or ''}",
        f"- 建议交付周期：{report.get('turnaround') or ''}",
        f"- 预计章节：{report.get('estimated_sections')}",
        f"- 招标要求：{report.get('requirement_count')}",
        f"- 资料缺口：{report.get('material_gap_count')}",
        "",
        "## 加价与折扣明细",
    ]
    for item in report.get("line_items", []):
        lines.append(f"- {item.get('name')}：{item.get('amount')} 元。{item.get('detail')}")
    lines.extend(["", "## 客户报价话术", "", report.get("customer_message") or ""])
    return "\n".join(lines).strip() + "\n"
