from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..utils import content_hash, normalize_text, parse_json


CONFIRMATION_FIELDS = {
    "delivery_confirmation", "professional_reviewer", "reviewed_by",
    "compliance_confirmed", "manual_finalized", "final_approved",
}


def context_fingerprint(project: dict, section: dict, requirements: list[dict], sources: list[dict]) -> str:
    """Pin the scope and source ordering that the preserved prose refers to."""
    value = {
        "project": {key: project.get(key) for key in ("id", "name", "industry", "project_type", "region", "source_text")},
        "profile": {key: value for key, value in (project.get("profile") or {}).items() if key not in CONFIRMATION_FIELDS},
        "section": {"id": section["id"], "title": section["title"], "requirement_ids": section.get("requirement_ids", [])},
        "requirements": [{**{key: row.get(key) for key in ("id", "content", "source_page", "kind", "priority")},
                          "classification": {key: value for key, value in (row.get("classification") or {}).items()
                                             if key not in {"revision", "reviewed_at"}}} for row in requirements],
        "sources": [{key: row.get(key) for key in ("publication_id", "publication_version", "unit_id", "content_hash")} for row in sources],
    }
    return content_hash(json.dumps(value, ensure_ascii=False, sort_keys=True))


def part_fingerprint(part: dict) -> str:
    value = {key: part.get(key) for key in ("index", "requirement_ids", "content", "evidence", "confirmations", "status", "missing_requirement_ids")}
    return content_hash(json.dumps(value, ensure_ascii=False, sort_keys=True))


def read_generation(draft: dict[str, Any] | None) -> dict:
    if not draft:
        return {}
    value = parse_json(draft.get("generation_json"), {}) if "generation_json" in draft else draft.get("generation") or {}
    return value if isinstance(value, dict) else {}


def public_generation(draft: dict) -> dict:
    metadata = read_generation(draft)
    parts = metadata.get("parts") or []
    body_hash = content_hash(draft.get("content") or "")
    manual = metadata.get("manual_content_hash") == body_hash
    valid = bool(not manual and parts and metadata.get("draft_hash") == body_hash
                 and all(part.get("part_hash") == part_fingerprint(part) for part in parts))
    failed = [part for part in parts if part.get("status") in {"fallback", "ai_incomplete"}]
    repair_blocked = bool(metadata.get("repair_blocked"))
    return {
        "status": "manual_edit" if manual else metadata.get("status") or "legacy",
        "can_repair": valid and bool(failed) and not repair_blocked,
        "parts": [{key: part.get(key) for key in ("index", "status", "requirement_ids", "missing_requirement_ids", "ai_run_id", "reused")} for part in parts],
        "failed_parts": len(failed) if not manual else 0,
        "has_snapshot": valid,
        "repair_blocked": repair_blocked,
        "repair_blocked_reason": str(metadata.get("repair_blocked_reason") or ""),
    }


def bind_response_to_generation(draft: dict, requirement_id: int, quote: str, reviewer: str,
                                *, current_context_fingerprint: str, sources_current: bool = True) -> tuple[dict, list[str], dict]:
    """Reconcile one human-verified quote without editing any preserved prose.

    The caller has already checked project ownership, the actual body hash and
    the exact quote, and persists all returned values in its project transaction.
    Only a current, intact AI omission can become complete through this path.
    """
    metadata = deepcopy(read_generation(draft))
    confirmations = list(parse_json(draft.get("confirmations_json"), draft.get("confirmations") or []))
    before = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    detail = {"generation_before_hash": content_hash(before), "updated_part_index": None,
              "previous_confirmations": list(confirmations), "status_before": metadata.get("status"),
              "reviewer": reviewer, "outcome": "response_only"}

    def result():
        detail.update({"generation_after_hash": content_hash(json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
                       "confirmations": list(confirmations), "status_after": metadata.get("status"),
                       "repair_blocked": bool(metadata.get("repair_blocked")),
                       "repair_blocked_reason": metadata.get("repair_blocked_reason") or ""})
        return metadata, confirmations, detail

    if not public_generation(draft)["has_snapshot"]:
        detail["outcome"] = "snapshot_unavailable"
        return result()
    parts = metadata["parts"]
    indices = [part.get("index") for part in parts]
    owners = [part for part in parts if requirement_id in (part.get("requirement_ids") or [])]
    if len(set(indices)) != len(indices) or len(owners) != 1 or any(part.get("status") not in {"ai", "ai_incomplete", "fallback"} for part in parts):
        detail["outcome"] = "snapshot_ambiguous"
        return result()
    if metadata.get("context_fingerprint") != current_context_fingerprint or not sources_current:
        metadata["repair_blocked"] = True
        metadata["repair_blocked_reason"] = "生成时的项目范围或引用来源已变化，本次只记录整体正文响应；请核对当前范围后人工补写或重新生成。"
        detail["outcome"] = "snapshot_context_changed"
        return result()
    owner = owners[0]
    quote_parts = [part["index"] for part in parts if quote in normalize_text(str(part.get("content") or ""))]
    cross_part = owner["index"] not in quote_parts
    detail.update({"owner_part_index": owner["index"], "quote_part_indices": quote_parts,
                   "previous_missing_requirement_ids": list(owner.get("missing_requirement_ids") or [])})
    if cross_part:
        # This remains sticky: a later same-part binding cannot make it safe
        # to overwrite the text an earlier cross-part response relies upon.
        metadata["repair_blocked"] = True
        metadata["repair_blocked_reason"] = "人工响应片段位于其他分段或跨越分段边界，局部补写可能改动已定位依据；请继续人工补写或补录其余响应，齐备后再签审。"
    if owner["status"] != "ai_incomplete" or requirement_id not in (owner.get("missing_requirement_ids") or []):
        detail["outcome"] = "fallback_unchanged" if owner["status"] == "fallback" else "no_recorded_omission"
        return result()

    missing_marker = "缺少可核验的正文响应"
    old_machine = [text for text in owner.get("confirmations") or [] if missing_marker in str(text)]
    missing = [rid for rid in owner["missing_requirement_ids"] if rid != requirement_id]
    owner["evidence"] = [value for value in owner.get("evidence") or [] if value.get("requirement_id") != requirement_id]
    owner["evidence"].append({"requirement_id": requirement_id, "text": quote, "coverage_score": 1.0,
                              "manual_review": {"reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat(),
                                                "target_hash": content_hash(draft["content"]), "owner_part_index": owner["index"],
                                                "quote_part_indices": quote_parts}})
    owner["missing_requirement_ids"] = missing
    owner["confirmations"] = [text for text in owner.get("confirmations") or [] if text not in old_machine]
    if missing:
        owner["confirmations"].append(f"第{owner['index']}/{len(parts)}部分有{len(missing)}项要求缺少可核验的正文响应（要求ID：{','.join(map(str, missing))}），须补充后复核")
    owner["status"] = "ai_incomplete" if missing else "ai"
    owner["part_hash"] = part_fingerprint(owner)
    fallback = sum(part["status"] == "fallback" for part in parts)
    incomplete = sum(part["status"] == "ai_incomplete" for part in parts)
    metadata["status"] = ("incomplete" if incomplete else "ai") if not fallback else "fallback" if fallback == len(parts) else "partial_fallback"
    confirmations = [text for text in confirmations if text not in old_machine]
    for text in owner["confirmations"]:
        if text not in confirmations:
            confirmations.append(text)
    # All recorded omissions have now been reconciled. Remove a legacy copy
    # of that machine notice, while retaining failures, risks and human asks.
    if not incomplete:
        confirmations = [text for text in confirmations if missing_marker not in str(text) or str(text).startswith("高风险表述缺少充分证据：")]
    detail.update({"outcome": "omission_reconciled", "updated_part_index": owner["index"],
                   "missing_requirement_ids": missing, "cross_part": cross_part})
    return result()
