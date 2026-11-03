"""One lesson, four steps: video/identity, measurement, evaluation, report."""
from __future__ import annotations

import html

from .demo2_ui_kit import teacher_header


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _count(work, key):
    try:
        return int((work.get("summary") or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def render_lesson(account, task_id: str, work: dict, evaluations: list) -> str:
    school = work.get("school_context") or {}
    school_name = school.get("school_name") if isinstance(school, dict) else ""
    summary = work.get("summary") or {}
    people = [p for p in work.get("people") or [] if isinstance(p, dict)]
    media = work.get("media") or {}
    duration = media.get("duration_sec")
    duration_text = f"{int(duration // 60)} 分 {int(duration % 60)} 秒" if isinstance(duration, (int, float)) else "未返回"
    iep_ok = sum(1 for p in people if (p.get("iep_context") or {}).get("status") == "available")
    eval_rows = [e for e in evaluations or [] if isinstance(e, dict)]
    latest_eval = eval_rows[0] if eval_rows else None
    report = work.get("report") if isinstance(work.get("report"), dict) else {}
    ready = bool(report.get("ready"))
    people_links = "".join(
        f'<a class="person" href="/demo2/long-term?student_id={_e(p.get("student_id"))}">'
        f'<b>{_e(p.get("display_name") or "学生")}</b>'
        f'<span>{"IEP 已关联" if (p.get("iep_context") or {}).get("status") == "available" else "IEP 缺失"}</span></a>'
        for p in people[:8]
    )
    steps = [
        ("1", "视频与学生身份", f'视频 {duration_text} · 已确认 {_count(work,"students")} 人 · IEP {iep_ok}/{len(people)}',
         f'<a class="button primary" href="/demo2/identity?task_id={_e(task_id)}">确认学生 / 手动画框</a>'
         f'<a class="button" href="/demo2/video?id={_e(task_id)}">回看原视频</a>'),
        ("2", "学生测量", f'记录 {_count(work,"records")} 条 · 已复核 {_count(work,"reviewed")} · 已评分 {_count(work,"scored")}',
         f'<a class="button primary" href="/demo2/measurement">进入学生测量</a>'),
        ("3", "本课评课", (f'已保存 {len(eval_rows)} 条评价' if eval_rows else "还没有评课记录") + "",
         f'<a class="button primary" href="/demo2/evaluation?task_id={_e(task_id)}">去评课</a>'
         + (f'<a class="button" href="/demo2/evaluation?task_id={_e(task_id)}">查看评价</a>' if latest_eval else "")),
        ("4", "课堂报告", "报告可生成" if ready else "报告待补证据 / 待复核",
         f'<a class="button primary" href="/demo2/simple-result?task_id={_e(task_id)}">查看结果与报告</a>'
         f'<a class="button" href="/demo2/course-overview?task_id={_e(task_id)}">课程总览</a>'),
    ]
    cards = "".join(
        f'<article class="step-card"><div class="step-no">{n}</div><div class="step-main"><h2>{_e(title)}</h2>'
        f'<p>{_e(desc)}</p><div class="step-actions">{actions}</div></div></article>'
        for n, title, desc, actions in steps
    )
    body = f'''<main class="page-shell">
<div class="lesson-head"><div><span class="eyebrow">本课工作台</span><h1>{_e(work.get("course_name") or "课堂")}</h1>
<p>{_e(school_name)} · {_e((work.get("course_id") or task_id))}</p></div>
<a class="button" href="/demo2/upload">返回上传任务</a></div>
<div class="notice">一节课按 4 步走：先确认学生身份（可手动画框），再测量、评课、看报告。没有当前 IEP 的学生不能生成正式报告；IEP 状态可在学生卡片中查看。</div>
<section class="step-grid">{cards}</section>
<section class="people"><h2>本课学生</h2><p class="hint">IEP 缺失的学生仍可保存测量草稿，但正式报告会被阻断。</p><div class="people-row">{people_links or '<span class="muted">尚未确认学生，请先到第 1 步。</span>'}</div></section>
</main>'''
    header = teacher_header("home", account, page="home")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>本课工作台 · WeGlow</title><style>
body{{margin:0;background:#f6f8fb;color:#172b4d;font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.page-shell{{width:min(1120px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}}
.lesson-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}}h1{{font-size:28px;margin:2px 0}}h2{{font-size:17px;margin:0 0 5px}}.eyebrow{{font-size:11px;letter-spacing:.12em;color:#1f63c6;font-weight:800}}
.lesson-head p{{color:#5f7186;margin:0}}.notice{{margin:16px 0;padding:12px 14px;border-left:4px solid #1f63c6;background:#eef5ff;color:#324a67;border-radius:6px;font-size:13px}}
.step-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.step-card{{display:flex;gap:12px;background:#fff;border:1px solid #dbe5ef;border-radius:10px;padding:16px}}
.step-no{{flex:none;display:grid;place-items:center;width:32px;height:32px;border-radius:50%;background:#1f63c6;color:#fff;font-weight:800}}
.step-main{{min-width:0}}.step-main p{{color:#5f7186;font-size:13px;margin:0 0 10px}}.step-actions{{display:flex;gap:8px;flex-wrap:wrap}}
.button{{display:inline-block;border:1px solid #dbe5ef;background:#fff;color:#1f63c6;padding:7px 12px;border-radius:6px;text-decoration:none;font-size:13px}}.button.primary{{background:#1f63c6;color:#fff;border-color:#1f63c6}}
.people{{margin-top:26px}}.people-row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}.person{{display:flex;flex-direction:column;gap:2px;min-width:120px;background:#fff;border:1px solid #dbe5ef;border-radius:8px;padding:10px 12px;text-decoration:none;color:inherit}}.person span{{font-size:12px;color:#5f7186}}.hint,.muted{{font-size:12px;color:#5f7186}}
@media(max-width:760px){{.step-grid{{grid-template-columns:1fr}}}}
</style></head><body>{header}{body}</body></html>'''
