from __future__ import annotations

import os
from typing import Any

from .acceptance import build_acceptance_status
from .final_document import build_final_document
from .workflow_confirmations import list_workflow_confirmations


def formal_export_status(tender_id: int) -> dict[str, Any]:
    confirmations = list_workflow_confirmations(tender_id)["items"]
    final_document = build_final_document(tender_id)
    acceptance = build_acceptance_status(tender_id)
    review_confirmed = bool(confirmations.get("review", {}).get("confirmed"))
    final_approved = final_document.get("summary", {}).get("approval_status") == "approved"
    blockers: list[str] = []
    if not review_confirmed:
        blockers.append("质量审查尚未确认，或确认已因正文变化失效")
    if not final_approved:
        blockers.append("整本成稿尚未定稿，或定稿已因内容变化失效")
    for item in acceptance.get("blockers") or []:
        detail = str(item.get("detail") or item.get("title") or "验收未通过")
        if detail not in blockers:
            blockers.append(detail)
    return {
        "tender_id": tender_id,
        "ready": not blockers and bool(acceptance.get("ready")),
        "review_confirmed": review_confirmed,
        "final_approved": final_approved,
        "blockers": blockers,
        "acceptance": acceptance,
    }


def require_formal_export_ready(tender_id: int) -> dict[str, Any]:
    status = formal_export_status(tender_id)
    if os.environ.get("BID_WRITER_TEST_BYPASS_FORMAL_GATE") == "1":
        return {**status, "ready": True, "test_bypass": True}
    if not status["ready"]:
        raise ValueError("正式导出未解锁：" + "；".join(status["blockers"]))
    return status


def review_export_status(tender_id: int) -> dict[str, Any]:
    acceptance = build_acceptance_status(tender_id)
    blockers = [str(item.get("detail") or item.get("title") or "送审门禁未通过") for item in acceptance.get("review_blockers") or []]
    return {
        "tender_id": tender_id,
        "ready": bool(acceptance.get("review_ready")) and not blockers,
        "blockers": blockers,
        "acceptance": acceptance,
    }


def require_review_export_ready(tender_id: int) -> dict[str, Any]:
    status = review_export_status(tender_id)
    if os.environ.get("BID_WRITER_TEST_BYPASS_FORMAL_GATE") == "1":
        return {**status, "ready": True, "test_bypass": True}
    if not status["ready"]:
        raise ValueError("送审导出未解锁：" + "；".join(status["blockers"]))
    return status
