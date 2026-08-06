from __future__ import annotations

from typing import Any


COMPLIANCE_TERMS = (
    "暗标",
    "废标",
    "否决投标",
    "否决其投标",
    "无效投标",
    "投标保证金",
    "投标截止时间",
    "投标文件递交",
    "电子投标文件",
    "CA 锁",
    "CA锁",
    "开标程序",
)


def requirement_scope(requirement: dict[str, Any]) -> str:
    persisted = str(requirement.get("response_scope") or "").strip()
    if persisted:
        return persisted
    kind = str(requirement.get("kind") or "").lower()
    content = str(requirement.get("content") or "")
    if kind == "risk" or any(term in content for term in COMPLIANCE_TERMS):
        return "compliance"
    return "chapter"
