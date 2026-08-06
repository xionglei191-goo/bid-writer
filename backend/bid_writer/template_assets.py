from __future__ import annotations
from typing import Any

from .construction_methods import COMMON_METHODS, METHOD_LIBRARY


INDUSTRY_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "hospital",
        "name": "医院",
        "keywords": ["医院", "医疗", "医技", "病房"],
        "parameter_rules": ["洁污分流", "不停诊施工边界", "医疗专项接口", "感染控制", "大型设备运输"],
        "outline_variants": ["医疗专项施工", "净化与医用气体接口", "医院运营保护", "系统调试与移交"],
        "scoring_topics": ["施工组织", "安全防护", "质量创优", "专业协调", "绿色施工"],
        "visuals": ["医院洁污分流示意图", "医疗专项接口流程图", "不停诊区域隔离示意图"],
    },
    {
        "key": "school",
        "name": "学校",
        "keywords": ["学校", "校园", "教学", "实验楼"],
        "parameter_rules": ["开学节点", "师生安全隔离", "实验室接口", "操场与室外工程", "噪声控制"],
        "outline_variants": ["校园分区施工", "教学实验空间施工", "室外场地施工", "开学节点保障"],
        "scoring_topics": ["工期节点", "校园安全", "质量控制", "环保降噪"],
        "visuals": ["校园交通分流图", "开学节点横道图", "实验室接口流程图"],
    },
    {
        "key": "municipal",
        "name": "市政",
        "keywords": ["市政", "道路", "桥梁", "管网", "海绵城市"],
        "parameter_rules": ["交通导改", "地下管线保护", "深沟槽支护", "夜间施工", "道路恢复"],
        "outline_variants": ["道路工程", "综合管线", "桥涵构筑物", "交通导改与恢复"],
        "scoring_topics": ["保通措施", "进度组织", "管线保护", "扬尘治理"],
        "visuals": ["交通导改示意图", "管线施工流程图", "道路分段横道图"],
    },
    {
        "key": "factory",
        "name": "厂房",
        "keywords": ["厂房", "产业园", "工业", "生产", "洁净"],
        "parameter_rules": ["大跨度结构", "设备基础", "洁净等级", "工艺接口", "联动试车"],
        "outline_variants": ["钢结构与围护", "设备基础与地坪", "动力与洁净系统", "工艺调试移交"],
        "scoring_topics": ["设备接口", "质量控制", "调试计划", "安全吊装"],
        "visuals": ["设备接口管理流程图", "大跨度吊装流程图", "联动试车流程图"],
    },
    {
        "key": "water",
        "name": "水利",
        "keywords": ["水利", "水务", "河道", "泵站", "水厂", "污水"],
        "parameter_rules": ["围堰导流", "防汛度汛", "水工混凝土", "防渗", "设备联调"],
        "outline_variants": ["导流与降排水", "水工结构", "金属结构与设备安装", "试运行与生态恢复"],
        "scoring_topics": ["防汛安全", "水保环保", "防渗质量", "联动调试"],
        "visuals": ["围堰导流示意图", "泵站调试流程图", "防汛节点横道图"],
    },
)

TABLE_TEMPLATES = (
    "项目基本情况表", "承包范围与接口表", "评分点响应表", "项目管理岗位职责表", "劳动力配置表",
    "机械设备配置表", "主要材料计划表", "施工阶段部署表", "工艺控制参数表", "质量检查验收表",
    "安全风险分级管控表", "进度节点计划表", "临时设施配置表", "BIM应用点表", "专业界面协调表",
)

FLOW_TEMPLATES = (
    "项目总体实施流程", "技术管理流程", "质量检查验收流程", "安全风险闭环流程", "施工工艺流程",
    "设计深化流程", "材料设备报审流程", "进度动态控制流程", "BIM协同流程", "竣工验收移交流程",
)

ORGANIZATION_TEMPLATES = ("项目经理部组织架构", "质量管理组织架构", "安全应急组织架构")
GANTT_TEMPLATES = ("施工总进度横道图", "关键节点倒排横道图", "专项工程穿插横道图")
SITE_LAYOUT_TEMPLATES = ("房建施工总平面", "市政分段施工平面", "水利导流施工平面")


def _method_count() -> int:
    return len(set(COMMON_METHODS).union(*(set(items) for _, items in METHOD_LIBRARY)))


def industry_template_for(profile: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(profile.get(field) or "") for field in ("industry", "project_type", "contract_scope", "special_requirements"))
    for item in INDUSTRY_TEMPLATES:
        if any(keyword in text for keyword in item["keywords"]):
            return item
    return {"key": "general", "name": "通用", "parameter_rules": [], "outline_variants": [], "scoring_topics": [], "visuals": []}


def template_asset_catalog() -> dict[str, Any]:
    return {
        "summary": {
            "industries": len(INDUSTRY_TEMPLATES),
            "construction_methods": _method_count(),
            "table_templates": len(TABLE_TEMPLATES),
            "flow_templates": len(FLOW_TEMPLATES),
            "organization_templates": len(ORGANIZATION_TEMPLATES),
            "gantt_templates": len(GANTT_TEMPLATES),
            "site_layout_templates": len(SITE_LAYOUT_TEMPLATES),
        },
        "industries": list(INDUSTRY_TEMPLATES),
        "tables": list(TABLE_TEMPLATES),
        "flows": list(FLOW_TEMPLATES),
        "organizations": list(ORGANIZATION_TEMPLATES),
        "gantts": list(GANTT_TEMPLATES),
        "site_layouts": list(SITE_LAYOUT_TEMPLATES),
    }
