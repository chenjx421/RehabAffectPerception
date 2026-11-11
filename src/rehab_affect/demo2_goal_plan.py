"""Teacher-facing long-term → short-term goal decomposition workspace.

Prototype boundary: the generated rows are rule-based drafts. A special-education
teacher must edit and confirm them before they are used for instruction or
assessment. The school's evaluation indicators are shown read-only for reference.
"""
from __future__ import annotations

import html
import json
from typing import Any

from .demo2_portal import _COMMON_STYLE, _WORKSPACE_STYLE
from .demo2_ui_kit import UI_KIT_SCRIPT, UI_KIT_STYLE, teacher_header


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


RUBRIC = {
    "课堂教学-基本评价指标": [
        ("教学目标与教学要求", "教学目标落实课标要求，结合学生实际，体现差异性", "20%"),
        ("教学目标与教学要求", "教学目标关注学生学习经历", ""),
        ("教学内容与教学组织", "教学内容正确、科学，密度容量恰当", "30%"),
        ("教学内容与教学组织", "教学重点突出，难点有突破", ""),
        ("教学内容与教学组织", "教学组织有序，教学环节清晰、紧凑", ""),
        ("教学过程与教学效果", "教学方法与手段恰当；资源运用合理，信息技术支持有效", "30%"),
        ("教学过程与教学效果", "师生互动，学生主动参与，态度积极，活动面广", ""),
        ("教学过程与教学效果", "教学目标落实，教学效果良好", ""),
        ("教师基本素养与教学技艺", "教态亲切自然；语言科学；演示熟练；板书规范", "20%"),
        ("教师基本素养与教学技艺", "有良好的课堂掌控能力和信息素养", ""),
    ],
    "课堂评价表（15项 A-D）": [
        ("目标", "整体性：涉及认知、行为、情感领域"),
        ("目标", "针对性：符合学生学习能力，分层要求合理、清晰"),
        ("内容", "科学性：重点突出、容量适宜、内容正确"),
        ("内容", "整合性：符合学生生活经验，注意内容整合"),
        ("过程与方法", "全体性：面向全体，集体/小组/个别结合，分层落实"),
        ("过程与方法", "主体性：学生有主动参与学习和活动的兴趣"),
        ("过程与方法", "实践性：知识学习与生活能力培养结合"),
        ("过程与方法", "合理性：设计层次清楚，方法符合内容和学生实际"),
        ("教师素养", "教学策略：让学生在愉快活动中体验学习"),
        ("教师素养", "教学机智：观察了解学生并及时反馈调节"),
        ("教师素养", "教学技能：语言规范生动，演示操作正确熟练"),
        ("教师素养", "师生关系：耐心，营造和谐轻松氛围"),
        ("学习效果", "即时效果：学生掌握达到预期目标"),
        ("学习效果", "情意发展：情绪愉快、主动参与，能力和个性发展"),
        ("学习效果", "习惯培养：培养良好生活行为和学习习惯"),
    ],
    "生活语文/生活数学课程学习评价": [
        ("学习兴趣", "活动兴趣 / 作业兴趣"),
        ("学习习惯", "听说习惯 / 操作习惯"),
        ("学习效果", "倾听与说话；识字与写字；阅读；综合性学习"),
        ("学习效果（数学）", "常见的量；数与运算；综合与实践"),
        ("评价结果", "A/B/C 层次 + 5/4/3/2/1 计分；综合等第"),
    ],
}

_SUBJECTS = ["生活语文", "生活数学", "生活适应", "劳动技能", "唱游与律动", "绘画与手工", "运动与保健", "信息技术", "康复训练", "艺术休闲"]

# Selected goal descriptors from the ministry curriculum standard (2016 edition).
# This is a reference library, not a prescription for an individual student.
CURRICULUM = {
    "生活语文": {
        "低年级（1–3）": {
            "倾听与说话": [
                "能在别人对自己讲话时注意倾听。",
                "能听懂常用的词语，并作出适当回应。",
                "能听懂简单的句子，并作出适当回应。",
                "能听懂生活中的常用语言。",
                "能模仿运用生活中的常用语言。",
                "能用简短的语言表达个人基本需求。",
                "能使用人称代词（你/我/他）。",
                "能作简单的自我介绍（姓名、班级、家庭成员）。",
                "能在生活情境中进行简单对话。",
                "能听懂生活中常用的普通话，学说普通话。",
            ],
            "识字与写字": [
                "能关注汉字，萌发识字兴趣。",
                "能区别一般图形与汉字。",
                "认读生活中常用汉字 10–50 个。",
                "掌握正确的握笔姿势。",
                "认识汉字的笔画。",
                "能用铅笔描写或抄写生活中常用汉字。",
                "能按从左到右的格式书写。",
            ],
            "阅读": [
                "对书感兴趣，能模仿成人样子看书。",
                "能以基本正确的阅读姿势阅读。",
                "能从图片中找出熟悉的人、物和生活情景。",
                "知道图片上的文字和画面是对应的。",
                "能阅读背景简单的图画，了解大意。",
                "能认识句号、逗号、问号、感叹号。",
                "能用普通话朗读简单句。",
                "会诵读儿歌、古诗 5–10 首。",
                "愿意阅读，感受阅读的乐趣。",
            ],
            "综合性学习": [
                "熟悉班级环境，能与同伴一起交谈，获取有关信息。",
                "观察校园环境，能用自己的方式说出观察所得。",
                "能参加班级、学校活动，初步养成良好的语言行为习惯。",
            ],
        }
    },
    "生活数学": {
        "第一学段（1–3）": {
            "知识技能": [
                "经历从日常生活中认识常见的量的过程，了解日常生活中常见的量。",
                "理解 10 以内数的意义；体会加与减的意义，能计算 10 以内的加法和减法。",
                "认识简单几何体（球）和常见平面图形，初步形成识图能力。",
                "能根据给定的一个标准，对事物做初步的分类。",
            ],
            "数学思考": [
                "了解生活中常见的量，感受常见的量在生活中的作用。",
                "运用 10 以内的数描述现实生活中的简单现象，初步形成数感。",
                "尝试表达自己的想法。",
            ],
            "问题解决": [
                "在教师指导下，通过观察、比较、操作等方法发现简单问题，并尝试解决。",
                "经历与他人合作交流解决问题的过程。",
            ],
            "情感态度": [
                "在他人引导下，感受参与数学学习活动的乐趣。",
                "在他人引导下，感受数学活动中的成功。",
                "感受数学与日常生活的紧密联系。",
            ],
        }
    },
}


def _rubric_html() -> str:
    parts = []
    for title, rows in RUBRIC.items():
        body = "".join(
            f"<tr><td>{_e(cat)}</td><td>{_e(text)}</td><td>{_e(weight)}</td></tr>"
            if len(row) == 3 else f"<tr><td>{_e(cat)}</td><td>{_e(text)}</td><td></td></tr>"
            for row in rows for cat, text, *rest in [(*row, "")] for weight in [rest[0] if rest else ""]
        )
        parts.append(f'<details class="rubric-block"><summary>{_e(title)} <span>{len(rows)} 项</span></summary>'
                     f'<div class="table-wrap"><table><thead><tr><th>维度/项目</th><th>指标/要点</th><th>权重</th></tr></thead><tbody>{body}</tbody></table></div></details>')
    return "".join(parts)


def render_goal_plan(account: dict[str, Any], workspace: dict[str, Any], lesson_goals: list[dict[str, Any]] | None = None, task_id: str = "") -> str:
    students = [s for s in workspace.get("students") or [] if s.get("student_id")]
    students_json = json.dumps(
        [{"student_id": s.get("student_id"), "display_name": s.get("display_name") or "学生",
          "class_name": s.get("class_name") or "", "student_code": s.get("student_code") or ""} for s in students],
        ensure_ascii=False,
    ).replace("</", "<\\/")
    curriculum_json = json.dumps(CURRICULUM, ensure_ascii=False).replace("</", "<\\/")
    lesson_goals_json = json.dumps(lesson_goals or [], ensure_ascii=False).replace("</", "<\\/")
    lesson_goal_options = "".join(
        f'<option value="{_e(g.get("goal_code") or "")}">{_e(g.get("goal_code") or "目标")} · {_e((g.get("description") or "")[:26])}</option>'
        for g in (lesson_goals or []))
    task_note = (f'已载入本课目标 {len(lesson_goals or [])} 条，可把短期目标挂到本课目标。' if task_id else
                 '未指定课堂；先保存目标草案，再从课堂分析页带 task_id 打开本页做本课映射。')
    header = teacher_header("measurement", account, page="measurement")
    options = "".join(
        f'<option value="{_e(s.get("student_id"))}">{_e(s.get("display_name") or "学生")}'
        f'{" · " + _e(s.get("class_name")) if s.get("class_name") else ""}</option>' for s in students)
    if not options:
        options = '<option value="">暂无名册学生，请先到学生名册添加</option>'
    body = f'''<main class="page-shell">
<section class="gp-head"><div><span class="eyebrow">个别化目标 · 教师工作台</span><h1>长期目标拆短期目标</h1>
<p class="lead">先把长期目标拆成可教的短期目标，再挂到本节课的视频证据。这里生成的是<strong>规则草案</strong>，必须由特教老师修改并确认，不能自动替代 IEP。</p></div>
<div class="gp-actions"><a class="button" href="/demo2/long-term?student_id=" id="longTermLink">长期观测</a><a class="button" id="assessmentLink" href="#" hidden>学生综合评估</a><button class="button" id="ownerAcceptBtn" type="button">产品负责人验收</button></div></section>

<div class="gp-due" id="dueBanner" hidden></div>
<section class="gp-card">
  <div class="gp-grid">
    <label>学生<select id="studentSelect">{options}</select></label>
    <label>学科<select id="subjectSelect">{''.join(f'<option>{_e(s)}</option>' for s in _SUBJECTS)}</select></label>
    <label>年级段<select id="gradeSelect"></select></label>
    <label>课标领域<select id="domainSelect"></select></label>
    <label>周期（周）<input id="weeksInput" type="number" min="1" max="36" value="4"></label>
  </div>
  <label class="full">课标目标（选一条作为长期目标来源）<select id="curriculumSelect"></select></label>
  <div class="gp-actions"><button class="button primary" id="applyCurriculumBtn" type="button">用课标目标生成长期目标</button><span class="gp-hint" id="curriculumHint">长期目标仍可修改；课标只提供参考，不是学生个人 IEP。</span></div>
  <label class="full">长期目标（由课标目标生成，可修改）<textarea id="longTerm" rows="3" placeholder="选择课标目标后点“用课标目标生成长期目标”。"></textarea></label>
  <label class="full">当前基线 / 已有能力<textarea id="baseline" rows="2" placeholder="例：能执行一步指令；两步指令需要手势提示。"></textarea></label>
  <div class="gp-actions"><button class="button primary" id="decomposeBtn" type="button">生成短期目标草案</button><button class="button" id="clearBtn" type="button">清空</button><span class="gp-hint" id="statusHint">草案不会自动写入测量；确认后再进入课堂。</span></div>
</section>

<p class="gp-hint" id="taskNote">{task_note}</p>

<section class="gp-card" id="resultCard" hidden>
  <div class="gp-result-head"><div><h2>短期目标草案</h2><p class="lead">每条都应可观察、可计数；不需要的目标直接删除。</p></div><div class="gp-actions"><button class="button" id="addGoalBtn" type="button">新增一条</button><button class="button primary" id="saveBtn" type="button">保存草案</button><button class="button" id="confirmBtn" type="button">教师确认</button><button class="button" id="exportBtn" type="button">导出 JSON</button></div></div>
  <div class="table-wrap"><table class="goal-table"><thead><tr><th>#</th><th>短期目标</th><th>本课目标</th><th>通过标准</th><th>视频/课堂证据</th><th>支持方式</th><th></th></tr></thead><tbody id="goalRows"></tbody></table></div>
  <p class="gp-boundary">边界：本页只做目标拆解草案；IEP 的法定目标、诊断与安置结论仍由学校 IEP 团队确认。</p>
</section>

<section class="gp-card" id="evidenceCard" hidden><h2>本课证据链</h2><p class="lead">短期目标 → 本课目标 → 测量记录。未生成测量或未关联时，会明确标出缺口，不自动补分。</p><div class="table-wrap"><table class="goal-table"><thead><tr><th>短期目标</th><th>本课目标</th><th>测量状态</th><th>综合分</th><th>视频证据</th></tr></thead><tbody id="evidenceRows"></tbody></table></div><p class="gp-boundary">视频证据只指向该学生在本课的片段；教师未复核的记录不会显示为达成。</p></section>

<section class="gp-card"><h2>学校评价指标（只读参考）</h2><p class="lead">来自学校提供的课堂教学基本评价指标、课堂评价表和二年级生活语文/生活数学课程学习评价表。用于检查目标是否可评价，不直接生成分数。</p><p class="gp-boundary">课标目标来源：教育部《培智学校义务教育课程标准（2016年版）》。课标提供的是课程目标参考，不是学生个人 IEP；已确认的草案仍需特教老师按学生基线复核。</p>{_rubric_html()}</section>
</main>'''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>长期目标拆短期目标 · WeGlow</title><style>{_COMMON_STYLE}{_WORKSPACE_STYLE}
:root{{--ink:#172b4d;--muted:#5f7186;--line:#dbe5ef;--blue:#1f63c6;--pale:#eef5ff;--bg:#f6f8fb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.page-shell{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:28px 0 60px}}
.gp-head{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:16px}}h1{{font-size:28px;margin:2px 0}}h2{{font-size:18px;margin:0 0 8px}}.lead{{color:var(--muted);margin:0 0 10px}}
.eyebrow{{font-size:11px;letter-spacing:.12em;color:var(--blue);font-weight:800}}
.gp-card{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}}
.gp-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:12px}}label{{display:grid;gap:5px;font-size:13px;color:var(--muted)}}label.full{{margin-top:10px}}select,input,textarea{{font:inherit;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:6px;padding:9px 10px}}textarea{{resize:vertical}}
.gp-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}}
.button{{display:inline-block;border:1px solid var(--line);background:#fff;color:var(--blue);padding:8px 13px;border-radius:6px;text-decoration:none;font-size:13px;cursor:pointer}}.button.primary{{background:var(--blue);border-color:var(--blue);color:#fff}}.button:disabled{{opacity:.45;cursor:not-allowed}}
.gp-hint{{color:var(--muted);font-size:12px}}.gp-due{{background:#fff8ec;border:1px solid #f0c674;color:#8a4b00;border-radius:8px;padding:10px 14px;margin:0 0 12px;font-size:13px}}.gp-result-head{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}}.gp-boundary{{color:var(--muted);font-size:12px;border-left:3px solid #c98a1b;padding-left:10px}}
.table-wrap{{overflow-x:auto}}.goal-table,.rubric-block table{{width:100%;border-collapse:collapse;font-size:13px;min-width:860px}}.goal-table th,.goal-table td,.rubric-block th,.rubric-block td{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}.goal-table th,.rubric-block th{{background:#f4f8fd;color:#3d4e63;font-weight:600}}.goal-table input,.goal-table textarea{{width:100%;min-width:120px;border:1px solid transparent;background:#f8fafc;padding:6px}}.goal-table textarea{{min-height:54px}}.goal-table .idx{{width:34px;color:var(--muted)}}.goal-table .rm{{border:0;background:transparent;color:#b13f3f;cursor:pointer;font-size:18px}}
.rubric-block{{border:1px solid var(--line);border-radius:8px;margin:10px 0;padding:0 12px}}.rubric-block summary{{cursor:pointer;padding:10px 0;font-weight:700}}.rubric-block summary span{{color:var(--muted);font-weight:400;font-size:12px}}.rubric-block .table-wrap{{margin:0 0 12px}}
.status-ok{{color:#0d6042}}.status-warn{{color:#8a4b00}}
@media(max-width:760px){{.gp-grid{{grid-template-columns:1fr}}}}
</style>{UI_KIT_STYLE}</head><body>{header}{body}
<script>window.GP_STUDENTS={students_json};window.GP_CURRICULUM={curriculum_json};window.GP_LESSON_GOALS={lesson_goals_json};window.GP_TASK_ID={json.dumps(task_id, ensure_ascii=False)};</script>
{UI_KIT_SCRIPT}
<script>
(function(){{
  'use strict';
  var students=window.GP_STUDENTS||[];
  var $=function(id){{return document.getElementById(id);}};
  var rows=[];
  function esc(x){{return String(x==null?'':x).replace(/[&<>"']/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];}});}}
  var CURRICULUM=window.GP_CURRICULUM||{{}};
  function curriculumFor(){{var subject=$('subjectSelect').value,grade=$('gradeSelect').value;return (CURRICULUM[subject]||{{}})[grade]||null;}}
  function refreshGrades(){{
    var subject=$('subjectSelect').value,data=CURRICULUM[subject]||{{}},grades=Object.keys(data);
    $('gradeSelect').innerHTML=grades.map(function(g){{return '<option>'+esc(g)+'</option>';}}).join('');
    if(!grades.length){{$('gradeSelect').innerHTML='<option value="">暂无课标条目</option>';}}
    refreshDomains();
  }}
  function refreshDomains(){{
    var data=curriculumFor()||{{}},domains=Object.keys(data);
    $('domainSelect').innerHTML=domains.map(function(d){{return '<option>'+esc(d)+'</option>';}}).join('');
    if(!domains.length)$('domainSelect').innerHTML='<option value="">暂无领域</option>';
    refreshGoals();
  }}
  function refreshGoals(){{
    var data=curriculumFor()||{{}},goals=data[$('domainSelect').value]||[];
    $('curriculumSelect').innerHTML=goals.map(function(g,i){{return '<option value="'+i+'">'+esc(g)+'</option>';}}).join('');
    if(!goals.length)$('curriculumSelect').innerHTML='<option value="">暂无目标，请手动填写长期目标</option>';
    updateCurriculumHint();
  }}
  function updateCurriculumHint(){{
    var data=curriculumFor(),goals=data?data[$('domainSelect').value]||[]:[];
    $('curriculumHint').textContent=data?'已载入课标条目 '+goals.length+' 条；点按钮生成，长期目标仍可修改。':'该学科/年级暂无内置课标条目，请手动填写长期目标。';
  }}
  function selectedStudent(){{var id=$('studentSelect').value;return students.filter(function(s){{return s.student_id===id;}})[0]||null;}}
  function storageKey(){{var s=selectedStudent();return 'weglow-goal-plan:'+(s?s.student_id:'none')+':'+$('subjectSelect').value;}}
  function decompose(longTerm,weeks){{
    var text=(longTerm||'').replace(/^本学期目标\s*[:：]\s*/,'').replace(/（课标.*$/,'').replace(/\s+/g,' ').trim().replace(/[。；;]+$/,'');
    var w=Math.max(1,Math.min(36,parseInt(weeks,10)||4));
    var a=Math.max(1,Math.ceil(w/3)), b=Math.max(1,Math.ceil((w-a)/2)), c=Math.max(1,w-a-b);
    var behavior=/^(能|能够|学会|愿意|参与|做到)/.test(text);
    var core=text.replace(/^(能|能够)/,'');
    function first(){{return behavior?'在教师提示下，能'+core:'在教师提示下完成：'+text;}}
    function second(){{return behavior?'减少提示后，能'+core:'减少提示后完成：'+text;}}
    function third(){{return behavior?'独立做到：能'+core+'，并尝试在新课堂情境中保持':'独立完成：'+text+'，并尝试迁移到新材料/新情境';}}
    return [
      {{goal:first(), criterion:'3 次机会至少 2 次完成；允许视觉/手势提示', evidence:'视频中可选择 1 段包含提示与完成的片段', support:'视觉提示、手势、分段指令', weeks:a, lesson_goal_id:''}},
      {{goal:second(), criterion:'3 次机会至少 2 次完成；提示减少到 1 次', evidence:'视频中教师提示次数与完成情况', support:'仅保留必要口头/视觉提示', weeks:b, lesson_goal_id:''}},
      {{goal:third(), criterion:'3 次机会至少 2 次独立完成；新情境至少 1 次', evidence:'视频中无提示完成或换材料后的片段', support:'自然情境、同伴示范', weeks:c, lesson_goal_id:''}}
    ];
  }}
  var TASK_ID=window.GP_TASK_ID||'';
  function loadEvidence(){{
    if(!TASK_ID||!rows.length){{$('evidenceCard').hidden=true;return;}}
    var s=selectedStudent();if(!s){{$('evidenceCard').hidden=true;return;}}
    fetch('/api/v1/demo2/measurements',{{cache:'no-store',credentials:'same-origin'}})
      .then(function(r){{return r.json();}})
      .then(function(j){{
        var recs=((j.workspace&&j.workspace.records)||[]).filter(function(r){{return r.task_id===TASK_ID&&r.student_id===s.student_id;}});
        var byGoal={{}};recs.forEach(function(r){{byGoal[r.goal_id]=r;}});
        $('evidenceRows').innerHTML=rows.map(function(g){{
          var m=g.lesson_goal_id?byGoal[g.lesson_goal_id]:null;
          var status=m?(m.reviewed?'已复核':(m.assessment&&m.assessment.score!=null?'已评分待复核':'待复核')):'未生成测量';
          var score=m&&m.assessment?m.assessment.score:null;
          var evidence=m?'<a href="/demo2/simple-result?task_id='+encodeURIComponent(TASK_ID)+'">查看本课结果</a>':'—';
          return '<tr><td>'+esc(g.goal||'')+'</td><td>'+esc(g.lesson_goal_id||'未关联本课目标')+'</td><td>'+esc(status)+'</td><td>'+esc(score==null?'—':score)+'</td><td>'+evidence+'</td></tr>';
        }}).join('');
        $('evidenceCard').hidden=false;
      }}).catch(function(){{$('evidenceCard').hidden=true;}});
  }}
  function render(){{
    var host=$('goalRows');host.innerHTML=rows.map(function(r,i){{
      var lessonOptions='<option value="">— 未关联 —</option>'+((window.GP_LESSON_GOALS||[]).map(function(g){{return '<option value="'+esc(g.goal_code||'')+'"'+(r.lesson_goal_id===g.goal_code?' selected':'')+'>'+esc((g.goal_code||'目标')+' · '+((g.description||'').slice(0,24)))+'</option>';}}).join(''));
      return '<tr data-i="'+i+'"><td class="idx">'+(i+1)+'</td>'+
        '<td><textarea data-k="goal">'+esc(r.goal)+'</textarea></td>'+
        '<td><select data-k="lesson_goal_id">'+lessonOptions+'</select></td>'+
        '<td><textarea data-k="criterion">'+esc(r.criterion)+'</textarea></td>'+
        '<td><textarea data-k="evidence">'+esc(r.evidence)+'</textarea></td>'+
        '<td><textarea data-k="support">'+esc(r.support)+'</textarea></td>'+
        '<td><button class="rm" type="button" data-rm="'+i+'" aria-label="删除">×</button></td></tr>';
    }}).join('');
    host.querySelectorAll('[data-k]').forEach(function(el){{el.addEventListener('input',function(){{rows[+el.closest('tr').dataset.i][el.dataset.k]=el.value;}});}});
    host.querySelectorAll('select[data-k="lesson_goal_id"]').forEach(function(el){{el.addEventListener('change',function(){{rows[+el.closest('tr').dataset.i].lesson_goal_id=el.value;loadEvidence();}});}});
    host.querySelectorAll('[data-rm]').forEach(function(btn){{btn.onclick=function(){{rows.splice(+btn.dataset.rm,1);render();}};}});
    setTimeout(loadEvidence,0);
  }}
  function applyPlan(d){{lastPlanId=d.plan_id||'';$('longTerm').value=d.long_term||'';$('baseline').value=d.baseline||'';$('weeksInput').value=d.weeks||4;rows=d.goals||[];$('resultCard').hidden=!rows.length;render();}}
  function loadLocal(){{try{{var raw=localStorage.getItem(storageKey());if(raw){{applyPlan(JSON.parse(raw));return;}}}}catch(e){{}}rows=[];$('resultCard').hidden=true;}}
  function updateAssessmentLink(){{
    var s=selectedStudent(),a=$('assessmentLink'),task=window.GP_TASK_ID||'';
    if(!a)return;if(task&&s){{a.href='/demo2/assessment?task_id='+encodeURIComponent(task)+'&student_id='+encodeURIComponent(s.student_id);a.hidden=false;}}else{{a.hidden=true;}}
    loadDue();
  }}
  function loadDue(){{
    var s=selectedStudent(),box=$('dueBanner');if(!box)return;
    if(!s){{box.hidden=true;return;}}
    fetch('/api/v1/demo2/goal-plans/due',{{cache:'no-store',credentials:'same-origin'}}).then(function(r){{return r.json();}}).then(function(j){{
      var mine=((j.due)||[]).filter(function(d){{return d.student_id===s.student_id;}});
      if(!mine.length){{box.hidden=true;return;}}
      box.textContent='阶段复测提醒：'+mine.map(function(d){{return '第 '+d.week+' 周（'+d.due_date+'，已过 '+d.days_overdue+' 天）';}}).join('；')+'。请在学生测量中补记并复核。';
      box.hidden=false;
    }}).catch(function(){{box.hidden=true;}});
  }}
  function load(){{
    var s=selectedStudent();var lt=$('longTermLink');if(lt)lt.href='/demo2/long-term?student_id='+encodeURIComponent(s?s.student_id:'');updateAssessmentLink();
    if(!s){{rows=[];$('resultCard').hidden=true;return;}}
    var subject=$('subjectSelect').value;
    fetch('/api/v1/demo2/goal-plans?student_id='+encodeURIComponent(s.student_id)+'&subject='+encodeURIComponent(subject),{{cache:'no-store',credentials:'same-origin'}})
      .then(function(r){{return r.json().catch(function(){{return {{}};}}).then(function(j){{if(!r.ok||j.ok===false)throw new Error((j.error&&j.error.message)||'读取目标草案失败');return j;}});}})
      .then(function(j){{if(j.plan){{applyPlan(j.plan);$('statusHint').textContent=j.plan.status==='confirmed'?'已读取教师确认的目标草案。':'已读取目标草案；正式使用前仍需教师确认。';}}else loadLocal();}})
      .catch(function(){{loadLocal();}});
  }}
  function payload(){{return {{student_id:selectedStudent()?selectedStudent().student_id:'',subject:$('subjectSelect').value,weeks:parseInt($('weeksInput').value,10)||4,long_term:$('longTerm').value.trim(),baseline:$('baseline').value.trim(),goals:rows}};}}
  $('subjectSelect').onchange=function(){{refreshGrades();}};
  $('gradeSelect').onchange=function(){{refreshDomains();}};
  $('domainSelect').onchange=function(){{refreshGoals();}};
  $('applyCurriculumBtn').onclick=function(){{
    var data=curriculumFor(),goals=data?data[$('domainSelect').value]||[]:[];
    var idx=parseInt($('curriculumSelect').value,10);
    if(!goals.length||isNaN(idx)||!goals[idx]){{$('curriculumHint').textContent='当前学科/年级没有可选课标条目，请手动填写长期目标。';return;}}
    var goal=goals[idx].replace(/[。；;]+$/,'');
    $('longTerm').value='本学期目标：'+goal+'（课标'+$('gradeSelect').value+'）';
    $('statusHint').textContent='已用课标目标生成长期目标；请按学生基线修改，再生成短期目标。';
    $('statusHint').className='gp-hint status-ok';
  }};
  $('decomposeBtn').onclick=function(){{var t=$('longTerm').value.trim();if(!t){{$('statusHint').textContent='请先填写长期目标。';$('statusHint').className='gp-hint status-warn';return;}}rows=decompose(t,$('weeksInput').value);$('resultCard').hidden=false;render();$('statusHint').textContent='已生成规则草案，请逐条修改并请特教老师确认。';$('statusHint').className='gp-hint status-ok';}};
  $('addGoalBtn').onclick=function(){{rows.push({{goal:'',lesson_goal_id:'',criterion:'3 次机会至少 2 次完成',evidence:'',support:''}});$('resultCard').hidden=false;render();}};
  function persist(status,btn){{
    var data=payload();if(!data.student_id){{$('statusHint').textContent='请先选择学生。';$('statusHint').className='gp-hint status-warn';return;}}
    if(!data.long_term.trim()){{$('statusHint').textContent='请先填写长期目标。';$('statusHint').className='gp-hint status-warn';return;}}
    if(!data.goals.some(function(g){{return g.goal&&g.goal.trim();}})){{$('statusHint').textContent='请至少填写一条短期目标。';$('statusHint').className='gp-hint status-warn';return;}}
    data.status=status;btn.disabled=true;
    fetch('/api/v1/demo2/goal-plans',{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify(data)}})
      .then(function(r){{return r.json().catch(function(){{return {{}};}}).then(function(j){{if(!r.ok||j.ok===false)throw new Error((j.error&&j.error.message)||'保存失败');return j;}});}})
      .then(function(j){{localStorage.setItem(storageKey(),JSON.stringify(data));$('statusHint').textContent=status==='confirmed'?'已保存并经教师确认；可进入课堂目标映射。':'已保存草案；正式使用前仍需教师确认。';$('statusHint').className='gp-hint status-ok';loadEvidence();}})
      .catch(function(e){{$('statusHint').textContent=e.message||'保存失败';$('statusHint').className='gp-hint status-warn';}})
      .then(function(){{btn.disabled=false;}});
  }}
  $('saveBtn').onclick=function(){{persist('draft',$('saveBtn'));}};
  $('confirmBtn').onclick=function(){{persist('confirmed',$('confirmBtn'));}};
  $('ownerAcceptBtn').onclick=async function(){{if(!lastPlanId){{$('statusHint').textContent='请先保存目标草案，再由产品负责人验收。';$('statusHint').className='gp-hint status-warn';return;}}$('ownerAcceptBtn').disabled=true;try{{var r=await fetch('/api/v1/demo2/goal-plans/owner-accept',{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify({{plan_id:lastPlanId}})}});var j=await r.json();if(!r.ok||j.ok===false)throw new Error((j.error&&j.error.message)||'验收失败');$('statusHint').textContent='产品负责人已验收：'+j.owner_accepted_at;$('statusHint').className='gp-hint status-ok';}}catch(e){{$('statusHint').textContent=e.message||'验收失败';$('statusHint').className='gp-hint status-warn';}}finally{{$('ownerAcceptBtn').disabled=false;}}}};
  $('exportBtn').onclick=function(){{var b=new Blob([JSON.stringify(payload(),null,2)],{{type:'application/json'}});var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='goal-plan.json';a.click();URL.revokeObjectURL(a.href);}};
  $('clearBtn').onclick=function(){{rows=[];$('longTerm').value='';$('baseline').value='';$('resultCard').hidden=true;}};
  refreshGrades();
  $('studentSelect').onchange=load;$('subjectSelect').onchange=function(){{refreshGrades();load();}};updateAssessmentLink();
  load();
  var lt=$('longTermLink');if(lt&&selectedStudent())lt.href='/demo2/long-term?student_id='+encodeURIComponent(selectedStudent().student_id);
}})();
</script></body></html>'''
