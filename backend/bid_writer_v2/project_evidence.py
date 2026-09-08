"""Deterministic, project-scoped evidence binding.

Similarity only retrieves possible passages. Numbers, objects, units, scope and
conditions still have to agree, and every assertion in a compound claim needs
its own support. A profile is a consistency check, never a substitute source.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .utils import content_hash, normalize_text, parse_json


PROJECT_EVIDENCE_VERSION = "project-evidence-1.0.1"
_WORKFLOW_PROFILE_KEYS = {
    "delivery_confirmation", "compliance_confirmed", "manual_finalized", "final_approved",
    "professional_reviewer", "reviewed_by", "reviewed_at", "reviewer", "review_notes",
    "confirmed_by", "confirmed_at", "confirmation", "confirmations", "signature", "signed_by", "signed_at",
}
_PROJECT_OBJECTS = {
    "duration", "building_area", "aboveground_area", "underground_area", "quality_award",
    "site_address", "project_identity", "tender_scope", "evacuation_period", "evacuation_liability", "stage_count",
}
_OBJECT_PATTERNS = (
    ("aboveground_area", r"地上(?:建筑)?(?:面积)?"),
    ("underground_area", r"地下(?:建筑)?(?:面积)?"),
    ("building_area", r"(?:总建筑面积|建筑面积|建筑规模|总面积)"),
    ("evacuation_period", r"(?:腾退|退场|清退)(?:人员|场地)?"),
    ("reserve_capacity", r"(?:预留.{0,10}(?:余量|富余|面积)|(?:面积|场地|需求).{0,15}预留|余量|富余)"),
    ("penalty", r"(?:违约金|罚款|罚金)"),
    ("advance_payment", r"预付款"),
    ("quantity_adjustment", r"(?:工程量.{0,15}(?:增加|变动|偏差)|清单项工程量)"),
    ("quality_award", r"鲁班奖"),
    ("complaints", r"投诉"),
    ("accidents", r"事故"),
    ("site_address", r"(?:建设地点|建设地址|现场地址|项目地址|位于|坐落|路\d+号|街\d+号)"),
    ("duration", r"(?:总工期|计划工期|合同工期|施工工期|工期|工期总日历天数)"),
    ("stage_count", r"(?:个阶段|大阶段|阶段划分|划分.{0,8}阶段)"),
    ("excavation_depth", r"(?:开挖深度|基坑深度|挖深)"),
    ("thickness", r"(?:厚度|厚)"),
    ("diameter", r"(?:直径|管径)"),
)
_STAGE_PATTERN = re.compile(r"(?:施工准备|前期准备|基坑支护|地下室|基础施工|主体结构|主体施工|装饰装修|幕墙安装|机电安装|机电调试|联调|景观|竣工验收|竣工交付)")
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>\d+(?:\.\d+)?)\s*(?P<scale>万|千)?\s*"
    r"(?P<unit>日历天|工作日|日历日|平方米|平方毫米|平方厘米|立方米|m2|m3|mm2|cm2|MPa|kN|"
    r"万元|小时|分钟|个月|大阶段|阶段|年|月|天|日|人|台|套|个|米|毫米|厘米|万元|元|%|mm|cm|m|℃|号)(?![A-Za-z])",
    re.IGNORECASE,
)
_UNIT_ALIASES = {
    "日历天": "day", "日历日": "day", "天": "day", "日": "day", "工作日": "working_day",
    "平方米": "m2", "平方毫米": "mm2", "平方厘米": "cm2", "立方米": "m3",
    "米": "m", "毫米": "mm", "厘米": "cm", "万元": "yuan_10000", "元": "yuan", "大阶段": "stage", "阶段": "stage",
}


def factual_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    return {key: value for key, value in profile.items() if key not in _WORKFLOW_PROFILE_KEYS}


def project_source_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    profile = project.get("profile")
    if not isinstance(profile, dict):
        profile = parse_json(project.get("profile_json"), {})
    material = {
        "project_id": project.get("id"), "name": project.get("name") or "",
        "industry": project.get("industry") or "", "project_type": project.get("project_type") or "",
        "region": project.get("region") or "", "source_text": str(project.get("source_text") or ""),
        "profile": factual_profile(profile),
    }
    return {
        **material, "source_hash": content_hash(material["source_text"]),
        "project_source_hash": content_hash(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        "rule_version": PROJECT_EVIDENCE_VERSION,
    }


def _chinese_integer(value: str) -> str:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if all(char in digits for char in value):
        return "".join(str(digits[char]) for char in value)
    total, current = 0, 0
    for char in value:
        if char in digits:
            current = digits[char]
        else:
            total += (current or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            current = 0
    return str(total + current)


def _text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).replace("²", "2").replace("³", "3")
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    text = re.sub(r"[【\[（(]\s*(\d+(?:\.\d+)?)\s*[】\]）)]", r"\1", text)
    text = re.sub(r"(?:^|\n)\s*(?:REQ-\d+\s*[:：]?\s*)?\d+(?:\.\d+){0,5}[.、）):：]?\s+(?=[^\d])", "", text)
    text = re.sub(r"REQ-\d+\s*[:：]?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"([零〇一二三四五六七八九十百千两]+)(?=个阶段|大阶段|阶段|天|日|台|套)", lambda match: _chinese_integer(match.group(1)), text)
    return re.sub(r"[*_`<>]", "", text).strip()


def _compact(value: str) -> str:
    return re.sub(r"[\s，,。；;：:、（）()【】\[\]“”‘’\"'|#]", "", _text(value)).lower()


def _terms(value: str) -> set[str]:
    compact = _compact(value)
    return {compact[i:i + 2] for i in range(max(0, len(compact) - 1))}


def _semantic_text(value: str) -> str:
    text = _compact(value)
    for old, new in (
        ("通知之日起", "通知后"), ("收到腾退通知", "腾退通知后"), ("接到腾退通知", "腾退通知后"),
        ("完成腾退", "腾退"), ("完成人员场地腾退", "人员场地腾退"),
        ("总建筑面积", "建筑面积"), ("质量目标", "质量要求"),
        ("计划总工期", "工期"), ("计划工期", "工期"), ("合同工期", "工期"), ("总工期", "工期"),
        ("日历天", "天"), ("平方米", "m2"), ("争取获得", "争创"), ("力争获得", "争创"),
    ):
        text = text.replace(old, new)
    return text


def _score(claim: str, passage: str) -> float:
    left, right = _semantic_text(claim), _semantic_text(passage)
    if left and left in right:
        return 1.0
    terms = {left[i:i + 2] for i in range(max(0, len(left) - 1))}
    source = {right[i:i + 2] for i in range(max(0, len(right) - 1))}
    return round(len(terms & source) / len(terms), 4) if terms else 0.0


def _scope(value: str) -> str:
    text = _compact(value)
    found = list(re.finditer(r"标段([一二三四五六七八九十0-9]+)|([南北东西])区", text))
    if not found:
        return "all" if re.search(r"(?:全院|全部标段|所有标段|整个院区)", text) else ""
    match = found[-1]
    return "section:" + match.group(1).translate(str.maketrans("一二三四五六七八九", "123456789")) if match.group(1) else "area:" + match.group(2)


def _object(value: str, *, unit: str = "", position: int | None = None) -> str:
    text = _compact(value)
    if unit == "stage" or (unit == "个" and "阶段" in text):
        return "stage_count"
    if unit == "day":
        # A named construction stage is never interchangeable with total time.
        nearby = text[max(0, (position or len(text)) - 35):(position or len(text)) + 18]
        stages = list(_STAGE_PATTERN.finditer(nearby))
        if stages and not re.search(r"(?:总工期|计划工期|合同工期|工期总)", nearby):
            return "stage_duration:" + stages[-1].group()
    if unit == "m2":
        matches = list(re.finditer(r"(?:地上(?:建筑)?(?:面积)?|地下(?:建筑)?(?:面积)?|总建筑面积|建筑面积|建筑规模|总面积)", text[:position] if position is not None else text))
        if matches:
            label = matches[-1].group()
            return "aboveground_area" if label.startswith("地上") else ("underground_area" if label.startswith("地下") else "building_area")
    found = []
    for key, pattern in _OBJECT_PATTERNS:
        for match in re.finditer(pattern, text):
            # Nearby context binds a value to its own object, not another
            # distant number that happens to occur in the same long paragraph.
            distance = abs((position if position is not None else len(text)) - match.end())
            found.append((distance, key))
    if found:
        return min(found)[1]
    return ""


def _notice_actor(value: str, position: int) -> str:
    # Only an actor attached to the notice is its issuer: '承包人接到通知'
    # names the recipient and must not silently become a contractor notice.
    matches = list(re.finditer(
        r"(发包人|招标人|业主|建设单位|监理工程师|监理人|监理|承包人|我方)"
        r"(?:的|发出(?:的)?|下达(?:的)?|发出腾退|腾退)?通知", value[:position],
    ))
    if not matches:
        return ""
    actor = matches[-1].group(1)
    return "employer" if actor in {"发包人", "招标人", "业主", "建设单位"} else ("supervisor" if actor.startswith("监理") else "contractor")


def _prerequisite_text(value: str) -> str:
    text = _compact(value)
    for pattern, replacement in (
        (r"发包人|招标人|业主|建设单位", "发包人"), (r"监理工程师|监理人", "监理"),
        (r"验收通过", "验收合格"), (r"审批通过|同意", "批准"),
    ):
        text = re.sub(pattern, replacement, text)
    return text


def _prerequisites(value: str) -> list[str]:
    text = _text(value)
    conditions = []
    if re.search(r"(?:验收合格|验收通过)(?:(?:之|以)?后|方可|才可|才能)", text):
        conditions.append("验收合格")
    for match in re.finditer(r"(?:经|取得)([^，。；]{1,30}?(?:批准|审批通过|同意))(?:(?:之|以)?后|方可|才可|才能)", text):
        conditions.append(_prerequisite_text(match.group(1)))
    for match in re.finditer(r"(满足[^，。；]{1,35}?)(?:(?:之|以)?后|方可|才可|才能)", text):
        conditions.append(_prerequisite_text(match.group(1)))
    return conditions


def _condition(value: str, position: int, end: int) -> dict[str, Any]:
    around = value[max(0, position - 18):end + 12]
    before, after = value[max(0, position - 8):position], value[end:end + 5]
    bound = "max" if re.search(r"(?:不超过|不得超过|以内|至多|最多|≤)", before + after) or after.startswith("内") else "exact"
    if re.search(r"(?:不少于|不得少于|不低于|至少|≥)", before):
        bound = "min"
    return {
        "bound": bound,
        "trigger": "evacuation_notice" if "通知" in value and re.search(r"腾退|退场|清退", value) else "",
        "notice_actor": _notice_actor(value, position),
        "calendar": "working" if "工作日" in around else "calendar",
    }


def number_bindings(value: str, context: str = "") -> list[dict[str, Any]]:
    text = _compact(value)
    context_text = _compact(context)
    numbers = []
    for match in _NUMBER.finditer(text):
        raw_unit = match.group("unit").lower()
        unit = _UNIT_ALIASES.get(raw_unit, raw_unit)
        scale = Decimal(10000 if match.group("scale") == "万" else (1000 if match.group("scale") == "千" else 1))
        try:
            amount = Decimal(match.group("value")) * scale
        except InvalidOperation:
            continue
        if unit == "yuan_10000":
            amount, unit = amount * 10000, "yuan"
        label = _object(text, unit=unit, position=match.start())
        if not label and context_text:
            label = _object(context_text, unit=unit)
        scope = _scope(text[:match.start()]) or _scope(context_text)
        numbers.append({"value": format(amount.normalize(), "f"), "unit": unit, "object": label,
                        "scope": scope, "conditions": _condition(text, match.start(), match.end())})
    for match in re.finditer(r"(?<![a-z])(?P<grade>hrb|hpb|c|q|mu)(?P<value>\d+(?:\.\d+)?)(?![a-z0-9])", text):
        numbers.append({"value": match.group("value"), "unit": "grade:" + match.group("grade"),
                        "object": "material_grade:" + match.group("grade"), "scope": "",
                        "conditions": {"bound": "exact", "trigger": "", "calendar": "calendar"}})
    return numbers


def assertions(value: str) -> list[dict[str, str]]:
    text = _text(value)
    # Commas inside a formatted decimal were removed by _text first.
    pieces = [piece.strip(" #|：:，,。；;") for piece in re.split(r"[，,；;。！？\n]+", text)]
    output = []
    previous = ""
    for piece in pieces:
        if len(_compact(piece)) < 3:
            previous = previous + piece
            continue
        # Pure introducing labels carry no independent assertion.
        if re.fullmatch(r"(?:质量目标|质量要求|建筑规模|工程概况|建设地点|计划工期|依据|证据来源|其中)", _compact(piece)):
            previous = piece
            continue
        output.append({"text": piece, "context": previous})
        previous = piece
    return output


def _guard(claim: str, passage: str, context: str, source_context: str, expected_scope: str) -> tuple[bool, str, dict[str, Any]]:
    claim_text, source_text = _compact(claim), _compact(passage)
    numbers, source_numbers = number_bindings(claim, context), number_bindings(passage, source_context)
    objects = {item["object"] for item in numbers if item["object"]}
    if _object(claim):
        objects.add(_object(claim))
    info: dict[str, Any] = {"numbers": numbers, "objects": sorted(objects), "conditions": []}
    for item in numbers:
        possible = [other for other in source_numbers if (other["value"], other["unit"]) == (item["value"], item["unit"])]
        if not possible:
            return False, "数值或计量单位在该来源中没有对应", info
        if item["object"]:
            possible = [other for other in possible if other["object"] == item["object"]]
            if not possible:
                return False, "同一数值属于不同对象，不能相互佐证", info
        else:
            # Unknown numeric subjects require close literal support; the
            # value alone never establishes which resource or stage it means.
            if _score(claim, passage) < 0.8:
                return False, "数值所修饰的对象没有充分对应", info
        desired_scope = item["scope"] or expected_scope
        if desired_scope:
            possible = [other for other in possible if not other["scope"] or other["scope"] == desired_scope]
            if not possible:
                return False, "数值的标段或区域范围不一致", info
        compatible = []
        for other in possible:
            cond, source_cond = item["conditions"], other["conditions"]
            if cond["bound"] != source_cond["bound"] or cond["calendar"] != source_cond["calendar"]:
                continue
            if item["object"] == "evacuation_period" and cond["trigger"] != source_cond["trigger"]:
                continue
            if cond.get("notice_actor") and cond["notice_actor"] != source_cond.get("notice_actor"):
                continue
            compatible.append(other)
        if not compatible:
            return False, "数值的期限、上下限或触发条件不一致", info
        info["conditions"].append(item["conditions"])
    # Keep explicit negation and exception clauses. A similarity score cannot
    # turn '不得' into permission or discard a stated exception.
    negated = bool(re.search(r"不得|禁止|严禁|不能|不可|不应|不允许", claim_text))
    source_negated = bool(re.search(r"不得|禁止|严禁|不能|不可|不应|不允许", source_text))
    if negated != source_negated:
        return False, "肯定或否定含义不一致", info
    prerequisites = _prerequisites(passage)
    claim_conditions = _prerequisite_text(context + " " + claim)
    if any(condition not in claim_conditions for condition in prerequisites):
        return False, "来源中的验收、审批或实施前提未完整保留", info
    entities = set(re.findall(r"钢筋|混凝土|砂浆|管道|墙体|楼板|模板|脚手架|基坑|基础|塔吊|场地", claim_text))
    source_entities = set(re.findall(r"钢筋|混凝土|砂浆|管道|墙体|楼板|模板|脚手架|基坑|基础|塔吊|场地", source_text))
    if numbers and entities and not entities.issubset(source_entities):
        return False, "数值绑定的构件、资源或场地对象不一致", info
    exceptions = re.findall(r"(?:除[^，。；]{1,25}外|除非[^，。；]{1,25}|仅(?:限|适用)[^，。；]{1,25})", _text(passage))
    if exceptions and re.search(r"(?:确保|保证|必须|不得|严禁|承诺|执行|适用)", claim_text):
        if any(_compact(exception) not in claim_text for exception in exceptions):
            return False, "来源中的例外或适用限制未保留", info
    source_has_aim = bool(re.search(r"争创|力争|争取|目标|计划", source_text))
    if re.search(r"确保|保证|必定|必获|已获|零投诉|零事故|100%", claim_text):
        for promise in re.findall(r"确保|保证|必定|必获|已获|零投诉|零事故|100%", claim_text):
            if promise not in source_text:
                return False, "新增或强化的承诺缺少相同对象的原文依据", info
        if source_has_aim and re.search(r"鲁班奖|获奖", claim_text) and not re.search(r"确保|保证|已获", source_text):
            return False, "争创目标不能证明保证获奖或既有获奖事实", info
    if "鲁班奖" in claim_text and "鲁班奖" not in source_text:
        return False, "奖项目标没有对应来源", info
    return True, "对象、数值、单位、范围与条件已逐项对应", info


def _simple_structured_fact(claim: str, passage: str, context: str, expected_scope: str) -> bool:
    text = _semantic_text(claim)
    text = re.sub(r"^(?:本项目|本工程|本标段|项目|工程)", "", text)
    if re.fullmatch(r"(?:计划)?工期(?:为|是|要求|目标)?\d+(?:\.\d+)?天", text):
        return bool(number_bindings(claim))
    if re.fullmatch(r"(?:建筑规模)?(?:地上|地下)?(?:建筑)?面积(?:为|是|共|约)?\d+(?:\.\d+)?m2", text):
        return bool(number_bindings(claim, context))
    if re.fullmatch(r"(?:其中)?(?:地上|地下)(?:建筑面积|面积)?\d+(?:\.\d+)?m2", text):
        return bool(number_bindings(claim, context))
    if re.fullmatch(r"(?:质量要求)?(?:争创|力争|争取)鲁班奖", text):
        return bool(re.search(r"争创鲁班奖|力争鲁班奖|争取鲁班奖", _semantic_text(passage)))
    if re.search(r"通知", text) and re.search(r"腾退|退场|清退", text):
        # A narrowly delimited paraphrase: the source and claim both bind
        # this number to the notice-triggered evacuation obligation.
        stripped = re.sub(r"(?:发包人|承包人|接到|收到|腾退|退场|清退|通知|后|之日起|人员|场地|应|须|必须|在|于|内|完成|全部|\d+(?:\.\d+)?天)", "", text)
        if not stripped and number_bindings(claim, context):
            return True
    if text in {"逾期损失自担", "逾期损失由承包人承担"} and re.search(r"通知.{0,15}\d+天内.*腾退", _semantic_text(context)):
        source = _semantic_text(passage)
        return bool(re.search(r"通知后\d+天内.*腾退.*否则.*损失.*承包人承担", source))
    return False


class ProjectEvidenceIndex:
    def __init__(self, project: dict[str, Any], knowledge_sources: list[dict[str, Any]] | None = None) -> None:
        self.snapshot = project_source_snapshot(project)
        self.expected_scope = _scope(str(project.get("name") or ""))
        self.passages: list[dict[str, Any]] = []
        self.by_term: dict[str, set[int]] = defaultdict(set)
        self.by_number: dict[tuple[str, str], set[int]] = defaultdict(set)
        self._add_project_passages()
        for source in knowledge_sources or []:
            kind = "knowledge_publication" if source.get("publication_id") or source.get("unit_id") else "knowledge_reference"
            self._add_text(str(source.get("content") or ""), {
                **source, "source_kind": kind, "source_title": source.get("title") or "知识来源",
                "source_page": ((source.get("sources") or [{}])[0]).get("page_start"),
                "source_hash": source.get("content_hash") or content_hash(str(source.get("content") or "")),
            })
        self.profile_conflicts = self._find_profile_conflicts()

    def _add_text(self, text: str, metadata: dict[str, Any]) -> None:
        joined = "".join(line.strip() for line in normalize_text(text).splitlines() if not re.fullmatch(r"\s*\d+\s*", line))
        chunks = [item for item in re.split(r"(?<=[。；！？])", joined) if item.strip()]
        for chunk in chunks:
            # Keep punctuation and nearby context intact. Very long source
            # blocks are bounded at clause boundaries, never silently sliced
            # between a number and its object or exception.
            segments = [chunk] if len(chunk) <= 1800 else [item for item in re.split(r"(?<=[，,])", chunk) if item.strip()]
            for segment in segments:
                if not _compact(segment):
                    continue
                row = {**metadata, "content": segment, "context": "", "numbers": number_bindings(segment)}
                index = len(self.passages)
                self.passages.append(row)
                for term in _terms(segment):
                    self.by_term[term].add(index)
                for item in row["numbers"]:
                    self.by_number[(item["value"], item["unit"])].add(index)

    def _add_project_passages(self) -> None:
        source = self.snapshot["source_text"]
        matches = list(re.finditer(r"\[第\s*(\d+)\s*页\]", source))
        chunks = [(None, source)] if not matches else [(int(match.group(1)), source[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(source)]) for index, match in enumerate(matches)]
        for page, text in chunks:
            self._add_text(text, {
                "source_kind": "project_tender", "source_title": self.snapshot["name"] + " · 招标原文",
                "source_page": page, "source_hash": self.snapshot["source_hash"],
                "project_id": self.snapshot["project_id"], "page_hash": content_hash(text),
            })

    def _candidates(self, claim: str) -> list[dict[str, Any]]:
        scores: Counter[int] = Counter()
        for term in _terms(claim):
            scores.update(self.by_term.get(term, ()))
        selected = {index for index, _score_value in scores.most_common(50)}
        for number in number_bindings(claim):
            selected.update(self.by_number.get((number["value"], number["unit"]), ()))
        return [self.passages[index] for index in sorted(selected)]

    def match_assertion(self, claim: str, context: str = "", *, check_profile: bool = True) -> dict[str, Any]:
        objects = {item["object"] for item in number_bindings(claim, context)}
        named_object = _object(claim)
        if named_object:
            objects.add(named_object)
        evacuation_liability = bool(re.fullmatch(r"逾期损失(?:自担|由承包人承担)", _compact(claim)) and "腾退" in context)
        if evacuation_liability:
            objects.add("evacuation_liability")
        project_bound = bool(objects & _PROJECT_OBJECTS) or bool(re.search(r"本项目|本工程|本标段", claim))
        conflict_objects = {item["object"] for item in self.profile_conflicts} if check_profile and hasattr(self, "profile_conflicts") else set()
        if objects & conflict_objects:
            return {"supported": False, "score": 0.0, "reason": "用户项目资料与本项目原文冲突，需要先核对来源", "matches": [], "objects": sorted(objects)}
        ranked = []
        for passage in self._candidates(claim + (" " + context if evacuation_liability else "")):
            score = _score(claim, passage["content"])
            if project_bound and passage["source_kind"] != "project_tender":
                ranked.append((False, score, "本项目事实不能由其他项目的通用知识证明", {}, passage))
                continue
            valid, reason, binding = _guard(claim, passage["content"], context, passage["context"], self.expected_scope if project_bound else "")
            simple = valid and _simple_structured_fact(claim, passage["content"], context, self.expected_scope)
            # Do not lower the old threshold: normalization plus strict
            # structured binding handles small, legitimate paraphrases.
            threshold = 0.42 if number_bindings(claim, context) or re.search(r"确保|保证|必须|不得|承诺", claim) else 0.55
            exact = _semantic_text(claim) in _semantic_text(passage["content"])
            supported = valid and (simple or exact or score >= threshold)
            if not supported and valid:
                reason = "该子句尚无足够文字与对象证据，不能仅凭相同数字认定"
            ranked.append((supported, 1.0 if simple or exact else score, reason, binding, passage))
        ranked.sort(key=lambda row: (row[0], row[1], row[4]["source_kind"] == "project_tender"), reverse=True)
        if not ranked:
            return {"supported": False, "score": 0.0, "reason": "完整项目原文与已提供知识中未找到对应证据", "matches": [], "objects": sorted(objects)}
        valid, score, reason, binding, passage = ranked[0]
        match = {
            **{key: passage.get(key) for key in ("source_kind", "source_title", "source_page", "source_hash", "page_hash", "project_id", "unit_id", "publication_id", "retrieval_run_id")},
            "source_excerpt": passage["content"], "score": score, "supported": valid,
            "match_reason": reason, "assertion": claim, **binding,
        }
        return {"supported": valid, "score": score, "reason": reason, "matches": [match], "objects": sorted(objects)}

    def evaluate(self, claim: str) -> dict[str, Any]:
        atoms = assertions(claim)
        results = [self.match_assertion(atom["text"], atom["context"]) for atom in atoms]
        supported = bool(results) and all(item["supported"] for item in results)
        return {
            "supported": supported, "score": min((item["score"] for item in results), default=0.0),
            "reason": "全部子句均已独立对应来源" if supported else "；".join(dict.fromkeys(item["reason"] for item in results if not item["supported"])),
            "matches": [match for item in results for match in item["matches"]],
            "assertions": [{**atom, "supported": result["supported"], "reason": result["reason"]} for atom, result in zip(atoms, results)],
            "project_source_hash": self.snapshot["project_source_hash"],
        }

    def _find_profile_conflicts(self) -> list[dict[str, Any]]:
        profile = self.snapshot["profile"]
        checks = (
            ("duration", "duration", "计划工期{value}"),
            ("building_area_m2", "building_area", "建筑面积{value}平方米"),
            ("aboveground_area_m2", "aboveground_area", "地上建筑面积{value}平方米"),
            ("underground_area_m2", "underground_area", "地下建筑面积{value}平方米"),
            ("quality_target", "quality_award", "{value}"),
        )
        conflicts = []
        for key, object_name, template in checks:
            if profile.get(key) in (None, ""):
                continue
            claim = template.format(value=profile[key])
            pieces = assertions(claim)
            matches = [self.match_assertion(item["text"], item["context"], check_profile=False) for item in pieces]
            if matches and all(item["supported"] for item in matches):
                continue
            relevant = [row for row in self.passages if row["source_kind"] == "project_tender" and (
                object_name in {number["object"] for number in row["numbers"]} or (object_name == "quality_award" and "鲁班奖" in row["content"]))]
            if relevant:
                conflicts.append({"field": key, "object": object_name, "value": profile[key], "reason": "项目资料字段与原文对应对象不一致或未保留其条件",
                                  "source_page": relevant[0].get("source_page"), "source_excerpt": relevant[0]["content"]})
        return conflicts
