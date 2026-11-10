"""Read-only class-level learning summary from teacher-reviewed records."""
from __future__ import annotations

import html
from collections import defaultdict
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
.page-shell{width:min(1200px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}.cs-head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start;margin-bottom:16px}h1{font-size:28px;margin:2px 0}.lead{color:var(--muted);margin:0}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}
.cs-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}.cs-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.cs-kpi{background:#f4f8fd;border:1px solid #e2ebf5;border-radius:8px;padding:10px 12px}.cs-kpi span{display:block;color:var(--muted);font-size:12px}.cs-kpi strong{font-size:20px}
.cs-wrap{overflow-x:auto}.cs-table{width:100%;border-collapse:collapse;font-size:13px;min-width:760px}.cs-table th,.cs-table td{border-bottom:1px solid var(--line);padding:9px;text-align:left;vertical-align:top}.cs-table th{background:#f4f8fd;color:#3d4e63;font-weight:600}.cs-table td.num{text-align:right;font-variant-numeric:tabular-nums}.cs-badge{display:inline-block;padding:2px 7px;border-radius:4px;background:#eef5ff;color:var(--blue);font-size:12px}.cs-badge.ok{background:#eef9f3;color:var(--ok)}.cs-badge.warn{background:#fff8ec;color:var(--warn)}.cs-note{color:var(--muted);font-size:12px;border-left:3px solid var(--blue);padding-left:10px}.cs-link{color:var(--blue);text-decoration:none}
@media(max-width:760px){.cs-kpis{grid-template-columns:1fr 1fr}}
"""


def render_class_summary(account: dict[str, Any], workspace: dict[str, Any], plans_by_student: dict[str, list[dict[str, Any]]],
                         class_name: str = "") -> str:
    students = [s for s in workspace.get("students") or [] if s.get("student_id")]
    records = [r for r in workspace.get("records") or [] if isinstance(r, dict)]
    classes = sorted({str(s.get("class_name") or "未分班") for s in students})
    selected = class_name or (classes[0] if classes else "")
    class_students = [s for s in students if str(s.get("class_name") or "未分班") == selected]
    by_student = defaultdict(list)
    for r in records:
        by_student[str(r.get("student_id") or "")].append(r)
    rows = []
    total_reviewed = 0
    total_score = []
    for s in class_students:
        sid = str(s.get("student_id") or "")
        recs = by_student.get(sid, [])
        reviewed = [r for r in recs if r.get("reviewed")]
        scores = [r.get("assessment", {}).get("score") for r in reviewed if isinstance(r.get("assessment"), dict)]
        vals = [v for v in scores if isinstance(v, (int, float))]
        total_reviewed += len(reviewed)
        total_score.extend(vals)
        plans = plans_by_student.get(sid) or []
        plan = next((p for p in plans if p.get("status") == "confirmed"), plans[0] if plans else None)
        plan_status = "已确认" if (plan or {}).get("status") == "confirmed" else ("草案" if plan else "未生成")
        plan_cls = "ok" if plan_status == "已确认" else ("warn" if plan_status == "未生成" else "")
        latest_task = ""
        if recs:
            latest = sorted(recs, key=lambda r: str(r.get("lesson_date") or r.get("updated_at") or ""), reverse=True)[0]
            latest_task = str(latest.get("task_id") or "")
        link = (f'/demo2/assessment?task_id={_e(latest_task)}&student_id={_e(sid)}' if latest_task else "")
        rows.append(
            '<tr><td><strong>%s</strong><br><small>%s</small></td><td><span class="cs-badge %s">%s</span></td>'
            '<td class="num">%d</td><td class="num">%d</td><td class="num">%s</td><td>%s</td></tr>' % (
                _e(s.get("display_name") or "学生"), _e(s.get("student_code") or ""), plan_cls, plan_status,
                len(recs), len(reviewed), _num(sum(vals) / len(vals) if vals else None),
                f'<a class="cs-link" href="{link}">学生证据链</a>' if link else "—"))
    avg = sum(total_score) / len(total_score) if total_score else None
    options = "".join(f'<option value="{_e(c)}"{" selected" if c == selected else ""}>{_e(c)}</option>' for c in classes)
    body = f'''<main class="page-shell">
<section class="cs-head"><div><span class="eyebrow">班级学情 · 教师只读</span><h1>{_e(selected or "班级")}</h1>
<p class="lead">按班级汇总已复核记录和个别化目标覆盖；不做排名，不用未复核数据下结论。</p></div>
<form method="get"><select name="class_name" onchange="this.form.submit()" style="padding:8px;border:1px solid #dbe5ef;border-radius:6px">{options}</select></form></section>
<section class="cs-card"><div class="cs-kpis"><div class="cs-kpi"><span>学生</span><strong>{len(class_students)}</strong></div><div class="cs-kpi"><span>测量记录</span><strong>{sum(len(by_student.get(str(s.get('student_id')), [])) for s in class_students)}</strong></div><div class="cs-kpi"><span>已复核</span><strong>{total_reviewed}</strong></div><div class="cs-kpi"><span>综合分均值</span><strong>{_num(avg)}</strong></div></div></section>
<section class="cs-card"><h2>学生概览</h2><p class="cs-note">目标草案状态来自个别化目标工作台；“测量记录”和“已复核”只统计已有记录。没有记录的显示“—”，不按 0 分处理。</p>
<div class="cs-wrap"><table class="cs-table"><thead><tr><th>学生</th><th>目标草案</th><th>测量记录</th><th>已复核</th><th>综合分均值</th><th>证据链</th></tr></thead><tbody>{''.join(rows) if rows else '<tr><td colspan="6">该班级还没有学生。</td></tr>'}</tbody></table></div></section>
<section class="cs-card"><h2>边界</h2><p class="cs-note">班级学情是教师复盘辅助，不是学生能力排名，也不能替代 IEP 团队判断。综合分均值只对已有已复核记录的学生计算，缺失学生不补 0。</p></section>
</main>'''
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>班级学情 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}{CSS}</style>{UI_KIT_STYLE}</head><body>{header}{body}{UI_KIT_SCRIPT}</body></html>'''
