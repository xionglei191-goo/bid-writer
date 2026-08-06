from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .settings import DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            source_format TEXT,
            markdown_path TEXT,
            output_dir TEXT,
            processing_action TEXT,
            duplicate_policy TEXT,
            top_category TEXT,
            top_company TEXT,
            top_project TEXT,
            page_count INTEGER,
            section_count INTEGER,
            char_count INTEGER,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            markdown_path TEXT,
            heading_order INTEGER,
            heading_level INTEGER,
            heading_text TEXT,
            page_number TEXT,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            section_id INTEGER,
            source_path TEXT NOT NULL,
            markdown_path TEXT,
            top_category TEXT,
            top_company TEXT,
            top_project TEXT,
            heading_text TEXT,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE SET NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            heading_text,
            source_path,
            top_category,
            top_project,
            tokenize='unicode61'
        );

        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            industry TEXT,
            region TEXT,
            file_path TEXT,
            raw_text TEXT,
            parsed_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS document_processing_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER,
            source_path TEXT,
            original_filename TEXT,
            file_type TEXT,
            action TEXT,
            status TEXT DEFAULT 'pending',
            text_chars INTEGER DEFAULT 0,
            page_count INTEGER DEFAULT 0,
            ocr_job_id TEXT,
            ocr_output_dir TEXT,
            markdown_path TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            source_hint TEXT,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending',
            requirement_key TEXT,
            response_scope TEXT DEFAULT 'chapter',
            score_weight REAL DEFAULT 0,
            source_page INTEGER,
            section_path TEXT,
            applicable INTEGER DEFAULT 1,
            classification_source TEXT DEFAULT 'auto',
            review_status TEXT DEFAULT 'pending',
            review_notes TEXT,
            acceptance_keywords_json TEXT DEFAULT '[]',
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS project_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            project_name TEXT,
            industry TEXT,
            region TEXT,
            project_type TEXT,
            structure_type TEXT,
            building_area TEXT,
            floor_info TEXT,
            duration_days INTEGER,
            planned_start TEXT,
            planned_finish TEXT,
            quality_target TEXT,
            safety_target TEXT,
            green_target TEXT,
            contract_scope TEXT,
            site_conditions TEXT,
            key_constraints TEXT,
            special_requirements TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS enterprise_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_name TEXT NOT NULL UNIQUE,
            bidder_name TEXT,
            legal_representative TEXT,
            contact TEXT,
            qualification_summary TEXT,
            capability_summary TEXT,
            quality_system TEXT,
            safety_system TEXT,
            key_personnel TEXT,
            equipment_resources TEXT,
            similar_projects TEXT,
            service_commitment TEXT,
            notes TEXT,
            is_default INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS production_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            customer_name TEXT,
            source_platform TEXT,
            order_no TEXT,
            contact TEXT,
            deadline TEXT,
            budget TEXT,
            deliverable_format TEXT,
            delivery_status TEXT DEFAULT '待生产',
            delivery_notes TEXT,
            internal_owner TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS material_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            category TEXT,
            name TEXT NOT NULL,
            status TEXT DEFAULT '待补充',
            required INTEGER DEFAULT 1,
            source TEXT,
            notes TEXT,
            owner TEXT,
            due_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            section_title TEXT NOT NULL,
            requirements_json TEXT,
            content TEXT NOT NULL,
            citations_json TEXT,
            review_json TEXT,
            generation_mode TEXT DEFAULT 'unknown',
            generation_model TEXT,
            generation_error TEXT,
            status TEXT DEFAULT 'draft',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS draft_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            tender_id INTEGER NOT NULL,
            version_no INTEGER NOT NULL,
            content TEXT NOT NULL,
            origin TEXT DEFAULT 'saved',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE CASCADE,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS section_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            order_no INTEGER NOT NULL,
            section_title TEXT NOT NULL,
            template_name TEXT,
            requirement_ids_json TEXT DEFAULT '[]',
            rationale TEXT,
            status TEXT DEFAULT 'planned',
            draft_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS requirement_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            requirement_id INTEGER NOT NULL,
            section_plan_id INTEGER,
            draft_id INTEGER,
            section_title TEXT,
            heading_path TEXT,
            evidence_text TEXT,
            coverage_score REAL DEFAULT 0,
            response_status TEXT DEFAULT 'unlinked',
            review_status TEXT DEFAULT 'pending',
            reviewed_by TEXT,
            review_notes TEXT,
            content_signature TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(requirement_id, draft_id),
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
            FOREIGN KEY(section_plan_id) REFERENCES section_plans(id) ON DELETE SET NULL,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS revision_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            task_key TEXT NOT NULL,
            source TEXT DEFAULT 'quality_gate',
            severity TEXT,
            title TEXT NOT NULL,
            scope TEXT,
            detail TEXT,
            action TEXT,
            section_title TEXT,
            draft_id INTEGER,
            requirement_id INTEGER,
            status TEXT DEFAULT '待处理',
            owner TEXT,
            due_at TEXT,
            notes TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            UNIQUE(tender_id, task_key),
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE SET NULL,
            FOREIGN KEY(requirement_id) REFERENCES requirements(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS delivery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            package_path TEXT,
            package_format TEXT,
            package_size INTEGER,
            components_json TEXT DEFAULT '{}',
            task_snapshot_json TEXT DEFAULT '{}',
            review_snapshot_json TEXT DEFAULT '{}',
            delivery_channel TEXT,
            recipient TEXT,
            status TEXT DEFAULT '已导出',
            notes TEXT,
            exported_at TEXT DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS feedback_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            delivery_record_id INTEGER,
            customer_name TEXT,
            source_channel TEXT,
            feedback_text TEXT NOT NULL,
            related_section TEXT,
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT '待处理',
            action_plan TEXT,
            owner TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(delivery_record_id) REFERENCES delivery_records(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS closure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            delivery_record_id INTEGER,
            status TEXT DEFAULT '客户待确认',
            confirmed_by TEXT,
            reply_deadline TEXT,
            confirmation_note TEXT,
            customer_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(delivery_record_id) REFERENCES delivery_records(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS project_retrospectives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT '待复盘',
            actual_price TEXT,
            actual_cost TEXT,
            work_hours REAL,
            revision_count INTEGER,
            satisfaction TEXT,
            risk_level TEXT,
            reusable_score INTEGER,
            industry_tags TEXT,
            reusable_assets TEXT,
            lessons TEXT,
            next_action TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pricing_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            value_type TEXT DEFAULT 'number',
            value TEXT NOT NULL,
            unit TEXT,
            enabled INTEGER DEFAULT 1,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS quotation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            customer_message TEXT,
            source_platform TEXT,
            quote_low INTEGER,
            quote_high INTEGER,
            suggested_price TEXT,
            workload TEXT,
            turnaround TEXT,
            factors_json TEXT DEFAULT '{}',
            pricing_snapshot_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payment_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'CNY',
            payment_stage TEXT DEFAULT '定金',
            payment_method TEXT,
            status TEXT DEFAULT '待确认',
            received_at TEXT,
            proof TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS case_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            draft_id INTEGER,
            project_name TEXT,
            industry TEXT,
            section_title TEXT NOT NULL,
            tags TEXT,
            content TEXT NOT NULL,
            summary TEXT,
            reusable_score INTEGER DEFAULT 3,
            source_status TEXT DEFAULT '人工沉淀',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS custom_section_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            keywords_json TEXT DEFAULT '[]',
            intent TEXT,
            outline_json TEXT DEFAULT '[]',
            quality_points_json TEXT DEFAULT '[]',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS document_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            source_docx_path TEXT,
            style_map_json TEXT DEFAULT '{}',
            cover_fields_json TEXT DEFAULT '{}',
            version TEXT DEFAULT '1.0',
            status TEXT DEFAULT 'active',
            is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS final_check_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            check_key TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            required INTEGER DEFAULT 1,
            status TEXT DEFAULT '待确认',
            owner TEXT,
            notes TEXT,
            auto_status TEXT,
            auto_detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tender_id, check_key),
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS draft_replacement_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            search_text TEXT NOT NULL,
            replace_text TEXT NOT NULL,
            changed_drafts INTEGER DEFAULT 0,
            changed_count INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_communications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            stage TEXT DEFAULT '询盘',
            direction TEXT DEFAULT 'outgoing',
            channel TEXT,
            customer_message TEXT,
            system_reply TEXT,
            status TEXT DEFAULT '待发送',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS document_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            document_title TEXT,
            document_subtitle TEXT,
            document_type TEXT DEFAULT '技术标',
            bidder_name TEXT,
            version_label TEXT DEFAULT '初稿',
            prepared_by TEXT,
            reviewed_by TEXT,
            document_date TEXT,
            confidentiality TEXT,
            header_text TEXT,
            footer_text TEXT,
            body_font TEXT DEFAULT 'Microsoft YaHei',
            body_font_size REAL DEFAULT 10.5,
            heading_font TEXT DEFAULT 'Microsoft YaHei',
            include_cover INTEGER DEFAULT 1,
            include_toc INTEGER DEFAULT 1,
            include_response_matrix INTEGER DEFAULT 1,
            include_delivery_review INTEGER DEFAULT 1,
            section_page_break INTEGER DEFAULT 1,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bid_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            positioning TEXT,
            win_themes TEXT,
            key_constraints TEXT,
            risk_controls TEXT,
            response_priorities TEXT,
            writing_tone TEXT,
            section_focus_json TEXT DEFAULT '[]',
            reference_keywords TEXT,
            forbidden_terms TEXT,
            status TEXT DEFAULT 'draft',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS final_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'draft',
            approved_by TEXT,
            approved_at TEXT,
            notes TEXT,
            checklist_json TEXT DEFAULT '[]',
            snapshot_hash TEXT,
            snapshot_char_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS visual_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER,
            asset_type TEXT NOT NULL,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            source_path TEXT,
            source_kind TEXT DEFAULT 'generated',
            industry TEXT,
            section_title TEXT,
            tags TEXT,
            caption TEXT,
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            sha256 TEXT,
            visual_class TEXT DEFAULT 'reference',
            review_status TEXT DEFAULT '待复核',
            review_notes TEXT,
            disclaimer TEXT,
            generation_prompt TEXT,
            technical_basis TEXT,
            overlay_json TEXT DEFAULT '{}',
            ai_model TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS document_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            draft_id INTEGER,
            section_title TEXT NOT NULL,
            block_order INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            title TEXT,
            caption TEXT,
            data_json TEXT DEFAULT '{}',
            asset_id INTEGER,
            source_path TEXT,
            status TEXT DEFAULT 'active',
            generated_by TEXT DEFAULT 'system',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE,
            FOREIGN KEY(draft_id) REFERENCES drafts(id) ON DELETE CASCADE,
            FOREIGN KEY(asset_id) REFERENCES visual_assets(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS workflow_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            stage_key TEXT NOT NULL,
            status TEXT DEFAULT 'confirmed',
            confirmed_by TEXT,
            notes TEXT,
            content_signature TEXT NOT NULL,
            confirmed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tender_id, stage_key),
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS acceptance_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            run_type TEXT DEFAULT 'full',
            status TEXT DEFAULT 'completed',
            quality_score INTEGER DEFAULT 0,
            metrics_json TEXT DEFAULT '{}',
            blockers_json TEXT DEFAULT '[]',
            exports_json TEXT DEFAULT '{}',
            manual_edit_hours REAL,
            conclusion TEXT,
            content_signature TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tender_id) REFERENCES tenders(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS case_assets_fts USING fts5(
            content,
            section_title,
            project_name,
            industry,
            tags,
            tokenize='unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(top_category);
        CREATE INDEX IF NOT EXISTS idx_document_processing_tender ON document_processing_records(tender_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_document_processing_status ON document_processing_records(status, file_type);
        CREATE INDEX IF NOT EXISTS idx_requirement_responses_tender ON requirement_responses(tender_id, response_status, review_status);
        CREATE INDEX IF NOT EXISTS idx_requirement_responses_requirement ON requirement_responses(requirement_id);
        CREATE INDEX IF NOT EXISTS idx_acceptance_runs_tender ON acceptance_runs(tender_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(top_category);
        CREATE INDEX IF NOT EXISTS idx_chunks_heading ON chunks(heading_text);
        CREATE INDEX IF NOT EXISTS idx_requirements_tender ON requirements(tender_id);
        CREATE INDEX IF NOT EXISTS idx_project_profiles_tender ON project_profiles(tender_id);
        CREATE INDEX IF NOT EXISTS idx_enterprise_profiles_default ON enterprise_profiles(is_default, profile_name);
        CREATE INDEX IF NOT EXISTS idx_production_tasks_tender ON production_tasks(tender_id);
        CREATE INDEX IF NOT EXISTS idx_production_tasks_status ON production_tasks(delivery_status);
        CREATE INDEX IF NOT EXISTS idx_material_items_tender ON material_items(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_drafts_tender ON drafts(tender_id);
        CREATE INDEX IF NOT EXISTS idx_draft_versions_draft ON draft_versions(draft_id, version_no);
        CREATE INDEX IF NOT EXISTS idx_section_plans_tender ON section_plans(tender_id, order_no);
        CREATE INDEX IF NOT EXISTS idx_revision_tasks_tender ON revision_tasks(tender_id, active, status);
        CREATE INDEX IF NOT EXISTS idx_revision_tasks_scope ON revision_tasks(scope, severity);
        CREATE INDEX IF NOT EXISTS idx_delivery_records_tender ON delivery_records(tender_id, exported_at);
        CREATE INDEX IF NOT EXISTS idx_delivery_records_status ON delivery_records(status);
        CREATE INDEX IF NOT EXISTS idx_feedback_items_tender ON feedback_items(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_feedback_items_delivery ON feedback_items(delivery_record_id);
        CREATE INDEX IF NOT EXISTS idx_closure_records_tender ON closure_records(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_closure_records_delivery ON closure_records(delivery_record_id);
        CREATE INDEX IF NOT EXISTS idx_project_retrospectives_status ON project_retrospectives(status, risk_level);
        CREATE INDEX IF NOT EXISTS idx_pricing_rules_category ON pricing_rules(category, enabled);
        CREATE INDEX IF NOT EXISTS idx_quotation_records_tender ON quotation_records(tender_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_payment_records_tender ON payment_records(tender_id, status, received_at);
        CREATE INDEX IF NOT EXISTS idx_case_assets_tender ON case_assets(tender_id, section_title);
        CREATE INDEX IF NOT EXISTS idx_case_assets_industry ON case_assets(industry, reusable_score);
        CREATE INDEX IF NOT EXISTS idx_custom_section_templates_enabled ON custom_section_templates(enabled, name);
        CREATE INDEX IF NOT EXISTS idx_final_check_items_tender ON final_check_items(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_draft_replacement_records_tender ON draft_replacement_records(tender_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_customer_communications_tender ON customer_communications(tender_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_customer_communications_status ON customer_communications(status, stage);
        CREATE INDEX IF NOT EXISTS idx_document_settings_tender ON document_settings(tender_id);
        CREATE INDEX IF NOT EXISTS idx_bid_strategies_tender ON bid_strategies(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_final_documents_tender ON final_documents(tender_id, status);
        CREATE INDEX IF NOT EXISTS idx_visual_assets_tender ON visual_assets(tender_id, asset_type, status);
        CREATE INDEX IF NOT EXISTS idx_visual_assets_sha ON visual_assets(sha256);
        CREATE INDEX IF NOT EXISTS idx_document_blocks_tender ON document_blocks(tender_id, section_title, block_order);
        CREATE INDEX IF NOT EXISTS idx_document_blocks_draft ON document_blocks(draft_id, block_order);
        CREATE INDEX IF NOT EXISTS idx_workflow_confirmations_tender ON workflow_confirmations(tender_id, stage_key);
        """
    )
    _ensure_column(conn, "drafts", "generation_mode", "TEXT DEFAULT 'unknown'")
    _ensure_column(conn, "drafts", "generation_model", "TEXT")
    _ensure_column(conn, "drafts", "generation_error", "TEXT")
    _ensure_column(conn, "requirements", "requirement_key", "TEXT")
    _ensure_column(conn, "requirements", "response_scope", "TEXT DEFAULT 'chapter'")
    _ensure_column(conn, "requirements", "score_weight", "REAL DEFAULT 0")
    _ensure_column(conn, "requirements", "source_page", "INTEGER")
    _ensure_column(conn, "requirements", "section_path", "TEXT")
    _ensure_column(conn, "requirements", "applicable", "INTEGER DEFAULT 1")
    _ensure_column(conn, "requirements", "classification_source", "TEXT DEFAULT 'auto'")
    _ensure_column(conn, "requirements", "review_status", "TEXT DEFAULT 'pending'")
    _ensure_column(conn, "requirements", "review_notes", "TEXT")
    _ensure_column(conn, "requirements", "acceptance_keywords_json", "TEXT DEFAULT '[]'")
    _ensure_column(conn, "document_settings", "template_id", "INTEGER")
    _ensure_column(conn, "custom_section_templates", "industry", "TEXT")
    _ensure_column(conn, "custom_section_templates", "project_type", "TEXT")
    _ensure_column(conn, "custom_section_templates", "method_key", "TEXT")
    _ensure_column(conn, "custom_section_templates", "version", "TEXT DEFAULT '1.0'")
    _ensure_column(conn, "custom_section_templates", "review_status", "TEXT DEFAULT 'approved'")
    _ensure_column(conn, "custom_section_templates", "generation_rules_json", "TEXT DEFAULT '{}'")
    _ensure_column(conn, "visual_assets", "visual_class", "TEXT DEFAULT 'reference'")
    _ensure_column(conn, "visual_assets", "review_status", "TEXT DEFAULT '待复核'")
    _ensure_column(conn, "visual_assets", "review_notes", "TEXT")
    _ensure_column(conn, "visual_assets", "disclaimer", "TEXT")
    _ensure_column(conn, "visual_assets", "generation_prompt", "TEXT")
    _ensure_column(conn, "visual_assets", "technical_basis", "TEXT")
    _ensure_column(conn, "visual_assets", "overlay_json", "TEXT DEFAULT '{}'")
    _ensure_column(conn, "visual_assets", "ai_model", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requirements_scope ON requirements(tender_id, response_scope, priority)")
    conn.commit()


def reset_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS chunks_fts;
        DROP TABLE IF EXISTS case_assets_fts;
        DROP TABLE IF EXISTS acceptance_runs;
        DROP TABLE IF EXISTS requirement_responses;
        DROP TABLE IF EXISTS revision_tasks;
        DROP TABLE IF EXISTS section_plans;
        DROP TABLE IF EXISTS case_assets;
        DROP TABLE IF EXISTS custom_section_templates;
        DROP TABLE IF EXISTS final_check_items;
        DROP TABLE IF EXISTS draft_replacement_records;
        DROP TABLE IF EXISTS customer_communications;
        DROP TABLE IF EXISTS document_settings;
        DROP TABLE IF EXISTS document_templates;
        DROP TABLE IF EXISTS bid_strategies;
        DROP TABLE IF EXISTS final_documents;
        DROP TABLE IF EXISTS workflow_confirmations;
        DROP TABLE IF EXISTS document_blocks;
        DROP TABLE IF EXISTS visual_assets;
        DROP TABLE IF EXISTS payment_records;
        DROP TABLE IF EXISTS quotation_records;
        DROP TABLE IF EXISTS pricing_rules;
        DROP TABLE IF EXISTS project_retrospectives;
        DROP TABLE IF EXISTS closure_records;
        DROP TABLE IF EXISTS feedback_items;
        DROP TABLE IF EXISTS delivery_records;
        DROP TABLE IF EXISTS draft_versions;
        DROP TABLE IF EXISTS drafts;
        DROP TABLE IF EXISTS material_items;
        DROP TABLE IF EXISTS production_tasks;
        DROP TABLE IF EXISTS enterprise_profiles;
        DROP TABLE IF EXISTS project_profiles;
        DROP TABLE IF EXISTS requirements;
        DROP TABLE IF EXISTS document_processing_records;
        DROP TABLE IF EXISTS tenders;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS sections;
        DROP TABLE IF EXISTS documents;
        """
    )
    conn.commit()
    init_db(conn)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def count(table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    categories = conn.execute(
        """
        SELECT top_category AS category, COUNT(*) AS count
        FROM documents
        WHERE COALESCE(top_category, '') <> ''
        GROUP BY top_category
        ORDER BY count DESC, category
        LIMIT 20
        """
    ).fetchall()
    return {
        "documents": count("documents"),
        "sections": count("sections"),
        "chunks": count("chunks"),
        "tenders": count("tenders"),
        "drafts": count("drafts"),
        "plans": count("section_plans"),
        "revision_tasks": count("revision_tasks"),
        "deliveries": count("delivery_records"),
        "feedback": count("feedback_items"),
        "materials": count("material_items"),
        "closures": count("closure_records"),
        "retrospectives": count("project_retrospectives"),
        "pricing_rules": count("pricing_rules"),
        "quotations": count("quotation_records"),
        "payments": count("payment_records"),
        "case_assets": count("case_assets"),
        "custom_templates": count("custom_section_templates"),
        "final_checks": count("final_check_items"),
        "replacement_records": count("draft_replacement_records"),
        "communications": count("customer_communications"),
        "document_settings": count("document_settings"),
        "enterprise_profiles": count("enterprise_profiles"),
        "bid_strategies": count("bid_strategies"),
        "final_documents": count("final_documents"),
        "document_blocks": count("document_blocks"),
        "visual_assets": count("visual_assets"),
        "document_processing": count("document_processing_records"),
        "top_categories": rows_to_dicts(categories),
    }
