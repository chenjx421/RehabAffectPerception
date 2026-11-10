"""One searchable place to find every teacher action, without hunting through tabs."""
from __future__ import annotations

import html

from .demo2_portal import _document
from .demo2_ui_kit import teacher_header


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


STYLE = r"""
.find-wrap{max-width:980px;margin:0 auto;padding:24px 16px 64px}
.find-head h1{font-size:27px;margin:4px 0 6px;color:var(--rx-ink)}
.find-head p{color:var(--muted);margin:0 0 16px}
.find-search{display:flex;gap:8px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 14px;box-shadow:0 4px 14px rgba(20,50,90,.06);position:sticky;top:12px;z-index:5}
.find-search input{flex:1;border:0;outline:0;font:inherit;min-height:36px;background:transparent}
.find-search kbd{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.find-group{margin-top:22px}.find-group h2{font-size:15px;color:var(--muted);margin:0 0 8px;font-weight:700}
.find-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.find-card{display:flex;flex-direction:column;gap:4px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;text-decoration:none;color:inherit;min-height:92px}
.find-card:hover{border-color:var(--blue);box-shadow:0 4px 14px rgba(31,99,198,.12)}
.find-card strong{font-size:14px;color:var(--rx-ink)}.find-card span{font-size:12px;color:var(--muted);line-height:1.5}
.find-list{display:grid;gap:8px}.find-row{display:flex;gap:10px;align-items:center;justify-content:space-between;background:#fff;border:1px solid var(--line);border-radius:9px;padding:10px 12px;flex-wrap:wrap}
.find-row strong{font-size:13px}.find-row small{color:var(--muted);font-size:12px}.find-row .acts{display:flex;gap:6px;flex-wrap:wrap}
.find-empty{color:var(--muted);font-size:13px;padding:16px;text-align:center}
@media(max-width:760px){.find-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:460px){.find-grid{grid-template-columns:1fr}.find-search{position:static}}
"""


def render_find(account) -> str:
    body = f'''{teacher_header("home", account, page="find")}
<main class="find-wrap">
  <div class="find-head"><span class="eyebrow">找功能</span><h1>你想做什么？</h1><p>不用记菜单。输入“评课 / 测量 / IEP / 报告 / 手动画框”，或直接点下面的入口。</p></div>
  <label class="find-search"><span aria-hidden="true">⌕</span><input id="findQuery" type="search" placeholder="搜索功能：评课、测量、IEP、报告、手动画框…" aria-label="搜索功能" autocomplete="off"><kbd>直接输入</kbd></label>
  <div id="findResults">
    <section class="find-group" data-group="recent"><h2>继续最近的课</h2><div class="find-list" id="findRecent"><p class="find-empty">正在读取最近课堂…</p></div></section>
    <section class="find-group" data-group="actions"><h2>常用入口</h2><div class="find-grid" id="findActions"></div></section>
    <section class="find-group" data-group="students"><h2>学生</h2><div class="find-list" id="findStudents"><p class="find-empty">正在读取学生名册…</p></div></section>
  </div>
  <p class="find-empty" id="findNoMatch" hidden>没有找到匹配项，换个词试试，或从上面的常用入口进入。</p>
</main>'''
    script = r"""
'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const actions=[
 {k:'workbench',t:'本课工作台',d:'视频与身份 / 测量 / 评课 / 报告 4 步',href:'/demo2/upload',words:'本课 工作台 课堂 任务'},
 {k:'identity',t:'确认学生 / 手动画框',d:'框定 3 个座位，按座位重新分析',href:'/demo2/identity',words:'手动画框 学生 身份 座位 重新分析'},
 {k:'measurement',t:'学生测量',d:'四维评分、纵向趋势、单次报告',href:'/demo2/measurement',words:'测量 评分 趋势 报告'},
 {k:'evaluation',t:'评课',d:'整节课 4 类目 10 条目',href:'/demo2/evaluation',words:'评课 评价 课堂 评分'},
 {k:'longterm',t:'长期观测 / IEP',d:'课程时间轴、IEP 状态、测量记录',href:'/demo2/students',words:'长期 IEP 观测 时间轴 学生'},
 {k:'upload',t:'上传课堂视频',d:'拖入视频，后台分析',href:'/demo2/upload',words:'上传 视频 课堂'},
 {k:'students',t:'学生名册',d:'新增学生、班级和编号',href:'/demo2/students',words:'学生 名册 班级 新增'},
 {k:'help',t:'使用帮助',d:'所有功能、步骤和常见问题',href:'/demo2/help',words:'帮助 教程 说明 常见问题'},
 {k:'school',t:'学校信息',d:'学校归属与目录',href:'/demo2/school',words:'学校 信息 归属'},
 {k:'membership',t:'会员中心',d:'套餐、订单与服务状态',href:'/demo2/membership',words:'会员 套餐 订单'},
];
const card=a=>`<a class="find-card" href="${esc(a.href)}" data-words="${esc((a.t+' '+a.d+' '+a.words).toLowerCase())}"><strong>${esc(a.t)}</strong><span>${esc(a.d)}</span></a>`;
$('findActions').innerHTML=actions.map(card).join('');
const safe=v=>typeof v==='string'&&v.startsWith('/demo2/')&&!v.startsWith('//')?v:'/demo2/upload';
async function load(){
 try{const d=await fetch('/api/v1/demo2/home/summary',{credentials:'same-origin'}).then(r=>r.json());const items=(d.home&&d.home.recent_tasks)||[];const host=$('findRecent');
  host.innerHTML=items.length?items.slice(0,5).map(t=>`<div class="find-row" data-words="${esc((t.course_name||t.filename||'').toLowerCase())}"><div><strong>${esc(t.course_name||t.filename||'未命名课程')}</strong><br><small>${esc(t.filename||'')}</small></div><div class="acts"><a class="rx-btn rx-btn-secondary" href="/demo2/lesson?task_id=${encodeURIComponent(t.task_id)}">本课工作台</a><a class="rx-btn rx-btn-secondary" href="/demo2/identity?task_id=${encodeURIComponent(t.task_id)}">手动画框</a><a class="rx-btn rx-btn-secondary" href="/demo2/simple-result?task_id=${encodeURIComponent(t.task_id)}">结果</a></div></div>`).join(''):'<p class="find-empty">还没有上传课堂视频。<a href="/demo2/upload">去上传</a></p>';
 }catch(e){$('findRecent').innerHTML='<p class="find-empty">最近课堂暂时读取失败。<a href="/demo2/upload">去上传页</a></p>';}
 try{const d=await fetch('/api/v1/demo2/identity/roster',{credentials:'same-origin'}).then(r=>r.json());const ss=(d.roster&&d.roster.students)||(d.workspace&&d.workspace.students)||[];const host=$('findStudents');
  host.innerHTML=ss.length?ss.slice(0,30).map(s=>`<div class="find-row" data-words="${esc((s.display_name+' '+(s.class_name||'')).toLowerCase())}"><div><strong>${esc(s.display_name||'未命名学生')}</strong><br><small>${esc(s.class_name||'')} ${esc(s.student_code||'')}</small></div><div class="acts"><a class="rx-btn rx-btn-secondary" href="/demo2/measurement?student_id=${encodeURIComponent(s.student_id)}">测量</a><a class="rx-btn rx-btn-secondary" href="/demo2/long-term?student_id=${encodeURIComponent(s.student_id)}">长期观测</a><a class="rx-btn rx-btn-secondary" href="/demo2/dossier?student_id=${encodeURIComponent(s.student_id)}">资料 / IEP</a></div></div>`).join(''):'<p class="find-empty">还没有学生。<a href="/demo2/students">去学生名册</a></p>';
 }catch(e){$('findStudents').innerHTML='<p class="find-empty">学生名册暂时读取失败。<a href="/demo2/students">打开学生名册</a></p>';}
}
function filter(){
 const q=($('findQuery').value||'').trim().toLowerCase();let visible=0;
 document.querySelectorAll('.find-card,.find-row').forEach(el=>{const hit=!q||(el.dataset.words||'').includes(q)||el.innerText.toLowerCase().includes(q);el.hidden=!hit;if(hit)visible++;});
 document.querySelectorAll('.find-group').forEach(g=>{g.hidden=!g.querySelector('.find-card:not([hidden]),.find-row:not([hidden])');});
 $('findNoMatch').hidden=!!visible||!q;
}
$('findQuery').addEventListener('input',filter);load();
"""
    return _document(title='找功能', body=body, page_style=STYLE, script=script)
