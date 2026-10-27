"""Designed PDF exports for classroom results and dual-track evaluation.

The pilots are called from the HTTP layer when a teacher downloads a result;
the same functions are used for local delivery so the layout stays identical.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"
INK = colors.HexColor("#16233a")
MUTED = colors.HexColor("#5b6b80")
BLUE = colors.HexColor("#1f63c6")
BLUE_SOFT = colors.HexColor("#eaf2fc")
GREEN = colors.HexColor("#17684f")
AMBER = colors.HexColor("#b7791f")
PURPLE = colors.HexColor("#6b46c1")
RED = colors.HexColor("#943e3e")
LINE = colors.HexColor("#dbe4ee")

STATE_COLORS = {
    "参与": GREEN,
    "注意力下降": AMBER,
    "困惑·停滞": PURPLE,
    "成人干扰下不确定": colors.HexColor("#b45309"),
    "无法判断": RED,
}
STATE_KEYS = {
    "参与": "engaged",
    "注意力下降": "low_attention",
    "困惑·停滞": "confused_or_stuck",
    "成人干扰下不确定": "uncertain_adult_interference",
    "无法判断": "uncertain",
}

_TITLE = ParagraphStyle("title", fontName=FONT, fontSize=22, leading=28, textColor=colors.white)
_SUB = ParagraphStyle("sub", fontName=FONT, fontSize=12, leading=18, textColor=colors.HexColor("#dbeafe"))
_H2 = ParagraphStyle("h2", fontName=FONT, fontSize=14, leading=20, textColor=INK, spaceBefore=12, spaceAfter=6)
_BODY = ParagraphStyle("body", fontName=FONT, fontSize=10.5, leading=18, textColor=INK)
_SMALL = ParagraphStyle("small", fontName=FONT, fontSize=9, leading=14, textColor=MUTED)
_CELL = ParagraphStyle("cell", fontName=FONT, fontSize=9, leading=13, textColor=INK)
_CELLH = ParagraphStyle("cellh", fontName=FONT, fontSize=9, leading=13, textColor=colors.white)
_VALUE = ParagraphStyle("value", fontName=FONT, fontSize=16, leading=21, textColor=INK)


def _t(value: Any) -> str:
    return str(value or "").replace("·", "、").replace("→", " 至 ")


def _bar(fraction: float, color, width: float = 88 * mm, height: float = 3.6 * mm) -> Table:
    fraction = max(0.0, min(1.0, fraction))
    filled = width * fraction
    table = Table([["", ""]], colWidths=[filled, width - filled], rowHeights=[height])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), color),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#edf2f7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "RehabAffect · 课堂分析内测版 · 状态为回看线索，不是成绩或诊断")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def _header(story: list, title: str, lines: list[str]) -> None:
    band = Table([[Paragraph(_t(title), _TITLE)]], colWidths=[174 * mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 6 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
    ]))
    meta = Table([[Paragraph(_t(line), _SUB) for line in lines]], colWidths=[174 * mm / len(lines)] * len(lines))
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2b72d2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(band)
    story.append(meta)
    story.append(Spacer(1, 6 * mm))


def _kpi(story: list, items: list[tuple[str, str]]) -> None:
    width = 174 * mm / len(items)
    cells = []
    for label, value in items:
        cells.append([Paragraph(f"<b>{_t(value)}</b>", _VALUE), Paragraph(_t(label), _SMALL)])
    table = Table([cells], colWidths=[width] * len(items))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7fafd")),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))


def _evaluation_box(story: list, evaluation: dict | None) -> None:
    if not evaluation:
        return
    result = evaluation.get("result") or {}
    school = result.get("school") or {}
    enhanced = result.get("enhanced") or {}
    comparison = result.get("comparison") or {}
    rows = [
        [Paragraph("学校轨", _CELL), Paragraph("系统增强轨", _CELL), Paragraph("总差", _CELL), Paragraph("证据差 / 权重差", _CELL)],
        [Paragraph(f"{float(school.get('score_10', 0)):.2f} / 10", _CELL),
         Paragraph(f"{float(enhanced.get('score_10', 0)):.2f} / 10", _CELL),
         Paragraph(f"{float(comparison.get('total_delta', 0)):+.2f}", _CELL),
         Paragraph(f"{float(comparison.get('evidence_delta', 0)):+.2f} / {float(comparison.get('weight_delta', 0)):+.2f}", _CELL)],
    ]
    table = Table(rows, colWidths=[174 * mm / 4] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE_SOFT), ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(Paragraph("本课双轨评价（学校轨与系统增强轨）", _H2))
    story.append(table)
    story.append(Spacer(1, 4 * mm))


def student_pdf(analysis: dict, person: dict, archive: dict | None = None,
                evaluation: dict | None = None) -> bytes:
    name = (archive or {}).get("student_name") or person.get("display_name") or "学生"
    counts = (person.get("state_summary") or {}).get("counts") or {}
    total = max(1, len(person.get("windows") or []))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=f"{name} 课堂结果", author="RehabAffect")
    story: list = []
    _header(story, f"{name} · 课堂结果报告",
            ["课程：室外活动示例课", f"人物：{person.get('display_name', '')}（人工指定为{name}）", "日期：2026-10-27"])
    _kpi(story, [
        ("本课主导状态", person.get("dominant_state_zh", "")),
        ("参与时间片", f"{counts.get('engaged', 0)} / {total}"),
        ("建议回看", f"{(person.get('state_summary') or {}).get('review_required', 0)} 段"),
        ("动作参考值", f"{float(person.get('average_student_score') or 0):.1f}"),
    ])
    story.append(Paragraph("状态分布", _H2))
    rows = []
    for label, color in STATE_COLORS.items():
        count = int(counts.get(STATE_KEYS[label], 0))
        rows.append([Paragraph(_t(label), _CELL), _bar(count / total, color),
                     Paragraph(f"{count} 段 · {count / total * 100:.0f}%", _SMALL)])
    table = Table(rows, colWidths=[30 * mm, 96 * mm, 32 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(table)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("课堂小结（约 1000 字）", _H2))
    for para in ((person.get("lesson_report") or {}).get("text") or "").split("\n"):
        if para.strip():
            story.append(Paragraph(_t(para.replace("&", "&amp;").replace("<", "&lt;")), _BODY))
            story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph("关键片段", _H2))
    rows = [[Paragraph("时间", _CELLH), Paragraph("状态", _CELLH), Paragraph("说明", _CELLH)]]
    for moment in person.get("key_moments") or []:
        rows.append([Paragraph(f"{moment['start_sec']}–{moment['end_sec']} 秒", _CELL),
                     Paragraph(_t(moment.get("state_zh")), _CELL), Paragraph(_t(moment.get("reason")), _CELL)])
    if len(rows) == 1:
        story.append(Paragraph("本节课没有需要特别回看的片段。", _SMALL))
    else:
        table = Table(rows, colWidths=[30 * mm, 26 * mm, 118 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ]))
        story.append(table)
    _evaluation_box(story, evaluation)
    story.append(Paragraph("说明：状态是课堂回看线索，不是成绩、诊断或注意力测评；身份为人工按顺序绑定，不是人脸识别。", _SMALL))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def class_pdf(task: dict, evaluation: dict, references: dict | None = None) -> bytes:
    result = (evaluation or {}).get("result") or {}
    school = result.get("school") or {}
    enhanced = result.get("enhanced") or {}
    comparison = result.get("comparison") or {}
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title="课堂双轨评价报告", author="RehabAffect")
    story: list = []
    _header(story, "课堂双轨评价报告",
            [f"课程：{task.get('course_name') or '课堂视频'}", f"日期：{evaluation.get('lesson_date', '')}",
             f"任务：{str(task.get('task_id', ''))[:12]}…"])
    _kpi(story, [
        ("学校轨", f"{float(school.get('score_10') or 0):.2f} / 10"),
        ("系统增强轨", f"{float(enhanced.get('score_10') or 0):.2f} / 10"),
        ("总差", f"{float(comparison.get('total_delta') or 0):+.2f}"),
        ("复核状态", "已复核" if evaluation.get("reviewed") else "待复核"),
    ])
    story.append(Paragraph("分差来源", _H2))
    table = Table([[Paragraph("证据修正", _CELL), Paragraph(f"{float(comparison.get('evidence_delta') or 0):+.2f}", _CELL),
                    Paragraph("权重调整", _CELL), Paragraph(f"{float(comparison.get('weight_delta') or 0):+.2f}", _CELL)]],
                  colWidths=[30 * mm, 30 * mm, 30 * mm, 84 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7fafd")), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("分类得分", _H2))
    rows = [[Paragraph("分类", _CELLH), Paragraph("学校", _CELLH), Paragraph("系统", _CELLH), Paragraph("权重", _CELLH)]]
    for category in result.get("categories") or []:
        rows.append([Paragraph(_t(category.get("label")), _CELL),
                     Paragraph(f"{float(category.get('school_score') or 0):.2f}", _CELL),
                     Paragraph(f"{float(category.get('enhanced_score') or 0):.2f}", _CELL),
                     Paragraph(f"{float(category.get('school_weight') or 0) * 100:.0f}%", _CELL)])
    table = Table(rows, colWidths=[90 * mm, 24 * mm, 24 * mm, 36 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
    ]))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("逐项对照（学校分 至 系统分）", _H2))
    rows = [[Paragraph("#", _CELLH), Paragraph("评价项", _CELLH), Paragraph("学校", _CELLH),
             Paragraph("系统", _CELLH), Paragraph("差值", _CELLH)]]
    for index, item in enumerate(comparison.get("items") or [], 1):
        rows.append([Paragraph(str(index), _CELL), Paragraph(_t(item.get("label", ""))[:30], _CELL),
                     Paragraph(f"{item.get('school_score', 0):g}", _CELL), Paragraph(f"{item.get('enhanced_score', 0):g}", _CELL),
                     Paragraph(f"{float(item.get('total_delta') or 0):+.2f}", _CELL)])
    table = Table(rows, colWidths=[8 * mm, 112 * mm, 16 * mm, 16 * mm, 22 * mm])
    style = [("BACKGROUND", (0, 0), (-1, 0), BLUE), ("GRID", (0, 0), (-1, -1), 0.35, LINE),
             ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
             ("TOPPADDING", (0, 0), (-1, -1), 1.3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3 * mm)]
    for row_index, item in enumerate(comparison.get("items") or [], 1):
        if abs(float(item.get("total_delta") or 0)) > 0.0001:
            style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#fff7e6")))
    table.setStyle(TableStyle(style))
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("评分依据与参考资料", _H2))
    for index, item in enumerate((references or {}).get("items") or [], 1):
        link = f' <a href="{item["url"]}" color="#1f63c6">原文</a>' if item.get("url") else ""
        story.append(Paragraph(_t(f"{index}. {item['title']}（{item['issuer']} {item.get('year', '')}）：{item['scope']}。{item['note']}") + link, _SMALL))
        story.append(Spacer(1, 1.2 * mm))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_t((references or {}).get("note", "")), _SMALL))
    story.append(Paragraph("说明：双轨对照只用于解释两轨口径差异，不代表教学效果高低，也不用于教师绩效排名。", _SMALL))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
