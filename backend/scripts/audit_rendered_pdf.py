from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat


def _page_number(path: Path) -> int:
    try:
        return int(path.stem.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def _page_metrics(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = source.convert("L")
        width, height = image.size
        ink = image.point(lambda value: 255 if value < 245 else 0)
        histogram = ink.histogram()
        ink_pixels = sum(histogram[1:])
        ink_ratio = ink_pixels / max(width * height, 1)
        bbox = ink.getbbox()
        edge_margin = None
        if bbox:
            edge_margin = min(bbox[0], bbox[1], width - bbox[2], height - bbox[3])
        return {
            "page": _page_number(path),
            "file": str(path),
            "width": width,
            "height": height,
            "ink_ratio": round(ink_ratio, 6),
            "blank": ink_ratio < 0.002,
            "edge_margin_px": edge_margin,
            "touches_edge": bool(edge_margin is not None and edge_margin < 3),
            "mean_luma": round(ImageStat.Stat(image).mean[0], 2),
        }


def _contact_sheets(paths: list[Path], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    thumb_width, thumb_height = 220, 310
    columns, rows = 4, 5
    sheets: list[str] = []
    for sheet_index in range(0, len(paths), columns * rows):
        batch = paths[sheet_index : sheet_index + columns * rows]
        canvas = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + 24)), "#dbe3ea")
        draw = ImageDraw.Draw(canvas)
        for index, path in enumerate(batch):
            row, column = divmod(index, columns)
            with Image.open(path) as source:
                thumb = ImageOps.contain(source.convert("RGB"), (thumb_width - 12, thumb_height - 12))
            x = column * thumb_width + (thumb_width - thumb.width) // 2
            y = row * (thumb_height + 24) + 6
            canvas.paste(thumb, (x, y))
            label = f"Page {_page_number(path)}"
            draw.text((column * thumb_width + 8, row * (thumb_height + 24) + thumb_height + 3), label, fill="#12263a")
        output = output_dir / f"contact_{sheet_index // (columns * rows) + 1:02d}.jpg"
        canvas.save(output, quality=88)
        sheets.append(str(output))
    return sheets


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: audit_rendered_pdf.py <page-image-dir> [output-json]")
    page_dir = Path(sys.argv[1])
    paths = sorted(page_dir.glob("page-*.png"), key=_page_number)
    if not paths:
        raise SystemExit(f"No rendered pages found in {page_dir}")
    pages = [_page_metrics(path) for path in paths]
    sheets = _contact_sheets(paths, page_dir / "contact_sheets")
    report = {
        "pages": len(pages),
        "blank_pages": [item["page"] for item in pages if item["blank"]],
        "edge_touch_pages": [item["page"] for item in pages if item["touches_edge"]],
        "contact_sheets": sheets,
        "page_metrics": pages,
    }
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else page_dir / "render_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("pages", "blank_pages", "edge_touch_pages", "contact_sheets")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
