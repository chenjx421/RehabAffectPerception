"""Readable Chinese Word / PDF renderings of classroom and measurement reports.

The page and the md/json exports stay the source of truth; this module only
turns an already-authorized, already-redacted snapshot into a typeset document:
cover, table of contents, headings, tables and chart images. Report text never
carries Markdown or JSON syntax — every string passes through :func:`plain`.

Rendering is split into a neutral document model (list of blocks) and two
writers, so the classroom report and the single measurement report share the
same typesetting. python-docx is required for Word, reportlab for PDF; a
missing package raises :class:`RendererUnavailable` (HTTP 503
``report_renderer_unavailable``) instead of a generic 500.
"""
from __future__ import annotations

import glob
import io
import os
import re
import threading
from datetime import datetime
from typing import Any

from .demo2_ui_kit import BRAND_FULL_NAME

BOUNDARY_TEXT = ("本报告用于课堂教育支持复盘，不构成医学诊断、学生能力定级或教师绩效结论。"
                 "评分来自教师依量表复核与系统按公开口径计算的参考分，权重与 6 分参考线为试行口径，尚待校方确认；"
                 "视频处理不自动识别情绪，也不替代教师判断。报告内容仅限本校教学团队使用，请勿外传含学生姓名的副本。")
FORMATS = ("docx", "pdf")
CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
PRIMARY = (31, 95, 191)
PRIMARY_DEEP = (18, 63, 134)
SYSTEM_COLOR = (79, 195, 247)
MUTED = (91, 107, 128)
GRID = (227, 234, 243)
WARN = (212, 138, 16)
_MARKUP = str.maketrans({"#": "＃", "*": "×", "|": "／", "`": "'", "{": "（", "}": "）", "<": "＜", ">": "＞"})
_FONT_LOCK = threading.Lock()
_PDF_FONT: dict[str, str] = {}
_PIL_FONT_PATH: list[str | None] = []

CJK_FONT_ENV = "REHAB_REPORT_CJK_FONT"
_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-sans-cjk-ttc-fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    # TencentOS/OpenCloudOS: google-droid-sans-fonts (TrueType; Noto CJK is CFF and cannot be embedded by reportlab).
    "/usr/share/fonts/google-droid-fonts/DroidSansFallback.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


class RendererUnavailable(RuntimeError):
    """A document library is missing; callers map this to 503 report_renderer_unavailable."""

    def __init__(self, fmt: str, package: str):
        super().__init__(f"{fmt} renderer requires {package}")
        self.fmt, self.package = fmt, package


class RenderFailed(RuntimeError):
    """Rendering raised unexpectedly; callers map this to 500 report_render_failed."""


# -- text helpers -----------------------------------------------------------------

def plain(value: Any) -> str:
    """Display text without Markdown / JSON markup characters or control characters."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    text = str(value)
    text = text.replace("```", "").replace("**", "").replace("---", "—")
    text = text.translate(_MARKUP)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def number(value: Any, digits: int = 2) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    text = f"{float(value):.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def mmss(seconds: Any) -> str:
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "—"
    return f"{total // 60:02d}:{total % 60:02d}"


def date_text(value: Any) -> str:
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", text)
    if not match:
        return plain(text) or "—"
    return match.group(1) + (f" {match.group(2)}" if match.group(2) else "")


def sentences(text: Any, limit: int = 0) -> list[str]:
    """Split long narrative into readable paragraphs at sentence ends."""
    clean = plain(text)
    if not clean:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[。！？])", clean) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) + len(part) < 90:
            merged[-1] += part
        else:
            merged.append(part)
    return merged[:limit] if limit else merged


def safe_filename_part(value: Any, fallback: str, limit: int = 40) -> str:
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "", str(value or "")).strip()
    text = re.sub(r"\s+", "_", text)[:limit].strip("._")
    return text or fallback


# -- document model -----------------------------------------------------------------

class DocumentModel:
    """Neutral list of blocks rendered identically by the Word and PDF writers."""

    def __init__(self, title: str, header: str, footer: str):
        self.title, self.header, self.footer = plain(title), plain(header), plain(footer)
        self.blocks: list[dict[str, Any]] = []

    def cover(self, title: str, subtitle: str, rows: list[tuple[str, Any]], note: str = "") -> None:
        self.blocks.append({"kind": "cover", "title": plain(title), "subtitle": plain(subtitle),
                            "rows": [(plain(k), plain(v) or "—") for k, v in rows], "note": plain(note)})

    def toc(self) -> None:
        self.blocks.append({"kind": "toc"})

    def heading(self, text: str, level: int = 1) -> None:
        self.blocks.append({"kind": "heading", "text": plain(text), "level": max(1, min(3, level))})

    def para(self, text: Any, style: str = "normal") -> None:
        clean = plain(text)
        if clean:
            self.blocks.append({"kind": "para", "text": clean, "style": style})

    def paras(self, text: Any, style: str = "normal") -> None:
        for part in sentences(text):
            self.para(part, style)

    def bullets(self, items: list[Any]) -> None:
        clean = [plain(i) for i in items if plain(i)]
        if clean:
            self.blocks.append({"kind": "bullets", "items": clean})

    def table(self, headers: list[str], rows: list[list[Any]], widths: list[float] | None = None) -> None:
        if not rows:
            return
        self.blocks.append({"kind": "table", "headers": [plain(h) for h in headers],
                            "rows": [[plain(c) or "—" for c in row] for row in rows],
                            "widths": widths})

    def kv(self, rows: list[tuple[str, Any]]) -> None:
        if rows:
            self.blocks.append({"kind": "kv", "rows": [(plain(k), plain(v) or "—") for k, v in rows]})

    def image(self, png: bytes | None, caption: str = "", width_ratio: float = 1.0) -> None:
        if png:
            self.blocks.append({"kind": "image", "png": png, "caption": plain(caption),
                                "width_ratio": max(0.3, min(1.0, width_ratio))})

    def page_break(self) -> None:
        self.blocks.append({"kind": "pagebreak"})

    def headings(self) -> list[tuple[int, str]]:
        return [(b["level"], b["text"]) for b in self.blocks if b["kind"] == "heading" and b["level"] <= 2]

    def text_content(self) -> str:
        """All visible text (tests and markup checks)."""
        out: list[str] = [self.title, self.header, self.footer]
        for block in self.blocks:
            kind = block["kind"]
            if kind == "cover":
                out += [block["title"], block["subtitle"], block["note"]] + [f"{k}{v}" for k, v in block["rows"]]
            elif kind in {"heading", "para"}:
                out.append(block["text"])
            elif kind == "bullets":
                out += block["items"]
            elif kind == "table":
                out += block["headers"] + [c for row in block["rows"] for c in row]
            elif kind == "kv":
                out += [f"{k}{v}" for k, v in block["rows"]]
            elif kind == "image":
                out.append(block["caption"])
        return "\n".join(out)


# -- fonts --------------------------------------------------------------------------

def _font_candidates() -> list[str]:
    configured = os.getenv(CJK_FONT_ENV, "").strip()
    paths = [configured] if configured else []
    paths += [p for p in _FONT_CANDIDATES if os.path.isfile(p)]
    for pattern in ("/usr/share/fonts/**/*[Ww][Qq][Yy]*.tt[cf]", "/usr/share/fonts/**/*CJK*.tt[cf]",
                    "/usr/share/fonts/**/*[Hh]ei*.tt[cf]", "/usr/share/fonts/**/*[Ss]ong*.tt[cf]"):
        try:
            paths += sorted(glob.glob(pattern, recursive=True))[:4]
        except OSError:
            continue
    seen: list[str] = []
    for path in paths:
        if path and os.path.isfile(path) and path not in seen:
            seen.append(path)
    return seen


def pil_cjk_font_path() -> str | None:
    """First font Pillow can load that actually has CJK glyphs (cached per process)."""
    with _FONT_LOCK:
        if _PIL_FONT_PATH:
            return _PIL_FONT_PATH[0]
        found = None
        try:
            from PIL import ImageFont
        except ImportError:
            _PIL_FONT_PATH.append(None)
            return None
        for path in _font_candidates():
            try:
                font = ImageFont.truetype(path, 20)
                box = font.getbbox("课")
                if box and box[2] - box[0] > 8:
                    found = path
                    break
            except (OSError, ValueError):
                continue
        _PIL_FONT_PATH.append(found)
        return found


def _pdf_font() -> str:
    """Embed a TrueType CJK font when available, otherwise the built-in Adobe-GB1 CID font."""
    with _FONT_LOCK:
        if "name" in _PDF_FONT:
            return _PDF_FONT["name"]
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont

        name = ""
        for path in _font_candidates():
            for index in (0, 1, 2):
                try:
                    candidate = f"WeGlowCJK{len(_PDF_FONT)}{index}"
                    font = TTFont(candidate, path, subfontIndex=index) if path.lower().endswith(".ttc") else TTFont(candidate, path)
                    if not font.face.charToGlyph.get(ord("课")):
                        continue
                    pdfmetrics.registerFont(font)
                    name = candidate
                    break
                except Exception:  # reportlab raises TTFError / generic errors for CFF or broken fonts
                    if not path.lower().endswith(".ttc"):
                        break
                    continue
            if name:
                break
        if not name:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            name = "STSong-Light"
        _PDF_FONT["name"] = name
        return name


def pdf_font_kind() -> str:
    """'embedded' or 'cid' (for logs and tests)."""
    return "cid" if _pdf_font() == "STSong-Light" else "embedded"


# -- charts (Pillow PNG, shared by Word and PDF) ------------------------------------------

class _Canvas:
    def __init__(self, width: int, height: int):
        from PIL import Image, ImageDraw, ImageFont

        self.image = Image.new("RGB", (width, height), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.font_path = pil_cjk_font_path()
        self._font_cls = ImageFont
        self._cache: dict[int, Any] = {}

    def font(self, size: int):
        if size not in self._cache:
            if self.font_path:
                self._cache[size] = self._font_cls.truetype(self.font_path, size)
            else:
                try:
                    self._cache[size] = self._font_cls.load_default(size=size)
                except TypeError:
                    self._cache[size] = self._font_cls.load_default()
        return self._cache[size]

    def label(self, text: str, fallback: str) -> str:
        """Chinese labels need a CJK font; without one the chart uses short codes explained in its caption."""
        if self.font_path or all(ord(c) < 128 for c in text):
            return text
        return fallback

    def text(self, xy, text, size=18, fill=MUTED, anchor="la"):
        self.draw.text(xy, text, font=self.font(size), fill=fill, anchor=anchor)

    def width(self, text, size=18) -> float:
        return self.draw.textlength(text, font=self.font(size))

    def png(self) -> bytes:
        buffer = io.BytesIO()
        self.image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _fit(canvas: _Canvas, text: str, size: int, max_width: float) -> str:
    if canvas.width(text, size) <= max_width:
        return text
    while text and canvas.width(text + "…", size) > max_width:
        text = text[:-1]
    return text + "…"


def bar_chart(categories: list[str], series: list[tuple[str, tuple[int, int, int], list[Any]]],
              maximum: float = 10.0, codes: list[str] | None = None) -> tuple[bytes | None, bool]:
    """Horizontal grouped bars (0..maximum). Returns (png, used_codes)."""
    try:
        canvas = _Canvas(1400, 120 + len(categories) * (34 * max(1, len(series)) + 30))
    except ImportError:
        return None, False
    codes = codes or [f"C{i + 1}" for i in range(len(categories))]
    labels = [canvas.label(c, codes[i]) for i, c in enumerate(categories)]
    used_codes = labels != categories
    label_w = 420 if not used_codes else 120
    left, right, top = label_w + 30, 1400 - 120, 70
    span = right - left
    x = left
    for name, color, _ in series:
        canvas.draw.rectangle([x, 20, x + 26, 40], fill=color)
        legend = canvas.label(name, name if all(ord(c) < 128 for c in name) else ("School" if color == PRIMARY else "System"))
        canvas.text((x + 34, 30), legend, 22, MUTED, "lm")
        x += 60 + canvas.width(legend, 22) + 30
    for tick in range(0, 11, 2):
        tx = left + span * tick / 10
        canvas.draw.line([tx, top - 6, tx, canvas.image.height - 40], fill=GRID, width=2)
        canvas.text((tx, canvas.image.height - 30), number(maximum * tick / 10, 1), 18, MUTED, "ma")
    y = top
    for index, label in enumerate(labels):
        group_h = 34 * max(1, len(series))
        canvas.text((left - 16, y + group_h / 2), _fit(canvas, label, 22, label_w), 22, (23, 43, 77), "rm")
        for s_index, (_, color, values) in enumerate(series):
            value = values[index] if index < len(values) else None
            by = y + s_index * 34
            canvas.draw.rectangle([left, by + 4, right, by + 28], fill=(240, 244, 249))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                width = span * max(0.0, min(1.0, float(value) / maximum))
                canvas.draw.rectangle([left, by + 4, left + width, by + 28], fill=color)
                canvas.text((right + 12, by + 16), number(value), 20, (23, 43, 77), "lm")
            else:
                canvas.text((right + 12, by + 16), "—", 20, MUTED, "lm")
        y += group_h + 30
    return canvas.png(), used_codes


def timeline_chart(segments: list[dict[str, Any]], duration: float, colors: dict[str, str],
                   labels: dict[str, str]) -> bytes | None:
    """Classroom state strip (one row) with a time axis and legend."""
    if not segments or not duration or duration <= 0:
        return None
    try:
        canvas = _Canvas(1400, 190)
    except ImportError:
        return None
    left, right, top, bottom = 40, 1360, 70, 120
    span = right - left
    canvas.draw.rectangle([left, top, right, bottom], fill=(240, 244, 249))
    for seg in segments:
        try:
            start, end = float(seg.get("start_sec") or 0), float(seg.get("end_sec") or 0)
        except (TypeError, ValueError):
            continue
        color = _hex(colors.get(seg.get("state"), "#c9d3df"))
        x0 = left + span * max(0.0, min(1.0, start / duration))
        x1 = left + span * max(0.0, min(1.0, end / duration))
        canvas.draw.rectangle([x0, top, max(x0 + 2, x1), bottom], fill=color)
    for i in range(0, 6):
        tx = left + span * i / 5
        canvas.draw.line([tx, bottom, tx, bottom + 8], fill=MUTED, width=2)
        canvas.text((tx, bottom + 14), mmss(duration * i / 5), 18, MUTED, "ma")
    x = left
    fallback = {"engaged": "Engaged", "low_response": "Low", "away": "Away", "not_observed": "N/A"}
    for key, color in colors.items():
        canvas.draw.rectangle([x, 22, x + 24, 42], fill=_hex(color))
        text = canvas.label(labels.get(key, key), fallback.get(key, key))
        canvas.text((x + 32, 32), text, 20, MUTED, "lm")
        x += 70 + canvas.width(text, 20)
    return canvas.png()


def line_chart(points: list[dict[str, Any]], maximum: float = 10.0, pass_score: float = 6.0) -> bytes | None:
    """Trend of reviewed composite scores; gaps (no score) drawn as hollow points."""
    if len(points) < 2:
        return None
    try:
        canvas = _Canvas(1400, 520)
    except ImportError:
        return None
    left, right, top, bottom = 90, 1350, 40, 440
    for tick in range(0, 11, 2):
        ty = bottom - (bottom - top) * tick / 10
        canvas.draw.line([left, ty, right, ty], fill=GRID, width=2)
        canvas.text((left - 14, ty), number(maximum * tick / 10, 1), 18, MUTED, "rm")
    py = bottom - (bottom - top) * pass_score / maximum
    for dx in range(left, right, 24):
        canvas.draw.line([dx, py, min(right, dx + 12), py], fill=WARN, width=3)
    step = (right - left) / max(1, len(points) - 1)
    coords = []
    for index, point in enumerate(points):
        x = left + step * index
        canvas.text((x, bottom + 16), date_text(point.get("date"))[5:10] or str(index + 1), 18, MUTED, "ma")
        score = point.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            coords.append((x, bottom - (bottom - top) * max(0.0, min(1.0, float(score) / maximum)), float(score)))
        else:
            coords.append((x, None, None))
    previous = None
    for x, y, _ in coords:
        if y is not None and previous is not None:
            canvas.draw.line([previous[0], previous[1], x, y], fill=PRIMARY, width=5)
        if y is not None:
            previous = (x, y)
    for x, y, score in coords:
        if y is None:
            canvas.draw.ellipse([x - 9, bottom - 9, x + 9, bottom + 9], outline=(138, 150, 168), width=3)
        else:
            canvas.draw.ellipse([x - 10, y - 10, x + 10, y + 10], fill=PRIMARY)
            canvas.text((x, y - 16), number(score), 18, PRIMARY_DEEP, "md")
    return canvas.png()


def _hex(value: str) -> tuple[int, int, int]:
    value = str(value or "#c9d3df").lstrip("#")
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (201, 211, 223)


# -- Word writer ----------------------------------------------------------------------

def render_docx(model: DocumentModel) -> tuple[bytes, dict[str, Any]]:
    try:
        from docx import Document
        from docx.enum.section import WD_SECTION
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Cm, Pt, RGBColor
    except ImportError as exc:
        raise RendererUnavailable("docx", "python-docx") from exc
    del WD_SECTION
    font_name = "Microsoft YaHei"
    east_asia = "微软雅黑"

    def set_font(run_or_style, size=None, bold=None, color=None):
        font = run_or_style.font
        font.name = font_name
        if size:
            font.size = Pt(size)
        if bold is not None:
            font.bold = bold
        if color:
            font.color.rgb = RGBColor(*color)
        element = run_or_style.element if hasattr(run_or_style, "element") else run_or_style._element
        rpr = element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(attr), font_name)
        fonts.set(qn("w:eastAsia"), east_asia)

    def shade(cell, fill):
        tc_pr = cell._tc.get_or_add_tcPr()
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), fill)
        tc_pr.append(shading)

    def field(paragraph, instruction):
        run = paragraph.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        text = OxmlElement("w:instrText")
        text.set(qn("xml:space"), "preserve")
        text.text = instruction
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(begin)
        run._r.append(text)
        run._r.append(end)
        set_font(run, 8, color=MUTED)

    def fix_widths(table, ratios):
        """Word honours cell widths, LibreOffice/WPS the tblGrid: set both and disable autofit."""
        table.autofit = False
        total = float(sum(ratios)) or 1.0
        for index, column in enumerate(table.columns):
            column.width = Cm(content_width * ratios[index] / total)
        grid = table._tbl.tblGrid
        for index, col in enumerate(grid.findall(qn("w:gridCol"))):
            col.set(qn("w:w"), str(int(Cm(content_width * ratios[index] / total).twips)))

    document = Document()
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.2)
    section.top_margin, section.bottom_margin = Cm(2.4), Cm(2.2)
    content_width = 21 - 4.4
    normal = document.styles["Normal"]
    set_font(normal, 10.5)
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(4)
    for level, size in ((1, 16), (2, 13), (3, 11.5)):
        style = document.styles[f"Heading {level}"]
        set_font(style, size, True, PRIMARY_DEEP if level < 3 else PRIMARY)
        style.paragraph_format.space_before = Pt(14 if level == 1 else 10)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.keep_with_next = True

    header = section.header.paragraphs[0]
    header.text = ""
    run = header.add_run(model.header)
    set_font(run, 8.5, color=PRIMARY)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run(model.footer + " · 第 ")
    set_font(run, 8, color=MUTED)
    field(footer, "PAGE")
    run = footer.add_run(" 页")
    set_font(run, 8, color=MUTED)

    def add_table(headers, rows, widths=None, header_fill="E6EFFB"):
        table = document.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        ratios = widths or [1] * len(headers)
        fix_widths(table, ratios)
        total = float(sum(ratios)) or 1.0
        for r_index, values in enumerate([headers, *rows]):
            for c_index, value in enumerate(values):
                cell = table.rows[r_index].cells[c_index]
                cell.width = Cm(content_width * ratios[c_index] / total)
                paragraph = cell.paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.2
                run = paragraph.add_run(value)
                set_font(run, 9, bold=r_index == 0 and header_fill is not None,
                         color=PRIMARY_DEEP if r_index == 0 and header_fill else None)
                if r_index == 0 and header_fill:
                    shade(cell, header_fill)
        document.add_paragraph().paragraph_format.space_after = Pt(2)
        return table

    image_count = 0
    for block in model.blocks:
        kind = block["kind"]
        if kind == "cover":
            for _ in range(5):
                document.add_paragraph()
            brand = document.add_paragraph()
            brand.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_font(brand.add_run(BRAND_FULL_NAME), 14, True, PRIMARY)
            title = document.add_paragraph()
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER
            title.paragraph_format.space_before = Pt(12)
            set_font(title.add_run(block["title"]), 26, True, PRIMARY_DEEP)
            subtitle = document.add_paragraph()
            subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
            subtitle.paragraph_format.space_after = Pt(36)
            set_font(subtitle.add_run(block["subtitle"]), 13, color=MUTED)
            table = document.add_table(rows=len(block["rows"]), cols=2)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            fix_widths(table, [4, 9])
            for index, (key, value) in enumerate(block["rows"]):
                left, right = table.rows[index].cells
                left.width, right.width = Cm(4), Cm(9)
                set_font(left.paragraphs[0].add_run(key), 11, color=MUTED)
                left.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
                set_font(right.paragraphs[0].add_run(value), 11, True)
            if block["note"]:
                note = document.add_paragraph()
                note.alignment = WD_ALIGN_PARAGRAPH.CENTER
                note.paragraph_format.space_before = Pt(48)
                set_font(note.add_run(block["note"]), 9, color=MUTED)
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        elif kind == "toc":
            heading = document.add_paragraph()
            set_font(heading.add_run("目录"), 16, True, PRIMARY_DEEP)
            heading.paragraph_format.space_after = Pt(10)
            for level, text in model.headings():
                entry = document.add_paragraph()
                entry.paragraph_format.left_indent = Cm(0 if level == 1 else 0.9)
                entry.paragraph_format.space_after = Pt(1)
                entry.paragraph_format.space_before = Pt(3 if level == 1 else 0)
                entry.paragraph_format.line_spacing = 1.0
                set_font(entry.add_run(text), 10.5 if level == 1 else 9.5, level == 1,
                         PRIMARY_DEEP if level == 1 else None)
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        elif kind == "heading":
            document.add_heading(block["text"], level=block["level"])
        elif kind == "para":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(block["text"])
            if block["style"] == "note":
                set_font(run, 9, color=MUTED)
            elif block["style"] == "lead":
                set_font(run, 11, True, PRIMARY_DEEP)
            elif block["style"] == "warn":
                set_font(run, 10, color=(154, 90, 8))
            else:
                set_font(run, 10.5)
        elif kind == "bullets":
            for item in block["items"]:
                paragraph = document.add_paragraph(style="List Bullet")
                set_font(paragraph.add_run(item), 10.5)
        elif kind == "table":
            add_table(block["headers"], block["rows"], block["widths"])
        elif kind == "kv":
            table = document.add_table(rows=len(block["rows"]), cols=2)
            table.style = "Table Grid"
            fix_widths(table, [0.26, 0.74])
            for index, (key, value) in enumerate(block["rows"]):
                left, right = table.rows[index].cells
                left.width, right.width = Cm(content_width * 0.26), Cm(content_width * 0.74)
                shade(left, "F2F6FB")
                set_font(left.paragraphs[0].add_run(key), 9.5, True, PRIMARY_DEEP)
                set_font(right.paragraphs[0].add_run(value), 9.5)
            document.add_paragraph().paragraph_format.space_after = Pt(2)
        elif kind == "image":
            document.add_picture(io.BytesIO(block["png"]), width=Cm(content_width * block["width_ratio"]))
            document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            image_count += 1
            if block["caption"]:
                caption = document.add_paragraph()
                caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_font(caption.add_run(block["caption"]), 9, color=MUTED)
        elif kind == "pagebreak":
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    core = document.core_properties
    core.title = model.title
    core.author = BRAND_FULL_NAME
    core.comments = "由 " + BRAND_FULL_NAME + " 生成"
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    return data, {"byte_size": len(data), "image_count": image_count, "page_count": None}


# -- PDF writer ---------------------------------------------------------------------------

def render_pdf(model: DocumentModel) -> tuple[bytes, dict[str, Any]]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Spacer, Table,
                                        TableStyle)
        from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate
        from reportlab.platypus.frames import Frame
        from reportlab.platypus.tableofcontents import TableOfContents
        from xml.sax.saxutils import escape
    except ImportError as exc:
        raise RendererUnavailable("pdf", "reportlab") from exc
    font = _pdf_font()
    width, height = A4
    margin_x, margin_top, margin_bottom = 2.2 * cm, 2.4 * cm, 2.2 * cm
    content_width = width - 2 * margin_x
    rgb = lambda c: colors.Color(c[0] / 255, c[1] / 255, c[2] / 255)  # noqa: E731
    base = ParagraphStyle("base", fontName=font, fontSize=10.5, leading=17, wordWrap="CJK", spaceAfter=4)
    styles = {
        "normal": base,
        "note": ParagraphStyle("note", parent=base, fontSize=9, leading=14, textColor=rgb(MUTED)),
        "lead": ParagraphStyle("lead", parent=base, fontSize=11.5, leading=18, textColor=rgb(PRIMARY_DEEP)),
        "warn": ParagraphStyle("warn", parent=base, fontSize=10, textColor=colors.Color(0.6, 0.35, 0.03)),
        "h1": ParagraphStyle("h1", parent=base, fontSize=16, leading=22, spaceBefore=12, spaceAfter=8,
                             textColor=rgb(PRIMARY_DEEP)),
        "h2": ParagraphStyle("h2", parent=base, fontSize=13, leading=19, spaceBefore=10, spaceAfter=6,
                             textColor=rgb(PRIMARY_DEEP)),
        "h3": ParagraphStyle("h3", parent=base, fontSize=11.5, leading=17, spaceBefore=8, spaceAfter=4,
                             textColor=rgb(PRIMARY)),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=13, spaceAfter=0),
        "cellhead": ParagraphStyle("cellhead", parent=base, fontSize=9, leading=13, spaceAfter=0,
                                   textColor=rgb(PRIMARY_DEEP)),
        "caption": ParagraphStyle("caption", parent=base, fontSize=9, leading=13, alignment=TA_CENTER,
                                  textColor=rgb(MUTED)),
        "cover_brand": ParagraphStyle("cover_brand", parent=base, fontSize=14, leading=20, alignment=TA_CENTER,
                                      textColor=rgb(PRIMARY)),
        "cover_title": ParagraphStyle("cover_title", parent=base, fontSize=26, leading=36, alignment=TA_CENTER,
                                      textColor=rgb(PRIMARY_DEEP), spaceBefore=10),
        "cover_sub": ParagraphStyle("cover_sub", parent=base, fontSize=13, leading=20, alignment=TA_CENTER,
                                    textColor=rgb(MUTED), spaceAfter=30),
        "cover_key": ParagraphStyle("cover_key", parent=base, fontSize=11, alignment=TA_RIGHT, textColor=rgb(MUTED)),
        "cover_val": ParagraphStyle("cover_val", parent=base, fontSize=11),
        "toc_title": ParagraphStyle("toc_title", parent=base, fontSize=16, leading=22, textColor=rgb(PRIMARY_DEEP),
                                    spaceAfter=10),
    }
    # The built-in Adobe-GB1 CID font has no glyph for U+00B7 / U+2022 / U+2027; use the CJK middle dot.
    glyphs = str.maketrans({"·": "・", "•": "・", "‧": "・"}) if font == "STSong-Light" else {}
    fix = lambda text: str(text).translate(glyphs) if glyphs else str(text)  # noqa: E731
    p = lambda text, style="normal": Paragraph(escape(fix(text)).replace("\n", "<br/>"), styles[style])  # noqa: E731
    pages = {"count": 0}

    class ReportDoc(BaseDocTemplate):
        def afterFlowable(self, flowable):  # noqa: N802 - reportlab hook name
            level = getattr(flowable, "_toc_level", None)
            if level is not None:
                key = f"h{id(flowable)}"
                self.canv.bookmarkPage(key)
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page, key))

    def decorate(canvas, doc):
        pages["count"] = max(pages["count"], doc.page)
        canvas.saveState()
        canvas.setFont(font, 8.5)
        if doc.page > 1:
            canvas.setFillColor(rgb(PRIMARY))
            canvas.drawString(margin_x, height - 1.5 * cm, fix(model.header))
            canvas.setStrokeColor(rgb(PRIMARY))
            canvas.setLineWidth(0.8)
            canvas.line(margin_x, height - 1.65 * cm, width - margin_x, height - 1.65 * cm)
        canvas.setFillColor(rgb(MUTED))
        canvas.setFont(font, 8)
        canvas.drawCentredString(width / 2, 1.2 * cm, fix(f"{model.footer} · 第 {doc.page} 页"))
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = ReportDoc(buffer, pagesize=A4, title=model.title, author=BRAND_FULL_NAME,
                    subject=model.header, creator=BRAND_FULL_NAME,
                    leftMargin=margin_x, rightMargin=margin_x, topMargin=margin_top, bottomMargin=margin_bottom)
    frame = Frame(margin_x, margin_bottom, content_width, height - margin_top - margin_bottom, id="body")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=decorate)])
    grid = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.85, 0.9)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.94, 0.98)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    story: list[Any] = []
    image_count = 0
    for block in model.blocks:
        kind = block["kind"]
        if kind == "cover":
            story += [Spacer(1, 5 * cm), p(BRAND_FULL_NAME, "cover_brand"), p(block["title"], "cover_title"),
                      p(block["subtitle"], "cover_sub")]
            rows = [[p(k, "cover_key"), p(v, "cover_val")] for k, v in block["rows"]]
            table = Table(rows, colWidths=[4.5 * cm, 9 * cm])
            table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.Color(0.88, 0.91, 0.95))]))
            story.append(table)
            if block["note"]:
                story += [Spacer(1, 2.5 * cm), p(block["note"], "caption")]
            story.append(PageBreak())
        elif kind == "toc":
            toc = TableOfContents()
            toc.levelStyles = [
                ParagraphStyle("toc1", parent=base, fontSize=11, leading=18, textColor=rgb(PRIMARY_DEEP)),
                ParagraphStyle("toc2", parent=base, fontSize=10, leading=16, leftIndent=18),
            ]
            toc.dotsMinLevel = 0
            story += [p("目录", "toc_title"), toc, PageBreak()]
        elif kind == "heading":
            paragraph = p(block["text"], f"h{block['level']}")
            if block["level"] <= 2:
                paragraph._toc_level = block["level"] - 1
            story.append(paragraph)
        elif kind == "para":
            story.append(p(block["text"], block["style"] if block["style"] in styles else "normal"))
        elif kind == "bullets":
            for item in block["items"]:
                story.append(Paragraph(fix("• " + escape(item)), ParagraphStyle("bullet", parent=base, leftIndent=12,
                                                                            firstLineIndent=-10)))
        elif kind in {"table", "kv"}:
            if kind == "table":
                rows = [[p(h, "cellhead") for h in block["headers"]]]
                rows += [[p(c, "cell") for c in row] for row in block["rows"]]
                ratios = block["widths"] or [1] * len(block["headers"])
                style = grid
            else:
                rows = [[p(k, "cellhead"), p(v, "cell")] for k, v in block["rows"]]
                ratios = [0.26, 0.74]
                style = TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.85, 0.9)),
                    ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.965, 0.985)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ])
            total = float(sum(ratios)) or 1.0
            table = Table(rows, colWidths=[content_width * r / total for r in ratios],
                          repeatRows=1 if kind == "table" else 0)
            table.setStyle(style)
            story += [table, Spacer(1, 6)]
        elif kind == "image":
            from PIL import Image as PILImage

            with PILImage.open(io.BytesIO(block["png"])) as probe:
                pw, ph = probe.size
            draw_w = content_width * block["width_ratio"]
            image = Image(io.BytesIO(block["png"]), width=draw_w, height=draw_w * ph / pw)
            parts = [image]
            if block["caption"]:
                parts.append(p(block["caption"], "caption"))
            story += [KeepTogether(parts), Spacer(1, 6)]
            image_count += 1
        elif kind == "pagebreak":
            story.append(PageBreak())
    doc.multiBuild(story)
    data = buffer.getvalue()
    return data, {"byte_size": len(data), "image_count": image_count, "page_count": pages["count"] or None,
                  "font": "cid" if font == "STSong-Light" else "embedded"}


def render(model: DocumentModel, fmt: str) -> tuple[bytes, dict[str, Any]]:
    if fmt == "docx":
        return render_docx(model)
    if fmt == "pdf":
        return render_pdf(model)
    raise ValueError(f"unsupported format {fmt}")


def renderer_available(fmt: str) -> bool:
    try:
        if fmt == "docx":
            import docx  # noqa: F401
        elif fmt == "pdf":
            import reportlab  # noqa: F401
        else:
            return False
    except ImportError:
        return False
    return True


# -- classroom report ------------------------------------------------------------------

def _students_by_id(payload: dict[str, Any]) -> dict[str, str]:
    return {s.get("student_id"): s.get("display_name") or "学生"
            for s in payload.get("students") or [] if isinstance(s, dict)}


def classroom_report_model(payload: dict[str, Any], meta: dict[str, Any], *, admin: bool) -> DocumentModel:
    """Typeset model of a (role-redacted) classroom report snapshot."""
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    overview = report.get("course_overview") if isinstance(report.get("course_overview"), dict) else {}
    school = payload.get("school_context") if isinstance(payload.get("school_context"), dict) else {}
    names = _students_by_id(payload)
    course_name = overview.get("course_name") or meta.get("course_name") or "未命名课程"
    lesson_date = overview.get("lesson_date") or str(meta.get("generated_at") or "")[:10]
    title = meta.get("title") or report.get("title") or "课堂观察与学习支持报告"
    model = DocumentModel(title, f"{BRAND_FULL_NAME} · 课堂观察报告", f"由 {BRAND_FULL_NAME} 生成")
    stats = meta.get("stats") or {}
    school_name = school.get("school_name") or overview.get("school_name") or "—"
    region = " ".join(x for x in (school.get("city"), school.get("district")) if x)
    model.cover(title, "课堂观察报告 · " + plain(course_name), [
        ("课程", course_name),
        ("上课日期", date_text(lesson_date)),
        ("学校", school_name + (f"（{region}）" if region else "")),
        ("报告编号", str(meta.get("report_id") or "")[:8]),
        ("生成时间", date_text(meta.get("generated_at"))),
        ("关联学生", f"{stats.get('students', len(names))} 名"),
        ("报告状态", meta.get("status_label") or "可下载"),
        ("阅读对象", "公司后台（学生已化名）" if admin else "本校教学团队"),
    ], note="本报告由教师复核记录与系统公开口径生成，仅用于课堂教育支持复盘。")
    model.toc()
    chapter = _Chapters()

    # 一、课程总览与结论
    model.heading(chapter.next("课程总览与结论"), 1)
    model.table(["关联学生", "已复核目标", "可计分目标", "待处理记录"],
                [[f"{stats.get('students', 0)} 名", f"{stats.get('reviewed', 0)} 条",
                  f"{stats.get('scored', 0)} 条", f"{stats.get('pending', 0)} 条"]])
    conclusion = overview.get("conclusion") if isinstance(overview.get("conclusion"), dict) else {}
    if conclusion.get("available"):
        grade = conclusion.get("grade") or {}
        model.para(f"课程结论（试行口径）：{plain(grade.get('label'))}，结论分 {number(conclusion.get('score'), 1)}"
                   f"（等级区间 {plain(grade.get('range'))}）。", "lead")
        formula = (conclusion.get("formula") or {}).get("text")
        if formula:
            model.para("计算方式：" + plain(formula))
        strengths = [s.get("text") for s in conclusion.get("strengths") or [] if isinstance(s, dict)]
        improvements = [s.get("text") for s in conclusion.get("improvements") or [] if isinstance(s, dict)]
        if strengths:
            model.heading("主要优点", 3)
            model.bullets(strengths)
        if improvements:
            model.heading("主要待改进", 3)
            model.bullets(improvements)
        if conclusion.get("note"):
            model.para(conclusion.get("note"), "note")
    else:
        missing = conclusion.get("missing") if isinstance(conclusion.get("missing"), list) else []
        if overview:
            model.para("课程结论暂未生成：" + ("、".join(plain(m) for m in missing) or "缺少已核对的课程评价或已复核测量")
                       + "。完成后重新打开课堂分析页即可更新报告。", "warn")
        overview_section = next((s for s in report.get("sections") or []
                                 if isinstance(s, dict) and s.get("source") == "course_overview"), None)
        if overview_section:
            model.paras(overview_section.get("text"))
    measures = [m for m in report.get("measurements") or [] if isinstance(m, dict)]
    if measures:
        png, used = bar_chart([m.get("label", "") for m in measures],
                              [("综合分", PRIMARY, [m.get("score") for m in measures])],
                              codes=[f"M{i + 1}" for i in range(len(measures))])
        caption = "图：已记录目标测量（10 分制，空缺表示证据不足，不按 0 分处理）"
        if used:
            caption += "；" + "，".join(f"M{i + 1}＝{plain(m.get('label'))}" for i, m in enumerate(measures))
        model.image(png, caption)

    # 二、课程评价
    indicators = overview.get("indicators") if isinstance(overview.get("indicators"), dict) else {}
    categories = [c for c in indicators.get("categories") or [] if isinstance(c, dict)]
    items = [i for i in indicators.get("items") or [] if isinstance(i, dict)]
    model.heading(chapter.next("课程评价"), 1)
    if categories:
        model.para("课程评价按学校标准 4 类、10 项评分（每项 10 分）：学校评分来自教师核对后的原表，"
                   "系统评分按公开口径由课程任务目标、学生测量与视频片段计算，两者分差用于复盘讨论，不互相替代。")
        model.kv([
            ("学校原表总分", f"{number(indicators.get('school_total_100'), 1)} / 100"),
            ("学校评分（10分制）", number(indicators.get("school_score_10"))),
            ("教学评分（70分制）", number(indicators.get("teaching_score_70"), 1)),
            ("系统评分（10分制）", number(indicators.get("system_score_10"))),
            ("系统总分（100分制）", number(indicators.get("system_total_100"), 1)),
            ("总分差（系统−学校）", number(indicators.get("total_gap_10"))),
        ])
        png, used = bar_chart([c.get("label", "") for c in categories],
                              [("学校评分", PRIMARY, [c.get("school") for c in categories]),
                               ("系统评分", SYSTEM_COLOR, [c.get("system") for c in categories])],
                              codes=[f"C{i + 1}" for i in range(len(categories))])
        caption = "图：学校标准四类目得分对比（10 分制；深蓝为学校评分，浅蓝为系统评分）"
        if used:
            caption += "；" + "，".join(f"C{i + 1}＝{plain(c.get('label'))}" for i, c in enumerate(categories))
        model.image(png, caption)
        model.heading("类目得分", 2)
        model.table(["评价类目", "学校评分", "系统评分", "分差（系统−学校）", "包含条目"],
                    [[c.get("label"), number(c.get("school")), number(c.get("system")), number(c.get("gap")),
                      "、".join(f"第{str(i)[1:]}项" for i in c.get("item_ids") or [])] for c in categories],
                    [3.2, 1.2, 1.2, 1.6, 1.8])
    if items:
        model.heading("条目得分与依据摘要", 2)
        model.table(["序号", "评价条目", "所属类目", "学校分", "系统分", "依据摘要"],
                    [[str(i.get("number") or ""), i.get("label"), i.get("category_label"), number(i.get("school")),
                      number(i.get("system")), _clip(i.get("evidence") or i.get("formula") or "未填写依据", 160)]
                     for i in items], [0.6, 3.0, 1.8, 0.9, 0.9, 4.2])
        formulas = [(i.get("number"), i.get("formula")) for i in items if i.get("formula")]
        if formulas:
            model.heading("系统评分计算依据", 3)
            for number_, formula in formulas:
                model.para(f"第{plain(number_)}项：{plain(formula)}", "note")
    if not categories and not items:
        dual = next((s for s in report.get("sections") or [] if isinstance(s, dict) and s.get("title") == "双轨评价对照"), None)
        if dual:
            model.paras(dual.get("text"))
        else:
            model.para("本课尚未保存课程评价，课程评价类目与条目得分暂缺。", "warn")

    # 三、学生个体评价
    model.heading(chapter.next("学生个体评价"), 1)
    overview_students = [s for s in overview.get("students") or [] if isinstance(s, dict)]
    rows_by_student: dict[str, list[dict[str, Any]]] = {}
    for row in report.get("student_measurements") or []:
        if isinstance(row, dict):
            rows_by_student.setdefault(row.get("student_id"), []).append(row)
    dimension_labels = indicators.get("dimension_labels") or {
        "accuracy": "准确性", "independence": "独立性", "consistency": "一致性", "transfer": "泛化性"}
    weights = {"accuracy": "35%", "independence": "30%", "consistency": "20%", "transfer": "15%"}
    goal_text = {g.get("goal_code"): g.get("description") for g in (report.get("course_task") or {}).get("goals") or []
                 if isinstance(g, dict)}
    student_ids = [s.get("student_id") for s in overview_students] or list(rows_by_student) or list(names)
    if not student_ids:
        model.para("本课尚未确认画面中的学生，暂无学生个体评价。", "warn")
    for index, student_id in enumerate(student_ids, start=1):
        info = next((s for s in overview_students if s.get("student_id") == student_id), {})
        name = info.get("display_name") or names.get(student_id) or f"学生{index}"
        model.heading(f"{chapter.current}.{index} {plain(name)}", 2)
        summary_bits = []
        if info:
            summary_bits.append(f"综合分 {number(info.get('composite'))}/10")
            summary_bits.append(f"目标达成 {info.get('goals_achieved', 0)}/{info.get('goals_total', 0)}")
            summary_bits.append(f"达成度 {number(info.get('attainment'), 1)}")
            if info.get("class_name") and not admin:
                summary_bits.append(f"班级 {plain(info.get('class_name'))}")
        if summary_bits:
            model.para("；".join(summary_bits) + "。", "lead")
        dims = info.get("dimensions") if isinstance(info.get("dimensions"), dict) else {}
        if dims:
            model.table(["维度", "本课平均分（10分制）", "权重（试行）"],
                        [[dimension_labels.get(k, k), number(dims.get(k)), weights.get(k, "")] for k in
                         ("accuracy", "independence", "consistency", "transfer")], [2, 2, 1.5])
        rows = rows_by_student.get(student_id, [])
        if rows:
            model.heading("目标达成", 3)
            model.table(["目标", "通过标准", "复核状态", "综合分", "是否达标"],
                        [[f"{r.get('goal_id', '')} {_clip(r.get('goal_description') or goal_text.get(r.get('goal_id')) or '', 40)}",
                          r.get("pass_criteria") or "未填写", r.get("review_label"),
                          number(r.get("score")) if r.get("score") is not None else "空缺（证据不足或待复核）",
                          "达到" if r.get("passed") is True else "未达到" if r.get("passed") is False else "—"]
                         for r in rows], [3.4, 2, 1.4, 1.4, 1])
        elif info.get("goal_scores"):
            model.table(["目标", "得分"], [[g, number(v)] for g, v in info["goal_scores"].items()], [3, 1])
        timeline = info.get("timeline") if isinstance(info.get("timeline"), dict) else {}
        segments = [s for s in timeline.get("segments") or [] if isinstance(s, dict)]
        key_points = []
        for row in rows:
            for seg in row.get("evidence_segments") or []:
                if isinstance(seg, dict):
                    key_points.append((seg.get("start_sec"), seg.get("end_sec"), seg.get("state_label"), row.get("goal_id")))
        if segments or key_points:
            model.heading("关键片段时间点", 3)
            png = timeline_chart(segments, float(timeline.get("duration_sec") or 0),
                                 overview.get("state_colors") or {}, overview.get("state_labels") or {})
            model.image(png, "图：课堂状态时间轴（绿色稳定参与、橙色回应偏低、红色离开或不可见、灰色未观察）")
            seen = set()
            point_rows = []
            for start, end, label, goal in key_points:
                key = (start, end, label)
                if key in seen:
                    continue
                seen.add(key)
                point_rows.append([f"{mmss(start)}–{mmss(end)}", label or "—", goal or "—"])
            if not point_rows:
                point_rows = [[f"{mmss(s.get('start_sec'))}–{mmss(s.get('end_sec'))}", s.get("label") or "—", "—"]
                              for s in segments]
            model.table(["时间段", "片段状态", "关联目标"], point_rows[:12], [1.6, 3, 1.2])
        observations = [r.get("observation_summary") for r in rows if r.get("observation_summary")]
        model.heading("教师观察摘要", 3)
        if observations:
            model.bullets(observations[:6])
        else:
            model.para("本课该学生暂无教师填写的观察记录摘要。", "note")
        if info.get("flags"):
            model.para("提示：" + "；".join(plain(f.get("text") if isinstance(f, dict) else f) for f in info["flags"]), "warn")

    # 四、本课任务目标与达成情况
    course_task = report.get("course_task") if isinstance(report.get("course_task"), dict) else {}
    task_section = next((s for s in report.get("sections") or []
                         if isinstance(s, dict) and s.get("source") == "course_task"), None)
    model.heading(chapter.next("本课任务目标与达成情况"), 1)
    goals = [g for g in course_task.get("goals") or [] if isinstance(g, dict)]
    if goals:
        model.para(f"本课课程任务版本 {plain(course_task.get('version'))}，共确认 {len(goals)} 个目标。"
                   "达成情况只按教师在本视频中按目标编号保存的复核记录统计，未记录的目标保持空缺，不按未达成处理。")
        model.table(["目标编号", "目标描述", "通过标准", "关联/已复核/达标", "达成情况"],
                    [[g.get("goal_code"), g.get("description"), g.get("pass_criteria") or "未填写",
                      f"{g.get('record_count', 0)}/{g.get('reviewed_count', 0)}/{g.get('passed_count', 0)}",
                      g.get("achievement_label") or "—"] for g in goals], [1.1, 3.4, 2, 1.6, 1.3])
        ov_goals = [g for g in indicators.get("goals") or [] if isinstance(g, dict)]
        if ov_goals:
            model.table(["目标编号", "学生达成"], [[g.get("goal_code"), g.get("label")] for g in ov_goals], [1, 3])
    if task_section:
        model.heading("目标与课堂评价依据", 3)
        model.paras(task_section.get("text"))
    if not goals and not task_section:
        model.para("本课未上传或未确认课程任务文件，目标达成情况暂缺。上传课程任务 Word/PDF 后可自动带入目标。", "warn")

    # 五、课堂观察记录（其余叙述章节）
    skipped = {"course_overview", "course_task", "student_measurement"}
    narrative = [s for s in report.get("sections") or [] if isinstance(s, dict)
                 and s.get("source") not in skipped and s.get("title") != "双轨评价对照"]
    if admin:
        narrative = [s for s in narrative if "iep" not in str(s.get("source") or "").lower()
                     and "IEP" not in str(s.get("title") or "") and "授权资料" not in str(s.get("title") or "")]
    measurement_section = next((s for s in report.get("sections") or []
                                if isinstance(s, dict) and s.get("source") == "student_measurement"), None)
    if narrative or measurement_section:
        model.heading(chapter.next("课堂观察记录"), 1)
        for sub, section in enumerate(narrative, start=1):
            model.heading(f"{chapter.current}.{sub} {plain(section.get('title'))}", 2)
            model.paras(section.get("text"))
        if measurement_section:
            model.heading(f"{chapter.current}.{len(narrative) + 1} 学生测量明细", 2)
            intro = sentences(measurement_section.get("text"))
            for part in intro[:2]:
                model.para(part)
            rows = [r for r in report.get("student_measurements") or [] if isinstance(r, dict)]
            if rows:
                model.table(["学生", "目标", "复核状态", "综合分 / 建议分", "视频指标", "证据片段"],
                            [_measurement_cells(r, names) for r in rows], [1.3, 0.8, 1.1, 1.6, 2.8, 1.8])

    # 附录
    model.heading("附录 A　评分依据摘要", 1)
    basis = next((s for s in report.get("appendix_sections") or []
                  if isinstance(s, dict) and s.get("source") == "score_basis"), None)
    if basis:
        model.paras(basis.get("text"))
    else:
        model.para("该报告生成于评分依据上线之前，请重新打开课堂分析页生成最新报告后再下载。", "note")
    model.heading("附录 B　评分标准细则", 1)
    _rubric_appendix(model)
    rubric = next((s for s in report.get("appendix_sections") or []
                   if isinstance(s, dict) and s.get("source") == "rubric_appendix"), None)
    if rubric:
        model.heading("细则原文", 3)
        model.paras(rubric.get("text"))
    for extra in report.get("appendix_sections") or []:
        if isinstance(extra, dict) and extra.get("source") not in {"score_basis", "rubric_appendix"}:
            model.heading(plain(extra.get("title")), 2)
            model.paras(extra.get("text"))

    model.heading("使用边界声明", 1)
    model.paras(BOUNDARY_TEXT)
    for note in (payload.get("source_note"), payload.get("report_scope"), overview.get("boundary")):
        if note:
            model.para(note, "note")
    model.para(f"报告编号 {str(meta.get('report_id') or '')[:8]} · 版本 {plain(meta.get('version_fingerprint'))} · "
               f"生成时间 {date_text(meta.get('generated_at'))} · 由 {BRAND_FULL_NAME} 生成", "note")
    return model


def _measurement_cells(row: dict[str, Any], names: dict[str, str]) -> list[str]:
    from .demo2_measurement_link import measurement_table_cells

    cells = measurement_table_cells(row, names)
    # measurement_table_cells: 学生, 目标编号, 通过标准, 复核状态, 综合分/建议分, 视频指标, 证据片段
    return [cells[0], cells[1], cells[3], cells[4], cells[5], cells[6]]


def _clip(text: Any, limit: int) -> str:
    clean = plain(text)
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def _rubric_appendix(model: DocumentModel) -> None:
    try:
        from .assessment_rubric import rubric_contract
        contract = rubric_contract()
    except Exception:  # appendix degrades to the snapshot text only
        return
    model.para(f"学生测量量表 {plain(contract.get('rubric_version'))}（细则 {plain(contract.get('detail_version'))}）："
               f"十分制，{number((contract.get('scale') or {}).get('pass_score'), 1)} 分为试行参考线；"
               "综合分 = 各维度分 × 权重之和，仅在教师复核、四个维度齐全且观察至少 2 次时生成。")
    dims = [d for d in contract.get("dimensions") or [] if isinstance(d, dict)]
    model.table(["维度", "权重", "含义", "证据要求"],
                [[d.get("label"), f"{d.get('weight_percent')}%", d.get("description"), d.get("evidence")] for d in dims],
                [1, 0.7, 3, 3.3])
    levels = sorted({a.get("level") for d in dims for a in d.get("anchors") or [] if isinstance(a, dict)},
                    reverse=True)
    if levels:
        rows = []
        for level in levels:
            row = [f"{level} 分"]
            for d in dims:
                anchor = next((a.get("text") for a in d.get("anchors") or [] if a.get("level") == level), "")
                row.append(anchor or "—")
            rows.append(row)
        model.table(["锚点"] + [d.get("label") for d in dims], rows, [0.7] + [2] * len(dims))
    if contract.get("anchor_rule"):
        model.para(contract["anchor_rule"], "note")


class _Chapters:
    NUMERALS = "一二三四五六七八九十"

    def __init__(self):
        self.count = 0

    def next(self, title: str) -> str:
        self.count += 1
        return f"{self.NUMERALS[self.count - 1] if self.count <= 10 else self.count}、{title}"

    @property
    def current(self) -> int:
        return self.count


def classroom_filename(payload: dict[str, Any], meta: dict[str, Any], fmt: str) -> str:
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    overview = report.get("course_overview") if isinstance(report.get("course_overview"), dict) else {}
    course = safe_filename_part(overview.get("course_name") or meta.get("course_name"), "课程")
    day = (overview.get("lesson_date") or str(meta.get("generated_at") or "")[:10] or
           datetime.now().strftime("%Y-%m-%d"))
    return f"WeGlow_课堂报告_{course}_{safe_filename_part(day, 'date', 10)}.{fmt}"


# -- single measurement report --------------------------------------------------------

SOURCE_LABELS = {"classroom_observation": "现场观察", "video_review": "视频复核", "video": "课堂视频（系统生成）"}
SCORING_NOTE = ("本报告呈现教师逐课手工记录数据，经教师依量表复核后生成综合得分。量表采用10分制，6分为试行参考合格线。"
                "四个维度为：准确性（目标行为完成正确率）、独立性（完成行为所需提示级别）、一致性（在相同条件下重复出现的稳定程度）、"
                "泛化性（在新材料或新场景中是否出现，少于2次观察机会时应留空而非填0）。各维度权重为试行参考，尚待校方结合实际数据校准，"
                "不应引用为官方验证结论。本次得分仅反映所记录课次的表现，不代表该学生的整体能力评价；跨课比较需保持相同目标、条件与通过标准，"
                "混合不同测量条件的数据不具可比性。视频处理系统不自动给分，所有得分均由教师人工判断后填写。")


def measurement_report_model(record: dict[str, Any], student_name: str, trend_points: list[dict[str, Any]],
                             rubric: dict[str, Any]) -> DocumentModel:
    """Same content as the measurement page 「单次报告」 tab (teacher-side, gated IEP)."""
    dims_meta = [d for d in rubric.get("dimensions") or [] if isinstance(d, dict)]
    labels = {d["key"]: d.get("label", d["key"]) for d in dims_meta}
    weights = {d["key"]: f"{d.get('weight_percent')}%" for d in dims_meta}
    insufficient = (rubric.get("evidence_status") or {}).get("insufficient", "证据不足")
    assessment = record.get("assessment") if isinstance(record.get("assessment"), dict) else {}
    dims = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
    scale_max = (assessment.get("scale") or {}).get("max") or (rubric.get("scale") or {}).get("max") or 10
    score = assessment.get("score") if assessment.get("evidence_status") != insufficient else None
    pending_video = record.get("source_type") == "video" and not record.get("reviewed")
    title = f"{student_name} · 单次记录报告"
    model = DocumentModel(title, f"{BRAND_FULL_NAME} · 学生测量报告", f"由 {BRAND_FULL_NAME} 生成")
    model.cover("学生单次测量报告", f"{student_name} · {plain(record.get('goal_id'))}", [
        ("学生", student_name),
        ("课程", record.get("course_name") or "—"),
        ("上课日期", date_text(record.get("lesson_date"))),
        ("学习目标", f"{plain(record.get('goal_id'))} {plain(record.get('goal_description'))}".strip()),
        ("记录编号", str(record.get("record_id") or "")[:8]),
        ("生成时间", date_text(datetime.now().astimezone().isoformat())),
    ], note="仅反映所记录课次的表现，不代表学生整体能力评价。")
    model.heading("一、记录信息", 1)
    model.kv([
        ("日期", date_text(record.get("lesson_date"))), ("课节", record.get("lesson_id")),
        ("课程", record.get("course_name") or "—"), ("目标", record.get("goal_id")),
        ("条件", record.get("measurement_context")), ("来源", SOURCE_LABELS.get(record.get("source_type"), "现场观察")),
        ("复核状态", "教师已复核" if record.get("reviewed") else "建议·待复核" if pending_video else "未复核"),
        ("机会次数", record.get("opportunities") if record.get("opportunities") is not None else "—"),
        ("观察次数", record.get("observed") if record.get("observed") is not None else "—"),
        ("通过标准", record.get("criterion") or "—"),
    ])
    model.heading("二、综合评分", 1)
    if pending_video:
        suggested = record.get("suggested_scores") or {}
        model.para("建议·待复核：本记录由课堂视频系统生成，教师复核前不生成综合得分、不进入趋势得分线和课堂报告综合分。系统建议："
                   + "、".join(f"{labels.get(k, k)} {'留空' if suggested.get(k) is None else number(suggested.get(k), 1)}"
                              for k in labels) + "。", "warn")
    elif score is None:
        reasons = "；".join(plain(r) for r in assessment.get("evidence_reasons") or []) or "未达到最低评分条件"
        model.para(f"{insufficient}：{reasons}。不生成综合得分，避免基于不充分证据给出数字。", "warn")
    else:
        passed = assessment.get("passed")
        model.para(f"综合得分 {float(score):.2f} / {number(scale_max, 0)} 分"
                   + ("，达到参考合格线" if passed is True else "，未达参考合格线" if passed is False else "") + "。", "lead")
    basis = record.get("score_basis") if isinstance(record.get("score_basis"), dict) else {}
    if basis.get("formula"):
        inputs = basis.get("inputs") or {}
        if basis.get("status") != "scored":
            model.para("依据：证据不足，未计分（" + "；".join(plain(r) for r in basis.get("reasons") or []) + "）", "note")
        else:
            formula = basis["formula"]
            model.para(f"依据：{plain(formula.get('expression'))} = {plain(formula.get('result'))}；观察 "
                       f"{plain(inputs.get('observed', '—'))}/{plain(inputs.get('opportunities', '—'))} 次，提示层级"
                       f"「{plain(inputs.get('support_label') or '未记录')}」（量表 {plain(basis.get('rubric_version'))}）", "note")
    dim_rows, values = [], []
    for key in labels:
        value = (dims.get(key) or {}).get("score") if isinstance(dims.get(key), dict) else None
        values.append(value)
        dim_rows.append([labels[key], "未观察" if value is None else f"{number(value, 1)} 分", weights.get(key, "")])
    model.table(["维度", "得分", "权重（试行）"], dim_rows, [2, 2, 1.5])
    if any(v is not None for v in values):
        png, used = bar_chart(list(labels.values()), [("得分", PRIMARY, values)], maximum=float(scale_max),
                              codes=["ACC", "IND", "CON", "TRA"][:len(labels)])
        caption = "图：四维度得分（10 分制）"
        if used:
            caption += "；ACC＝准确性，IND＝独立性，CON＝一致性，TRA＝泛化性"
        model.image(png, caption, 0.85)
    model.para("准确性35%·独立性30%·一致性20%·泛化性15%为试行设计权重，尚待校方确认。6分参考合格线不具法定效力。"
               "评分由教师人工依照量表复核，视频处理不自动给分。", "note")
    first = (record.get("evidence_segments") or [{}])[0] if record.get("evidence_segments") else None
    if record.get("source_type") == "video" and record.get("task_id"):
        model.para("数据来源：课堂视频（系统生成）" + (f"，首个证据片段 {mmss(first.get('start_sec'))}–{mmss(first.get('end_sec'))}"
                                                 if isinstance(first, dict) else ""), "note")
    elif record.get("source_type") == "video_review" and record.get("task_id"):
        model.para(f"数据来源：视频复核片段 {number(record.get('start_sec') or 0, 0)}s – {number(record.get('end_sec'), 0)}s", "note")
    else:
        model.para("数据来源：现场课堂观察", "note")
    if record.get("source_type") == "video":
        model.heading("三、本课目标、IEP 支持条件与视频证据", 1)
        doc_id = record.get("course_task_doc_id")
        model.kv([
            ("课程任务", f"{str(doc_id)[:12]} · 版本 {plain(record.get('course_task_version'))}" if doc_id else "本课未确认课程任务"),
            ("课堂任务", str(record.get("task_id") or "")[:12]),
            ("上课日期", date_text(record.get("lesson_date")) + ("（来自课程任务）" if record.get("lesson_date_source") == "course_task"
                                                              else "（来自上传时间）")),
            ("学习目标", f"{plain(record.get('goal_id'))} {plain(record.get('goal_description'))}"),
            ("通过标准", record.get("pass_criteria") or record.get("criterion") or "未填写"),
            ("测量条件", record.get("measurement_conditions") or record.get("measurement_context") or "未填写"),
        ])
        items = [i for i in record.get("iep_support") or [] if isinstance(i, dict)]
        manual = record.get("iep_manual_supplement") or ""
        model.heading("IEP 支持条件", 3)
        if items or manual:
            model.bullets([f"{plain(i.get('category_label') or '要点')}：{plain(i.get('text'))}"
                           + (f"（第 {plain(i.get('page'))} 页）" if i.get("page") else "") for i in items]
                          + ([f"教师补充：{plain(manual)}"] if manual else []))
        else:
            model.para(record.get("iep_status_label") or "本课未关联 IEP 支持条件", "note")
        metrics = record.get("video_metrics") if isinstance(record.get("video_metrics"), dict) else {}
        model.heading("视频指标汇总", 3)
        pct = lambda v: "—" if v is None else f"{round(float(v) * 100)}%"  # noqa: E731
        model.table(["指标", "片段数", "时长（秒）", "时长占比"], [
            [label, plain(metrics.get(f"{key}_segments", "—")), plain(metrics.get(f"{key}_seconds", "—")),
             pct(metrics.get(f"{key}_ratio"))]
            for key, label in (("engaged", "稳定参与"), ("low_response", "回应偏低"), ("away", "离开或不可见"),
                               ("not_observed", "未观察"))], [2, 1, 1, 1])
        ref = metrics.get("participation_score_ref")
        model.para(f"参与得分参考：{'—' if ref is None else number(ref, 1)} / 10（视频线索参考，不直接计入综合分）", "note")
        segments = [s for s in record.get("evidence_segments") or [] if isinstance(s, dict)]
        model.heading("证据片段时间点", 3)
        if segments:
            model.table(["时间段", "片段状态"], [[f"{mmss(s.get('start_sec'))}–{mmss(s.get('end_sec'))}", s.get("state_label") or "—"]
                                           for s in segments], [1, 3])
        else:
            model.para("暂无证据片段", "note")
        if record.get("lesson_summary"):
            model.heading("本课总结", 3)
            model.paras(record["lesson_summary"])
    if record.get("evidence"):
        model.heading("观察记录摘要", 1)
        model.paras(record["evidence"])
    if len(trend_points) > 1:
        model.heading("历史趋势（同目标/条件/标准）", 1)
        scored = sum(1 for p in trend_points if p.get("score") is not None)
        if scored >= 2:
            model.image(line_chart(trend_points, float(scale_max),
                                   float((rubric.get("scale") or {}).get("pass_score") or 6)),
                        "图：历次已复核综合分（虚线为 6 分参考线，空心点表示未达评分条件或未复核，非得分为零）")
        else:
            model.para("至少需要 2 次已复核记录才能看趋势", "note")
        model.table(["日期", "综合分", "复核"], [[date_text(p.get("date")), number(p.get("score")) if p.get("score") is not None else "空缺",
                                             "已复核" if p.get("reviewed") else "未复核"] for p in trend_points], [2, 1, 1])
        model.para("仅相同目标、测量条件、通过标准及量表版本的记录参与比较。空缺表示该课次未达评分条件或未复核，非得分为零。", "note")
    model.heading("评分说明", 1)
    model.paras(SCORING_NOTE)
    model.para(f"量表版本：{plain(record.get('rubric_version') or '—')}　更新时间：{date_text(record.get('updated_at'))}", "note")
    model.heading("使用边界声明", 1)
    model.paras(BOUNDARY_TEXT)
    return model


def measurement_filename(record: dict[str, Any], student_name: str, fmt: str) -> str:
    student = safe_filename_part(student_name, "学生", 20)
    goal = safe_filename_part(record.get("goal_id"), "目标", 20)
    day = safe_filename_part(str(record.get("lesson_date") or "")[:10], datetime.now().strftime("%Y-%m-%d"), 10)
    return f"WeGlow_测量报告_{student}_{goal}_{day}.{fmt}"


def content_disposition(filename: str) -> str:
    """RFC 5987/6266: ASCII fallback plus UTF-8 encoded Chinese name."""
    from urllib.parse import quote

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    ascii_name = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9._-]+", "_", filename)).strip("_") or f"report.{ext}"
    if not re.search(r"[A-Za-z0-9]", ascii_name.rsplit(".", 1)[0]):
        ascii_name = f"WeGlow_report.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
