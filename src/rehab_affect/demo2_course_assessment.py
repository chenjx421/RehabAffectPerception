"""Course-level evidence summary: per-student goal plans → mapped measurements.

Read-only. It deliberately does not replace the canonical course conclusion; it
shows how much of the student layer is actually evidenced and where gaps remain.
"""
from __future__ import annotations

import html
from typing import Any

from .demo2_portal import _COMMON_STYLE, _WORKSPACE_STYLE
from .demo2_ui_kit import UI_KIT_SCRIPT, UI_KIT_STYLE, teacher_header


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


CSS = """
:root{--ink:#172b4d;--muted:#5f7186;--line:#dbe5ef;--blue:#1f63c6;--bg:#f6f8fb;--ok:#0d6042;--warn:#8a4b00}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.page-shell{width:min(1200px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}
.ca-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:16px}h1{font-size:28px;margin:2px 0}.lead{color:var(--muted);margin:0}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}
.ca-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}.ca-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.ca-kpi{background:#f4f8fd;border:1px solid #e2ebf5;border-radius:8px;padding:10px 12px}.ca-kpi span{display:block;color:var(--muted);font-size:12px}.ca-kpi strong{font-size:20px}
.ca-wrap{overflow-x:auto}.ca-table{width:100%;border-collapse:collapse;font-size:13px;min-width:900px}.ca-table th,.ca-table td{border-bottom:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}.ca-table th{background:#f4f8fd;color:#3d4e63;font-weight:600}.ca-table td.num{text-align:right;font-variant-numeric:tabular-nums}.ca-badge{display:inline-block;padding:2px 7px;border-radius:4px;background:#eef5ff;color:var(--blue);font-size:12px}.ca-badge.ok{background:#eef9f3;color:var(--ok)}.ca-badge.warn{background:#fff8ec;color:var(--warn)}.ca-note{color:var(--muted);font-size:12px;border-left:3px solid var(--blue);padding-left:10px}.ca-link{color:var(--blue);text-decoration:none}
@media(max-width:760px){.ca-kpis{grid-template-columns:1fr 1fr}}
"""


def render_course_assessment(account: dict[str, Any], task: dict[str, Any], students: list[dict[str, Any]],
                             plans_by_student: dict[str, list[dict[str, Any]]], lesson_goals: list[dict[str, Any]],
                             records: list[dict[str, Any]], overview: dict[str, Any]) -> str:
    lesson_ids = {str(g.get("goal_code") or "") for g in lesson_goals if isinstance(g, dict)}
    rows = []
    evidenced_students = 0
    for student in students:
        sid = str(student.get("student_id") or "")
        plans = plans_by_student.get(sid) or []
        plan = next((p for p in plans if p.get("status") == "confirmed"), plans[0] if plans else None)
        goals = (plan or {}).get("goals") or []
        mapped = [g for g in goals if str(g.get("lesson_goal_id") or "") in lesson_ids]
        recs = [r for r in records if r.get("student_id") == sid]
        by_goal = {}
        for r in recs:
            by_goal.setdefault(str(r.get("goal_id") or ""), []).append(r)
        reviewed = [r for g in mapped for r in by_goal.get(str(g.get("lesson_goal_id") or ""), []) if r.get("reviewed")]
        scores = [r.get("assessment", {}).get("score") for r in reviewed if isinstance(r.get("assessment"), dict)]
        plan_attainment = (sum(s for s in scores if isinstance(s, (int, float))) / len(scores) * 10) if scores else None
        if plan_attainment is not None:
            evidenced_students += 1
        status = ("已确认" if (plan or {}).get("status") == "confirmed" else
                  "草案" if plan else "未生成")
        status_cls = "ok" if status == "已确认" else ("warn" if status == "未生成" else "")
        rows.append(
            '<tr><td><strong>%s</strong><br><small>%s</small></td><td><span class="ca-badge %s">%s</span></td>'
            '<td>%d / %d</td><td>%d</td><td>%s</td><td>%s</td><td><a class="ca-link" href="/demo2/assessment?task_id=%s&student_id=%s">学生证据链</a></td></tr>' % (
                _e(student.get("display_name") or "学生"), _e(student.get("class_name") or ""), status_cls, status,
                len(mapped), len(goals), len(reviewed), _num(plan_attainment),
                "有已复核证据" if plan_attainment is not None else "待补",
                _e(task.get("task_id")), _e(sid)))
    conclusion = (overview or {}).get("conclusion") or {}
    course_score = conclusion.get("score") if isinstance(conclusion, dict) else None
    grade = (conclusion.get("grade") or {}).get("label") if isinstance(conclusion, dict) else ""
    body = f'''<main class="page-shell">
<section class="ca-head"><div><span class="eyebrow">课程评估 · 证据总览</span><h1>{_e(task.get("course_name") or "课堂")}</h1>
<p class="lead">{_e(task.get("lesson_date") or "日期未记录")} · 每名学生：目标草案 → 本课目标 → 测量</p></div>
<a class="ca-link" href="/demo2/course-overview?task_id={_e(task.get("task_id"))}">返回课程总览</a></section>
<section class="ca-card"><div class="ca-kpis"><div class="ca-kpi"><span>纳入检测学生</span><strong>{len(students)}</strong></div><div class="ca-kpi"><span>已有复核证据</span><strong>{evidenced_students}</strong></div><div class="ca-kpi"><span>课程评价</span><strong>{_num(course_score)}{" " + _e(grade) if grade else ""}</strong></div><div class="ca-kpi"><span>本课测量记录</span><strong>{len(records)}</strong></div></div></section>
<section class="ca-card"><h2>学生目标证据覆盖</h2><p class="ca-note">“已关联”= 短期目标已挂到本课目标；“已复核”= 对应测量已由教师复核。计划达成分只是已映射测量的平均，不等于正式课程结论；课程总览仍是原 60/40 口径。</p>
<div class="ca-wrap"><table class="ca-table"><thead><tr><th>学生</th><th>目标草案</th><th>已关联 / 短期目标</th><th>已复核测量</th><th>计划达成分（参考）</th><th>状态</th><th></th></tr></thead><tbody>{''.join(rows) if rows else '<tr><td colspan="7">本课还没有学生。</td></tr>'}</tbody></table></div></section>
<section class="ca-card"><h2>结论口径说明</h2><p class="ca-note">课程总览的 71.7 仍由“课程评价 78 × 60% + 学生目标达成 62.2 × 40%”计算；学生目标达成来自课程任务目标，不来自上面的短期目标。要让课程总评按短期目标重算，需要把本表“已复核测量”接入总览公式，并明确缺失学生如何处理。</p>
<p><a class="ca-link" href="/demo2/course-overview?task_id={_e(task.get("task_id"))}">打开课程总览</a></p></section>
</main>'''
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>课程评估证据总览 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}{CSS}</style>{UI_KIT_STYLE}</head><body>{header}{body}{UI_KIT_SCRIPT}</body></html>'''
