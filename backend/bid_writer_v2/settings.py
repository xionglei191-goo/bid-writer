from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE_ROOT = APP_ROOT.parents[1]


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
