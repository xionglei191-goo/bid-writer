from __future__ import annotations

from typing import Any


COMMON_METHODS = (
    "施工测量与控制网复核",
    "临时工程与施工准备",
    "成品保护与工序交接",
)


METHOD_LIBRARY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("医院", "医疗", "公建", "学校", "住宅", "综合体", "房建", "办公", "商业"),
        (
            "土方开挖、基坑支护与降排水施工",
            "桩基、地基处理与基础结构施工",
            "主体结构钢筋、模板、混凝土施工",
            "砌体、二次结构与粗装修施工",
            "屋面、防水与保温工程施工",
            "装饰装修与公共区域精装修施工",
            "给排水、电气、暖通及消防机电安装",
            "室外道路、管网、景观及收尾工程",
        ),
    ),
    (
        ("医院", "医疗", "医技", "病房"),
        (
            "医疗专项机电、医用气体与净化区域施工",
            "防辐射、防感染与洁污分流专项施工",
            "不停诊或邻近运营区域施工组织与隔离防护",
            "手术部、ICU及检验科洁净围护与密封施工",
            "医疗设备基础、预埋与专业接口复核",
            "医院物流传输、弱电智能化与综合调试",
        ),
    ),
    (
        ("学校", "教学", "校园", "实验楼"),
        (
            "教学楼、实验楼及宿舍楼标准层流水施工",
            "操场、室外活动场地及校园配套工程施工",
            "开学节点倒排与校园安全隔离施工",
            "实验室通风、给排水与专业台柜接口施工",
            "校园运营区域噪声、扬尘与交通分流控制",
        ),
    ),
    (
        ("厂房", "产业园", "生产", "工业", "仓储", "物流", "洁净"),
        (
            "大跨度钢结构、金属屋面及围护系统施工",
            "设备基础、地坪与预留预埋施工",
            "洁净厂房、动力站房及机电管综施工",
            "生产物流动线、调试移交与工艺接口管理",
            "大面积耐磨地坪、洁净地坪与分仓施工",
            "工艺设备吊装、二次配管与联动试车配合",
        ),
    ),
    (
        ("市政", "道路", "桥", "管网", "排水", "海绵"),
        (
            "道路路基、基层与面层施工",
            "雨污水、给水、电力通信等综合管线施工",
            "桥涵、挡墙与附属构筑物施工",
            "交通导改、围挡组织与文明施工恢复",
            "深沟槽支护、降排水与管线保护施工",
            "海绵城市设施、透水铺装与雨水调蓄施工",
        ),
    ),
    (
        ("水利", "水务", "泵站", "河道", "污水", "水厂"),
        (
            "围堰导流、降排水与水保措施施工",
            "水工混凝土、池体结构与防渗施工",
            "泵站、水处理构筑物与设备安装调试",
            "管道试压、闭水试验与联动试运行",
            "河道清淤、边坡防护与生态修复施工",
            "闸门启闭机、格栅及水工金属结构安装",
        ),
    ),
    (
        ("改造", "加固", "装修", "修缮", "更新"),
        (
            "拆除、保护性拆改与临时支撑施工",
            "结构加固、植筋、粘钢或碳纤维施工",
            "既有机电系统改造与新旧接口转换",
            "运营场景下分区封闭、降噪降尘与成品保护",
        ),
    ),
)


def profile_text(profile: dict[str, Any], *fields: str) -> str:
    return " ".join(str(profile.get(field) or "") for field in fields)


def method_outline_for(profile: dict[str, Any]) -> tuple[str, ...]:
    haystack = profile_text(
        profile,
        "industry",
        "project_type",
        "structure_type",
        "contract_scope",
        "special_requirements",
    )
    selected: list[str] = list(COMMON_METHODS)
    for terms, methods in METHOD_LIBRARY:
        if any(term and term in haystack for term in terms):
            selected.extend(methods)
    if len(selected) == len(COMMON_METHODS):
        selected.extend(METHOD_LIBRARY[0][1])

    deduped: list[str] = []
    seen: set[str] = set()
    for item in selected:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return tuple(deduped)


def method_summary(profile: dict[str, Any]) -> str:
    return "\n".join(f"- {item}" for item in method_outline_for(profile))
