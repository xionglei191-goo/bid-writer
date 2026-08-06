from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .db import connect, init_db, reset_db
from .settings import KB_ROOT, MANIFEST_PATH, PROJECT_ROOT, SECTIONS_PATH
from .text_utils import chunk_text, parse_markdown_sections, read_text


def _int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value)))
    except ValueError:
        return None


def _load_manifest(limit_documents: int | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with MANIFEST_PATH.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            if not row.get("markdown_path"):
                continue
            rows.append(row)
            if limit_documents and len(rows) >= limit_documents:
                break
    return rows


def _load_sections(source_paths: set[str]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {source: [] for source in source_paths}
    if not SECTIONS_PATH.exists():
        return result
    with SECTIONS_PATH.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            source = row.get("source_path", "")
            if source in result:
                result[source].append(row)
    return result


def _resolve_markdown_path(markdown_path: str) -> Path:
    md_path = Path(markdown_path)
    if md_path.is_absolute():
        return md_path
    project_path = PROJECT_ROOT / md_path
    if project_path.exists():
        return project_path
    return KB_ROOT / md_path


def _clear_document_index(conn, document_id: int) -> None:
    chunk_ids = [int(row[0]) for row in conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()]
    if chunk_ids:
        placeholders = ",".join("?" for _ in chunk_ids)
        conn.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({placeholders})", chunk_ids)
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM sections WHERE document_id = ?", (document_id,))


def index_manifest_row(
    conn,
    row: dict[str, str],
    *,
    section_rows: list[dict[str, str]] | None = None,
    max_chunks_per_document: int = 80,
) -> dict[str, int]:
    md_rel = row.get("markdown_path", "")
    md_path = _resolve_markdown_path(md_rel)
    if not md_path.exists():
        return {"documents": 0, "sections": 0, "chunks": 0, "missing_markdown": 1}

    cur = conn.execute(
        """
        INSERT INTO documents (
            source_path, source_format, markdown_path, output_dir, processing_action,
            duplicate_policy, top_category, top_company, top_project,
            page_count, section_count, char_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            markdown_path=excluded.markdown_path,
            output_dir=excluded.output_dir,
            processing_action=excluded.processing_action,
            duplicate_policy=excluded.duplicate_policy,
            top_category=excluded.top_category,
            top_company=excluded.top_company,
            top_project=excluded.top_project,
            page_count=excluded.page_count,
            section_count=excluded.section_count,
            char_count=excluded.char_count,
            imported_at=CURRENT_TIMESTAMP
        RETURNING id
        """,
        (
            row.get("source_path", ""),
            row.get("source_format", ""),
            md_rel,
            row.get("output_dir", ""),
            row.get("processing_action", ""),
            row.get("duplicate_policy", ""),
            row.get("top_category", ""),
            row.get("top_company", ""),
            row.get("top_project", ""),
            _int(row.get("page_count")),
            _int(row.get("section_count")),
            _int(row.get("char_count")),
        ),
    )
    document_id = int(cur.fetchone()[0])
    _clear_document_index(conn, document_id)

    counters = {"documents": 1, "sections": 0, "chunks": 0, "missing_markdown": 0}
    source = row.get("source_path", "")
    section_id_by_heading: dict[str, int] = {}
    for section in section_rows or []:
        cur = conn.execute(
            """
            INSERT INTO sections (
                document_id, source_path, markdown_path, heading_order,
                heading_level, heading_text, page_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                source,
                md_rel,
                _int(section.get("heading_order")),
                _int(section.get("heading_level")),
                section.get("heading_text", ""),
                section.get("page_number", ""),
            ),
        )
        section_id = int(cur.lastrowid)
        section_id_by_heading.setdefault(section.get("heading_text", ""), section_id)
        counters["sections"] += 1

    markdown = read_text(md_path)
    default_heading = Path(source).stem
    parsed_sections = parse_markdown_sections(markdown, default_heading=default_heading)
    chunk_index = 0
    for parsed in parsed_sections:
        heading = str(parsed["heading_text"])
        section_id = section_id_by_heading.get(heading)
        if section_id is None:
            cur = conn.execute(
                """
                INSERT INTO sections (
                    document_id, source_path, markdown_path, heading_order,
                    heading_level, heading_text, page_number
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    source,
                    md_rel,
                    len(section_id_by_heading) + 1,
                    _int(parsed.get("heading_level")),
                    heading,
                    "",
                ),
            )
            section_id = int(cur.lastrowid)
            section_id_by_heading.setdefault(heading, section_id)
            counters["sections"] += 1
        for content in chunk_text(str(parsed["content"])):
            if max_chunks_per_document and chunk_index >= max_chunks_per_document:
                break
            chunk_index += 1
            cur = conn.execute(
                """
                INSERT INTO chunks (
                    document_id, section_id, source_path, markdown_path,
                    top_category, top_company, top_project, heading_text,
                    chunk_index, content
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    section_id,
                    source,
                    md_rel,
                    row.get("top_category", ""),
                    row.get("top_company", ""),
                    row.get("top_project", ""),
                    heading,
                    chunk_index,
                    content,
                ),
            )
            chunk_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO chunks_fts (
                    rowid, content, heading_text, source_path, top_category, top_project
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    content,
                    heading,
                    source,
                    row.get("top_category", ""),
                    row.get("top_project", ""),
                ),
            )
            counters["chunks"] += 1
        if max_chunks_per_document and chunk_index >= max_chunks_per_document:
            break
    return counters


def import_knowledge_base(
    reset: bool = False,
    limit_documents: int | None = None,
    max_chunks_per_document: int = 80,
    use_sections_csv: bool = False,
) -> dict[str, int]:
    conn = connect()
    if reset:
        reset_db(conn)
    else:
        init_db(conn)

    manifest_rows = _load_manifest(limit_documents)
    source_paths = {row["source_path"] for row in manifest_rows}
    section_rows = _load_sections(source_paths) if use_sections_csv else {}

    counters = {"documents": 0, "sections": 0, "chunks": 0, "missing_markdown": 0}
    for document_index, row in enumerate(manifest_rows, 1):
        with conn:
            row_counters = index_manifest_row(
                conn,
                row,
                section_rows=section_rows.get(row.get("source_path", ""), []),
                max_chunks_per_document=max_chunks_per_document,
            )
            for key, value in row_counters.items():
                counters[key] += value
        if document_index % 50 == 0:
            print(
                {
                    "processed": document_index,
                    "documents": counters["documents"],
                    "sections": counters["sections"],
                    "chunks": counters["chunks"],
                    "missing_markdown": counters["missing_markdown"],
                },
                flush=True,
            )
    conn.close()
    return counters


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--limit-documents", type=int, default=0)
    parser.add_argument("--max-chunks-per-document", type=int, default=80)
    parser.add_argument("--use-sections-csv", action="store_true")
    args = parser.parse_args()
    counters = import_knowledge_base(
        reset=args.reset,
        limit_documents=args.limit_documents or None,
        max_chunks_per_document=args.max_chunks_per_document,
        use_sections_csv=args.use_sections_csv,
    )
    print(counters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
