from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .ocr import OCRFailed, OCRNotConfigured, ocr_pdf_to_markdown


TECHNICAL_TERMS = [
    "施工组织",
    "施工方案",
    "施工工艺",
    "施工方法",
    "主要施工方法",
    "分部分项",
    "专项施工方案",
    "工艺流程",
    "施工技术措施",
    "工程概况",
    "重难点",
    "质量",
    "安全",
    "文明施工",
    "环境保护",
    "进度",
    "工期",
    "总平面",
    "劳动力",
    "机械设备",
    "BIM",
    "新技术",
    "总承包管理",
]
SCORING_TERMS = ["评分", "分值", "评审", "技术标评分", "技术部分", "得分"]
RISK_TERMS = ["废标", "否决", "无效投标", "不得", "必须", "未按", "不符合"]
CATALOG_TERMS = ["目录", "章节", "格式", "编制要求", "投标文件组成"]
PROJECT_TYPE_TERMS = [
    ("医院", "医院类"),
    ("医疗", "医院类"),
    ("学校", "学校类"),
    ("校区", "学校类"),
    ("厂房", "厂房类"),
    ("产业园", "厂房类"),
    ("市政", "市政类"),
    ("道路", "市政类"),
    ("桥梁", "市政类"),
    ("水利", "水利水务类"),
    ("水务", "水利水务类"),
    ("污水", "水利水务类"),
    ("住宅", "住宅类"),
    ("公寓", "公寓类"),
    ("办公楼", "办公楼类"),
    ("商业", "商业综合体类"),
    ("改造", "改造类"),
]
STRUCTURE_TERMS = ["框架剪力墙", "框剪", "剪力墙", "框架", "钢结构", "混凝土结构", "装配式", "砖混"]
CONSTRAINT_TERMS = ["重难点", "难点", "风险", "不停", "交叉施工", "交通导改", "深基坑", "高支模", "周边环境", "夜间施工"]
SPECIAL_TERMS = ["BIM", "绿色施工", "智慧工地", "医疗专项", "净化", "洁净", "装配式", "海绵城市", "EPC", "总承包管理"]
STRONG_RISK_TERMS = ["废标", "否决", "无效投标", "不予评审", "未能通过", "暗标", "缺项", "得分为 0"]
CORE_REQUIREMENT_LABELS = [
    "项目名称",
    "工程名称",
    "建设地点",
    "项目概况",
    "建设规模",
    "建筑面积",
    "招标范围",
    "承包范围",
    "计划工期",
    "总工期",
    "质量要求",
    "质量目标",
    "安全要求",
    "安全目标",
]


def _core_label(line: str) -> str:
    labels = "|".join(re.escape(label) for label in CORE_REQUIREMENT_LABELS)
    match = re.match(rf"^(?:\d+(?:\.\d+)*\s*)?(?:[、.．]\s*)?({labels})(?:\s*[:：]|\s+)", line.strip())
    return match.group(1) if match else ""


def extract_text(path: Path) -> str:
    return str(extract_file(path)["text"])


def extract_file(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "text": text,
            "file_type": suffix.lstrip("."),
            "action": "markdown_to_text" if suffix == ".md" else "plain_text",
            "text_chars": len(text),
            "page_count": 1 if text else 0,
            "source_path": str(path),
        }
    if suffix == ".docx":
        text = extract_docx_text(path)
        return {
            "text": text,
            "file_type": "docx",
            "action": "docx_to_text",
            "text_chars": len(text),
            "page_count": 0,
            "source_path": str(path),
        }
    if suffix == ".pdf":
        return extract_pdf_file(path)
    raise ValueError(f"Unsupported tender file type: {suffix}")


def extract_docx_text(path: Path) -> str:
    try:
        import docx  # type: ignore

        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip())
    except Exception:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for p in root.findall(".//w:p", ns):
            text = "".join(t.text or "" for t in p.findall(".//w:t", ns)).strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)


def extract_pdf_text(path: Path) -> str:
    return str(extract_pdf_file(path)["text"])


def extract_pdf_file(path: Path) -> dict[str, object]:
    extraction_error = ""
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if text:
            return {
                "text": text,
                "file_type": "pdf",
                "action": "pdf_text_extract",
                "text_chars": len(text),
                "page_count": len(reader.pages),
                "source_path": str(path),
            }
        extraction_error = "PDF 未提取到可用文本，可能是扫描版。"
    except Exception as exc:
        extraction_error = f"PDF 文本提取失败：{type(exc).__name__}: {exc}"

    try:
        result = ocr_pdf_to_markdown(path)
        text = str(result["text"])
        return {
            "text": text,
            "file_type": "pdf",
            "action": "pdf_ocr_to_markdown",
            "text_chars": len(text),
            "page_count": int(result.get("page_count") or 0),
            "source_path": str(path),
            "ocr_job_id": result.get("job_id") or "",
            "ocr_output_dir": result.get("output_dir") or "",
            "markdown_path": result.get("combined_path") or "",
        }
    except OCRNotConfigured as exc:
        raise ValueError(f"{extraction_error} {exc}") from exc
    except OCRFailed as exc:
        raise ValueError(f"{extraction_error} OCR 解析失败：{exc}") from exc


def _line_value(line: str, labels: list[str], max_len: int = 120) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]\s*(.{{1,{max_len}}})", line)
    if not match:
        return ""
    value = re.split(r"[。；;]", match.group(1).strip(), maxsplit=1)[0].strip()
    return value[:max_len].strip()


def _first_labeled(lines: list[str], labels: list[str], max_len: int = 120) -> str:
    for line in lines[:260]:
        value = _line_value(line, labels, max_len=max_len)
        if value:
            return value
    return ""


def _duration_days(lines: list[str]) -> int | None:
    for line in lines[:320]:
        if "工期" not in line and "日历天" not in line:
            continue
        match = re.search(r"(?:计划工期|总工期|工期)[^0-9]{0,24}(\d{1,4})\s*(?:日历天|天)", line)
        if match:
            return int(match.group(1))
    return None


def _infer_project_type(lines: list[str]) -> str:
    sample = "\n".join(lines[:160])
    for term, label in PROJECT_TYPE_TERMS:
        if term in sample:
            return label
    return ""


def _infer_structure(lines: list[str]) -> str:
    labeled = _first_labeled(lines, ["结构形式", "结构类型", "主体结构"], max_len=80)
    if labeled:
        return labeled
    sample = "\n".join(lines[:220])
    for term in STRUCTURE_TERMS:
        if term in sample:
            return term
    return ""


def _floor_info(lines: list[str]) -> str:
    labeled = _first_labeled(lines, ["层数", "建筑层数"], max_len=80)
    if labeled:
        return labeled
    for line in lines[:220]:
        match = re.search(r"(地下\s*\d+\s*层).*?(地上\s*\d+\s*层)", line)
        if match:
            return f"{match.group(1).strip()}，{match.group(2).strip()}"
        match = re.search(r"(地上\s*\d+\s*层).*?(地下\s*\d+\s*层)", line)
        if match:
            return f"{match.group(2).strip()}，{match.group(1).strip()}"
    return ""


def _collect_relevant(lines: list[str], labels: list[str], terms: list[str], limit: int = 3) -> str:
    found: list[str] = []
    for index, line in enumerate(lines[:360]):
        labeled = _line_value(line, labels, max_len=160) if labels else ""
        if labeled:
            expanded = _expanded_clause(lines, index)
            found.append(_line_value(expanded, labels, max_len=260) or labeled)
        elif any(term in line for term in terms):
            if terms is SPECIAL_TERMS and not any(cue in line for cue in ("要求", "须", "应", "重点", "专项", "采用", "实施")):
                continue
            found.append(line[:160])
        if len(found) >= limit:
            break
    return "\n".join(dict.fromkeys(item.strip() for item in found if item.strip()))


def extract_profile_overview(lines: list[str], project_name: str) -> dict[str, object]:
    building_area = _first_labeled(lines, ["建设规模", "工程规模", "建筑面积", "总建筑面积"], max_len=120)
    if not building_area:
        for line in lines[:220]:
            match = re.search(r"(?:总建筑面积|建筑面积)[约为\s:：]*(\d+(?:\.\d+)?\s*(?:万)?平方米)", line)
            if match:
                building_area = match.group(1)
                break
    return {
        "project_name": project_name,
        "project_type": _infer_project_type(lines),
        "structure_type": _infer_structure(lines),
        "building_area": building_area,
        "floor_info": _floor_info(lines),
        "duration_days": _duration_days(lines),
        "quality_target": _first_labeled(lines, ["质量目标", "质量要求", "质量标准"], max_len=100),
        "safety_target": _first_labeled(lines, ["安全目标", "安全文明目标", "安全要求"], max_len=120),
        "green_target": _first_labeled(lines, ["绿色施工目标", "绿色施工要求", "环保目标", "环境保护目标"], max_len=120),
        "contract_scope": _collect_relevant(lines, ["招标范围", "承包范围", "施工范围"], ["范围包括", "施工内容"], limit=2),
        "site_conditions": _collect_relevant(lines, ["现场条件", "施工条件", "现场情况"], ["周边环境", "场地狭小", "交通", "不停"], limit=3),
        "key_constraints": _collect_relevant(lines, ["关键约束", "重点难点", "工程重难点"], CONSTRAINT_TERMS, limit=4),
        "special_requirements": _collect_relevant(lines, ["特殊要求", "专项要求"], SPECIAL_TERMS, limit=4),
    }


def classify_requirement(line: str) -> tuple[str, str]:
    if any(term in line for term in RISK_TERMS):
        return "risk", "high"
    if any(term in line for term in SCORING_TERMS):
        return "scoring", "high"
    if any(term in line for term in CATALOG_TERMS):
        return "catalog", "normal"
    if any(term in line for term in TECHNICAL_TERMS):
        return "technical", "normal"
    return "general", "normal"


def _is_page_or_catalog_line(line: str) -> bool:
    compact = line.strip()
    if re.fullmatch(r"\d{1,4}", compact):
        return True
    if re.search(r"\.{4,}\s*\d*\s*$", compact):
        return True
    return False


def _expanded_clause(lines: list[str], index: int, max_lines: int = 4, max_len: int = 260) -> str:
    parts = [lines[index].strip()]
    first_label = _core_label(parts[0])
    if first_label in ("项目名称", "工程名称", "建设地点", "计划工期", "总工期", "质量要求", "质量目标", "安全要求", "安全目标") and re.search(r"[:：]\s*\S", parts[0]):
        return parts[0][:max_len]
    for offset in range(1, max_lines):
        if index + offset >= len(lines):
            break
        current = "".join(parts).strip()
        if re.search(r"[。；;]$", current):
            break
        next_line = lines[index + offset].strip()
        if _is_page_or_catalog_line(next_line):
            continue
        if _core_label(next_line):
            break
        if any(term in next_line for term in ("评分因素", "评分标准", "参考评分标准")):
            break
        if re.match(r"^(?:第[一二三四五六七八九十]+[章节条]|\d+(?:\.\d+)+)\s*\S", next_line):
            break
        if len(current) + len(next_line) > max_len:
            break
        parts.append(next_line)
    return "".join(parts)[:max_len].strip()


def _title_suffix(parts: list[str]) -> tuple[list[str], list[str]]:
    split_at = len(parts)
    count = 0
    for index in range(len(parts) - 1, -1, -1):
        part = parts[index].strip()
        if (
            not part
            or len(part) > 18
            or re.search(r"[。；;，,：:]$", part)
            or any(term in part for term in ("合理", "可行", "确保", "符合", "满足", "禁止", "是否"))
        ):
            break
        split_at = index
        count += 1
        if count >= 4:
            break
    return parts[:split_at], parts[split_at:]


def _scoring_section(lines: list[str]) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if "评分因素" not in line or "评分标准" not in line:
            continue
        context = "".join(lines[max(0, index - 20) : index + 1]).replace(" ", "")
        if "施工组织设计" not in context:
            continue
        end = min(len(lines), index + 180)
        for cursor in range(index + 10, end):
            nearby = "".join(lines[cursor : min(len(lines), cursor + 2)]).replace(" ", "")
            if "综合标" in nearby and ("总分" in nearby or "评审项目" in nearby):
                end = cursor
                break
        return index + 1, end
    return None


def _extract_scoring_requirements(lines: list[str]) -> list[dict[str, str]]:
    section = _scoring_section(lines)
    if not section:
        return []
    start, end = section
    requirements: list[dict[str, str]] = []
    buffer: list[str] = []
    current: dict[str, object] | None = None

    def finish(description_parts: list[str]) -> None:
        nonlocal current
        if not current:
            return
        description = "".join(description_parts).strip(" ，,；;")
        title = str(current["title"]).strip()
        score = int(current["score"])
        if title:
            content = f"{title}（{score}分）"
            if description:
                content += f"：{description}"
            requirements.append(
                {
                    "kind": "scoring",
                    "content": content[:500],
                    "source_hint": f"line:{current['line']}",
                    "priority": "high",
                    "status": "pending",
                }
            )
        current = None

    for index in range(start, end):
        line = lines[index].strip()
        if not line or re.search(r"\.{4,}\s*\d*\s*$", line):
            continue
        if line.startswith(("1、各档次", "1.各档次", "各档次的标准")):
            finish(buffer)
            break
        titled_score = re.match(r"^([^\d。；;，,：（(）)]{2,30}?)\s+(\d{1,3})(?:\s+(.+))?$", line)
        score_first = re.match(r"^(\d{1,3})(?:\s+(.+))?$", line)
        if titled_score:
            finish(buffer)
            current = {"title": titled_score.group(1), "score": int(titled_score.group(2)), "line": index + 1}
            buffer = [titled_score.group(3)] if titled_score.group(3) else []
            continue
        if score_first:
            description, title_parts = _title_suffix(buffer)
            if not title_parts:
                continue
            finish(description)
            title = "".join(title_parts).strip()
            current = {"title": title, "score": int(score_first.group(1)), "line": index + 1}
            buffer = [score_first.group(2)] if score_first.group(2) else []
            continue
        buffer.append(line)
    else:
        finish(buffer)
    return [item for item in requirements if item["content"]]


def _requirement_key(content: str) -> str:
    key = re.sub(r"\s+", "", content)
    key = re.sub(r"^(?:第[一二三四五六七八九十]+[章节条]|[A-Za-z]?\d+(?:\.\d+)*[、.．]?)+", "", key)
    return key[:180]


def _append_requirement(
    target: list[dict[str, str]],
    seen: set[str],
    content: str,
    kind: str,
    priority: str,
    line_number: int,
) -> None:
    content = re.sub(r"\s+", " ", content).strip()
    if len(content) < 6 or _is_page_or_catalog_line(content):
        return
    key = _requirement_key(content)
    if not key or key in seen:
        return
    seen.add(key)
    target.append(
        {
            "kind": kind,
            "content": content[:500],
            "source_hint": f"line:{line_number}",
            "priority": priority,
            "status": "pending",
        }
    )


def parse_tender_text(text: str, fallback_name: str) -> dict[str, object]:
    normalized = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    project_name = fallback_name
    for line in lines[:120]:
        match = re.search(r"(?:项目名称|工程名称|招标项目名称)[:：\s]+(.{4,80})", line)
        if match:
            project_name = match.group(1).strip().rstrip("；;。")
            break

    requirements: list[dict[str, str]] = []
    seen: set[str] = set()
    scoring_section = _scoring_section(lines)

    for item in _extract_scoring_requirements(lines):
        _append_requirement(
            requirements,
            seen,
            item["content"],
            item["kind"],
            item["priority"],
            int(item["source_hint"].split(":", 1)[1]),
        )

    seen_core_labels: set[str] = set()
    for index, line in enumerate(lines):
        if scoring_section and scoring_section[0] - 1 <= index < scoring_section[1]:
            continue
        if _is_page_or_catalog_line(line):
            continue
        core_label = _core_label(line)
        if core_label:
            if core_label in seen_core_labels:
                continue
            seen_core_labels.add(core_label)
            clause = _expanded_clause(lines, index)
            priority = "high" if core_label in ("计划工期", "总工期", "质量要求", "质量目标", "安全要求", "安全目标") else "normal"
            _append_requirement(requirements, seen, clause, "technical", priority, index + 1)

    technical_count = 0
    risk_count = 0
    for index, line in enumerate(lines):
        if scoring_section and scoring_section[0] - 1 <= index < scoring_section[1]:
            continue
        if _is_page_or_catalog_line(line) or len(line) > 260:
            continue
        if "评分标准" in line or "评分因素" in line:
            continue
        kind, priority = classify_requirement(line)
        has_instruction = any(term in line for term in ("要求", "应", "须", "措施", "方案", "计划", "体系", "编制", "标准"))
        is_targeted_scoring = kind == "scoring" and ("技术标评分" in line or "施工组织设计" in line)
        if (kind in {"technical", "catalog"} or is_targeted_scoring) and has_instruction and technical_count < 45:
            _append_requirement(requirements, seen, _expanded_clause(lines, index, max_lines=3), kind, priority, index + 1)
            technical_count += 1
        elif any(term in line for term in STRONG_RISK_TERMS) and risk_count < 20:
            _append_requirement(requirements, seen, _expanded_clause(lines, index, max_lines=3), "risk", "high", index + 1)
            risk_count += 1
        if len(requirements) >= 100:
            break

    overview = extract_profile_overview(lines, project_name)
    overview.update(
        {
            "line_count": len(lines),
            "char_count": len(normalized),
        }
    )
    return {"overview": overview, "requirements": requirements}


def dumps(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
