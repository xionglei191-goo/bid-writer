from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader


def ink_ratio(image: Image.Image) -> float:
    gray = image.convert("L")
    histogram = gray.histogram()
    dark = sum(histogram[:245])
    return dark / (gray.width * gray.height)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("page_dir", type=Path)
    args = parser.parse_args()
    reader = PdfReader(args.pdf)
    pages = sorted(args.page_dir.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
    blank_pages = []
    low_ink_pages = []
    edge_ink_pages = []
    text_empty_pages = []
    page_sizes = set()
    ratios = []
    for index, page_path in enumerate(pages, start=1):
        with Image.open(page_path) as image:
            image = image.convert("RGB")
            page_sizes.add(image.size)
            ratio = ink_ratio(image)
            ratios.append(ratio)
            if ratio < 0.002:
                blank_pages.append(index)
            elif ratio < 0.01:
                low_ink_pages.append(index)
            border = max(3, round(min(image.size) * 0.006))
            edge = Image.new("RGB", image.size, "white")
            edge.paste(image.crop((0, 0, image.width, border)), (0, 0))
            edge.paste(image.crop((0, image.height - border, image.width, image.height)), (0, image.height - border))
            edge.paste(image.crop((0, 0, border, image.height)), (0, 0))
            edge.paste(image.crop((image.width - border, 0, image.width, image.height)), (image.width - border, 0))
            if ink_ratio(edge) > 0.00012:
                edge_ink_pages.append(index)
        if index <= len(reader.pages) and not (reader.pages[index - 1].extract_text() or "").strip():
            text_empty_pages.append(index)
    report = {
        "pdf_pages": len(reader.pages),
        "png_pages": len(pages),
        "page_sizes": sorted([list(size) for size in page_sizes]),
        "blank_pages": blank_pages,
        "low_ink_pages": low_ink_pages,
        "edge_ink_pages": edge_ink_pages,
        "text_empty_pages": text_empty_pages,
        "min_ink_ratio": round(min(ratios), 6) if ratios else 0,
        "max_ink_ratio": round(max(ratios), 6) if ratios else 0,
        "ready": bool(pages) and len(reader.pages) == len(pages) and not blank_pages,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
