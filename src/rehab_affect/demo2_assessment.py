"""Read-only one-student assessment evidence page.

Shows the chain that the platform can currently prove: curriculum goal → long-term
draft → short-term draft → lesson goal → measurement / video evidence → course
conclusion. Missing links remain visible rather than being filled with a score.
"""
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta
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
.as-note{color:var(--muted);font-size:12px;border-left:3px solid var(--blue);padding-left:10px}.as-share{margin-top:8px;font-size:12px;background:#f4f8fd;border:1px solid var(--line);border-radius:6px;padding:8px;max-width:560px;word-break:break-all}.as-actions{display:flex;gap:8px;flex-wrap:wrap}.as-link{color:var(--blue);text-decoration:none}.as-empty{background:#fff;border:1px solid var(--line);border-radius:8px;padding:20px;color:var(--muted)}
.as-trend-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:7px 0;border-bottom:1px dashed var(--line)}.as-trend-row>span:first-child{min-width:80px;font-weight:600}.as-point{background:#f4f8fd;border:1px solid #e2ebf5;border-radius:4px;padding:3px 7px;color:var(--muted);font-size:12px}.as-point b{color:var(--ink)}.as-stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.as-stage{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:#f8fafc}.as-stage b{display:block;font-size:16px}.as-stage span{color:var(--muted);font-size:12px}.as-stage em{font-style:normal;color:var(--warn);font-size:12px}@media(max-width:760px){.as-grid{grid-template-columns:1fr 1fr}.as-stages{grid-template-columns:1fr 1fr}.as-table{min-width:720px}.as-wrap{overflow-x:auto}}
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
    base_text = str((plan or {}).get("confirmed_at") or (plan or {}).get("updated_at") or task.get("lesson_date") or "")
    try:
        base_date = datetime.fromisoformat(base_text.replace("Z", "+00:00")).date() if base_text else date.today()
    except ValueError:
        base_date = date.today()
    today = date.today()
    def stage_metrics(week: int) -> tuple[int, str]:
        end = base_date + timedelta(weeks=week)
        start = base_date + timedelta(weeks=0 if week == 1 else {2: 1, 4: 2, 8: 4}[week])
        points = []
        for record in records:
            raw = str(record.get("lesson_date") or record.get("updated_at") or "")[:10]
            try:
                point_date = date.fromisoformat(raw)
            except ValueError:
                continue
            if start < point_date <= end and record.get("reviewed"):
                value = (record.get("assessment") or {}).get("score")
                if isinstance(value, (int, float)):
                    points.append(value)
        return len(points), (_score(sum(points) / len(points)) if points else "—")
    baseline_points = []
    for record in records:
        raw = str(record.get("lesson_date") or record.get("updated_at") or "")[:10]
        try:
            point_date = date.fromisoformat(raw)
        except ValueError:
            continue
        if point_date <= base_date and record.get("reviewed"):
            value = (record.get("assessment") or {}).get("score")
            if isinstance(value, (int, float)):
                baseline_points.append(value)
    baseline_text = (f"基线：{base_date.isoformat()} 及以前已有 {len(baseline_points)} 条已复核测量，均分 {_score(sum(baseline_points) / len(baseline_points))}；阶段窗口从目标确认后开始计算。"
                     if baseline_points else "基线：目标确认前还没有已复核测量；阶段窗口从目标确认后开始计算。")
    stage_cards = []
    for week in (1, 2, 4, 8):
        count, avg = stage_metrics(week)
        stage_cards.append(
            f'<div class="as-stage"><b>第 {week} 周</b><span>{(base_date + timedelta(weeks=week)).isoformat()}</span>'
            f'<span>记录 {count} · 均分 {avg}</span>'
            f'<em>{"已到期待补测" if (base_date + timedelta(weeks=week)) <= today else "待复测"}</em></div>')
    stages = "".join(stage_cards)
    trend_rows = []
    for g in goals:
        lesson_id = str(g.get("lesson_goal_id") or "")
        if not lesson_id:
            continue
        points = [r for r in records if str(r.get("goal_id") or "") == lesson_id]
        points.sort(key=lambda r: str(r.get("lesson_date") or r.get("updated_at") or ""))
        if len(points) <= 1:
            continue
        cells = []
        for r in points:
            score = (r.get("assessment") or {}).get("score")
            cells.append(f'<span class="as-point"><b>{_e(r.get("lesson_date") or "日期未记录")}</b> {_score(score)}</span>')
        trend_rows.append(f'<div class="as-trend-row"><span>{_e(lesson_id)}</span>{"".join(cells)}</div>')
    trend_html = ('<section class="as-card"><h2>跨阶段趋势</h2><p class="as-note">同一目标在不同课堂的测量分；只展示已存在的记录，不推断缺失阶段。</p>'
                  + ''.join(trend_rows) + '</section>' if trend_rows else
                  '<section class="as-card"><h2>跨阶段趋势</h2><p class="as-note">当前只有本课记录，还没有跨课堂趋势；到期补测后会在这里对比。</p></section>')
    plan_status = (plan or {}).get("status") or "none"
    plan_badge = {"confirmed": "已确认", "draft": "草案，待教师确认", "none": "未生成目标草案"}.get(plan_status, plan_status)
    task_records = [r for r in records if str(r.get("task_id") or "") == str(task.get("task_id") or "")]
    student_records = [r for r in task_records if str(r.get("student_id") or "") == str(student.get("student_id") or "")]
    reviewed = [r for r in student_records if r.get("reviewed")]
    conclusion = (overview or {}).get("conclusion") if isinstance(overview, dict) else {}
    course_score = conclusion.get("score") if isinstance(conclusion, dict) else None
    grade = (conclusion.get("grade") or {}).get("label") if isinstance(conclusion, dict) else ""
    body = f'''<main class="page-shell">
<section class="as-head"><div><span class="eyebrow">学生综合评估 · 证据链</span><h1>{_e(student.get("display_name") or "学生")}</h1>
<p class="lead">{_e(task.get("course_name") or "课堂")} · {_e(task.get("lesson_date") or "日期未记录")} · 只读汇总</p></div>
<div class="as-actions"><a class="button" href="/demo2/goal-plan?student_id={_e(student.get("student_id"))}">编辑目标</a><a class="button" href="/demo2/plan-analysis?task_id={_e(task.get("task_id"))}&student_id={_e(student.get("student_id"))}">计划与进度分析</a><a class="button" href="/api/v1/demo2/assessment/report?task_id={_e(task.get("task_id"))}&student_id={_e(student.get("student_id"))}">下载 Word 报告</a><select id="shareRole" aria-label="分享对象"><option value="parent">家长</option><option value="manager">管理者</option></select><button class="button" id="shareBtn" type="button">生成 24 小时分享链接</button><div class="as-share" id="shareResult" hidden></div></div></section>
<div class="as-grid"><div class="as-kpi"><span>目标草案</span><strong>{_e(plan_badge)}</strong></div><div class="as-kpi"><span>本课测量</span><strong>{len(student_records)} 条</strong></div><div class="as-kpi"><span>已复核</span><strong>{len(reviewed)} 条</strong></div><div class="as-kpi"><span>课程结论</span><strong>{_e(_score(course_score))}{" " + _e(grade) if grade else ""}</strong></div></div>
<section class="as-card"><h2>目标与证据链</h2>
<p class="as-note">链路：长期目标 → 短期目标 → 本课目标 → 测量 → 视频证据。未关联或未复核时明确显示缺口，不自动补分。</p>
<div class="as-wrap"><table class="as-table"><thead><tr><th>#</th><th>短期目标</th><th>本课目标</th><th>测量状态</th><th>综合分</th><th>视频证据</th></tr></thead><tbody>{''.join(rows) if rows else '<tr><td colspan="6">尚未生成并确认短期目标。</td></tr>'}</tbody></table></div></section>
<section class="as-card"><h2>阶段复测排程（草案）</h2><p class="as-note">从目标确认/更新日期起算 1、2、4、8 周；显示该阶段窗口内已复核记录的均分，不把缺失阶段补 0。到期后请在学生测量中补记并复核。</p><p class="as-note">{_e(baseline_text)}</p><div class="as-stages">{stages}</div></section>
{trend_html}
<section class="as-card"><h2>课程结论的来源</h2><p class="as-note">课程评价是教师评分；学生短期目标达成来自已映射且已复核的测量。5/5 名学生都有短期目标证据时，课程总览已正式按“课程评价 60% + 短期目标达成 40%”计算；证据不全时保留原口径并标记缺口。</p>
<p><a class="as-link" href="/demo2/course-overview?task_id={_e(task.get("task_id"))}">打开课程总览</a> · <a class="as-link" href="/demo2/measurement?student_id={_e(student.get("student_id"))}">打开学生测量</a></p></section>
</main>'''
    task_json = json.dumps(str(task.get("task_id") or ""), ensure_ascii=False)
    student_json = json.dumps(str(student.get("student_id") or ""), ensure_ascii=False)
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>学生综合评估 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}{CSS}</style>{UI_KIT_STYLE}</head><body>{header}{body}{UI_KIT_SCRIPT}<script>
(function(){{
  var btn=document.getElementById('shareBtn'),box=document.getElementById('shareResult');
  if(!btn)return;
  btn.addEventListener('click',function(){{
    btn.disabled=true;box.hidden=true;
    fetch('/api/v1/demo2/assessment/share',{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify({{task_id:{task_json},student_id:{student_json},role:(document.getElementById('shareRole')||{{}}).value||'parent'}})}})
      .then(function(r){{return r.json().catch(function(){{return {{}};}}).then(function(j){{if(!r.ok||j.ok===false)throw new Error((j.error&&j.error.message)||'生成失败');return j;}});}})
      .then(function(j){{var token=j.url.split('/').pop(),url=location.origin+j.url;box.innerHTML='24 小时只读报告链接（'+((document.getElementById('shareRole')||{{}}).value==='manager'?'管理者':'家长')+'）：<a href="'+url+'" target="_blank" rel="noopener">'+url+'</a> <button type="button" id="revokeShareBtn">撤销链接</button><br><small>拿到链接的人无需登录即可下载 Word 报告；到期自动失效。</small>';box.hidden=false;var rb=document.getElementById('revokeShareBtn');if(rb)rb.onclick=function(){{rb.disabled=true;fetch('/api/v1/demo2/assessment/share/revoke',{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify({{token:token}})}}).then(function(r){{return r.json();}}).then(function(x){{if(!x.ok)throw new Error('撤销失败');box.textContent='链接已撤销，旧链接立即失效。';}}).catch(function(e){{rb.disabled=false;box.textContent=e.message||'撤销失败';}});}};}})
      .catch(function(e){{box.textContent=e.message||'生成失败';box.hidden=false;}})
      .then(function(){{btn.disabled=false;}});
  }});
}})();
</script></body></html>'''
