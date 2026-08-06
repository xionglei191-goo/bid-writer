from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .docx_audit import attach_visual_render_audit, load_docx_audit
from .settings import QA_DIR


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _poppler(name: str) -> str:
    dependencies = Path(sys.executable).resolve().parents[1]
    candidate = dependencies / "native" / "poppler" / "Library" / "bin" / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"未找到{name}，无法执行PDF逐页检查")


def _render_with_word(docx_path: Path, pdf_path: Path) -> None:
    script = f"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$word=$null
$document=$null
try {{
  $word=New-Object -ComObject Word.Application
  $word.Visible=$false
  $word.DisplayAlerts=0
  $document=$word.Documents.Open({_powershell_literal(str(docx_path))},$false,$true)
  $document.Fields.Update() | Out-Null
  $document.ExportAsFixedFormat({_powershell_literal(str(pdf_path))},17)
}} finally {{
  if($document){{$document.Close($false)}}
  if($word){{$word.Quit()}}
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}}
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )
    if completed.returncode != 0 or not pdf_path.is_file():
        detail = (completed.stderr or completed.stdout or "Word导出PDF失败").strip()
        raise RuntimeError(detail)


def _page_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("L")
        width, height = image.size
        content = image.crop((0, int(height * 0.08), width, int(height * 0.92)))
        ink = content.point(lambda value: 255 if value < 245 else 0)
        ink_ratio = sum(ink.histogram()[1:]) / max(content.width * content.height, 1)
        bbox = ink.getbbox()
        margin = min(bbox[0], bbox[1], content.width - bbox[2], content.height - bbox[3]) if bbox else None
        return {
            "page": int(path.stem.rsplit("-", 1)[-1]),
            "content_ink_ratio": round(ink_ratio, 6),
            "blank": ink_ratio < 0.0006,
            "touches_edge": bool(margin is not None and margin < 2),
        }


def _contact_sheets(paths: list[Path], output_dir: Path) -> list[str]:
    from PIL import ImageDraw

    result: list[str] = []
    columns, rows = 4, 5
    cell_w, cell_h = 180, 270
    for offset in range(0, len(paths), columns * rows):
        canvas = Image.new("RGB", (columns * cell_w, rows * (cell_h + 20)), "#dbe3ea")
        draw = ImageDraw.Draw(canvas)
        for index, path in enumerate(paths[offset : offset + columns * rows]):
            row, column = divmod(index, columns)
            with Image.open(path) as source:
                thumb = ImageOps.contain(source.convert("RGB"), (cell_w - 10, cell_h - 10))
            x = column * cell_w + (cell_w - thumb.width) // 2
            y = row * (cell_h + 20) + 5
            canvas.paste(thumb, (x, y))
            draw.text((column * cell_w + 5, row * (cell_h + 20) + cell_h), f"P{int(path.stem.rsplit('-', 1)[-1])}", fill="#12263a")
        target = output_dir / f"contact_{offset // (columns * rows) + 1:02d}.jpg"
        canvas.save(target, quality=85)
        result.append(str(target))
    return result


def run_docx_visual_qa(tender_id: int, docx_path: str | Path) -> dict[str, Any]:
    audit = load_docx_audit(tender_id)
    if not audit or not audit.get("ready"):
        raise ValueError("DOCX结构审计未通过，不能执行视觉预检")
    source = Path(docx_path).resolve()
    output_dir = QA_DIR / "docx" / f"project_{tender_id}_render"
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("page-*.png"):
        old.unlink()
    for old in output_dir.glob("contact_*.jpg"):
        old.unlink()
    pdf_path = output_dir / f"project_{tender_id}_preflight.pdf"
    _render_with_word(source, pdf_path)
    prefix = output_dir / "page"
    completed = subprocess.run(
        [_poppler("pdftoppm"), "-png", "-r", "72", str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "PDF逐页渲染失败").strip())
    paths = sorted(output_dir.glob("page-*.png"), key=lambda item: int(item.stem.rsplit("-", 1)[-1]))
    metrics = [_page_metrics(path) for path in paths]
    blank_pages = [item["page"] for item in metrics if item["blank"]]
    edge_pages = [item["page"] for item in metrics if item["touches_edge"]]
    visual = {
        "ready": bool(paths) and not blank_pages and not edge_pages,
        "pdf_path": str(pdf_path),
        "contact_sheets": _contact_sheets(paths, output_dir),
        "metrics": {
            "pages": len(paths),
            "blank_pages": blank_pages,
            "edge_touch_pages": edge_pages,
        },
    }
    return attach_visual_render_audit(tender_id, visual)
