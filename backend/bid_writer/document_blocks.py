from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from .db import connect, row_to_dict, rows_to_dicts
from .project_profiles import get_project_profile
from .visual_assets import generate_visual_asset, list_visual_assets


BLOCK_TYPES = {"text", "table", "organization_chart", "flow_chart", "gantt_chart", "image", "callout", "page_break"}


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, json.JSONDecodeError):
        return fallback


def _normalize_block(row: dict[str, Any]) -> dict[str, Any]:
    row["data"] = _json(row.get("data_json"), {})
    row.pop("data_json", None)
    if row.get("asset_file_path"):
        row["asset"] = {
            "id": row.get("asset_id"),
            "file_path": row.get("asset_file_path"),
            "name": row.get("asset_name"),
            "asset_type": row.get("asset_type"),
            "source_kind": row.get("asset_source_kind"),
            "visual_class": row.get("asset_visual_class"),
            "review_status": row.get("asset_review_status"),
            "disclaimer": row.get("asset_disclaimer"),
        }
    return row


def list_document_blocks(tender_id: int, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT db.*, va.file_path AS asset_file_path, va.name AS asset_name,
                   va.asset_type AS asset_type, va.source_kind AS asset_source_kind,
                   va.visual_class AS asset_visual_class, va.review_status AS asset_review_status,
                   va.disclaimer AS asset_disclaimer
            FROM document_blocks db
            LEFT JOIN visual_assets va ON va.id = db.asset_id
            WHERE db.tender_id = ? AND db.status = 'active'
            ORDER BY db.section_title, db.block_order, db.id
            """,
            (tender_id,),
        ).fetchall()
    )
    result = [_normalize_block(row) for row in rows]
    if own_conn:
        conn.close()
    return result


def blocks_by_section(tender_id: int, conn: sqlite3.Connection | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for block in list_document_blocks(tender_id, conn=conn):
        grouped.setdefault(str(block.get("section_title") or ""), []).append(block)
    return grouped


def create_document_block(tender_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    block_type = str(data.get("block_type") or "text")
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"Unsupported block type: {block_type}")
    section_title = str(data.get("section_title") or "").strip()
    if not section_title:
        raise ValueError("section_title is required")
    order = data.get("block_order")
    if order is None:
        order = int(
            conn.execute(
                "SELECT COALESCE(MAX(block_order), 0) + 10 FROM document_blocks WHERE tender_id = ? AND section_title = ?",
                (tender_id, section_title),
            ).fetchone()[0]
        )
    payload = data.get("data") if isinstance(data.get("data"), (dict, list)) else _json(data.get("data_json"), {})
    with conn:
        cur = conn.execute(
            """
            INSERT INTO document_blocks (
                tender_id, draft_id, section_title, block_order, block_type,
                title, caption, data_json, asset_id, source_path, status, generated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tender_id,
                data.get("draft_id"),
                section_title,
                int(order),
                block_type,
                str(data.get("title") or ""),
                str(data.get("caption") or ""),
                json.dumps(payload, ensure_ascii=False),
                data.get("asset_id"),
                str(data.get("source_path") or ""),
                str(data.get("status") or "active"),
                str(data.get("generated_by") or "manual"),
            ),
        )
    result = get_document_block(int(cur.lastrowid), conn=conn)
    if own_conn:
        conn.close()
    return result


def get_document_block(block_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    row = row_to_dict(
        conn.execute(
            """
            SELECT db.*, va.file_path AS asset_file_path, va.name AS asset_name,
                   va.asset_type AS asset_type, va.source_kind AS asset_source_kind,
                   va.visual_class AS asset_visual_class, va.review_status AS asset_review_status,
                   va.disclaimer AS asset_disclaimer
            FROM document_blocks db LEFT JOIN visual_assets va ON va.id = db.asset_id
            WHERE db.id = ?
            """,
            (block_id,),
        ).fetchone()
    )
    if not row:
        raise ValueError(f"Document block not found: {block_id}")
    result = _normalize_block(row)
    if own_conn:
        conn.close()
    return result


def update_document_block(block_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    allowed = {"section_title", "block_order", "block_type", "title", "caption", "asset_id", "source_path", "status"}
    cleaned = {key: value for key, value in data.items() if key in allowed}
    if "block_type" in cleaned and cleaned["block_type"] not in BLOCK_TYPES:
        raise ValueError(f"Unsupported block type: {cleaned['block_type']}")
    if "data" in data or "data_json" in data:
        payload = data.get("data") if isinstance(data.get("data"), (dict, list)) else _json(data.get("data_json"), {})
        cleaned["data_json"] = json.dumps(payload, ensure_ascii=False)
    if cleaned:
        assignments = ", ".join(f"{key} = ?" for key in cleaned)
        with conn:
            conn.execute(
                f"UPDATE document_blocks SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*cleaned.values(), block_id),
            )
    result = get_document_block(block_id, conn=conn)
    if own_conn:
        conn.close()
    return result


def delete_document_block(block_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    with conn:
        cur = conn.execute("UPDATE document_blocks SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (block_id,))
    result = {"deleted": bool(cur.rowcount), "id": block_id}
    if own_conn:
        conn.close()
    return result


def _table(title: str, columns: list[str], rows: list[list[Any]], caption: str = "") -> dict[str, Any]:
    return {
        "block_type": "table",
        "title": title,
        "caption": caption or title,
        "data": {"columns": columns, "rows": [[str(cell) for cell in row] for row in rows]},
    }


def _value(profile: dict[str, Any], key: str, label: str) -> str:
    value = str(profile.get(key) or "").strip()
    return value or f"【待确认：{label}】"


def _overview_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "项目基本情况表",
            ["项目", "内容"],
            [
                ["项目名称", _value(profile, "project_name", "项目名称")],
                ["项目类型", _value(profile, "project_type", "项目类型")],
                ["建设规模", _value(profile, "building_area", "建设规模")],
                ["结构形式", _value(profile, "structure_type", "结构形式")],
                ["计划工期", f"{profile.get('duration_days')} 日历天" if profile.get("duration_days") else "【待确认：计划工期】"],
                ["质量目标", _value(profile, "quality_target", "质量目标")],
                ["安全目标", _value(profile, "safety_target", "安全目标")],
            ],
        ),
        _table(
            "承包范围与专业接口表",
            ["类别", "主要内容", "控制要求"],
            [
                ["承包范围", _value(profile, "contract_scope", "承包范围"), "以招标文件、图纸和清单为准"],
                ["现场条件", _value(profile, "site_conditions", "现场条件"), "进场复核并形成书面记录"],
                ["关键约束", _value(profile, "key_constraints", "关键约束"), "纳入策划、交底和过程检查"],
                ["专项要求", _value(profile, "special_requirements", "专项要求"), "明确界面、预留条件和移交标准"],
            ],
        ),
    ]


def _deployment_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "项目管理岗位职责表",
            ["岗位", "主要职责", "配置"],
            [
                ["项目经理", "全面负责履约、资源和外部协调", "【待确认：姓名及证书】"],
                ["项目总工程师", "技术策划、方案审批、质量技术管理", "【待确认：姓名及职称】"],
                ["生产经理", "施工组织、进度协调和现场调度", "【待确认：姓名】"],
                ["商务经理", "合同、成本、计量和变更管理", "【待确认：姓名】"],
                ["质量负责人", "质量体系、检查验收和问题闭环", "【待确认：姓名】"],
                ["安全负责人", "安全体系、风险管控和应急管理", "【待确认：姓名】"],
            ],
        ),
        _table(
            "施工阶段总体部署表",
            ["阶段", "主要任务", "组织重点"],
            [
                ["施工准备", "临建、测量、方案、资源和接口确认", "先策划后实施"],
                ["基础及地下结构", "基坑、基础、地下结构和防水", "降排水、监测和穿插"],
                ["主体结构", "竖向结构、水平结构和二次结构", "流水分段、样板引路"],
                ["机电及装饰", "管线综合、安装、装修和专项接口", "深化先行、专业穿插"],
                ["调试验收", "系统调试、联合验收和资料移交", "问题清零、分区移交"],
            ],
        ),
        _table(
            "主要资源投入计划表",
            ["资源类别", "建议配置", "进场原则"],
            [
                ["劳动力", "按阶段峰值配置，具体人数【待确认】", "随工作面分批进场"],
                ["垂直运输设备", "塔吊、施工电梯数量【待确认】", "基础条件完成后验收投用"],
                ["混凝土设备", "输送泵及布料设备【待确认】", "按浇筑计划动态配置"],
                ["机电加工设备", "套丝、压槽、焊接和检测设备【待确认】", "加工区形成后集中配置"],
            ],
        ),
    ]


def _method_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "主要分部分项工程施工方法表",
            ["分部工程", "关键工序", "质量控制点"],
            [
                ["测量工程", "控制网复核、轴线与标高传递", "闭合复测、成果签认"],
                ["基础工程", "验槽、垫层、钢筋模板、混凝土", "基底保护、隐蔽验收"],
                ["主体结构", "钢筋、模板、混凝土、二次结构", "样板、实测实量、养护"],
                ["防水工程", "基层、节点附加层、防水层、保护层", "节点旁站、闭水试验"],
                ["机电安装", "预留预埋、支吊架、管线、试压调试", "综合排布、接口复核"],
                ["装饰装修", "基层、样板、面层、成品保护", "样板确认、观感检查"],
            ],
        ),
        _table(
            "施工工艺样板计划表",
            ["样板名称", "实施时间", "确认单位", "状态"],
            [
                ["钢筋模板实体样板", "主体施工前", "建设/监理/设计/总包", "【待确认】"],
                ["防水节点样板", "防水施工前", "建设/监理/总包/专业分包", "【待确认】"],
                ["机电综合样板", "安装大面展开前", "建设/监理/设计/总包", "【待确认】"],
                ["装饰样板间", "装修大面施工前", "建设/监理/设计/总包", "【待确认】"],
            ],
        ),
        _table(
            "主要施工机械设备计划表",
            ["设备", "用途", "建议数量", "核验要求"],
            [
                ["塔式起重机", "主体材料垂直运输", "【待确认】", "专项方案、安装验收"],
                ["施工电梯", "人员及装修材料运输", "【待确认】", "检测合格、定期维保"],
                ["混凝土输送泵", "混凝土输送", "【待确认】", "泵管固定、应急备用"],
                ["全站仪/水准仪", "测量放线与沉降观测", "【待确认】", "检定有效"],
                ["管线加工设备", "机电预制加工", "【待确认】", "防护齐全、专人操作"],
            ],
        ),
    ]


def _risk_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "工程重难点及对策表",
            ["重难点", "主要风险", "针对性措施", "责任岗位"],
            [
                ["医院多专业交叉", "接口冲突、返工", "BIM 综合、样板确认、联合会审", "项目总工程师"],
                ["地下工程体量大", "渗漏、工期压力", "分区流水、节点旁站、监测预警", "生产经理"],
                ["机电系统复杂", "净高不足、调试困难", "深化排布、预制加工、分系统调试", "机电负责人"],
                ["现场运输组织", "交通拥堵、周边影响", "人车分流、预约进场、专人指挥", "安全负责人"],
                ["专项目标", _value(profile, "key_constraints", "关键约束"), "清单化响应、过程销项", "项目经理"],
            ],
        ),
        _table(
            "风险分级管控台账",
            ["风险事项", "等级", "预警指标", "处置措施"],
            [
                ["深基坑及降排水", "高", "位移、沉降、地下水位", "监测预警、停工复核、专家支持"],
                ["高大模板及脚手架", "高", "沉降、变形、荷载", "验收挂牌、旁站监测、限载"],
                ["大型设备吊装", "高", "风速、站位、吊点", "专项方案、试吊、警戒"],
                ["临时用电及动火", "中", "漏保、温升、可燃物", "分级审批、监护、巡检"],
            ],
        ),
    ]


def _progress_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    total = int(profile.get("duration_days") or 0)
    total_text = f"{total} 日历天" if total else "【待确认：总工期】"
    return [
        _table(
            "总体进度控制节点表",
            ["节点", "计划控制", "成果标准"],
            [
                ["开工准备完成", "开工后 30 天内（建议）", "临建、测量、方案和资源具备"],
                ["地下结构完成", "总工期约 35%（建议）", "地下结构验收、回填条件具备"],
                ["主体结构封顶", "总工期约 58%（建议）", "主体结构验收"],
                ["机电装修大面完成", "总工期约 88%（建议）", "系统单机调试条件具备"],
                ["竣工验收", total_text, "验收合格、资料齐全、完成移交"],
            ],
        ),
        _table(
            "进度偏差纠偏措施表",
            ["偏差等级", "判断条件", "主要措施", "审批层级"],
            [
                ["轻微", "关键工作偏差不超过 3 天", "班组调整、工作面优化", "生产经理"],
                ["一般", "关键工作偏差 4-7 天", "增加资源、调整穿插、专项协调", "项目经理"],
                ["严重", "关键工作偏差超过 7 天", "重排总控计划、公司资源支援", "公司/项目联合"],
            ],
        ),
    ]


def _quality_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "质量目标分解表",
            ["控制层级", "目标", "主要控制手段"],
            [
                ["总体质量", _value(profile, "quality_target", "质量目标"), "策划、样板、实测、验收和复盘"],
                ["分项工程", "一次验收合格率目标【待确认】", "首件认可、过程检查"],
                ["实测实量", "合格率目标【待确认】", "分层分区实测、数据上墙"],
                ["资料管理", "同步、真实、完整、可追溯", "责任到人、节点归档"],
            ],
        ),
        _table(
            "关键质量控制点表",
            ["工序", "控制点", "检查方法", "验收记录"],
            [
                ["钢筋工程", "规格、接头、间距、保护层", "尺量、抽检、隐蔽验收", "隐蔽验收记录"],
                ["模板工程", "尺寸、垂直度、支撑体系", "实测、巡检、验收", "模板验收记录"],
                ["混凝土工程", "配合比、坍落度、振捣、养护", "旁站、试块、测温", "浇筑令及试验报告"],
                ["防水工程", "基层、节点、搭接、闭水", "旁站、厚度、闭水试验", "隐蔽及试验记录"],
                ["机电工程", "坡度、标高、支吊架、试压", "尺量、试压、调试", "试验与调试记录"],
            ],
        ),
        _table(
            "检验试验计划表",
            ["材料/工序", "检验项目", "频次", "责任人"],
            [
                ["钢筋", "力学性能、重量偏差", "按规范及批次", "试验工程师"],
                ["混凝土", "坍落度、抗压强度、抗渗", "按浇筑批次", "试验工程师"],
                ["防水材料", "物理性能", "按批次见证取样", "材料/试验工程师"],
                ["管材阀件", "外观、强度、严密性", "按系统及批次", "机电质量工程师"],
            ],
        ),
    ]


def _safety_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "安全文明施工目标表",
            ["类别", "目标", "控制措施"],
            [
                ["安全生产", _value(profile, "safety_target", "安全目标"), "责任制、风险分级、检查闭环"],
                ["文明施工", "标准化工地目标【待确认】", "分区管理、定置堆放、形象统一"],
                ["环境保护", _value(profile, "green_target", "绿色施工目标"), "扬尘、噪声、污水和固废控制"],
                ["消防管理", "不发生火灾事故", "动火审批、临时消防和巡查"],
            ],
        ),
        _table(
            "重大危险源控制表",
            ["危险源", "主要事故类型", "控制措施", "应急准备"],
            [
                ["基坑工程", "坍塌、涌水", "方案论证、监测、降排水", "抢险物资和撤离路线"],
                ["模板脚手架", "坍塌、高处坠落", "验收挂牌、限载、巡检", "警戒和应急支撑"],
                ["起重吊装", "物体打击、机械伤害", "持证、试吊、警戒", "应急停机和救援"],
                ["临电动火", "触电、火灾", "三级配电、动火审批", "灭火器材和应急断电"],
            ],
        ),
        _table(
            "绿色施工与环境保护措施表",
            ["环境因素", "控制指标", "主要措施", "检查频次"],
            [
                ["扬尘", "满足属地管理要求", "围挡、覆盖、喷淋、车辆冲洗", "每日"],
                ["噪声", "满足施工场界标准", "低噪设备、时段管理、监测", "重点工序"],
                ["施工污水", "达标后排放或回用", "沉淀、隔油、检测", "每周"],
                ["建筑垃圾", "分类、减量、合规清运", "定点堆放、台账和联单", "每日"],
            ],
        ),
    ]


def _layout_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "临时设施配置表",
            ["设施", "布置原则", "规模/位置"],
            [
                ["施工道路", "形成环路、人车分流、满足消防", "【待确认：红线及出入口】"],
                ["材料堆场", "靠近使用点、分类定置、防雨防火", "【待确认：场地尺寸】"],
                ["加工区", "集中加工、减少二次搬运", "【待确认：位置及面积】"],
                ["临水临电", "分区计量、三级保护、消防兼顾", "【待确认：接驳点】"],
            ],
        ),
        _table(
            "施工总平面动态转换表",
            ["阶段", "主要占用", "调整重点"],
            [
                ["基础阶段", "基坑、土方、钢筋模板加工", "运输路线与排水"],
                ["主体阶段", "垂直运输、周转料场", "塔吊覆盖与消防通道"],
                ["装饰安装阶段", "专业加工、设备材料堆场", "施工电梯与分区移交"],
                ["室外收尾阶段", "道路管网和景观施工", "临建拆除与场地恢复"],
            ],
        ),
    ]


def _bim_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "BIM 应用计划表",
            ["应用项", "应用阶段", "成果", "责任专业"],
            [
                ["图纸会审与碰撞检查", "深化设计", "问题清单、综合模型", "BIM/设计/各专业"],
                ["机电综合排布", "安装前", "综合管线图、预留预埋图", "机电/BIM"],
                ["施工模拟", "重大工序前", "可视化交底和方案比选", "技术/BIM"],
                ["进度与质量协同", "施工过程", "模型状态、问题闭环记录", "生产/质量/BIM"],
                ["竣工模型移交", "竣工阶段", "竣工模型及关联资料", "资料/BIM"],
            ],
        ),
        _table(
            "BIM 模型交付标准表",
            ["成果", "深度要求", "格式", "状态"],
            [
                ["综合协调模型", "满足碰撞检查和净高分析", "原生格式+IFC/PDF", "【待确认】"],
                ["预留预埋图", "定位、尺寸和标高完整", "DWG/PDF", "【待确认】"],
                ["竣工模型", "与现场及竣工图一致", "按业主标准", "【待确认】"],
            ],
        ),
    ]


def _technology_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "新技术应用计划表",
            ["技术类别", "拟应用内容", "应用部位", "效益与风险控制"],
            [
                ["数字建造", "BIM 深化、移动巡检、资料关联", "全项目", "减少返工，权限和数据备份"],
                ["工业化施工", "机电预制、定型化防护", "安装及临防", "提高效率，样板确认"],
                ["绿色施工", "节水节能、材料减损、建筑垃圾分类", "施工全过程", "降低消耗，过程计量"],
                ["质量提升", "实测实量数字化、样板引路", "结构及装修", "数据驱动，问题闭环"],
            ],
        ),
        _table(
            "新技术评价与推广表",
            ["阶段", "评价内容", "输出成果"],
            [
                ["立项", "适用性、经济性、安全质量风险", "应用策划及审批记录"],
                ["样板", "工艺参数、效率和质量效果", "样板评审记录"],
                ["推广", "标准化交底、过程检查", "作业指导书和检查记录"],
                ["总结", "成本、工期、质量和绿色效益", "应用总结及成果资料"],
            ],
        ),
    ]


def _coordination_tables(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _table(
            "总承包协调界面表",
            ["协调对象", "主要界面", "协调机制", "输出记录"],
            [
                ["建设单位", "需求、节点、设计变更和验收", "例会、专题会、书面报告", "会议纪要/报告"],
                ["设计单位", "深化、材料、接口和变更", "图纸会审、设计协调", "问题清单/确认单"],
                ["监理单位", "方案、报验、旁站和验收", "报审报验、联合检查", "审批及验收记录"],
                ["专业分包", "工作面、预留、工序和成品保护", "界面清单、移交验收", "移交单/销项单"],
                ["供应商", "技术参数、到货、安装调试", "计划联动、进场验收", "进场及调试记录"],
            ],
        ),
        _table(
            "专业工程移交条件表",
            ["移交事项", "前置条件", "接收确认"],
            [
                ["结构向机电移交", "轴线标高、洞口、工作面和安全条件", "联合验收并签署移交单"],
                ["机电向装修移交", "隐蔽验收、试压、标识和成品保护", "样板确认、分区移交"],
                ["装修向设备移交", "环境、尺寸、电源和运输条件", "设备单位复核签认"],
                ["施工向运维移交", "调试完成、资料齐全、培训完成", "竣工验收及移交记录"],
            ],
        ),
    ]


def _tables_for_section(title: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    if "工程概况" in title:
        return _overview_tables(profile)
    if "部署" in title:
        return _deployment_tables(profile)
    if "工艺" in title or "施工方法" in title:
        return _method_tables(profile)
    if "难点" in title or "风险" in title:
        return _risk_tables(profile)
    if "进度" in title or "工期" in title:
        return _progress_tables(profile)
    if "质量" in title:
        return _quality_tables(profile)
    if "安全" in title or "文明" in title or "环境" in title:
        return _safety_tables(profile)
    if "平面" in title or "临设" in title:
        return _layout_tables(profile)
    if "BIM" in title or "智慧" in title or "信息化" in title:
        return _bim_tables(profile)
    if "新技术" in title or "四新" in title:
        return _technology_tables(profile)
    if "总承包" in title or "协调" in title:
        return _coordination_tables(profile)
    return []


def _flow_specs(title: str) -> list[tuple[str, list[str]]]:
    if "部署" in title:
        return [("项目总体实施流程", ["项目策划", "图纸会审", "临建及资源准备", "分区流水施工", "专业穿插", "系统调试", "竣工移交"])]
    if "工艺" in title or "施工方法" in title:
        return [
            ("主体结构施工流程", ["测量放线", "墙柱钢筋", "机电预埋", "模板安装", "梁板钢筋", "隐蔽验收", "混凝土浇筑", "养护与拆模"]),
            ("防水工程施工流程", ["基层处理", "节点附加层", "防水层施工", "过程检查", "闭水/淋水试验", "保护层施工", "成品保护"]),
            ("机电安装施工流程", ["深化排布", "预留预埋复核", "支吊架施工", "管线设备安装", "试压冲洗", "单机调试", "联合调试", "验收移交"]),
            ("装饰装修施工流程", ["基层验收", "样板确认", "测量排版", "大面施工", "细部收口", "质量检查", "成品保护", "分区移交"]),
        ]
    if "难点" in title:
        return [("工程风险闭环管理流程", ["风险识别", "分级评价", "制定措施", "责任交底", "过程监测", "预警处置", "复查销项", "经验复盘"])]
    if "进度" in title:
        return [("进度计划动态控制流程", ["总控计划", "月周计划分解", "资源匹配", "每日跟踪", "偏差分析", "纠偏审批", "计划更新", "节点复核"])]
    if "质量" in title:
        return [("质量检查验收流程", ["方案与交底", "材料验收", "样板确认", "班组自检", "项目复检", "监理验收", "问题整改", "资料归档"])]
    if "安全" in title or "文明" in title:
        return [
            ("安全风险管控流程", ["危险源辨识", "风险分级", "方案审批", "安全交底", "条件验收", "旁站巡检", "隐患整改", "复查销项"]),
            ("应急响应流程", ["发现险情", "立即报告", "停工警戒", "人员疏散", "启动预案", "抢险救援", "监测评估", "恢复与复盘"]),
        ]
    if "BIM" in title or "智慧" in title:
        return [("BIM 协同工作流程", ["模型标准", "专业建模", "模型整合", "碰撞检查", "问题派发", "专业整改", "复核关闭", "成果交付"])]
    if "新技术" in title:
        return [("新技术应用管理流程", ["需求识别", "技术筛选", "风险评估", "审批立项", "样板试用", "评审优化", "推广应用", "成果总结"])]
    if "总承包" in title or "协调" in title:
        return [("专业界面协调流程", ["界面识别", "责任划分", "条件确认", "联合交底", "过程协调", "移交验收", "问题销项", "资料归档"])]
    return []


def _schedule_data(profile: dict[str, Any]) -> dict[str, Any]:
    total = max(180, int(profile.get("duration_days") or 850))
    specs = [
        ("施工准备", 0.00, 0.05),
        ("基础及地下结构", 0.03, 0.32),
        ("主体结构", 0.22, 0.38),
        ("屋面及外围护", 0.50, 0.16),
        ("机电安装", 0.28, 0.46),
        ("装饰装修", 0.52, 0.34),
        ("医疗专项接口配合", 0.62, 0.23),
        ("室外工程", 0.76, 0.16),
        ("系统联合调试", 0.87, 0.10),
        ("竣工验收与移交", 0.95, 0.05),
    ]
    tasks = []
    for name, start_ratio, duration_ratio in specs:
        start = round(total * start_ratio)
        duration = min(total - start, max(1, round(total * duration_ratio)))
        tasks.append({"name": name, "start": start, "duration": duration, "milestone": name == "竣工验收与移交"})
    return {"total_days": total, "tasks": tasks, "note": "投标阶段建议总控进度；实际开工日期、里程碑和资源投入须结合合同节点、图纸及现场条件复核。"}


def _insert_specs(
    tender_id: int,
    draft_id: int | None,
    section_title: str,
    specs: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    created = []
    order = 10
    for spec in specs:
        payload = dict(spec)
        payload.update(
            {
                "draft_id": draft_id,
                "section_title": section_title,
                "block_order": order,
                "generated_by": "system",
            }
        )
        created.append(create_document_block(tender_id, payload, conn=conn))
        order += 10
    return created


def generate_document_blocks(
    tender_id: int,
    *,
    regenerate: bool = True,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    tender = row_to_dict(conn.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone())
    if not tender:
        raise ValueError(f"Tender not found: {tender_id}")
    if regenerate:
        with conn:
            conn.execute("DELETE FROM document_blocks WHERE tender_id = ? AND generated_by = 'system'", (tender_id,))
    existing = list_document_blocks(tender_id, conn=conn)
    if existing and not regenerate:
        summary = summarize_document_blocks(existing)
        result = {"tender": tender, "summary": summary, "blocks": existing, "assets": list_visual_assets(tender_id, conn=conn)}
        if own_conn:
            conn.close()
        return result

    profile = get_project_profile(tender_id, conn=conn)
    plan_rows = rows_to_dicts(
        conn.execute(
            """
            SELECT sp.order_no, sp.section_title, sp.draft_id
            FROM section_plans sp WHERE sp.tender_id = ? ORDER BY sp.order_no, sp.id
            """,
            (tender_id,),
        ).fetchall()
    )
    if not plan_rows:
        plan_rows = rows_to_dicts(
            conn.execute(
                "SELECT id AS draft_id, section_title, id AS order_no FROM drafts WHERE tender_id = ? ORDER BY id",
                (tender_id,),
            ).fetchall()
        )
    created: list[dict[str, Any]] = []
    industry = str(tender.get("industry") or profile.get("industry") or "")
    reference_assets = rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM visual_assets
            WHERE tender_id = ? AND status = 'active'
              AND source_kind IN ('docx_embedded', 'user_upload')
            ORDER BY id
            """,
            (tender_id,),
        ).fetchall()
    )
    used_reference_assets = 0
    for plan in plan_rows:
        section_title = str(plan.get("section_title") or "")
        draft_id = int(plan["draft_id"]) if plan.get("draft_id") else None
        specs: list[dict[str, Any]] = [
            {
                "block_type": "text",
                "title": section_title,
                "caption": "",
                "data": {"source": "draft", "draft_id": draft_id},
            }
        ]
        specs.extend(_tables_for_section(section_title, profile))

        if "部署" in section_title:
            data = {
                "root": "项目经理",
                "roles": ["项目总工程师", "生产经理", "商务经理"],
                "departments": ["工程技术部", "质量管理部", "安全环境部", "机电管理部", "物资设备部", "商务合约部", "综合办公室", "各专业施工队"],
            }
            asset = generate_visual_asset(
                tender_id,
                asset_type="organization_chart",
                name="项目管理组织架构图",
                title="项目管理组织架构图",
                data=data,
                industry=industry,
                section_title=section_title,
                caption="项目管理组织架构图（岗位人员待确认）",
                conn=conn,
            )
            specs.append({"block_type": "organization_chart", "title": "项目管理组织架构", "caption": asset["caption"], "data": data, "asset_id": asset["id"]})

        for flow_title, steps in _flow_specs(section_title):
            flow_data = {"steps": steps}
            asset = generate_visual_asset(
                tender_id,
                asset_type="flow_chart",
                name=flow_title,
                title=flow_title,
                data=flow_data,
                industry=industry,
                section_title=section_title,
                caption=flow_title,
                conn=conn,
            )
            specs.append({"block_type": "flow_chart", "title": flow_title, "caption": flow_title, "data": flow_data, "asset_id": asset["id"]})

        if "进度" in section_title:
            schedule = _schedule_data(profile)
            asset = generate_visual_asset(
                tender_id,
                asset_type="gantt_chart",
                name="施工总进度横道图",
                title="施工总进度横道图",
                data=schedule,
                industry=industry,
                section_title=section_title,
                caption="施工总进度横道图（投标阶段建议计划）",
                conn=conn,
            )
            specs.append({"block_type": "gantt_chart", "title": "施工总进度横道图", "caption": asset["caption"], "data": schedule, "asset_id": asset["id"]})

        illustration: tuple[str, str] | None = None
        if "平面" in section_title:
            illustration = ("施工总平面功能分区示意图", "site_layout")
        elif "质量" in section_title:
            illustration = ("质量管理 PDCA 闭环示意图", "quality_loop")
        elif "BIM" in section_title or "智慧" in section_title:
            illustration = ("BIM 多专业协同应用示意图", "bim_coordination")
        if illustration:
            illustration_data = {"kind": illustration[1]}
            asset = generate_visual_asset(
                tender_id,
                asset_type="illustration",
                name=illustration[0],
                title=illustration[0],
                data=illustration_data,
                industry=industry,
                section_title=section_title,
                caption=f"{illustration[0]}（非现场实景）",
                conn=conn,
            )
            specs.append({"block_type": "image", "title": illustration[0], "caption": asset["caption"], "data": illustration_data, "asset_id": asset["id"]})

        matching_references = [
            asset
            for asset in reference_assets
            if used_reference_assets < 8
            and (not str(asset.get("section_title") or "").strip() or str(asset.get("section_title") or "") == section_title)
        ][:4]
        for asset in matching_references:
            specs.append(
                {
                    "block_type": "image",
                    "title": str(asset.get("name") or "历史标书示例图片"),
                    "caption": str(asset.get("caption") or "历史资料示例图（使用前人工核对适用性）"),
                    "data": {"source_kind": asset.get("source_kind"), "requires_review": True},
                    "asset_id": int(asset["id"]),
                    "source_path": str(asset.get("source_path") or ""),
                }
            )
            used_reference_assets += 1

        created.extend(_insert_specs(tender_id, draft_id, section_title, specs, conn))

    blocks = list_document_blocks(tender_id, conn=conn)
    result = {
        "tender": {"id": tender_id, "name": tender.get("name"), "industry": industry},
        "summary": summarize_document_blocks(blocks),
        "blocks": blocks,
        "assets": list_visual_assets(tender_id, conn=conn),
    }
    if own_conn:
        conn.close()
    return result


def summarize_document_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item.get("block_type") or "unknown") for item in blocks)
    sections = {str(item.get("section_title") or "") for item in blocks}
    return {
        "total_blocks": len(blocks),
        "sections": len(sections),
        "text_blocks": counts.get("text", 0),
        "tables": counts.get("table", 0),
        "organization_charts": counts.get("organization_chart", 0),
        "flow_charts": counts.get("flow_chart", 0),
        "gantt_charts": counts.get("gantt_chart", 0),
        "images": counts.get("image", 0),
        "visual_blocks": sum(counts.get(kind, 0) for kind in ("organization_chart", "flow_chart", "gantt_chart", "image")),
        "by_type": dict(counts),
    }


def render_section_blocks_markdown(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        block_type = str(block.get("block_type") or "")
        if block_type in {"text", "page_break"}:
            continue
        caption = str(block.get("caption") or block.get("title") or "")
        if block_type == "table":
            data = block.get("data") or {}
            columns = [str(item) for item in (data.get("columns") or [])]
            rows = list(data.get("rows") or [])
            if not columns:
                continue
            lines.extend(["", f"### {caption}", "", "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            for raw_row in rows:
                values = list(raw_row) if isinstance(raw_row, (list, tuple)) else [raw_row]
                padded = [str(values[index]) if index < len(values) else "" for index in range(len(columns))]
                lines.append("| " + " | ".join(value.replace("|", "\\|") for value in padded) + " |")
        elif block_type in {"organization_chart", "flow_chart", "gantt_chart", "image"}:
            asset = block.get("asset") or {}
            path = str(asset.get("file_path") or block.get("source_path") or "")
            if path:
                lines.extend(["", f"![{caption}]({path.replace(chr(92), '/')})", "", f"*{caption}*"])
        elif block_type == "callout":
            text = str((block.get("data") or {}).get("text") or block.get("title") or "")
            lines.extend(["", f"> {text}"])
    return "\n".join(lines).strip()
