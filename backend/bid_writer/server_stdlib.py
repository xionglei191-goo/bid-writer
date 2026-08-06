from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .acceptance import build_acceptance_status, list_acceptance_runs, run_acceptance
from .bid_strategy import generate_bid_strategy, get_bid_strategy, update_bid_strategy
from .case_assets import (
    create_case_asset_from_draft,
    create_case_assets_from_tender,
    delete_case_asset,
    list_case_assets,
    update_case_asset,
)
from .closure_confirmation import build_closure_confirmation, list_closure_records, record_closure_confirmation
from .communications import (
    create_communication,
    delete_communication,
    list_communications,
    suggest_communication_reply,
    update_communication,
)
from .channel_ops import build_channel_ops
from .client_delivery_confirmation import build_client_delivery_confirmation, confirm_client_delivery
from .client_delivery_preparation import prepare_client_delivery
from .client_package_validation import validate_latest_client_package
from .command_center import build_command_center
from .coverage_report import build_coverage_report
from .db import connect, init_db, stats
from .delivery_assistant import build_delivery_assistant
from .delivery_records import list_delivery_records, update_delivery_record
from .delivery_release import build_delivery_release
from .delivery_review import build_delivery_review
from .document_processing import list_document_processing_records
from .document_blocks import (
    create_document_block,
    delete_document_block,
    generate_document_blocks,
    list_document_blocks,
    update_document_block,
)
from .document_settings import get_document_settings, update_document_settings
from .document_templates import delete_document_template, list_document_templates, save_document_template, update_document_template
from .docx_visual_qa import run_docx_visual_qa
from .draft_versions import list_draft_versions, restore_draft_version
from .draft_polish import apply_replacement, list_replacement_records, preview_replacement, scan_project_polish
from .enterprise_profiles import get_enterprise_profile, update_enterprise_profile
from .exporter import export_client_docx, export_client_package, export_docx, export_markdown, export_package
from .formal_export_gate import require_formal_export_ready
from .final_checklist import build_final_checklist, update_final_check_item
from .final_document import build_final_document, update_final_document
from .feedback import create_feedback_item, list_feedback_items, update_feedback_item
from .feedback_rework import apply_feedback_rework_plan, build_feedback_rework, execute_feedback_rework
from .generator import generate_draft
from .intake_assistant import build_intake_assistant, create_intake_tender
from .kb_audit import build_kb_audit
from .kb_importer import import_knowledge_base
from .kb_ocr_queue import build_kb_ocr_queue, run_kb_ocr_item
from .llm_config import llm_settings, probe_llm
from .materials import create_material_item, delete_material_item, list_material_items, update_material_item
from .order_dashboard import build_order_dashboard
from .order_confirmation import build_order_confirmation
from .order_wizard import build_order_wizard
from .package_validation import validate_latest_package
from .payments import create_payment_record, delete_payment_record, payment_summary, update_payment_record
from .planner import (
    add_section_plan,
    audit_section_plan,
    build_section_plan,
    delete_section_plan,
    generate_all_from_plan,
    generate_from_plan,
    list_section_plans,
    repair_section_plan,
    update_section_plan,
)
from .pricing import build_price_quote, ensure_default_pricing_rules, list_quotation_records, update_pricing_rule
from .production_readiness import build_production_readiness
from .production_pipeline import run_production_pipeline
from .production_starter import build_production_starter
from .production_tasks import get_production_task, update_production_task
from .project_overview import build_project_overview
from .project_timeline import build_project_timeline
from .project_profiles import get_project_profile, update_project_profile
from .quality_gate import build_quality_gate
from .retrieval import search_chunks
from .response_matrix import auto_link_response_matrix, build_response_matrix, realign_response_matrix
from .requirement_responses import classify_tender_requirements, list_requirement_responses, rebuild_requirement_responses, update_requirement_response
from .review import review_draft, review_tender
from .retrospective import build_project_retrospective, build_retrospective_dashboard, update_project_retrospective
from .revision_tasks import list_revision_tasks, sync_revision_tasks, update_revision_task
from .section_templates import all_templates, delete_section_template, save_section_template, template_coverage_report, update_section_template
from .source_audit import build_source_audit
from .source_preview import preview_source
from .settings import EXPORT_DIR, STATIC_DIR, UPLOAD_DIR
from .task_status import sync_all_production_status, sync_production_status
from .template_assets import template_asset_catalog
from .benchmarks import build_benchmark_dataset
from .tenders import (
    create_tender,
    create_requirement,
    delete_requirement,
    delete_tender,
    get_draft,
    get_requirements,
    get_tender,
    list_drafts,
    list_tenders,
    parse_tender,
    update_requirement,
    update_draft,
    update_tender_source,
)
from .workflow import build_workflow_status
from .workflow_confirmations import list_workflow_confirmations, set_workflow_confirmation
from .visual_assets import auto_validate_technical_visuals, batch_review_visual_assets, get_visual_asset, import_docx_images, import_image_file, list_visual_assets, resolve_asset_path, update_visual_asset_review, visual_review_summary
from .visual_pipeline import build_visual_plan, generate_hybrid_visual, image_generation_settings


def _log(message: str) -> None:
    try:
        print(message, flush=True)
    except Exception:
        pass


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    return json.loads(body or "{}")


def _parse_multipart(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type", "")
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Missing multipart boundary")
    boundary = match.group("boundary").strip('"').encode("utf-8")
    length = int(handler.headers.get("Content-Length", "0") or 0)
    body = handler.rfile.read(length)
    result: dict[str, object] = {}
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="ignore")
        disposition = next((line for line in headers.splitlines() if line.lower().startswith("content-disposition:")), "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        content = content.rstrip(b"\r\n")
        if filename_match:
            result[name] = {
                "filename": Path(filename_match.group(1)).name,
                "content": content,
            }
        else:
            result[name] = content.decode("utf-8", errors="ignore")
    return result


class BidWriterHandler(BaseHTTPRequestHandler):
    server_version = "BidWriterMVP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/status":
                conn = connect()
                try:
                    _json_response(self, 200, stats(conn))
                finally:
                    conn.close()
                return
            if path == "/api/kb/audit":
                _json_response(self, 200, build_kb_audit())
                return
            if path == "/api/kb/ocr-queue":
                _json_response(self, 200, build_kb_ocr_queue())
                return
            if path == "/api/llm/status":
                _json_response(self, 200, llm_settings())
                return
            if path == "/api/enterprise-profile":
                _json_response(self, 200, get_enterprise_profile())
                return
            if path == "/api/templates":
                _json_response(self, 200, all_templates())
                return
            if path == "/api/templates/coverage":
                _json_response(self, 200, template_coverage_report())
                return
            if path == "/api/template-assets":
                _json_response(self, 200, template_asset_catalog())
                return
            if path == "/api/benchmarks":
                _json_response(self, 200, build_benchmark_dataset())
                return
            if path == "/api/document-templates":
                _json_response(self, 200, list_document_templates())
                return
            if path == "/api/orders/dashboard":
                _json_response(self, 200, build_order_dashboard())
                return
            if path == "/api/retrospectives/dashboard":
                _json_response(self, 200, build_retrospective_dashboard())
                return
            if path == "/api/pricing/rules":
                _json_response(self, 200, ensure_default_pricing_rules())
                return
            if path == "/api/case-assets":
                _json_response(self, 200, list_case_assets())
                return
            if path == "/api/document-processing":
                _json_response(self, 200, list_document_processing_records())
                return
            if path == "/api/tenders":
                _json_response(self, 200, list_tenders())
                return
            if path == "/api/image-generation/settings":
                _json_response(self, 200, image_generation_settings())
                return
            match = re.match(r"^/api/tenders/(\d+)$", path)
            if match:
                _json_response(self, 200, get_tender(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/document-processing$", path)
            if match:
                _json_response(self, 200, list_document_processing_records(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/requirements$", path)
            if match:
                _json_response(self, 200, get_requirements(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/requirement-responses$", path)
            if match:
                tender_id = int(match.group(1))
                rebuild_requirement_responses(tender_id)
                _json_response(self, 200, list_requirement_responses(tender_id))
                return
            match = re.match(r"^/api/tenders/(\d+)/profile$", path)
            if match:
                _json_response(self, 200, get_project_profile(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/task$", path)
            if match:
                _json_response(self, 200, get_production_task(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/document-settings$", path)
            if match:
                _json_response(self, 200, get_document_settings(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/document-blocks$", path)
            if match:
                _json_response(self, 200, list_document_blocks(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-assets$", path)
            if match:
                _json_response(self, 200, list_visual_assets(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-plan$", path)
            if match:
                _json_response(self, 200, build_visual_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-review$", path)
            if match:
                _json_response(self, 200, visual_review_summary(int(match.group(1))))
                return
            match = re.match(r"^/api/visual-assets/(\d+)/file$", path)
            if match:
                asset = get_visual_asset(int(match.group(1)))
                self._send_file(resolve_asset_path(str(asset.get("file_path") or "")))
                return
            match = re.match(r"^/api/tenders/(\d+)/bid-strategy$", path)
            if match:
                _json_response(self, 200, get_bid_strategy(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/final-document$", path)
            if match:
                _json_response(self, 200, build_final_document(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/materials$", path)
            if match:
                _json_response(self, 200, list_material_items(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/intake-assistant$", path)
            if match:
                _json_response(self, 200, build_intake_assistant(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/order-confirmation$", path)
            if match:
                _json_response(self, 200, build_order_confirmation(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/communications$", path)
            if match:
                _json_response(self, 200, list_communications(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/workflow$", path)
            if match:
                _json_response(self, 200, build_workflow_status(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/workflow-confirmations$", path)
            if match:
                _json_response(self, 200, list_workflow_confirmations(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/command-center$", path)
            if match:
                _json_response(self, 200, build_command_center(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/production-starter$", path)
            if match:
                _json_response(self, 200, build_production_starter(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/order-wizard$", path)
            if match:
                _json_response(self, 200, build_order_wizard(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/channel-ops$", path)
            if match:
                _json_response(self, 200, build_channel_ops(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/overview$", path)
            if match:
                _json_response(self, 200, build_project_overview(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/timeline$", path)
            if match:
                _json_response(self, 200, build_project_timeline(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/plan$", path)
            if match:
                _json_response(self, 200, list_section_plans(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/plan/audit$", path)
            if match:
                _json_response(self, 200, audit_section_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/coverage$", path)
            if match:
                _json_response(self, 200, build_coverage_report(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/response-matrix$", path)
            if match:
                _json_response(self, 200, build_response_matrix(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/source-audit$", path)
            if match:
                _json_response(self, 200, build_source_audit(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/delivery-review$", path)
            if match:
                _json_response(self, 200, build_delivery_review(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/delivery-release$", path)
            if match:
                _json_response(self, 200, build_delivery_release(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/production-readiness$", path)
            if match:
                _json_response(self, 200, build_production_readiness(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/package-validation$", path)
            if match:
                _json_response(self, 200, validate_latest_package(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/client-package-validation$", path)
            if match:
                _json_response(self, 200, validate_latest_client_package(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/client-delivery-confirmation$", path)
            if match:
                _json_response(self, 200, build_client_delivery_confirmation(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/final-checklist$", path)
            if match:
                _json_response(self, 200, build_final_checklist(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/quality-gate$", path)
            if match:
                _json_response(self, 200, build_quality_gate(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/acceptance$", path)
            if match:
                tender_id = int(match.group(1))
                _json_response(self, 200, {"current": build_acceptance_status(tender_id), "runs": list_acceptance_runs(tender_id)})
                return
            match = re.match(r"^/api/tenders/(\d+)/revision-tasks$", path)
            if match:
                _json_response(self, 200, list_revision_tasks(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/delivery-assistant$", path)
            if match:
                _json_response(self, 200, build_delivery_assistant(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/deliveries$", path)
            if match:
                _json_response(self, 200, list_delivery_records(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/feedback$", path)
            if match:
                _json_response(self, 200, list_feedback_items(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/feedback-rework$", path)
            if match:
                _json_response(self, 200, build_feedback_rework(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/closure-confirmation$", path)
            if match:
                _json_response(self, 200, build_closure_confirmation(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/closures$", path)
            if match:
                _json_response(self, 200, list_closure_records(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/retrospective$", path)
            if match:
                _json_response(self, 200, build_project_retrospective(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/price-quote$", path)
            if match:
                _json_response(self, 200, build_price_quote(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/quotations$", path)
            if match:
                _json_response(self, 200, list_quotation_records(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/payments$", path)
            if match:
                _json_response(self, 200, payment_summary(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/case-assets$", path)
            if match:
                _json_response(self, 200, list_case_assets(tender_id=int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/polish$", path)
            if match:
                _json_response(self, 200, scan_project_polish(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/replacements$", path)
            if match:
                _json_response(self, 200, list_replacement_records(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/drafts$", path)
            if match:
                _json_response(self, 200, list_drafts(int(match.group(1))))
                return
            match = re.match(r"^/api/drafts/(\d+)$", path)
            if match:
                _json_response(self, 200, get_draft(int(match.group(1))))
                return
            match = re.match(r"^/api/drafts/(\d+)/versions$", path)
            if match:
                _json_response(self, 200, list_draft_versions(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/review$", path)
            if match:
                _json_response(self, 200, review_tender(int(match.group(1))))
                return
            if path.startswith("/exports/"):
                target = EXPORT_DIR / Path(path).name
                return self._send_file(target)
            return self._send_static(path)
        except Exception as exc:  # noqa: BLE001
            _json_response(self, 500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            multipart_upload = (
                path in {"/api/tenders/upload", "/api/document-templates/upload"}
                or re.match(r"^/api/tenders/\d+/source/upload$", path)
            )
            payload = {} if multipart_upload else _read_json(self)
            if path == "/api/kb/import":
                _json_response(
                    self,
                    200,
                    import_knowledge_base(
                        reset=bool(payload.get("reset")),
                        limit_documents=payload.get("limit_documents") or None,
                    ),
                )
                return
            match = re.match(r"^/api/kb/ocr-queue/([^/]+)/run$", path)
            if match:
                _json_response(self, 200, run_kb_ocr_item(match.group(1), reindex=bool(payload.get("reindex", True))))
                return
            if path == "/api/orders/sync-status":
                _json_response(self, 200, sync_all_production_status())
                return
            if path == "/api/llm/probe":
                _json_response(self, 200, probe_llm())
                return
            if path == "/api/enterprise-profile":
                _json_response(self, 200, update_enterprise_profile(payload))
                return
            if path == "/api/sections/search":
                _json_response(
                    self,
                    200,
                    search_chunks(
                        query=payload.get("query", ""),
                        category=payload.get("category", ""),
                        project_type=payload.get("project_type", ""),
                        heading=payload.get("heading", ""),
                        limit=int(payload.get("limit", 10)),
                    ),
                )
                return
            if path == "/api/sources/preview":
                _json_response(self, 200, preview_source(payload))
                return
            if path == "/api/templates":
                _json_response(self, 200, save_section_template(payload))
                return
            if path == "/api/document-templates":
                _json_response(self, 200, save_document_template(payload))
                return
            if path == "/api/document-templates/upload":
                form = _parse_multipart(self)
                file_info = form.get("file")
                if not isinstance(file_info, dict):
                    raise ValueError("Missing upload file")
                filename = str(file_info.get("filename") or "enterprise_template.docx")
                content = file_info.get("content")
                if Path(filename).suffix.lower() != ".docx" or not isinstance(content, bytes):
                    raise ValueError("企业文档模板必须是 DOCX 文件。")
                target = UPLOAD_DIR / filename
                target.write_bytes(content)
                _json_response(
                    self,
                    200,
                    save_document_template(
                        {
                            "name": str(form.get("name") or Path(filename).stem),
                            "source_docx_path": str(target),
                            "version": str(form.get("version") or "1.0"),
                            "is_default": str(form.get("is_default") or "").lower() in {"1", "true", "yes", "是"},
                        }
                    ),
                )
                return
            match = re.match(r"^/api/document-templates/(\d+)$", path)
            if match:
                _json_response(self, 200, update_document_template(int(match.group(1)), payload))
                return
            if path == "/api/tenders/import":
                _json_response(
                    self,
                    200,
                    create_tender(
                        name=payload.get("name", ""),
                        text=payload.get("text", ""),
                        industry=payload.get("industry", ""),
                        region=payload.get("region", ""),
                    ),
                )
                return
            if path == "/api/intake/create-tender":
                _json_response(self, 200, create_intake_tender(payload))
                return
            if path == "/api/tenders/upload":
                form = _parse_multipart(self)
                file_info = form.get("file")
                if not isinstance(file_info, dict):
                    raise ValueError("Missing upload file")
                filename = str(file_info.get("filename") or "tender.txt")
                content = file_info.get("content")
                if not isinstance(content, bytes):
                    raise ValueError("Invalid upload file")
                target = UPLOAD_DIR / filename
                target.write_bytes(content)
                _json_response(
                    self,
                    200,
                    create_tender(
                        name=Path(filename).stem,
                        file_path=str(target),
                        industry=str(form.get("industry") or ""),
                        region=str(form.get("region") or ""),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/source/upload$", path)
            if match:
                form = _parse_multipart(self)
                file_info = form.get("file")
                if not isinstance(file_info, dict):
                    raise ValueError("Missing upload file")
                filename = str(file_info.get("filename") or "tender.txt")
                content = file_info.get("content")
                if not isinstance(content, bytes):
                    raise ValueError("Invalid upload file")
                target = UPLOAD_DIR / filename
                target.write_bytes(content)
                _json_response(
                    self,
                    200,
                    update_tender_source(
                        int(match.group(1)),
                        file_path=str(target),
                        name=Path(filename).stem,
                        industry=str(form.get("industry") or "") or None,
                        region=str(form.get("region") or "") or None,
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/parse$", path)
            if match:
                _json_response(self, 200, parse_tender(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/source$", path)
            if match:
                _json_response(
                    self,
                    200,
                    update_tender_source(
                        int(match.group(1)),
                        text=str(payload.get("text") or ""),
                        name=str(payload.get("name") or ""),
                        industry=payload.get("industry") if "industry" in payload else None,
                        region=payload.get("region") if "region" in payload else None,
                        mode=str(payload.get("mode") or "replace"),
                        reset_plan=bool(payload.get("reset_plan", True)),
                        parse=bool(payload.get("parse", True)),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/requirements$", path)
            if match:
                _json_response(self, 200, create_requirement(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/requirements/reclassify$", path)
            if match:
                tender_id = int(match.group(1))
                _json_response(
                    self,
                    200,
                    {
                        "classification": classify_tender_requirements(tender_id),
                        "evidence": rebuild_requirement_responses(tender_id),
                    },
                )
                return
            match = re.match(r"^/api/requirement-responses/(\d+)$", path)
            if match:
                _json_response(self, 200, update_requirement_response(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/profile$", path)
            if match:
                _json_response(self, 200, update_project_profile(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/task$", path)
            if match:
                _json_response(self, 200, update_production_task(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/task/sync-status$", path)
            if match:
                _json_response(self, 200, sync_production_status(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/document-settings$", path)
            if match:
                _json_response(self, 200, update_document_settings(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/document-blocks/generate$", path)
            if match:
                _json_response(
                    self,
                    200,
                    generate_document_blocks(int(match.group(1)), regenerate=bool(payload.get("regenerate", True))),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/document-blocks$", path)
            if match:
                _json_response(self, 200, create_document_block(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/document-blocks/(\d+)$", path)
            if match:
                _json_response(self, 200, update_document_block(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-assets/import$", path)
            if match:
                tender_id = int(match.group(1))
                source_path = str(payload.get("source_path") or "")
                if Path(source_path).suffix.lower() == ".docx":
                    result = import_docx_images(
                        source_path,
                        tender_id=tender_id,
                        industry=str(payload.get("industry") or ""),
                        section_title=str(payload.get("section_title") or ""),
                    )
                else:
                    result = import_image_file(
                        source_path,
                        tender_id=tender_id,
                        asset_type=str(payload.get("asset_type") or "project_image"),
                        name=str(payload.get("name") or ""),
                        caption=str(payload.get("caption") or ""),
                        industry=str(payload.get("industry") or ""),
                        section_title=str(payload.get("section_title") or ""),
                    )
                _json_response(self, 200, result)
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-assets/generate-hybrid$", path)
            if match:
                _json_response(
                    self,
                    200,
                    generate_hybrid_visual(
                        int(match.group(1)),
                        scene_key=str(payload.get("scene_key") or ""),
                        source_path=str(payload.get("source_path") or ""),
                        section_title=str(payload.get("section_title") or ""),
                        attach=bool(payload.get("attach", True)),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-assets/review-batch$", path)
            if match:
                _json_response(
                    self,
                    200,
                    batch_review_visual_assets(
                        int(match.group(1)),
                        [int(item) for item in payload.get("asset_ids") or []],
                        review_status=str(payload.get("review_status") or "待复核"),
                        review_notes=str(payload.get("review_notes") or ""),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/visual-assets/auto-validate$", path)
            if match:
                _json_response(self, 200, auto_validate_technical_visuals(int(match.group(1))))
                return
            match = re.match(r"^/api/visual-assets/(\d+)/review$", path)
            if match:
                _json_response(
                    self,
                    200,
                    update_visual_asset_review(
                        int(match.group(1)),
                        review_status=str(payload.get("review_status") or "待复核"),
                        review_notes=str(payload.get("review_notes") or ""),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/bid-strategy/generate$", path)
            if match:
                _json_response(self, 200, generate_bid_strategy(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/bid-strategy$", path)
            if match:
                _json_response(self, 200, update_bid_strategy(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/final-document$", path)
            if match:
                _json_response(self, 200, update_final_document(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/intake-assistant$", path)
            if match:
                _json_response(self, 200, build_intake_assistant(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/order-confirmation$", path)
            if match:
                _json_response(self, 200, build_order_confirmation(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/communications/suggest$", path)
            if match:
                _json_response(self, 200, suggest_communication_reply(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/communications$", path)
            if match:
                _json_response(self, 200, create_communication(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/materials$", path)
            if match:
                _json_response(self, 200, create_material_item(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/production/run$", path)
            if match:
                _json_response(self, 200, run_production_pipeline(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/client-delivery/prepare$", path)
            if match:
                _json_response(self, 200, prepare_client_delivery(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/plan$", path)
            if match:
                _json_response(self, 200, build_section_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/workflow-confirmations/(parse|outline|review)$", path)
            if match:
                _json_response(
                    self,
                    200,
                    set_workflow_confirmation(int(match.group(1)), match.group(2), payload),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/plan/repair$", path)
            if match:
                _json_response(self, 200, repair_section_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/response-matrix/auto-link$", path)
            if match:
                _json_response(self, 200, auto_link_response_matrix(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/response-matrix/realign$", path)
            if match:
                _json_response(self, 200, realign_response_matrix(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/acceptance/run$", path)
            if match:
                _json_response(
                    self,
                    200,
                    run_acceptance(
                        int(match.group(1)),
                        manual_edit_hours=payload.get("manual_edit_hours"),
                        conclusion=str(payload.get("conclusion") or ""),
                        exports=payload.get("exports") or {},
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/docx-preflight$", path)
            if match:
                tender_id = int(match.group(1))
                exported = export_docx(tender_id)
                visual = run_docx_visual_qa(tender_id, exported["path"])
                _json_response(self, 200, {**exported, "layout_audit": visual})
                return
            match = re.match(r"^/api/tenders/(\d+)/revision-tasks/sync$", path)
            if match:
                _json_response(self, 200, sync_revision_tasks(int(match.group(1))))
                return
            match = re.match(r"^/api/tenders/(\d+)/plan/sections$", path)
            if match:
                _json_response(
                    self,
                    200,
                    add_section_plan(
                        int(match.group(1)),
                        section_title=str(payload.get("section_title") or ""),
                        template_name=str(payload.get("template_name") or ""),
                        requirement_ids=payload.get("requirement_ids") or [],
                        order_no=payload.get("order_no") or None,
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/feedback$", path)
            if match:
                _json_response(self, 200, create_feedback_item(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/feedback-rework$", path)
            if match:
                _json_response(self, 200, apply_feedback_rework_plan(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/feedback-rework/execute$", path)
            if match:
                _json_response(self, 200, execute_feedback_rework(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/closure-confirmation$", path)
            if match:
                _json_response(self, 200, build_closure_confirmation(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/client-delivery-confirmation$", path)
            if match:
                _json_response(self, 200, confirm_client_delivery(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/closures$", path)
            if match:
                _json_response(self, 200, record_closure_confirmation(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/retrospective$", path)
            if match:
                _json_response(self, 200, update_project_retrospective(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/price-quote$", path)
            if match:
                _json_response(
                    self,
                    200,
                    build_price_quote(
                        int(match.group(1)),
                        payload,
                        save_record=bool(payload.get("save_record")),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/payments$", path)
            if match:
                _json_response(self, 200, create_payment_record(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/pricing/rules/(\d+)$", path)
            if match:
                _json_response(self, 200, update_pricing_rule(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/templates/(\d+)$", path)
            if match:
                _json_response(self, 200, update_section_template(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/requirements/(\d+)$", path)
            if match:
                _json_response(self, 200, update_requirement(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/case-assets$", path)
            if match:
                _json_response(self, 200, create_case_assets_from_tender(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/replacements/preview$", path)
            if match:
                _json_response(
                    self,
                    200,
                    preview_replacement(
                        int(match.group(1)),
                        str(payload.get("search_text") or ""),
                        str(payload.get("replace_text") or ""),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/replacements/apply$", path)
            if match:
                _json_response(
                    self,
                    200,
                    apply_replacement(
                        int(match.group(1)),
                        str(payload.get("search_text") or ""),
                        str(payload.get("replace_text") or ""),
                        str(payload.get("notes") or ""),
                    ),
                )
                return
            match = re.match(r"^/api/tenders/(\d+)/plan/generate-all$", path)
            if match:
                _json_response(
                    self,
                    200,
                    generate_all_from_plan(
                        int(match.group(1)),
                        regenerate=bool(payload.get("regenerate")),
                    ),
                )
                return
            if path == "/api/drafts/generate":
                _json_response(
                    self,
                    200,
                    generate_draft(
                        tender_id=int(payload["tender_id"]),
                        section_title=payload["section_title"],
                        requirement_ids=payload.get("requirement_ids") or [],
                        category=payload.get("category", ""),
                    ),
                )
                return
            match = re.match(r"^/api/section-plans/(\d+)/generate$", path)
            if match:
                _json_response(self, 200, generate_from_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/section-plans/(\d+)$", path)
            if match:
                _json_response(
                    self,
                    200,
                    update_section_plan(
                        int(match.group(1)),
                        section_title=payload.get("section_title"),
                        order_no=payload.get("order_no"),
                        requirement_ids=payload.get("requirement_ids") if "requirement_ids" in payload else None,
                        status=payload.get("status"),
                    ),
                )
                return
            match = re.match(r"^/api/drafts/(\d+)$", path)
            if match:
                _json_response(self, 200, update_draft(int(match.group(1)), payload.get("content", "")))
                return
            match = re.match(r"^/api/drafts/(\d+)/review$", path)
            if match:
                _json_response(self, 200, review_draft(int(match.group(1))))
                return
            match = re.match(r"^/api/drafts/(\d+)/versions/(\d+)/restore$", path)
            if match:
                _json_response(self, 200, restore_draft_version(int(match.group(1)), int(match.group(2))))
                return
            match = re.match(r"^/api/drafts/(\d+)/case-asset$", path)
            if match:
                _json_response(self, 200, create_case_asset_from_draft(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/case-assets/(\d+)$", path)
            if match:
                _json_response(self, 200, update_case_asset(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/deliveries/(\d+)$", path)
            if match:
                _json_response(self, 200, update_delivery_record(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/payments/(\d+)$", path)
            if match:
                _json_response(self, 200, update_payment_record(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/feedback/(\d+)$", path)
            if match:
                _json_response(self, 200, update_feedback_item(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/communications/(\d+)$", path)
            if match:
                _json_response(self, 200, update_communication(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/final-checks/(\d+)$", path)
            if match:
                _json_response(self, 200, update_final_check_item(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/revision-tasks/(\d+)$", path)
            if match:
                _json_response(self, 200, update_revision_task(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/materials/(\d+)$", path)
            if match:
                _json_response(self, 200, update_material_item(int(match.group(1)), payload))
                return
            match = re.match(r"^/api/tenders/(\d+)/export$", path)
            if match:
                tender_id = int(match.group(1))
                export_format = payload.get("format")
                if export_format in {"formal_docx", "docx", "client_package", "client_zip"}:
                    require_formal_export_ready(tender_id)
                if export_format in {"client_package", "client_zip"}:
                    result = export_client_package(tender_id)
                elif export_format in {"internal_package", "package", "zip"}:
                    result = export_package(tender_id)
                elif export_format in {"formal_docx", "docx"}:
                    result = export_client_docx(tender_id)
                elif export_format == "internal_docx":
                    result = export_docx(tender_id)
                else:
                    result = export_markdown(tender_id)
                result["download_url"] = "/exports/" + Path(result["path"]).name
                _json_response(self, 200, result)
                return
            _json_response(self, 404, {"error": "Not found"})
        except Exception as exc:  # noqa: BLE001
            _json_response(self, 500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_POST()

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            match = re.match(r"^/api/tenders/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_tender(int(match.group(1))))
                return
            match = re.match(r"^/api/section-plans/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_section_plan(int(match.group(1))))
                return
            match = re.match(r"^/api/materials/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_material_item(int(match.group(1))))
                return
            match = re.match(r"^/api/payments/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_payment_record(int(match.group(1))))
                return
            match = re.match(r"^/api/case-assets/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_case_asset(int(match.group(1))))
                return
            match = re.match(r"^/api/templates/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_section_template(int(match.group(1))))
                return
            match = re.match(r"^/api/document-templates/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_document_template(int(match.group(1))))
                return
            match = re.match(r"^/api/requirements/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_requirement(int(match.group(1))))
                return
            match = re.match(r"^/api/communications/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_communication(int(match.group(1))))
                return
            match = re.match(r"^/api/document-blocks/(\d+)$", parsed.path)
            if match:
                _json_response(self, 200, delete_document_block(int(match.group(1))))
                return
            _json_response(self, 404, {"error": "Not found"})
        except Exception as exc:  # noqa: BLE001
            _json_response(self, 500, {"error": f"{type(exc).__name__}: {exc}"})

    def _send_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = STATIC_DIR / "index.html"
        else:
            target = (STATIC_DIR / path.lstrip("/")).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                _json_response(self, 403, {"error": "Forbidden"})
                return
        self._send_file(target)

    def _send_file(self, target: Path) -> None:
        if not target.exists() or not target.is_file():
            _json_response(self, 404, {"error": "File not found"})
            return
        content = target.read_bytes()
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() in {".html", ".css", ".js"}:
            mime += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        _log(f"[server] {self.address_string()} {format % args}")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    conn = connect()
    init_db(conn)
    conn.close()
    server = ThreadingHTTPServer((host, port), BidWriterHandler)
    _log(f"Serving 标书生产工作台 at http://{host}:{port}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local bid writer workspace.")
    parser.add_argument("--host", default=os.environ.get("BID_WRITER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BID_WRITER_PORT", "8765")))
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
