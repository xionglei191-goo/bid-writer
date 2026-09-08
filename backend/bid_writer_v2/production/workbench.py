from __future__ import annotations

from contextlib import nullcontext
from .response_text import copies_requirement


def is_generation_confirmation(text: str) -> bool:
    return ("AI编写失败" in text or "大模型不可用" in text
            or "缺少可核验的正文响应" in text)


def human_confirmation_indices(draft: dict) -> list[int]:
    return [index for index, text in enumerate(draft.get("confirmations") or [])
            if not str(text).startswith("高风险表述缺少充分证据：") and not is_generation_confirmation(str(text))]


def generation_incomplete(draft: dict) -> bool:
    generation = draft.get("generation") or {}
    if generation.get("status") == "manual_edit":
        return False
    return bool(generation.get("failed_parts") or any(is_generation_confirmation(str(text)) for text in draft.get("confirmations", [])))


def response_metrics(service, project: dict, *, conn=None) -> dict:
    eligible = {item["id"] for item in project["requirements"] if item.get("formal_technical", True)}
    requirements = {item["id"]: item for item in project["requirements"]}
    drafts = {section["draft"]["id"]: section["draft"] for section in project["sections"] if section.get("draft")}
    current_pairs = {(section["draft"]["id"], rid) for section in project["sections"] if section.get("draft") for rid in section["requirement_ids"]}
    responded, signed, response_pairs = set(), set(), set()
    with (nullcontext(conn) if conn is not None else service.db.connect()) as connection:
        rows = connection.execute(
            "SELECT rr.*,EXISTS(SELECT 1 FROM draft_review_decisions rd WHERE rd.draft_id=d.id "
            "AND rd.target_hash=rr.content_fingerprint AND rd.decision='approved') AS signed "
            "FROM requirement_responses rr JOIN project_drafts d ON d.id=rr.draft_id WHERE d.project_id=?",
            (project["id"],),
        ).fetchall()
    for row in rows:
        draft = drafts.get(row["draft_id"])
        if not draft or (row["draft_id"], row["requirement_id"]) not in current_pairs or row["requirement_id"] not in eligible or row["coverage_score"] < .8:
            continue
        if row["content_fingerprint"] != draft["content_hash"] or not str(row["evidence_text"] or "").strip():
            continue
        if row["evidence_text"] not in draft["content"]:
            continue
        if copies_requirement(row["evidence_text"], requirements[row["requirement_id"]]):
            continue
        responded.add(row["requirement_id"])
        response_pairs.add((row["draft_id"], row["requirement_id"]))
        if row["review_status"] == "confirmed" and row["signed"]:
            signed.add(row["requirement_id"])
    mapped = eligible.intersection(rid for section in project["sections"] for rid in section["requirement_ids"])
    return {"mapped": len(mapped), "responded": len(responded), "signed": len(signed),
            "total": len(project["requirements"]), "technical_total": len(eligible),
            "planning_technical_total": project["requirements_workflow"]["planning_technical_total"],
            "responded_ids": sorted(responded), "signed_ids": sorted(signed), "response_pairs": sorted(response_pairs)}


def build_workbench(service, project: dict) -> dict:
    metrics = response_metrics(service, project)
    tasks = []
    requirements = {item["id"]: item for item in project["requirements"]}
    response_pairs = set(metrics["response_pairs"])
    stale = set((project.get("evidence_source") or {}).get("stale_draft_ids") or [])
    for section in project["sections"]:
        draft = section.get("draft")
        common = {"section_id": section["id"], "section_title": section["title"]}
        if not draft:
            tasks.append({**common, "id": f"generation:{section['id']}", "kind": "generation",
                          "title": section["title"] + "尚未生成", "detail": "补写此章，保留其他章节。", "action": "regenerate"})
            continue
        common["draft_id"] = draft["id"]
        generation = draft.get("generation") or {}
        system_failure = generation_incomplete(draft)
        if system_failure:
            tasks.append({**common, "id": f"generation:{section['id']}", "kind": "generation",
                          "title": section["title"] + "有未完成部分", "detail": generation.get("repair_blocked_reason") or (f"{generation.get('failed_parts') or '部分'}个分段需要补写或补充正文响应；已写完整的分段保持原文。" if generation.get("can_repair") else "旧稿没有可验证的分段记录；请补写此章并复核新版本。"),
                          "action": "manual_response" if generation.get("repair_blocked") else "repair" if generation.get("can_repair") else "regenerate"})
        elif draft["id"] not in stale:
            for rid in section["requirement_ids"]:
                requirement = requirements.get(rid)
                if (draft["id"], rid) not in response_pairs and requirement and requirement.get("formal_technical", True):
                    tasks.append({**common, "id": f"response:{section['id']}:{rid}", "kind": "response", "requirement_id": rid,
                                  "source_page": requirement.get("source_page"), "title": f"{requirement['requirement_key']}缺少正文响应",
                                  "detail": requirement["content"], "action": "locate_response"})
        for claim in draft.get("claims", []):
            if claim.get("risk_level") == "high" and claim.get("support_status") in {"unsupported", "invalidated"}:
                tasks.append({**common, "id": f"evidence:{claim['id']}", "kind": "evidence", "claim_id": claim["id"],
                              "title": "关键表述待核验", "detail": claim.get("text") or claim.get("claim_text") or "",
                              "evidence": claim.get("evidence") or claim.get("links") or [], "action": "review_claim"})
        resolved = {item["confirmation_index"] for item in draft.get("confirmation_resolutions", [])}
        for index, text in enumerate(draft.get("confirmations", [])):
            if index in resolved or str(text).startswith("高风险表述缺少充分证据：") or is_generation_confirmation(str(text)):
                continue
            tasks.append({**common, "id": f"information:{draft['id']}:{index}", "kind": "information",
                          "confirmation_index": index, "title": "补充实际资料或方案决定", "detail": text, "action": "information"})
    for requirement in requirements.values():
        rid = requirement["id"]
        if rid in project["requirements_workflow"]["classification_pending_ids"] or rid in project["requirements_workflow"]["checklist_pending_ids"] or (requirement["planning_category"] in {"technical", "unclassified"} and not requirement["section_ids"]):
            tasks.append({"id": f"scope:{rid}", "kind": "information" if rid in project["requirements_workflow"]["checklist_pending_ids"] else "scope", "requirement_id": rid, "source_page": requirement.get("source_page"),
                          "title": f"{requirement['requirement_key']}范围、响应或章节待确定", "detail": requirement["content"], "action": "classify"})
    if stale:
        tasks.insert(0, {"id": "evidence:recheck", "kind": "evidence", "title": "项目原文或资料变化，需要重新核验", "detail": f"{len(stale)}章证据尚未绑定当前项目资料；重新检查不会修改正文或代替签审。", "action": "recheck"})
    field_names = {"duration": "工期", "building_area_m2": "建筑面积", "aboveground_area_m2": "地上建筑面积", "underground_area_m2": "地下建筑面积", "quality_target": "质量目标"}
    for index, conflict in enumerate((project.get("evidence_source") or {}).get("profile_conflicts") or []):
        detail = f"{field_names.get(conflict.get('field'), '项目资料')}填写为“{conflict.get('value')}”，{conflict.get('reason')}。请核对第{conflict.get('source_page') or '待定位'}页：{str(conflict.get('source_excerpt') or '')[:400]}" if isinstance(conflict, dict) else str(conflict)
        tasks.insert(0, {"id": f"information:profile:{index}", "kind": "information", "title": "项目资料与原文不一致", "detail": detail, "action": "information"})
    return {"project_id": project["id"], "metrics": {key: value for key, value in metrics.items() if not key.endswith("_ids") and key != "response_pairs"}, "tasks": tasks}
