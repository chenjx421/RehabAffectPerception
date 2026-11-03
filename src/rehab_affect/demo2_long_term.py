"""Long-term observation: one student's lessons, IEP anchor and measurement history.

Read-only teacher view. IEP text is never copied into the timeline; only the
current status/version is shown, and no diagnosis or ability inference is made.
"""
from __future__ import annotations

import html
from collections import OrderedDict

from .demo2_ui_kit import teacher_header


def _e(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _score(value):
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "—"


IEP_LABELS = {
    "available": ("已关联当前 IEP", "ok", "报告与长期观测可以使用当前 IEP 目标与支持条件。"),
    "not_found": ("尚未上传 IEP", "warn", "请先到学生资料中登记授权并上传当前 IEP 摘要；没有 IEP 不能生成正式报告。"),
    "ambiguous": ("存在多份有效 IEP", "warn", "请先核实并只保留一份当前有效的 IEP。"),
    "unavailable": ("IEP 不可用", "warn", "授权已到期/撤回或资料不可用；请重新登记授权后再使用长期观测。"),
}


def render_long_term(account, token: str, student_id: str, workspace: dict, iep: dict) -> str:
    students = workspace.get("students") or []
    student = next((s for s in students if s.get("student_id") == student_id), None)
    if not student:
        return _shell(account, '<main class="page-shell"><p class="empty">未找到该学生，或该学生不在当前学校范围内。</p><a class="button" href="/demo2/students">返回学生名册</a></main>')
    records = [r for r in (workspace.get("records") or []) if r.get("student_id") == student_id]
    records.sort(key=lambda r: (str(r.get("lesson_date") or ""), str(r.get("updated_at") or "")), reverse=True)
    reviewed = [r for r in records if r.get("assessment", {}).get("score") is not None]
    lessons = OrderedDict()
    for r in records:
        key = (r.get("lesson_date") or "", r.get("task_id") or "", r.get("course_name") or r.get("lesson_id") or "")
        lessons.setdefault(key, []).append(r)
    status = str(iep.get("status") or "unavailable")
    label, tone, note = IEP_LABELS.get(status, IEP_LABELS["unavailable"])
    version = ""
    doc = iep.get("iep") if isinstance(iep.get("iep"), dict) else {}
    if doc:
        version = f" · 版本 v{doc.get('version')}" if doc.get("version") is not None else ""
    cards = "".join(
        f'<article class="rx-kpi"><span class="rx-kpi-label">{_e(k)}</span><strong class="rx-kpi-value">{_e(v)}</strong></article>'
        for k, v in (("课程数", len(lessons)), ("测量记录", len(records)), ("已复核", len(reviewed)))
    )
    timeline = []
    for (when, task_id, course), rows in list(lessons.items())[:30]:
        rows_html = []
        for r in rows:
            dims = r.get("scores") if isinstance(r.get("scores"), dict) else {}
            score = (r.get("assessment") or {}).get("score")
            source = {"video": "视频复核", "video_review": "视频复核", "classroom_observation": "现场观察"}.get(str(r.get("source_type")), "教师记录")
            dims_html = "".join(
                f'<span><b>{_e(label)}</b> {_score(dims.get(key))}</span>'
                for key, label in (("accuracy", "准确性"), ("independence", "独立性"), ("consistency", "一致性"), ("transfer", "泛化性"))
            )
            rows_html.append(
                '<div class="lt-record">'
                f'<div><b>{_e(r.get("goal_id") or "未标目标")}</b> {_e(r.get("goal_description") or "")}</div>'
                f'<div class="lt-meta">{_e(source)} · {_e(r.get("measurement_context") or "课堂")} · '
                f'{"已复核" if r.get("reviewed") else "待复核"} · 综合 {_score(score)}</div>'
                f'<div class="lt-dims">{dims_html}</div>'
                '</div>'
            )
        timeline.append(
            f'<article class="lt-lesson"><header><span>{_e(when or "日期未填")}</span>'
            f'<strong>{_e(course or "未命名课程")}</strong>'
            + (f'<a class="button quiet" href="/demo2/simple-result?task_id={_e(task_id)}">课堂结果</a>' if task_id else "")
            + '</header>' + "".join(rows_html) + '</article>'
        )
    empty = '<div class="empty"><p>该学生还没有测量记录。先从课堂视频或现场观察建立第一条记录。</p><a class="button" href="/demo2/measurement?student_id=' + _e(student_id) + '">去学生测量</a></div>'
    body = f'''<main class="page-shell">
<section class="lt-head">
  <div><span class="eyebrow">长期观测 · 教育支持</span>
  <h1>{_e(student.get("display_name") or "学生")}</h1>
  <p class="lead">{_e(student.get("class_name") or "")} {_e(student.get("student_code") or "")}</p></div>
  <a class="button" href="/demo2/measurement?student_id={_e(student_id)}">返回学生测量</a>
</section>
<div class="iep-banner {tone}"><strong>{_e(label)}{_e(version)}</strong><span>{_e(note)}</span>
<a class="button quiet" href="/demo2/dossier?student_id={_e(student_id)}">管理 IEP 与授权</a></div>
<section class="rx-kpi-grid">{cards}</section>
<p class="lt-note">长期观测只汇总教师复核记录，不按视频出现次数推断能力，不做跨学生比较。没有当前 IEP 的记录不能生成正式报告；IEP 更新保留历史版本。</p>
<h2>课程时间轴</h2>
<div class="lt-timeline">{''.join(timeline) if timeline else empty}</div>
</main>'''
    return _shell(account, body)


def _shell(account, body: str) -> str:
    header = teacher_header("measurement", account, page="measurement")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>长期观测 · WeGlow</title><style>
:root{{--ink:#172b4d;--muted:#5f7186;--line:#dbe5ef;--blue:#1f63c6;--blue-pale:#eef5ff;--ok:#0d6042;--warn:#8a4b00;--bg:#f6f8fb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.page-shell{{width:min(1120px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}}
.lt-head{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:18px}}h1{{font-size:28px;margin:2px 0}}h2{{font-size:18px;margin:28px 0 10px}}.lead{{color:var(--muted);margin:0}}
.eyebrow{{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}}
.iep-banner{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-left:4px solid var(--line);background:#fff;padding:12px 16px;border-radius:8px;margin:16px 0}}
.iep-banner.ok{{border-color:#1d9b70;background:#eef9f3}}.iep-banner.warn{{border-color:#c98a1b;background:#fff8ec}}.iep-banner span{{color:var(--muted);font-size:13px}}
.rx-kpi-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}}.rx-kpi{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px}}.rx-kpi-label{{color:var(--muted);font-size:12px}}.rx-kpi-value{{display:block;font-size:26px;line-height:1.2;margin-top:4px}}
.lt-note{{color:var(--muted);font-size:12px;line-height:1.7;border-left:3px solid var(--blue);padding-left:12px}}
.lt-lesson{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:10px 0}}.lt-lesson header{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:8px}}.lt-lesson header span{{color:var(--muted)}}.lt-lesson header a{{margin-left:auto}}
.lt-record{{padding:8px 0;border-bottom:1px dashed var(--line)}}.lt-record:last-child{{border-bottom:0}}.lt-meta{{color:var(--muted);font-size:12px;margin-top:3px}}.lt-dims{{display:flex;gap:14px;flex-wrap:wrap;margin-top:5px;font-size:12px}}.lt-dims span b{{color:var(--muted);font-weight:600}}
.empty{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:24px;text-align:center}}.button{{display:inline-block;border:1px solid var(--line);background:#fff;color:var(--blue);padding:8px 14px;border-radius:6px;text-decoration:none;font-size:13px}}.button.quiet{{background:#fff}}
@media(max-width:720px){{.rx-kpi-grid{{grid-template-columns:1fr}}}}
</style></head><body>{header}{body}</body></html>'''
