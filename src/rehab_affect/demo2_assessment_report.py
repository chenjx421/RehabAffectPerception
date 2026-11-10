"""Downloadable one-student evidence-chain report (Word)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _shade(cell, color: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tc.append(shd)


def build_assessment_report(*, task: dict[str, Any], student: dict[str, Any], plan: dict[str, Any] | None,
                           lesson_goals: list[dict[str, Any]], records: list[dict[str, Any]],
                           overview: dict[str, Any]) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")
    normal.paragraph_format.space_after = Pt(3)

    doc.add_paragraph().add_run("WeGlow 微光系统 · 学生证据链").bold = True
    title = doc.add_paragraph()
    run = title.add_run(student.get("display_name") or "学生")
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(15, 42, 72)
    doc.add_paragraph(f"{task.get('course_name') or '课堂'} · {task.get('lesson_date') or '日期未记录'} · 只读报告")

    conclusion = (overview or {}).get("conclusion") or {}
    course_score = conclusion.get("score") if isinstance(conclusion, dict) else None
    grade = ((conclusion.get("grade") or {}).get("label") if isinstance(conclusion, dict) else "") or ""
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, label in enumerate(("目标草案", "本课测量", "已复核", "课程结论")):
        cell = table.rows[0].cells[i]
        cell.text = ""
        r = cell.paragraphs[0].add_run(label)
        r.bold = True
        r.font.size = Pt(8)
        _shade(cell, "E8EEF7")
    vals = [("已确认" if (plan or {}).get("status") == "confirmed" else ("草案" if plan else "未生成")),
            str(len([r for r in records if r.get("task_id") == task.get("task_id")])),
            str(len([r for r in records if r.get("task_id") == task.get("task_id") and r.get("reviewed")])),
            f"{_num(course_score)} {grade}".strip()]
    cells = table.add_row().cells
    for i, value in enumerate(vals):
        cells[i].text = ""
        r = cells[i].paragraphs[0].add_run(value)
        r.font.size = Pt(10)

    doc.add_heading("目标与证据链", level=1)
    goals = (plan or {}).get("goals") or []
    lesson_map = {str(g.get("goal_code") or ""): g for g in lesson_goals if isinstance(g, dict)}
    rec_map = {}
    for record in records:
        if record.get("task_id") == task.get("task_id"):
            rec_map.setdefault(str(record.get("goal_id") or ""), []).append(record)
    gt = doc.add_table(rows=1, cols=5)
    gt.style = "Table Grid"
    headers = ("短期目标", "本课目标", "测量状态", "综合分", "视频证据")
    for i, h in enumerate(headers):
        c = gt.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(8)
        _shade(c, "E8EEF7")
    for g in goals:
        lesson_id = str(g.get("lesson_goal_id") or "")
        lesson = lesson_map.get(lesson_id)
        matched = rec_map.get(lesson_id, []) if lesson_id else []
        scores = [r.get("assessment", {}).get("score") for r in matched if isinstance(r.get("assessment"), dict)]
        vals = [g.get("goal") or "（未填写）", (lesson or {}).get("description") if lesson else (lesson_id or "—"),
                ("已复核" if matched and all(r.get("reviewed") for r in matched) else
                 ("待复核" if matched else ("未关联本课目标" if not lesson_id else "未生成测量"))),
                _num(max([x for x in scores if isinstance(x, (int, float))], default=None)),
                ("有" if matched else "—")]
        cells = gt.add_row().cells
        for i, value in enumerate(vals):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(value)).font.size = Pt(8.5)

    doc.add_heading("阶段复测", level=1)
    base_text = str((plan or {}).get("confirmed_at") or (plan or {}).get("updated_at") or task.get("lesson_date") or "")
    try:
        base = datetime.fromisoformat(base_text.replace("Z", "+00:00")).date()
    except ValueError:
        base = date.today()
    today = date.today()
    for week in (1, 2, 4, 8):
        when = base + timedelta(weeks=week)
        doc.add_paragraph(f"第 {week} 周：{when.isoformat()}（{'已到期' if when <= today else '待复测'}）")

    doc.add_heading("口径与边界", level=1)
    doc.add_paragraph("本报告是教师复核辅助，不是正式 IEP，也不替代特教/临床判断。未关联、未复核或缺失的数据不按 0 分补齐。")
    doc.add_paragraph("课程结论仍是原课程评价与学生目标达成的 60/40 口径；学生短期目标重算只在证据覆盖完整时展示。")
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
