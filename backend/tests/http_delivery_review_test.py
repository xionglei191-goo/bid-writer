from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("BID_WRITER_TEST_BASE_URL", "http://127.0.0.1:8876")
TEMP_NAME = "交付审查验证项目临时"


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code} {method} {path}: {detail}") from exc
    return json.loads(body) if body else None


def api_error(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    raise AssertionError(f"Expected HTTP error for {method} {path}")


def wait_for_server() -> dict[str, Any]:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            return api("GET", "/api/status")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Server did not become ready: {last_error}")


def cleanup(created_id: int | None, *packages: dict[str, Any] | None) -> None:
    if created_id:
        try:
            api("DELETE", f"/api/tenders/{created_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup tender failed: {exc}", file=sys.stderr)
    for package in packages:
        if not package:
            continue
        paths = [
            package.get("path"),
            (package.get("components") or {}).get("markdown"),
            (package.get("components") or {}).get("docx"),
            (package.get("components") or {}).get("client_markdown"),
            (package.get("components") or {}).get("client_docx"),
        ]
        for item in paths:
            if item:
                Path(item).unlink(missing_ok=True)


def main() -> int:
    before = wait_for_server()
    kb_audit = api("GET", "/api/kb/audit")
    assert kb_audit["summary"]["title"] == "知识库体检", kb_audit["summary"]
    assert kb_audit["summary"]["indexed_documents"] >= 1, kb_audit["summary"]
    assert kb_audit["directories"], kb_audit
    ocr_queue = api("GET", "/api/kb/ocr-queue")
    assert ocr_queue["summary"]["title"] == "OCR 补录队列", ocr_queue["summary"]
    assert "token_configured" in ocr_queue["summary"], ocr_queue["summary"]
    assert "execution" in ocr_queue["policy"], ocr_queue["policy"]
    llm_status = api("GET", "/api/llm/status")
    assert llm_status["provider"] == "openai-compatible", llm_status
    assert llm_status["generation_mode"] in {"llm", "local_fallback"}, llm_status
    original_enterprise = api("GET", "/api/enterprise-profile")
    enterprise = api(
        "PATCH",
        "/api/enterprise-profile",
        {
            "profile_name": "HTTP 测试投标单位",
            "bidder_name": "HTTP 测试建设集团有限公司",
            "qualification_summary": "建筑工程施工总承包壹级，具备医院综合楼项目技术标编制和履约能力。",
            "capability_summary": "具备总承包组织、深化设计、资源调配和施工协调能力。",
            "quality_system": "执行质量管理体系，落实样板引路、三检制和过程验收。",
            "safety_system": "执行安全文明施工标准化管理，落实风险分级管控和隐患闭环整改。",
            "key_personnel": "拟投入项目经理、技术负责人、质量负责人、安全负责人和机电专业工程师。",
            "equipment_resources": "配置塔吊、施工电梯、测量仪器、检测设备和周转材料。",
            "similar_projects": "具有医院、公共建筑和综合楼类似项目经验。",
            "service_commitment": "配合客户完成资料补充、格式调整和交付前人工复核。",
        },
    )
    assert enterprise["bidder_name"] == "HTTP 测试建设集团有限公司", enterprise
    processing_records = api("GET", "/api/document-processing")
    assert isinstance(processing_records, list), processing_records
    created_id: int | None = None
    intake_created_id: int | None = None
    template_id: int | None = None
    package: dict[str, Any] | None = None
    client_package: dict[str, Any] | None = None
    prepared_client_package: dict[str, Any] | None = None
    try:
        templates = api("GET", "/api/templates")
        assert any(item["name"] == "施工工艺及主要施工方法" for item in templates), templates
        saved_template = api(
            "POST",
            "/api/templates",
            {
                "name": "HTTP 模板验证章节",
                "keywords": "HTTP模板\n模板验证",
                "intent": "用于 HTTP 测试的临时章节模板。",
                "outline": "模板目标\n模板措施",
                "quality_points": "测试完成后必须清理",
            },
        )
        template_id = int(saved_template["id"])
        updated_template = api(
            "PATCH",
            f"/api/templates/{template_id}",
            {
                "name": "HTTP 模板验证章节",
                "keywords": ["HTTP模板", "模板验证"],
                "intent": "已更新的 HTTP 临时章节模板。",
                "outline": ["模板目标", "模板措施", "模板复核"],
                "quality_points": ["测试完成后必须清理"],
            },
        )
        assert updated_template["intent"] == "已更新的 HTTP 临时章节模板。", updated_template
        templates = api("GET", "/api/templates")
        assert any(item["name"] == "HTTP 模板验证章节" and item["source"] == "custom" for item in templates), templates
        template_coverage = api("GET", "/api/templates/coverage")
        assert template_coverage["summary"]["construction_method_template_covered"], template_coverage
        assert template_coverage["summary"]["missing_total"] == 0, template_coverage
        assert template_coverage["summary"]["custom_templates"] >= 1, template_coverage
        assert any("医院" in item["keywords"] for item in template_coverage["construction_methods"]["groups"]), template_coverage
        intake_created = api(
            "POST",
            "/api/intake/create-tender",
            {
                "customer_message": "闲鱼客户咨询：项目名称：HTTP 接单草稿医院技术标。需要技术标 Word 初稿，明天前交，预算 900 元，招标文件稍后发。",
                "customer_name": "HTTP 接单草稿客户",
                "source_platform": "闲鱼",
                "budget_expectation": "900 元",
                "deliverable_format": "DOCX + ZIP 交付包",
                "industry": "医院类",
            },
        )
        intake_created_id = int(intake_created["tender"]["id"])
        assert intake_created["task"]["customer_name"] == "HTTP 接单草稿客户", intake_created
        assert intake_created["intake"]["suggested_task"]["source_platform"] == "闲鱼", intake_created
        intake_communications = api("GET", f"/api/tenders/{intake_created_id}/communications")
        assert intake_communications and intake_communications[0]["stage"] == "询盘", intake_communications
        source_updated = api(
            "POST",
            f"/api/tenders/{intake_created_id}/source",
            {
                "name": "HTTP 接单草稿医院技术标",
                "industry": "医院类",
                "text": """
项目名称：HTTP 接单草稿医院技术标
技术标评分要求：施工总体部署、施工工艺及主要施工方法、质量保证措施、安全文明施工、施工进度计划。
主要施工工艺要求：测量放线、主体结构、防水屋面、装饰装修、医疗专项机电安装必须完整响应。
废标风险：投标文件不得出现与本项目无关的历史项目名称。
""",
                "mode": "replace",
                "reset_plan": True,
                "parse": True,
            },
        )
        assert source_updated["tender"]["id"] == intake_created_id, source_updated
        assert len(source_updated["requirements"]) >= 3, source_updated
        tender = api(
            "POST",
            "/api/tenders/import",
            {
                "name": TEMP_NAME,
                "industry": "医院类",
                "region": "上海",
                "text": """
项目名称：交付审查验证项目临时
建设规模：总建筑面积约 36000 平方米，地下1层，地上9层，框架结构。
计划工期：420 日历天。
质量目标：确保合格，争创市优工程。
安全目标：杜绝重伤事故，创建安全文明工地。
招标范围：土建、装饰装修、机电安装、医疗专项机电和室外配套。
现场条件：医院区域不停诊，材料运输和噪声控制要求高。
特殊要求：医疗专项机电、洁污分流、净化区域施工需重点控制。
技术标评分要求：施工总体部署、施工工艺及主要施工方法、工程重难点分析、质量保证措施、安全文明施工及环境保护、施工进度计划及保证措施。
主要施工工艺要求：测量放线、基坑土方、主体结构、防水屋面、装饰装修、机电安装、医疗专项机电必须完整响应。
投标文件必须响应工期、质量、安全目标，不得出现与本项目无关的历史项目名称。
""",
            },
        )
        created_id = int(tender["id"])
        processing_records = api("GET", f"/api/tenders/{created_id}/document-processing")
        assert isinstance(processing_records, list), processing_records
        task = api(
            "PATCH",
            f"/api/tenders/{created_id}/task",
            {
                "customer_name": "HTTP 验证客户",
                "source_platform": "内部验证",
                "order_no": "HTTP-DELIVERY-001",
                "deadline": "2026-08-10 18:00",
                "budget": "1200 元",
                "deliverable_format": "DOCX + ZIP 交付包",
                "delivery_status": "生产中",
                "delivery_notes": "用于真实 HTTP 验证的临时生产任务。",
            },
        )
        assert task["customer_name"] == "HTTP 验证客户", task
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "待解析", status
        dashboard = api("GET", "/api/orders/dashboard")
        assert any(item["id"] == created_id for item in dashboard["items"]), dashboard
        parsed = api("POST", f"/api/tenders/{created_id}/parse", {})
        assert parsed["requirements"], parsed
        assert parsed["profile"]["duration_days"] == 420, parsed["profile"]
        assert "36000" in parsed["profile"]["building_area"], parsed["profile"]
        assert "地下1层" in parsed["profile"]["floor_info"] and "地上9层" in parsed["profile"]["floor_info"], parsed["profile"]
        assert "市优" in parsed["profile"]["quality_target"], parsed["profile"]
        assert "安全文明" in parsed["profile"]["safety_target"], parsed["profile"]
        assert "医疗专项机电" in parsed["profile"]["special_requirements"], parsed["profile"]
        manual_requirement = api(
            "POST",
            f"/api/tenders/{created_id}/requirements",
            {
                "kind": "评分点",
                "content": "HTTP 人工补充：医疗专项机电调试计划需单独响应。",
                "source_hint": "HTTP 人工校正",
                "priority": "high",
            },
        )
        assert manual_requirement["id"] and manual_requirement["priority"] == "high", manual_requirement
        manual_requirement = api(
            "PATCH",
            f"/api/requirements/{manual_requirement['id']}",
            {"content": "HTTP 人工补充：医疗专项机电调试计划和联动测试需单独响应。", "status": "confirmed"},
        )
        assert manual_requirement["status"] == "confirmed" and "联动测试" in manual_requirement["content"], manual_requirement
        requirements = api("GET", f"/api/tenders/{created_id}/requirements")
        assert any(item["id"] == manual_requirement["id"] for item in requirements), requirements
        deleted_requirement = api("DELETE", f"/api/requirements/{manual_requirement['id']}")
        assert deleted_requirement["deleted"], deleted_requirement
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "待生成目录", status
        materials = api("GET", f"/api/tenders/{created_id}/materials")
        assert any(item["name"] == "完整招标文件" for item in materials), materials
        material = api(
            "POST",
            f"/api/tenders/{created_id}/materials",
            {
                "category": "格式资料",
                "name": "企业技术标格式模板",
                "status": "待补充",
                "source": "客户稍后提供",
            },
        )
        material = api("PATCH", f"/api/materials/{material['id']}", {"status": "已具备", "source": "客户微信"})
        assert material["status"] == "已具备", material
        api(
            "PATCH",
            f"/api/tenders/{created_id}/profile",
            {
                "project_type": "医院综合楼",
                "structure_type": "框架剪力墙结构",
                "building_area": "约52000平方米",
                "floor_info": "地下2层，地上12层",
                "duration_days": 540,
                "quality_target": "确保合格，争创省优工程",
                "safety_target": "杜绝重伤及以上事故，创建安全文明工地",
                "contract_scope": "土建、装饰装修、机电安装、室外配套工程",
                "special_requirements": "医疗专项机电、洁污分流、净化区域施工需重点控制",
            },
        )
        document_settings = api(
            "PATCH",
            f"/api/tenders/{created_id}/document-settings",
            {
                "document_title": "HTTP 交付审查验证项目技术标",
                "document_subtitle": "投标文件技术部分",
                "bidder_name": "HTTP 测试投标单位",
                "prepared_by": "HTTP 编制",
                "reviewed_by": "HTTP 复核",
                "header_text": "HTTP 交付审查验证项目 / 技术标",
                "footer_text": "HTTP 测试页脚：正式投标前人工复核",
                "include_cover": True,
                "include_toc": True,
                "include_response_matrix": True,
                "include_delivery_review": True,
                "section_page_break": True,
            },
        )
        assert document_settings["document_title"] == "HTTP 交付审查验证项目技术标", document_settings
        document_settings = api("GET", f"/api/tenders/{created_id}/document-settings")
        assert document_settings["include_cover"], document_settings
        intake = api(
            "POST",
            f"/api/tenders/{created_id}/intake-assistant",
            {
                "customer_message": "客户从闲鱼咨询：医院综合楼技术标，明天前需要 Word 初稿和交付包，预算 1200 元。",
                "source_platform": "闲鱼",
                "deadline": "2026-08-10 18:00",
                "budget_expectation": "1200 元",
            },
        )
        assert intake["acceptance"]["decision"] in {"可承接", "谨慎承接"}, intake
        assert "HTTP 验证客户" in intake["reply_message"], intake["reply_message"]
        assert intake["suggested_task"]["source_platform"] == "闲鱼", intake
        pricing_rules = api("GET", "/api/pricing/rules")
        assert any(rule["rule_key"] == "base_price" for rule in pricing_rules), pricing_rules
        base_rule = next(rule for rule in pricing_rules if rule["rule_key"] == "base_price")
        original_base_price = base_rule["value"]
        updated_rule = api("PATCH", f"/api/pricing/rules/{base_rule['id']}", {"value": "720"})
        assert updated_rule["value"] == "720", updated_rule
        quote = api(
            "POST",
            f"/api/tenders/{created_id}/price-quote",
            {
                "customer_message": "客户从闲鱼咨询：医院综合楼技术标，明天前需要 Word 初稿和交付包，预算 1200 元。",
                "source_platform": "闲鱼",
                "save_record": True,
            },
        )
        assert quote["suggested_price"] and quote["line_items"], quote
        assert "报价测算" in quote["markdown"], quote["markdown"][:200]
        quote_records = api("GET", f"/api/tenders/{created_id}/quotations")
        assert quote_records and quote_records[0]["suggested_price"] == quote["suggested_price"], quote_records
        restored_rule = api("PATCH", f"/api/pricing/rules/{base_rule['id']}", {"value": original_base_price})
        assert restored_rule["value"] == original_base_price, restored_rule
        confirmation = api(
            "POST",
            f"/api/tenders/{created_id}/order-confirmation",
            {"agreed_price": "1200 元", "revision_rounds": "2"},
        )
        assert "订单确认单" in confirmation["markdown"], confirmation["markdown"][:200]
        assert "不承诺中标结果" in confirmation["customer_message"], confirmation["customer_message"]
        payment_report = api("GET", f"/api/tenders/{created_id}/payments")
        assert payment_report["status"] in {"unpaid", "unknown"}, payment_report
        payment = api(
            "POST",
            f"/api/tenders/{created_id}/payments",
            {
                "amount": "600",
                "payment_stage": "定金",
                "payment_method": "闲鱼",
                "status": "已收款",
                "proof": "HTTP 收款凭证",
            },
        )
        payment_report = api("GET", f"/api/tenders/{created_id}/payments")
        assert payment_report["status"] == "partial" and payment_report["outstanding_amount"] == 600, payment_report
        payment = api("PATCH", f"/api/payments/{payment['id']}", {"amount": "1200", "payment_stage": "全款", "status": "已确认"})
        payment_report = api("GET", f"/api/tenders/{created_id}/payments")
        assert payment_report["status"] == "paid" and payment_report["delivery_authorized"], payment_report
        communication_suggestion = api(
            "POST",
            f"/api/tenders/{created_id}/communications/suggest",
            {
                "stage": "quote",
                "channel": "闲鱼",
                "customer_message": "客户问：这份医院技术标多少钱，明天能不能交？",
            },
        )
        assert communication_suggestion["reply"] and communication_suggestion["stage"] == "报价", communication_suggestion
        communication = api(
            "POST",
            f"/api/tenders/{created_id}/communications",
            {
                "stage": "quote",
                "channel": "闲鱼",
                "customer_message": "客户问：这份医院技术标多少钱，明天能不能交？",
                "system_reply": communication_suggestion["reply"],
                "status": "待发送",
                "notes": "HTTP 报价沟通。",
            },
        )
        assert communication["id"] and communication["status"] == "待发送", communication
        communication = api("PATCH", f"/api/communications/{communication['id']}", {"status": "已发送"})
        assert communication["status"] == "已发送", communication
        communications = api("GET", f"/api/tenders/{created_id}/communications")
        assert communications and communications[0]["stage"] == "报价", communications
        overview = api("GET", f"/api/tenders/{created_id}/overview")
        assert overview["readiness"]["label"] and overview["metrics"]["communications"] >= 1, overview
        command_center = api("GET", f"/api/tenders/{created_id}/command-center")
        assert command_center["tender"]["id"] == created_id, command_center
        assert command_center["cards"] and any(item["key"] == "requirements" for item in command_center["cards"]), command_center
        assert command_center["progress"] and command_center["primary_actions"], command_center
        starter = api("GET", f"/api/tenders/{created_id}/production-starter")
        assert starter["summary"]["strategy"] == "标书生产工具优先", starter["summary"]
        assert starter["customer_reply"] and starter["start_checklist"], starter
        assert "不自动登录平台" in starter["channel_policy"]["automation_boundary"], starter["channel_policy"]
        wizard = api("GET", f"/api/tenders/{created_id}/order-wizard")
        assert wizard["summary"]["title"] == "新单生产向导", wizard["summary"]
        assert wizard["steps"] and wizard["action_bar"], wizard
        assert wizard["copyables"]["customer_reply"], wizard["copyables"]
        channel_ops = api("GET", f"/api/tenders/{created_id}/channel-ops")
        assert channel_ops["summary"]["title"] == "渠道运营助手", channel_ops["summary"]
        assert channel_ops["summary"]["copy_assets"] >= 6, channel_ops["summary"]
        assert any(item["key"] == "listing_description" and "不承诺中标结果" in item["text"] for item in channel_ops["scripts"]), channel_ops["scripts"]
        assert "不自动登录平台" in channel_ops["policy"]["automation_boundary"], channel_ops["policy"]
        plan = api("POST", f"/api/tenders/{created_id}/plan", {})
        assert any(item["section_title"] == "施工工艺及主要施工方法" for item in plan), plan
        plan_audit = api("GET", f"/api/tenders/{created_id}/plan/audit")
        assert plan_audit["summary"]["missing_standard"] == 0, plan_audit
        assert plan_audit["summary"]["construction_method_present"], plan_audit["summary"]
        construction_plan = next(item for item in plan if item["section_title"] == "施工工艺及主要施工方法")
        deleted_plan = api("DELETE", f"/api/section-plans/{construction_plan['id']}")
        assert deleted_plan["deleted"], deleted_plan
        plan_audit = api("GET", f"/api/tenders/{created_id}/plan/audit")
        assert plan_audit["summary"]["missing_standard"] >= 1, plan_audit
        assert not plan_audit["summary"]["construction_method_present"], plan_audit["summary"]
        repaired_plan = api("POST", f"/api/tenders/{created_id}/plan/repair", {})
        assert repaired_plan["added_count"] >= 1, repaired_plan
        assert repaired_plan["after"]["summary"]["missing_standard"] == 0, repaired_plan["after"]["summary"]
        assert repaired_plan["after"]["summary"]["construction_method_present"], repaired_plan["after"]["summary"]
        plan = api("GET", f"/api/tenders/{created_id}/plan")
        assert any(item["section_title"] == "施工工艺及主要施工方法" for item in plan), plan
        response_matrix = api("GET", f"/api/tenders/{created_id}/response-matrix")
        assert response_matrix["summary"]["requirements"] >= 1, response_matrix
        assert response_matrix["summary"]["planned_requirements"] >= 1, response_matrix["summary"]
        late_requirement = api(
            "POST",
            f"/api/tenders/{created_id}/requirements",
            {
                "kind": "评分点",
                "content": "HTTP 后续补充：BIM深化设计、碰撞检查和智慧建造应用需单独响应。",
                "source_hint": "HTTP 后续补充",
                "priority": "high",
            },
        )
        response_matrix = api("GET", f"/api/tenders/{created_id}/response-matrix")
        late_item = next(item for item in response_matrix["requirements"] if item["id"] == late_requirement["id"])
        assert not late_item["planned_sections"] and late_item["auto_linkable"], late_item
        linked_matrix = api("POST", f"/api/tenders/{created_id}/response-matrix/auto-link", {})
        assert linked_matrix["linked_count"] >= 1, linked_matrix
        late_item = next(item for item in linked_matrix["after"]["requirements"] if item["id"] == late_requirement["id"])
        assert late_item["planned_sections"], late_item
        strategy = api("POST", f"/api/tenders/{created_id}/bid-strategy/generate", {})
        assert strategy["positioning"] and strategy["section_focus"], strategy
        strategy = api(
            "PATCH",
            f"/api/tenders/{created_id}/bid-strategy",
            {"status": "approved", "writing_tone": "HTTP 策略口径：强调可执行措施和来源可追溯。"},
        )
        assert strategy["status"] == "approved" and "HTTP 策略口径" in strategy["writing_tone"], strategy
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "生产中", status
        batch = api("POST", f"/api/tenders/{created_id}/plan/generate-all", {"regenerate": False})
        assert batch["generated_count"] >= 1 or batch["skipped_count"] >= 1, batch
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "待导出", status
        drafts = api("GET", f"/api/tenders/{created_id}/drafts")
        assert drafts, drafts
        loaded_draft = api("GET", f"/api/drafts/{drafts[0]['id']}")
        assert loaded_draft["citations"], loaded_draft
        draft_source_preview = api("POST", "/api/sources/preview", loaded_draft["citations"][0])
        assert draft_source_preview["content"] and draft_source_preview["source_path"], draft_source_preview
        risky_draft = api("PATCH", f"/api/drafts/{drafts[0]['id']}", {"content": loaded_draft["content"] + "\n\n风险表述：确保中标。"})
        assert "确保中标" in risky_draft["content"], risky_draft["content"][-100:]
        polish = api("GET", f"/api/tenders/{created_id}/polish")
        assert any(item["search_text"] == "确保中标" for item in polish["suggestions"]), polish
        preview = api(
            "POST",
            f"/api/tenders/{created_id}/replacements/preview",
            {"search_text": "确保中标", "replace_text": "确保技术标响应完整"},
        )
        assert preview["changed_count"] >= 1, preview
        applied = api(
            "POST",
            f"/api/tenders/{created_id}/replacements/apply",
            {"search_text": "确保中标", "replace_text": "确保技术标响应完整", "notes": "HTTP 风险承诺清理"},
        )
        assert applied["record"] and applied["changed_count"] >= 1, applied
        replacement_records = api("GET", f"/api/tenders/{created_id}/replacements")
        assert replacement_records and replacement_records[0]["changed_count"] >= 1, replacement_records
        loaded_draft = api("GET", f"/api/drafts/{drafts[0]['id']}")
        assert "确保中标" not in loaded_draft["content"], loaded_draft["content"][-200:]
        report = api("GET", f"/api/tenders/{created_id}/delivery-review")
        assert report["checklist"], report
        assert report["summary"]["task_missing"] == [], report
        assert "交付审查报告" in report["markdown"], report["markdown"][:200]
        draft_with_revision_issue = api(
            "PATCH",
            f"/api/drafts/{drafts[0]['id']}",
            {"content": loaded_draft["content"] + "\n\nHTTP 修订台账测试风险：确保中标。"},
        )
        assert "确保中标" in draft_with_revision_issue["content"], draft_with_revision_issue["content"][-120:]
        revision_report = api("POST", f"/api/tenders/{created_id}/revision-tasks/sync", {})
        assert revision_report["summary"]["active"] >= 1 and revision_report["summary"]["high_open"] >= 1, revision_report
        revision_item = next(item for item in revision_report["items"] if item["severity"] == "high")
        revision_item = api(
            "PATCH",
            f"/api/revision-tasks/{revision_item['id']}",
            {"status": "处理中", "owner": "HTTP 验证", "notes": "HTTP 修订台账处理中。"},
        )
        assert revision_item["status"] == "处理中" and revision_item["owner"] == "HTTP 验证", revision_item
        api(
            "POST",
            f"/api/tenders/{created_id}/replacements/apply",
            {"search_text": "确保中标", "replace_text": "确保技术标响应完整", "notes": "HTTP 修订台账测试清理"},
        )
        revision_report = api("POST", f"/api/tenders/{created_id}/revision-tasks/sync", {})
        assert revision_report["summary"]["resolved_by_sync"] >= 1, revision_report["summary"]
        revision_report = api("GET", f"/api/tenders/{created_id}/revision-tasks")
        assert any(not item["active"] and item["status"] == "已消除" for item in revision_report["items"]), revision_report
        quality_gate = api("GET", f"/api/tenders/{created_id}/quality-gate")
        assert quality_gate["summary"]["total_sections"] >= 1, quality_gate
        assert "materials_pending_required" in quality_gate["summary"], quality_gate
        assert "质量门禁报告" in quality_gate["markdown"], quality_gate["markdown"][:200]
        final_checklist = api("GET", f"/api/tenders/{created_id}/final-checklist")
        assert final_checklist["items"] and final_checklist["summary"]["required_total"] >= 1, final_checklist
        updated_final_check = api(
            "PATCH",
            f"/api/final-checks/{final_checklist['items'][0]['id']}",
            {"status": "已确认", "owner": "HTTP 验证", "notes": "HTTP 链路确认。"},
        )
        assert updated_final_check["status"] == "已确认", updated_final_check
        final_document = api("GET", f"/api/tenders/{created_id}/final-document")
        assert final_document["content"] and final_document["summary"]["generated_sections"] >= 1, final_document
        assert "技术标章节" in final_document["content"], final_document["content"][:500]
        final_document = api(
            "PATCH",
            f"/api/tenders/{created_id}/final-document",
            {"status": "approved", "approved_by": "HTTP 验证", "notes": "HTTP 定稿确认。"},
        )
        assert final_document["summary"]["approval_status"] == "approved", final_document
        assert final_document["approval"]["approved_by"] == "HTTP 验证", final_document
        review_confirmation = api(
            "PATCH",
            f"/api/tenders/{created_id}/workflow-confirmations/review",
            {"confirmed": True, "confirmed_by": "HTTP 验证"},
        )
        assert review_confirmation["items"]["review"]["confirmed"], review_confirmation
        readiness_before_package = api("GET", f"/api/tenders/{created_id}/production-readiness")
        assert readiness_before_package["summary"]["blockers"] >= 1, readiness_before_package["summary"]
        assert any(item["key"] == "package" for item in readiness_before_package["blockers"]), readiness_before_package["blockers"]
        method_draft = next((item for item in drafts if "施工工艺" in item.get("section_title", "")), drafts[0])
        case_asset = api(
            "POST",
            f"/api/drafts/{method_draft['id']}/case-asset",
            {"tags": "HTTP / 施工工艺 / 高复用", "reusable_score": 5},
        )
        assert case_asset["id"] and case_asset["tender_id"] == created_id, case_asset
        case_assets = api("GET", f"/api/tenders/{created_id}/case-assets")
        assert any(item["id"] == case_asset["id"] for item in case_assets), case_assets
        search_hits = api(
            "POST",
            "/api/sections/search",
            {"query": "施工工艺", "category": "医院类", "heading": "施工工艺", "limit": 8},
        )
        assert any(item.get("source_type") == "case_asset" for item in search_hits), search_hits
        kb_hit = next(item for item in search_hits if item.get("source_type") != "case_asset")
        kb_source_preview = api("POST", "/api/sources/preview", kb_hit)
        assert kb_source_preview["source_type"] == "kb_chunk" and kb_source_preview["content"], kb_source_preview
        assert kb_source_preview["file_exists"] and kb_source_preview["markdown_excerpt"], kb_source_preview
        case_hit = next(item for item in search_hits if item.get("source_type") == "case_asset")
        case_source_preview = api("POST", "/api/sources/preview", case_hit)
        assert case_source_preview["source_type"] == "case_asset" and "施工工艺" in case_source_preview["heading_text"], case_source_preview
        package = api("POST", f"/api/tenders/{created_id}/export", {"format": "package"})
        assert package["delivery_record"]["status"] == "已导出", package
        package_readiness_report = api("GET", f"/api/tenders/{created_id}/production-readiness")
        assert package_readiness_report["summary"]["requirements"] >= 1, package_readiness_report["summary"]
        assert package_readiness_report["summary"]["generated_sections"] >= 1, package_readiness_report["summary"]
        assert package_readiness_report["summary"]["package_readiness"] in {"ready", "warning"}, package_readiness_report["summary"]
        package_validation = api("GET", f"/api/tenders/{created_id}/package-validation")
        assert package_validation["summary"]["package_exists"], package_validation["summary"]
        assert package_validation["summary"]["zip_readable"], package_validation["summary"]
        assert package_validation["summary"]["core_missing"] == 0, package_validation["summary"]
        assert package_validation["summary"]["invalid_json"] == 0, package_validation["summary"]
        assert "交付包清单核验报告" in package_validation["markdown"], package_validation["markdown"][:200]
        delivery_release = api("GET", f"/api/tenders/{created_id}/delivery-release")
        assert delivery_release["summary"]["release_status"] in {"ready", "conditional", "blocked"}, delivery_release["summary"]
        assert delivery_release["checks"] and "交付放行单" in delivery_release["markdown"], delivery_release["markdown"][:200]
        command_center = api("GET", f"/api/tenders/{created_id}/command-center")
        assert command_center["package"]["summary"]["package_exists"], command_center["package"]
        assert command_center["headline"]["next_step_title"], command_center["headline"]
        retrospective = api("GET", f"/api/tenders/{created_id}/retrospective")
        assert retrospective["summary"]["status"] == "待复盘", retrospective
        retro_dashboard = api("GET", "/api/retrospectives/dashboard")
        assert any(item["id"] == created_id for item in retro_dashboard["items"]), retro_dashboard
        closure = api("GET", f"/api/tenders/{created_id}/closure-confirmation")
        assert closure["summary"]["closure_status"] == "待客户确认", closure
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "待客户确认", status
        assistant = api("GET", f"/api/tenders/{created_id}/delivery-assistant")
        assert assistant["summary"]["has_package"], assistant
        assert "HTTP 验证客户" in assistant["customer_message"], assistant["customer_message"]
        deliveries = api("GET", f"/api/tenders/{created_id}/deliveries")
        assert len(deliveries) == 1, deliveries
        delivered = api(
            "PATCH",
            f"/api/deliveries/{deliveries[0]['id']}",
            {
                "status": "已交付",
                "delivery_channel": "内部验证",
                "recipient": "HTTP 验证客户",
                "notes": "HTTP 验证标记已交付。",
            },
        )
        assert delivered["status"] == "已交付" and delivered["delivered_at"], delivered
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "已交付", status
        workflow = api("GET", f"/api/tenders/{created_id}/workflow")
        assert workflow["summary"]["delivered_records"] == 1, workflow
        dashboard = api("GET", "/api/orders/dashboard")
        assert dashboard["summary"]["delivered"] >= 1, dashboard
        closure = api("POST", f"/api/tenders/{created_id}/closure-confirmation", {"reply_deadline": "2026-08-11 12:00"})
        assert closure["summary"]["can_record_closure"], closure
        assert "最终交付版本" in closure["customer_message"], closure["customer_message"]
        feedback = api(
            "POST",
            f"/api/tenders/{created_id}/feedback",
            {
                "feedback_text": "客户要求补充医疗专项机电调试计划。",
                "related_section": "施工工艺及主要施工方法",
                "priority": "high",
                "action_plan": "补充医疗专项机电调试、联动测试和成品保护措施。",
            },
        )
        assert feedback["status"] == "待处理", feedback
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "返工处理", status
        feedback_items = api("GET", f"/api/tenders/{created_id}/feedback")
        assert len(feedback_items) == 1, feedback_items
        workflow = api("GET", f"/api/tenders/{created_id}/workflow")
        assert workflow["summary"]["feedback"]["open"] == 1, workflow
        closure = api("GET", f"/api/tenders/{created_id}/closure-confirmation")
        assert not closure["summary"]["can_close"] and closure["summary"]["closure_status"] == "需返工处理", closure
        dashboard = api("GET", "/api/orders/dashboard")
        assert dashboard["summary"]["feedback_open"] >= 1, dashboard
        assistant = api("GET", f"/api/tenders/{created_id}/delivery-assistant")
        assert "客户反馈未解决" in "\n".join(assistant["actions"]), assistant
        feedback_rework = api("GET", f"/api/tenders/{created_id}/feedback-rework")
        assert feedback_rework["summary"]["open_feedback"] == 1, feedback_rework["summary"]
        assert feedback_rework["summary"]["affected_sections"] >= 1, feedback_rework
        assert "医疗专项机电" in feedback_rework["customer_message"], feedback_rework["customer_message"]
        applied_rework = api("POST", f"/api/tenders/{created_id}/feedback-rework", {"owner": "HTTP 验证"})
        assert applied_rework["summary"]["applied_updates"] == 1, applied_rework["summary"]
        assert applied_rework["items"][0]["status"] == "处理中", applied_rework["items"]
        executed_rework = api("POST", f"/api/tenders/{created_id}/feedback-rework/execute", {"owner": "HTTP 验证"})
        assert executed_rework["execution"]["updated_drafts"] >= 1, executed_rework["execution"]
        assert executed_rework["items"][0]["status"] == "需复核", executed_rework["items"]
        rework_draft = api("GET", f"/api/drafts/{executed_rework['execution']['touched'][0]['draft_id']}")
        assert "客户反馈响应补充" in rework_draft["content"], rework_draft["content"][-800:]
        resolved_feedback = api("PATCH", f"/api/feedback/{feedback['id']}", {"status": "已解决"})
        assert resolved_feedback["status"] == "已解决" and resolved_feedback["resolved_at"], resolved_feedback
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "已交付", status
        closure = api("GET", f"/api/tenders/{created_id}/closure-confirmation")
        assert closure["summary"]["can_record_closure"], closure
        all_status = api("POST", "/api/orders/sync-status", {})
        assert all_status["total"] >= 1, all_status
        workflow = api("GET", f"/api/tenders/{created_id}/workflow")
        assert workflow["summary"]["feedback"]["open"] == 0, workflow
        dashboard = api("GET", "/api/orders/dashboard")
        assert not any(item["id"] == created_id and item["feedback_open"] for item in dashboard["items"]), dashboard
        pipeline = api("POST", f"/api/tenders/{created_id}/production/run", {"export_package": False})
        assert pipeline["steps"][-1]["status"] == "skipped", pipeline
        assert pipeline["status"]["current_status"] == "已交付", pipeline
        assert pipeline["quality_gate"]["summary"]["total_sections"] >= 1, pipeline
        closure = api(
            "POST",
            f"/api/tenders/{created_id}/closures",
            {
                "confirmed_by": "HTTP 验证客户",
                "reply_deadline": "2026-08-11 12:00",
                "confirmation_note": "客户确认最终交付版本无误。",
            },
        )
        assert closure["summary"]["closure_status"] == "已结案", closure
        closures = api("GET", f"/api/tenders/{created_id}/closures")
        assert closures and closures[0]["status"] == "客户已确认", closures
        status = api("POST", f"/api/tenders/{created_id}/task/sync-status", {})
        assert status["current_status"] == "已结案", status
        dashboard = api("GET", "/api/orders/dashboard")
        assert dashboard["summary"]["closed"] >= 1, dashboard
        retrospective = api(
            "PATCH",
            f"/api/tenders/{created_id}/retrospective",
            {
                "status": "已复盘",
                "actual_price": "1200 元",
                "actual_cost": "200 元",
                "work_hours": 4,
                "revision_count": 1,
                "satisfaction": "高",
                "risk_level": "低",
                "reusable_score": 5,
                "industry_tags": "医院类 / 施工工艺 / 高复用",
                "reusable_assets": "施工工艺章节、医疗专项机电调试段落、交付话术。",
                "lessons": "急单需先确认评分办法和图纸清单。",
                "next_action": "沉淀医院类施工工艺模板。",
            },
        )
        assert retrospective["summary"]["status"] == "已复盘", retrospective
        assert retrospective["summary"]["gross_margin_value"] == 1000.0, retrospective
        retro_dashboard = api("GET", "/api/retrospectives/dashboard")
        assert retro_dashboard["summary"]["reviewed"] >= 1, retro_dashboard
        timeline = api("GET", f"/api/tenders/{created_id}/timeline")
        timeline_kinds = {item["kind"] for item in timeline["events"]}
        assert {
            "tender",
            "task",
            "quote",
            "payment",
            "communication",
            "plan",
            "draft",
            "polish",
            "final_document",
            "delivery",
            "feedback",
            "closure",
            "retrospective",
            "case_asset",
        } <= timeline_kinds, timeline
        assert timeline["summary"]["payment_events"] >= 1 and timeline["summary"]["draft_events"] >= 1, timeline["summary"]
        source_audit = api("GET", f"/api/tenders/{created_id}/source-audit")
        assert source_audit["summary"]["drafts"] >= 1 and source_audit["summary"]["total_citations"] >= 1, source_audit
        assert source_audit["summary"]["invalid_citations"] == 0, source_audit["summary"]
        assert source_audit["summary"]["kb_citations"] >= 1, source_audit["summary"]
        with zipfile.ZipFile(package["path"]) as archive:
            names = set(archive.namelist())
            package_starter = json.loads(archive.read("生产启动包.json").decode("utf-8"))
            package_wizard = json.loads(archive.read("新单生产向导.json").decode("utf-8"))
            package_channel_ops = json.loads(archive.read("渠道运营助手.json").decode("utf-8"))
            package_timeline = json.loads(archive.read("项目生产履历.json").decode("utf-8"))
            package_plan_audit = json.loads(archive.read("目录完整性审计.json").decode("utf-8"))
            package_response_matrix = json.loads(archive.read("响应矩阵挂接报告.json").decode("utf-8"))
            package_revision_tasks = json.loads(archive.read("修订任务台账.json").decode("utf-8"))
            package_feedback_rework = json.loads(archive.read("客户反馈返工处理单.json").decode("utf-8"))
            package_source_audit = json.loads(archive.read("引用来源审计.json").decode("utf-8"))
            package_readiness = json.loads(archive.read("项目可交付性评估.json").decode("utf-8"))
            package_validation_json = json.loads(archive.read("交付包清单核验.json").decode("utf-8"))
            package_delivery_release = json.loads(archive.read("交付放行单.json").decode("utf-8"))
        assert {"技术标初稿.docx", "技术标初稿.md", "生产任务.json", "交付审查报告.md", "交付审查报告.json", "交付说明.md", "README.txt"} <= names, names
        assert {"项目总览.md", "项目总览.json"} <= names, names
        assert {"项目生产履历.md", "项目生产履历.json"} <= names, names
        assert {"生产启动包.md", "生产启动包.json"} <= names, names
        assert {"新单生产向导.md", "新单生产向导.json"} <= names, names
        assert {"渠道运营助手.md", "渠道运营助手.json"} <= names, names
        assert {"目录完整性审计.md", "目录完整性审计.json"} <= names, names
        assert {"响应矩阵挂接报告.md", "响应矩阵挂接报告.json"} <= names, names
        assert {"引用来源审计.md", "引用来源审计.json"} <= names, names
        assert {"客户反馈返工处理单.md", "客户反馈返工处理单.json"} <= names, names
        assert {"成稿格式设置.md", "成稿格式设置.json"} <= names, names
        assert {"投标单位资料.md", "投标单位资料.json"} <= names, names
        assert {"投标响应策略.md", "投标响应策略.json"} <= names, names
        assert {"接单评估.md", "接单评估.json"} <= names, names
        assert {"客户沟通记录.md", "客户沟通记录.json"} <= names, names
        assert {"报价测算.md", "报价测算.json"} <= names, names
        assert {"收款记录.md", "收款记录.json"} <= names, names
        assert {"订单确认单.md", "订单确认单.json"} <= names, names
        assert {"质量门禁报告.md", "质量门禁报告.json"} <= names, names
        assert {"修订任务台账.md", "修订任务台账.json"} <= names, names
        assert {"最终核对清单.md", "最终核对清单.json"} <= names, names
        assert {"成稿确认报告.md", "成稿确认报告.json"} <= names, names
        assert {"项目化校正记录.md", "项目化校正记录.json"} <= names, names
        assert {"资料清单.md", "资料清单.json"} <= names, names
        assert {"结案确认单.md", "结案确认单.json"} <= names, names
        assert {"项目复盘.md", "项目复盘.json"} <= names, names
        assert {"案例资产.md", "案例资产.json"} <= names, names
        assert {"项目可交付性评估.md", "项目可交付性评估.json"} <= names, names
        assert {"交付放行单.md", "交付放行单.json"} <= names, names
        assert {"交付包清单核验.md", "交付包清单核验.json"} <= names, names
        assert package_starter["summary"]["strategy"] == "标书生产工具优先", package_starter["summary"]
        assert "不自动登录平台" in package_starter["channel_policy"]["automation_boundary"], package_starter["channel_policy"]
        assert package_wizard["summary"]["title"] == "新单生产向导", package_wizard["summary"]
        assert package_wizard["steps"] and package_wizard["copyables"]["customer_reply"], package_wizard
        assert package_channel_ops["summary"]["title"] == "渠道运营助手", package_channel_ops["summary"]
        assert package_channel_ops["scripts"] and "不自动登录平台" in package_channel_ops["policy"]["automation_boundary"], package_channel_ops
        assert package_timeline["summary"]["payment_events"] >= 1 and package_timeline["summary"]["draft_events"] >= 1, package_timeline["summary"]
        assert package_plan_audit["summary"]["construction_method_present"], package_plan_audit["summary"]
        assert package_plan_audit["summary"]["missing_standard"] == 0, package_plan_audit["summary"]
        assert package_response_matrix["summary"]["requirements"] >= 1, package_response_matrix["summary"]
        assert package_response_matrix["summary"]["high_unplanned_requirements"] == 0, package_response_matrix["summary"]
        assert package_revision_tasks["summary"]["total"] >= 1, package_revision_tasks["summary"]
        assert any(not item["active"] and item["status"] == "已消除" for item in package_revision_tasks["items"]), package_revision_tasks
        assert "total_feedback" in package_feedback_rework["summary"], package_feedback_rework["summary"]
        assert package_source_audit["summary"]["total_citations"] >= 1 and package_source_audit["summary"]["invalid_citations"] == 0, package_source_audit["summary"]
        assert package_readiness["summary"]["requirements"] >= 1, package_readiness["summary"]
        assert package_readiness["summary"]["generated_sections"] >= 1, package_readiness["summary"]
        assert package_validation_json["summary"]["core_missing"] == 0, package_validation_json["summary"]
        assert package_validation_json["summary"]["invalid_json"] == 0, package_validation_json["summary"]
        assert package_delivery_release["summary"]["release_status"] in {"ready", "conditional", "blocked"}, package_delivery_release["summary"]
        assert package_delivery_release["checks"], package_delivery_release
        stale_confirmation = api("GET", f"/api/tenders/{created_id}/workflow-confirmations")
        assert stale_confirmation["items"]["review"]["status"] == "stale", stale_confirmation
        review_confirmation = api(
            "PATCH",
            f"/api/tenders/{created_id}/workflow-confirmations/review",
            {"confirmed": True, "confirmed_by": "HTTP 验证返工复核"},
        )
        assert review_confirmation["items"]["review"]["confirmed"], review_confirmation
        final_document = api(
            "PATCH",
            f"/api/tenders/{created_id}/final-document",
            {"status": "approved", "approved_by": "HTTP 验证返工复核", "notes": "返工后重新定稿。"},
        )
        assert final_document["summary"]["approval_status"] == "approved", final_document
        gate_status, gate_detail = api_error(
            "POST",
            f"/api/tenders/{created_id}/export",
            {"format": "client_package"},
        )
        assert gate_status == 500, (gate_status, gate_detail)
        assert "正式导出未解锁" in gate_detail, gate_detail
        assert "章节未完成大模型生成或二次终审" in gate_detail, gate_detail
        assert "DOCX预检稿" in gate_detail, gate_detail
        print(
            json.dumps(
                {
                    "before_tenders": before.get("tenders"),
                    "temp_tender_id": created_id,
                    "formal_export_gate_blocked": True,
                    "internal_package_ready": True,
                },
                ensure_ascii=False,
            )
        )
        return 0
        client_package = api("POST", f"/api/tenders/{created_id}/export", {"format": "client_package"})
        assert client_package["format"] == "client_zip" and Path(client_package["path"]).exists(), client_package
        assert client_package["delivery_record"]["package_format"] == "client_zip", client_package["delivery_record"]
        with zipfile.ZipFile(client_package["path"]) as archive:
            client_names = set(archive.namelist())
            client_md = archive.read("技术标初稿_客户版.md").decode("utf-8")
        assert {"技术标初稿_客户版.docx", "技术标初稿_客户版.md", "客户发货说明.md", "客户文件清单.txt", "README.txt"} <= client_names, client_names
        assert not {"报价测算.json", "收款记录.json", "引用来源审计.json", "质量门禁报告.json", "交付放行单.json"} & client_names, client_names
        assert "收款记录" not in client_md and "引用来源" not in client_md and "交付审查报告" not in client_md, client_md[:1000]
        client_package_validation = api("GET", f"/api/tenders/{created_id}/client-package-validation")
        assert client_package_validation["summary"]["readiness"] == "ready", client_package_validation["summary"]
        assert client_package_validation["summary"]["forbidden_files"] == 0, client_package_validation["summary"]
        assert client_package_validation["summary"]["content_findings"] == 0, client_package_validation
        client_delivery_preparation = api(
            "POST",
            f"/api/tenders/{created_id}/client-delivery/prepare",
            {"export_internal_package": False},
        )
        prepared_client_package = client_delivery_preparation["client_package"]
        assert client_delivery_preparation["summary"]["ready_to_send"], client_delivery_preparation["summary"]
        assert client_delivery_preparation["summary"]["client_package_ready"], client_delivery_preparation["summary"]
        assert prepared_client_package["format"] == "client_zip" and Path(prepared_client_package["path"]).exists(), prepared_client_package
        assert client_delivery_preparation["client_package_validation"]["summary"]["readiness"] == "ready", client_delivery_preparation["client_package_validation"]["summary"]
        assert client_delivery_preparation["client_delivery_confirmation"]["summary"]["can_send"], client_delivery_preparation["client_delivery_confirmation"]["summary"]
        client_delivery_confirmation = api("GET", f"/api/tenders/{created_id}/client-delivery-confirmation")
        assert client_delivery_confirmation["summary"]["has_client_package"], client_delivery_confirmation["summary"]
        assert client_delivery_confirmation["summary"]["client_package_ready"], client_delivery_confirmation["summary"]
        assert client_delivery_confirmation["summary"]["can_send"], client_delivery_confirmation
        assert "客户版 Word 初稿" in client_delivery_confirmation["customer_message"], client_delivery_confirmation["customer_message"]
        client_delivery_confirmed = api(
            "POST",
            f"/api/tenders/{created_id}/client-delivery-confirmation",
            {
                "delivery_channel": "HTTP 内部验证",
                "recipient": "HTTP 测试客户",
                "confirmation_note": "HTTP 测试确认客户包已人工发出。",
                "customer_message": client_delivery_confirmation["customer_message"],
            },
        )
        assert client_delivery_confirmed["summary"]["delivery_confirmed"], client_delivery_confirmed["summary"]
        assert client_delivery_confirmed["summary"]["latest_client_delivery_status"] == "已交付", client_delivery_confirmed["summary"]
        assert client_delivery_confirmed["latest_client_package"]["delivered_at"], client_delivery_confirmed["latest_client_package"]
        release_after_client_package = api("GET", f"/api/tenders/{created_id}/delivery-release")
        assert any(item["key"] == "client_package_validation" for item in release_after_client_package["checks"]), release_after_client_package["checks"]
        internal_validation_after_client_package = api("GET", f"/api/tenders/{created_id}/package-validation")
        assert internal_validation_after_client_package["summary"]["core_missing"] == 0, internal_validation_after_client_package["summary"]
        print(
            json.dumps(
                {
                    "before_tenders": before.get("tenders"),
                    "kb_audit_directories": kb_audit["summary"].get("directories"),
                    "kb_ocr_pending": ocr_queue["summary"].get("pending_count"),
                    "temp_tender_id": created_id,
                    "sections": report["summary"].get("generated_sections"),
                    "readiness": report["summary"].get("readiness"),
                    "zip_has_delivery_review": True,
                    "zip_has_closure_confirmation": True,
                    "zip_has_retrospective": True,
                    "zip_has_price_quote": True,
                    "zip_has_timeline": True,
                    "zip_has_plan_audit": True,
                    "zip_has_response_matrix": True,
                    "zip_has_revision_tasks": True,
                    "zip_has_source_audit": True,
                    "zip_has_production_readiness": True,
                    "zip_has_delivery_release": True,
                    "zip_has_client_package": True,
                    "zip_has_production_starter": True,
                    "zip_has_order_wizard": True,
                    "zip_has_channel_ops": True,
                    "zip_has_package_validation": True,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        try:
            restore_payload = {
                key: original_enterprise.get(key)
                for key in (
                    "profile_name",
                    "bidder_name",
                    "legal_representative",
                    "contact",
                    "qualification_summary",
                    "capability_summary",
                    "quality_system",
                    "safety_system",
                    "key_personnel",
                    "equipment_resources",
                    "similar_projects",
                    "service_commitment",
                    "notes",
                    "is_default",
                )
            }
            api("PATCH", "/api/enterprise-profile", restore_payload)
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup enterprise profile failed: {exc}", file=sys.stderr)
        if template_id:
            try:
                api("DELETE", f"/api/templates/{template_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup template failed: {exc}", file=sys.stderr)
        if intake_created_id:
            try:
                api("DELETE", f"/api/tenders/{intake_created_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup intake tender failed: {exc}", file=sys.stderr)
        cleanup(created_id, package, client_package, prepared_client_package)
        tenders = api("GET", "/api/tenders")
        assert all(item.get("name") != TEMP_NAME for item in tenders), tenders
        print(json.dumps({"after_temp_removed": True, "remaining_tenders": len(tenders)}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
