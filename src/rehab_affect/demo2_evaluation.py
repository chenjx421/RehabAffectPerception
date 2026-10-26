from __future__ import annotations

import json
from typing import Any

from .demo2_portal import _document, _WORKSPACE_STYLE, _account_payload

_API = "/api/v1/demo2"

_EVAL_STYLE = r"""
.eval-heading{margin-bottom:18px;align-items:center}
.eval-heading h1{font-size:26px;letter-spacing:0}
.eval-heading .lead{font-size:14px}
.eval-heading .eyebrow{margin-bottom:4px}
.eval-heading .lead{max-width:760px;margin-top:8px}
.eval-layout{display:grid;grid-template-columns:218px minmax(0,1fr);gap:26px;align-items:start;padding-top:10px}
.eval-sidebar{position:sticky;top:86px;min-width:0}
.sidebar-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--line)}
.sidebar-head h2{font-size:15px;margin:0;color:var(--ink)}
.record-list{display:flex;flex-direction:column;gap:8px;max-height:calc(100vh - 190px);overflow-y:auto;padding-right:3px}
.record-item{position:relative;border:1px solid transparent;border-radius:8px;padding:13px 12px 13px 16px;cursor:pointer;background:rgba(255,255,255,.62);transition:border-color .18s,background .18s,transform .18s}
.record-item::before{content:'';position:absolute;left:0;top:12px;bottom:12px;width:3px;border-radius:4px;background:transparent}
.record-item:hover{border-color:#b5d2ec;background:#fff;transform:translateX(2px)}
.record-item.active{border-color:#b7d7f4;background:#fff;box-shadow:0 8px 20px rgba(31,99,198,.08)}
.record-item.active::before{background:var(--blue)}
.record-item-meta{font-size:11px;color:var(--muted);margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.record-item-title{font-size:13px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--blue-deep)}
.eval-main{display:flex;flex-direction:column;gap:18px;min-width:0;grid-column:2;grid-row:2}
#resultCard{min-width:0;grid-column:2;grid-row:1}
.eval-sidebar{grid-row:1 / span 2}
.form-card{border:0;border-radius:0;box-shadow:none}
.form-card .card-head{padding:22px 26px 18px;background:#f5faff}
.form-card .card-body{padding:24px 26px 26px}
.form-card .card-head h2{font-size:21px;color:var(--blue-deep)}
.form-card .card-head p{max-width:680px}
.review-check{display:flex;align-items:center;gap:10px;margin:18px 0 14px;font-size:14px;color:var(--blue-deep);font-weight:700}
.review-check input{width:20px;min-height:20px;accent-color:var(--blue)}
.category-weights{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:18px 0;font-size:13px}
.category-weights p{margin:0;padding:12px 13px;border-left:3px solid #64a8dd;background:#f5faff;line-height:1.6}
.category-weights p b{display:block;color:var(--blue-deep);margin-bottom:3px}
.result-context{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);line-height:1.7;margin-top:10px}
.result-card{border:0;border-radius:0;box-shadow:none;overflow:hidden}
.result-card .card-head{padding:18px 28px 16px;background:#f0f7ff}
.result-card .card-head h2{font-size:24px;color:var(--blue-deep)}
.result-card .card-body{padding:0 28px 28px}
.result-card .tab-bar{margin-inline:-28px;padding-inline:28px;background:#fff}
.result-meta-line{color:var(--muted);font-size:12px!important;line-height:1.8}
.result-goal{margin-top:10px;font-size:13px;color:var(--muted)}
.result-goal summary{cursor:pointer;color:var(--blue-deep);font-weight:600}
.result-goal p{font-size:13px;line-height:1.7}
.result-focus{display:flex;gap:8px;align-items:flex-start;margin-top:14px;padding:10px 12px;border-left:3px solid #4aa694;background:rgba(255,255,255,.72);color:#315e61;font-size:13px;line-height:1.6}
.form-section{border-bottom:1px solid #e2ebf4;padding-bottom:22px;margin-bottom:22px}
.form-section:last-of-type{border-bottom:0;padding-bottom:0;margin-bottom:0}
.form-section-title{display:flex;align-items:center;gap:9px;font-size:14px;font-weight:700;color:var(--blue-deep);margin:0 0 14px;letter-spacing:0}
.form-section-title::before{content:'';width:6px;height:18px;border-radius:5px;background:#4f9bd5}
.form-grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.form-grid-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.field-wide{grid-column:1/-1}
textarea{width:100%;min-width:0;border:1px solid #c5d3e0;border-radius:7px;padding:9px 11px;background:#fff;color:var(--ink);font:inherit;resize:vertical;min-height:58px}
textarea:hover{border-color:#7fa7cf}textarea:focus{border-color:var(--blue);outline:3px solid rgba(31,99,198,.14)}
.lock-notice{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;margin-top:8px;padding:8px 10px;background:#f6faff;border:1px solid #dcebf8;border-radius:6px}
.lock-notice svg{width:14px;height:14px;flex:none;color:#6e95b6}
.items-table-wrap{overflow-x:auto;border:1px solid #c9dced;border-radius:8px;margin-top:10px;box-shadow:0 4px 12px rgba(29,75,122,.04)}
.items-table{width:100%;min-width:900px;border-collapse:collapse;background:#fff;font-size:13px}
.items-table th{background:#eaf4fd;color:#345a7e;font-size:11px;font-weight:800;padding:11px 10px;border-bottom:1px solid #c9dced;white-space:nowrap;text-align:left;vertical-align:bottom}
.items-table td{padding:10px;border-bottom:1px solid #e7eef5;vertical-align:top}
.items-table tbody tr:nth-child(even){background:#fbfdff}.items-table tbody tr:hover{background:#f3f9ff}
.items-table tr:last-child td{border-bottom:0}
.items-table input[type=number]{min-height:38px;padding:5px 7px;font-size:13px}
.items-table select{min-height:38px;padding:5px 7px;font-size:13px}
.items-table textarea{min-height:48px;padding:6px 7px;font-size:12px}
.score-null{color:#9aabb8;font-size:12px;display:inline-flex;min-height:38px;align-items:center}
.weight-hint{font-size:11px;color:#7a8fa0;display:block;margin-top:3px}
.tab-bar{display:flex;gap:4px;border-bottom:1px solid #cfe0ef;margin-bottom:22px;overflow-x:auto}
.tab-btn{min-height:48px;padding:10px 17px;border:0;border-bottom:3px solid transparent;margin-bottom:-1px;background:transparent;color:var(--muted);font-size:14px;font-weight:800;cursor:pointer;transition:color .18s,background .18s}
.tab-btn:hover{color:var(--blue);background:#f5faff}.tab-btn[aria-selected=true]{color:var(--blue);border-bottom-color:var(--blue);background:#f5faff}
.score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;margin-bottom:20px;background:#f6faff;border-block:1px solid #dbe7f3}
.score-box{border:0;border-right:1px solid #dbe7f3;border-radius:0;padding:18px 20px;background:transparent;text-align:left;min-height:104px}
.score-box:last-child{border-right:0}
.score-box-label{font-size:11px;color:var(--muted);margin-bottom:8px;font-weight:800}
.score-box-value{font-size:30px;font-weight:800;color:var(--blue-deep);font-variant-numeric:tabular-nums;line-height:1.1}
.score-box-sub{font-size:11px;color:var(--muted);margin-top:6px;line-height:1.45}
.score-box.pass{border-color:#a8d8c3;background:#f0faf5}.score-box.pass .score-box-value{color:#137b59}
.score-box.fail{border-color:#efc2be;background:#fff5f4}.score-box.fail .score-box-value{color:#b42318}
.score-box.na{opacity:.7}
.score-line{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:-8px 0 18px;padding:10px 12px;background:#f7fbff;border-left:3px solid #85b8df;color:#496781;font-size:12px}
.unverified-notice{font-size:12px;color:#7b6000;background:#fff8dc;border:1px solid #e8d87a;border-radius:7px;padding:10px 12px;margin-bottom:16px;display:flex;align-items:flex-start;gap:7px;line-height:1.6}
.unverified-notice svg{flex:none;margin-top:1px}
.chart-section{margin-bottom:22px;padding-top:2px}.chart-title{font-size:13px;font-weight:800;color:var(--ink);margin:0 0 10px}.svg-chart{width:100%;height:auto;overflow:visible}
.ref-list{display:flex;flex-direction:column;gap:12px}.ref-item{border:1px solid #cfe0ef;border-radius:8px;padding:14px;background:#fbfdff}.ref-title{font-size:13px;font-weight:800;color:var(--blue-deep);margin-bottom:6px}.ref-support{font-size:12px;color:#2a5a3a;background:#f0faf5;border-radius:5px;padding:7px 9px;margin-bottom:5px}.ref-limit{font-size:12px;color:#7b4708;background:#fff8ec;border-radius:5px;padding:7px 9px}
.diff-positive{fill:#2b77ca}.diff-negative{fill:#cc8a22}.diff-zero{fill:#99aabb}
.form-actions{display:flex;gap:10px;flex-wrap:wrap;padding-top:18px;border-top:1px solid #e2ebf4}
.page-msg{display:none;padding:11px 13px;border-radius:7px;font-size:13px;margin-bottom:14px;border-left:3px solid}.page-msg.error{display:block;border-color:#b42318;background:#fff1f0;color:#8b1d16}.page-msg.success{display:block;border-color:#167451;background:#eaf7f2;color:#0d5c3f}.page-msg.info{display:block;border-color:var(--blue);background:#edf5ff;color:var(--blue-deep)}
.withdrawn-badge{display:inline-block;padding:2px 7px;background:#fdf0dc;border:1px solid #e8c97a;border-radius:4px;font-size:11px;color:#7b5500;margin-left:6px}.item-evidence-group{display:flex;flex-direction:column;gap:4px}
[hidden]{display:none!important}
.page-shell,.header-inner{width:min(1440px,calc(100% - 64px))}
.page-shell{padding-top:20px}
.eval-main:not(:has([hidden])){grid-row:auto}
.help{font-size:13px;color:var(--muted);line-height:1.8;margin:12px 0 18px}
#ePass{font-size:22px;line-height:1.35}
.result-tools{display:flex;align-items:center;justify-content:space-between;gap:16px}
.evidence-reasons{margin:20px 0}
.evidence-reasons article{padding:16px 0;border-top:1px solid var(--line)}
.evidence-reasons h3{font-size:15px;margin-bottom:8px}
.evidence-reasons p{font-size:13px;line-height:1.8;margin:4px 0;color:var(--muted)}
.chart-legend{font-size:12px;color:var(--muted);margin-bottom:10px}
.ref-list{gap:0}.ref-item{border:0;border-bottom:1px solid var(--line);border-radius:0;padding:18px 0;background:transparent}
.ref-support,.ref-limit{background:transparent;padding:4px 0;font-size:13px}
.domain-choices{display:flex;flex-wrap:wrap;gap:10px 22px;padding:12px 0;border:0;margin:0}
.domain-choices label{display:flex;align-items:center;gap:7px;font-size:14px;font-weight:500}
.domain-choices input{width:18px;min-height:18px;accent-color:var(--blue)}
.policy-summary{padding:16px 0;border-top:1px solid var(--line);margin-top:18px;font-size:13px;line-height:1.8}
.policy-summary h3{font-size:16px;margin:0 0 10px}.policy-summary summary{cursor:pointer;font-weight:600}
.policy-summary table{width:100%;border-collapse:collapse;font-size:13px}.policy-summary th,.policy-summary td{text-align:left;padding:9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
.policy-summary th:first-child{width:48%}.policy-note{color:var(--muted);font-size:13px;line-height:1.8}
.method-line{padding:12px 14px;background:#f4f9ff;border-left:3px solid #5c9bcf;margin:12px 0;overflow-wrap:anywhere}
.anchor-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:14px 0}.anchor-list p{margin:0;font-size:13px;line-height:1.7}
.items-table td:first-child{min-width:230px}
.svg-chart{max-height:300px}
.page-msg:empty{display:none}
.field [aria-invalid=true]{border-color:#b42318;box-shadow:0 0 0 3px rgba(180,35,24,.12)}
.field-error{display:block;margin-top:5px;font-size:12px;color:#8b1d16}
.field-error:empty{display:none}
@media (prefers-reduced-motion:reduce){.record-item,.button,.tab-btn{transition:none}}
@media print{
  .eval-sidebar,.form-actions,.tab-bar,.no-print,#formCard,.site-header,.page-heading{display:none!important}
  #resultCard [role=tabpanel][hidden]{display:block!important}
  #resultCard [role=tabpanel]{break-inside:auto;margin-top:24px}
  .items-table-wrap{overflow:visible;border:0}
  .items-table{min-width:0;font-size:9px}
  .items-table th,.items-table td{overflow-wrap:anywhere;white-space:normal;padding:4px}
  .eval-layout{display:block}
  .eval-main .card{box-shadow:none;border:1px solid #ccc}
}
@media(max-width:900px){
  .page-shell,.header-inner{width:calc(100% - 28px)}
  .eval-layout{grid-template-columns:1fr}
  .eval-main,#resultCard,.eval-sidebar{grid-column:1;grid-row:auto}
  .eval-sidebar{position:static}
  .score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .form-grid-3{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:480px){
  .anchor-list{grid-template-columns:1fr}
  .form-card .card-head,.form-card .card-body,.result-card .card-head{padding:18px 14px}
  .result-card .card-body{padding:0 14px 18px}
  .result-card .tab-bar{margin-inline:-14px;padding-inline:8px;gap:0}
  .tab-btn{padding:10px;font-size:13px}
  .category-weights{grid-template-columns:1fr}
  .header-actions .button{width:auto}
  .score-line,.result-tools{align-items:flex-start;flex-direction:column}
  .items-table td:first-child{min-width:0}
  .score-grid{grid-template-columns:1fr}
  .form-grid-3,.form-grid-2{grid-template-columns:1fr}
  .tab-bar{flex-wrap:wrap}
  #itemsTable,#itemsTable tbody,#itemsTable tr,#itemsTable td{display:block;min-width:0;width:100%}
  #itemsTable thead{display:none}
  #itemsTable tr{padding:12px 0;border-bottom:2px solid var(--line)}
  #itemsTable td{border:0}
  #itemsTable td:before{content:attr(data-label);display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
}
"""
def render_evaluation(account: Any | None = None) -> str:
    account_json = _account_payload(account)
    body = (
        '<header class="site-header"><div class="header-inner">'
        '<a class="brand" href="/demo2/upload" aria-label="返回工作台首页">'
        '<svg class="brand-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
        '<path d="M3 5.5A2.5 2.5 0 0 1 5.5 3H10a2 2 0 0 1 2 2v16a3 3 0 0 0-3-3H3Z"/>'
        '<path d="M21 5.5A2.5 2.5 0 0 0 18.5 3H14a2 2 0 0 0-2 2v16a3 3 0 0 1 3-3h6Z"/></svg>'
        '<div class="brand-copy"><strong>RehabAffect</strong><span>辅读学校内测平台</span></div></a>'
        '<nav class="workspace-nav" aria-label="课堂工作台"><a href="/demo2/upload">课程上传</a><a href="/demo2/evaluation" aria-current="page">课堂评价</a><a href="/demo2/measurement">学生测量</a><a href="/demo2/safety">安全核查</a></nav>'
        '<div class="header-actions">'
        '<span class="account-chip"><span>登录账号</span><strong id="accountName">—</strong></span>'
        '<a href="/demo2/upload" class="button quiet no-print">工作台</a>'
        '<button id="logoutBtn" class="button quiet no-print">退出</button>'
        '</div></div></header>'
        '<main id="mainContent" class="page-shell">'
        '<div class="page-heading eval-heading"><div>'
        '<span class="eyebrow">教师工作台</span>'
        '<h1>课堂双轨评价</h1>'
        '<p class="lead">对照学校标准与系统增强两套评价，记录课堂质量并查看差异分析。不涉及学生个体能力评分。</p>'
        '</div></div>'
        '<div id="pageMsg" class="page-msg" role="alert" aria-live="polite"></div>'
        '<div class="eval-layout">'
        '<aside class="eval-sidebar" aria-label="评价记录列表">'
        '<div class="sidebar-head"><h2>评价记录</h2>'
        '<button id="newBtn" class="button primary no-print" style="min-height:36px;padding:6px 12px;font-size:13px">新建</button>'
        '</div><div id="recordList" class="record-list"><p class="loading-line">加载中…</p></div>'
        '</aside>'
        '<div class="eval-main">'
        '<div class="card form-card" id="formCard"><div class="card-head">'
        '<h2 id="formTitle">新建评价记录</h2>'
        '<p id="evaluationSource" role="status">未关联视频任务（课堂级评价，不指定单个学生）</p>'
        '<p>填写课堂基本信息，选择评价模板后逐项打分。</p>'
        '</div><div class="card-body">'
        '<div class="form-section"><p class="form-section-title">课程基本信息</p>'
        '<div class="form-grid-3">'
        '<div class="field"><label for="fLessonId">课堂编号 <abbr title="必填">*</abbr></label>'
        '<input id="fLessonId" type="text" autocomplete="off" required placeholder="如 L2026-001"/></div>'
        '<div class="field"><label for="fLessonDate">上课日期 <abbr title="必填">*</abbr></label>'
        '<input id="fLessonDate" type="date" required/></div>'
        '<div class="field"><label for="fCourseName">课程名称 <abbr title="必填">*</abbr></label>'
        '<input id="fCourseName" type="text" autocomplete="off" required placeholder="如 生活语文第3课"/></div>'
        '</div></div>'
        '<div class="form-section"><p class="form-section-title">课程口径（保存后锁定）</p>'
        '<div class="form-grid-3">'
        '<div class="field"><label for="fSubject">学科 <abbr title="必填">*</abbr></label>'
        '<select id="fSubject" required><option value="">请选择…</option></select></div>'
        '<div class="field"><label for="fTemplate">评价模板 <abbr title="必填">*</abbr></label>'
        '<select id="fTemplate" required><option value="">请选择…</option></select></div>'
        '<div class="field"><label for="fWeightPolicy">评价方案</label><select id="fWeightPolicy"><option value="school_context">学校基础 + 情境复核</option><option value="common">通用试行权重（历史方案）</option><option value="subject_trial">学科与本课目标试行权重</option></select></div>'
        '<div class="field field-wide" id="domainField" hidden><label>本课重点支持领域</label><fieldset class="domain-choices" id="domainChoices" aria-label="本课重点支持领域"></fieldset><p class="policy-note">按本课目标选择，可多选。未涉及领域不评价；学校五领域命名不同时需先核对映射。</p></div>'
        '<div class="field field-wide" style="grid-column:1/-1">'
        '<label for="fGoalContext">本课目标与学生分层支持约定 <abbr title="必填">*</abbr></label>'
        '<textarea id="fGoalContext" rows="3" required placeholder="填写本节课学习目标及学生能力分层支持安排，不填写学生姓名。"></textarea></div>'
        '</div>'
        '<div id="focusHint" class="lock-notice" hidden>'
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>'
        '<span id="focusHintText"></span></div>'
        '<div id="lockNotice" class="lock-notice" hidden>'
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
        '<span>已保存记录的学科、模板和目标口径不可更改，以保证评价一致性。</span></div>'
        '</div>'
        '<div class="form-section"><p class="form-section-title">评分来源</p>'
        '<div class="form-grid-2">'
        '<div class="field"><label for="fSchoolSource">学校评分来源 <abbr title="必填">*</abbr></label>'
        '<select id="fSchoolSource" required>'
        '<option value="teacher_recorded">教师自评/他评（真人打分）</option>'
        '<option value="rubric_initial">按校表初评（结构化表格）</option>'
        '</select></div>'
        '<div class="field" id="raterField"><label for="fSchoolRater">评分人 <abbr title="必填">*</abbr></label>'
        '<input id="fSchoolRater" type="text" autocomplete="off" placeholder="评分教师姓名或工号"/></div>'
        '</div></div>'
        '<div class="form-section"><p class="form-section-title">逐项评价</p>'
        '<div id="contextHelp" class="policy-summary" hidden><strong>学校基础 + 情境复核</strong><p>无新证据沿用学校分。情境修正分留空表示沿用，不是零分；修改时记录片段时间、教师应对、学生后续表现及下一课建议。未复核的修正仅作建议。</p><p>手势、指认和辅助沟通可以是有效回应。学生出现困难、课堂中断或收音不清，不单独作为扣分依据。疑似安全事件须单独核查，不以总分代替处置。</p></div>'
        '<div id="qingpuNotice" class="unverified-notice" hidden>'
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="#9a7000" stroke-width="2" width="16" height="16">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>'
        '<span>该表尚无增强映射，切换基本评价指标可使用双轨对照。</span></div>'
        '<div id="itemsWrap" class="items-table-wrap">'
        '<table class="items-table" id="itemsTable">'
        '<thead><tr>'
        '<th style="min-width:140px">评价项目</th>'
        '<th>分类</th>'
        '<th style="min-width:80px">学校分<br/><small class="weight-hint">校权重</small></th>'
        '<th style="min-width:80px">增强分<br/><small class="weight-hint">增权重</small></th>'
        '<th style="min-width:120px">证据摘要</th>'
        '<th style="min-width:100px">改分理由</th>'
        '<th style="min-width:100px">改进建议</th>'
        '</tr></thead>'
        '<tbody id="itemsTbody"><tr><td colspan="7" class="loading-line" style="padding:20px;text-align:center">'
        '请先选择评价模板</td></tr></tbody></table></div></div>'
        '<label class="review-check"><input type="checkbox" id="fReviewed"/>我已逐项核对证据与情境，确认改分针对教学应对，而非学生障碍或采集缺失</label>'
        '<details class="policy-summary"><summary>查看增强评分等级与证据要求</summary><div id="anchorList" class="anchor-list"></div></details>'
        '<p class="help">未评价请留空。选择学科方案后按本课目标调整候选权重，保存后锁定。当前评分由教师录入与复核，尚未接入自动视频评分。</p>'
        '<div id="formMsg" class="page-msg" role="alert"></div>'
        '<div class="form-actions no-print">'
        '<button id="previewBtn" class="button" type="button">预览评分</button>'
        '<button id="saveBtn" class="button primary" type="button">保存记录</button>'
        '<button id="withdrawBtn" class="button" type="button" hidden>撤销此记录</button>'
        '</div></div></div>'
        '</div>'
        '<div id="resultCard" class="card result-card" hidden><div class="card-head">'
        '<div class="result-tools"><h2>评价结果</h2><button id="editRecordBtn" class="button no-print">查看评分与证据</button></div><p id="resultMeta" class="result-meta-line"></p><p id="resultContext" class="result-context"></p><details class="result-goal"><summary>本课目标与支持约定</summary><p id="resultGoal"></p></details><div id="resultFocus" class="result-focus" hidden></div></div><div class="card-body">'
        '<div class="tab-bar" role="tablist" aria-label="评价标签">'
        '<button class="tab-btn" role="tab" aria-selected="true" id="tabSchool" aria-controls="panelSchool">学校标准</button>'
        '<button class="tab-btn" role="tab" aria-selected="false" id="tabEnhanced" aria-controls="panelEnhanced">系统增强</button>'
        '<button class="tab-btn" role="tab" aria-selected="false" id="tabCompare" aria-controls="panelCompare">双轨对照</button>'
        '<button class="tab-btn" role="tab" aria-selected="false" id="tabRefs" aria-controls="panelRefs">文献依据</button>'
        '</div>'
        '<div id="panelSchool" role="tabpanel" aria-labelledby="tabSchool">'
        '<div class="score-grid">'
        '<div class="score-box"><div class="score-box-label">原始分</div>'
        '<div class="score-box-value" id="sRaw">—</div><div class="score-box-sub" id="sRawMax"></div></div>'
        '<div class="score-box"><div class="score-box-label">折算10分</div>'
        '<div class="score-box-value" id="sScore10">—</div></div>'
        '<div class="score-box"><div class="score-box-label">教学质量分（70分制）</div>'
        '<div class="score-box-value" id="sScore70">—</div>'
        '<div class="score-box-sub">原表折算，不代表学校合格判定</div></div>'
        '</div>'
        '<div id="sScoreLine" class="score-line"><span>项目统一参考线：6 / 10</span><strong id="sReferenceStatus">待教师复核</strong></div>'
        '<div id="sCoverage" class="unverified-notice" hidden></div>'
        '<div id="sChartWrap" class="chart-section"><p class="chart-title">学校评分条形图</p>'
        '<svg id="sBarChart" class="svg-chart" aria-label="学校评分条形图"></svg></div>'
        '</div>'
        '<div id="panelEnhanced" role="tabpanel" aria-labelledby="tabEnhanced" hidden>'
        '<div class="unverified-notice">'
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="#9a7000" stroke-width="2" width="16" height="16">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>'
        '<span>结果用于教学复核，尚未完成真实课堂校准。6分为项目参考线，不代表官方认证。</span></div>'
        '<div class="score-grid">'
        '<div class="score-box"><div class="score-box-label">增强得分</div>'
        '<div class="score-box-value" id="eScore10">—</div></div>'
        '<div class="score-box" id="ePassBox"><div class="score-box-label">试行参考线（6分）</div>'
        '<div class="score-box-value" id="ePass">—</div><div class="score-box-sub" id="ePassSub"></div></div>'
        '<div class="score-box"><div class="score-box-label">已评/总项</div>'
        '<div class="score-box-value" id="eCoverage">—</div></div>'
        '</div>'
        '<div class="score-line"><span>增强轨参考线：6 / 10</span><strong>仅用于试行复核</strong></div>'
        '<div id="categoryWeights" class="category-weights"></div>'
        '<div id="eChartWrap" class="chart-section"><p class="chart-title">四类评分对照</p>'
        '<svg id="eBarChart" class="svg-chart" aria-label="增强评分条形图"></svg></div>'
        '<section id="policyDetails" class="policy-summary"></section>'
        '<section id="sensitivityDetails" class="policy-summary"></section>'
        '<section class="evidence-reasons" aria-labelledby="enhancedReasonsTitle"><h3 id="enhancedReasonsTitle">差异与下一课建议</h3><p class="help" id="enhancedDifference"></p><div id="enhancedReasons"></div></section>'
        '<section id="contextChanges" class="evidence-reasons" hidden></section>'
        '</div>'
        '<div id="panelCompare" role="tabpanel" aria-labelledby="tabCompare" hidden>'
        '<div class="unverified-notice">'
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="#9a7000" stroke-width="2" width="16" height="16">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>'
        '<span>差值 = 增强分 − 学校分。先解释证据复核，再解释权重调整；增强权重尚未验证。</span></div>'
        '<div class="score-grid">'
        '<div class="score-box"><div class="score-box-label">证据差值</div>'
        '<div class="score-box-value" id="cEvidDelta">—</div></div>'
        '<div class="score-box"><div class="score-box-label">权重差值</div>'
        '<div class="score-box-value" id="cWeightDelta">—</div></div>'
        '<div class="score-box"><div class="score-box-label">总分差值</div>'
        '<div class="score-box-value" id="cTotalDelta">—</div></div>'
        '</div>'
        '<div class="chart-section"><p class="chart-title">逐项分差图（增强−学校）</p>'
        '<svg id="diffChart" class="svg-chart" aria-label="逐项分差图"></svg></div>'
        '<div id="compareItemsWrap" class="items-table-wrap"><table class="items-table">'
        '<thead><tr><th>项目</th><th>学校分</th><th>增强分</th><th>证据差</th><th>权重差</th><th>总差</th>'
        '<th>理由</th><th>证据</th><th>建议</th></tr></thead>'
        '<tbody id="compareItemsTbody"></tbody></table></div>'
        '</div>'
        '<div id="panelRefs" role="tabpanel" aria-labelledby="tabRefs" hidden>'
        '<div id="refList" class="ref-list"></div></div>'
        '<div class="form-actions no-print" style="margin-top:16px">'
        '<button id="exportJsonBtn" class="button">导出 JSON</button>'
        '<button id="printBtn" class="button" onclick="window.print()">打印</button>'
        '</div></div></div>'
        '</div>'
        '</main>'
    )
    script = (
        'const SERVER_ACCOUNT=__ACCOUNT_JSON__;'
        'const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");'
        'const byId=id=>document.getElementById(id);'
        'let workspace=null,activeRecord=null,previewResult=null,renderedRecord=null,formRevision=0,busy=false,focusAfter="";function focusInvalid(){if(!focusAfter)return;const el=byId(focusAfter);focusAfter="";if(el&&!el.disabled)el.focus();}'
        'const sourceParams=new URLSearchParams(location.search);'
        'const sourceValues=[...sourceParams.getAll("currenttask"),...sourceParams.getAll("task_id")];'
        'const requestedTask=sourceValues.length===1&&/^[A-Za-z0-9_-]{1,120}$/.test(sourceValues[0])?sourceValues[0]:"";'
        'let sourceError=sourceValues.length&&!requestedTask?"课堂任务链接无效，请从原任务重新进入。":"",taskSource=null;'
        'function sourceLabel(rec){const source=rec||taskSource;byId("evaluationSource").textContent=sourceError||'
        '(source?.task_id?"课堂级来源任务："+source.task_id+" · "+(source.source_provenance?.status==="needs_reconfirmation"?"来源待重新确认":"已关联视频版本")+"；不指定单个学生":"未关联视频任务（课堂级评价，不指定单个学生）");}'
        'function invalidate(){formRevision++;previewResult=null;renderedRecord=null;byId("resultCard").hidden=true;byId("formCard").hidden=false;}'
        'function setBusy(value){busy=value;["previewBtn","saveBtn","withdrawBtn","newBtn"].forEach(id=>byId(id).disabled=value);document.querySelectorAll("#formCard input,#formCard select,#formCard textarea").forEach(el=>{if(value){el.dataset.priorDisabled=String(el.disabled);el.disabled=true;}else{el.disabled=el.dataset.priorDisabled==="true";}});}'
        'async function api(url,opts){'
        'const r=await fetch(url,{credentials:"include",...(opts||{})});'
        'const d=await r.json();'
        'if(!d.ok){const e=d.error||{};const err=new Error(e.message||"HTTP "+r.status);err.code=e.code;err.status=r.status;throw err;}'
        'return d;}'
        'function msg(t,k="error"){const el=byId("pageMsg");el.className="page-msg "+k;el.textContent=t;}'
        'function fmsg(t,k="error"){const el=byId("formMsg");el.className="page-msg "+k;el.textContent=t;}'
        'function clearFmsg(){const el=byId("formMsg");el.className="page-msg";el.textContent="";}'
        'function onSchoolSourceChange(){'
        'const rf=byId("raterField");'
        'if(rf)rf.hidden=byId("fSchoolSource").value!=="teacher_recorded";}'
        'function onSubjectChange(){'
        'const id=byId("fSubject").value;'
        'const s=(workspace?.subjects||[]).find(s=>s.id===id);'
        'const hint=byId("focusHint");const ht=byId("focusHintText");'
        'if(s?.focus?.length){ht.textContent="课程关注点："+s.focus.join("、")+(s.note?"。"+s.note:"");hint.hidden=false;}'
        'else{hint.hidden=true;}}'
        'function updatePolicy(){const trial=byId("fWeightPolicy").value==="subject_trial";byId("domainField").hidden=!trial;const legacy=byId("fTemplate").value==="qingpu_15";if(legacy){byId("fWeightPolicy").value="common";byId("domainField").hidden=true;}if(!trial||legacy)document.querySelectorAll("#domainChoices input").forEach(el=>el.checked=false);byId("contextHelp").hidden=byId("fWeightPolicy").value!=="school_context";updateWeightHints();}'
        'function updateWeightHints(){const t=(workspace?.templates||[]).find(t=>t.id===byId("fTemplate").value);if(!t?.enhanced_available)return;const policy=workspace.weight_policy;if(!policy)return;const contextual=byId("fWeightPolicy").value==="school_context";const trial=byId("fWeightPolicy").value==="subject_trial";const domains=trial?[...document.querySelectorAll("#domainChoices input:checked")].map(el=>el.value):[];const subjectItems=trial?(policy.subject_items[byId("fSubject").value]||[]):[];const raws=t.items.map(i=>(contextual?i.school_weight:i.enhanced_weight)*(1+(subjectItems.includes(i.id)?.1:0)+(domains.length?.1*policy.domains.filter(d=>domains.includes(d.id)&&d.items.includes(i.id)).length/domains.length:0)));const sum=raws.reduce((a,b)=>a+b,0);t.items.forEach((item,n)=>{const el=document.querySelector(`[data-weight-for="${item.id}"]`);if(el)el.textContent=(raws[n]/sum*100).toFixed(2)+"%";const input=document.querySelector(`[name="enhanced_${item.id}"]`);if(input)input.placeholder=contextual?"沿用学校分":"0-10";});}'
        'function onTemplateChange(){'
        'const id=byId("fTemplate").value;'
        'if(!id){byId("itemsTbody").innerHTML=\'<tr><td colspan="7" style="padding:20px;text-align:center;color:#8a9bb0">请先选择评价模板</td></tr>\';'
        'byId("qingpuNotice").hidden=true;return;}'
        'const tmpl=(workspace?.templates||[]).find(t=>t.id===id);if(!tmpl)return;'
        'const isQ=id==="qingpu_15";'
        'byId("qingpuNotice").hidden=!isQ;'
        'renderItemsTable(tmpl,null);updatePolicy();clearFmsg();byId("resultCard").hidden=true;previewResult=null;}'
        'function populateSubjects(){'
        'const sel=byId("fSubject");'
        'sel.innerHTML=\'<option value="">请选择学科…</option>\'+'
        '(workspace?.subjects||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");'
        'sel.addEventListener("change",onSubjectChange);}'
        'function populateTemplates(){'
        'const sel=byId("fTemplate");'
        'sel.innerHTML=\'<option value="">请选择模板…</option>\'+'
        '(workspace?.templates||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join("");'
        'sel.addEventListener("change",onTemplateChange);}'
        'function renderItemsTable(tmpl,existingItems){'
        'const isQ=tmpl.id==="qingpu_15";'
        'const cats=Object.fromEntries((tmpl.categories||[]).map(c=>[c.id,c]));'
        'const rows=(tmpl.items||[]).map(item=>{'
        'const ex=existingItems?.find(e=>e.id===item.id)||{};'
        'const cat=cats[item.category_id]||{};'
        'const sw=((item.school_weight||0)*100).toFixed(0)+"%";'
        'const ew=isQ?"—":((item.enhanced_weight||0)*100).toFixed(0)+"%";'
        'const schoolInput=isQ'
        '?`<select name="school_${item.id}" aria-label="${esc(item.label)} 原表等第">'
        '<option value="">—</option>'
        '<option value="2"${ex.school_score===2?" selected":""}>2</option>'
        '<option value="3"${ex.school_score===3?" selected":""}>3</option>'
        '<option value="4"${ex.school_score===4?" selected":""}>4</option>'
        '<option value="5"${ex.school_score===5?" selected":""}>5</option>'
        '</select>`'
        ':`<input type="number" name="school_${item.id}" min="1" max="10" step="1"'
        ' aria-label="${esc(item.label)} 学校分" value="${ex.school_score!=null?ex.school_score:""}"'
        ' placeholder="1-10"/>`;'
        'const enhInput=isQ'
        '?`<span class="score-null" aria-label="无增强分">—</span>`'
        ':`<input type="number" name="enhanced_${item.id}" min="0" max="10" step="0.5"'
        ' aria-label="${esc(item.label)} 增强分" value="${ex.enhanced_score!=null?ex.enhanced_score:""}"'
        ' placeholder="0-10"/>`;'
        'return `<tr>'
        '<td data-label="评价项目"><strong>${esc(item.label)}</strong>'
        '${item.anchor?`<br/><small style="color:#8a9bb0">${esc(item.anchor)}</small>`:""}'
        '</td>'
        '<td data-label="分类"><span title="${esc(cat.rationale||"")}">${esc(cat.label||item.category_id||"")}</span>'
        '${cat.school_weight!=null?`<span class="weight-hint">分类校${((cat.school_weight||0)*100).toFixed(0)}%</span>`:""}'
        '</td>'
        '<td data-label="学校分">${schoolInput}<span class="weight-hint">${sw}</span></td>'
        '<td data-label="增强分">${enhInput}<span class="weight-hint" data-weight-for="${item.id}">${ew}</span></td>'
        '<td data-label="证据摘要"><textarea name="evidence_${item.id}" rows="2" aria-label="${esc(item.label)} 证据摘要"'
        ' placeholder="观察/教案页/时间点">${esc(ex.evidence||"")}</textarea></td>'
        '<td data-label="改分理由"><textarea name="reason_${item.id}" rows="2" aria-label="${esc(item.label)} 改分理由"'
        ' placeholder="增强分改动时必填">${esc(ex.reason||"")}</textarea></td>'
        '<td data-label="改进建议"><textarea name="suggestion_${item.id}" rows="2" aria-label="${esc(item.label)} 改进建议"'
        ' placeholder="可选">${esc(ex.suggestion||"")}</textarea></td>'
        '</tr>`;}).join("");'
        'byId("itemsTbody").innerHTML=rows||\'<tr><td colspan="7">模板无评价项</td></tr>\';}'
        'const REQUIRED_FIELDS=[["fLessonId","请填写课堂编号"],["fLessonDate","请选择上课日期"],["fCourseName","请填写课程名称"],'
        '["fSubject","请选择学科"],["fTemplate","请选择评价模板"],["fGoalContext","请填写本课目标与学生分层支持约定"],'
        '["fSchoolSource","请选择学校评分来源"],["fSchoolRater","请填写评分人"]];'
        'function fieldError(el,text){const field=el.closest(".field");let note=field?.querySelector(".field-error");'
        'if(!note&&field){note=document.createElement("span");note.className="field-error";note.id=el.id+"Error";note.setAttribute("role","alert");field.appendChild(note);}'
        'if(text){el.setAttribute("aria-invalid","true");if(note){note.textContent=text;el.setAttribute("aria-describedby",note.id);}}'
        'else{el.removeAttribute("aria-invalid");if(note)note.textContent="";}}'
        'function clearFieldErrors(){REQUIRED_FIELDS.forEach(([id])=>fieldError(byId(id),""));}'
        'function goalNameError(e){if(e?.code!=="goal_contains_student_name")return;fieldError(byId("fGoalContext"),e.message);e.focusId="fGoalContext";byId("fGoalContext").scrollIntoView({block:"center"});}'
        'function validateRequired(){'
        'const missing=REQUIRED_FIELDS.filter(([id])=>{const el=byId(id);'
        'if(id==="fSchoolRater"&&(byId("fSchoolSource").value!=="teacher_recorded"||byId("raterField").hidden))return false;'
        'return !String(el.value||"").trim();});'
        'REQUIRED_FIELDS.forEach(([id,text])=>fieldError(byId(id),missing.some(m=>m[0]===id)?text:""));'
        'if(!missing.length)return;'
        'const first=byId(missing[0][0]);first.scrollIntoView({block:"center"});'
        'const err=new Error(`请先完成必填项：${missing.map(m=>m[1].replace(/^请(填写|选择)/,"")).join("、")}。`);err.focusId=first.id;throw err;}'
        'function collectPayload(recordId,expectedVersion){'
        'const lessonId=byId("fLessonId").value.trim();'
        'const lessonDate=byId("fLessonDate").value;'
        'const courseName=byId("fCourseName").value.trim();'
        'const subjectId=byId("fSubject").value;'
        'const templateId=byId("fTemplate").value;'
        'const goalContext=byId("fGoalContext").value.trim();'
        'const schoolSource=byId("fSchoolSource").value;'
        'const schoolRater=schoolSource==="teacher_recorded"?byId("fSchoolRater").value.trim():"";'
        'validateRequired();'
        'const tmpl=(workspace?.templates||[]).find(t=>t.id===templateId);'
        'if(!tmpl)throw new Error("未找到所选模板。");'
        'const isQ=templateId==="qingpu_15";'
        'const items=(tmpl.items||[]).map(item=>{'
        'const sf=document.querySelector(`[name="school_${item.id}"]`);'
        'const ef=document.querySelector(`[name="enhanced_${item.id}"]`);'
        'const ev=document.querySelector(`[name="evidence_${item.id}"]`)?.value.trim()||"";'
        'const re=document.querySelector(`[name="reason_${item.id}"]`)?.value.trim()||"";'
        'const sg=document.querySelector(`[name="suggestion_${item.id}"]`)?.value.trim()||"";'
        'const sv=sf?.value;'
        'const school_score=sv!==""&&sv!=null?Number(sv):null;'
        'const enhanced_score=isQ?null:(ef?.value!==""&&ef?.value!=null?Number(ef.value):null);'
        'return {id:item.id,school_score,enhanced_score,evidence:ev,reason:re,suggestion:sg};});'
        'if(sourceError)throw new Error(sourceError);'
        'if(requestedTask&&!taskSource)throw new Error("正在核验课堂来源，请稍后重试。");'
        'const source=activeRecord||taskSource;'
        'if(source?.source_provenance?.status==="needs_reconfirmation")throw new Error("视频来源已失效，请核对后新建评价。");'
        'return {...(source?.task_id?{task_id:source.task_id,frame_revision:source.frame_revision}:{}),record_id:recordId||crypto.randomUUID(),expected_version:expectedVersion??0,'
        'lesson_id:lessonId,lesson_date:lessonDate,course_name:courseName,'
        'subject_id:subjectId,template_id:templateId,goal_context:goalContext,'
        'school_source:schoolSource,school_rater:schoolRater,reviewed:byId("fReviewed").checked,items,weight_policy:byId("fWeightPolicy").value,focus_domains:[...document.querySelectorAll("#domainChoices input:checked")].map(el=>el.value)};}'
        'function loadRecordIntoForm(rec){'
        'activeRecord=rec;previewResult=null;clearFieldErrors();byId("resultCard").hidden=true;'
        'sourceLabel(rec);'
        'byId("fLessonId").value=rec.lesson_id||"";'
        'byId("fLessonDate").value=rec.lesson_date||"";'
        'byId("fCourseName").value=rec.course_name||"";'
        'byId("fSubject").value=rec.subject_id||"";'
        'byId("fTemplate").value=rec.template_id||"";'
        'byId("fWeightPolicy").value=rec.weight_policy||"common";document.querySelectorAll("#domainChoices input").forEach(el=>{el.checked=(rec.focus_domains||[]).includes(el.value);el.disabled=rec.version>0;});'
        'byId("fGoalContext").value=rec.goal_context||"";'
        'byId("fSchoolSource").value=rec.school_source||"teacher_recorded";'
        'byId("fSchoolRater").value=rec.school_rater||"";'
        'byId("fReviewed").checked=rec.reviewed===true;byId("qingpuNotice").hidden=rec.template_id!=="qingpu_15";'
        'onSchoolSourceChange();onSubjectChange();'
        'const tmpl=(workspace?.templates||[]).find(t=>t.id===rec.template_id);'
        'if(tmpl)renderItemsTable(tmpl,rec.items||[]);'
        'updatePolicy();byId("fWeightPolicy").disabled=rec.version>0;'
        'const locked=rec.version>0;'
        'byId("fSubject").disabled=locked;byId("fTemplate").disabled=locked;byId("fGoalContext").disabled=locked;'
        'byId("fLessonId").disabled=locked;byId("fLessonDate").disabled=locked;'
        'byId("lockNotice").hidden=!locked;'
        'byId("formTitle").textContent=(rec.status==="withdrawn"?"[已撤销] ":"")+"编辑评价记录";'
        'byId("withdrawBtn").hidden=rec.status==="withdrawn";'
        'if(rec.result)renderResult(rec.result,rec);}'
        'function fmtNum(v,digits){return v!=null&&!isNaN(v)?Number(v).toFixed(digits??1):"—";}'
        'function statusLabel(s){return{reviewed:"已复核",provisional:"草稿",incomplete:"草稿·未评完",withdrawn:"已撤销",active:"有效"}[s]||s||"—";}'
        'function renderBarChart(svgId,items,schoolKey,enhKey){'
        'const svg=byId(svgId);if(!svg)return;'
        'const n=items.length;if(!n){svg.innerHTML="<text x=\'0\' y=\'16\' font-size=\'12\' fill=\'#8a9bb0\'>无数据</text>";return;}'
        'const rowH=38,pad=4,labelW=170,barMaxW=240,numW=36;'
        'const h=n*rowH+pad*2+24;svg.setAttribute("viewBox",`0 0 ${labelW+barMaxW+numW*2+24} ${h}`);'
        'svg.setAttribute("height",h);'
        'let html="";'
        'items.forEach((item,i)=>{'
        'const y=pad+i*rowH+rowH/2;'
        'const sv=item[schoolKey];const ev=item[enhKey];'
        'const sw=sv!=null?Math.round((sv/10)*barMaxW):0;'
        'const ew=ev!=null?Math.round((ev/10)*barMaxW):0;'
        'html+=`<text x="${labelW-4}" y="${y+4}" font-size="11" fill="#556070" text-anchor="end">${esc(item.label||item.id)}</text>`;'
        'html+=`<rect x="${labelW}" y="${y-8}" width="${sv!=null?sw:0}" height="10" fill="#2163C4" rx="2" opacity=".8"/>`;'
        'html+=`<rect x="${labelW}" y="${y+2}" width="${ev!=null?ew:0}" height="10" fill="#e09030" rx="2" opacity=".8"/>`;'
        'html+=`<text x="${labelW+barMaxW+4}" y="${y+4}" font-size="11" fill="#2163C4">${sv!=null?fmtNum(sv,1):"—"}</text>`;'
        'if(enhKey!=="unused")html+=`<text x="${labelW+barMaxW+4+numW}" y="${y+4}" font-size="11" fill="#b06a00">${ev!=null?fmtNum(ev,1):"—"}</text>`;'
        '});'
        'html+=`<text x="${labelW+4}" y="${h-2}" font-size="10" fill="#2163C4">■ 学校</text>`;'
        'if(enhKey!=="unused")html+=`<text x="${labelW+50}" y="${h-2}" font-size="10" fill="#b06a00">■ 增强</text>`;'
        'svg.innerHTML=html;}'
        'function renderDiffChart(svgId,items){'
        'const svg=byId(svgId);if(!svg)return;'
        'const n=items.length;if(!n){svg.innerHTML="<text x=\'0\' y=\'16\' font-size=\'12\' fill=\'#8a9bb0\'>无数据</text>";return;}'
        'const rowH=26,pad=4,labelW=120,mid=200,halfMax=80;'
        'const h=n*rowH+pad*2+20;svg.setAttribute("viewBox",`0 0 ${labelW+mid+halfMax+40} ${h}`);'
        'svg.setAttribute("height",h);'
        'let html=`<line x1="${labelW+halfMax}" y1="${pad}" x2="${labelW+halfMax}" y2="${h-20}" stroke="#ccc" stroke-width="1"/>`;'
        'items.forEach((item,i)=>{'
        'const y=pad+i*rowH+rowH/2;'
        'const d=item.total_delta;'
        'const maxDelta=Math.max(.1,...items.map(x=>Math.abs(x.total_delta||0)));const w=d!=null?Math.round(Math.abs(d)/maxDelta*halfMax):0;'
        'const cx=labelW+halfMax;'
        'const cls=d==null?"diff-zero":d>0?"diff-positive":d<0?"diff-negative":"diff-zero";'
        'html+=`<text x="${labelW-4}" y="${y+4}" font-size="11" fill="#556070" text-anchor="end"><title>${esc(item.label||item.id)}</title>${esc((item.label||item.id).slice(0,9))}</text>`;'
        'if(d!=null&&d!==0){'
        'const x=d>0?cx:cx-w;'
        'html+=`<rect x="${x}" y="${y-7}" width="${w}" height="14" class="${cls}" rx="2"/>`;}'
        'html+=`<text x="${cx+halfMax+6}" y="${y+4}" font-size="11" fill="${d!=null&&d>0?"#2163C4":d!=null&&d<0?"#c47b00":"#99aabb"}">${d!=null?fmtNum(d,2):"—"}</text>`;'
        '});'
        'html+=`<text x="${labelW+4}" y="${h-4}" font-size="10" fill="#8a9bb0">← 学校高   增强高 →</text>`;'
        'svg.innerHTML=html;}'
        'function renderResult(result,rec){'
        'const cr=result.context_review;const ce=byId("contextChanges");ce.hidden=!cr?.enabled;if(cr?.enabled){ce.innerHTML=`<h3>情境修正记录</h3><p>${cr.pending_count?`${cr.pending_count}项建议待复核，尚未计入总分。`:"无待复核修正。"}</p>${cr.changes.map(c=>`<article><h4>${esc(c.label)} · ${c.applied?"已复核":"建议待复核"}</h4><p>学校分 ${fmtNum(c.school_score,2)} → 建议分 ${fmtNum(c.proposed_score,2)}；总分影响 ${fmtNum(c.proposed_delta,2)}</p><p>证据：${esc(c.evidence)}</p><p>应对与后续表现：${esc(c.reason)}</p><p>下一课：${esc(c.suggestion)}</p></article>`).join("")}<p>${esc(cr.note)}</p>`;}'
        'if(!result){byId("resultCard").hidden=true;return;}'
        'byId("resultCard").hidden=false;'
        'byId("formCard").hidden=true;'
        'renderedRecord=rec;byId("exportJsonBtn").disabled=!rec;'
        'const sch=result.school||{};const enh=result.enhanced||{};const cmp=result.comparison||{};'
        'const statusBadge=`<span class="status-badge${result.status==="reviewed"?" success":result.status==="provisional"?" warning":" "}">${statusLabel(result.status)}</span>`;'
        'const selectedTemplate=(rec?.rule_snapshot?.templates||workspace?.templates||[]).find(t=>t.id===result.template_id);byId("resultMeta").innerHTML=`${esc(selectedTemplate?.label||"课堂评价")} · ${rec?"已保存版本 "+rec.version:"未保存预览"} · ${statusBadge}<br>规则版本：${esc(result.rule_version||"—")}`;'
        'const data=rec||collectPayload(activeRecord?.record_id,activeRecord?.version);byId("resultContext").textContent=`${data.course_name} · ${data.lesson_date}\n${sch.source_label||""}${data.school_rater?" · "+data.school_rater:""}\n${data.task_id?"课堂级来源任务："+data.task_id+" · "+(data.source_provenance?.status||"预览")+" · SHA-256："+(data.source_sha256||"保存时核验"):"未关联视频任务"}`;byId("resultGoal").textContent=data.goal_context;'
        'const subject=result.subject_context||(rec?.rule_snapshot?.subjects||workspace?.subjects||[]).find(s=>s.id===data.subject_id);const focusNode=byId("resultFocus");if(subject){focusNode.hidden=false;focusNode.textContent=`课程关注：${(subject.focus||[]).join("、")}。${subject.note||""}`;}else{focusNode.hidden=true;}'
        'byId("sRaw").textContent=sch.raw_score!=null?`${fmtNum(sch.raw_score,sch.raw_max===5?2:1)}`:"—";'
        'byId("sRawMax").textContent=sch.raw_max!=null?`满分${sch.raw_max}`:"";'
        'byId("sScore10").textContent=fmtNum(sch.score_10,2);'
        'byId("sScore70").textContent=fmtNum(sch.teaching_score_70,1);'
        'byId("sReferenceStatus").textContent=sch.reference_status||"仅作项目参考，不替代学校判定";'
        'const scov=sch.coverage;'
        'const scovEl=byId("sCoverage");'
        'if(scov&&scov.scored<scov.total){scovEl.hidden=false;scovEl.textContent=`学校评分仅${scov.scored}/${scov.total}项，暂不形成完整总评。缺项不填零。`;}else{scovEl.hidden=true;}'
        'byId("eScore10").textContent=fmtNum(enh.score_10,2);'
        'const epEl=byId("ePassBox");'
        'if(enh.passed===true){epEl.className="score-box pass";}else if(enh.passed===false){epEl.className="score-box fail";}else{epEl.className="score-box na";}'
        'byId("ePass").textContent=enh.passed===true?"达到参考线":enh.passed===false?"未达参考线":"待定";'
        'byId("ePassSub").textContent=enh.status_label||"";'
        'const ecov=enh.coverage;byId("eCoverage").textContent=ecov?`${ecov.scored}/${ecov.total}`:"—";'
        'byId("cEvidDelta").textContent=cmp.available&&cmp.evidence_delta!=null?fmtNum(cmp.evidence_delta,2):"不可用";'
        'byId("cWeightDelta").textContent=cmp.available&&cmp.weight_delta!=null?fmtNum(cmp.weight_delta,2):"不可用";'
        'byId("cTotalDelta").textContent=cmp.available&&cmp.total_delta!=null?fmtNum(cmp.total_delta,2):"不可用";'
        'const ci=cmp.items||[];'
        'byId("enhancedDifference").textContent=cmp.available?`相对学校分变化 ${fmtNum(cmp.total_delta,2)} 分，其中证据修正 ${fmtNum(cmp.evidence_delta,2)} 分，权重调整 ${fmtNum(cmp.weight_delta,2)} 分。分差不表示系统比教师更准确。`:"评分尚不完整，暂不进行两轨差值解释。";'
        'const changed=ci.filter(i=>i.reason||i.suggestion);byId("enhancedReasons").innerHTML=changed.length?changed.map(i=>`<article><h3>${esc(i.label)} · ${fmtNum(i.school_score,1)} → ${fmtNum(i.enhanced_score,1)}</h3><p><strong>依据：</strong>${esc(i.evidence||"尚未补充")}</p><p><strong>解释：</strong>${esc(i.reason||"条目分未调整，仅按公开权重汇总。")}</p><p><strong>下一步：</strong>${esc(i.suggestion||"暂无补充建议")}</p></article>`).join(""):"<p class=help>暂无逐项补充理由或建议。</p>";'
        'renderBarChart("sBarChart",result.categories||[],"school_score","unused");'
        'renderBarChart("eBarChart",result.categories||[],"school_score","enhanced_score");'
        'byId("categoryWeights").innerHTML=(result.categories||[]).map(c=>`<p><b>${esc(c.label)}</b> · 学校 ${(c.school_weight*100).toFixed(1)}% → 增强 ${c.enhanced_weight==null?"不适用":(c.enhanced_weight*100).toFixed(1)+"%"}<br>${esc(c.rationale)}</p>`).join("");'
        'const wp=result.weight_policy;byId("policyDetails").innerHTML=wp?`<h3>${wp.mode==="subject_trial"?"学科与本课目标权重":"通用试行权重"}</h3><p>${esc(wp.rationale)}</p><p class="policy-note">本课重点：${wp.domains.filter(d=>d.selected).map(d=>esc(d.label)).join("、")||"未选领域"}。${esc(wp.note)}</p><details><summary>逐项权重与计算过程</summary><p class="method-line">${esc(wp.formula)}</p><table><thead><tr><th>项目</th><th>基础</th><th>调整倍数</th><th>最终</th></tr></thead><tbody>${wp.items.map(i=>`<tr><td>${esc(i.label)}</td><td>${i.base_weight==null?"—":fmtNum(i.base_weight*100,2)+"%"}</td><td>${fmtNum(i.multiplier,3)}</td><td>${i.final_weight==null?"—":fmtNum(i.final_weight*100,2)+"%"}</td></tr>`).join("")}</tbody></table><p class="policy-note">${esc(wp.limitation)} · ${esc(wp.version)}</p></details>`:"<p>此历史记录未使用学科目标权重。</p>";'
        'const sensitivity=result.sensitivity;byId("sensitivityDetails").innerHTML=sensitivity?.available?`<h3>权重敏感性检查</h3><p>小幅调整分类权重后：<strong>${fmtNum(sensitivity.low,2)}–${fmtNum(sensitivity.high,2)} / 10</strong>。${sensitivity.crosses_reference?"跨越6分参考线，建议先复核证据，不直接给出稳定达标结论。":"本次检查未跨越6分参考线。"}</p><p class="policy-note">${esc(sensitivity.note)}</p>`:"<p>完整填写增强分后显示权重敏感性检查。</p>";'
        'if(wp?.mode==="school_context"){byId("policyDetails").querySelector("h3").textContent="学校基础 + 情境复核";byId("sensitivityDetails").innerHTML="<p>本方案沿用学校权重；总分差只来自已复核的单项修正，无权重调整项。</p>";}'
        'renderDiffChart("diffChart",ci);'
        'byId("compareItemsTbody").innerHTML=ci.map(item=>`<tr>'
        '<td>${esc(item.label||item.id)}</td>'
        '<td>${item.school_score!=null?fmtNum(item.school_score,1):"—"}</td>'
        '<td>${item.enhanced_score!=null?fmtNum(item.enhanced_score,1):"—"}</td>'
        '<td>${item.evidence_delta!=null?fmtNum(item.evidence_delta,2):"—"}</td>'
        '<td>${item.weight_delta!=null?fmtNum(item.weight_delta,2):"—"}</td>'
        '<td>${item.total_delta!=null?fmtNum(item.total_delta,2):"—"}</td>'
        '<td>${esc(item.reason||"")}</td>'
        '<td style="white-space:pre-wrap">${esc(item.evidence||"")}</td>'
        '<td>${esc(item.suggestion||"")}</td>'
        '</tr>`).join("");'
        'const refs=rec?.rule_snapshot?.references||workspace?.references||[];'
        'byId("refList").innerHTML=refs.length?refs.map(r=>`<div class="ref-item">'
        '<div class="ref-title">${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title||r.id)}</a>`:esc(r.title||r.id)}</div>'
        '${r.support?`<div class="ref-support">支持：${esc(r.support)}</div>`:""}'
        '${r.limitation?`<div class="ref-limit">局限：${esc(r.limitation)}</div>`:""}'
        '</div>`).join(""):`<p style="color:#8a9bb0;font-size:13px">暂无文献数据。</p>`;'
        '}'
        'function resetForm(){'
        'activeRecord=null;previewResult=null;byId("resultCard").hidden=true;'
        'sourceLabel(null);'
        'byId("formCard").hidden=false;'
        'renderedRecord=null;byId("fReviewed").checked=false;byId("fLessonId").disabled=false;byId("fLessonDate").disabled=false;'
        'byId("fLessonId").value="";byId("fLessonDate").value="";byId("fCourseName").value="";'
        'byId("fSubject").value="";byId("fSubject").disabled=false;'
        'byId("fTemplate").value="";byId("fTemplate").disabled=false;'
        'byId("fWeightPolicy").value="school_context";byId("fWeightPolicy").disabled=false;document.querySelectorAll("#domainChoices input").forEach(el=>{el.checked=false;el.disabled=false;});updatePolicy();'
        'byId("fGoalContext").value="";byId("fGoalContext").disabled=false;'
        'byId("fSchoolSource").value="teacher_recorded";byId("fSchoolRater").value="";'
        'byId("lockNotice").hidden=true;byId("focusHint").hidden=true;'
        'byId("formTitle").textContent="新建评价记录";byId("withdrawBtn").hidden=true;'
        'byId("itemsTbody").innerHTML=\'<tr><td colspan="7" style="padding:20px;text-align:center;color:#8a9bb0">请先选择评价模板</td></tr>\';'
        'byId("qingpuNotice").hidden=true;clearFmsg();clearFieldErrors();onSchoolSourceChange();}'
        'function renderRecordList(records){'
        'const el=byId("recordList");'
        'if(!records.length){el.innerHTML=\'<p style="color:#8a9bb0;font-size:13px">暂无评价记录。</p>\';return;}'
        'el.innerHTML=records.map(r=>`<div class="record-item${activeRecord?.record_id===r.record_id?" active":""}" '
        'data-id="${esc(r.record_id)}" tabindex="0" role="button" '
        'aria-pressed="${activeRecord?.record_id===r.record_id}">'
        '<div class="record-item-title">${esc(r.course_name||r.lesson_id||r.record_id)}'
        '${r.status==="withdrawn"?\'<span class="withdrawn-badge">已撤销</span>\':""}</div>'
        '<div class="record-item-meta">${esc(r.lesson_date||"")} · ${statusLabel(r.result?.status||r.status)}</div>'
        '</div>`).join("");'
        'el.querySelectorAll(".record-item").forEach(el=>{'
        'el.addEventListener("click",()=>selectRecord(el.dataset.id));'
        'el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectRecord(el.dataset.id);}});});}'
        'function selectRecord(id){'
        'if(busy)return;'
        'const rec=(workspace?.records||[]).find(r=>r.record_id===id);'
        'if(!rec)return;'
        'loadRecordIntoForm(rec);'
        'renderRecordList(workspace.records);'
        '}'
        'async function loadWorkspace(){'
        'try{'
        'const d=await api("' + _API + '/evaluations");'
        'workspace=d.workspace||{records:[],templates:[],subjects:[],references:[]};'
        'byId("domainChoices").innerHTML=(workspace.weight_policy?.domains||[]).map(d=>`<label><input type="checkbox" value="${esc(d.id)}">${esc(d.label)}</label>`).join("");byId("anchorList").innerHTML=(workspace.weight_policy?.anchors||[]).map(a=>`<p><strong>${a.score}分 · ${esc(a.label)}</strong><br>${esc(a.detail)}</p>`).join("");'
        'if(workspace.needs_school_context){msg("请先到学校信息页填写所属学校，再保存课堂评价。");}'
        'populateSubjects();populateTemplates();'
        'renderRecordList(workspace.records||[]);'
        'byId("fSchoolSource").addEventListener("change",onSchoolSourceChange);'
        'onSchoolSourceChange();'
        'if(sourceError)throw new Error(sourceError);'
        'if(requestedTask){const source=await api("' + _API + '/identity/workspace?task_id="+encodeURIComponent(requestedTask));'
        'if(!source.workspace?.media_available||!source.workspace.frame_revision)throw new Error("任务证据未就绪，暂不能关联评价。");'
        'taskSource={task_id:requestedTask,frame_revision:source.workspace.frame_revision};'
        'workspace.records=workspace.records.filter(r=>r.task_id===requestedTask);renderRecordList(workspace.records);sourceLabel(null);'
        'byId("fLessonId").value=source.workspace.course_id||requestedTask;byId("fCourseName").value=source.workspace.course_name||"";}'
        'if(workspace.records?.length)selectRecord(workspace.records[0].record_id);'
        '}catch(e){sourceError=e.message;sourceLabel(null);byId("previewBtn").disabled=true;byId("saveBtn").disabled=true;msg("工作台数据加载失败："+e.message);}}'
        'byId("previewBtn").addEventListener("click",async()=>{'
        'if(busy)return;clearFmsg();setBusy(true);'
        'try{'
        'const payload=collectPayload(activeRecord?.record_id,activeRecord?.version);'
        'const d=await api("' + _API + '/evaluations/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});'
        'previewResult=d.result;renderResult(d.result,null);'
        'fmsg("预览已生成，如数据有变动请重新预览后再保存。","info");'
        '}catch(e){invalidate();goalNameError(e);fmsg((e.status===400?"提交数据有误：":e.status===403?"权限不足：":e.status===409?"版本冲突，请重新加载记录：":"")+e.message);focusAfter=e.focusId||"";}finally{setBusy(false);focusInvalid();}});'
        'byId("saveBtn").addEventListener("click",async()=>{'
        'if(busy)return;clearFmsg();setBusy(true);'
        'try{'
        'const payload=collectPayload(activeRecord?.record_id,activeRecord?.version??0);'
        'const d=await api("' + _API + '/evaluations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});'
        'const saved=d.record;'
        'if(!workspace.records.find(r=>r.record_id===saved.record_id)){workspace.records.unshift(saved);}'
        'else{workspace.records=workspace.records.map(r=>r.record_id===saved.record_id?saved:r);}'
        'setBusy(false);loadRecordIntoForm(saved);renderRecordList(workspace.records);'
        'fmsg("记录已保存。","success");'
        '}catch(e){goalNameError(e);fmsg((e.status===400?"提交数据有误：":e.status===403?"权限不足：":e.status===409?"版本冲突，请重新加载记录：":"")+e.message);focusAfter=e.focusId||"";}finally{if(busy)setBusy(false);focusInvalid();}});'
        'byId("withdrawBtn").addEventListener("click",async()=>{'
        'if(!activeRecord||busy)return;'
        'const reason=prompt("请输入撤销原因（必填）：");if(!reason?.trim())return;'
        'setBusy(true);'
        'try{'
        'const d=await api("' + _API + '/evaluations/withdraw",{method:"POST",headers:{"Content-Type":"application/json"},'
        'body:JSON.stringify({record_id:activeRecord.record_id,expected_version:activeRecord.version,reason:reason.trim()})});'
        'const updated=d.record;'
        'workspace.records=workspace.records.filter(r=>r.record_id!==updated.record_id);'
        'setBusy(false);resetForm();renderRecordList(workspace.records);'
        'fmsg("记录已撤销。","info");'
        '}catch(e){fmsg((e.status===409?"版本冲突，请重新加载记录：":"")+e.message);}finally{if(busy)setBusy(false);}});'
        'byId("newBtn").addEventListener("click",()=>{resetForm();renderRecordList(workspace?.records||[]);msg("");byId("fLessonId").focus();});'
        'byId("editRecordBtn").addEventListener("click",()=>{byId("formCard").hidden=false;byId("formCard").scrollIntoView({block:"start"});});'
        'byId("exportJsonBtn").addEventListener("click",()=>{'
        'if(!renderedRecord)return;'
        'const blob=new Blob([JSON.stringify(renderedRecord,null,2)],{type:"application/json"});'
        'const url=URL.createObjectURL(blob);const a=document.createElement("a");'
        'a.href=url;a.download=`eval_${renderedRecord.record_id||"record"}.json`;a.click();URL.revokeObjectURL(url);});'
        'document.querySelectorAll(".tab-btn").forEach(btn=>{'
        'btn.addEventListener("click",()=>{'
        'document.querySelectorAll(".tab-btn").forEach(b=>{b.setAttribute("aria-selected","false");});'
        'btn.setAttribute("aria-selected","true");'
        'const panel=btn.getAttribute("aria-controls");'
        '["panelSchool","panelEnhanced","panelCompare","panelRefs"].forEach(id=>{'
        'const el=byId(id);if(el)el.hidden=id!==panel;});});});'
        'document.querySelector(".tab-bar").addEventListener("keydown",e=>{const tabs=[...document.querySelectorAll(".tab-btn")];const index=tabs.indexOf(document.activeElement);if(index<0||!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();const next=e.key==="Home"?0:e.key==="End"?tabs.length-1:(index+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;tabs[next].click();tabs[next].focus();});'
        'byId("logoutBtn").addEventListener("click",async()=>{'
        'try{await api("' + _API + '/auth/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});}finally{window.location.assign("/demo2/login");}});'
        'byId("accountName").textContent=SERVER_ACCOUNT.login_alias||SERVER_ACCOUNT.username||"—";'
        'byId("fWeightPolicy").addEventListener("change",updatePolicy);byId("domainChoices").addEventListener("change",updateWeightHints);byId("fSubject").addEventListener("change",updateWeightHints);'
        'function changedInput(e){if(e.target.getAttribute?.("aria-invalid")==="true"&&String(e.target.value||"").trim())fieldError(e.target,"");if(e.target.id!=="fReviewed")byId("fReviewed").checked=false;invalidate();}byId("formCard").addEventListener("input",changedInput);byId("formCard").addEventListener("change",changedInput);'
        'loadWorkspace();'
    )
    script = script.replace('__ACCOUNT_JSON__', account_json)
    return _document(
        title="课堂双轨评价 · RehabAffect",
        body=body,
        page_style=_WORKSPACE_STYLE + _EVAL_STYLE,
        script=script,
    )


__all__ = ["render_evaluation"]
