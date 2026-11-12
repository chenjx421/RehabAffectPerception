"""Teacher-facing student learning report with evidence images and four review questions."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

import cv2
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

INK = RGBColor(0x17, 0x2B, 0x4D)
BLUE = RGBColor(0x1F, 0x63, 0xC6)
MUTED = RGBColor(0x5F, 0x71, 0x86)
GREEN = RGBColor(0x0D, 0x60, 0x42)
ORANGE = RGBColor(0x9A, 0x5B, 0x00)
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _shade(cell, color: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tc.append(shd)


def _cell(cell, text: Any, *, bold: bool = False, size: float = 8.5, color=INK) -> None:
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


def _font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def _goal_chart(rows: list[dict[str, Any]]) -> BytesIO:
    width, height = 1200, 430
    image = Image.new("RGB", (width, height), "#f7fafd")
    draw = ImageDraw.Draw(image)
    left, top, right = 80, 60, 1130
    draw.text((left, 18), "本课短期目标得分与 6 分参考线", font=_font(24), fill="#172b4d")
    draw.line((left, top, left, height - 60), fill="#9aa9bb", width=1)
    draw.line((left, height - 60, right, height - 60), fill="#9aa9bb", width=1)
    for i in range(0, 11, 2):
        x = left + (right - left) * i / 10
        draw.line((x, top, x, height - 60), fill="#e5edf5", width=1)
        draw.text((x - 8, height - 45), str(i), font=_font(15), fill="#5f7186")
    pass_x = left + (right - left) * 6 / 10
    draw.line((pass_x, top, pass_x, height - 60), fill="#c98a1b", width=2)
    draw.text((pass_x + 5, top + 4), "通过参考 6", font=_font(14), fill="#8a5a0b")
    for index, row in enumerate(rows[:4]):
        y = top + 48 + index * 72
        score = row.get("score")
        draw.text((left - 10, y + 4), f"G-{index + 1:02d}", font=_font(16), fill="#344b60", anchor="ra")
        if isinstance(score, (int, float)):
            end = left + (right - left) * max(0, min(10, float(score))) / 10
            color = "#1f63c6" if float(score) >= 6 else "#c24d4d"
            draw.rounded_rectangle((left + 4, y, max(left + 8, end), y + 28), radius=6, fill=color)
            draw.text((min(end + 8, right - 45), y + 3), _num(score), font=_font(18), fill="#172b4d")
    return _image_bytes(image)


def _engagement_chart(metrics: dict[str, Any]) -> BytesIO:
    width, height = 1200, 390
    image = Image.new("RGB", (width, height), "#f7fafd")
    draw = ImageDraw.Draw(image)
    draw.text((70, 20), "课堂状态线索占比（来自逐人视频窗口）", font=_font(24), fill="#172b4d")
    values = [
        ("稳定参与", metrics.get("engaged_ratio"), "#1d8a5c"),
        ("回应信号较低", metrics.get("low_response_ratio"), "#c98a1b"),
        ("离开/未在座位", metrics.get("away_ratio"), "#c24d4d"),
        ("未被画面捕捉", metrics.get("not_observed_ratio"), "#8797aa"),
    ]
    left, top, right = 240, 85, 1130
    for index, (label, value, color) in enumerate(values):
        y = top + index * 70
        draw.text((70, y + 7), label, font=_font(17), fill="#344b60")
        draw.rounded_rectangle((left, y, right, y + 28), radius=6, fill="#e5edf5")
        ratio = max(0.0, min(1.0, float(value or 0)))
        if ratio:
            draw.rounded_rectangle((left, y, left + (right - left) * ratio, y + 28), radius=6, fill=color)
        draw.text((right + 14, y + 4), _pct(value), font=_font(17), fill="#172b4d")
    return _image_bytes(image)


def _image_bytes(image: Image.Image) -> BytesIO:
    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _evidence_frame(path: str, seconds: float, caption: str) -> BytesIO | None:
    if not path:
        return None
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(seconds)) * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        height, width = frame.shape[:2]
        if width > 1100:
            frame = cv2.resize(frame, (1100, int(height * 1100 / width)))
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle((0, image.height - 52, image.width, image.height), fill=(15, 42, 72, 190))
        draw.text((18, image.height - 38), caption, font=_font(20), fill="#ffffff")
        return _image_bytes(image)
    finally:
        cap.release()


def _plan_goals(plan: dict[str, Any] | None, records: list[dict[str, Any]], lesson_goals: list[dict[str, Any]]):
    lesson = {str(g.get("goal_code") or ""): g for g in lesson_goals if isinstance(g, dict)}
    by_goal = {}
    for record in records:
        by_goal.setdefault(str(record.get("goal_id") or ""), []).append(record)
    rows = []
    for goal in (plan or {}).get("goals") or []:
        lesson_id = str(goal.get("lesson_goal_id") or "")
        matched = by_goal.get(lesson_id, [])
        reviewed = [r for r in matched if r.get("reviewed")]
        scores = [((r.get("assessment") or {}).get("overall_score") if (r.get("assessment") or {}).get("overall_score") is not None
                   else (r.get("assessment") or {}).get("score")) for r in matched if isinstance(r.get("assessment"), dict)]
        scores = [float(s) for s in scores if isinstance(s, (int, float))]
        rows.append({
            "goal": goal.get("goal") or "（未填写）",
            "lesson": (lesson.get(lesson_id) or {}).get("description") or lesson_id or "—",
            "records": matched,
            "reviewed": len(reviewed),
            "score": round(sum(scores) / len(scores), 1) if scores else None,
            "passed": bool(scores and sum(scores) / len(scores) >= 6),
        })
    return rows


def _student_metrics(records: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    task_records = [r for r in records if str(r.get("task_id") or "") == str(task_id)]
    metrics = {}
    for record in task_records:
        value = record.get("video_metrics")
        if isinstance(value, dict) and value:
            metrics = value
            break
    return metrics


def _add_picture(doc, image: BytesIO | None, caption: str, width=Inches(6.4)) -> None:
    if image is None:
        doc.add_paragraph("（本次没有可嵌入的课堂画面；仅保留文字与数据。）").style = "Caption"
        return
    doc.add_picture(image, width=width)
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(caption)
    p.style = "Caption"
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _iep_support(records: list[dict[str, Any]]) -> tuple[list[tuple[str, str, str]], str]:
    wanted = {"support_needs", "teaching_strategies", "precautions", "assessment_methods"}
    seen = set()
    rows = []
    manual = ""
    for record in records:
        if not isinstance(record.get("iep_support"), list):
            continue
        for item in record["iep_support"]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            text = str(item.get("text") or "").strip()
            if category not in wanted or not text or text in seen:
                continue
            seen.add(text)
            rows.append((str(item.get("category_label") or category), text, str(item.get("page") or "")))
            if len(rows) >= 8:
                break
        manual = manual or str(record.get("iep_manual_supplement") or "").strip()
        if len(rows) >= 8:
            break
    return rows, manual


def build_learning_report(*, task: dict[str, Any], student: dict[str, Any], plan: dict[str, Any] | None,
                          lesson_goals: list[dict[str, Any]], records: list[dict[str, Any]],
                          overview: dict[str, Any]) -> bytes:
    task_id = str(task.get("task_id") or "")
    task_records = [r for r in records if str(r.get("task_id") or "") == task_id]
    goals = _plan_goals(plan, task_records, lesson_goals)
    reviewed = [r for r in task_records if r.get("reviewed")]
    goal_scores = [g["score"] for g in goals if isinstance(g.get("score"), (int, float))]
    student_score = round(sum(goal_scores) / len(goal_scores), 1) if goal_scores else None
    source = overview.get("overview") if isinstance(overview, dict) and isinstance(overview.get("overview"), dict) else overview
    conclusion = (source or {}).get("conclusion") or {}
    class_score = conclusion.get("score") if isinstance(conclusion, dict) else (overview.get("class_score") if isinstance(overview, dict) else None)
    grade = ((conclusion.get("grade") or {}).get("label") if isinstance(conclusion, dict) else "") or ""
    metrics = _student_metrics(records, task_id)
    iep_rows, iep_manual = _iep_support(task_records)
    states = Counter(str(r.get("observed_state") or "未标注") for r in task_records)
    state_text = "、".join(f"{k} {v} 条" for k, v in states.most_common(4)) or "暂无状态标注"

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti SC")
    normal.paragraph_format.space_after = Pt(4)

    header = section.header.paragraphs[0]
    header.text = "WeGlow 微光系统 · 学生课堂检测报告"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in header.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = MUTED
    footer = section.footer.paragraphs[0]
    footer.text = "教师复核辅助材料 · 不是正式 IEP 或医学诊断"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in footer.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = MUTED

    p = doc.add_paragraph()
    r = p.add_run("学生课堂检测报告")
    r.bold = True
    r.font.size = Pt(25)
    r.font.color.rgb = INK
    p.paragraph_format.space_after = Pt(2)
    doc.add_paragraph(f"{student.get('display_name') or '学生'} · {student.get('class_name') or '班级未记录'}").runs[0].font.size = Pt(12)
    doc.add_paragraph(f"{task.get('course_name') or '课堂'} · {task.get('lesson_date') or '日期未记录'} · 只读").runs[0].font.color.rgb = MUTED
    doc.add_paragraph(f"本课测量 {len(task_records)} 条，其中已复核 {len(reviewed)} 条。").runs[0].font.color.rgb = MUTED
    doc.add_paragraph()

    # Required point 1: learning state.
    doc.add_heading("1. 本次课程的学习状态", level=1)
    if metrics:
        doc.add_paragraph(
            f"本课共观察到 {_num(metrics.get('observed_seconds'), 0)} 秒；稳定参与 {_pct(metrics.get('engaged_ratio'))}，"
            f"回应信号较低 {_pct(metrics.get('low_response_ratio'))}，离开/未在座位 {_pct(metrics.get('away_ratio'))}，"
            f"未被画面捕捉 {_pct(metrics.get('not_observed_ratio'))}。主要状态线索为“{metrics.get('dominant_state') or '未标注'}”。"
        )
    else:
        doc.add_paragraph("本课没有可用的逐人课堂状态窗口；学习状态只按教师测量记录描述，不补推测。")
    doc.add_paragraph(f"测量记录中的学生状态：{state_text}。")
    _add_picture(doc, _engagement_chart(metrics) if metrics else None, "图 1  本课课堂状态线索占比")

    # Required point 2: goals and score.
    doc.add_heading("2. 本次课程目标是否达成与评分", level=1)
    table_rows = []
    for index, g in enumerate(goals, start=1):
        table_rows.append([
            f"G-{index:02d}", g["goal"], g["lesson"],
            f"{_num(g.get('score'))} / 10" if g.get("score") is not None else "—",
            "达到 6 分参考线" if g.get("passed") else ("未达到 6 分参考线" if g.get("score") is not None else "待补测"),
        ])
    _table(doc, ["目标", "短期目标", "本课目标", "综合分", "判断"], table_rows,
           widths=[1.3, 5.4, 4.4, 2.0, 3.0])
    score_line = f"本课学生短期目标平均分：{_num(student_score)} / 10。"
    if isinstance(class_score, (int, float)):
        score_line += f" 课程总览结论分：{_num(class_score)} {grade}。"
    else:
        score_line += " 课程总览结论分以课程总览页当前结果为准。"
    score_line += "课程结论是班级层面的评价，不等同于学生个人正式成绩。"
    doc.add_paragraph(score_line)
    _add_picture(doc, _goal_chart(goals), "图 2  短期目标得分与 6 分参考线")

    # Required point 3: concentration and score deviations.
    doc.add_heading("3. 集中度线索与评分偏差解释", level=1)
    if metrics:
        low = float(metrics.get("low_response_ratio") or 0)
        engaged = float(metrics.get("engaged_ratio") or 0)
        if low >= 0.4:
            focus_text = "回应信号较低时段占比较高，建议把任务切成更短回合，并在每个回合给一次明确回应机会。"
        elif engaged >= 0.5:
            focus_text = "稳定参与时段占比较高，当前节奏基本能维持参与；可逐步增加等待和迁移任务。"
        else:
            focus_text = "参与与低回应时段接近，建议先稳定任务节奏，再增加目标难度。"
        doc.add_paragraph(
            f"集中度在本报告中只使用“稳定参与 / 回应信号较低 / 离开 / 未捕捉”等课堂状态线索，"
            f"不是注意力诊断，也不把画面变化直接等同学习能力。{focus_text}"
        )
    else:
        doc.add_paragraph("本课没有逐人状态窗口，无法做集中度线索分析；不补造数据。")

    deviation_rows = []
    for index, record in enumerate(reviewed[:3], start=1):
        assessment = record.get("assessment") if isinstance(record.get("assessment"), dict) else {}
        dims = assessment.get("dimensions") if isinstance(assessment.get("dimensions"), dict) else {}
        if not dims:
            continue
        parts = []
        for key, label in (("accuracy", "准确"), ("independence", "独立"), ("consistency", "一致"), ("transfer", "迁移")):
            dim = dims.get(key) if isinstance(dims.get(key), dict) else {}
            score = dim.get("score")
            weight = dim.get("weight_percent")
            if isinstance(score, (int, float)):
                parts.append(f"{label} {_num(score)}（权重 {weight}%，贡献 {_num(score * float(dim.get('weight') or 0), 2)} 分）")
        if parts:
            deviation_rows.append([f"目标 {index}", "；".join(parts), record.get("support_level") or "未标注", record.get("student_response") or "未填写"])
    if deviation_rows:
        _table(doc, ["测量", "四维得分与加权贡献", "支持程度", "学生回应"], deviation_rows,
               widths=[1.6, 9.2, 2.6, 3.0])
        doc.add_paragraph("评分为四维加权结果；低于 6 分的维度是后续教学优先补强项，高于 6 分的维度可以作为保持项，不对学生做横向排名。")
    else:
        doc.add_paragraph("当前没有可解释的四维评分明细；不生成偏差结论。")

    # Required point 4: IEP and long-term planning suggestions.
    doc.add_heading("4. IEP 与长期教学规划建议", level=1)
    long_term = (plan or {}).get("long_term") or "未填写长期目标"
    doc.add_paragraph(f"长期目标：{long_term}")
    if iep_rows:
        doc.add_paragraph("本课 IEP 支持摘要（只列支持方式、教学策略、注意事项和评估方式）：")
        _table(doc, ["类别", "内容", "页码"], [[a, b, c] for a, b, c in iep_rows], widths=[3.2, 10.4, 2.0])
    if iep_manual:
        doc.add_paragraph("教师人工补充：" + iep_manual)
    if goals:
        doc.add_paragraph("短期目标与建议：")
        for index, g in enumerate(goals, start=1):
            score = g.get("score")
            if score is None:
                advice = "尚无已复核测量，先补一次课堂测量，再决定进阶或降阶。"
            elif score >= 6:
                advice = "已达到 6 分参考线，下一阶段可减少提示、增加迁移情境，并保留一次维持性复测。"
            else:
                advice = "暂未达到 6 分参考线，建议拆小步骤、增加视觉提示和重复练习，4 周内再做一次同目标复测。"
            doc.add_paragraph(f"G-{index:02d} {g['goal']}：{advice}")

    base_text = str((plan or {}).get("confirmed_at") or (plan or {}).get("updated_at") or task.get("lesson_date") or "")
    try:
        base = datetime.fromisoformat(base_text.replace("Z", "+00:00")).date()
    except ValueError:
        base = date.today()
    today = date.today()
    stage_parts = []
    for week in (1, 2, 4, 8):
        when = base + timedelta(weeks=week)
        stage_parts.append(f"第 {week} 周 {when.isoformat()}（{'已到期' if when <= today else '待复测'}）")
    doc.add_paragraph("阶段复测建议：" + "；".join(stage_parts) + "。")
    doc.add_paragraph("长期规划建议：把本课未达到 6 分的目标保留在短期计划中，把已达到的目标转入维持/迁移目标；每 4 周复核一次节奏，若连续两次低于 6 分，应降低任务难度或增加支持，而不是简单增加练习量。")

    # Evidence images.
    doc.add_heading("课堂证据帧", level=1)
    chosen = []
    seen_states = set()
    for record in task_records:
        segments = record.get("evidence_segments") if isinstance(record.get("evidence_segments"), list) else []
        for segment in segments:
            state = str(segment.get("state_label") or segment.get("state") or "")
            if state in seen_states:
                continue
            sec = segment.get("start_sec")
            if isinstance(sec, (int, float)):
                chosen.append((float(sec), f"{state} · {int(float(sec)) // 60:02d}:{int(float(sec)) % 60:02d}"))
                seen_states.add(state)
            if len(chosen) >= 2:
                break
        if len(chosen) >= 2:
            break
    video_path = str(task.get("file_path") or "")
    for index, (sec, caption) in enumerate(chosen, start=1):
        image = _evidence_frame(video_path, sec, caption)
        _add_picture(doc, image, f"图 {index + 2}  课堂证据帧：{caption}", width=Inches(5.6))

    doc.add_heading("口径与边界", level=1)
    doc.add_paragraph("本报告用于教师回看、教学改进和家校沟通，不是正式 IEP，不替代特教、医学或心理诊断。")
    doc.add_paragraph("未关联目标、未复核测量、缺失阶段均保留为空缺，不按 0 分补齐；不同学生的分数不用于横向排名。")
    doc.add_paragraph("课堂状态线索来自固定座位视频窗口，可能受遮挡、光线、镜头角度影响；必须由教师结合现场观察复核。")

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
