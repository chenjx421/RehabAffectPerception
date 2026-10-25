"""Check PDF structure and assemble rendered-page contact sheets for visual QA."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
MEMBERSHIP = os.getenv("DEMO2_GUIDE_MEMBERSHIP") == "1"
NAME = "demo2_membership_guide_20260909" if MEMBERSHIP else "demo2_current_guide_20260909"
PDF = ROOT / "output/pdf" / ("RehabAffect_Demo2_手机号会员版全界面说明_20260909.pdf" if MEMBERSHIP else "RehabAffect_Demo2_全界面功能说明_20260909.pdf")
QA = ROOT / "tmp/pdfs" / NAME


def main():
    reader = PdfReader(PDF)
    manifest = json.loads((ROOT / "output/playwright" / NAME / "manifest.json").read_text(encoding="utf-8"))
    pages = sorted(QA.glob("page-*.png"))
    assert len(pages) == len(reader.pages) == len(manifest["pages"]) + 3
    assert all(len(page.extract_text()) > 100 for page in reader.pages)
    assert all(page.get("/Resources", {}).get("/XObject") for page in reader.pages[2:-1])
    assert len(reader.pages[1].get("/Annots", [])) == len(manifest["pages"])
    sheets = []
    for start in range(0, len(pages), 12):
        batch = pages[start:start + 12]
        sheet = Image.new("RGB", (1530, 1520), "#e7edf5")
        draw = ImageDraw.Draw(sheet)
        for index, file in enumerate(batch):
            x, y = 10 + (index % 3) * 510, 10 + (index // 3) * 380
            with Image.open(file) as im:
                im.thumbnail((500, 352))
                sheet.paste(im, (x, y + 20))
            draw.text((x, y + 3), f"PAGE {start + index + 1:02d}", fill="#1d406b")
        target = QA / f"contact-{start // 12 + 1:02d}.png"
        sheet.save(target)
        sheets.append(str(target))
    report = {
        "page_count": len(pages),
        "screenshot_count": len(manifest["pages"]),
        "clickable_contents_links": len(reader.pages[1].get("/Annots", [])),
        "all_screenshot_pages_have_images": True,
        "all_pages_have_searchable_text": True,
        "contact_sheets": sheets,
    }
    (QA / "structural_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
