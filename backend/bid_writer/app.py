from __future__ import annotations

from pathlib import Path
from typing import Any

from .bid_strategy import generate_bid_strategy, get_bid_strategy, update_bid_strategy
from .acceptance import build_acceptance_status, list_acceptance_runs, run_acceptance
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
from .document_templates import (
    delete_document_template,
    list_document_templates,
    save_document_template,
    update_document_template,
)
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
from .payments import create_payment_record, delete_payment_record, list_payment_records, payment_summary, update_payment_record
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
from .pricing import build_price_quote, ensure_default_pricing_rules, list_pricing_rules, list_quotation_records, update_pricing_rule
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
from .requirement_responses import (
    classify_tender_requirements,
    list_requirement_responses,
    rebuild_requirement_responses,
    update_requirement_response,
)
from .review import review_tender
from .retrospective import build_project_retrospective, build_retrospective_dashboard, update_project_retrospective
from .revision_tasks import list_revision_tasks, sync_revision_tasks, update_revision_task
from .section_templates import all_templates, delete_section_template, save_section_template, template_coverage_report, update_section_template
from .source_audit import build_source_audit
from .source_preview import preview_source
from .settings import STATIC_DIR, UPLOAD_DIR
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
from .visual_assets import (
    auto_validate_technical_visuals,
    batch_review_visual_assets,
    get_visual_asset,
    import_docx_images,
    import_image_file,
    list_visual_assets,
    resolve_asset_path,
    update_visual_asset_review,
    visual_review_summary,
)
from .visual_pipeline import build_visual_plan, generate_hybrid_visual, image_generation_settings

try:
    from fastapi import FastAPI, File, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except Exception as exc:  # pragma: no cover - handled by server_stdlib in dependency-light environments.
    raise RuntimeError("FastAPI dependencies are not installed. Use server_stdlib.py or install backend/requirements.txt.") from exc


class ImportRequest(BaseModel):
    reset: bool = False
    limit_documents: int | None = None


class WorkflowConfirmationRequest(BaseModel):
    confirmed: bool = True
    confirmed_by: str = "人工复核"
    notes: str = ""


class KbOcrRunRequest(BaseModel):
    reindex: bool = True


class SearchRequest(BaseModel):
    query: str
    category: str = ""
    project_type: str = ""
    heading: str = ""
    limit: int = 10


class SourcePreviewRequest(BaseModel):
    source_type: str = "kb_chunk"
    id: int | None = None
    chunk_id: int | None = None
    source_path: str = ""
    markdown_path: str = ""
    heading_text: str = ""


class TemplateRequest(BaseModel):
    name: str
    keywords: list[str] | str = []
    intent: str = ""
    outline: list[str] | str = []
    quality_points: list[str] | str = []
    industry: str = ""
    project_type: str = ""
    method_key: str = ""
    version: str = "1.0"
    review_status: str = "approved"
    generation_rules: dict[str, Any] = {}


class RequirementRequest(BaseModel):
    kind: str = "技术要求"
    content: str
    source_hint: str = ""
    priority: str = "normal"
    status: str = "pending"
    response_scope: str | None = None
    score_weight: float | None = None
    source_page: int | None = None
    section_path: str | None = None
    applicable: bool | None = None
    classification_source: str | None = None
    review_status: str | None = None
    review_notes: str | None = None


class RequirementUpdateRequest(BaseModel):
    kind: str | None = None
    content: str | None = None
    source_hint: str | None = None
    priority: str | None = None
    status: str | None = None
    response_scope: str | None = None
    score_weight: float | None = None
    source_page: int | None = None
    section_path: str | None = None
    applicable: bool | None = None
    classification_source: str | None = None
    review_status: str | None = None
    review_notes: str | None = None


class RequirementResponseUpdateRequest(BaseModel):
    response_status: str | None = None
    review_status: str | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None


class FinalCheckUpdateRequest(BaseModel):
    status: str | None = None
    owner: str | None = None
    notes: str | None = None


class ReplacementRequest(BaseModel):
    search_text: str
    replace_text: str = ""
    notes: str = ""


class TenderTextRequest(BaseModel):
    name: str
    text: str
    industry: str = ""
    region: str = ""


class TenderSourceUpdateRequest(BaseModel):
    text: str = ""
    name: str | None = None
    industry: str | None = None
    region: str | None = None
    mode: str = "replace"
    reset_plan: bool = True
    parse: bool = True


class GenerateRequest(BaseModel):
    tender_id: int
    section_title: str
    requirement_ids: list[int] = []
    category: str = ""


class DraftUpdateRequest(BaseModel):
    content: str


class ExportRequest(BaseModel):
    format: str = "markdown"


class GenerateAllRequest(BaseModel):
    regenerate: bool = False


class SectionPlanCreateRequest(BaseModel):
    section_title: str
    template_name: str = ""
    requirement_ids: list[int] = []
    order_no: int | None = None


class SectionPlanUpdateRequest(BaseModel):
    section_title: str | None = None
    order_no: int | None = None
    requirement_ids: list[int] | None = None
    status: str | None = None


class RevisionTaskUpdateRequest(BaseModel):
    status: str | None = None
    owner: str | None = None
    due_at: str | None = None
    notes: str | None = None


class ProjectProfileUpdateRequest(BaseModel):
    project_name: str | None = None
    industry: str | None = None
    region: str | None = None
    project_type: str | None = None
    structure_type: str | None = None
    building_area: str | None = None
    floor_info: str | None = None
    duration_days: int | None = None
    planned_start: str | None = None
    planned_finish: str | None = None
    quality_target: str | None = None
    safety_target: str | None = None
    green_target: str | None = None
    contract_scope: str | None = None
    site_conditions: str | None = None
    key_constraints: str | None = None
    special_requirements: str | None = None


class EnterpriseProfileUpdateRequest(BaseModel):
    profile_name: str | None = None
    bidder_name: str | None = None
    legal_representative: str | None = None
    contact: str | None = None
    qualification_summary: str | None = None
    capability_summary: str | None = None
    quality_system: str | None = None
    safety_system: str | None = None
    key_personnel: str | None = None
    equipment_resources: str | None = None
    similar_projects: str | None = None
    service_commitment: str | None = None
    notes: str | None = None
    is_default: bool | None = None


class ProductionTaskUpdateRequest(BaseModel):
    customer_name: str | None = None
    source_platform: str | None = None
    order_no: str | None = None
    contact: str | None = None
    deadline: str | None = None
    budget: str | None = None
    deliverable_format: str | None = None
    delivery_status: str | None = None
    delivery_notes: str | None = None
    internal_owner: str | None = None


class DocumentSettingsUpdateRequest(BaseModel):
    template_id: int | None = None
    document_title: str | None = None
    document_subtitle: str | None = None
    document_type: str | None = None
    bidder_name: str | None = None
    version_label: str | None = None
    prepared_by: str | None = None
    reviewed_by: str | None = None
    document_date: str | None = None
    confidentiality: str | None = None
    header_text: str | None = None
    footer_text: str | None = None
    body_font: str | None = None
    body_font_size: float | None = None
    heading_font: str | None = None
    include_cover: bool | None = None
    include_toc: bool | None = None
    include_response_matrix: bool | None = None
    include_delivery_review: bool | None = None
    section_page_break: bool | None = None
    notes: str | None = None


class DocumentBlocksGenerateRequest(BaseModel):
    regenerate: bool = True


class DocumentBlockRequest(BaseModel):
    draft_id: int | None = None
    section_title: str | None = None
    block_order: int | None = None
    block_type: str | None = None
    title: str | None = None
    caption: str | None = None
    data: dict[str, Any] | list[Any] | None = None
    asset_id: int | None = None
    source_path: str | None = None
    status: str | None = None


class VisualAssetImportRequest(BaseModel):
    source_path: str
    asset_type: str = "project_image"
    name: str = ""
    caption: str = ""
    industry: str = ""
    section_title: str = ""


class VisualHybridGenerateRequest(BaseModel):
    scene_key: str
    source_path: str = ""
    section_title: str = ""
    attach: bool = True


class VisualAssetReviewRequest(BaseModel):
    review_status: str
    review_notes: str = ""


class VisualAssetBatchReviewRequest(BaseModel):
    asset_ids: list[int] = []
    review_status: str
    review_notes: str = ""


class DocumentTemplateRequest(BaseModel):
    name: str
    source_docx_path: str = ""
    style_map: dict[str, Any] = {}
    cover_fields: dict[str, Any] = {}
    version: str = "1.0"
    status: str = "active"
    is_default: bool = False


class AcceptanceRunRequest(BaseModel):
    manual_edit_hours: float | None = None
    conclusion: str = ""
    exports: dict[str, Any] = {}


class BidStrategyUpdateRequest(BaseModel):
    positioning: str | None = None
    win_themes: str | None = None
    key_constraints: str | None = None
    risk_controls: str | None = None
    response_priorities: str | None = None
    writing_tone: str | None = None
    section_focus_json: str | list[dict[str, Any]] | None = None
    reference_keywords: str | None = None
    forbidden_terms: str | None = None
    status: str | None = None
    notes: str | None = None


class FinalDocumentUpdateRequest(BaseModel):
    status: str | None = None
    approved_by: str | None = None
    notes: str | None = None
    checklist_json: str | list[dict[str, Any]] | None = None


class MaterialItemCreateRequest(BaseModel):
    category: str | None = None
    name: str
    status: str | None = None
    required: bool | None = True
    source: str | None = None
    notes: str | None = None
    owner: str | None = None
    due_at: str | None = None


class MaterialItemUpdateRequest(BaseModel):
    category: str | None = None
    name: str | None = None
    status: str | None = None
    required: bool | None = None
    source: str | None = None
    notes: str | None = None
    owner: str | None = None
    due_at: str | None = None


class DeliveryRecordUpdateRequest(BaseModel):
    delivery_channel: str | None = None
    recipient: str | None = None
    status: str | None = None
    notes: str | None = None
    delivered_at: str | None = None


class FeedbackCreateRequest(BaseModel):
    delivery_record_id: int | None = None
    customer_name: str | None = None
    source_channel: str | None = None
    feedback_text: str
    related_section: str | None = None
    priority: str | None = None
    status: str | None = None
    action_plan: str | None = None
    owner: str | None = None


class FeedbackUpdateRequest(BaseModel):
    delivery_record_id: int | None = None
    customer_name: str | None = None
    source_channel: str | None = None
    feedback_text: str | None = None
    related_section: str | None = None
    priority: str | None = None
    status: str | None = None
    action_plan: str | None = None
    owner: str | None = None


class FeedbackReworkRequest(BaseModel):
    owner: str | None = None
    overwrite_action_plan: bool = False
    generate_missing_drafts: bool = True
    extra_note: str | None = None


class IntakeAssistantRequest(BaseModel):
    customer_message: str | None = None
    source_platform: str | None = None
    deadline: str | None = None
    budget_expectation: str | None = None
    deliverable_format: str | None = None
    rush_level: str | None = None
    notes: str | None = None


class ProductionPipelineRequest(BaseModel):
    force_parse: bool = False
    rebuild_plan: bool = False
    regenerate: bool = False
    export_package: bool = True


class ClientDeliveryPreparationRequest(BaseModel):
    force_parse: bool = False
    rebuild_plan: bool = False
    regenerate: bool = False
    export_internal_package: bool = True
    extra_note: str | None = None


class OrderConfirmationRequest(BaseModel):
    agreed_price: str | None = None
    deadline: str | None = None
    revision_rounds: str | None = None
    deliverables: str | None = None
    exclusions: str | None = None


class ClosureConfirmationRequest(BaseModel):
    reply_deadline: str | None = None
    extra_note: str | None = None
    status: str | None = None
    confirmed_by: str | None = None
    confirmation_note: str | None = None
    customer_message: str | None = None


class ClientDeliveryConfirmationRequest(BaseModel):
    delivery_channel: str | None = None
    recipient: str | None = None
    confirmation_note: str | None = None
    customer_message: str | None = None
    extra_note: str | None = None


class ProjectRetrospectiveRequest(BaseModel):
    status: str | None = None
    actual_price: str | None = None
    actual_cost: str | None = None
    work_hours: float | None = None
    revision_count: int | None = None
    satisfaction: str | None = None
    risk_level: str | None = None
    reusable_score: int | None = None
    industry_tags: str | None = None
    reusable_assets: str | None = None
    lessons: str | None = None
    next_action: str | None = None


class PricingRuleUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    value_type: str | None = None
    value: str | None = None
    unit: str | None = None
    enabled: bool | None = None
    description: str | None = None


class PriceQuoteRequest(BaseModel):
    customer_message: str | None = None
    source_platform: str | None = None
    save_record: bool = False


class PaymentRecordRequest(BaseModel):
    amount: float | str | None = None
    currency: str | None = None
    payment_stage: str | None = None
    payment_method: str | None = None
    status: str | None = None
    received_at: str | None = None
    proof: str | None = None
    notes: str | None = None


class CaseAssetRequest(BaseModel):
    project_name: str | None = None
    industry: str | None = None
    section_title: str | None = None
    tags: str | None = None
    content: str | None = None
    summary: str | None = None
    reusable_score: int | None = None
    source_status: str | None = None


class IntakeCreateTenderRequest(BaseModel):
    customer_message: str
    customer_name: str | None = None
    source_platform: str | None = None
    contact: str | None = None
    deadline: str | None = None
    budget_expectation: str | None = None
    deliverable_format: str | None = None
    rush_level: str | None = None
    project_name: str | None = None
    industry: str | None = None
    region: str | None = None
    internal_owner: str | None = None


class CommunicationRequest(BaseModel):
    stage: str | None = None
    direction: str | None = None
    channel: str | None = None
    customer_message: str | None = None
    system_reply: str | None = None
    status: str | None = None
    notes: str | None = None


app = FastAPI(title="技术标智能编制系统", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    conn = connect()
    init_db(conn)
    conn.close()


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    conn = connect()
    try:
        return stats(conn)
    finally:
        conn.close()


@app.get("/api/kb/audit")
def api_kb_audit(limit: int = 160) -> dict[str, Any]:
    return build_kb_audit(limit_directories=limit)


@app.get("/api/kb/ocr-queue")
def api_kb_ocr_queue(limit: int = 80) -> dict[str, Any]:
    return build_kb_ocr_queue(limit=limit)


@app.post("/api/kb/ocr-queue/{item_id}/run")
def api_run_kb_ocr_item(item_id: str, payload: KbOcrRunRequest) -> dict[str, Any]:
    return run_kb_ocr_item(item_id, reindex=payload.reindex)


@app.get("/api/llm/status")
def api_llm_status() -> dict[str, Any]:
    return llm_settings()


@app.post("/api/llm/probe")
def api_llm_probe() -> dict[str, Any]:
    return probe_llm()


@app.get("/api/enterprise-profile")
def api_enterprise_profile() -> dict[str, Any]:
    return get_enterprise_profile()


@app.patch("/api/enterprise-profile")
def api_update_enterprise_profile(payload: EnterpriseProfileUpdateRequest) -> dict[str, Any]:
    return update_enterprise_profile(payload.dict(exclude_unset=True))


@app.get("/api/templates")
def api_templates() -> list[dict[str, Any]]:
    return all_templates()


@app.get("/api/templates/coverage")
def api_template_coverage() -> dict[str, Any]:
    return template_coverage_report()


@app.get("/api/template-assets")
def api_template_assets() -> dict[str, Any]:
    return template_asset_catalog()


@app.get("/api/benchmarks")
def api_benchmarks() -> dict[str, Any]:
    return build_benchmark_dataset()


@app.post("/api/templates")
def api_save_template(payload: TemplateRequest) -> dict[str, Any]:
    return save_section_template(payload.dict())


@app.patch("/api/templates/{template_id}")
def api_update_template(template_id: int, payload: TemplateRequest) -> dict[str, Any]:
    return update_section_template(template_id, payload.dict())


@app.delete("/api/templates/{template_id}")
def api_delete_template(template_id: int) -> dict[str, Any]:
    return delete_section_template(template_id)


@app.get("/api/document-templates")
def api_document_templates() -> list[dict[str, Any]]:
    return list_document_templates()


@app.post("/api/document-templates")
def api_save_document_template(payload: DocumentTemplateRequest) -> dict[str, Any]:
    return save_document_template(payload.dict())


@app.post("/api/document-templates/upload")
async def api_upload_document_template(
    file: UploadFile = File(...),
    name: str = "",
    version: str = "1.0",
    is_default: bool = False,
) -> dict[str, Any]:
    filename = file.filename or "enterprise_template.docx"
    if Path(filename).suffix.lower() != ".docx":
        raise ValueError("企业文档模板必须是 DOCX 文件。")
    target = UPLOAD_DIR / filename
    target.write_bytes(await file.read())
    return save_document_template(
        {
            "name": name or Path(filename).stem,
            "source_docx_path": str(target),
            "version": version,
            "is_default": is_default,
        }
    )


@app.patch("/api/document-templates/{template_id}")
def api_update_document_template(template_id: int, payload: DocumentTemplateRequest) -> dict[str, Any]:
    return update_document_template(template_id, payload.dict(exclude_unset=True))


@app.delete("/api/document-templates/{template_id}")
def api_delete_document_template(template_id: int) -> dict[str, Any]:
    return delete_document_template(template_id)


@app.get("/api/orders/dashboard")
def api_order_dashboard() -> dict[str, Any]:
    return build_order_dashboard()


@app.get("/api/retrospectives/dashboard")
def api_retrospective_dashboard() -> dict[str, Any]:
    return build_retrospective_dashboard()


@app.get("/api/pricing/rules")
def api_pricing_rules() -> list[dict[str, Any]]:
    return ensure_default_pricing_rules()


@app.patch("/api/pricing/rules/{rule_id}")
def api_update_pricing_rule(rule_id: int, payload: PricingRuleUpdateRequest) -> dict[str, Any]:
    return update_pricing_rule(rule_id, payload.dict(exclude_unset=True))


@app.post("/api/orders/sync-status")
def api_sync_all_status() -> dict[str, Any]:
    return sync_all_production_status()


@app.post("/api/kb/import")
def api_import_kb(payload: ImportRequest) -> dict[str, int]:
    return import_knowledge_base(reset=payload.reset, limit_documents=payload.limit_documents)


@app.post("/api/sections/search")
def api_search(payload: SearchRequest) -> list[dict[str, Any]]:
    return search_chunks(
        query=payload.query,
        category=payload.category,
        project_type=payload.project_type,
        heading=payload.heading,
        limit=payload.limit,
    )


@app.post("/api/sources/preview")
def api_source_preview(payload: SourcePreviewRequest) -> dict[str, Any]:
    return preview_source(payload.dict(exclude_none=True))


@app.get("/api/tenders")
def api_tenders() -> list[dict[str, Any]]:
    return list_tenders()


@app.get("/api/tenders/{tender_id}")
def api_tender(tender_id: int) -> dict[str, Any]:
    return get_tender(tender_id)


@app.get("/api/document-processing")
def api_document_processing() -> list[dict[str, Any]]:
    return list_document_processing_records()


@app.get("/api/tenders/{tender_id}/document-processing")
def api_tender_document_processing(tender_id: int) -> list[dict[str, Any]]:
    return list_document_processing_records(tender_id)


@app.delete("/api/tenders/{tender_id}")
def api_delete_tender(tender_id: int) -> dict[str, Any]:
    return delete_tender(tender_id)


@app.post("/api/tenders/import")
def api_import_tender(payload: TenderTextRequest) -> dict[str, Any]:
    return create_tender(payload.name, text=payload.text, industry=payload.industry, region=payload.region)


@app.post("/api/intake/create-tender")
def api_create_intake_tender(payload: IntakeCreateTenderRequest) -> dict[str, Any]:
    return create_intake_tender(payload.dict(exclude_unset=True))


@app.post("/api/tenders/upload")
async def api_upload_tender(file: UploadFile = File(...), industry: str = "", region: str = "") -> dict[str, Any]:
    target = UPLOAD_DIR / Path(file.filename or "tender").name
    target.write_bytes(await file.read())
    return create_tender(Path(target).stem, file_path=str(target), industry=industry, region=region)


@app.post("/api/tenders/{tender_id}/source")
def api_update_tender_source(tender_id: int, payload: TenderSourceUpdateRequest) -> dict[str, Any]:
    return update_tender_source(
        tender_id,
        text=payload.text,
        name=payload.name or "",
        industry=payload.industry,
        region=payload.region,
        mode=payload.mode,
        reset_plan=payload.reset_plan,
        parse=payload.parse,
    )


@app.post("/api/tenders/{tender_id}/source/upload")
async def api_upload_tender_source(tender_id: int, file: UploadFile = File(...), industry: str = "", region: str = "") -> dict[str, Any]:
    target = UPLOAD_DIR / Path(file.filename or "tender").name
    target.write_bytes(await file.read())
    return update_tender_source(
        tender_id,
        file_path=str(target),
        name=Path(target).stem,
        industry=industry or None,
        region=region or None,
    )


@app.post("/api/tenders/{tender_id}/parse")
def api_parse_tender(tender_id: int) -> dict[str, Any]:
    return parse_tender(tender_id)


@app.get("/api/tenders/{tender_id}/requirements")
def api_requirements(tender_id: int) -> list[dict[str, Any]]:
    return get_requirements(tender_id)


@app.post("/api/tenders/{tender_id}/requirements")
def api_create_requirement(tender_id: int, payload: RequirementRequest) -> dict[str, Any]:
    return create_requirement(tender_id, payload.dict())


@app.patch("/api/requirements/{requirement_id}")
def api_update_requirement(requirement_id: int, payload: RequirementUpdateRequest) -> dict[str, Any]:
    return update_requirement(requirement_id, payload.dict(exclude_unset=True))


@app.delete("/api/requirements/{requirement_id}")
def api_delete_requirement(requirement_id: int) -> dict[str, Any]:
    return delete_requirement(requirement_id)


@app.post("/api/tenders/{tender_id}/requirements/reclassify")
def api_reclassify_requirements(tender_id: int) -> dict[str, Any]:
    classification = classify_tender_requirements(tender_id)
    evidence = rebuild_requirement_responses(tender_id)
    return {"classification": classification, "evidence": evidence}


@app.get("/api/tenders/{tender_id}/requirement-responses")
def api_requirement_responses(tender_id: int) -> list[dict[str, Any]]:
    rebuild_requirement_responses(tender_id)
    return list_requirement_responses(tender_id)


@app.patch("/api/requirement-responses/{response_id}")
def api_update_requirement_response(response_id: int, payload: RequirementResponseUpdateRequest) -> dict[str, Any]:
    return update_requirement_response(response_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/profile")
def api_get_profile(tender_id: int) -> dict[str, Any]:
    return get_project_profile(tender_id)


@app.patch("/api/tenders/{tender_id}/profile")
def api_update_profile(tender_id: int, payload: ProjectProfileUpdateRequest) -> dict[str, Any]:
    return update_project_profile(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/task")
def api_get_task(tender_id: int) -> dict[str, Any]:
    return get_production_task(tender_id)


@app.patch("/api/tenders/{tender_id}/task")
def api_update_task(tender_id: int, payload: ProductionTaskUpdateRequest) -> dict[str, Any]:
    return update_production_task(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/task/sync-status")
def api_sync_task_status(tender_id: int) -> dict[str, Any]:
    return sync_production_status(tender_id)


@app.get("/api/tenders/{tender_id}/document-settings")
def api_get_document_settings(tender_id: int) -> dict[str, Any]:
    return get_document_settings(tender_id)


@app.patch("/api/tenders/{tender_id}/document-settings")
def api_update_document_settings(tender_id: int, payload: DocumentSettingsUpdateRequest) -> dict[str, Any]:
    return update_document_settings(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/document-blocks")
def api_document_blocks(tender_id: int) -> list[dict[str, Any]]:
    return list_document_blocks(tender_id)


@app.post("/api/tenders/{tender_id}/document-blocks")
def api_create_document_block(tender_id: int, payload: DocumentBlockRequest) -> dict[str, Any]:
    return create_document_block(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/document-blocks/generate")
def api_generate_document_blocks(tender_id: int, payload: DocumentBlocksGenerateRequest) -> dict[str, Any]:
    return generate_document_blocks(tender_id, regenerate=payload.regenerate)


@app.patch("/api/document-blocks/{block_id}")
def api_update_document_block(block_id: int, payload: DocumentBlockRequest) -> dict[str, Any]:
    return update_document_block(block_id, payload.dict(exclude_unset=True))


@app.delete("/api/document-blocks/{block_id}")
def api_delete_document_block(block_id: int) -> dict[str, Any]:
    return delete_document_block(block_id)


@app.get("/api/tenders/{tender_id}/visual-assets")
def api_visual_assets(tender_id: int) -> list[dict[str, Any]]:
    return list_visual_assets(tender_id)


@app.get("/api/tenders/{tender_id}/visual-plan")
def api_visual_plan(tender_id: int) -> dict[str, Any]:
    return build_visual_plan(tender_id)


@app.get("/api/image-generation/settings")
def api_image_generation_settings() -> dict[str, Any]:
    return image_generation_settings()


@app.get("/api/visual-assets/{asset_id}/file")
def api_visual_asset_file(asset_id: int) -> FileResponse:
    asset = get_visual_asset(asset_id)
    return FileResponse(resolve_asset_path(str(asset.get("file_path") or "")))


@app.post("/api/tenders/{tender_id}/visual-assets/import")
def api_import_visual_asset(tender_id: int, payload: VisualAssetImportRequest) -> dict[str, Any]:
    if Path(payload.source_path).suffix.lower() == ".docx":
        return import_docx_images(
            payload.source_path,
            tender_id=tender_id,
            industry=payload.industry,
            section_title=payload.section_title,
        )
    return import_image_file(
        payload.source_path,
        tender_id=tender_id,
        asset_type=payload.asset_type,
        name=payload.name,
        caption=payload.caption,
        industry=payload.industry,
        section_title=payload.section_title,
    )


@app.post("/api/tenders/{tender_id}/visual-assets/generate-hybrid")
def api_generate_hybrid_visual(tender_id: int, payload: VisualHybridGenerateRequest) -> dict[str, Any]:
    return generate_hybrid_visual(
        tender_id,
        scene_key=payload.scene_key,
        source_path=payload.source_path,
        section_title=payload.section_title,
        attach=payload.attach,
    )


@app.patch("/api/visual-assets/{asset_id}/review")
def api_review_visual_asset(asset_id: int, payload: VisualAssetReviewRequest) -> dict[str, Any]:
    return update_visual_asset_review(
        asset_id,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )


@app.get("/api/tenders/{tender_id}/visual-review")
def api_visual_review(tender_id: int) -> dict[str, Any]:
    return visual_review_summary(tender_id)


@app.post("/api/tenders/{tender_id}/visual-assets/review-batch")
def api_batch_review_visual_assets(tender_id: int, payload: VisualAssetBatchReviewRequest) -> dict[str, Any]:
    return batch_review_visual_assets(
        tender_id,
        payload.asset_ids,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )


@app.post("/api/tenders/{tender_id}/visual-assets/auto-validate")
def api_auto_validate_visual_assets(tender_id: int) -> dict[str, Any]:
    return auto_validate_technical_visuals(tender_id)


@app.get("/api/tenders/{tender_id}/bid-strategy")
def api_get_bid_strategy(tender_id: int) -> dict[str, Any]:
    return get_bid_strategy(tender_id)


@app.post("/api/tenders/{tender_id}/bid-strategy/generate")
def api_generate_bid_strategy(tender_id: int) -> dict[str, Any]:
    return generate_bid_strategy(tender_id)


@app.patch("/api/tenders/{tender_id}/bid-strategy")
def api_update_bid_strategy(tender_id: int, payload: BidStrategyUpdateRequest) -> dict[str, Any]:
    return update_bid_strategy(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/final-document")
def api_get_final_document(tender_id: int) -> dict[str, Any]:
    return build_final_document(tender_id)


@app.patch("/api/tenders/{tender_id}/final-document")
def api_update_final_document(tender_id: int, payload: FinalDocumentUpdateRequest) -> dict[str, Any]:
    return update_final_document(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/materials")
def api_material_items(tender_id: int) -> list[dict[str, Any]]:
    return list_material_items(tender_id)


@app.post("/api/tenders/{tender_id}/materials")
def api_create_material_item(tender_id: int, payload: MaterialItemCreateRequest) -> dict[str, Any]:
    return create_material_item(tender_id, payload.dict(exclude_unset=True))


@app.patch("/api/materials/{item_id}")
def api_update_material_item(item_id: int, payload: MaterialItemUpdateRequest) -> dict[str, Any]:
    return update_material_item(item_id, payload.dict(exclude_unset=True))


@app.delete("/api/materials/{item_id}")
def api_delete_material_item(item_id: int) -> dict[str, Any]:
    return delete_material_item(item_id)


@app.get("/api/tenders/{tender_id}/intake-assistant")
def api_get_intake_assistant(tender_id: int) -> dict[str, Any]:
    return build_intake_assistant(tender_id)


@app.get("/api/tenders/{tender_id}/order-confirmation")
def api_get_order_confirmation(tender_id: int) -> dict[str, Any]:
    return build_order_confirmation(tender_id)


@app.post("/api/tenders/{tender_id}/order-confirmation")
def api_build_order_confirmation(tender_id: int, payload: OrderConfirmationRequest) -> dict[str, Any]:
    return build_order_confirmation(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/intake-assistant")
def api_build_intake_assistant(tender_id: int, payload: IntakeAssistantRequest) -> dict[str, Any]:
    return build_intake_assistant(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/communications")
def api_get_communications(tender_id: int) -> list[dict[str, Any]]:
    return list_communications(tender_id)


@app.post("/api/tenders/{tender_id}/communications/suggest")
def api_suggest_communication(tender_id: int, payload: CommunicationRequest) -> dict[str, Any]:
    return suggest_communication_reply(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/communications")
def api_create_communication(tender_id: int, payload: CommunicationRequest) -> dict[str, Any]:
    return create_communication(tender_id, payload.dict(exclude_unset=True))


@app.patch("/api/communications/{communication_id}")
def api_update_communication(communication_id: int, payload: CommunicationRequest) -> dict[str, Any]:
    return update_communication(communication_id, payload.dict(exclude_unset=True))


@app.delete("/api/communications/{communication_id}")
def api_delete_communication(communication_id: int) -> dict[str, Any]:
    return delete_communication(communication_id)


@app.get("/api/tenders/{tender_id}/workflow")
def api_workflow(tender_id: int) -> dict[str, Any]:
    return build_workflow_status(tender_id)


@app.get("/api/tenders/{tender_id}/workflow-confirmations")
def api_workflow_confirmations(tender_id: int) -> dict[str, Any]:
    return list_workflow_confirmations(tender_id)


@app.patch("/api/tenders/{tender_id}/workflow-confirmations/{stage_key}")
def api_set_workflow_confirmation(
    tender_id: int,
    stage_key: str,
    payload: WorkflowConfirmationRequest,
) -> dict[str, Any]:
    return set_workflow_confirmation(tender_id, stage_key, payload.dict())


@app.get("/api/tenders/{tender_id}/command-center")
def api_command_center(tender_id: int) -> dict[str, Any]:
    return build_command_center(tender_id)


@app.get("/api/tenders/{tender_id}/production-starter")
def api_production_starter(tender_id: int) -> dict[str, Any]:
    return build_production_starter(tender_id)


@app.get("/api/tenders/{tender_id}/order-wizard")
def api_order_wizard(tender_id: int) -> dict[str, Any]:
    return build_order_wizard(tender_id)


@app.get("/api/tenders/{tender_id}/channel-ops")
def api_channel_ops(tender_id: int) -> dict[str, Any]:
    return build_channel_ops(tender_id)


@app.get("/api/tenders/{tender_id}/overview")
def api_project_overview(tender_id: int) -> dict[str, Any]:
    return build_project_overview(tender_id)


@app.get("/api/tenders/{tender_id}/timeline")
def api_project_timeline(tender_id: int) -> dict[str, Any]:
    return build_project_timeline(tender_id)


@app.post("/api/tenders/{tender_id}/production/run")
def api_run_production(tender_id: int, payload: ProductionPipelineRequest) -> dict[str, Any]:
    return run_production_pipeline(tender_id, payload.dict())


@app.post("/api/tenders/{tender_id}/client-delivery/prepare")
def api_prepare_client_delivery(tender_id: int, payload: ClientDeliveryPreparationRequest) -> dict[str, Any]:
    return prepare_client_delivery(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/plan")
def api_build_plan(tender_id: int) -> list[dict[str, Any]]:
    return build_section_plan(tender_id)


@app.get("/api/tenders/{tender_id}/plan")
def api_plan(tender_id: int) -> list[dict[str, Any]]:
    return list_section_plans(tender_id)


@app.get("/api/tenders/{tender_id}/plan/audit")
def api_plan_audit(tender_id: int) -> dict[str, Any]:
    return audit_section_plan(tender_id)


@app.post("/api/tenders/{tender_id}/plan/repair")
def api_plan_repair(tender_id: int) -> dict[str, Any]:
    return repair_section_plan(tender_id)


@app.post("/api/tenders/{tender_id}/plan/sections")
def api_add_plan_section(tender_id: int, payload: SectionPlanCreateRequest) -> dict[str, Any]:
    return add_section_plan(
        tender_id=tender_id,
        section_title=payload.section_title,
        template_name=payload.template_name,
        requirement_ids=payload.requirement_ids,
        order_no=payload.order_no,
    )


@app.post("/api/tenders/{tender_id}/plan/generate-all")
def api_generate_all_plan(tender_id: int, payload: GenerateAllRequest) -> dict[str, Any]:
    return generate_all_from_plan(tender_id, regenerate=payload.regenerate)


@app.get("/api/tenders/{tender_id}/coverage")
def api_coverage(tender_id: int) -> dict[str, Any]:
    return build_coverage_report(tender_id)


@app.get("/api/tenders/{tender_id}/response-matrix")
def api_response_matrix(tender_id: int) -> dict[str, Any]:
    return build_response_matrix(tender_id)


@app.post("/api/tenders/{tender_id}/response-matrix/auto-link")
def api_response_matrix_auto_link(tender_id: int) -> dict[str, Any]:
    return auto_link_response_matrix(tender_id)


@app.post("/api/tenders/{tender_id}/response-matrix/realign")
def api_response_matrix_realign(tender_id: int) -> dict[str, Any]:
    return realign_response_matrix(tender_id)


@app.get("/api/tenders/{tender_id}/source-audit")
def api_source_audit(tender_id: int) -> dict[str, Any]:
    return build_source_audit(tender_id)


@app.get("/api/tenders/{tender_id}/delivery-review")
def api_delivery_review(tender_id: int) -> dict[str, Any]:
    return build_delivery_review(tender_id)


@app.get("/api/tenders/{tender_id}/delivery-release")
def api_delivery_release(tender_id: int) -> dict[str, Any]:
    return build_delivery_release(tender_id)


@app.get("/api/tenders/{tender_id}/production-readiness")
def api_production_readiness(tender_id: int) -> dict[str, Any]:
    return build_production_readiness(tender_id)


@app.get("/api/tenders/{tender_id}/package-validation")
def api_package_validation(tender_id: int) -> dict[str, Any]:
    return validate_latest_package(tender_id)


@app.get("/api/tenders/{tender_id}/client-package-validation")
def api_client_package_validation(tender_id: int) -> dict[str, Any]:
    return validate_latest_client_package(tender_id)


@app.get("/api/tenders/{tender_id}/client-delivery-confirmation")
def api_get_client_delivery_confirmation(tender_id: int) -> dict[str, Any]:
    return build_client_delivery_confirmation(tender_id)


@app.post("/api/tenders/{tender_id}/client-delivery-confirmation")
def api_confirm_client_delivery(tender_id: int, payload: ClientDeliveryConfirmationRequest) -> dict[str, Any]:
    return confirm_client_delivery(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/final-checklist")
def api_final_checklist(tender_id: int) -> dict[str, Any]:
    return build_final_checklist(tender_id)


@app.patch("/api/final-checks/{item_id}")
def api_update_final_check(item_id: int, payload: FinalCheckUpdateRequest) -> dict[str, Any]:
    return update_final_check_item(item_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/quality-gate")
def api_quality_gate(tender_id: int) -> dict[str, Any]:
    return build_quality_gate(tender_id)


@app.get("/api/tenders/{tender_id}/acceptance")
def api_acceptance(tender_id: int) -> dict[str, Any]:
    return {"current": build_acceptance_status(tender_id), "runs": list_acceptance_runs(tender_id)}


@app.post("/api/tenders/{tender_id}/acceptance/run")
def api_run_acceptance(tender_id: int, payload: AcceptanceRunRequest) -> dict[str, Any]:
    return run_acceptance(
        tender_id,
        manual_edit_hours=payload.manual_edit_hours,
        conclusion=payload.conclusion,
        exports=payload.exports,
    )


@app.post("/api/tenders/{tender_id}/docx-preflight")
def api_docx_preflight(tender_id: int) -> dict[str, Any]:
    exported = export_docx(tender_id)
    visual = run_docx_visual_qa(tender_id, exported["path"])
    return {**exported, "layout_audit": visual}


@app.get("/api/tenders/{tender_id}/revision-tasks")
def api_revision_tasks(tender_id: int) -> dict[str, Any]:
    return list_revision_tasks(tender_id)


@app.post("/api/tenders/{tender_id}/revision-tasks/sync")
def api_sync_revision_tasks(tender_id: int) -> dict[str, Any]:
    return sync_revision_tasks(tender_id)


@app.patch("/api/revision-tasks/{task_id}")
def api_update_revision_task(task_id: int, payload: RevisionTaskUpdateRequest) -> dict[str, Any]:
    return update_revision_task(task_id, payload.dict(exclude_none=True))


@app.get("/api/tenders/{tender_id}/delivery-assistant")
def api_delivery_assistant(tender_id: int) -> dict[str, Any]:
    return build_delivery_assistant(tender_id)


@app.get("/api/tenders/{tender_id}/deliveries")
def api_delivery_records(tender_id: int) -> list[dict[str, Any]]:
    return list_delivery_records(tender_id)


@app.patch("/api/deliveries/{record_id}")
def api_update_delivery(record_id: int, payload: DeliveryRecordUpdateRequest) -> dict[str, Any]:
    return update_delivery_record(record_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/feedback")
def api_feedback_items(tender_id: int) -> list[dict[str, Any]]:
    return list_feedback_items(tender_id)


@app.get("/api/tenders/{tender_id}/feedback-rework")
def api_feedback_rework(tender_id: int) -> dict[str, Any]:
    return build_feedback_rework(tender_id)


@app.post("/api/tenders/{tender_id}/feedback-rework")
def api_apply_feedback_rework(tender_id: int, payload: FeedbackReworkRequest) -> dict[str, Any]:
    return apply_feedback_rework_plan(tender_id, payload.dict(exclude_unset=True))


@app.post("/api/tenders/{tender_id}/feedback-rework/execute")
def api_execute_feedback_rework(tender_id: int, payload: FeedbackReworkRequest) -> dict[str, Any]:
    return execute_feedback_rework(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/closure-confirmation")
def api_get_closure_confirmation(tender_id: int) -> dict[str, Any]:
    return build_closure_confirmation(tender_id)


@app.post("/api/tenders/{tender_id}/closure-confirmation")
def api_build_closure_confirmation(tender_id: int, payload: ClosureConfirmationRequest) -> dict[str, Any]:
    return build_closure_confirmation(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/closures")
def api_closure_records(tender_id: int) -> list[dict[str, Any]]:
    return list_closure_records(tender_id)


@app.post("/api/tenders/{tender_id}/closures")
def api_record_closure(tender_id: int, payload: ClosureConfirmationRequest) -> dict[str, Any]:
    return record_closure_confirmation(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/retrospective")
def api_project_retrospective(tender_id: int) -> dict[str, Any]:
    return build_project_retrospective(tender_id)


@app.patch("/api/tenders/{tender_id}/retrospective")
def api_update_project_retrospective(tender_id: int, payload: ProjectRetrospectiveRequest) -> dict[str, Any]:
    return update_project_retrospective(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/price-quote")
def api_price_quote(tender_id: int) -> dict[str, Any]:
    return build_price_quote(tender_id)


@app.post("/api/tenders/{tender_id}/price-quote")
def api_build_price_quote(tender_id: int, payload: PriceQuoteRequest) -> dict[str, Any]:
    return build_price_quote(tender_id, payload.dict(exclude_unset=True), save_record=payload.save_record)


@app.get("/api/tenders/{tender_id}/quotations")
def api_quotation_records(tender_id: int) -> list[dict[str, Any]]:
    return list_quotation_records(tender_id)


@app.get("/api/tenders/{tender_id}/payments")
def api_payment_records(tender_id: int) -> dict[str, Any]:
    return payment_summary(tender_id)


@app.post("/api/tenders/{tender_id}/payments")
def api_create_payment(tender_id: int, payload: PaymentRecordRequest) -> dict[str, Any]:
    return create_payment_record(tender_id, payload.dict(exclude_unset=True))


@app.patch("/api/payments/{payment_id}")
def api_update_payment(payment_id: int, payload: PaymentRecordRequest) -> dict[str, Any]:
    return update_payment_record(payment_id, payload.dict(exclude_unset=True))


@app.delete("/api/payments/{payment_id}")
def api_delete_payment(payment_id: int) -> dict[str, Any]:
    return delete_payment_record(payment_id)


@app.get("/api/tenders/{tender_id}/case-assets")
def api_tender_case_assets(tender_id: int) -> list[dict[str, Any]]:
    return list_case_assets(tender_id=tender_id)


@app.get("/api/tenders/{tender_id}/polish")
def api_polish_scan(tender_id: int) -> dict[str, Any]:
    return scan_project_polish(tender_id)


@app.get("/api/tenders/{tender_id}/replacements")
def api_replacement_records(tender_id: int) -> list[dict[str, Any]]:
    return list_replacement_records(tender_id)


@app.post("/api/tenders/{tender_id}/replacements/preview")
def api_preview_replacement(tender_id: int, payload: ReplacementRequest) -> dict[str, Any]:
    return preview_replacement(tender_id, payload.search_text, payload.replace_text)


@app.post("/api/tenders/{tender_id}/replacements/apply")
def api_apply_replacement(tender_id: int, payload: ReplacementRequest) -> dict[str, Any]:
    return apply_replacement(tender_id, payload.search_text, payload.replace_text, payload.notes)


@app.post("/api/tenders/{tender_id}/case-assets")
def api_create_tender_case_assets(tender_id: int, payload: CaseAssetRequest) -> dict[str, Any]:
    return create_case_assets_from_tender(tender_id, payload.dict(exclude_unset=True))


@app.get("/api/case-assets")
def api_case_assets() -> list[dict[str, Any]]:
    return list_case_assets()


@app.patch("/api/case-assets/{asset_id}")
def api_update_case_asset(asset_id: int, payload: CaseAssetRequest) -> dict[str, Any]:
    return update_case_asset(asset_id, payload.dict(exclude_unset=True))


@app.delete("/api/case-assets/{asset_id}")
def api_delete_case_asset(asset_id: int) -> dict[str, Any]:
    return delete_case_asset(asset_id)


@app.post("/api/tenders/{tender_id}/feedback")
def api_create_feedback(tender_id: int, payload: FeedbackCreateRequest) -> dict[str, Any]:
    return create_feedback_item(tender_id, payload.dict(exclude_unset=True))


@app.patch("/api/feedback/{item_id}")
def api_update_feedback(item_id: int, payload: FeedbackUpdateRequest) -> dict[str, Any]:
    return update_feedback_item(item_id, payload.dict(exclude_unset=True))


@app.get("/api/tenders/{tender_id}/drafts")
def api_drafts(tender_id: int) -> list[dict[str, Any]]:
    return list_drafts(tender_id)


@app.get("/api/drafts/{draft_id}")
def api_draft(draft_id: int) -> dict[str, Any]:
    return get_draft(draft_id)


@app.post("/api/drafts/{draft_id}/case-asset")
def api_create_draft_case_asset(draft_id: int, payload: CaseAssetRequest) -> dict[str, Any]:
    return create_case_asset_from_draft(draft_id, payload.dict(exclude_unset=True))


@app.get("/api/drafts/{draft_id}/versions")
def api_draft_versions(draft_id: int) -> list[dict[str, Any]]:
    return list_draft_versions(draft_id)


@app.post("/api/drafts/{draft_id}/versions/{version_id}/restore")
def api_restore_draft_version(draft_id: int, version_id: int) -> dict[str, Any]:
    return restore_draft_version(draft_id, version_id)


@app.post("/api/drafts/generate")
def api_generate(payload: GenerateRequest) -> dict[str, Any]:
    return generate_draft(
        tender_id=payload.tender_id,
        section_title=payload.section_title,
        requirement_ids=payload.requirement_ids,
        category=payload.category,
    )


@app.post("/api/section-plans/{plan_id}/generate")
def api_generate_plan(plan_id: int) -> dict[str, Any]:
    return generate_from_plan(plan_id)


@app.patch("/api/section-plans/{plan_id}")
def api_update_plan(plan_id: int, payload: SectionPlanUpdateRequest) -> dict[str, Any]:
    return update_section_plan(
        plan_id,
        section_title=payload.section_title,
        order_no=payload.order_no,
        requirement_ids=payload.requirement_ids,
        status=payload.status,
    )


@app.delete("/api/section-plans/{plan_id}")
def api_delete_plan(plan_id: int) -> dict[str, Any]:
    return delete_section_plan(plan_id)


@app.patch("/api/drafts/{draft_id}")
def api_update_draft(draft_id: int, payload: DraftUpdateRequest) -> dict[str, Any]:
    return update_draft(draft_id, payload.content)


@app.get("/api/tenders/{tender_id}/review")
def api_review(tender_id: int) -> list[dict[str, Any]]:
    return review_tender(tender_id)


@app.post("/api/tenders/{tender_id}/export")
def api_export(tender_id: int, payload: ExportRequest) -> dict[str, Any]:
    if payload.format in {"formal_docx", "docx", "client_package", "client_zip"}:
        require_formal_export_ready(tender_id)
    if payload.format in {"client_package", "client_zip"}:
        result = export_client_package(tender_id)
    elif payload.format in {"internal_package", "package", "zip"}:
        result = export_package(tender_id)
    elif payload.format in {"formal_docx", "docx"}:
        result = export_client_docx(tender_id)
    elif payload.format == "internal_docx":
        result = export_docx(tender_id)
    else:
        result = export_markdown(tender_id)
    return result


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
