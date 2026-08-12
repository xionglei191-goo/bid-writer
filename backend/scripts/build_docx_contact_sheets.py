from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("page_dir", type=Path)
    parser.add_argument("--per-sheet", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=520)
    args = parser.parse_args()
    pages = sorted(args.page_dir.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
    if not pages:
        raise ValueError("没有找到逐页 PNG")
    columns = 2
    rows = math.ceil(args.per_sheet / columns)
    gap = 24
    label_height = 34
    sample = Image.open(pages[0])
    thumb_height = round(sample.height * args.thumb_width / sample.width)
    sheet_width = columns * args.thumb_width + (columns + 1) * gap
    sheet_height = rows * (thumb_height + label_height) + (rows + 1) * gap
    font = ImageFont.load_default(size=22)
    sheet_paths = []
    for sheet_index in range(0, len(pages), args.per_sheet):
        batch = pages[sheet_index : sheet_index + args.per_sheet]
        sheet = Image.new("RGB", (sheet_width, sheet_height), "#d7d7d7")
        draw = ImageDraw.Draw(sheet)
        for offset, page_path in enumerate(batch):
            row, column = divmod(offset, columns)
            x = gap + column * (args.thumb_width + gap)
            y = gap + row * (thumb_height + label_height + gap)
            with Image.open(page_path) as page:
                page = page.convert("RGB")
                page.thumbnail((args.thumb_width, thumb_height), Image.Resampling.LANCZOS)
                sheet.paste(page, (x, y + label_height))
            page_number = int(page_path.stem.split("-")[-1])
            draw.text((x, y), f"Page {page_number}", fill="black", font=font)
        start = int(batch[0].stem.split("-")[-1])
        end = int(batch[-1].stem.split("-")[-1])
        output = args.page_dir / f"contact-{start:03d}-{end:03d}.png"
        sheet.save(output, optimize=True)
        sheet_paths.append(output)
    print(f"pages={len(pages)} sheets={len(sheet_paths)}")


if __name__ == "__main__":
    main()
