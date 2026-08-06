from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import sqlite3
import textwrap
import zipfile
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .settings import ASSET_DIR, PROJECT_ROOT


FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)
FONT_BOLD_CANDIDATES = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
)


def _font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return result[:80] or "asset"


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_asset_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _asset_row(row: dict[str, Any]) -> dict[str, Any]:
    row["file_exists"] = resolve_asset_path(str(row.get("file_path") or "")).exists()
    source_kind = str(row.get("source_kind") or "")
    if not str(row.get("visual_class") or "").strip() or row.get("visual_class") == "reference":
        row["visual_class"] = {
            "generated_schematic": "technical_diagram",
            "ai_generated_hybrid": "ai_scene",
            "docx_embedded": "historical_reference",
            "user_upload": "real_material",
        }.get(source_kind, str(row.get("visual_class") or "reference"))
    row["can_be_evidence"] = row["visual_class"] == "real_material" and row.get("review_status") == "已通过"
    try:
        row["overlay"] = json.loads(row.get("overlay_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        row["overlay"] = {}
    return row


def list_visual_assets(tender_id: int | None = None, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    if tender_id is None:
        rows = rows_to_dicts(conn.execute("SELECT * FROM visual_assets WHERE status = 'active' ORDER BY id DESC").fetchall())
    else:
        rows = rows_to_dicts(
            conn.execute(
                "SELECT * FROM visual_assets WHERE status = 'active' AND (tender_id = ? OR tender_id IS NULL) ORDER BY id DESC",
                (tender_id,),
            ).fetchall()
        )
    result = [_asset_row(row) for row in rows]
    if own_conn:
        conn.close()
    return result


def get_visual_asset(asset_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(conn.execute("SELECT * FROM visual_assets WHERE id = ?", (asset_id,)).fetchone())
    if not row:
        raise ValueError(f"Visual asset not found: {asset_id}")
    result = _asset_row(row)
    if own_conn:
        conn.close()
    return result


def register_visual_asset(
    tender_id: int | None,
    *,
    asset_type: str,
    name: str,
    file_path: Path,
    source_path: str = "",
    source_kind: str = "generated",
    industry: str = "",
    section_title: str = "",
    tags: str = "",
    caption: str = "",
    visual_class: str = "reference",
    review_status: str = "待复核",
    review_notes: str = "",
    disclaimer: str = "",
    generation_prompt: str = "",
    technical_basis: str = "",
    overlay: dict[str, Any] | None = None,
    ai_model: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    from PIL import Image

    own_conn = conn is None
    conn = conn or connect()
    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    width = height = 0
    try:
        with Image.open(file_path) as image:
            width, height = image.size
    except Exception:
        pass
    digest = _sha256(file_path)
    existing = row_to_dict(
        conn.execute(
            "SELECT * FROM visual_assets WHERE COALESCE(tender_id, -1) = COALESCE(?, -1) AND sha256 = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (tender_id, digest),
        ).fetchone()
    )
    if existing:
        result = _asset_row(existing)
        if own_conn:
            conn.close()
        return result
    with conn:
        cur = conn.execute(
            """
            INSERT INTO visual_assets (
                tender_id, asset_type, name, file_path, source_path, source_kind,
                industry, section_title, tags, caption, width, height, sha256,
                visual_class, review_status, review_notes, disclaimer,
                generation_prompt, technical_basis, overlay_json, ai_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                asset_type,
                name,
                _relative_path(file_path),
                source_path,
                source_kind,
                industry,
                section_title,
                tags,
                caption,
                width,
                height,
                digest,
                visual_class,
                review_status,
                review_notes,
                disclaimer,
                generation_prompt,
                technical_basis,
                json.dumps(overlay or {}, ensure_ascii=False),
                ai_model,
            ),
        )
    result = _asset_row(row_to_dict(conn.execute("SELECT * FROM visual_assets WHERE id = ?", (cur.lastrowid,)).fetchone()) or {})
    if own_conn:
        conn.close()
    return result


def _arrow(draw: Any, start: tuple[int, int], end: tuple[int, int], *, color: str = "#3f5f7f", width: int = 5) -> None:
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 16
    for delta in (2.55, -2.55):
        point = (end[0] + int(length * math.cos(angle + delta)), end[1] + int(length * math.sin(angle + delta)))
        draw.line([end, point], fill=color, width=width)


def _centered_text(draw: Any, box: tuple[int, int, int, int], text: str, font: Any, fill: str = "#18324b") -> None:
    left, top, right, bottom = box
    max_chars = max(4, int((right - left) / max(15, getattr(font, "size", 24)) * 1.7))
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=max_chars) or [""])
    line_height = int(getattr(font, "size", 24) * 1.35)
    y = top + max(0, ((bottom - top) - line_height * len(lines)) // 2)
    for line in lines[:4]:
        bounds = draw.textbbox((0, 0), line, font=font)
        x = left + ((right - left) - (bounds[2] - bounds[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _canvas(title: str, width: int, height: int) -> tuple[Any, Any]:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 92), fill="#eef4f8")
    draw.rectangle((0, 90, width, 96), fill="#2d6d93")
    draw.text((42, 24), title, font=_font(34, bold=True), fill="#14324a")
    draw.text((width - 285, 35), "技术标施工示意图", font=_font(20), fill="#557084")
    return image, draw


def render_organization_chart(path: Path, title: str, data: dict[str, Any]) -> None:
    roles = list(data.get("roles") or [])
    departments = list(data.get("departments") or [])
    image, draw = _canvas(title, 2200, 1450)
    root_box = (770, 150, 1430, 270)
    draw.rounded_rectangle(root_box, radius=16, fill="#1f5d7a", outline="#164257", width=4)
    _centered_text(draw, root_box, str(data.get("root") or "项目经理"), _font(32, bold=True), "white")

    role_boxes: list[tuple[int, int, int, int]] = []
    role_count = max(1, len(roles))
    gap = 35
    box_width = min(430, int((1980 - gap * (role_count - 1)) / role_count))
    total_width = role_count * box_width + (role_count - 1) * gap
    start_x = (2200 - total_width) // 2
    for index, role in enumerate(roles or ["项目总工程师"]):
        box = (start_x + index * (box_width + gap), 400, start_x + index * (box_width + gap) + box_width, 520)
        role_boxes.append(box)
        draw.rounded_rectangle(box, radius=14, fill="#d9ebf4", outline="#2d6d93", width=4)
        _centered_text(draw, box, str(role), _font(27, bold=True))

    root_center = (root_box[0] + root_box[2]) // 2
    role_centers = [(box[0] + box[2]) // 2 for box in role_boxes]
    role_bus_y = 340
    draw.line((root_center, root_box[3], root_center, role_bus_y), fill="#3f5f7f", width=5)
    draw.line((min(role_centers), role_bus_y, max(role_centers), role_bus_y), fill="#3f5f7f", width=5)
    for box, center in zip(role_boxes, role_centers):
        _arrow(draw, (center, role_bus_y), (center, box[1]), width=4)

    dept_cols = 4
    dept_width, dept_height = 450, 125
    dept_boxes: list[tuple[int, int, int, int]] = []
    for index, dept in enumerate(departments):
        row, col = divmod(index, dept_cols)
        x = 90 + col * 525
        y = 760 + row * 250
        box = (x, y, x + dept_width, y + dept_height)
        dept_boxes.append(box)
        draw.rounded_rectangle(box, radius=12, fill="#f7fafc", outline="#7894a8", width=3)
        _centered_text(draw, box, str(dept), _font(26, bold=True))

    management_center_y = max(box[3] for box in role_boxes)
    trunk_end_y = 700 + max(0, math.ceil(len(dept_boxes) / dept_cols) - 1) * 250
    draw.line((root_center, management_center_y, root_center, trunk_end_y), fill="#3f5f7f", width=5)
    for row_index in range(math.ceil(len(dept_boxes) / dept_cols)):
        row_boxes = dept_boxes[row_index * dept_cols : (row_index + 1) * dept_cols]
        if not row_boxes:
            continue
        bus_y = row_boxes[0][1] - 55
        centers = [(box[0] + box[2]) // 2 for box in row_boxes]
        draw.line((min(centers), bus_y, max(centers), bus_y), fill="#3f5f7f", width=4)
        draw.line((root_center, bus_y - 5, root_center, bus_y + 5), fill="#3f5f7f", width=5)
        for box, center in zip(row_boxes, centers):
            _arrow(draw, (center, bus_y), (center, box[1]), width=3)
    image.save(path, dpi=(300, 300))


def render_flow_chart(path: Path, title: str, data: dict[str, Any]) -> None:
    steps = [str(item) for item in (data.get("steps") or [])]
    notes = str(data.get("note") or "流程节点须经检查确认后转序，异常时返回上一控制节点整改。")
    cols = 4
    rows = max(1, math.ceil(len(steps) / cols))
    height = 470 + rows * 260
    image, draw = _canvas(title, 2200, height)
    boxes: list[tuple[int, int, int, int]] = []
    for index, step in enumerate(steps):
        row, raw_col = divmod(index, cols)
        col = raw_col if row % 2 == 0 else cols - 1 - raw_col
        x = 90 + col * 525
        y = 190 + row * 255
        box = (x, y, x + 430, y + 125)
        boxes.append(box)
        fill = "#e7f2f5" if index not in {0, len(steps) - 1} else "#d8eadf"
        draw.rounded_rectangle(box, radius=18, fill=fill, outline="#2d6d93", width=4)
        draw.ellipse((x + 18, y + 38, x + 68, y + 88), fill="#2d6d93")
        number = str(index + 1)
        number_font = _font(22, bold=True)
        bounds = draw.textbbox((0, 0), number, font=number_font)
        draw.text((x + 43 - (bounds[2] - bounds[0]) // 2, y + 62 - (bounds[3] - bounds[1]) // 2), number, font=number_font, fill="white")
        _centered_text(draw, (x + 72, y, x + 420, y + 125), step, _font(25, bold=True))
    for first, second in zip(boxes, boxes[1:]):
        start = ((first[0] + first[2]) // 2, first[3]) if abs(first[1] - second[1]) > 20 else (first[2], (first[1] + first[3]) // 2)
        end = ((second[0] + second[2]) // 2, second[1]) if abs(first[1] - second[1]) > 20 else (second[0], (second[1] + second[3]) // 2)
        if first[0] > second[0] and abs(first[1] - second[1]) < 20:
            start, end = (first[0], (first[1] + first[3]) // 2), (second[2], (second[1] + second[3]) // 2)
        _arrow(draw, start, end)
    draw.rounded_rectangle((90, height - 150, 2110, height - 55), radius=12, fill="#f3f6f8", outline="#b8c8d3", width=2)
    _centered_text(draw, (110, height - 145, 2090, height - 60), notes, _font(22), "#425b6d")
    image.save(path, dpi=(300, 300))


def render_gantt_chart(path: Path, title: str, data: dict[str, Any]) -> None:
    tasks = list(data.get("tasks") or [])
    total_days = max(1, int(data.get("total_days") or 1))
    width = 2600
    row_height = 72
    height = 300 + row_height * len(tasks)
    image, draw = _canvas(title, width, height)
    label_width = 620
    chart_left, chart_right = label_width + 40, width - 70
    chart_width = chart_right - chart_left
    top = 190
    divisions = 10
    for index in range(divisions + 1):
        x = chart_left + int(chart_width * index / divisions)
        draw.line((x, top - 20, x, height - 70), fill="#cbd7df", width=2)
        day = round(total_days * index / divisions)
        label = f"第 {day} 天"
        bounds = draw.textbbox((0, 0), label, font=_font(20))
        draw.text((x - (bounds[2] - bounds[0]) // 2, top - 60), label, font=_font(20), fill="#4f6677")
    for index, task in enumerate(tasks):
        y = top + index * row_height
        if index % 2:
            draw.rectangle((55, y - 10, chart_right, y + row_height - 10), fill="#f7f9fb")
        name = str(task.get("name") or f"任务 {index + 1}")
        start = max(0, int(task.get("start") or 0))
        duration = max(1, int(task.get("duration") or 1))
        end = min(total_days, start + duration)
        draw.text((70, y + 9), f"{index + 1}. {name}", font=_font(23, bold=True), fill="#243f55")
        draw.text((440, y + 12), f"{start}-{end} 天", font=_font(19), fill="#607789")
        x1 = chart_left + int(chart_width * start / total_days)
        x2 = chart_left + int(chart_width * end / total_days)
        color = "#2d6d93" if not task.get("milestone") else "#b85c38"
        draw.rounded_rectangle((x1, y + 11, max(x1 + 8, x2), y + 47), radius=8, fill=color)
        if task.get("milestone"):
            draw.polygon([(x2, y + 4), (x2 + 18, y + 29), (x2, y + 54), (x2 - 18, y + 29)], fill="#b85c38")
    draw.text((70, height - 55), str(data.get("note") or "本横道图为投标阶段建议总控计划，开工日期及节点以合同和批准计划为准。"), font=_font(20), fill="#526b7d")
    image.save(path, dpi=(300, 300))


def render_illustration(path: Path, title: str, data: dict[str, Any]) -> None:
    kind = str(data.get("kind") or "site_layout")
    image, draw = _canvas(title, 2200, 1350)
    if kind == "quality_loop":
        nodes = [(1100, 260, "策划"), (1660, 590, "实施"), (1100, 930, "检查"), (540, 590, "改进")]
        for x, y, label in nodes:
            box = (x - 210, y - 72, x + 210, y + 72)
            draw.rounded_rectangle(box, radius=30, fill="#e3f0f4", outline="#2d6d93", width=5)
            _centered_text(draw, box, label, _font(34, bold=True))
        for first, second in zip(nodes, nodes[1:] + nodes[:1]):
            _arrow(draw, (first[0], first[1]), (second[0], second[1]), width=8)
        _centered_text(draw, (790, 500, 1410, 690), "样板引路\n过程实测\n问题闭环", _font(32, bold=True), "#b35d37")
    elif kind == "bim_coordination":
        center = (1100, 680)
        center_box = (850, 570, 1350, 790)
        draw.rounded_rectangle(center_box, radius=24, fill="#245f7d", outline="#173f54", width=5)
        _centered_text(draw, center_box, "BIM 协同模型", _font(38, bold=True), "white")
        labels = ["结构深化", "机电综合", "净高检查", "预留预埋", "进度模拟", "质量验收"]
        for index, label in enumerate(labels):
            angle = math.pi * 2 * index / len(labels) - math.pi / 2
            x = center[0] + int(720 * math.cos(angle))
            y = center[1] + int(430 * math.sin(angle))
            box = (x - 180, y - 62, x + 180, y + 62)
            draw.rounded_rectangle(box, radius=18, fill="#edf4f7", outline="#5b8399", width=4)
            _centered_text(draw, box, label, _font(28, bold=True))
            _arrow(draw, (x, y), center, width=4)
    else:
        draw.rectangle((100, 175, 2100, 1200), fill="#f7fafb", outline="#607d8d", width=5)
        zones = [
            ((160, 240, 720, 570), "主体施工区", "#dbeaf2"),
            ((790, 240, 1420, 570), "材料加工与堆场", "#e4eee3"),
            ((1490, 240, 2040, 570), "办公生活区", "#f2e9d9"),
            ((160, 690, 900, 1110), "地下及安装作业区", "#e8e4f0"),
            ((1010, 690, 2040, 1110), "临时道路、消防与运输组织", "#e8f0f2"),
        ]
        for box, label, fill in zones:
            draw.rounded_rectangle(box, radius=18, fill=fill, outline="#587487", width=4)
            _centered_text(draw, box, label, _font(31, bold=True))
        _arrow(draw, (220, 630), (1980, 630), color="#b85c38", width=10)
        draw.text((800, 595), "场内主运输通道", font=_font(27, bold=True), fill="#9b482d")
    draw.text((90, 1260), "注：本图为投标阶段功能分区示意，最终位置和尺寸以批准的施工总平面布置图为准。", font=_font(21), fill="#526b7d")
    image.save(path, dpi=(300, 300))


def generate_visual_asset(
    tender_id: int,
    *,
    asset_type: str,
    name: str,
    title: str,
    data: dict[str, Any],
    industry: str = "",
    section_title: str = "",
    caption: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    folder = ASSET_DIR / f"tender_{tender_id}"
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    path = folder / f"{_safe_name(name)}_{fingerprint}.png"
    if asset_type == "organization_chart":
        render_organization_chart(path, title, data)
    elif asset_type == "flow_chart":
        render_flow_chart(path, title, data)
    elif asset_type == "gantt_chart":
        render_gantt_chart(path, title, data)
    else:
        render_illustration(path, title, data)
    result = register_visual_asset(
        tender_id,
        asset_type=asset_type,
        name=name,
        file_path=path,
        source_kind="generated_schematic",
        industry=industry,
        section_title=section_title,
        tags=asset_type,
        caption=caption or title,
        visual_class="technical_diagram",
        review_status="系统生成待复核",
        disclaimer="投标阶段技术示意图，非施工图；正式使用前须结合图纸、方案和现场条件复核。",
        technical_basis="项目资料、章节模板与确定性程序制图规则",
        overlay=data,
        conn=conn,
    )
    if own_conn:
        conn.close()
    return result


def import_docx_images(
    source_path: str,
    *,
    tender_id: int | None = None,
    industry: str = "",
    section_title: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    from PIL import Image

    own_conn = conn is None
    conn = conn or connect()
    source = Path(source_path).resolve()
    if not source.exists() or source.suffix.lower() != ".docx":
        raise ValueError("只支持从现有 DOCX 文件提取图片。")
    target_dir = ASSET_DIR / (f"tender_{tender_id}" if tender_id else "library") / _safe_name(source.stem)
    target_dir.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []
    skipped = 0
    with zipfile.ZipFile(source) as archive:
        members = [name for name in archive.namelist() if name.startswith("word/media/")]
        for index, member in enumerate(members, 1):
            payload = archive.read(member)
            try:
                with Image.open(io.BytesIO(payload)) as image:
                    width, height = image.size
                    image_format = (image.format or "PNG").lower()
                    if width < 480 or height < 260:
                        skipped += 1
                        continue
                    extension = ".jpg" if image_format in {"jpeg", "jpg"} else ".png"
                    target = target_dir / f"image_{index:03d}{extension}"
                    converted = image.convert("RGB") if extension == ".jpg" else image.convert("RGBA")
                    converted.save(target, quality=92)
            except Exception:
                skipped += 1
                continue
            imported.append(
                register_visual_asset(
                    tender_id,
                    asset_type="reference_image",
                    name=f"{source.stem} 示例图片 {index}",
                    file_path=target,
                    source_path=str(source),
                    source_kind="docx_embedded",
                    industry=industry,
                    section_title=section_title,
                    tags="历史标书,示例图片,待人工确认",
                    caption=f"{source.stem}历史资料示例图（使用前人工核对适用性）",
                    visual_class="historical_reference",
                    review_status="待复核",
                    disclaimer="历史资料参考图，不得作为本项目现场实景或履约证明。",
                    technical_basis="历史 DOCX 内嵌图片，来源路径已记录",
                    conn=conn,
                )
            )
    result = {"source_path": str(source), "found": len(members), "imported": len(imported), "skipped": skipped, "assets": imported}
    if own_conn:
        conn.close()
    return result


def import_image_file(
    source_path: str,
    *,
    tender_id: int | None = None,
    asset_type: str = "project_image",
    name: str = "",
    caption: str = "",
    industry: str = "",
    section_title: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    source = Path(source_path).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    folder = ASSET_DIR / (f"tender_{tender_id}" if tender_id else "library") / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{_safe_name(name or source.stem)}_{_sha256(source)[:10]}{source.suffix.lower()}"
    if not target.exists():
        shutil.copy2(source, target)
    return register_visual_asset(
        tender_id,
        asset_type=asset_type,
        name=name or source.stem,
        file_path=target,
        source_path=str(source),
        source_kind="user_upload",
        industry=industry,
        section_title=section_title,
        tags="项目图片",
        caption=caption or source.stem,
        visual_class="real_material",
        review_status="待复核",
        disclaimer="用户上传资料，须核对拍摄项目、时间、授权和适用章节后方可作为证明材料。",
        technical_basis="用户上传原始文件",
        conn=conn,
    )


def update_visual_asset_review(
    asset_id: int,
    *,
    review_status: str,
    review_notes: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    allowed = {"待复核", "系统生成待复核", "已通过", "需修改", "禁止使用"}
    if review_status not in allowed:
        raise ValueError(f"Unsupported review status: {review_status}")
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        conn.execute(
            "UPDATE visual_assets SET review_status = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (review_status, review_notes, asset_id),
        )
    result = get_visual_asset(asset_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def used_visual_assets(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT DISTINCT va.*
            FROM visual_assets va
            JOIN document_blocks db ON db.asset_id = va.id
            WHERE db.tender_id = ? AND db.status = 'active' AND va.status = 'active'
            ORDER BY va.id
            """,
            (tender_id,),
        ).fetchall()
    )
    result = [_asset_row(row) for row in rows]
    if own_conn:
        conn.close()
    return result


def visual_review_summary(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    assets = used_visual_assets(tender_id, conn=conn)
    approved = [item for item in assets if item.get("review_status") == "已通过"]
    rejected = [item for item in assets if item.get("review_status") == "禁止使用"]
    pending = [item for item in assets if item.get("review_status") not in {"已通过", "禁止使用"}]
    missing = [item for item in assets if not item.get("file_exists")]
    return {
        "tender_id": tender_id,
        "total_used": len(assets),
        "approved": len(approved),
        "pending": len(pending),
        "rejected": len(rejected),
        "missing_files": len(missing),
        "ready": len(approved) == len(assets) and not missing and not rejected,
        "items": assets,
    }


def batch_review_visual_assets(
    tender_id: int,
    asset_ids: list[int],
    *,
    review_status: str,
    review_notes: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    allowed_ids = {
        int(row["id"])
        for row in rows_to_dicts(
            conn.execute(
                "SELECT id FROM visual_assets WHERE status = 'active' AND (tender_id = ? OR tender_id IS NULL)",
                (tender_id,),
            ).fetchall()
        )
    }
    selected = sorted({int(item) for item in asset_ids if int(item) in allowed_ids})
    updated = [
        update_visual_asset_review(
            asset_id,
            review_status=review_status,
            review_notes=review_notes,
            conn=conn,
        )
        for asset_id in selected
    ]
    result = {"updated": updated, "summary": visual_review_summary(tender_id, conn=conn)}
    if own_conn:
        conn.close()
    return result


def auto_validate_technical_visuals(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    candidates = [
        item
        for item in used_visual_assets(tender_id, conn=conn)
        if item.get("visual_class") == "technical_diagram" and item.get("source_kind") == "generated_schematic"
    ]
    updated: list[dict[str, Any]] = []
    for item in candidates:
        valid = bool(item.get("file_exists")) and int(item.get("width") or 0) >= 800 and int(item.get("height") or 0) >= 400
        updated.append(
            update_visual_asset_review(
                int(item["id"]),
                review_status="已通过" if valid else "需修改",
                review_notes="程序化图表文件、尺寸和挂接关系自动校验通过。" if valid else "程序化图表文件缺失或尺寸不足，需重新生成。",
                conn=conn,
            )
        )
    result = {"updated": updated, "summary": visual_review_summary(tender_id, conn=conn)}
    if own_conn:
        conn.close()
    return result
