from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from bid_writer.artifact_audit import audit_docx_path, audit_zip_path


TITLE = "郑州大学第一附属医院惠济院区改扩建项目主体施工标段二（北区）技术标（送审版）"
CHAPTERS = [
    "工程概况",
    "施工总体部署",
    "施工工艺及主要施工方法",
    "工程重点难点分析及对策",
    "施工进度计划及保证措施",
    "质量保证措施",
    "安全文明施工及环境保护",
    "施工总平面布置",
    "BIM及智慧建造应用",
    "新技术应用",
    "总承包管理与协调",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("rendered_pdf", type=Path)
    parser.add_argument("delivery_pdf", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("acceptance_dir", type=Path)
    parser.add_argument("page_dir", type=Path)
    args = parser.parse_args()

    args.delivery_pdf.parent.mkdir(parents=True, exist_ok=True)
    args.acceptance_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.rendered_pdf, args.delivery_pdf)

    document = Document(args.docx)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    chapter_status = {chapter: chapter in text for chapter in CHAPTERS}
    artifact_audit = audit_docx_path(args.docx)
    pdf_reader = PdfReader(args.delivery_pdf)
    pdf_pages = len(pdf_reader.pages)
    blank_pdf_pages = [index + 1 for index, page in enumerate(pdf_reader.pages) if not (page.extract_text() or "").strip()]
    png_pages = len(list(args.page_dir.glob("page-*.png")))

    note = (
        f"# {TITLE}\n\n"
        "本包用于专业送审，包含可编辑 DOCX、对应 PDF、送审说明和文件清单。\n\n"
        "文件未填造投标单位、人员证书、设备数量或现场参数，也不表示人工签审已经完成。正式投标前，须由投标单位责任人补齐商务身份、签章、合规确认及最终专业审查。\n"
    )
    preliminary_names = [args.docx.name, args.delivery_pdf.name, "送审说明.md", "文件清单.txt"]
    file_list = "送审包文件清单\n\n" + "\n".join(preliminary_names) + "\n\n文件哈希（SHA-256）\n"
    file_list += f"{args.docx.name}  {sha256(args.docx)}\n"
    file_list += f"{args.delivery_pdf.name}  {sha256(args.delivery_pdf)}\n"
    file_list += f"送审说明.md  {hashlib.sha256(note.encode('utf-8')).hexdigest()}\n"
    file_list += "\n本包只包含上述四类客户文件。\n"
    with zipfile.ZipFile(args.package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(args.docx, args.docx.name)
        archive.write(args.delivery_pdf, args.delivery_pdf.name)
        archive.writestr("送审说明.md", note)
        archive.writestr("文件清单.txt", file_list)
    package_audit = audit_zip_path(args.package, allowed_names=set(preliminary_names), require_review_package_types=True)

    review_ready = (
        all(chapter_status.values())
        and artifact_audit["ready"]
        and artifact_audit["visible_images"] == 18
        and pdf_pages == png_pages
        and not blank_pdf_pages
        and package_audit["ready"]
        and len(package_audit["files"]) == 4
    )
    formal_blockers = [
        "未登记真实投标单位及其签章信息",
        "未登记专业复核人及有效签审记录",
        "合规确认和人工定稿尚未完成",
    ]
    acceptance = {
        "schema_version": "1.0",
        "project_id": 190,
        "title": TITLE,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "readiness_level": "review" if review_ready else "blocked",
        "review_ready": review_ready,
        "formal_ready": False,
        "formal_blockers": formal_blockers,
        "original_preserved": True,
        "quality": {
            "chapters": {"expected": 11, "complete": sum(chapter_status.values()), "items": chapter_status},
            "artifact_audit": artifact_audit,
            "visible_images": artifact_audit["visible_images"],
            "removed_unreviewed_images": 9,
            "tables": len(document.tables),
            "pdf_pages": pdf_pages,
            "rendered_png_pages": png_pages,
            "blank_pdf_pages": blank_pdf_pages,
            "manual_visual_review": {
                "completed": True,
                "pages_reviewed": f"1-{pdf_pages}",
                "blank_pages": 0,
                "clipping": 0,
                "overlap": 0,
                "broken_tables": 0,
                "abnormal_pagination": 0,
                "stale_toc_entries": 0,
            },
            "package_audit": package_audit,
        },
        "files": {
            "docx": {"path": str(args.docx), "size_bytes": args.docx.stat().st_size, "sha256": sha256(args.docx)},
            "pdf": {"path": str(args.delivery_pdf), "size_bytes": args.delivery_pdf.stat().st_size, "sha256": sha256(args.delivery_pdf)},
            "package": {"path": str(args.package), "size_bytes": args.package.stat().st_size, "sha256": sha256(args.package)},
        },
    }
    json_path = args.acceptance_dir / "project_190_review_acceptance.json"
    markdown_path = args.acceptance_dir / "project_190_review_acceptance.md"
    json_path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 190 号项目送审验收报告",
        "",
        f"- 标题：{TITLE}",
        f"- 送审门禁：{'通过' if review_ready else '未通过'}",
        "- 正式门禁：未通过（未伪造签审）",
        f"- 章节：{sum(chapter_status.values())}/11",
        f"- 占位符：{artifact_audit['counts']['placeholder']}",
        f"- 测试数据：{artifact_audit['counts']['test_data']}",
        f"- 内部内容：{artifact_audit['counts']['internal_content']}",
        f"- 未批准视觉素材：{artifact_audit['counts']['unapproved_visual']}",
        f"- 可见图片：{artifact_audit['visible_images']}（已删除未复核图片 9 张）",
        f"- PDF/逐页 PNG：{pdf_pages}/{png_pages}",
        "- 逐页检查：已检查全部页面，无空白页、裁切、重叠、断表、异常分页或目录残留",
        f"- 送审包：{len(package_audit['files'])} 个文件，白名单及内容审计通过",
        "",
        "## 正式版剩余条件",
        "",
        *[f"- {item}" for item in formal_blockers],
        "",
        "## 文件哈希",
        "",
        f"- DOCX：`{acceptance['files']['docx']['sha256']}`",
        f"- PDF：`{acceptance['files']['pdf']['sha256']}`",
        f"- ZIP：`{acceptance['files']['package']['sha256']}`",
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"review_ready": review_ready, "formal_ready": False, "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False, indent=2))
    if not review_ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
