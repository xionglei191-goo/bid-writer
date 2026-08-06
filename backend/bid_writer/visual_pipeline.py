from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .llm_config import environment_value
from .project_profiles import get_project_profile
from .settings import ASSET_DIR
from .visual_assets import _font, _safe_name, register_visual_asset, resolve_asset_path


AI_SCENES: dict[str, dict[str, Any]] = {
    "pile_foundation": {
        "title": "桩基础施工场景示意图",
        "keywords": ["桩基", "灌注桩", "钻孔桩", "旋挖桩"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["测量定位", "钻进成孔", "清孔验收", "钢筋笼安装", "导管安装", "混凝土灌注"],
        "subject": "rotary drilling rig constructing cast-in-place bored piles, casing, slurry equipment, reinforcement cage and concrete truck",
        "basis": "桩基础专项方案、地勘资料、设计桩表和试桩成果",
    },
    "rebar_work": {
        "title": "钢筋加工与安装施工场景示意图",
        "keywords": ["钢筋加工", "钢筋绑扎", "钢筋工程"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["原材验收", "下料加工", "分类堆放", "运输就位", "绑扎连接", "隐蔽验收"],
        "subject": "organized rebar fabrication shelter and reinforcement installation on a large building construction site",
        "basis": "结构施工图、钢筋翻样单、连接工艺评定和验收规范",
    },
    "concrete_pour": {
        "title": "混凝土浇筑施工场景示意图",
        "keywords": ["混凝土浇筑", "混凝土工程", "大体积混凝土"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["配合比确认", "入模检查", "分层浇筑", "振捣密实", "表面收整", "养护测温"],
        "subject": "concrete pump truck and workers placing concrete on a reinforced concrete hospital building slab, safe organized site",
        "basis": "结构图、施工缝设置、配合比、浇筑令和温控方案",
    },
    "waterproofing": {
        "title": "地下防水施工场景示意图",
        "keywords": ["地下防水", "防水工程", "防水施工"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["基层处理", "节点附加层", "大面施工", "搭接密封", "成品保护", "隐蔽验收"],
        "subject": "workers applying waterproof membrane to a clean underground structure, visible corner reinforcement and protected finished membrane",
        "basis": "防水设计、节点详图、材料系统和样板验收标准",
    },
    "mep_installation": {
        "title": "机电综合安装施工场景示意图",
        "keywords": ["机电安装", "机电工程", "管线综合", "综合支吊架"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["BIM 深化", "支吊架定位", "管线安装", "设备连接", "测试冲洗", "联合调试"],
        "subject": "hospital building mechanical electrical plumbing installation with coordinated ducts, pipes, cable trays and modular supports",
        "basis": "机电施工图、BIM 综合模型、净高要求和设备技术文件",
    },
    "interior_fitout": {
        "title": "医院装饰装修施工场景示意图",
        "keywords": ["装饰装修", "室内装修", "洁净区域"],
        "preferred_section": "施工工艺及主要施工方法",
        "steps": ["样板确认", "基层施工", "机电末端", "饰面安装", "洁净保护", "分区移交"],
        "subject": "clean hospital interior fit-out construction, workers installing wall ceiling and MEP terminals with finished-product protection",
        "basis": "装修深化图、医疗工艺条件、材料样板和洁净控制要求",
    },
    "safety_site": {
        "title": "安全文明施工标准化场景示意图",
        "keywords": ["安全文明", "扬尘治理", "临边防护", "文明施工"],
        "preferred_section": "安全文明施工及环境保护",
        "steps": ["封闭围挡", "通道分流", "临边防护", "材料定置", "扬尘控制", "每日检查"],
        "subject": "standardized large construction site with guarded edges, separated pedestrian routes, covered materials, wheel wash and dust control",
        "basis": "安全文明施工方案、危大工程清单、地方扬尘标准和现场总平面",
    },
    "bim_scene": {
        "title": "BIM 多专业协同应用场景示意图",
        "keywords": ["BIM", "智慧建造", "数字化建造"],
        "preferred_section": "BIM及智慧建造应用",
        "steps": ["模型整合", "碰撞检查", "净高优化", "方案交底", "现场复核", "竣工交付"],
        "subject": "construction engineers coordinating a hospital BIM model on large screens, realistic project office, no readable screen text",
        "basis": "BIM 实施策划、模型精度标准、专业界面和交付要求",
    },
}


def image_generation_settings() -> dict[str, Any]:
    api_key = environment_value("IMAGE_API_KEY") or environment_value("OPENAI_API_KEY")
    base_url = environment_value("IMAGE_BASE_URL") or environment_value("OPENAI_BASE_URL", "https://api.openai.com/v1")
    endpoint = environment_value("IMAGE_API_URL") or f"{base_url.rstrip('/')}/images/generations"
    model = environment_value("IMAGE_MODEL")
    return {
        "configured": bool(api_key and model),
        "endpoint": endpoint,
        "model": model,
        "api_key_env": "IMAGE_API_KEY" if environment_value("IMAGE_API_KEY") else ("OPENAI_API_KEY" if api_key else ""),
        "note": "已配置图片生成服务。" if api_key and model else "未配置 IMAGE_MODEL；系统仍可生成提示词，并接收外部生图底图进行合成。",
    }


def _draft_sections(tender_id: int, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            "SELECT section_title, content FROM drafts WHERE tender_id = ? ORDER BY id",
            (tender_id,),
        ).fetchall()
    )


def _scene_prompt(scene: dict[str, Any], profile: dict[str, Any]) -> str:
    project_type = str(profile.get("project_type") or "large public building")
    site = str(profile.get("site_conditions") or "organized active construction site")
    return (
        "Use case: scientific-educational. Asset type: technical bid construction scene base image. "
        f"Create a realistic, technically plausible wide illustration of {scene['subject']}. "
        f"Project context: {project_type}; site constraints: {site}. "
        "Show safe work methods, correct personal protective equipment, orderly material placement and realistic construction machinery. "
        "No written words, no labels, no arrows, no numbers, no logos, no watermark, no company branding. "
        "Do not invent project-specific dimensions or claim this is a real project photograph. "
        "Landscape 16:9 composition with clear empty margins for later programmatic Chinese annotations."
    )


def build_visual_plan(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    profile = get_project_profile(tender_id, conn=conn)
    drafts = _draft_sections(tender_id, conn)
    technical = rows_to_dicts(
        conn.execute(
            """
            SELECT id, name, asset_type, section_title, caption, review_status
            FROM visual_assets
            WHERE tender_id = ? AND status = 'active' AND source_kind = 'generated_schematic'
            ORDER BY id
            """,
            (tender_id,),
        ).fetchall()
    )
    ai_plans: list[dict[str, Any]] = []
    for scene_key, scene in AI_SCENES.items():
        matches = [row for row in drafts if any(keyword in str(row.get("content") or "") for keyword in scene["keywords"])]
        if not matches:
            continue
        preferred = next(
            (row for row in matches if scene["preferred_section"] in str(row.get("section_title") or "")),
            matches[0],
        )
        existing = row_to_dict(
            conn.execute(
                """
                SELECT id, review_status FROM visual_assets
                WHERE tender_id = ? AND status = 'active' AND source_kind = 'ai_generated_hybrid' AND tags LIKE ?
                ORDER BY id DESC LIMIT 1
                """,
                (tender_id, f"%scene:{scene_key}%"),
            ).fetchone()
        )
        ai_plans.append(
            {
                "scene_key": scene_key,
                "title": scene["title"],
                "section_title": str(preferred.get("section_title") or scene["preferred_section"]),
                "method": "ai_hybrid",
                "steps": scene["steps"],
                "technical_basis": scene["basis"],
                "prompt": _scene_prompt(scene, profile),
                "status": "已生成" if existing else "待生成",
                "asset_id": existing.get("id") if existing else None,
                "review_status": existing.get("review_status") if existing else "待复核",
                "disclaimer": "AI 生成施工场景底图；程序叠加工序标注；非现场实景、非施工图。",
            }
        )
    real_required = [
        {
            "title": "项目现场及周边条件实景",
            "section_title": "工程概况",
            "method": "real_only",
            "reason": "现场条件、交通组织和周边环境必须来自本项目真实资料，不允许 AI 生成替代。",
        },
        {
            "title": "企业类似业绩与设备实拍",
            "section_title": "施工总体部署",
            "method": "real_only",
            "reason": "履约证明、设备投入和企业业绩只能引用可核验的真实图片。",
        },
    ]
    result = {
        "tender": {"id": tender_id, "name": tender.get("name"), "industry": tender.get("industry")},
        "settings": image_generation_settings(),
        "summary": {
            "technical_diagrams": len(technical),
            "ai_hybrid_plans": len(ai_plans),
            "ai_generated": sum(1 for item in ai_plans if item["asset_id"]),
            "real_only_requirements": len(real_required),
        },
        "technical_diagrams": technical,
        "ai_hybrid_plans": ai_plans,
        "real_only_requirements": real_required,
        "policy": {
            "technical_diagram": "组织关系、流程、节点、横道图和总平面采用确定性程序制图。",
            "ai_scene": "AI 只生成无文字场景底图，中文工序、箭头、图例和免责声明由程序叠加。",
            "real_material": "现场实景、企业业绩、证书和设备证明必须上传真实资料并人工审核。",
        },
    }
    if own_conn:
        conn.close()
    return result


def _request_ai_base(prompt: str, output_path: Path) -> str:
    settings = image_generation_settings()
    if not settings["configured"]:
        raise ValueError(settings["note"])
    api_key = environment_value("IMAGE_API_KEY") or environment_value("OPENAI_API_KEY")
    payload = {"model": settings["model"], "prompt": prompt, "size": "1536x1024", "n": 1}
    request = urllib.request.Request(
        str(settings["endpoint"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:  # noqa: S310 - user-configured endpoint.
        data = json.loads(response.read().decode("utf-8"))
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(str(item["url"]), timeout=120) as image_response:  # noqa: S310
            output_path.write_bytes(image_response.read())
    else:
        raise ValueError("图片生成响应未包含 b64_json 或 url。")
    return str(settings["model"])


def _compose_hybrid(base_path: Path, output_path: Path, title: str, steps: list[str], disclaimer: str) -> None:
    from PIL import Image, ImageDraw, ImageOps

    with Image.open(base_path) as raw:
        base = ImageOps.fit(raw.convert("RGB"), (2200, 1120), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (2200, 1450), "white")
    canvas.paste(base, (0, 100))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 2200, 100), fill="#eef4f8")
    draw.rectangle((0, 94, 2200, 100), fill="#2d6d93")
    draw.text((42, 25), title, font=_font(34, bold=True), fill="#14324a")
    draw.text((1690, 33), "AI 场景底图 + 程序化标注", font=_font(21), fill="#557084")
    band_top = 1220
    draw.rectangle((0, band_top, 2200, 1450), fill="#f7fafc")
    count = max(1, len(steps))
    gap = 20
    box_width = int((2080 - gap * (count - 1)) / count)
    for index, step in enumerate(steps):
        left = 60 + index * (box_width + gap)
        right = left + box_width
        draw.rounded_rectangle((left, 1260, right, 1345), radius=12, fill="#e5f0f5", outline="#2d6d93", width=3)
        draw.ellipse((left + 12, 1281, left + 54, 1323), fill="#2d6d93")
        number = str(index + 1)
        draw.text((left + 24, 1284), number, font=_font(19, bold=True), fill="white")
        draw.text((left + 64, 1281), str(step), font=_font(21, bold=True), fill="#18324b")
        if index < count - 1:
            draw.line((right + 3, 1302, right + gap - 3, 1302), fill="#3f5f7f", width=3)
            draw.polygon([(right + gap - 3, 1302), (right + gap - 16, 1294), (right + gap - 16, 1310)], fill="#3f5f7f")
    draw.text((60, 1382), disclaimer, font=_font(21), fill="#8a4933")
    canvas.save(output_path, dpi=(300, 300), quality=94)


def generate_hybrid_visual(
    tender_id: int,
    *,
    scene_key: str,
    source_path: str = "",
    section_title: str = "",
    attach: bool = True,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    if scene_key not in AI_SCENES:
        raise ValueError(f"Unsupported scene: {scene_key}")
    own_conn = conn is None
    conn = conn or connect()
    scene = AI_SCENES[scene_key]
    profile = get_project_profile(tender_id, conn=conn)
    prompt = _scene_prompt(scene, profile)
    folder = ASSET_DIR / f"tender_{tender_id}" / "ai_hybrid"
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256((scene_key + prompt + source_path).encode("utf-8")).hexdigest()[:12]
    base_path = folder / f"{_safe_name(scene['title'])}_base_{fingerprint}.png"
    ai_model = "external_import"
    if source_path:
        source = resolve_asset_path(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        from PIL import Image

        with Image.open(source) as image:
            image.convert("RGB").save(base_path, quality=94)
    else:
        ai_model = _request_ai_base(prompt, base_path)
    disclaimer = "AI生成施工场景底图；工序标注由程序叠加；非现场实景、非施工图，使用前须结合专项方案人工复核。"
    final_path = folder / f"{_safe_name(scene['title'])}_{fingerprint}.png"
    _compose_hybrid(base_path, final_path, scene["title"], list(scene["steps"]), disclaimer)
    target_section = section_title or str(scene["preferred_section"])
    asset = register_visual_asset(
        tender_id,
        asset_type="ai_scene",
        name=str(scene["title"]),
        file_path=final_path,
        source_path=str(source_path or base_path),
        source_kind="ai_generated_hybrid",
        section_title=target_section,
        tags=f"AI场景,程序化标注,scene:{scene_key},待人工复核",
        caption=f"{scene['title']}（AI生成施工示意，非现场实景）",
        visual_class="ai_scene",
        review_status="待复核",
        disclaimer=disclaimer,
        generation_prompt=prompt,
        technical_basis=str(scene["basis"]),
        overlay={"scene_key": scene_key, "steps": scene["steps"], "annotation_mode": "programmatic"},
        ai_model=ai_model,
        conn=conn,
    )
    block = None
    if attach:
        existing = row_to_dict(
            conn.execute(
                "SELECT * FROM document_blocks WHERE tender_id = ? AND asset_id = ? AND status = 'active' LIMIT 1",
                (tender_id, asset["id"]),
            ).fetchone()
        )
        if existing:
            block = existing
        else:
            order = int(
                conn.execute(
                    "SELECT COALESCE(MAX(block_order), 0) + 10 FROM document_blocks WHERE tender_id = ? AND section_title = ?",
                    (tender_id, target_section),
                ).fetchone()[0]
            )
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO document_blocks (
                        tender_id, section_title, block_order, block_type, title, caption,
                        data_json, asset_id, source_path, status, generated_by
                    ) VALUES (?, ?, ?, 'image', ?, ?, ?, ?, ?, 'active', 'ai_hybrid')
                    """,
                    (
                        tender_id,
                        target_section,
                        order,
                        scene["title"],
                        asset["caption"],
                        json.dumps({"scene_key": scene_key, "requires_review": True, "disclaimer": disclaimer}, ensure_ascii=False),
                        asset["id"],
                        str(source_path or base_path),
                    ),
                )
            block = row_to_dict(conn.execute("SELECT * FROM document_blocks WHERE id = ?", (cur.lastrowid,)).fetchone())
    result = {"asset": asset, "block": block, "settings": image_generation_settings()}
    if own_conn:
        conn.close()
    return result
