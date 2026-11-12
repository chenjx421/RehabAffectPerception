"""IEP goal plan, progress and teaching-rhythm analysis (teacher-facing)."""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from typing import Any

from .demo2_portal import _COMMON_STYLE, _WORKSPACE_STYLE
from .demo2_ui_kit import UI_KIT_SCRIPT, UI_KIT_STYLE, teacher_header

CSS = """
:root{--ink:#172b4d;--muted:#5f7186;--line:#dbe5ef;--blue:#1f63c6;--bg:#f6f8fb;--ok:#0d6042;--warn:#8a4b00;--bad:#9b2c2c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.page-shell{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:26px 0 60px}.pa-head{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;align-items:flex-start;margin-bottom:14px}h1{font-size:27px;margin:2px 0}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}.lead{color:var(--muted);margin:4px 0}.pa-actions{display:flex;gap:8px;flex-wrap:wrap}
.pa-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}.pa-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.pa-kpi{background:#f4f8fd;border:1px solid #e2ebf5;border-radius:8px;padding:10px 12px}.pa-kpi span{display:block;color:var(--muted);font-size:12px}.pa-kpi strong{font-size:21px;display:block}.pa-kpi small{color:var(--muted)}
.pa-goal{border-top:1px solid var(--line);padding:14px 0}.pa-goal:first-of-type{border-top:0}.pa-goal-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}.pa-goal-head strong{font-size:15px}.pa-goal-meta{color:var(--muted);font-size:12px}.pa-pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}.pa-pill.ok{background:#eef9f3;color:var(--ok)}.pa-pill.warn{background:#fff8ec;color:var(--warn)}.pa-pill.bad{background:#fdecec;color:var(--bad)}.pa-bar{height:10px;border-radius:5px;background:#e5edf5;margin:8px 0;position:relative;overflow:hidden}.pa-bar i{display:block;height:100%;border-radius:5px;background:var(--blue)}.pa-bar em{position:absolute;left:60%;top:-2px;height:14px;width:2px;background:#c98a1b}.pa-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pa-box{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:#fbfdff}.pa-box h3{margin:0 0 6px;font-size:15px}.pa-box p{margin:4px 0;color:#344b60;font-size:13px}.pa-box ul{margin:4px 0 0;padding-left:18px;color:#344b60;font-size:13px}.pa-note{color:var(--muted);font-size:12px;border-left:3px solid var(--blue);padding-left:10px}.pa-timeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.pa-step{border:1px solid var(--line);border-radius:8px;padding:10px;background:#f8fafc}.pa-step b{display:block}.pa-step span{font-size:12px;color:var(--muted)}
@media(max-width:800px){.pa-kpis{grid-template-columns:1fr 1fr}.pa-grid{grid-template-columns:1fr}.pa-timeline{grid-template-columns:1fr 1fr}}
"""


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _parse(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _score(value: Any) -> float | None:
    try:
        value = float(value)
        return value if 0 <= value <= 10 else None
    except (TypeError, ValueError):
        return None


def _goal_rows(plan: dict[str, Any] | None, task_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_goal: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("task_id") or "") == task_id:
            by_goal.setdefault(str(record.get("goal_id") or ""), []).append(record)
    rows = []
    for goal in (plan or {}).get("goals") or []:
        lesson_id = str(goal.get("lesson_goal_id") or "")
        matched = by_goal.get(lesson_id, []) if lesson_id else []
        scores = [_score(((r.get("assessment") or {}).get("overall_score") if (r.get("assessment") or {}).get("overall_score") is not None else (r.get("assessment") or {}).get("score"))) for r in matched]
        scores = [s for s in scores if s is not None]
        avg = round(sum(scores) / len(scores), 1) if scores else None
        rows.append({"lesson_id": lesson_id, "goal": goal.get("goal") or "（未填写）", "score": avg,
                     "reviewed": sum(1 for r in matched if r.get("reviewed")), "matched": matched})
    return rows


def _weak_dimensions(records: list[dict[str, Any]]) -> list[tuple[str, float]]:
    labels = {"accuracy": "准确", "independence": "独立", "consistency": "一致", "transfer": "迁移"}
    totals: dict[str, list[float]] = {key: [] for key in labels}
    for record in records:
        dims = ((record.get("assessment") or {}).get("dimensions") or {})
        if not isinstance(dims, dict):
            continue
        for key in totals:
            value = (dims.get(key) or {}).get("score")
            if isinstance(value, (int, float)):
                totals[key].append(float(value))
    values = [(labels[key], sum(vals) / len(vals)) for key, vals in totals.items() if vals]
    values.sort(key=lambda item: item[1])
    return values


def render_plan_analysis(account: dict[str, Any], task: dict[str, Any], student: dict[str, Any],
                         plan: dict[str, Any] | None, lesson_goals: list[dict[str, Any]],
                         records: list[dict[str, Any]]) -> str:
    task_id = str(task.get("task_id") or "")
    rows = _goal_rows(plan, task_id, records)
    scores = [r["score"] for r in rows if isinstance(r.get("score"), (int, float))]
    student_avg = round(sum(scores) / len(scores), 1) if scores else None
    below = [r for r in rows if isinstance(r.get("score"), (int, float)) and r["score"] < 6]
    above = [r for r in rows if isinstance(r.get("score"), (int, float)) and r["score"] >= 6]
    base = _parse((plan or {}).get("confirmed_at") or (plan or {}).get("updated_at") or task.get("lesson_date"))
    today = date.today()
    stages = []
    for week in (1, 2, 4, 8):
        when = (base or today) + timedelta(weeks=week)
        stages.append((week, when, when <= today))
    weak = _weak_dimensions([r for r in records if str(r.get("task_id") or "") == task_id])
    weak_text = "、".join(f"{name} {_num(value)}" for name, value in weak[:2]) if weak else "暂无四维评分"
    task_records = [r for r in records if str(r.get("task_id") or "") == task_id]
    dates = sorted({str(r.get("lesson_date") or "")[:10] for r in task_records if r.get("lesson_date")})
    longitudinal = len(dates) >= 2

    goal_html = []
    for index, item in enumerate(rows, start=1):
        score = item["score"]
        if score is None:
            badge = '<span class="pa-pill warn">待补测</span>'
        elif score >= 6:
            badge = '<span class="pa-pill ok">已达到 6 分参考线</span>'
        else:
            badge = '<span class="pa-pill bad">低于参考线</span>'
        width = max(0, min(100, (score or 0) * 10))
        diff = "—" if score is None else f"{score - 6:+.1f}"
        goal_html.append(f'''<div class="pa-goal"><div class="pa-goal-head"><div><strong>G-{index:02d} {_e(item['goal'])}</strong><div class="pa-goal-meta">本课目标：{_e(item['lesson_id'] or '未关联')} · 已复核 {item['reviewed']} 条</div></div>{badge}</div>
<div class="pa-bar"><i style="width:{width:.1f}%"></i><em></em></div><div class="pa-goal-meta">当前 {_num(score)} / 10，距 6 分参考线 {diff}</div></div>''')

    # Rule-based plan suggestions; no invented numeric velocity.
    weakest = weak[0] if weak else ("暂无", None)
    goal_focus = below[0]["goal"] if below else (rows[0]["goal"] if rows else "当前长期目标")
    score_text = _num(student_avg)
    if not longitudinal:
        speed_text = ("目前只有一次可比较的课堂测量，不能计算学习速度，也不能预测“快于/慢于原计划”；"
                      "先按阶段补一次复测，再用两次测量差判断。")
    else:
        speed_text = f"已有 {len(dates)} 个课堂日期，可比较趋势；本页只显示分差，不把分差直接等同学习能力。"
    if below:
        pace_text = f"当前有 {len(below)} 条目标低于 6 分参考线，建议下一阶段先补最弱维度“{weakest[0]}”，不要同时加新目标。"
    elif above:
        pace_text = "当前目标均达到参考线，下一阶段可降低提示、增加迁移或维持性任务。"
    else:
        pace_text = "当前没有可用评分，先完成一次测量并复核。"

    weekly = [
        f"每周 2 次 10–15 分钟短练，围绕“{goal_focus}”，每次只练一个步骤。",
        f"优先补“{weakest[0]}”维度；提示从视觉/手势开始，完成后逐步撤除。",
        "每次结束用 1 个可观察动作记录“完成/未完成”，不凭印象打分。",
    ]
    monthly = [
        "第 4 周做一次同目标复测，比较分数和提示等级，而不是只看一次课堂表现。",
        "若连续 2 次低于 6 分，降低任务难度或增加支持；若达到 6 分，增加迁移情境。",
    ]
    quarterly = [
        "每季度回看长期目标和 1/2/4/8 周记录，保留有效支持，删除无效提示。",
        "把已达到的目标转为维持目标，把未达到的目标拆成更小步骤。",
    ]
    yearly = [
        f"围绕长期目标“{(plan or {}).get('long_term') or '未填写'}”安排年度主题，不把单节课分数当成年度结论。",
        "年度复盘时同时看目标达成、课堂参与线索和教师观察，三者不一致时以教师复核为准。",
    ]

    stage_html = ""
    for week, when, due in stages:
        state = "已到期" if due else "待复测"
        stage_html += f'<div class="pa-step"><b>第 {week} 周</b><span>{when.isoformat()}</span><br><span>{state}</span></div>'

    def boxes(title: str, items: list[str]) -> str:
        return '<div class="pa-box"><h3>%s</h3><ul>%s</ul></div>' % (
            _e(title), "".join(f"<li>{_e(item)}</li>" for item in items))

    body = f'''<main class="page-shell">
<section class="pa-head"><div><span class="eyebrow">IEP 计划与进度 · 教师工作台</span><h1>{_e(student.get('display_name') or '学生')} · 计划与进度分析</h1>
<p class="lead">{_e(task.get('course_name') or '课堂')} · {_e(task.get('lesson_date') or '日期未记录')} · 规则建议草案，教师修改后使用</p></div>
<div class="pa-actions"><a class="button" href="/demo2/assessment?task_id={_e(task_id)}&student_id={_e(student.get('student_id'))}">学生证据链</a><a class="button" href="/demo2/goal-plan?student_id={_e(student.get('student_id'))}">编辑目标</a><a class="button" href="/demo2/long-term?student_id={_e(student.get('student_id'))}">长期观测</a></div></section>
<section class="pa-card"><div class="pa-kpis"><div class="pa-kpi"><span>学生短期目标均分</span><strong>{score_text}</strong><small>10 分制</small></div><div class="pa-kpi"><span>已达到参考线</span><strong>{len(above)}</strong><small>条目标</small></div><div class="pa-kpi"><span>低于参考线</span><strong>{len(below)}</strong><small>条目标</small></div><div class="pa-kpi"><span>最弱维度</span><strong>{_e(weakest[0])}</strong><small>{_num(weakest[1]) if weakest[1] is not None else '暂无'}</small></div></div></section>
<section class="pa-card"><h2>目标进度</h2><p class="pa-note">6 分是试行参考线，不是正式及格/诊断；缺失测量不按 0 分补齐。</p>{''.join(goal_html) if goal_html else '<p class="pa-note">还没有短期目标。</p>'}</section>
<section class="pa-card"><h2>学习速度与计划偏差</h2><p class="pa-note">{_e(speed_text)}</p><p class="pa-note">{_e(pace_text)}</p>
<div class="pa-timeline">{stage_html}</div></section>
<section class="pa-card"><h2>个案教学节奏建议</h2><p class="pa-note">以下为规则生成的草案，按学生实际接受度调整；不是正式教案，也不替代特教老师设计。</p>
<div class="pa-grid">{boxes('每周', weekly)}{boxes('每月', monthly)}{boxes('每季度', quarterly)}{boxes('每学年', yearly)}</div></section>
<section class="pa-card"><h2>边界</h2><p class="pa-note">学习速度只在有两次以上不同课堂日期的测量时才可比较；本页不伪造预测值。课堂状态线索受遮挡、光线、镜头影响，需教师结合现场观察。</p></section>
</main>'''
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IEP 计划与进度分析 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}{CSS}</style>{UI_KIT_STYLE}</head><body>{header}{body}{UI_KIT_SCRIPT}</body></html>'''
