"""Read-only one-student assessment evidence page.

Shows the chain that the platform can currently prove: curriculum goal → long-term
draft → short-term draft → lesson goal → measurement / video evidence → course
conclusion. Missing links remain visible rather than being filled with a score.
"""
from __future__ import annotations

import html
from typing import Any

from .demo2_portal import _COMMON_STYLE, _WORKSPACE_STYLE
from .demo2_ui_kit import UI_KIT_SCRIPT, UI_KIT_STYLE, teacher_header


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _score(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


CSS = """
:root{--ink:#172b4d;--muted:#5f7186;--line:#dbe5ef;--blue:#1f63c6;--bg:#f6f8fb;--ok:#0d6042;--warn:#8a4b00}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.page-shell{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}
.as-head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start;margin-bottom:16px}h1{font-size:28px;margin:2px 0}h2{font-size:18px;margin:0 0 10px}.lead{color:var(--muted);margin:0}
.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}
.as-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
.as-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.as-kpi{background:#f4f8fd;border:1px solid #e2ebf5;border-radius:8px;padding:10px 12px}.as-kpi span{display:block;color:var(--muted);font-size:12px}.as-kpi strong{font-size:20px}
.as-table{width:100%;border-collapse:collapse;font-size:13px}.as-table th,.as-table td{border-bottom:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}.as-table th{background:#f4f8fd;color:#3d4e63;font-weight:600}.as-status{display:inline-block;padding:2px 7px;border-radius:4px;background:#eef5ff;color:var(--blue);font-size:12px}.as-status.ok{background:#eef9f3;color:var(--ok)}.as-status.warn{background:#fff8ec;color:var(--warn)}
.as-note{color:var(--muted);font-size:12px;border-left:3px solid var(--blue);padding-left:10px}.as-link{color:var(--blue);text-decoration:none}.as-empty{background:#fff;border:1px solid var(--line);border-radius:8px;padding:20px;color:var(--muted)}
@media(max-width:760px){.as-grid{grid-template-columns:1fr 1fr}.as-table{min-width:720px}.as-wrap{overflow-x:auto}}
"""


def render_assessment(account: dict[str, Any], task: dict[str, Any], student: dict[str, Any],
                      plan: dict[str, Any] | None, lesson_goals: list[dict[str, Any]],
                      records: list[dict[str, Any]], overview: dict[str, Any]) -> str:
    lesson_map = {str(g.get("goal_code") or ""): g for g in lesson_goals if isinstance(g, dict)}
    rec_map = {}
    for r in records:
        rec_map.setdefault(str(r.get("goal_id") or ""), []).append(r)
    goals = (plan or {}).get("goals") or []
    rows = []
    for index, g in enumerate(goals, start=1):
        lesson_id = str(g.get("lesson_goal_id") or "")
        lesson = lesson_map.get(lesson_id)
        matched = rec_map.get(lesson_id, []) if lesson_id else []
        if not lesson_id:
            status = '<span class="as-status warn">未关联本课目标</span>'
            score = "—"
            link = "—"
        elif not matched:
            status = '<span class="as-status warn">未生成测量</span>'
            score = "—"
            link = "—"
        else:
            reviewed = all(bool(m.get("reviewed")) for m in matched)
            scores = [m.get("assessment", {}).get("score") for m in matched if isinstance(m.get("assessment"), dict)]
            score = _score(max([s for s in scores if isinstance(s, (int, float))], default=None))
            status = f'<span class="as-status {"ok" if reviewed else "warn"}">{"已复核" if reviewed else "待复核"}</span>'
            link = f'<a class="as-link" href="/demo2/simple-result?task_id={_e(task.get("task_id"))}">本课视频证据</a>'
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                index, _e(g.get("goal") or "（未填写）"),
                _e(lesson.get("description") if lesson else (lesson_id or "—")),
                status, score, link))
    plan_status = (plan or {}).get("status") or "none"
    plan_badge = {"confirmed": "已确认", "draft": "草案，待教师确认", "none": "未生成目标草案"}.get(plan_status, plan_status)
    student_records = [r for r in records if str(r.get("student_id") or "") == str(student.get("student_id") or "")]
    reviewed = [r for r in student_records if r.get("reviewed")]
    conclusion = (overview or {}).get("conclusion") if isinstance(overview, dict) else {}
    course_score = conclusion.get("score") if isinstance(conclusion, dict) else None
    grade = (conclusion.get("grade") or {}).get("label") if isinstance(conclusion, dict) else ""
    body = f'''<main class="page-shell">
<section class="as-head"><div><span class="eyebrow">学生综合评估 · 证据链</span><h1>{_e(student.get("display_name") or "学生")}</h1>
<p class="lead">{_e(task.get("course_name") or "课堂")} · {_e(task.get("lesson_date") or "日期未记录")} · 只读汇总</p></div>
<a class="button" href="/demo2/goal-plan?task_id={_e(task.get("task_id"))}&student_id={_e(student.get("student_id"))}">编辑目标草案</a></section>
<div class="as-grid"><div class="as-kpi"><span>目标草案</span><strong>{_e(plan_badge)}</strong></div><div class="as-kpi"><span>本课测量</span><strong>{len(student_records)} 条</strong></div><div class="as-kpi"><span>已复核</span><strong>{len(reviewed)} 条</strong></div><div class="as-kpi"><span>课程结论</span><strong>{_e(_score(course_score))}{" " + _e(grade) if grade else ""}</strong></div></div>
<section class="as-card"><h2>目标与证据链</h2>
<p class="as-note">链路：长期目标 → 短期目标 → 本课目标 → 测量 → 视频证据。未关联或未复核时明确显示缺口，不自动补分。</p>
<div class="as-wrap"><table class="as-table"><thead><tr><th>#</th><th>短期目标</th><th>本课目标</th><th>测量状态</th><th>综合分</th><th>视频证据</th></tr></thead><tbody>{''.join(rows) if rows else '<tr><td colspan="6">尚未生成并确认短期目标。</td></tr>'}</tbody></table></div></section>
<section class="as-card"><h2>课程结论的来源</h2><p class="as-note">课程评价是教师评分；学生目标达成度来自本课已复核测量。两者合成结论，但当前仍未把每名学生的长期/短期目标自动纳入课程总览；本页只展示已存在的证据。</p>
<p><a class="as-link" href="/demo2/course-overview?task_id={_e(task.get("task_id"))}">打开课程总览</a> · <a class="as-link" href="/demo2/measurement?student_id={_e(student.get("student_id"))}">打开学生测量</a></p></section>
</main>'''
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>学生综合评估 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}{CSS}</style>{UI_KIT_STYLE}</head><body>{header}{body}{UI_KIT_SCRIPT}</body></html>'''
