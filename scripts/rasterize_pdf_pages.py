from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("output_dir")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    scale = args.dpi / 72
    matrix = fitz.Matrix(scale, scale)
    for index, page in enumerate(document, start=1):
        output = output_dir / f"page-{index}.png"
        page.get_pixmap(matrix=matrix, alpha=False).save(output)
        print(output)
    print(f"pages={len(document)}")


if __name__ == "__main__":
    main()
