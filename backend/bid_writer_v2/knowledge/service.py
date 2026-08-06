from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..database import Database
from ..llm import LlmClient
from ..settings import Settings
from ..utils import content_hash, family_key, infer_industry, normalize_text, parse_json, sha256_file, write_json_atomic, write_text_atomic
from .ocr import ocr_pdf
from .parsers import OcrRequired, ParsedDocument, parse_document


SUPPORTED_TEXT = {".docx", ".doc", ".pdf", ".md", ".txt"}
ARCHIVES = {".zip", ".rar", ".7z"}
ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".xlsx", ".xls", ".pptx"}
METADATA_ONLY = {".dwg", ".dwf", ".mpp", ".vsd", ".plt"}


def decode_archive_member_name(name: str, flag_bits: int = 0) -> str:
    """Repair legacy Chinese ZIP names decoded by zipfile as CP437."""
    if flag_bits & 0x800:
        return name
    suspicious = sum(
        1
        for char in name
        if "\u2500" <= char <= "\u259f" or "\u0370" <= char <= "\u03ff"
    )
    if not suspicious:
        return name
    try:
        candidate = name.encode("cp437").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return candidate if any("\u4e00" <= char <= "\u9fff" for char in candidate) else name


class KnowledgeService:
    def __init__(self, db: Database, settings: Settings, llm: LlmClient | None = None) -> None:
        self.db = db
        self.settings = settings
        self.llm = llm or LlmClient()

    def scan_sources(self, limit: int | None = None, expand_archives: bool = True) -> dict[str, Any]:
        counters = {"scanned": 0, "created": 0, "updated": 0, "duplicates": 0, "archives": 0, "archive_failed": 0, "file_failed": 0, "unsupported": 0}
        inventory: list[dict[str, Any]] = []
        candidates = (path for path in self.settings.raw_root.rglob("*") if path.is_file())
        with self.db.connect() as conn:
            for path in candidates:
                if limit and counters["scanned"] >= limit:
                    break
                counters["scanned"] += 1
                try:
                    row, created = self._register_source(conn, path, source_kind="raw")
                except Exception:
                    counters["file_failed"] += 1
                    continue
                counters["created" if created else "updated"] += 1
                if row.get("duplicate_of"):
                    counters["duplicates"] += 1
                if path.suffix.lower() in ARCHIVES:
                    counters["archives"] += 1
                    if expand_archives:
                        try:
                            members = self._expand_archive(path, int(row["id"]), row["sha256"])
                        except Exception as exc:  # noqa: BLE001
                            counters["archive_failed"] += 1
                            conn.execute(
                                "UPDATE source_files SET status='failed',error_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (f"{type(exc).__name__}: {exc}", row["id"]),
                            )
                            members = []
                        for member in members:
                            try:
                                child, child_created = self._register_source(
                                    conn,
                                    member,
                                    source_kind="archive_member",
                                    parent_source_id=int(row["id"]),
                                )
                                counters["created" if child_created else "updated"] += 1
                            except Exception:
                                counters["file_failed"] += 1
                elif path.suffix.lower() not in SUPPORTED_TEXT | ASSET_EXTENSIONS | METADATA_ONLY:
                    counters["unsupported"] += 1
                inventory.append(row)
            all_sources = [dict(item) for item in conn.execute("SELECT * FROM source_files ORDER BY id")]
        metadata_path = self.settings.knowledge_directories["metadata"] / "source_inventory.jsonl"
        write_text_atomic(metadata_path, "\n".join(json.dumps(item, ensure_ascii=False) for item in all_sources) + "\n")
        return {**counters, "inventory_path": str(metadata_path)}

    def _register_source(
        self,
        conn,
        path: Path,
        *,
        source_kind: str,
        parent_source_id: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        absolute = str(path.resolve())
        try:
            relative = str(path.resolve().relative_to(self.settings.workspace_root))
        except ValueError:
            relative = absolute
        digest = sha256_file(path)
        duplicate = conn.execute(
            "SELECT id FROM source_files WHERE sha256 = ? AND absolute_path <> ? ORDER BY id LIMIT 1",
            (digest, absolute),
        ).fetchone()
        existing = conn.execute("SELECT id FROM source_files WHERE absolute_path = ?", (absolute,)).fetchone()
        status = self._source_status(path.suffix.lower(), bool(duplicate))
        values = (
            parent_source_id,
            relative,
            path.name,
            path.suffix.lower(),
            path.stat().st_size,
            digest,
            family_key(path),
            infer_industry(path),
            source_kind,
            int(duplicate[0]) if duplicate else None,
            status,
            absolute,
        )
        if existing:
            conn.execute(
                """
                UPDATE source_files SET parent_source_id=?, relative_path=?, file_name=?, extension=?, size_bytes=?,
                    sha256=?, family_key=?, industry=?, source_kind=?, duplicate_of=?, status=?, updated_at=CURRENT_TIMESTAMP
                WHERE absolute_path=?
                """,
                values,
            )
            source_id = int(existing[0])
            created = False
        else:
            cursor = conn.execute(
                """
                INSERT INTO source_files(parent_source_id, relative_path, file_name, extension, size_bytes, sha256,
                    family_key, industry, source_kind, duplicate_of, status, absolute_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            source_id = int(cursor.lastrowid)
            created = True
        row = conn.execute("SELECT * FROM source_files WHERE id = ?", (source_id,)).fetchone()
        family_matches = conn.execute(
            "SELECT id,extension FROM source_files WHERE family_key=? AND id<>? ORDER BY id LIMIT 20",
            (family_key(path), source_id),
        ).fetchall()
        for match in family_matches:
            if {path.suffix.lower(), str(match["extension"])} <= {".doc", ".docx", ".pdf"}:
                left, right = sorted((source_id, int(match["id"])))
                conn.execute(
                    "INSERT OR IGNORE INTO source_relations(source_id,related_source_id,relation_type,confidence) VALUES (?,?, 'word_pdf_pair',0.75)",
                    (left, right),
                )
        return dict(row), created

    @staticmethod
    def _source_status(extension: str, duplicate: bool) -> str:
        if duplicate:
            return "duplicate"
        if extension in SUPPORTED_TEXT:
            return "discovered"
        if extension in ARCHIVES:
            return "archive"
        if extension in ASSET_EXTENSIONS:
            return "asset"
        return "metadata_only"

    def _expand_archive(self, path: Path, source_id: int, digest: str) -> list[Path]:
        target = self.settings.cache_root / "archives" / f"{source_id}_{digest[:12]}"
        marker = target / ".complete"
        if marker.exists():
            return [item for item in target.rglob("*") if item.is_file() and item.name != ".complete"]
        target.mkdir(parents=True, exist_ok=True)
        extension = path.suffix.lower()
        if extension == ".zip":
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    member_name = decode_archive_member_name(member.filename, member.flag_bits)
                    destination = (target / member_name).resolve()
                    if not str(destination).startswith(str(target.resolve())):
                        continue
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, destination.open("wb") as output:
                            shutil.copyfileobj(source, output)
        else:
            seven_zip = shutil.which("7z") or shutil.which("7za")
            if not seven_zip:
                return []
            subprocess.run([seven_zip, "x", str(path), f"-o{target}", "-y"], check=True, timeout=600)
        marker.write_text("ok", encoding="ascii")
        return [item for item in target.rglob("*") if item.is_file() and item.name != ".complete"]

    def list_sources(self, status: str = "", query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if query:
            clauses.append("(file_name LIKE ? OR relative_path LIKE ? OR industry LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(limit, 500))
        with self.db.connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM source_files {where}", params).fetchone()[0])
            rows = conn.execute(
                f"SELECT * FROM source_files {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, limit, max(0, offset)],
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def create_jobs(self, source_ids: Iterable[int] | None = None, limit: int = 100) -> dict[str, Any]:
        with self.db.connect() as conn:
            if source_ids:
                ids = [int(value) for value in source_ids]
            else:
                ids = [
                    int(row[0])
                    for row in conn.execute(
                        "SELECT id FROM source_files WHERE status = 'discovered' ORDER BY id LIMIT ?", (limit,)
                    ).fetchall()
                ]
            created: list[int] = []
            for source_id in ids:
                existing = conn.execute(
                    "SELECT id FROM processing_jobs WHERE source_id=? AND status IN ('pending','running','waiting_ocr')",
                    (source_id,),
                ).fetchone()
                if existing:
                    continue
                cursor = conn.execute(
                    "INSERT INTO processing_jobs(source_id, job_type, status, current_step) VALUES (?, 'normalize', 'pending', 'queued')",
                    (source_id,),
                )
                created.append(int(cursor.lastrowid))
        return {"created": len(created), "job_ids": created}

    def list_jobs(self, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE j.status = ?"
            params.append(status)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT j.*, s.file_name, s.relative_path, s.extension, s.industry
                FROM processing_jobs j JOIN source_files s ON s.id=j.source_id
                {where} ORDER BY j.id DESC LIMIT ?
                """,
                [*params, max(1, min(limit, 500))],
            ).fetchall()
        return [dict(row) for row in rows]

    def run_job(self, job_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT j.*, s.absolute_path, s.file_name, s.extension, s.industry, s.duplicate_of FROM processing_jobs j JOIN source_files s ON s.id=j.source_id WHERE j.id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise KeyError("处理任务不存在")
            job = dict(row)
            if job["duplicate_of"]:
                conn.execute(
                    "UPDATE processing_jobs SET status='skipped', progress=100, current_step='duplicate', finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job_id,),
                )
                return {"id": job_id, "status": "skipped", "reason": "duplicate"}
            conn.execute(
                "UPDATE processing_jobs SET status='running', progress=5, current_step='parse', attempt_count=attempt_count+1, started_at=COALESCE(started_at,CURRENT_TIMESTAMP), updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        try:
            parsed = self._parse_job(job)
            result = self._store_document(job, parsed)
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE processing_jobs SET status='completed', progress=100, current_step='completed', error_message=NULL, finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job_id,),
                )
                conn.execute("UPDATE source_files SET status='processed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["source_id"],))
            return {"id": job_id, "status": "completed", **result}
        except OcrRequired as exc:
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE processing_jobs SET status='waiting_ocr', progress=20, current_step='ocr', checkpoint_json=?, error_message=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps({"page_count": exc.page_count}), job_id),
                )
            return {"id": job_id, "status": "waiting_ocr", "page_count": exc.page_count}
        except Exception as exc:  # noqa: BLE001
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE processing_jobs SET status='failed', current_step='failed', error_message=?, finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (f"{type(exc).__name__}: {exc}", job_id),
                )
            return {"id": job_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    def run_ocr(self, job_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT j.*, s.absolute_path, s.file_name, s.extension, s.industry FROM processing_jobs j JOIN source_files s ON s.id=j.source_id WHERE j.id=?",
                (job_id,),
            ).fetchone()
            if not row:
                raise KeyError("处理任务不存在")
            job = dict(row)
            conn.execute(
                "UPDATE processing_jobs SET status='running', current_step='ocr', progress=25, attempt_count=attempt_count+1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        try:
            markdown, page_count = ocr_pdf(Path(job["absolute_path"]), int(job["source_id"]), self.settings)
            parsed = ParsedDocument(Path(job["absolute_path"]).stem, markdown, "paddleocr-vl-1.5", page_count)
            result = self._store_document(job, parsed)
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE processing_jobs SET status='completed', progress=100, current_step='completed', error_message=NULL, finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (job_id,),
                )
                conn.execute("UPDATE source_files SET status='processed', updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["source_id"],))
            return {"id": job_id, "status": "completed", **result}
        except Exception as exc:  # noqa: BLE001
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE processing_jobs SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (f"{type(exc).__name__}: {exc}", job_id),
                )
            return {"id": job_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    def retry_job(self, job_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE processing_jobs SET status='pending', progress=0, current_step='queued', error_message=NULL, finished_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
        return self.run_job(job_id)

    def pause_job(self, job_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT status FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("处理任务不存在")
            if row["status"] == "running":
                raise ValueError("当前步骤正在执行，将在步骤完成后才能暂停")
            conn.execute("UPDATE processing_jobs SET status='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        return {"id": job_id, "status": "paused"}

    def resume_job(self, job_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT status FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("处理任务不存在")
            conn.execute("UPDATE processing_jobs SET status='pending',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        return {"id": job_id, "status": "pending"}

    def run_pending_jobs(self, limit: int = 20) -> dict[str, Any]:
        jobs = [item for item in self.list_jobs(status="pending", limit=limit)]
        results = [self.run_job(int(item["id"])) for item in reversed(jobs)]
        return {
            "processed": len(results),
            "completed": sum(1 for item in results if item.get("status") == "completed"),
            "waiting_ocr": sum(1 for item in results if item.get("status") == "waiting_ocr"),
            "failed": sum(1 for item in results if item.get("status") == "failed"),
            "results": results,
        }

    def _parse_job(self, job: dict[str, Any]) -> ParsedDocument:
        path = Path(job["absolute_path"])
        return parse_document(path, int(job["source_id"]), self.settings)

    def _store_document(self, job: dict[str, Any], parsed: ParsedDocument) -> dict[str, Any]:
        source_id = int(job["source_id"])
        document_dir = self.settings.knowledge_directories["documents"] / f"{source_id:07d}"
        markdown_path = document_dir / "document.md"
        write_text_atomic(markdown_path, parsed.markdown)
        sections = self._split_sections(parsed.markdown, parsed.title)
        with self.db.connect() as conn:
            fingerprint = content_hash(normalize_text(parsed.markdown))
            duplicate_document = conn.execute(
                "SELECT id,source_id FROM standard_documents WHERE text_fingerprint=? AND source_id<>? ORDER BY id LIMIT 1",
                (fingerprint, source_id),
            ).fetchone()
            if duplicate_document:
                conn.execute(
                    "UPDATE source_files SET duplicate_of=?,status='duplicate',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (int(duplicate_document["source_id"]), source_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO source_relations(source_id,related_source_id,relation_type,confidence) VALUES (?,?, 'content_duplicate',1.0)",
                    (min(source_id, int(duplicate_document["source_id"])), max(source_id, int(duplicate_document["source_id"]))),
                )
                return {"document_id": int(duplicate_document["id"]), "sections": 0, "units": 0, "markdown_path": str(markdown_path), "duplicate_of": int(duplicate_document["source_id"])}
            existing = conn.execute("SELECT id FROM standard_documents WHERE source_id=?", (source_id,)).fetchone()
            if existing:
                document_id = int(existing[0])
                conn.execute("DELETE FROM document_sections WHERE document_id=?", (document_id,))
                conn.execute(
                    "UPDATE standard_documents SET title=?, markdown_path=?, parser=?, page_count=?, char_count=?, text_fingerprint=?, status='ready', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (parsed.title, str(markdown_path), parsed.parser, parsed.page_count, len(parsed.markdown), fingerprint, document_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO standard_documents(source_id,title,markdown_path,parser,page_count,char_count,text_fingerprint) VALUES (?,?,?,?,?,?,?)",
                    (source_id, parsed.title, str(markdown_path), parsed.parser, parsed.page_count, len(parsed.markdown), fingerprint),
                )
                document_id = int(cursor.lastrowid)
            unit_ids: list[int] = []
            for order_no, section in enumerate(sections, 1):
                section_fingerprint = content_hash(section["content"])
                cursor = conn.execute(
                    "INSERT INTO document_sections(document_id,order_no,level,heading,content,page_start,page_end,content_fingerprint) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        document_id,
                        order_no,
                        section["level"],
                        section["heading"],
                        section["content"],
                        section.get("page_start"),
                        section.get("page_end"),
                        section_fingerprint,
                    ),
                )
                section_id = int(cursor.lastrowid)
                is_structured = section["heading"].startswith(("表格", "流程图", "组织架构图", "横道图", "总平面图"))
                minimum_length = 20 if is_structured else 80
                if len(section["content"].strip()) < minimum_length:
                    continue
                unit_id = self._create_unit(conn, source_id, section_id, job, section)
                unit_ids.append(unit_id)
        return {"document_id": document_id, "sections": len(sections), "units": len(unit_ids), "markdown_path": str(markdown_path)}

    def _create_unit(self, conn, source_id: int, section_id: int, job: dict[str, Any], section: dict[str, Any]) -> int:
        cleaned = self._clean_project_specific(section["content"])
        unit_type = self._classify_unit(section["heading"], cleaned)
        fingerprint = content_hash(cleaned)
        unit_key = content_hash(f"{source_id}:{section_id}:{fingerprint}")[:32]
        tags = self._tags(section["heading"], cleaned, str(job.get("industry") or "通用"), unit_type)
        cursor = conn.execute(
            """
            INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,industry,tags_json,risk_level,status,content_fingerprint)
            VALUES (?,?,?,?,?,?,?,'textual','review_required',?)
            """,
            (
                unit_key,
                unit_type,
                section["heading"],
                section["content"],
                cleaned,
                job.get("industry") or "通用",
                json.dumps(tags, ensure_ascii=False),
                fingerprint,
            ),
        )
        unit_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO knowledge_unit_sources(unit_id,section_id,source_id,excerpt,page_start) VALUES (?,?,?,?,?)",
            (unit_id, section_id, source_id, cleaned[:500], section.get("page_start")),
        )
        conn.execute(
            "INSERT INTO knowledge_versions(unit_id,version_no,content,summary,origin,content_hash,status) VALUES (?,1,?,?, 'extracted',?,'review_required')",
            (unit_id, cleaned, cleaned[:200], fingerprint),
        )
        self._write_unit_file(unit_id, {
            "id": unit_id,
            "unit_key": unit_key,
            "unit_type": unit_type,
            "title": section["heading"],
            "industry": job.get("industry") or "通用",
            "tags": tags,
            "status": "review_required",
            "source_ids": [source_id],
            "content": cleaned,
        })
        return unit_id

    @staticmethod
    def _split_sections(markdown: str, default_title: str) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current = {"heading": default_title, "level": 1, "lines": [], "page_start": None, "page_end": None}
        current_page: int | None = None
        for line in markdown.splitlines():
            page_match = re.match(r"<!--\s*page:(\d+)\s*-->", line.strip())
            if page_match:
                current_page = int(page_match.group(1))
                if current["page_start"] is None:
                    current["page_start"] = current_page
                current["page_end"] = current_page
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
            if heading:
                content = normalize_text("\n".join(current["lines"]))
                if content:
                    sections.append({
                        "heading": current["heading"],
                        "level": current["level"],
                        "content": content,
                        "page_start": current["page_start"],
                        "page_end": current["page_end"],
                    })
                current = {
                    "heading": heading.group(2).strip(),
                    "level": len(heading.group(1)),
                    "lines": [],
                    "page_start": current_page,
                    "page_end": current_page,
                }
            else:
                current["lines"].append(line)
                if current_page:
                    current["page_end"] = current_page
        content = normalize_text("\n".join(current["lines"]))
        if content:
            sections.append({
                "heading": current["heading"],
                "level": current["level"],
                "content": content,
                "page_start": current["page_start"],
                "page_end": current["page_end"],
            })
        return sections

    @staticmethod
    def _clean_project_specific(content: str) -> str:
        value = normalize_text(content)
        patterns = [
            r"[\u4e00-\u9fffA-Za-z0-9（）()·—-]{4,80}(?:建设|改扩建|施工|工程)项目",
            r"[\u4e00-\u9fffA-Za-z0-9（）()·—-]{4,80}(?:工程|标段)",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "[项目名称]", value)
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系电话]", value)
        return value

    @staticmethod
    def _classify_unit(title: str, content: str) -> str:
        text = f"{title} {content[:1000]}"
        mappings = [
            (("工艺", "施工方法", "施工流程"), "construction_method"),
            (("质量", "检验", "验收"), "quality_control"),
            (("安全", "危险源", "应急"), "safety_measure"),
            (("进度", "工期", "横道图"), "schedule_plan"),
            (("资源", "人员", "机械", "材料"), "resource_plan"),
            (("组织架构", "组织机构"), "organization_chart"),
            (("流程图",), "process_flow"),
            (("总平面", "平面布置"), "site_layout"),
            (("表格", "序号"), "table_template"),
        ]
        for keywords, unit_type in mappings:
            if any(keyword in text for keyword in keywords):
                return unit_type
        return "management_measure"

    @staticmethod
    def _tags(title: str, content: str, industry: str, unit_type: str) -> list[str]:
        candidates = [industry, unit_type]
        for keyword in ["基坑", "钢筋", "模板", "混凝土", "防水", "机电", "装饰", "绿色施工", "BIM", "冬雨季"]:
            if keyword in title or keyword in content:
                candidates.append(keyword)
        return list(dict.fromkeys(candidates))

    def list_documents(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        with self.db.connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM standard_documents").fetchone()[0])
            rows = conn.execute(
                """
                SELECT d.*, s.relative_path, s.industry, s.file_name,
                    (SELECT COUNT(*) FROM document_sections ds WHERE ds.document_id=d.id) AS section_count
                FROM standard_documents d JOIN source_files s ON s.id=d.source_id
                ORDER BY d.id DESC LIMIT ? OFFSET ?
                """,
                (max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def list_units(self, status: str = "", unit_type: str = "", query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("u.status=?")
            params.append(status)
        if unit_type:
            clauses.append("u.unit_type=?")
            params.append(unit_type)
        if query:
            clauses.append("(u.title LIKE ? OR u.cleaned_content LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT u.*,
                    (SELECT COUNT(*) FROM knowledge_unit_sources us WHERE us.unit_id=u.id) AS source_count,
                    (SELECT MAX(version_no) FROM knowledge_versions v WHERE v.unit_id=u.id) AS latest_version
                FROM knowledge_units u {where} ORDER BY u.updated_at DESC LIMIT ?
                """,
                [*params, max(1, min(limit, 500))],
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["tags"] = parse_json(item.pop("tags_json", "[]"), [])
        return items

    def cluster_units(self, limit: int = 2000) -> dict[str, Any]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id,title,industry,unit_type FROM knowledge_units ORDER BY id LIMIT ?",
                (max(1, min(limit, 10000)),),
            ).fetchall()
            clusters: set[int] = set()
            for row in rows:
                title_key = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(row["title"]))[:18]
                cluster_key = content_hash(f"{row['industry']}|{row['unit_type']}|{title_key}")[:24]
                existing = conn.execute("SELECT id FROM knowledge_clusters WHERE cluster_key=?", (cluster_key,)).fetchone()
                if existing:
                    cluster_id = int(existing[0])
                else:
                    cursor = conn.execute(
                        "INSERT INTO knowledge_clusters(cluster_key,title,industry,unit_type) VALUES (?,?,?,?)",
                        (cluster_key, row["title"], row["industry"], row["unit_type"]),
                    )
                    cluster_id = int(cursor.lastrowid)
                conn.execute("UPDATE knowledge_units SET cluster_id=? WHERE id=?", (cluster_id, row["id"]))
                clusters.add(cluster_id)
        return {"units": len(rows), "clusters": len(clusters)}

    def get_unit(self, unit_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM knowledge_units WHERE id=?", (unit_id,)).fetchone()
            if not row:
                raise KeyError("知识单元不存在")
            payload = dict(row)
            payload["tags"] = parse_json(payload.pop("tags_json", "[]"), [])
            payload["versions"] = [dict(item) for item in conn.execute("SELECT * FROM knowledge_versions WHERE unit_id=? ORDER BY version_no DESC", (unit_id,))]
            payload["sources"] = [dict(item) for item in conn.execute(
                """
                SELECT us.*, s.relative_path, s.file_name, ds.heading
                FROM knowledge_unit_sources us JOIN source_files s ON s.id=us.source_id
                LEFT JOIN document_sections ds ON ds.id=us.section_id WHERE us.unit_id=?
                """,
                (unit_id,),
            )]
            payload["reviews"] = [dict(item) for item in conn.execute("SELECT * FROM knowledge_reviews WHERE unit_id=? ORDER BY id DESC", (unit_id,))]
            payload["publications"] = [dict(item) for item in conn.execute("SELECT * FROM knowledge_publications WHERE unit_id=? ORDER BY publication_version DESC", (unit_id,))]
        return payload

    def rewrite_unit(self, unit_id: int, related_unit_ids: Iterable[int] = ()) -> dict[str, Any]:
        unit = self.get_unit(unit_id)
        related = [self.get_unit(int(value)) for value in related_unit_ids if int(value) != unit_id]
        source_material = "\n\n".join(
            f"## {item['title']}\n{item['cleaned_content']}" for item in [unit, *related]
        )
        prompt = (
            "请将以下历史技术标内容重构为可复用知识。删除具体项目、客户、地域、人员、设备数量和未经来源确认的承诺；"
            "保留可验证的施工逻辑、工艺步骤、质量检查、安全措施和验收逻辑。输出JSON："
            '{"title":"...","content":"Markdown正文","summary":"...","tags":["..."]}。\n\n'
            f"资料：\n{source_material[:30000]}"
        )
        result = self.llm.generate("你是建设工程技术标知识工程专家。不得编造参数，不得把示意内容写成现场事实。", prompt)
        payload = self.llm.json_payload(result.get("content", "")) if result.get("content") else None
        content = normalize_text(str(payload.get("content", ""))) if payload else unit["cleaned_content"]
        title = str(payload.get("title") or unit["title"]) if payload else unit["title"]
        summary = str(payload.get("summary") or content[:200]) if payload else content[:200]
        tags = payload.get("tags") if payload and isinstance(payload.get("tags"), list) else unit["tags"]
        with self.db.connect() as conn:
            version_no = int(conn.execute("SELECT COALESCE(MAX(version_no),0)+1 FROM knowledge_versions WHERE unit_id=?", (unit_id,)).fetchone()[0])
            digest = content_hash(content)
            cursor = conn.execute(
                "INSERT INTO knowledge_versions(unit_id,version_no,content,summary,origin,model,content_hash,status) VALUES (?,?,?,?,?,?,?,'review_required')",
                (unit_id, version_no, content, summary, "llm_rewrite" if result.get("content") else "local_rewrite", result.get("model"), digest),
            )
            version_id = int(cursor.lastrowid)
            conn.execute(
                "UPDATE knowledge_units SET title=?, cleaned_content=?, tags_json=?, status='review_required', content_fingerprint=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title, json.dumps(tags, ensure_ascii=False), digest, unit_id),
            )
        draft_path = self.settings.knowledge_directories["drafts"] / f"{unit_id:07d}" / f"v{version_no}.md"
        write_text_atomic(draft_path, content)
        return {"unit_id": unit_id, "version_id": version_id, "version_no": version_no, "content": content, "model": result.get("model"), "error": result.get("error", "")}

    def review_unit(self, unit_id: int, version_id: int, action: str, reviewer: str, notes: str = "") -> dict[str, Any]:
        if action not in {"approve", "reject"}:
            raise ValueError("action必须为approve或reject")
        if not reviewer.strip():
            raise ValueError("审核人不能为空")
        status = "approved" if action == "approve" else "rejected"
        with self.db.connect() as conn:
            version = conn.execute("SELECT * FROM knowledge_versions WHERE id=? AND unit_id=?", (version_id, unit_id)).fetchone()
            if not version:
                raise KeyError("知识版本不存在")
            conn.execute(
                "INSERT INTO knowledge_reviews(unit_id,version_id,action,reviewer,notes) VALUES (?,?,?,?,?)",
                (unit_id, version_id, action, reviewer.strip(), notes),
            )
            conn.execute("UPDATE knowledge_versions SET status=? WHERE id=?", (status, version_id))
            conn.execute("UPDATE knowledge_units SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, unit_id))
        review_path = self.settings.knowledge_directories["reviews"] / f"{unit_id:07d}.jsonl"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        with review_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"unit_id": unit_id, "version_id": version_id, "action": action, "reviewer": reviewer, "notes": notes}, ensure_ascii=False) + "\n")
        return {"unit_id": unit_id, "version_id": version_id, "status": status}

    def publish_unit(self, unit_id: int, version_id: int, publisher: str) -> dict[str, Any]:
        if not publisher.strip():
            raise ValueError("发布人不能为空")
        with self.db.connect() as conn:
            version = conn.execute(
                "SELECT v.*,u.title,u.tags_json,u.industry,u.unit_type,u.unit_key FROM knowledge_versions v JOIN knowledge_units u ON u.id=v.unit_id WHERE v.id=? AND v.unit_id=?",
                (version_id, unit_id),
            ).fetchone()
            if not version:
                raise KeyError("知识版本不存在")
            version = dict(version)
            if version["status"] != "approved":
                raise ValueError("只有审核通过的版本才能发布")
            publication_version = int(conn.execute("SELECT COALESCE(MAX(publication_version),0)+1 FROM knowledge_publications WHERE unit_id=?", (unit_id,)).fetchone()[0])
            conn.execute("UPDATE knowledge_publications SET status='retired', retired_at=CURRENT_TIMESTAMP WHERE unit_id=? AND status='published'", (unit_id,))
            publication_path = self.settings.knowledge_directories["published"] / f"{unit_id:07d}" / f"v{publication_version}.md"
            frontmatter = (
                "---\n"
                f"unit_id: {unit_id}\n"
                f"unit_key: {version['unit_key']}\n"
                f"version: {publication_version}\n"
                f"industry: {version['industry'] or '通用'}\n"
                f"unit_type: {version['unit_type']}\n"
                f"content_hash: {version['content_hash']}\n"
                "---\n\n"
            )
            write_text_atomic(publication_path, frontmatter + version["content"])
            cursor = conn.execute(
                "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,status,published_by,file_path,content_hash) VALUES (?,?,?,'published',?,?,?)",
                (unit_id, version_id, publication_version, publisher.strip(), str(publication_path), version["content_hash"]),
            )
            publication_id = int(cursor.lastrowid)
            conn.execute("DELETE FROM published_units_fts WHERE unit_id=?", (unit_id,))
            conn.execute(
                "INSERT INTO published_units_fts(unit_id,title,content,tags,industry,unit_type) VALUES (?,?,?,?,?,?)",
                (unit_id, version["title"], version["content"], version["tags_json"], version["industry"] or "通用", version["unit_type"]),
            )
            conn.execute("UPDATE knowledge_units SET status='published', updated_at=CURRENT_TIMESTAMP WHERE id=?", (unit_id,))
        return {"publication_id": publication_id, "unit_id": unit_id, "version": publication_version, "file_path": str(publication_path)}

    def retire_publication(self, publication_id: int, reviewer: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            publication = conn.execute("SELECT * FROM knowledge_publications WHERE id=?", (publication_id,)).fetchone()
            if not publication:
                raise KeyError("发布记录不存在")
            unit_id = int(publication["unit_id"])
            conn.execute("UPDATE knowledge_publications SET status='retired', retired_at=CURRENT_TIMESTAMP WHERE id=?", (publication_id,))
            conn.execute("DELETE FROM published_units_fts WHERE unit_id=?", (unit_id,))
            conn.execute("UPDATE knowledge_units SET status='approved', updated_at=CURRENT_TIMESTAMP WHERE id=?", (unit_id,))
            version_id = int(publication["version_id"])
            conn.execute(
                "INSERT INTO knowledge_reviews(unit_id,version_id,action,reviewer,notes) VALUES (?,?, 'retire', ?, '停用发布版本')",
                (unit_id, version_id, reviewer or "系统管理员"),
            )
        return {"publication_id": publication_id, "status": "retired"}

    def restore_publication(self, publication_id: int, reviewer: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            publication = conn.execute(
                """
                SELECT p.*,u.title,u.tags_json,u.industry,u.unit_type,v.content
                FROM knowledge_publications p JOIN knowledge_units u ON u.id=p.unit_id
                JOIN knowledge_versions v ON v.id=p.version_id WHERE p.id=?
                """,
                (publication_id,),
            ).fetchone()
            if not publication:
                raise KeyError("发布记录不存在")
            publication = dict(publication)
            unit_id = int(publication["unit_id"])
            conn.execute("UPDATE knowledge_publications SET status='retired',retired_at=CURRENT_TIMESTAMP WHERE unit_id=? AND status='published'", (unit_id,))
            conn.execute("UPDATE knowledge_publications SET status='published',retired_at=NULL WHERE id=?", (publication_id,))
            conn.execute("DELETE FROM published_units_fts WHERE unit_id=?", (unit_id,))
            conn.execute(
                "INSERT INTO published_units_fts(unit_id,title,content,tags,industry,unit_type) VALUES (?,?,?,?,?,?)",
                (unit_id, publication["title"], publication["content"], publication["tags_json"], publication["industry"] or "通用", publication["unit_type"]),
            )
            conn.execute("UPDATE knowledge_units SET status='published',updated_at=CURRENT_TIMESTAMP WHERE id=?", (unit_id,))
            conn.execute(
                "INSERT INTO knowledge_reviews(unit_id,version_id,action,reviewer,notes) VALUES (?,?, 'restore', ?, '恢复历史发布版本')",
                (unit_id, publication["version_id"], reviewer or "系统管理员"),
            )
        return {"publication_id": publication_id, "unit_id": unit_id, "status": "published"}

    def list_publications(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,u.title,u.unit_type,u.industry,s.file_name AS source_name
                FROM knowledge_publications p JOIN knowledge_units u ON u.id=p.unit_id
                LEFT JOIN knowledge_unit_sources us ON us.unit_id=u.id
                LEFT JOIN source_files s ON s.id=us.source_id
                ORDER BY p.id DESC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, industry: str = "", unit_type: str = "", limit: int = 12) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        domain_terms = [
            value for value in ["施工", "工艺", "质量", "安全", "进度", "工期", "平面", "资源", "人员", "机械", "材料", "重点", "难点", "技术", "管理", "基坑", "防水", "混凝土", "钢筋", "模板"]
            if value in query
        ]
        lexical_terms = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,8}", query)
        terms = list(dict.fromkeys([*domain_terms, *lexical_terms]))[:10]
        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms) or query
        filters: list[str] = []
        params: list[Any] = [match_query]
        if industry:
            filters.append("f.industry=?")
            params.append(industry)
        if unit_type:
            filters.append("f.unit_type=?")
            params.append(unit_type)
        where = f"AND {' AND '.join(filters)}" if filters else ""
        with self.db.connect() as conn:
            try:
                rows = conn.execute(
                    f"""
                    SELECT p.id AS publication_id,p.publication_version,p.file_path,p.content_hash,
                        u.id AS unit_id,u.title,u.unit_type,u.industry,v.content,
                        bm25(published_units_fts) AS rank
                    FROM published_units_fts f
                    JOIN knowledge_units u ON u.id=CAST(f.unit_id AS INTEGER)
                    JOIN knowledge_publications p ON p.unit_id=u.id AND p.status='published'
                    JOIN knowledge_versions v ON v.id=p.version_id
                    WHERE published_units_fts MATCH ? {where}
                    ORDER BY rank LIMIT ?
                    """,
                    [*params, max(1, min(limit, 50))],
                ).fetchall()
            except Exception:
                rows = []
            like_terms = terms or [query]
            like_clauses = " OR ".join("(u.title LIKE ? OR v.content LIKE ?)" for _ in like_terms)
            like_params: list[Any] = []
            for term in like_terms:
                like_params.extend([f"%{term}%", f"%{term}%"])
            extra_clauses = ["p.status='published'", f"({like_clauses})"]
            if industry:
                extra_clauses.append("u.industry=?")
                like_params.append(industry)
            if unit_type:
                extra_clauses.append("u.unit_type=?")
                like_params.append(unit_type)
            like_rows = conn.execute(
                f"""
                SELECT p.id AS publication_id,p.publication_version,p.file_path,p.content_hash,
                    u.id AS unit_id,u.title,u.unit_type,u.industry,v.content,0 AS rank
                FROM knowledge_publications p JOIN knowledge_units u ON u.id=p.unit_id
                JOIN knowledge_versions v ON v.id=p.version_id
                WHERE {' AND '.join(extra_clauses)}
                ORDER BY p.id DESC LIMIT ?
                """,
                [*like_params, max(1, min(limit * 2, 100))],
            ).fetchall()
            merged_rows = [*rows, *like_rows]
            items: list[dict[str, Any]] = []
            seen_units: set[int] = set()
            for row in merged_rows:
                item = dict(row)
                unit_id = int(item["unit_id"])
                if unit_id in seen_units:
                    continue
                seen_units.add(unit_id)
                item["sources"] = [dict(value) for value in conn.execute(
                    """
                    SELECT s.id,s.file_name,s.relative_path,us.page_start,us.excerpt
                    FROM knowledge_unit_sources us JOIN source_files s ON s.id=us.source_id WHERE us.unit_id=?
                    """,
                    (item["unit_id"],),
                )]
                items.append(item)
                if len(items) >= max(1, min(limit, 50)):
                    break
        return items

    def metrics(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            counts = {
                "sources": int(conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]),
                "duplicates": int(conn.execute("SELECT COUNT(*) FROM source_files WHERE duplicate_of IS NOT NULL").fetchone()[0]),
                "jobs_pending": int(conn.execute("SELECT COUNT(*) FROM processing_jobs WHERE status='pending'").fetchone()[0]),
                "jobs_running": int(conn.execute("SELECT COUNT(*) FROM processing_jobs WHERE status='running'").fetchone()[0]),
                "jobs_failed": int(conn.execute("SELECT COUNT(*) FROM processing_jobs WHERE status='failed'").fetchone()[0]),
                "documents": int(conn.execute("SELECT COUNT(*) FROM standard_documents").fetchone()[0]),
                "units": int(conn.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]),
                "review_pending": int(conn.execute("SELECT COUNT(*) FROM knowledge_units WHERE status='review_required'").fetchone()[0]),
                "published": int(conn.execute("SELECT COUNT(*) FROM knowledge_publications WHERE status='published'").fetchone()[0]),
            }
        counts["duplicate_rate"] = round(counts["duplicates"] / counts["sources"] * 100, 2) if counts["sources"] else 0
        counts["publication_rate"] = round(counts["published"] / counts["units"] * 100, 2) if counts["units"] else 0
        return counts

    def _write_unit_file(self, unit_id: int, payload: dict[str, Any]) -> None:
        write_json_atomic(self.settings.knowledge_directories["units"] / f"{unit_id:07d}.json", payload)
