from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
APP_ROOT = BACKEND_DIR.parent
DEFAULT_WORKSPACE_ROOT = APP_ROOT.parents[1]

WORKSPACE_ROOT = Path(
    os.environ.get("BID_WRITER_WORKSPACE", os.environ.get("BID_WRITER_ROOT", DEFAULT_WORKSPACE_ROOT))
).resolve()
PROJECT_ROOT = WORKSPACE_ROOT
RAW_ROOT = Path(os.environ.get("BID_WRITER_RAW", WORKSPACE_ROOT / "01_原始标书库")).resolve()
KNOWLEDGE_ROOT = Path(os.environ.get("BID_WRITER_KNOWLEDGE", WORKSPACE_ROOT / "02_知识库")).resolve()
KB_ROOT = KNOWLEDGE_ROOT / "Markdown"
MANIFEST_PATH = KB_ROOT / "manifest.csv"
SECTIONS_PATH = KB_ROOT / "sections.csv"
DELIVERY_ROOT = Path(os.environ.get("BID_WRITER_DELIVERY", WORKSPACE_ROOT / "04_交付与报告")).resolve()

DATA_DIR = Path(os.environ.get("BID_WRITER_DATA", APP_ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
OCR_DIR = DATA_DIR / "ocr"
ASSET_DIR = DATA_DIR / "visual_assets"
DOCUMENT_TEMPLATE_DIR = DATA_DIR / "document_templates"
EXPORT_DIR = Path(os.environ.get("BID_WRITER_EXPORT", DELIVERY_ROOT / "项目交付")).resolve()
QA_DIR = Path(os.environ.get("BID_WRITER_QA", DELIVERY_ROOT / "质量验收")).resolve()
DB_PATH = Path(os.environ.get("BID_WRITER_DB", DATA_DIR / "bid_writer.sqlite")).resolve()

STATIC_DIR = APP_ROOT / "static"

for directory in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, QA_DIR, OCR_DIR, ASSET_DIR, DOCUMENT_TEMPLATE_DIR):
    directory.mkdir(parents=True, exist_ok=True)
