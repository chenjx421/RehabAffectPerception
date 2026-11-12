"""Downloadable IEP plan / teaching-rhythm suggestion report (rule-based draft)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

INK = RGBColor(0x17, 0x2B, 0x4D)
MUTED = RGBColor(0x5F, 0x71, 0x86)
BLUE = RGBColor(0x1F, 0x63, 0xC6)


def _num(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


def _score(value: Any) -> float | None:
    try:
        value = float(value)
        return value if 0 <= value <= 10 else None
    except (TypeError, ValueError):
        return None


def _shade(cell, color):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tc.append(shd)


def _cell(cell, text, *, bold=False, size=8.5, color=INK):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(str(text))
    r.bold = bold
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.name = "Arial"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")


def _table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        _cell(t.rows[0].cells[i], h, bold=True, size=8)
        _shade(t.rows[0].cells[i], "E8EEF7")
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            _cell(cells[i], value)
    if widths:
        for row in t.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    return t


def _build_rows(task_id: str, plan: dict[str, Any] | None, records: list[dict[str, Any]]):
    by_goal = {}
    for record in records:
        if str(record.get("task_id") or "") == task_id:
            by_goal.setdefault(str(record.get("goal_id") or ""), []).append(record)
    rows = []
    for goal in (plan or {}).get("goals") or []:
        lesson_id = str(goal.get("lesson_goal_id") or "")
        matched = by_goal.get(lesson_id, []) if lesson_id else []
        scores = [_score((r.get("assessment") or {}).get("overall_score") if (r.get("assessment") or {}).get("overall_score") is not None else (r.get("assessment") or {}).get("score")) for r in matched]
        scores = [v for v in scores if v is not None]
        avg = round(sum(scores) / len(scores), 1) if scores else None
        rows.append({"goal": goal.get("goal") or "（未填写）", "lesson": lesson_id or "未关联",
                     "score": avg, "matched": matched, "reviewed": sum(1 for r in matched if r.get("reviewed"))})
    return rows


def build_plan_report(*, task: dict[str, Any], student: dict[str, Any], plan: dict[str, Any] | None,
                      lesson_goals: list[dict[str, Any]], records: list[dict[str, Any]]) -> bytes:
    task_id = str(task.get("task_id") or "")
    rows = _build_rows(task_id, plan, records)
    task_records = [r for r in records if str(r.get("task_id") or "") == task_id]
    dates = sorted({str(r.get("lesson_date") or "")[:10] for r in task_records if r.get("lesson_date")})
    scores = [r["score"] for r in rows if isinstance(r.get("score"), (int, float))]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    below = [r for r in rows if isinstance(r.get("score"), (int, float)) and r["score"] < 6]
    base_text = str((plan or {}).get("confirmed_at") or (plan or {}).get("updated_at") or task.get("lesson_date") or "")
    try:
        base = datetime.fromisoformat(base_text.replace("Z", "+00:00")).date()
    except ValueError:
        base = date.today()
    today = date.today()

    doc = Document()
    s = doc.sections[0]
    s.top_margin = Cm(1.6); s.bottom_margin = Cm(1.5); s.left_margin = Cm(1.8); s.right_margin = Cm(1.8)
    n = doc.styles["Normal"]
    n.font.name = "Arial"; n.font.size = Pt(9.5)
    n._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")
    n.paragraph_format.space_after = Pt(4)
    header = s.header.paragraphs[0]
    header.text = "WeGlow 微光系统 · IEP 计划与教学节奏建议"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in header.runs:
        r.font.size = Pt(8); r.font.color.rgb = MUTED
    footer = s.footer.paragraphs[0]
    footer.text = "规则建议草案 · 教师修改后使用 · 不替代正式 IEP"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in footer.runs:
        r.font.size = Pt(8); r.font.color.rgb = MUTED

    p = doc.add_paragraph()
    r = p.add_run("IEP 计划与教学节奏建议")
    r.bold = True; r.font.size = Pt(24); r.font.color.rgb = INK
    doc.add_paragraph(f"{student.get('display_name') or '学生'} · {student.get('class_name') or '班级未记录'}")
    doc.add_paragraph(f"{task.get('course_name') or '课堂'} · {task.get('lesson_date') or '日期未记录'}")
    doc.add_paragraph(f"生成日期：{today.isoformat()} · 学生短期目标均分：{_num(avg)} / 10").runs[0].font.color.rgb = MUTED

    doc.add_heading("一、长期目标与短期目标", level=1)
    doc.add_paragraph(f"长期目标：{(plan or {}).get('long_term') or '未填写'}")
    table_rows = []
    for index, row in enumerate(rows, start=1):
        table_rows.append([f"G-{index:02d}", row["goal"], row["lesson"],
                           f"{_num(row['score'])} / 10" if row["score"] is not None else "—",
                           "已达到 6 分参考线" if (row["score"] or 0) >= 6 else ("低于参考线" if row["score"] is not None else "待补测")])
    _table(doc, ["编号", "短期目标", "本课目标", "当前分", "判断"], table_rows, widths=[1.2, 6.0, 3.6, 2.2, 3.2])

    doc.add_heading("二、学习速度与计划偏差", level=1)
    if len(dates) < 2:
        doc.add_paragraph("目前只有一次可比较的课堂测量，不能计算学习速度，也不能判断快于或慢于原计划。"
                          "建议在 1/2/4/8 周阶段补一次复测，用两次同目标测量差再比较。")
    else:
        doc.add_paragraph(f"目前有 {len(dates)} 个不同课堂日期（{dates[0]} 至 {dates[-1]}），可比较同目标分数变化；"
                          "本报告只描述分差，不把分差直接等同学习能力。")
    if below:
        doc.add_paragraph(f"当前有 {len(below)} 条目标低于 6 分参考线。建议先补最弱维度，不增加新目标；"
                          "连续两次低于参考线时降低任务难度或增加支持。")
    else:
        doc.add_paragraph("当前目标均达到 6 分参考线。下一阶段可减少提示、增加迁移情境，并保留一次维持性复测。")

    doc.add_heading("三、阶段复测安排", level=1)
    stage_rows = []
    for week in (1, 2, 4, 8):
        when = base + timedelta(weeks=week)
        stage_rows.append([f"第 {week} 周", when.isoformat(), "已到期，建议补测" if when <= today else "待复测"])
    _table(doc, ["阶段", "日期", "状态"], stage_rows, widths=[2.2, 4.0, 6.0])

    doc.add_heading("四、教学节奏建议", level=1)
    weakest = "当前最弱维度"
    plan_rows = [
        ["每周", f"围绕“{rows[0]['goal'] if rows else '当前长期目标'}”安排 2 次 10–15 分钟短练；每次只练一个步骤，记录完成/未完成。", "视觉提示、手势、等待时间"],
        ["每月", "第 4 周做一次同目标复测；比较分数和提示等级，不只看一次课堂表现。", "同目标复测、教师观察"],
        ["每季度", "回看长期目标和 1/2/4/8 周记录；保留有效支持，删除无效提示，把已达到目标转为维持/迁移。", "阶段复盘、目标调整"],
        ["每学年", f"围绕长期目标“{(plan or {}).get('long_term') or '未填写'}”安排年度主题；年度结论同时看目标、参与线索和教师观察。", "年度复盘、家校沟通"],
    ]
    _table(doc, ["周期", "建议", "支持/评估"], plan_rows, widths=[2.0, 9.0, 5.0])

    doc.add_heading("五、边界", level=1)
    doc.add_paragraph("本报告由规则草案生成，必须由特教老师结合学生实际修改后使用；不替代正式 IEP、医学或心理诊断。")
    doc.add_paragraph("未复核测量、缺失阶段不按 0 分补齐；不同学生之间不做横向排名。")
    buffer = BytesIO(); doc.save(buffer); return buffer.getvalue()
