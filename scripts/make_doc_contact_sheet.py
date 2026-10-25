from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output")
    parser.add_argument("--columns", type=int, default=4)
    args = parser.parse_args()

    pages = sorted(Path(args.input_dir).glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
    thumbs = []
    for page in pages:
        image = Image.open(page).convert("RGB")
        image.thumbnail((310, 405))
        thumbs.append((page, image.copy()))
    cell_width, cell_height = 330, 440
    rows = (len(thumbs) + args.columns - 1) // args.columns
    canvas = Image.new("RGB", (cell_width * args.columns, cell_height * rows), "#DDE3EA")
    draw = ImageDraw.Draw(canvas)
    for index, (path, image) in enumerate(thumbs):
        x = (index % args.columns) * cell_width + (cell_width - image.width) // 2
        y = (index // args.columns) * cell_height + 22
        canvas.paste(image, (x, y))
        draw.text((x, 4), path.stem, fill="#10233F")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    print(output.resolve())


if __name__ == "__main__":
    main()
