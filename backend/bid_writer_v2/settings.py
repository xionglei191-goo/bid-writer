from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE_ROOT = APP_ROOT.parents[1] if len(APP_ROOT.parents) > 1 else APP_ROOT.parent


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    app_root: Path
    raw_root: Path
    knowledge_root: Path
    delivery_root: Path
    data_root: Path
    db_path: Path
    upload_root: Path
    cache_root: Path
    export_root: Path
    qa_root: Path
    operations_enabled: bool
    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = ""
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False
    minio_bucket: str = "bid-writer"
    auth_enabled: bool = False
    session_secret: str = ""
    bootstrap_admin: str = "admin"
    bootstrap_password: str = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_min_score: float = 0.25
    embedding_device: str = "auto"
    embedding_url: str = ""
    background_jobs_enabled: bool = False
    auto_publish_low_risk: bool = False
    ocr_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    ocr_model: str = "PaddleOCR-VL-1.5"
    ocr_token_env: str = "PADDLEOCR_TOKEN"
    ocr_chunk_pages: int = 100
    ocr_poll_interval_seconds: float = 5.0
    ocr_max_polls: int = 720

    @classmethod
    def from_env(cls) -> "Settings":
        workspace = Path(os.environ.get("BID_WRITER_WORKSPACE", DEFAULT_WORKSPACE_ROOT)).resolve()
        app_root = Path(os.environ.get("BID_WRITER_APP_ROOT", APP_ROOT)).resolve()
        data_root = Path(os.environ.get("BID_WRITER_DATA", app_root / "data")).resolve()
        delivery_root = Path(os.environ.get("BID_WRITER_DELIVERY", workspace / "04_\u4ea4\u4ed8\u4e0e\u62a5\u544a")).resolve()
        return cls(
            workspace_root=workspace,
            app_root=app_root,
            raw_root=Path(os.environ.get("BID_WRITER_RAW", workspace / "01_\u539f\u59cb\u6807\u4e66\u5e93")).resolve(),
            knowledge_root=Path(os.environ.get("BID_WRITER_KNOWLEDGE", workspace / "02_\u77e5\u8bc6\u5e93")).resolve(),
            delivery_root=delivery_root,
            data_root=data_root,
            db_path=Path(os.environ.get("BID_WRITER_DB", data_root / "bid_writer_v2.sqlite3")).resolve(),
            upload_root=Path(os.environ.get("BID_WRITER_UPLOADS", data_root / "uploads")).resolve(),
            cache_root=Path(os.environ.get("BID_WRITER_CACHE", data_root / "cache")).resolve(),
            export_root=Path(os.environ.get("BID_WRITER_EXPORT", delivery_root / "\u9879\u76ee\u4ea4\u4ed8")).resolve(),
            qa_root=Path(os.environ.get("BID_WRITER_QA", delivery_root / "\u8d28\u91cf\u9a8c\u6536")).resolve(),
            operations_enabled=os.environ.get("BID_WRITER_ENABLE_OPERATIONS", "0") == "1",
            database_url=os.environ.get("BID_WRITER_DATABASE_URL", "").strip(),
            redis_url=os.environ.get("BID_WRITER_REDIS_URL", "").strip(),
            qdrant_url=os.environ.get("BID_WRITER_QDRANT_URL", "").strip(),
            minio_endpoint=os.environ.get("BID_WRITER_MINIO_ENDPOINT", "").strip(),
            minio_access_key=os.environ.get("BID_WRITER_MINIO_ACCESS_KEY", "").strip(),
            minio_secret_key=os.environ.get("BID_WRITER_MINIO_SECRET_KEY", "").strip(),
            minio_secure=os.environ.get("BID_WRITER_MINIO_SECURE", "0") == "1",
            minio_bucket=os.environ.get("BID_WRITER_MINIO_BUCKET", "bid-writer").strip() or "bid-writer",
            auth_enabled=os.environ.get("BID_WRITER_AUTH_ENABLED", "0") == "1",
            session_secret=os.environ.get("BID_WRITER_SESSION_SECRET", "").strip(),
            bootstrap_admin=os.environ.get("BID_WRITER_BOOTSTRAP_ADMIN", "admin").strip() or "admin",
            bootstrap_password=os.environ.get("BID_WRITER_BOOTSTRAP_PASSWORD", "").strip(),
            oidc_issuer=os.environ.get("BID_WRITER_OIDC_ISSUER", "").strip(),
            oidc_client_id=os.environ.get("BID_WRITER_OIDC_CLIENT_ID", "").strip(),
            oidc_client_secret=os.environ.get("BID_WRITER_OIDC_CLIENT_SECRET", "").strip(),
            oidc_redirect_uri=os.environ.get("BID_WRITER_OIDC_REDIRECT_URI", "").strip(),
            embedding_model=os.environ.get("BID_WRITER_EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
            reranker_model=os.environ.get("BID_WRITER_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip(),
            reranker_min_score=max(0.0, min(1.0, float(os.environ.get("BID_WRITER_RERANK_MIN_SCORE", "0.25")))),
            embedding_device=os.environ.get("BID_WRITER_EMBEDDING_DEVICE", "auto").strip(),
            embedding_url=os.environ.get("BID_WRITER_EMBEDDING_URL", "").strip().rstrip("/"),
            background_jobs_enabled=os.environ.get("BID_WRITER_BACKGROUND_JOBS", "0") == "1",
            auto_publish_low_risk=os.environ.get("BID_WRITER_AUTO_PUBLISH_LOW_RISK", "0") == "1",
            ocr_job_url=(os.environ.get("BID_WRITER_OCR_URL") or os.environ.get("PADDLEOCR_JOB_URL") or "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs").rstrip("/"),
            ocr_model=os.environ.get("BID_WRITER_OCR_MODEL") or os.environ.get("PADDLEOCR_MODEL") or "PaddleOCR-VL-1.5",
            ocr_token_env=os.environ.get("BID_WRITER_OCR_TOKEN_ENV", "PADDLEOCR_TOKEN"),
            ocr_chunk_pages=max(1, int(os.environ.get("BID_WRITER_OCR_CHUNK_PAGES", "100"))),
            ocr_poll_interval_seconds=max(0.1, float(os.environ.get("BID_WRITER_OCR_POLL_SECONDS", "5"))),
            ocr_max_polls=max(1, int(os.environ.get("BID_WRITER_OCR_MAX_POLLS", "720"))),
        )

    def ensure_directories(self) -> None:
        directories = [
            self.raw_root,
            self.knowledge_root,
            self.data_root,
            self.upload_root,
            self.cache_root,
            self.export_root,
            self.qa_root,
        ]
        directories.extend(self.knowledge_directories.values())
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def knowledge_directories(self) -> dict[str, Path]:
        return {
            "documents": self.knowledge_root / "01_\u6807\u51c6\u5316\u6587\u6863",
            "units": self.knowledge_root / "02_\u77e5\u8bc6\u5355\u5143",
            "drafts": self.knowledge_root / "03_\u91cd\u6784\u8349\u7a3f",
            "reviews": self.knowledge_root / "04_\u5ba1\u6838\u8bb0\u5f55",
            "assets": self.knowledge_root / "05_\u6a21\u677f\u4e0e\u8d44\u4ea7",
            "published": self.knowledge_root / "06_\u5df2\u53d1\u5e03\u77e5\u8bc6\u5e93",
            "metadata": self.knowledge_root / "07_\u5143\u6570\u636e",
        }
