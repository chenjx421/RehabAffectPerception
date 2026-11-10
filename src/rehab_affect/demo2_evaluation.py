from __future__ import annotations

import json
from typing import Any

from .demo2_portal import _document, _WORKSPACE_STYLE, _account_payload
from .demo2_score_basis_ui import SCORE_BASIS_CSS, SCORE_BASIS_JS
from .demo2_ui_kit import UI_DRAFT_STORE_JS, teacher_header
from .score_basis import evaluation_rubric_detail
from .assessment_rubric import DIMENSION_LABELS, DIMENSION_WEIGHTS, RUBRIC_VERSION

_API = "/api/v1/demo2"

_EVAL_STYLE = r"""
.course-task-card{margin:10px 0 0;padding:12px 14px;border:1px solid #b9d7c9;border-left:4px solid #3aa57a;border-radius:8px;background:#f4fbf7}
.course-task-card .ct-card-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.course-task-card .ct-card-head p{margin:0;font-size:13px}
.course-task-card .ct-card-actions{display:flex;gap:8px;flex-wrap:wrap}
.course-task-card .course-task-goals{margin:8px 0 4px;padding-left:20px;font-size:13px}
.course-task-card .course-task-goals li{margin:0 0 6px}
.course-task-card .ct-meta{display:block;color:#56657a;font-size:12px}
.ct-goal-chip{display:inline-block;padding:0 6px;border-radius:8px;background:#e6f4ec;color:#1d7a55;font-size:12px;font-weight:700}
.course-task-basis{margin:6px 0 0;padding-left:20px;font-size:13px}
.course-task-basis p{margin:2px 0 8px;color:#3d4b5f}
.eval-heading{margin-bottom:18px;align-items:center}
.eval-heading h1{font-size:26px;letter-spacing:0}
.eval-heading .lead{font-size:14px;max-width:760px;margin-top:8px}
.eval-heading .eyebrow{margin-bottom:4px}
.eval-layout{display:grid;grid-template-columns:218px minmax(0,1fr);gap:26px;align-items:start;padding-top:10px}
.eval-sidebar{position:sticky;top:86px;min-width:0;grid-row:1 / span 2}
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
.form-card{border:0;border-radius:0;box-shadow:none}
.form-card .card-head{padding:20px 26px 16px;background:#f5faff}
.form-card .card-body{padding:22px 26px 26px}
.form-card .card-head h2{font-size:21px;color:var(--blue-deep)}
.form-card .card-head p{max-width:720px}
#evaluationSource{font-size:13px;color:var(--muted);margin-top:4px}
/* 步骤条 */
.step-bar{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 22px;padding:0;list-style:none;counter-reset:none}
.step-bar li{min-width:0}
.step-btn{display:flex;align-items:center;gap:10px;width:100%;min-height:56px;padding:9px 12px;border:1px solid #d3e2f0;border-radius:9px;background:#fff;color:var(--muted);font:inherit;text-align:left;cursor:pointer;transition:border-color .18s,background .18s,box-shadow .18s}
.step-btn:hover{border-color:#8fbbe3;background:#f7fbff}
.step-btn b{flex:none;display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#e8f1fa;color:#4e7397;font-size:13px}
.step-btn span{display:flex;flex-direction:column;min-width:0;font-size:13px;font-weight:800;line-height:1.35}
.step-btn small{font-size:11px;font-weight:500;color:#7b8fa3}
.step-btn.done{color:var(--blue-deep);border-color:#bcd8f0}
.step-btn.done b{background:#dff0e8;color:#137b59}
.step-btn.done b::after{content:'✓';font-size:13px}
.step-btn.done b i{display:none}
.step-btn.current{color:var(--blue-deep);border-color:var(--blue);background:#f0f7ff;box-shadow:0 6px 16px rgba(31,99,198,.12)}
.step-btn.current b{background:var(--blue);color:#fff}
.step-btn.current b::after{content:none}
.step-btn.current b i{display:inline}
.step-btn b i{font-style:normal}
.wizard{display:grid;grid-template-columns:minmax(0,1fr) 248px;gap:24px;align-items:start}
.wizard-main{min-width:0}
.step-panel{min-width:0}
.step-panel-head{margin:0 0 16px}
.step-panel-head h3{font-size:18px;margin:0;color:var(--blue-deep)}
.step-panel-head p{margin:6px 0 0;font-size:13px;color:var(--muted);line-height:1.7}
.form-section{border-bottom:1px solid #e2ebf4;padding-bottom:20px;margin-bottom:20px}
.form-section:last-child{border-bottom:0;padding-bottom:0;margin-bottom:0}
.form-section-title{display:flex;align-items:center;gap:9px;font-size:14px;font-weight:700;color:var(--blue-deep);margin:0 0 14px;letter-spacing:0}
.form-section-title::before{content:'';width:6px;height:18px;border-radius:5px;background:#4f9bd5}
.form-grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.form-grid-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.field-wide{grid-column:1/-1}
.field-tip{display:block;margin-top:5px;font-size:12px;color:#7b8fa3;line-height:1.6}
textarea{width:100%;min-width:0;border:1px solid #c5d3e0;border-radius:7px;padding:9px 11px;background:#fff;color:var(--ink);font:inherit;resize:vertical;min-height:58px;line-height:1.6}
textarea:hover{border-color:#7fa7cf}textarea:focus{border-color:var(--blue);outline:3px solid rgba(31,99,198,.14)}
textarea[data-autogrow]{resize:none;overflow:hidden}
.lock-notice{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;margin-top:10px;padding:8px 10px;background:#f6faff;border:1px solid #dcebf8;border-radius:6px}
.lock-notice svg{width:14px;height:14px;flex:none;color:#6e95b6}
.domain-choices{display:flex;flex-wrap:wrap;gap:10px 22px;padding:10px 0;border:0;margin:0}
.domain-choices label{display:flex;align-items:center;gap:7px;font-size:14px;font-weight:500}
.domain-choices input{width:18px;min-height:18px;accent-color:var(--blue)}
.policy-note{color:var(--muted);font-size:13px;line-height:1.8}
.context-help{padding:12px 14px;border-left:3px solid #4aa694;background:#f2faf7;font-size:13px;line-height:1.75;color:#2f5650;margin-bottom:16px}
.context-help p{margin:4px 0}
/* 逐项评分卡片 */
.item-cards{display:flex;flex-direction:column;gap:14px}
.item-card{position:relative;border:1px solid #d3e2f0;border-radius:10px;background:#fff;padding:16px 18px;box-shadow:0 3px 10px rgba(29,75,122,.04)}
.item-card.scored{border-color:#b6d8ca}
.item-card-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px}
.item-no{flex:none;display:inline-grid;place-items:center;min-width:28px;height:28px;padding:0 6px;border-radius:7px;background:#eaf3fc;color:var(--blue-deep);font-size:13px;font-weight:800}
.item-no.sm{min-width:22px;height:22px;font-size:11px;border-radius:5px;margin-right:6px}
.item-card-title{flex:1;min-width:0}
.item-card-title h4{margin:0;font-size:15px;line-height:1.5;color:var(--ink)}
.item-card-meta{margin:4px 0 0;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
.cat-chip{display:inline-block;padding:1px 8px;border-radius:999px;background:#eef5fb;color:#3d6587;font-weight:700}
.item-state{flex:none;font-size:12px;font-weight:800;padding:3px 9px;border-radius:999px;background:#f1f4f7;color:#7b8a99}
.item-state.ok{background:#e4f5ec;color:#137b59}
.item-state.changed{background:#fff2df;color:#8a5200}
.item-scores{display:flex;flex-wrap:wrap;align-items:flex-start;gap:14px 18px;margin-bottom:12px}
.item-scores .field{width:190px;max-width:100%}
.item-scores input,.item-scores select{min-height:40px}
.anchor-live{display:block;min-height:18px;margin-top:5px;font-size:12px;color:#2f6a95;line-height:1.5}
.anchor-btn{align-self:flex-end;margin-bottom:23px;min-height:40px;padding:6px 12px;border:1px dashed #8fb6da;border-radius:7px;background:#f6fbff;color:var(--blue-deep);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.anchor-btn:hover,.anchor-btn[aria-expanded=true]{background:#e8f3fd;border-style:solid}
.anchor-pop{position:relative;margin:-4px 0 14px;padding:14px 16px;border:1px solid #b7d5ef;border-radius:9px;background:#fbfdff;box-shadow:0 10px 26px rgba(29,75,122,.12);font-size:13px;line-height:1.7}
.anchor-pop .pop-title{margin:8px 0 2px;font-weight:800;color:var(--blue-deep)}
.anchor-pop .pop-title:first-child{margin-top:0}
.anchor-pop p{margin:0}
.anchor-dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px;margin:4px 0 0}
.anchor-dl div{display:flex;gap:10px;align-items:flex-start;padding:7px 9px;border-radius:7px;background:#f2f7fc}
.anchor-dl div.hit{background:#e3f1ff;outline:2px solid #8cbde8}
.anchor-dl dt{flex:none;font-weight:800;color:var(--blue-deep);min-width:38px}
.anchor-dl dd{margin:0}
.anchor-dl dd b{display:block}
.pop-note{margin-top:8px!important;color:#8a5200}
.anchor-close{margin-top:10px;min-height:32px;padding:4px 12px;font-size:12px}
.item-texts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 16px}
.item-texts .field-wide{grid-column:1/-1}
.item-texts textarea{min-height:64px;font-size:13px}
.empty-hint{padding:26px;text-align:center;color:#8a9bb0;border:1px dashed #cfe0ef;border-radius:10px}
/* 右侧小结卡 */
.wizard-summary{position:sticky;top:86px;display:flex;flex-direction:column;gap:12px;padding:16px;border:1px solid #d3e2f0;border-radius:11px;background:linear-gradient(180deg,#f5faff,#fff);font-size:13px}
.wizard-summary h3{margin:0;font-size:15px;color:var(--blue-deep)}
.sum-row{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.sum-row span{color:var(--muted)}
.sum-row strong{font-size:16px;color:var(--blue-deep);font-variant-numeric:tabular-nums;text-align:right}
.sum-progress{height:7px;border-radius:99px;background:#e3edf6;overflow:hidden}
.sum-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#3d8fd6,#2fa37f);transition:width .25s}
.sum-preview{padding:10px 11px;border-radius:8px;background:#fff;border:1px solid #e1ecf6;line-height:1.7}
.sum-preview b{color:var(--blue-deep)}
.sum-note{margin:0;font-size:11px;color:#7b8fa3;line-height:1.6}
/* 第4步核对 */
.review-list{display:grid;grid-template-columns:132px minmax(0,1fr) auto;border:1px solid #dbe7f3;border-radius:10px;overflow:hidden;margin:0}
.review-list>*{padding:10px 12px;border-bottom:1px solid #e8f0f7;font-size:13px;line-height:1.65}
.review-list dt{background:#f5f9fd;color:var(--muted);font-weight:700}
.review-list dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}
.review-list .review-edit{background:#fff}
.review-list .review-edit button{border:0;background:none;color:var(--blue);font:inherit;font-size:12px;font-weight:700;cursor:pointer;padding:0}
.review-list>*:nth-last-child(-n+3){border-bottom:0}
.review-missing{color:#8a5200}
.review-check{display:flex;align-items:flex-start;gap:10px;margin:18px 0 12px;padding:12px 14px;border:1px solid #cfe2f3;border-radius:9px;background:#f6fbff;font-size:14px;color:var(--blue-deep);font-weight:700;line-height:1.6}
.review-check input{flex:none;width:20px;min-height:20px;margin-top:2px;accent-color:var(--blue)}
.policy-summary{padding:14px 0;border-top:1px solid var(--line);margin-top:14px;font-size:13px;line-height:1.8}
.policy-summary h3{font-size:16px;margin:0 0 10px}.policy-summary summary{cursor:pointer;font-weight:700;color:var(--blue-deep)}
.policy-summary table{width:100%;border-collapse:collapse;font-size:13px}.policy-summary th,.policy-summary td{text-align:left;padding:8px 9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
.anchor-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:14px 0}.anchor-list p{margin:0;font-size:13px;line-height:1.7}
.help{font-size:13px;color:var(--muted);line-height:1.8;margin:12px 0}
.step-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:22px;padding-top:18px;border-top:1px solid #e2ebf4}
.step-nav-count{font-size:12px;color:var(--muted)}
.form-actions{display:flex;gap:10px;flex-wrap:wrap}
.unverified-notice{font-size:12px;color:#7b6000;background:#fff8dc;border:1px solid #e8d87a;border-radius:7px;padding:10px 12px;margin-bottom:16px;display:flex;align-items:flex-start;gap:7px;line-height:1.6}
.unverified-notice svg{flex:none;margin-top:1px}
.page-msg{display:none;padding:11px 13px;border-radius:7px;font-size:13px;margin:0 0 14px;border-left:3px solid}.page-msg.error{display:block;border-color:#b42318;background:#fff1f0;color:#8b1d16}.page-msg.success{display:block;border-color:#167451;background:#eaf7f2;color:#0d5c3f}.page-msg.info{display:block;border-color:var(--blue);background:#edf5ff;color:var(--blue-deep)}
.page-msg:empty{display:none}
#formMsg{margin:16px 0 0}
.field [aria-invalid=true]{border-color:#b42318;box-shadow:0 0 0 3px rgba(180,35,24,.12)}
.field-error{display:block;margin-top:5px;font-size:12px;color:#8b1d16;font-weight:600}
.field-error:empty{display:none}
.withdrawn-badge{display:inline-block;padding:2px 7px;background:#fdf0dc;border:1px solid #e8c97a;border-radius:4px;font-size:11px;color:#7b5500;margin-left:6px}
[hidden]{display:none!important}
.page-shell,.header-inner{width:min(1440px,calc(100% - 64px))}
.page-shell{padding-top:20px}
/* 结果区 */
.result-card{border:0;border-radius:0;box-shadow:none;overflow:visible}
.result-bar{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:14px 22px;background:#f0f7ff;border-radius:10px 10px 0 0}
.result-bar-main{display:flex;align-items:center;gap:10px;min-width:0}
.result-bar-main h2{margin:0;font-size:20px;color:var(--blue-deep)}
.result-keys{display:flex;flex-wrap:wrap;gap:8px;margin:0;flex:1}
.result-keys div{display:flex;align-items:baseline;gap:7px;padding:6px 12px;border-radius:8px;background:#fff;border:1px solid #d6e6f4}
.result-keys dt{font-size:12px;color:var(--muted);font-weight:700}
.result-keys dd{margin:0;font-size:18px;font-weight:800;color:var(--blue-deep);font-variant-numeric:tabular-nums}
.result-info{padding:8px 22px 10px;background:#f7fbff;border-bottom:1px solid #dbe7f3;font-size:13px}
.result-info summary{cursor:pointer;color:var(--blue-deep);font-weight:700;padding:4px 0}
.result-info[open]{padding-bottom:14px}
.result-meta-line{color:var(--muted);font-size:12px!important;line-height:1.8;margin:6px 0 0}
.result-context{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);line-height:1.7;margin:6px 0 0}
.result-goal{margin-top:8px;color:var(--muted)}
.result-goal p{margin:2px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}
.result-focus{display:flex;gap:8px;align-items:flex-start;margin-top:10px;padding:8px 12px;border-left:3px solid #4aa694;background:#fff;color:#315e61;font-size:13px;line-height:1.6}
.result-card .card-body{padding:0 22px 26px}
.tab-bar{display:flex;gap:4px;border-bottom:1px solid #cfe0ef;margin:0 -22px 20px;padding:0 22px;overflow-x:auto;background:#fff;position:sticky;top:70px;z-index:2}
.tab-btn{min-height:46px;padding:10px 17px;border:0;border-bottom:3px solid transparent;margin-bottom:-1px;background:transparent;color:var(--muted);font-size:14px;font-weight:800;cursor:pointer;transition:color .18s,background .18s;white-space:nowrap}
.tab-btn:hover{color:var(--blue);background:#f5faff}.tab-btn[aria-selected=true]{color:var(--blue);border-bottom-color:var(--blue);background:#f5faff}
.score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;margin-bottom:18px;background:#f6faff;border-block:1px solid #dbe7f3}
.score-box{border:0;border-right:1px solid #dbe7f3;border-radius:0;padding:16px 20px;background:transparent;text-align:left;min-height:96px}
.score-box:last-child{border-right:0}
.score-box-label{font-size:12px;color:var(--muted);margin-bottom:8px;font-weight:800}
.score-box-value{font-size:30px;font-weight:800;color:var(--blue-deep);font-variant-numeric:tabular-nums;line-height:1.1}
.score-box-sub{font-size:11px;color:var(--muted);margin-top:6px;line-height:1.45}
.score-box.pass{background:#f0faf5}.score-box.pass .score-box-value{color:#137b59}
.score-box.fail{background:#fff5f4}.score-box.fail .score-box-value{color:#b42318}
.score-box.na{opacity:.75}
#ePass{font-size:22px;line-height:1.35}
.score-line{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:-6px 0 18px;padding:10px 12px;background:#f7fbff;border-left:3px solid #85b8df;color:#496781;font-size:12px}
.delta-pos{color:#1f63c6!important}.delta-neg{color:#b25e00!important}.delta-zero{color:#6f8193!important}
.chart-section{margin-bottom:22px}.chart-title{font-size:14px;font-weight:800;color:var(--ink);margin:0 0 10px}
.bar-chart{display:flex;flex-direction:column;gap:10px}
.bar-legend{display:flex;gap:16px;font-size:12px;color:var(--muted)}
.bar-legend .lg::before{content:'';display:inline-block;width:12px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.lg-school::before{background:#2163c4}.lg-enh::before{background:#e09030}
.bar-row{display:grid;grid-template-columns:minmax(120px,220px) minmax(0,1fr);gap:12px;align-items:center}
.bar-label{font-size:13px;color:#3f5266;line-height:1.45;overflow-wrap:anywhere}
.bar-tracks{display:flex;flex-direction:column;gap:4px}
.bar-track{display:flex;align-items:center;gap:8px}
.bar-track::before{content:none}
.bar-bg{position:relative;flex:1;height:11px;border-radius:3px;background:#eef3f8;overflow:hidden}
.bar-bg .bar{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
.bar-school{background:#2163c4}.bar-enh{background:#e09030}
.bar-track em{flex:none;width:44px;font-style:normal;font-size:12px;font-weight:700;color:#2163c4;font-variant-numeric:tabular-nums}
.bar-track em.enh{color:#b06a00}
.diff-chart{display:flex;flex-direction:column;gap:6px}
.diff-axis{display:grid;grid-template-columns:minmax(150px,280px) minmax(0,1fr) 64px;gap:12px;font-size:12px;color:var(--muted)}
.diff-axis>span:nth-child(2){display:flex;justify-content:space-between}
.diff-row{display:grid;grid-template-columns:minmax(150px,280px) minmax(0,1fr) 64px;gap:12px;align-items:center;padding:6px 0;border-bottom:1px dashed #e4edf5}
.diff-label{display:flex;align-items:flex-start;font-size:13px;line-height:1.5;color:#33475b;overflow-wrap:anywhere}
.diff-track{position:relative;height:16px;border-radius:3px;background:#f2f6fa}
.diff-mid{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:#9fb3c6}
.diff-bar{position:absolute;top:2px;bottom:2px;border-radius:3px}
.diff-row.pos .diff-bar{background:#2b77ca}
.diff-row.neg .diff-bar{background:repeating-linear-gradient(135deg,#d88a1e 0 6px,#e6a24a 6px 9px)}
.diff-value{font-size:13px;font-weight:800;text-align:right;font-variant-numeric:tabular-nums}
.diff-row.pos .diff-value{color:#1f63c6}.diff-row.neg .diff-value{color:#b25e00}.diff-row.zero .diff-value,.diff-row.na .diff-value{color:#8a9bb0}
.chart-legend{font-size:12px;color:var(--muted);margin:8px 0 0}
.category-weights{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:18px 0;font-size:13px}
.category-weights p{margin:0;padding:12px 13px;border-left:3px solid #64a8dd;background:#f5faff;line-height:1.6}
.category-weights p b{display:block;color:var(--blue-deep);margin-bottom:3px}
.formula-block{margin:12px 0;padding:16px 18px;border:1px solid #cfe0ef;border-radius:10px;background:#fbfdff}
.formula-main{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:15px;font-weight:800;color:var(--blue-deep)}
.formula-main span{padding:5px 10px;border-radius:7px;background:#eaf3fc}
.formula-main i{font-style:normal;color:#5d7a96;font-size:17px}
.formula-main .frac{display:inline-flex;flex-direction:column;align-items:center;padding:3px 10px;line-height:1.3}
.formula-main .frac u{text-decoration:none;border-bottom:1px solid #6f93b6;padding-bottom:2px}
.formula-example{margin:12px 0 0;padding:10px 12px;border-left:3px solid #4aa694;background:#f2faf7;font-size:13px;line-height:1.8;color:#2f5650;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.formula-example b{color:#0d5c3f}
.sens-sentence{margin:6px 0;padding:12px 14px;border-radius:9px;font-size:14px;line-height:1.7}
.sens-sentence.ok{background:#eef9f3;color:#185c43}.sens-sentence.warn{background:#fff6e8;color:#7b4708}.sens-sentence.low{background:#fff3f2;color:#8b1d16}
.pro-note{margin-top:8px;font-size:13px}
.pro-note summary{cursor:pointer;color:var(--muted);font-weight:700}
.evidence-reasons{margin:20px 0}
.evidence-reasons article{padding:14px 0;border-top:1px solid var(--line)}
.evidence-reasons h3,.evidence-reasons h4{font-size:15px;margin:0 0 8px}
.evidence-reasons p{font-size:13px;line-height:1.8;margin:4px 0;color:var(--muted)}
.items-table-wrap{overflow-x:auto;border:1px solid #c9dced;border-radius:8px;margin-top:10px}
.items-table{width:100%;min-width:860px;border-collapse:collapse;background:#fff;font-size:13px}
.items-table th{background:#eaf4fd;color:#345a7e;font-size:12px;font-weight:800;padding:10px;border-bottom:1px solid #c9dced;white-space:nowrap;text-align:left}
.items-table td{padding:10px;border-bottom:1px solid #e7eef5;vertical-align:top;line-height:1.6;overflow-wrap:anywhere}
.items-table td:first-child{min-width:200px}
.items-table tr:last-child td{border-bottom:0}
.items-table .num{white-space:nowrap;font-variant-numeric:tabular-nums}
.unscored{color:#8a9bb0;font-weight:700}
.ref-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.ref-card{display:flex;flex-direction:column;gap:9px;padding:16px;border:1px solid #d6e5f2;border-radius:10px;background:#fff;box-shadow:0 3px 10px rgba(29,75,122,.04)}
.ref-title{font-size:14px;font-weight:800;color:var(--blue-deep);line-height:1.5;overflow-wrap:anywhere}
.ref-title a{color:inherit}
.ref-line{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.65;margin:0}
.tag{flex:none;display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:800}
.tag-support{background:#e1f4ea;color:#126b4b}
.tag-limit{background:#fdecd6;color:#8a4b00}
.basis-overview{margin:0 0 12px}.basis-insufficient{color:#9a5a08}#kEnhancedBasis{margin-top:4px}
@media (prefers-reduced-motion:reduce){.record-item,.button,.tab-btn,.step-btn,.sum-progress i{transition:none}}
@media print{
  .eval-sidebar,.form-actions,.tab-bar,.no-print,#formCard,.site-header,.page-heading{display:none!important}
  #resultCard [role=tabpanel][hidden]{display:block!important}
  #resultCard [role=tabpanel]{break-inside:auto;margin-top:24px}
  .items-table-wrap{overflow:visible;border:0}
  .items-table{min-width:0;font-size:9px}
  .items-table th,.items-table td{overflow-wrap:anywhere;white-space:normal;padding:4px}
  .eval-layout{display:block}
  .ref-list{grid-template-columns:1fr}
}
@media(max-width:1180px){
  .wizard{grid-template-columns:1fr}
  .wizard-summary{position:static;order:2}
}
@media(max-width:900px){
  .page-shell,.header-inner{width:calc(100% - 28px)}
  .eval-layout{grid-template-columns:1fr}
  .eval-main,#resultCard,.eval-sidebar{grid-column:1;grid-row:auto}
  .eval-sidebar{position:static}
  .score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .form-grid-3{grid-template-columns:repeat(2,minmax(0,1fr))}
  .step-btn small{display:none}
  .ref-list{grid-template-columns:1fr}
  .tab-bar{position:static}
}
@media(max-width:600px){
  .step-bar{grid-template-columns:repeat(3,minmax(0,1fr));gap:4px}
  .step-btn{flex-direction:column;justify-content:center;gap:4px;padding:8px 4px;text-align:center}
  .step-btn span{font-size:11px;align-items:center}
  .form-card .card-head,.form-card .card-body{padding:18px 14px}
  .result-bar{padding:14px}
  .result-info{padding:8px 14px}
  .result-card .card-body{padding:0 14px 18px}
  .tab-bar{margin-inline:-14px;padding-inline:8px;gap:0;flex-wrap:wrap}
  .tab-btn{padding:10px;font-size:13px}
  .category-weights,.anchor-list,.anchor-dl,.item-texts,.form-grid-3,.form-grid-2{grid-template-columns:1fr}
  .score-grid{grid-template-columns:1fr}
  .score-line{align-items:flex-start;flex-direction:column}
  .item-scores .field{width:100%}
  .anchor-btn{margin-bottom:0}
  .bar-row,.diff-row,.diff-axis{grid-template-columns:1fr}
  .diff-axis>span:first-child,.diff-axis>span:last-child{display:none}
  .diff-value{text-align:left}
  .review-list{grid-template-columns:96px minmax(0,1fr)}
  .review-list .review-edit{grid-column:1/-1;padding-top:0}
  .header-actions .button{width:auto}
}

/* 课程评价：系统建议分与类目结果 */
.course-banner{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin:0 0 14px;padding:12px 14px;border:1px solid #cfe0f5;border-left:4px solid #1f5fbf;border-radius:8px;background:#f5f9ff;font-size:13px;color:#123b70}
.course-banner strong{font-size:14px}
.course-banner .cb-counts{color:#3d526d}
.course-banner .button{min-height:32px;padding:4px 12px;font-size:12.5px}
.stale-notice{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 14px;padding:10px 14px;border:1px solid #f0c987;border-left:4px solid #d48a10;border-radius:8px;background:#fff8ec;color:#7b4708;font-size:13px}
.stale-notice strong{font-size:14px}
.sugg-box{display:grid;gap:6px;margin:8px 0 2px;padding:10px 12px;border:1px dashed #b9cdea;border-radius:8px;background:#f8fbff;font-size:13px}
.sugg-box.insufficient{border-color:#f0c987;background:#fffaf1;color:#7b4708}
.sugg-head{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.sugg-score{font-size:18px;font-weight:800;color:#1f5fbf;font-variant-numeric:tabular-nums}
.sugg-chip{display:inline-block;padding:1px 8px;border:1px solid #cfdcea;border-radius:8px;background:#fff;font-size:11.5px;color:#3d526d}
.sugg-state{display:inline-block;padding:1px 8px;border-radius:8px;font-size:11.5px;font-weight:800;background:#eef2f7;color:#4a5b70}
.sugg-state.adopted{background:#eaf7f2;color:#0d6042}.sugg-state.modified{background:#fff5e3;color:#7b4708}
.sugg-formula{margin:0;color:#3d526d;font-size:12px;line-height:1.6}
.sugg-actions{display:flex;flex-wrap:wrap;gap:6px}
.sugg-actions .button{min-height:28px;padding:2px 10px;font-size:12px}
.sugg-reason{margin-top:4px}
.course-result{margin:0 0 16px;padding:16px;border:1px solid #dde6f0;border-radius:8px;background:#fff}
.course-result h3{margin:0 0 10px;color:#123b70;font-size:16px}
.course-total{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 14px}
.course-total div{padding:10px 12px;border:1px solid #dde6f0;border-radius:8px;background:#f7faff}
.course-total span{display:block;color:#5b6b80;font-size:12px}
.course-total b{display:block;margin-top:2px;color:#172b4d;font-size:22px;font-variant-numeric:tabular-nums}
.course-total small{color:#5b6b80;font-size:12px}
.course-cats{width:100%;border-collapse:collapse;margin:0 0 14px;font-size:13px}
.course-cats th,.course-cats td{border:1px solid #dde6f0;padding:7px 9px;text-align:left}
.course-cats th{background:#eef4fb;color:#123b70}
.course-cats td.num{text-align:right;font-variant-numeric:tabular-nums}
.course-decision{font-size:12px;color:#5b6b80}
"""

_INFO_ICON = ('<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="#9a7000" stroke-width="2" width="16" height="16">'
              '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>')

_STEPS = (
    ("课程信息与口径", "课堂、学科、模板、目标"),
    ("逐项评分", "学校分与证据"),
    ("核对并保存", "预览、复核、保存"),
)


def _step_bar() -> str:
    items = []
    for index, (title, sub) in enumerate(_STEPS, start=1):
        state = " current" if index == 1 else ""
        current = ' aria-current="step"' if index == 1 else ""
        items.append(
            f'<li><button type="button" class="step-btn{state}" id="stepBtn{index}" data-step="{index}"{current}>'
            f'<b><i>{index}</i></b><span>{title}<small>{sub}</small></span></button></li>'
        )
    return '<ol class="step-bar no-print" id="stepBar" aria-label="新建评价步骤">' + "".join(items) + "</ol>"


_FORM_HTML = (
    '<div class="card form-card" id="formCard"><div class="card-head">'
    '<h2 id="formTitle">新建评价记录</h2>'
    '<p id="evaluationSource" role="status">未关联视频任务（课堂级评价，不指定单个学生）</p>'
    '</div><div class="card-body">'
    + _step_bar()
    + '<div class="wizard"><div class="wizard-main">'
    # 第1步
    '<section class="step-panel" id="stepPanel1" aria-labelledby="stepTitle1">'
    '<div class="step-panel-head"><h3 id="stepTitle1" tabindex="-1">第 1 步 · 课程信息与口径</h3>'
    '<p>先登记这节课是哪一堂课，并确认课程口径；课堂编号、日期和课程口径保存后锁定。</p></div>'
    '<div class="form-grid-3">'
    '<div class="field"><label for="fLessonId">课堂编号 <abbr title="必填">*</abbr></label>'
    '<input id="fLessonId" type="text" autocomplete="off" required maxlength="120" placeholder="如 L2026-001"/>'
    '<small class="field-tip">同一课堂同一模板只保留一条有效评价。</small></div>'
    '<div class="field"><label for="fLessonDate">上课日期 <abbr title="必填">*</abbr></label>'
    '<input id="fLessonDate" type="date" required/></div>'
    '<div class="field"><label for="fCourseName">课程名称 <abbr title="必填">*</abbr></label>'
    '<input id="fCourseName" type="text" autocomplete="off" required maxlength="200" placeholder="如 生活语文第3课"/></div>'
    '</div></section>'
    # 第2步
    '<section class="step-panel" id="stepPanel2" aria-labelledby="stepTitle2" hidden>'
    '<div class="step-panel-head"><h3 id="stepTitle2" tabindex="-1">同第 1 步 · 课程口径与本课目标</h3>'
    '<p>课程口径（保存后锁定）：学科、评价模板、评价方案和本课目标保存后不能再改，以保证前后评价可比。</p></div>'
    '<div class="form-section"><p class="form-section-title">课程口径（保存后锁定）</p>'
    '<div class="form-grid-3">'
    '<div class="field"><label for="fSubject">学科 <abbr title="必填">*</abbr></label>'
    '<select id="fSubject" required><option value="">请选择…</option></select></div>'
    '<div class="field"><label for="fTemplate">评价模板 <abbr title="必填">*</abbr></label>'
    '<select id="fTemplate" required><option value="">请选择…</option></select></div>'
    '<div class="field"><label for="fWeightPolicy">评价方案</label><select id="fWeightPolicy">'
    '<option value="school_context">学校基础 + 情境复核</option>'
    '<option value="common">通用试行权重（历史方案）</option>'
    '<option value="subject_trial">学科与本课目标试行权重</option></select>'
    '<small class="field-tip">推荐「学校基础 + 情境复核」：沿用学校分，只对有证据的项目做修正。</small></div>'
    '<div class="field field-wide" id="domainField" hidden><label>本课重点支持领域</label>'
    '<fieldset class="domain-choices" id="domainChoices" aria-label="本课重点支持领域"></fieldset>'
    '<p class="policy-note">按本课目标选择，可多选。未涉及领域不评价；学校五领域命名不同时需先核对映射。</p></div>'
    '</div>'
    '<div id="focusHint" class="lock-notice" hidden>'
    '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
    '<circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>'
    '<span id="focusHintText"></span></div></div>'
    '<div class="form-section"><p class="form-section-title">本课目标</p>'
    '<div class="field">'
    '<label for="fGoalContext">本课目标与学生分层支持约定 <abbr title="必填">*</abbr></label>'
    '<textarea id="fGoalContext" rows="4" required data-autogrow placeholder="填写本节课学习目标及学生能力分层支持安排，不填写学生姓名。"></textarea>'
    '<small class="field-tip">例如：A组能在视觉提示下指认 3 种物品；B组允许手势或沟通板回应。请不要写学生姓名。</small></div>'
    '<div id="courseTaskCard" class="course-task-card" role="region" aria-labelledby="courseTaskCardTitle" hidden></div>'
    '<div id="lockNotice" class="lock-notice" hidden>'
    '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
    '<path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
    '<span>已保存记录的学科、模板和目标口径不可更改，以保证评价一致性。</span></div>'
    '</div></section>'
    # 第3步
    '<section class="step-panel" id="stepPanel3" aria-labelledby="stepTitle3" hidden>'
    '<div class="step-panel-head"><h3 id="stepTitle3" tabindex="-1">第 2 步 · 逐项评分</h3>'
    '<p>每个评价项目一张卡片。没有评价的项目请留空，留空显示为「未评」，不按 0 分计算。点「评分参考」可查看各分值的含义。</p></div>'
    '<div class="form-section"><p class="form-section-title">评分来源</p>'
    '<div class="form-grid-2">'
    '<div class="field"><label for="fSchoolSource">学校评分来源 <abbr title="必填">*</abbr></label>'
    '<select id="fSchoolSource" required>'
    '<option value="teacher_recorded">教师自评/他评（真人打分）</option>'
    '<option value="rubric_initial">按校表初评（结构化表格）</option>'
    '</select></div>'
    '<div class="field" id="raterField"><label for="fSchoolRater">评分人 <abbr title="必填">*</abbr></label>'
    '<input id="fSchoolRater" type="text" autocomplete="off" maxlength="200" placeholder="评分教师姓名或工号"/></div>'
    '</div></div>'
    '<div id="contextHelp" class="context-help" hidden><strong>学校基础 + 情境复核</strong>'
    '<p>无新证据沿用学校分。情境修正分留空表示沿用，不是零分；修改时记录片段时间、教师应对、学生后续表现及下一课建议。未复核的修正仅作建议。</p>'
    '<p>手势、指认和辅助沟通可以是有效回应。学生出现困难、课堂中断或收音不清，不单独作为扣分依据。疑似安全事件须单独核查，不以总分代替处置。</p></div>'
    '<div id="qingpuNotice" class="unverified-notice" hidden>' + _INFO_ICON
    + '<span>该表尚无增强映射，切换基本评价指标可使用双轨对照。</span></div>'
    '<div id="courseBanner" class="course-banner" hidden></div>'
    '<div id="itemsWrap"><div id="itemsTable" aria-label="逐项评分">'
    '<div id="itemsTbody" class="item-cards" role="list"><p class="empty-hint">请先在第 2 步选择评价模板</p></div>'
    '</div></div></section>'
    # 第4步
    '<section class="step-panel" id="stepPanel4" aria-labelledby="stepTitle4" hidden>'
    '<div class="step-panel-head"><h3 id="stepTitle4" tabindex="-1">第 3 步 · 核对并保存</h3>'
    '<p>核对下面的信息，可先「预览评分」看两套结果，确认无误后保存。点击每行右侧「修改」可回到对应步骤。</p></div>'
    '<dl id="reviewSummary" class="review-list"></dl>'
    '<label class="review-check"><input type="checkbox" id="fReviewed"/>'
    '<span>我已逐项核对证据与情境，确认改分针对教学应对，而非学生障碍或采集缺失</span></label>'
    '<details class="policy-summary"><summary>查看增强评分等级与证据要求</summary><div id="anchorList" class="anchor-list"></div></details>'
    '<p class="help">未评价请留空。选择学科方案后按本课目标调整候选权重，保存后锁定。当前评分由教师录入与复核，尚未接入自动视频评分。任何字段修改后，「已核对」勾选会自动取消，请重新核对。</p>'
    '</section>'
    '<div id="formMsg" class="page-msg" role="alert"></div>'
    '<div class="step-nav no-print">'
    '<button id="stepPrev" class="button" type="button" hidden>上一步</button>'
    '<span class="step-nav-count" id="stepCount">第 1 / 3 步</span>'
    '<div class="form-actions">'
    '<button id="withdrawBtn" class="button" type="button" hidden>撤销此记录</button>'
    '<button id="previewBtn" class="button" type="button" hidden>预览评分</button>'
    '<button id="saveBtn" class="button primary" type="button" hidden>保存记录</button>'
    '<button id="stepNext" class="button primary" type="button">下一步：课程口径与本课目标</button>'
    '</div></div>'
    '</div>'
    # 小结卡
    '<aside class="wizard-summary no-print" aria-label="评分小结" aria-live="polite">'
    '<h3>评分小结</h3>'
    '<div class="sum-row"><span>当前步骤</span><strong id="sumStep">1 / 4</strong></div>'
    '<div class="sum-row"><span>学校分已评</span><strong id="sumScored">—</strong></div>'
    '<div class="sum-progress" aria-hidden="true"><i id="sumBar"></i></div>'
    '<div class="sum-row"><span id="sumEnhLabel">增强分已评</span><strong id="sumEnh">—</strong></div>'
    '<div class="sum-row"><span>学校折算10分（预估）</span><strong id="sumSchool10">—</strong></div>'
    '<div class="sum-preview" id="sumPreview">尚未预览。到第 3 步点「预览评分」查看两套结果。</div>'
    '<p class="sum-note">预估只按已填学校分平均；正式分数以「预览评分」和保存结果为准。未评项目不计 0 分。</p>'
    '</aside>'
    '</div></div></div>'
)

_RESULT_HTML = (
    '<div id="resultCard" class="card result-card" hidden>'
    '<div class="result-bar">'
    '<div class="result-bar-main"><h2>评价结果</h2><span id="resultStatus"></span></div>'
    '<dl class="result-keys" aria-label="关键分数">'
    '<div><dt>学校折算</dt><dd id="kSchool">—</dd></div>'
    '<div><dt>系统增强</dt><dd id="kEnhanced">—</dd><dd id="kEnhancedBasis" class="no-print"></dd></div>'
    '<div><dt>总分差</dt><dd id="kDelta">—</dd></div></dl>'
    '<button id="resultSaveBtn" class="button primary no-print" type="button" hidden>保存记录</button><button id="editRecordBtn" class="button no-print" type="button">查看评分与证据</button></div>'
    '<details class="result-info" id="resultInfo"><summary>课程、来源与本课目标</summary>'
    '<p id="resultMeta" class="result-meta-line"></p><p id="resultContext" class="result-context"></p>'
    '<div class="result-goal"><strong>本课目标与支持约定</strong><p id="resultGoal"></p></div>'
    '<div class="result-goal" id="resultCourseTask" hidden><strong>课程任务目标 · 系统轨逐条依据</strong>'
    '<ol id="resultCourseTaskList" class="course-task-basis"></ol></div>'
    '<div id="resultFocus" class="result-focus" hidden></div></details>'
    '<div class="card-body">'
    '<div id="courseStaleNotice" class="stale-notice" role="status" hidden></div>'
    '<section id="courseResult" class="course-result" aria-labelledby="courseResultTitle" hidden>'
    '<h3 id="courseResultTitle">课程评价结果 · 四类教学评价指标</h3>'
    '<div id="courseTotals" class="course-total"></div>'
    '<table class="course-cats" id="courseCategoryTable"><thead><tr><th scope="col">评价类目</th>'
    '<th scope="col">学校分（均分）</th><th scope="col">系统分（均分）</th><th scope="col">类目分差（系统−学校）</th>'
    '</tr></thead><tbody id="courseCategoryTbody"></tbody></table>'
    '<p class="chart-title">条目得分 · 学校 vs 系统</p>'
    '<div id="courseItemChart" class="bar-chart" role="group" aria-label="条目得分条形图：学校与系统"></div>'
    '<p class="course-decision" id="courseDecisionLine"></p>'
    '</section>'
    '<div class="tab-bar" role="tablist" aria-label="评价标签">'
    '<button class="tab-btn" role="tab" aria-selected="true" id="tabSchool" aria-controls="panelSchool">学校标准</button>'
    '<button class="tab-btn" role="tab" aria-selected="false" id="tabEnhanced" aria-controls="panelEnhanced">系统增强</button>'
    '<button class="tab-btn" role="tab" aria-selected="false" id="tabCompare" aria-controls="panelCompare">双轨对照</button>'
    '<button class="tab-btn" role="tab" aria-selected="false" id="tabBasis" aria-controls="panelBasis">评分依据</button>'
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
    '<div id="sChartWrap" class="chart-section"><p class="chart-title">学校评分（按类别）</p>'
    '<div id="sBarChart" class="bar-chart" role="group" aria-label="学校评分条形图"></div></div>'
    '</div>'
    '<div id="panelEnhanced" role="tabpanel" aria-labelledby="tabEnhanced" hidden>'
    '<div class="unverified-notice">' + _INFO_ICON
    + '<span>结果用于教学复核，尚未完成真实课堂校准。6分为项目参考线，不代表官方认证。</span></div>'
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
    '<div id="eBarChart" class="bar-chart" role="group" aria-label="增强评分条形图"></div></div>'
    '<section id="policyDetails" class="policy-summary"></section>'
    '<section id="sensitivityDetails" class="policy-summary"></section>'
    '<section class="evidence-reasons" aria-labelledby="enhancedReasonsTitle"><h3 id="enhancedReasonsTitle">差异与下一课建议</h3>'
    '<p class="help" id="enhancedDifference"></p><div id="enhancedReasons"></div></section>'
    '<section id="contextChanges" class="evidence-reasons" hidden></section>'
    '</div>'
    '<div id="panelCompare" role="tabpanel" aria-labelledby="tabCompare" hidden>'
    '<div class="unverified-notice">' + _INFO_ICON
    + '<span>差值 = 增强分 − 学校分。先解释证据复核，再解释权重调整；增强权重尚未验证。</span></div>'
    '<div class="score-grid">'
    '<div class="score-box"><div class="score-box-label">证据差值</div>'
    '<div class="score-box-value" id="cEvidDelta">—</div></div>'
    '<div class="score-box"><div class="score-box-label">权重差值</div>'
    '<div class="score-box-value" id="cWeightDelta">—</div></div>'
    '<div class="score-box"><div class="score-box-label">总分差值</div>'
    '<div class="score-box-value" id="cTotalDelta">—</div></div>'
    '</div>'
    '<div class="chart-section"><p class="chart-title">逐项分差图（增强−学校）</p>'
    '<div id="diffChart" class="diff-chart" role="group" aria-label="逐项分差图"></div>'
    '<p class="chart-legend">蓝色实心条与「+」表示增强分更高；橙色斜纹条与「−」表示学校分更高；「未评」项目不计 0 分。</p></div>'
    '<div id="compareItemsWrap" class="items-table-wrap"><table class="items-table">'
    '<thead><tr><th>项目</th><th>学校分</th><th>增强分</th><th>证据差</th><th>权重差</th><th>总差</th>'
    '<th>理由</th><th>证据</th><th>建议</th></tr></thead>'
    '<tbody id="compareItemsTbody"></tbody></table></div>'
    '</div>'
    '<div id="panelBasis" role="tabpanel" aria-labelledby="tabBasis" hidden>'
    '<div class="unverified-notice">' + _INFO_ICON
    + '<span>每个系统增强条目的分数都能查看命中锚点、证据与数据来源；证据不足的条目明确标注「证据不足，未计分」，不补造分数。</span></div>'
    '<div id="basisOverview" class="basis-overview"></div>'
    '<div id="basisItemsWrap" class="items-table-wrap"><table class="items-table" id="basisItemsTable">'
    '<thead><tr><th>条目</th><th>学校分</th><th>系统增强分</th><th>命中锚点</th><th>数据来源</th><th>状态</th><th>依据</th></tr></thead>'
    '<tbody id="basisItemsTbody"></tbody></table></div>'
    '<section class="policy-summary" id="evalRubricDetail" aria-labelledby="evalRubricTitle"></section>'
    '</div>'
    '<div id="panelRefs" role="tabpanel" aria-labelledby="tabRefs" hidden>'
    '<div id="refList" class="ref-list"></div></div>'
    '<div class="form-actions no-print" style="margin-top:18px;padding-top:16px;border-top:1px solid #e2ebf4">'
    '<button id="exportJsonBtn" class="button" type="button">导出 JSON</button>'
    '<button id="printBtn" class="button" type="button" onclick="window.print()">打印</button>'
    '</div></div></div>'
)

_SCRIPT = r"""
let evalCourseTask=null,courseTaskAutoText="",courseTaskRequest=0;
let courseData=null,courseRequest=0,courseError="";const modifiedLogged=new Set();
const COURSE_TEMPLATE="basic_100";
const SERVER_ACCOUNT=__ACCOUNT_JSON__;
const API="__API__";
const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const byId=id=>document.getElementById(id);
const fieldByName=name=>document.querySelector(`#itemsTbody [name="${name}"]`);
let workspace=null,activeRecord=null,previewResult=null,renderedRecord=null,formRevision=0,busy=false,focusAfter="";
let currentStep=1,maxStep=1;
const STEP_NAMES=["课程信息与口径","逐项评分","核对并保存"];
function focusInvalid(){if(!focusAfter)return;const el=byId(focusAfter)||fieldByName(focusAfter);focusAfter="";if(el&&!el.disabled){el.scrollIntoView({block:"center"});el.focus();}}
const sourceParams=new URLSearchParams(location.search);
const sourceValues=[...sourceParams.getAll("currenttask"),...sourceParams.getAll("task_id")];
const requestedTask=sourceValues.length===1&&/^[A-Za-z0-9_-]{1,120}$/.test(sourceValues[0])?sourceValues[0]:"";
let sourceError=sourceValues.length&&!requestedTask?"课堂任务链接无效，请从原任务重新进入。":"",taskSource=null;
function sourceLabel(rec){const source=rec||taskSource;byId("evaluationSource").textContent=sourceError||
(source?.task_id?"课堂级来源任务："+source.task_id+" · "+(source.source_provenance?.status==="needs_reconfirmation"?"来源待重新确认":"已关联视频版本")+"；不指定单个学生":"未关联视频任务（课堂级评价，不指定单个学生）");}
const SAFE_ID=/^[A-Za-z0-9_.:-]{1,120}$/;
function dbg(operation,result,extra){
const body={operation,result,...(extra||{})};
const rid=activeRecord?.record_id;if(rid&&SAFE_ID.test(rid))body.record_id=rid;
const cid=activeRecord?.course_id||taskSource?.course_id;if(cid&&SAFE_ID.test(cid))body.course_id=cid;
const tid=activeRecord?.task_id||taskSource?.task_id;if(tid&&SAFE_ID.test(tid))body.task_id=tid;
const tpl=byId("fTemplate").value;if(tpl&&SAFE_ID.test(tpl))body.template_id=tpl;
try{fetch(API+"/evaluations/debug-event",{method:"POST",credentials:"include",keepalive:true,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).catch(()=>{});}catch(_){}}
function currentTemplate(){return (workspace?.templates||[]).find(t=>t.id===byId("fTemplate").value)||null;}
function invalidate(){formRevision++;previewResult=null;renderedRecord=null;byId("resultCard").hidden=true;byId("formCard").hidden=false;}
function setBusy(value){busy=value;["previewBtn","saveBtn","withdrawBtn","newBtn","stepPrev","stepNext"].forEach(id=>byId(id).disabled=value);document.querySelectorAll("#formCard input,#formCard select,#formCard textarea").forEach(el=>{if(value){el.dataset.priorDisabled=String(el.disabled);el.disabled=true;}else{el.disabled=el.dataset.priorDisabled==="true";}});}
async function api(url,opts){
const r=await fetch(url,{credentials:"include",...(opts||{})});
const d=await r.json().catch(()=>({}));
if(!r.ok||!d.ok){const e=d.error||{};const err=new Error(e.message||"HTTP "+r.status);err.code=e.code;err.status=r.status;err.field=e.field;throw err;}
return d;}
const formGuard=(window.RxUI&&RxUI.trackForm)?RxUI.trackForm("#formCard"):{isDirty(){return false;},clean(){},markDirty(){}};
function okToast(t){if(window.RxUI?.success)RxUI.success(t);}
async function askReason(opts){
if(window.RxUI?.confirmDialog)return RxUI.confirmDialog(opts);
const v=prompt(opts.input.label+"（必填）：");return v&&v.trim()?v.trim():null;}
function msg(t,k="error"){const el=byId("pageMsg");el.className="page-msg "+k;el.textContent=t;}
function fmsg(t,k="error"){const el=byId("formMsg");el.className="page-msg "+k;el.textContent=t;}
function clearFmsg(){const el=byId("formMsg");el.className="page-msg";el.textContent="";}
function autoGrow(el){if(!el||el.tagName!=="TEXTAREA")return;el.style.height="auto";el.style.height=Math.max(el.scrollHeight+2,58)+"px";}
function growAll(){document.querySelectorAll("#formCard textarea[data-autogrow]").forEach(autoGrow);}
function onSchoolSourceChange(){
const rf=byId("raterField");
if(rf)rf.hidden=byId("fSchoolSource").value!=="teacher_recorded";}
function onSubjectChange(){
const id=byId("fSubject").value;
const s=(workspace?.subjects||[]).find(s=>s.id===id);
const hint=byId("focusHint");const ht=byId("focusHintText");
if(s?.focus?.length){ht.textContent="课程关注点："+s.focus.join("、")+(s.note?"。"+s.note:"");hint.hidden=false;}
else{hint.hidden=true;}}
function updatePolicy(){const trial=byId("fWeightPolicy").value==="subject_trial";byId("domainField").hidden=!trial;const legacy=byId("fTemplate").value==="qingpu_15";if(legacy){byId("fWeightPolicy").value="common";byId("domainField").hidden=true;}if(!trial||legacy)document.querySelectorAll("#domainChoices input").forEach(el=>el.checked=false);byId("contextHelp").hidden=byId("fWeightPolicy").value!=="school_context";updateWeightHints();}
function updateWeightHints(){const t=currentTemplate();const contextual=byId("fWeightPolicy").value==="school_context";
document.querySelectorAll("[data-enh-label]").forEach(el=>el.textContent=contextual?"情境修正分（留空=沿用学校分）":"增强分");
document.querySelectorAll("[data-weight-label]").forEach(el=>el.textContent=contextual?"修正权重":"增强权重");
if(!t?.enhanced_available){updateSummary();return;}const policy=workspace.weight_policy;if(!policy){updateSummary();return;}const trial=byId("fWeightPolicy").value==="subject_trial";const domains=trial?[...document.querySelectorAll("#domainChoices input:checked")].map(el=>el.value):[];const subjectItems=trial?(policy.subject_items[byId("fSubject").value]||[]):[];const raws=t.items.map(i=>(contextual?i.school_weight:i.enhanced_weight)*(1+(subjectItems.includes(i.id)?.1:0)+(domains.length?.1*policy.domains.filter(d=>domains.includes(d.id)&&d.items.includes(i.id)).length/domains.length:0)));const sum=raws.reduce((a,b)=>a+b,0);t.items.forEach((item,n)=>{const el=document.querySelector(`[data-weight-for="${item.id}"]`);if(el)el.textContent=(raws[n]/sum*100).toFixed(2)+"%";const input=fieldByName("enhanced_"+item.id);if(input)input.placeholder=contextual?"留空=沿用学校分":"0—10，未评留空";});
document.querySelectorAll("#itemsTbody input[name^=enhanced_]").forEach(updateLive);updateSummary();}
function onTemplateChange(){
const id=byId("fTemplate").value;
if(!id){byId("itemsTbody").innerHTML='<p class="empty-hint">请先在第 2 步选择评价模板</p>';
byId("qingpuNotice").hidden=true;updateSummary();return;}
const tmpl=(workspace?.templates||[]).find(t=>t.id===id);if(!tmpl)return;
const isQ=id==="qingpu_15";
byId("qingpuNotice").hidden=!isQ;
renderItemsTable(tmpl,null);updatePolicy();clearFmsg();byId("resultCard").hidden=true;previewResult=null;if(courseMode())prefillSuggestions();}
function populateSubjects(){
const sel=byId("fSubject");
sel.innerHTML='<option value="">请选择学科…</option>'+
(workspace?.subjects||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");
sel.addEventListener("change",onSubjectChange);}
function populateTemplates(){
const sel=byId("fTemplate");
sel.innerHTML='<option value="">请选择模板…</option>'+
(workspace?.templates||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join("");
sel.addEventListener("change",onTemplateChange);}
function schoolGrade(v,isQ){if(v==null||isNaN(v))return"";if(isQ)return{5:"等第 A（5）",4:"等第 B（4）",3:"等第 C（3）",2:"等第 D（2）"}[v]||"";if(v>=9)return"学校等级 A（9—10 分）";if(v>=6)return"学校等级 B（6—8 分）";if(v>=3)return"学校等级 C（3—5 分）";return"学校等级 D（1—2 分）";}
function anchorMeaning(v){const anchors=[...(workspace?.weight_policy?.anchors||[])].sort((a,b)=>a.score-b.score);if(v==null||isNaN(v)||!anchors.length)return"";const exact=anchors.find(a=>a.score===v);if(exact)return`${v} 分 · ${exact.label}`;const lower=[...anchors].reverse().find(a=>a.score<v);const upper=anchors.find(a=>a.score>v);if(lower&&upper)return`${v} 分 · 介于「${lower.label}」与「${upper.label}」之间`;return"";}
function updateLive(input){if(!input)return;const out=document.querySelector(`[data-live-for="${input.name}"]`);if(!out)return;const t=currentTemplate();const isQ=t?.id==="qingpu_15";const raw=input.value;
if(raw===""){out.textContent=input.name.startsWith("enhanced_")&&byId("fWeightPolicy").value==="school_context"?"留空 = 沿用学校分":"未评（留空不计 0 分）";syncAnchorHit(input,null);return;}
const v=Number(raw);if(input.name.startsWith("school_")){out.textContent=schoolGrade(v,isQ);}else{out.textContent=anchorMeaning(v);syncAnchorHit(input,v);}}
function syncAnchorHit(input,v){const id=input.name.replace(/^enhanced_/,"");document.querySelectorAll(`#anchorPop_${id} .anchor-dl div`).forEach(el=>el.classList.toggle("hit",v!=null&&Number(el.dataset.score)===Math.round(v/2)*2));}
function anchorPopHtml(item,tmpl){const isQ=tmpl.id==="qingpu_15";const anchors=workspace?.weight_policy?.anchors||[];
return `<p class="pop-title">本项核对要点</p><p>${esc(item.anchor||"按学校原表要求核对。")}</p>`+
`<p class="pop-title">学校原表等级</p><p>${esc(tmpl.rules_note||"")}</p>`+
(isQ?"":`<p class="pop-title">增强 / 情境修正分锚点（0—10）</p><dl class="anchor-dl">${anchors.map(a=>`<div data-score="${a.score}"><dt>${a.score} 分</dt><dd><b>${esc(a.label)}</b>${esc(a.detail)}</dd></div>`).join("")}</dl>`)+
`<p class="pop-note">没有评价请留空，缺失或未观察不按 0 分处理。</p><button type="button" class="button quiet anchor-close" data-close="${item.id}">收起评分参考</button>`;}
function renderItemsTable(tmpl,existingItems){
const isQ=tmpl.id==="qingpu_15";
const cats=Object.fromEntries((tmpl.categories||[]).map(c=>[c.id,c]));
const cards=(tmpl.items||[]).map((item,n)=>{
const ex=existingItems?.find(e=>e.id===item.id)||{};
const cat=cats[item.category_id]||{};
const sw=((item.school_weight||0)*100).toFixed(isQ?1:0)+"%";
const ew=isQ?"—":((item.enhanced_weight||0)*100).toFixed(0)+"%";
const sid="school_"+item.id,eid="enhanced_"+item.id,sAttr=`id="${sid}" name="${sid}"`;
const schoolInput=isQ
?`<select ${sAttr}><option value="">未评（留空）</option>${[5,4,3,2].map(v=>`<option value="${v}"${ex.school_score===v?" selected":""}>${{5:"A",4:"B",3:"C",2:"D"}[v]} · ${v}</option>`).join("")}</select>`
:`<input ${sAttr} type="number" min="1" max="10" step="1" inputmode="numeric" value="${ex.school_score!=null?ex.school_score:""}" placeholder="1—10，未评留空"/>`;
const enhField=isQ?"":`<div class="field"><label for="${eid}" data-enh-label>增强分</label><input id="${eid}" type="number" name="${eid}" min="0" max="10" step="0.5" inputmode="decimal" value="${ex.enhanced_score!=null?ex.enhanced_score:""}" placeholder="0—10，未评留空"/><small class="anchor-live" data-live-for="${eid}"></small></div>`;
return `<article class="item-card" role="listitem" data-item="${esc(item.id)}">
<header class="item-card-head"><span class="item-no">${n+1}</span><div class="item-card-title"><h4 id="itemTitle_${item.id}">${esc(item.label)}</h4>
<p class="item-card-meta"><span class="cat-chip" title="${esc(cat.rationale||"")}">${esc(cat.label||item.category_id||"")}</span><span>学校权重 ${sw}</span>${isQ?"":`<span><span data-weight-label>增强权重</span> <b data-weight-for="${item.id}">${ew}</b></span>`}</p></div>
<span class="item-state" data-state-for="${item.id}">未评</span></header>
<div class="item-scores"><div class="field"><label for="${sid}">${isQ?"学校原表等第":"学校分"}</label>${schoolInput}<small class="anchor-live" data-live-for="${sid}"></small></div>${enhField}
<button type="button" class="anchor-btn" aria-expanded="false" aria-controls="anchorPop_${item.id}" data-anchor="${item.id}">评分参考</button></div>
<div class="anchor-pop" id="anchorPop_${item.id}" role="region" aria-labelledby="itemTitle_${item.id}" hidden>${anchorPopHtml(item,tmpl)}</div>
<div class="item-texts">
<div class="field field-wide"><label for="evidence_${item.id}">证据摘要</label><textarea id="evidence_${item.id}" name="evidence_${item.id}" rows="2" maxlength="2000" data-autogrow placeholder="观察到的片段时间点、教案页码或课堂记录">${esc(ex.evidence||"")}</textarea></div>
<div class="field"><label for="reason_${item.id}">改分理由</label><textarea id="reason_${item.id}" name="reason_${item.id}" rows="2" maxlength="2000" data-autogrow placeholder="${isQ?"可选":"增强分/修正分与学校分不同时必填"}">${esc(ex.reason||"")}</textarea></div>
<div class="field"><label for="suggestion_${item.id}">改进建议</label><textarea id="suggestion_${item.id}" name="suggestion_${item.id}" rows="2" maxlength="2000" data-autogrow placeholder="可选；情境修正时必填">${esc(ex.suggestion||"")}</textarea></div>
</div></article>`;}).join("");
byId("itemsTbody").innerHTML=cards||'<p class="empty-hint">模板无评价项</p>';
document.querySelectorAll("#itemsTbody input,#itemsTbody select").forEach(updateLive);
annotateItemsWithGoals();
renderSuggestionBoxes(existingItems);
requestAnimationFrame(growAll);updateSummary();}
function scoreCounts(){const t=currentTemplate();const out={total:t?.items?.length||0,school:0,enh:0,sum:0,changed:0,isQ:t?.id==="qingpu_15",missing:[]};if(!t)return out;
t.items.forEach(i=>{const sv=fieldByName("school_"+i.id)?.value;const ev=fieldByName("enhanced_"+i.id)?.value;const hasS=sv!==""&&sv!=null,hasE=ev!==""&&ev!=null;
if(hasS){out.school++;out.sum+=Number(sv);}else out.missing.push(i.label);if(hasE)out.enh++;if(hasE&&(!hasS||Number(ev)!==Number(sv)))out.changed++;
const badge=document.querySelector(`[data-state-for="${i.id}"]`);if(badge){const changed=hasE&&(!hasS||Number(ev)!==Number(sv));badge.textContent=changed?"已修正":hasS?"已评":"未评";badge.className="item-state"+(changed?" changed":hasS?" ok":"");badge.closest(".item-card")?.classList.toggle("scored",hasS);}});return out;}
function updateSummary(){const c=scoreCounts();updateSuggestionStates();const ctx=byId("fWeightPolicy").value==="school_context";
byId("sumStep").textContent=`${currentStep} / 3`;
byId("sumScored").textContent=c.total?`${c.school} / ${c.total}`:"—";
byId("sumBar").style.width=c.total?(c.school/c.total*100)+"%":"0";
byId("sumEnhLabel").textContent=ctx?"情境修正项":"增强分已评";
byId("sumEnh").textContent=!c.total?"—":c.isQ?"无增强映射":ctx?`${c.changed} 项（其余沿用）`:`${c.enh} / ${c.total}`;
byId("sumSchool10").textContent=c.total&&c.school===c.total?(c.sum/c.total*(c.isQ?2:1)).toFixed(2):c.total?"待评完":"—";
const res=previewResult||(!byId("resultCard").hidden&&renderedRecord?.result)||activeRecord?.result;
byId("sumPreview").innerHTML=res?`<b>${previewResult?"最近预览":"已保存结果"}</b>（${esc(statusLabel(res.status))}）<br>学校折算 ${fmtNum(res.school?.score_10,2)} · 系统增强 ${fmtNum(res.enhanced?.score_10,2)}<br>总分差 ${signed(res.comparison?.available?res.comparison.total_delta:null)}`:"尚未预览。到第 3 步点「预览评分」查看两套结果。";}
const REQUIRED_FIELDS=[["fLessonId","请填写课堂编号"],["fLessonDate","请选择上课日期"],["fCourseName","请填写课程名称"],
["fSubject","请选择学科"],["fTemplate","请选择评价模板"],["fGoalContext","请填写本课目标与学生分层支持约定"],
["fSchoolSource","请选择学校评分来源"],["fSchoolRater","请填写评分人"]];
const FIELD_STEP={fLessonId:1,fLessonDate:1,fCourseName:1,fSubject:1,fTemplate:1,fGoalContext:1,fSchoolSource:3,fSchoolRater:3};
function fieldError(el,text){if(!el)return;const field=el.closest(".field");let note=field?.querySelector(".field-error");
if(!note&&field){note=document.createElement("span");note.className="field-error";note.id=el.id+"Error";note.setAttribute("role","alert");field.appendChild(note);}
if(text){el.setAttribute("aria-invalid","true");if(note){note.textContent=text;el.setAttribute("aria-describedby",note.id);}}
else{el.removeAttribute("aria-invalid");if(note)note.textContent="";}}
function clearFieldErrors(){document.querySelectorAll('#formCard [aria-invalid="true"]').forEach(el=>fieldError(el,""));REQUIRED_FIELDS.forEach(([id])=>fieldError(byId(id),""));}
function goalNameError(e){if(e?.code!=="goal_contains_student_name")return;showStep(2,true);fieldError(byId("fGoalContext"),e.message);e.focusId="fGoalContext";byId("fGoalContext").scrollIntoView({block:"center"});}
function missingFields(steps){return REQUIRED_FIELDS.filter(([id])=>{if(!steps.includes(FIELD_STEP[id]))return false;const el=byId(id);
if(id==="fSchoolRater"&&(byId("fSchoolSource").value!=="teacher_recorded"||byId("raterField").hidden))return false;
return !String(el.value||"").trim();});}
function itemProblems(){const t=currentTemplate();if(!t)return[];const isQ=t.id==="qingpu_15";const ctx=byId("fWeightPolicy").value==="school_context";const out=[];
t.items.forEach(item=>{const sf=fieldByName("school_"+item.id),ef=fieldByName("enhanced_"+item.id);
const s=sf&&sf.value!==""?Number(sf.value):null;const z=!isQ&&ef&&ef.value!==""?Number(ef.value):null;
if(courseMode()&&z!=null&&Number.isFinite(z)){const sg=suggestionFor(item.id);const rf=fieldByName("suggestion_reason_"+item.id);if(sg&&sg.suggested_score!=null&&z!==sg.suggested_score&&rf&&!rf.value.trim())out.push(["suggestion_reason_"+item.id,"修改了系统建议分，请填写修改理由","suggestion_reason_required"]);}
if(s!=null&&(!Number.isFinite(s)||s<(isQ?2:1)||s>(isQ?5:10)))out.push(["school_"+item.id,isQ?"请选择 A—D 等第":"学校分须在 1—10 之间，未评请留空","score_out_of_range"]);
if(!isQ&&ef&&ef.value===""&&ef.validity?.badInput)out.push(["enhanced_"+item.id,"请输入数字，未评请留空","score_out_of_range"]);
if(z!=null&&(!Number.isFinite(z)||z<0||z>10)){out.push(["enhanced_"+item.id,"分数须在 0—10 之间，未评请留空","score_out_of_range"]);return;}
if(ctx&&z!=null&&s==null){out.push(["enhanced_"+item.id,"情境修正需要先录入该项学校基础分","context_base_required"]);return;}
if(z!=null&&z!==s){const need=ctx?["evidence","reason","suggestion"]:["reason"];const text={evidence:"情境修正须填写证据时间点",reason:ctx?"请写明教师应对与学生后续表现":"增强分与学校分不同，请说明改分理由",suggestion:"情境修正须填写下一课建议"};
need.forEach(k=>{const f=fieldByName(k+"_"+item.id);if(f&&!f.value.trim())out.push([k+"_"+item.id,text[k],"reason_required"]);});}});
return out;}
function validateStep(n){
const scope=n===1?[1,2]:n===2?[3]:[4];
scope.forEach(p=>document.querySelectorAll(`#stepPanel${p} [aria-invalid="true"]`).forEach(el=>fieldError(el,"")));
const miss=n===1?missingFields([1,2]):n===3?missingFields([3]):[];const probs=n===2?itemProblems():[];
miss.forEach(([id,text])=>fieldError(byId(id),text));
probs.forEach(([name,text])=>fieldError(fieldByName(name),text));
const bad=[...miss.map(m=>m[0]),...probs.map(p=>p[0])];
if(bad.length)dbg("evaluation_step_invalid","blocked",{step:n,code:miss.length?"required_missing":probs[0][2],fields:bad.slice(0,40)});
return bad;}
function reviewedEvidenceProblems(){const t=currentTemplate();if(!t||!byId("fReviewed").checked)return[];const isQ=t.id==="qingpu_15";const out=[];
t.items.forEach((item,idx)=>{const sf=fieldByName("school_"+item.id),ef=fieldByName("enhanced_"+item.id),vf=fieldByName("evidence_"+item.id);
const scored=(sf&&sf.value!=="")||(!isQ&&ef&&ef.value!=="");if(scored&&vf&&!vf.value.trim())out.push(["evidence_"+item.id,idx+1]);});
return out;}
function validateRequired(){
for(const s of [1,2,3]){const bad=validateStep(s);if(!bad.length)continue;showStep(s,true);
const miss=missingFields(s===1?[1,2]:s===3?[3]:[]);const err=new Error(miss.length?`请先完成第 ${s} 步必填项：${miss.map(m=>m[1].replace(/^请(填写|选择)/,"")).join("、")}。`:"第 2 步逐项评分有需要修改的内容，请按字段下方的红字提示调整。");err.focusId=bad[0];throw err;}
const noEvidence=reviewedEvidenceProblems();
if(noEvidence.length){noEvidence.forEach(([name])=>fieldError(fieldByName(name),"已勾选「已核对」，有评分的项目须填写证据摘要"));
dbg("evaluation_step_invalid","blocked",{step:2,code:"evidence_required",fields:noEvidence.map(p=>p[0]).slice(0,40)});
showStep(2,true);const err=new Error(`已勾选「已核对」：第 ${noEvidence.map(p=>p[1]).join("、")} 项有评分但缺少证据摘要，请补充后再预览或保存；若暂不核对，可取消勾选后保存为草稿。`);err.focusId=noEvidence[0][0];throw err;}}
function showStep(n,silent){currentStep=n;maxStep=Math.max(maxStep,n);
const panels=n===1?[1,2]:n===2?[3]:[4];
for(let i=1;i<=4;i++){byId("stepPanel"+i).hidden=!panels.includes(i);}
for(let i=1;i<=3;i++){const b=byId("stepBtn"+i);b.classList.toggle("current",i===n);b.classList.toggle("done",i!==n&&i<=maxStep&&i<n);if(i===n)b.setAttribute("aria-current","step");else b.removeAttribute("aria-current");}
byId("stepPrev").hidden=n===1;byId("stepNext").hidden=n===3;byId("stepNext").textContent=n<3?`下一步：${STEP_NAMES[n]}`:"下一步";
byId("previewBtn").hidden=n!==3;byId("saveBtn").hidden=n!==3;byId("withdrawBtn").hidden=n!==3||!activeRecord||activeRecord.status==="withdrawn";
byId("stepCount").textContent=`第 ${n} / 3 步 · ${STEP_NAMES[n-1]}`;
if(n===3)renderReviewSummary();
if(n===2)requestAnimationFrame(growAll);
if(n===1)requestAnimationFrame(()=>autoGrow(byId("fGoalContext")));
updateSummary();
if(!silent){const card=byId("formCard");if(card.getBoundingClientRect().top<0)card.scrollIntoView({block:"start"});byId("stepTitle"+panels[0]).focus({preventScroll:true});}}
function tryGo(target){if(busy||target===currentStep)return;
if(target<currentStep){clearFmsg();showStep(target);return;}
for(let s=currentStep;s<target;s++){const bad=validateStep(s);if(bad.length){if(s!==currentStep)showStep(s,true);fmsg(`请先完成第 ${s} 步「${STEP_NAMES[s-1]}」中标红的内容，再进入下一步。`);focusAfter=bad[0];focusInvalid();return;}}
clearFmsg();showStep(target);dbg("evaluation_step_enter","ok",{step:target});}
function renderReviewSummary(){const t=currentTemplate();const subj=(workspace?.subjects||[]).find(s=>s.id===byId("fSubject").value);const c=scoreCounts();
const policy=byId("fWeightPolicy").selectedOptions[0]?.textContent||"";const domains=[...document.querySelectorAll("#domainChoices input:checked")].map(el=>el.parentElement.textContent.trim());
const src=byId("fSchoolSource").selectedOptions[0]?.textContent||"";const rater=byId("fSchoolSource").value==="teacher_recorded"?byId("fSchoolRater").value.trim():"（按校表初评，无需填写）";
const row=(k,v,step,cls)=>`<dt>${k}</dt><dd${cls?` class="${cls}"`:""}>${v}</dd><div class="review-edit"><button type="button" data-goto="${step}">修改</button></div>`;
byId("reviewSummary").innerHTML=row("课堂编号",esc(byId("fLessonId").value.trim()),1)+row("上课日期",esc(byId("fLessonDate").value),1)+row("课程名称",esc(byId("fCourseName").value.trim()),1)+
row("学科",esc(subj?.label||"—"),1)+row("评价模板",esc(t?.label||"—"),1)+row("评价方案",esc(policy)+(domains.length?`；本课重点：${esc(domains.join("、"))}`:""),1)+
row("本课目标",esc(byId("fGoalContext").value.trim()),1)+row("评分来源",esc(src)+" · 评分人："+esc(rater),3)+
row("逐项评分",c.total?`学校分已评 ${c.school} / ${c.total} 项${c.isQ?"":byId("fWeightPolicy").value==="school_context"?`，情境修正 ${c.changed} 项`:`，增强分已评 ${c.enh} / ${c.total} 项`}`:"—",2)+
row("未评项目",c.missing.length?`${c.missing.length} 项未评，保存后显示「未评」，不按 0 分计算：${esc(c.missing.join("；"))}`:"无，全部已评",2,c.missing.length?"review-missing":"");}
function buildPayload(recordId,expectedVersion){
const schoolSource=byId("fSchoolSource").value;
const tmpl=currentTemplate();
if(!tmpl)throw new Error("未找到所选模板。");
const isQ=tmpl.id==="qingpu_15";
const items=(tmpl.items||[]).map(item=>{
const sf=fieldByName("school_"+item.id);
const ef=fieldByName("enhanced_"+item.id);
const ev=fieldByName("evidence_"+item.id)?.value.trim()||"";
const re=fieldByName("reason_"+item.id)?.value.trim()||"";
const sg=fieldByName("suggestion_"+item.id)?.value.trim()||"";
const sv=sf?.value;
const school_score=sv!==""&&sv!=null?Number(sv):null;
const enhanced_score=isQ?null:(ef?.value!==""&&ef?.value!=null?Number(ef.value):null);
return {id:item.id,school_score,enhanced_score,evidence:ev,reason:re,suggestion:sg};});
if(sourceError)throw new Error(sourceError);
if(requestedTask&&!taskSource)throw new Error("正在核验课堂来源，请稍后重试。");
const source=activeRecord||taskSource;
if(source?.source_provenance?.status==="needs_reconfirmation")throw new Error("视频来源已失效，请核对后新建评价。");
return {...(source?.task_id?{task_id:source.task_id,frame_revision:source.frame_revision}:{}),record_id:recordId||crypto.randomUUID(),expected_version:expectedVersion??0,
lesson_id:byId("fLessonId").value.trim(),lesson_date:byId("fLessonDate").value,course_name:byId("fCourseName").value.trim(),
subject_id:byId("fSubject").value,template_id:tmpl.id,goal_context:byId("fGoalContext").value.trim(),
school_source:schoolSource,school_rater:schoolSource==="teacher_recorded"?byId("fSchoolRater").value.trim():"",reviewed:byId("fReviewed").checked,items,weight_policy:byId("fWeightPolicy").value,focus_domains:[...document.querySelectorAll("#domainChoices input:checked")].map(el=>el.value),...courseTaskPayload(),...coursePayload()};}
function collectPayload(recordId,expectedVersion){validateRequired();return buildPayload(recordId,expectedVersion);}
function loadRecordIntoForm(rec){
formGuard.clean();
activeRecord=rec;previewResult=null;clearFieldErrors();byId("resultCard").hidden=true;
sourceLabel(rec);
byId("fLessonId").value=rec.lesson_id||"";
byId("fLessonDate").value=rec.lesson_date||"";
byId("fCourseName").value=rec.course_name||"";
byId("fSubject").value=rec.subject_id||"";
byId("fTemplate").value=rec.template_id||"";
byId("fWeightPolicy").value=rec.weight_policy||"common";document.querySelectorAll("#domainChoices input").forEach(el=>{el.checked=(rec.focus_domains||[]).includes(el.value);el.disabled=rec.version>0;});
byId("fGoalContext").value=rec.goal_context||"";
courseTaskFromRecord(rec);
byId("fSchoolSource").value=rec.school_source||"teacher_recorded";
byId("fSchoolRater").value=rec.school_rater||"";
byId("fReviewed").checked=rec.reviewed===true;byId("qingpuNotice").hidden=rec.template_id!=="qingpu_15";
onSchoolSourceChange();onSubjectChange();
const tmpl=(workspace?.templates||[]).find(t=>t.id===rec.template_id);
if(tmpl)renderItemsTable(tmpl,rec.items||[]);
updatePolicy();byId("fWeightPolicy").disabled=rec.version>0;
const locked=rec.version>0;
byId("fSubject").disabled=locked;byId("fTemplate").disabled=locked;byId("fGoalContext").disabled=locked;
byId("fLessonId").disabled=locked;byId("fLessonDate").disabled=locked;
byId("lockNotice").hidden=!locked;
byId("formTitle").textContent=(rec.status==="withdrawn"?"[已撤销] ":"")+"编辑评价记录";
maxStep=4;showStep(3,true);
if(rec.course_evaluation&&rec.task_id&&courseData?.task_id!==rec.task_id)loadCourseData(rec.task_id);
if(rec.result)renderResult(rec.result,rec);}
function fmtNum(v,digits){return v!=null&&!isNaN(v)?Number(v).toFixed(digits??1):"—";}
function signed(v,digits){if(v==null||isNaN(v))return"—";const n=Number(v);const text=Math.abs(n).toFixed(digits??2);return n>0?"+"+text:n<0?"−"+text:text;}
function deltaClass(v){return v==null||isNaN(v)?"":Number(v)>0?"delta-pos":Number(v)<0?"delta-neg":"delta-zero";}
function setDelta(id,v,available){const el=byId(id);el.className="score-box-value "+(available?deltaClass(v):"");el.textContent=available&&v!=null?signed(v,2):"不可用";}
function scoreOrUnrated(v,digits){return v!=null&&!isNaN(v)?fmtNum(v,digits):'<span class="unscored">未评</span>';}
function statusLabel(s){return{reviewed:"已复核",provisional:"草稿",incomplete:"草稿·未评完",withdrawn:"已撤销",active:"有效"}[s]||s||"—";}
function renderBarChart(id,items,schoolKey,enhKey,labels){
const el=byId(id);if(!el)return;const both=enhKey!=="unused";const names=labels||["学校","增强"];
if(!items.length){el.innerHTML='<p class="help">无数据</p>';return;}
el.innerHTML=`<div class="bar-legend"><span class="lg lg-school">${names[0]}</span>${both?`<span class="lg lg-enh">${names[1]}</span>`:""}</div>`+items.map(item=>{const sv=item[schoolKey];const ev=both?item[enhKey]:null;
return `<div class="bar-row"><div class="bar-label">${esc(item.label||item.id)}</div><div class="bar-tracks">
<div class="bar-track"><span class="bar-bg"><span class="bar bar-school" style="width:${sv!=null?Math.max(0,Math.min(100,sv*10)):0}%"></span></span><em>${sv!=null?fmtNum(sv,1):"未评"}</em></div>
${both?`<div class="bar-track"><span class="bar-bg"><span class="bar bar-enh" style="width:${ev!=null?Math.max(0,Math.min(100,ev*10)):0}%"></span></span><em class="enh">${ev!=null?fmtNum(ev,1):"未评"}</em></div>`:""}</div></div>`;}).join("");}
function renderDiffChart(id,items){
const el=byId(id);if(!el)return;
if(!items.length){el.innerHTML='<p class="help">无数据</p>';return;}
const maxDelta=Math.max(.1,...items.map(x=>Math.abs(x.total_delta||0)));
el.innerHTML='<div class="diff-axis" aria-hidden="true"><span>评价项目</span><span><span>← 学校分更高</span><span>增强分更高 →</span></span><span>总差</span></div>'+items.map((item,n)=>{
const d=item.total_delta;const unrated=item.school_score==null||item.enhanced_score==null;
const cls=d==null?"na":d>0?"pos":d<0?"neg":"zero";const w=d!=null?Math.abs(d)/maxDelta*50:0;
return `<div class="diff-row ${cls}"><div class="diff-label" title="${esc(item.label||item.id)}"><span class="item-no sm">${n+1}</span><span>${esc(item.label||item.id)}</span></div>
<div class="diff-track">${d?`<span class="diff-bar" style="${d>0?"left:50%":"right:50%"};width:${w}%"></span>`:""}<span class="diff-mid"></span></div>
<div class="diff-value">${d!=null?signed(d,2):unrated?"未评":"—"}</div></div>`;}).join("");}
function formulaHtml(wp,result){const sch=result.school||{},enh=result.enhanced||{};
if(wp.mode==="school_context"){const changed=(result.comparison?.items||[]).filter(i=>i.total_delta);
const terms=changed.map(i=>{const w=wp.items.find(x=>x.id===i.id)?.base_weight||0;return `${fmtNum(w*100,0)}% × (${fmtNum(i.enhanced_score,1)} − ${fmtNum(i.school_score,1)})`;});
return `<div class="formula-block"><div class="formula-main"><span>最终分</span><i>=</i><span>学校基础分</span><i>+</i><span>Σ 学校权重 × 已复核单项分差</span></div>
<p class="formula-example">${sch.score_10!=null&&enh.score_10!=null?`本次计算：${fmtNum(sch.score_10,2)} ${terms.length?"+ "+terms.join(" + "):"+ 0（没有已复核的修正）"} = <b>${fmtNum(enh.score_10,2)}</b>`:"评分完整后显示本次计算过程。"}</p>
<p class="policy-note">${esc(wp.formula)}</p></div>`;}
const ex=wp.items.find(i=>Math.abs((i.multiplier||1)-1)>1e-9)||wp.items[0];
return `<div class="formula-block"><div class="formula-main"><span>最终权重</span><i>=</i><span class="frac"><u>基础权重 × (1 + 学科命中×10% + 命中领域数÷所选领域数×10%)</u>全部项目调整后权重之和</span></div>
<div class="formula-main" style="margin-top:10px"><span>增强得分</span><i>=</i><span>Σ 最终权重 × 单项增强分</span></div>
<p class="formula-example">${ex?`示例「${esc(ex.label)}」：基础权重 ${fmtNum((ex.base_weight||0)*100,2)}% × 调整倍数 ${fmtNum(ex.multiplier,3)} → 归一化后 <b>${ex.final_weight==null?"—":fmtNum(ex.final_weight*100,2)+"%"}</b>`:""}${enh.score_10!=null?`<br>本次增强得分：<b>${fmtNum(enh.score_10,2)}</b> / 10`:""}</p>
<p class="policy-note">${esc(wp.formula)}</p></div>`;}
function sensitivityHtml(sens,result){if(!sens?.available)return"<p>完整填写增强分后显示权重敏感性检查。</p>";
const lo=fmtNum(sens.low,2),hi=fmtNum(sens.high,2);
const verdict=sens.crosses_reference?["warn","跨越 6 分参考线，结论还不稳定，建议先复核证据，不直接给出达标结论"]:sens.low>6?["ok","均高于 6 分参考线"]:sens.low>=6?["ok","均达到 6 分参考线"]:["low","均低于 6 分参考线"];
const cats=Object.fromEntries((result.categories||[]).map(c=>[c.id,c.label]));
return `<h3>权重敏感性检查</h3><p class="sens-sentence ${verdict[0]}">把各类权重小幅上调或下调后，增强得分范围在 <strong>${lo}~${hi}</strong> 分，${verdict[1]}。</p>
<details class="pro-note"><summary>专业说明</summary><p class="policy-note">${esc(sens.note)}</p>${(sens.scenarios||[]).length?`<table><thead><tr><th>调整的类别</th><th>权重倍数</th><th>增强得分</th></tr></thead><tbody>${sens.scenarios.map(s=>`<tr><td>${esc(cats[s.category_id]||s.category_id)}</td><td>×${s.factor}</td><td>${fmtNum(s.score,2)}</td></tr>`).join("")}</tbody></table>`:""}</details>`;}
function renderResult(result,rec){
const cr=result?.context_review;const ce=byId("contextChanges");ce.hidden=!cr?.enabled;if(cr?.enabled){ce.innerHTML=`<h3>情境修正记录</h3><p>${cr.pending_count?`${cr.pending_count}项建议待复核，尚未计入总分。`:"无待复核修正。"}</p>${cr.changes.map(c=>`<article><h4>${esc(c.label)} · ${c.applied?"已复核":"建议待复核"}</h4><p>学校分 ${fmtNum(c.school_score,2)} → 建议分 ${fmtNum(c.proposed_score,2)}；总分影响 ${signed(c.proposed_delta,2)}</p><p>证据：${esc(c.evidence)}</p><p>应对与后续表现：${esc(c.reason)}</p><p>下一课：${esc(c.suggestion)}</p></article>`).join("")}<p>${esc(cr.note)}</p>`;}
if(!result){byId("resultCard").hidden=true;return;}
byId("resultCard").hidden=false;
byId("formCard").hidden=true;
byId("resultSaveBtn").hidden=!!rec;
renderedRecord=rec;byId("exportJsonBtn").disabled=!rec;
byId("editRecordBtn").textContent=rec?"查看评分与证据":"返回修改";
const sch=result.school||{};const enh=result.enhanced||{};const cmp=result.comparison||{};
const statusBadge=`<span class="status-badge${result.status==="reviewed"?" success":result.status==="provisional"?" warning":" "}">${statusLabel(result.status)}</span>`;
byId("resultStatus").innerHTML=statusBadge+(rec?"":' <span class="status-badge">未保存预览</span>');
byId("kSchool").textContent=fmtNum(sch.score_10,2);byId("kEnhanced").textContent=fmtNum(enh.score_10,2);
const kd=byId("kDelta");kd.textContent=cmp.available?signed(cmp.total_delta,2):"不可用";kd.className=cmp.available?deltaClass(cmp.total_delta):"";
const selectedTemplate=(rec?.rule_snapshot?.templates||workspace?.templates||[]).find(t=>t.id===result.template_id);byId("resultMeta").innerHTML=`${esc(selectedTemplate?.label||"课堂评价")} · ${rec?"已保存版本 "+rec.version:"未保存预览"} · ${statusBadge}<br>规则版本：${esc(result.rule_version||"—")}`;
let data=rec;if(!data){try{data=buildPayload(activeRecord?.record_id,activeRecord?.version);}catch(_){data={};}}
byId("resultContext").textContent=`${data.course_name||""} · ${data.lesson_date||""}\n${sch.source_label||""}${data.school_rater?" · "+data.school_rater:""}\n${data.task_id?"课堂级来源任务："+data.task_id+" · "+(data.source_provenance?.status||"预览")+" · SHA-256："+(data.source_sha256||"保存时核验"):"未关联视频任务"}`;byId("resultGoal").textContent=data.goal_context||"";renderCourseTaskBasis(result,rec);
const subject=result.subject_context||(rec?.rule_snapshot?.subjects||workspace?.subjects||[]).find(s=>s.id===data.subject_id);const focusNode=byId("resultFocus");if(subject){focusNode.hidden=false;focusNode.textContent=`课程关注：${(subject.focus||[]).join("、")}。${subject.note||""}`;}else{focusNode.hidden=true;}
byId("sRaw").textContent=sch.raw_score!=null?`${fmtNum(sch.raw_score,sch.raw_max===5?2:1)}`:"—";
byId("sRawMax").textContent=sch.raw_max!=null?`满分${sch.raw_max}`:"";
byId("sScore10").textContent=fmtNum(sch.score_10,2);
byId("sScore70").textContent=fmtNum(sch.teaching_score_70,1);
byId("sReferenceStatus").textContent=sch.reference_status||"仅作项目参考，不替代学校判定";
const scov=sch.coverage;
const scovEl=byId("sCoverage");
if(scov&&scov.scored<scov.total){scovEl.hidden=false;scovEl.textContent=`学校评分仅${scov.scored}/${scov.total}项，其余显示为「未评」，暂不形成完整总评。缺项不填零。`;}else{scovEl.hidden=true;}
byId("eScore10").textContent=fmtNum(enh.score_10,2);
const epEl=byId("ePassBox");
if(enh.passed===true){epEl.className="score-box pass";}else if(enh.passed===false){epEl.className="score-box fail";}else{epEl.className="score-box na";}
byId("ePass").textContent=enh.passed===true?"达到参考线":enh.passed===false?"未达参考线":"待定";
byId("ePassSub").textContent=enh.status_label||"";
const ecov=enh.coverage;byId("eCoverage").textContent=ecov?`${ecov.scored}/${ecov.total}`:"—";
setDelta("cEvidDelta",cmp.evidence_delta,cmp.available&&cmp.evidence_delta!=null);
setDelta("cWeightDelta",cmp.weight_delta,cmp.available&&cmp.weight_delta!=null);
setDelta("cTotalDelta",cmp.total_delta,cmp.available&&cmp.total_delta!=null);
const ci=cmp.items||[];
byId("enhancedDifference").textContent=cmp.available?`相对学校分变化 ${signed(cmp.total_delta,2)} 分，其中证据修正 ${signed(cmp.evidence_delta,2)} 分，权重调整 ${signed(cmp.weight_delta,2)} 分。分差不表示系统比教师更准确。`:"评分尚不完整，暂不进行两轨差值解释。";
const changed=ci.filter(i=>i.reason||i.suggestion);byId("enhancedReasons").innerHTML=changed.length?changed.map(i=>`<article><h4>${esc(i.label)} · ${i.school_score!=null?fmtNum(i.school_score,1):"未评"} → ${i.enhanced_score!=null?fmtNum(i.enhanced_score,1):"未评"}</h4><p><strong>依据：</strong>${esc(i.evidence||"尚未补充")}</p><p><strong>解释：</strong>${esc(i.reason||"条目分未调整，仅按公开权重汇总。")}</p><p><strong>下一步：</strong>${esc(i.suggestion||"暂无补充建议")}</p></article>`).join(""):"<p class=help>暂无逐项补充理由或建议。</p>";
renderBarChart("sBarChart",result.categories||[],"school_score","unused");
renderBarChart("eBarChart",result.categories||[],"school_score","enhanced_score");
byId("categoryWeights").innerHTML=(result.categories||[]).map(c=>`<p><b>${esc(c.label)}</b> · 学校 ${(c.school_weight*100).toFixed(1)}% → 增强 ${c.enhanced_weight==null?"不适用":(c.enhanced_weight*100).toFixed(1)+"%"}<br>${esc(c.rationale)}</p>`).join("");
const wp=result.weight_policy;byId("policyDetails").innerHTML=wp?`<h3>${wp.mode==="school_context"?"学校基础 + 情境复核":wp.mode==="subject_trial"?"学科与本课目标权重":"通用试行权重"}</h3><p>${esc(wp.rationale)}</p><p class="policy-note">本课重点：${wp.domains.filter(d=>d.selected).map(d=>esc(d.label)).join("、")||"未选领域"}。${esc(wp.note)}</p>${formulaHtml(wp,result)}<details><summary>逐项权重表</summary><table><thead><tr><th>项目</th><th>基础</th><th>调整倍数</th><th>最终</th></tr></thead><tbody>${wp.items.map(i=>`<tr><td>${esc(i.label)}</td><td>${i.base_weight==null?"—":fmtNum(i.base_weight*100,2)+"%"}</td><td>${fmtNum(i.multiplier,3)}</td><td>${i.final_weight==null?"—":fmtNum(i.final_weight*100,2)+"%"}</td></tr>`).join("")}</tbody></table><p class="policy-note">${esc(wp.limitation)} · ${esc(wp.version)}</p></details>`:"<p>此历史记录未使用学科目标权重。</p>";
byId("sensitivityDetails").innerHTML=wp?.mode==="school_context"?"<h3>权重敏感性检查</h3><p class=\"sens-sentence ok\">本方案沿用学校权重，总分差只来自已复核的单项修正，没有权重调整项，因此不需要做权重敏感性检查。</p>":sensitivityHtml(result.sensitivity,result);
renderDiffChart("diffChart",ci);
byId("compareItemsTbody").innerHTML=ci.map((item,n)=>`<tr>
<td><span class="item-no sm">${n+1}</span>${esc(item.label||item.id)}</td>
<td class="num">${scoreOrUnrated(item.school_score,1)}</td>
<td class="num">${scoreOrUnrated(item.enhanced_score,1)}</td>
<td class="num ${deltaClass(item.evidence_delta)}">${item.evidence_delta!=null?signed(item.evidence_delta,2):"—"}</td>
<td class="num ${deltaClass(item.weight_delta)}">${item.weight_delta!=null?signed(item.weight_delta,2):"—"}</td>
<td class="num ${deltaClass(item.total_delta)}"><strong>${item.total_delta!=null?signed(item.total_delta,2):"—"}</strong></td>
<td>${esc(item.reason||"")}</td>
<td style="white-space:pre-wrap">${esc(item.evidence||"")}</td>
<td>${esc(item.suggestion||"")}</td>
</tr>`).join("");
const refs=rec?.rule_snapshot?.references||workspace?.references||[];
byId("refList").innerHTML=refs.length?refs.map(r=>`<article class="ref-card">
<div class="ref-title">${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title||r.id)}</a>`:esc(r.title||r.id)}</div>
${r.support?`<p class="ref-line"><span class="tag tag-support">支持</span><span>${esc(r.support)}</span></p>`:""}
${r.limitation?`<p class="ref-line"><span class="tag tag-limit">局限</span><span>${esc(r.limitation)}</span></p>`:""}
</article>`).join(""):'<p style="color:#8a9bb0;font-size:13px">暂无文献数据。</p>';
renderBasisPanel(result,rec);
renderCourseResult(result,rec);
updateSummary();}
function basisButton(rec,focus,label){if(!rec||!rec.record_id)return `<button type="button" class="sb-btn" disabled title="保存评价后可查看依据">${esc(label||"查看依据")}</button>`;return `<button type="button" class="sb-btn" data-sb-kind="evaluation" data-sb-record="${esc(rec.record_id)}"${focus?` data-sb-focus="${esc(focus)}"`:""}>${esc(label||"查看依据")}</button>`;}
function renderBasisPanel(result,rec){
const basis=rec&&rec.score_basis;const kb=byId("kEnhancedBasis");if(kb)kb.innerHTML=basisButton(rec,"",rec?"查看依据":"保存后查看依据");
const ov=byId("basisOverview");const tb=byId("basisItemsTbody");
if(!basis){ov.innerHTML=rec?'<p class="help">该评价保存于评分依据功能上线前，点击「查看依据」会按当前记录补算依据。</p>':'<p class="help">这是未保存的预览。保存评价后，每个条目都会保存一份评分依据快照，可在此查看。</p>';
const ci=(result.comparison||{}).items||[];tb.innerHTML=ci.map((it,n)=>`<tr><td><span class="item-no sm">${n+1}</span>${esc(it.label||it.id)}</td><td class="num">${scoreOrUnrated(it.school_score,1)}</td><td class="num">${it.enhanced_score==null?'<span class="unscored">证据不足，未计分</span>':fmtNum(it.enhanced_score,1)}</td><td>—</td><td>—</td><td>${it.enhanced_score==null?"证据不足，未计分":"—"}</td><td>${basisButton(rec,it.id,"依据")}</td></tr>`).join("");}
else{const o=basis.overall||{};
ov.innerHTML=`<div class="score-grid"><div class="score-box"><div class="score-box-label">系统增强分</div><div class="score-box-value" id="basisSystemScore">${o.system_score==null?"未生成":fmtNum(o.system_score,2)}</div><div class="score-box-sub">${esc(basis.status_label)}</div></div><div class="score-box"><div class="score-box-label">公式代入结果</div><div class="score-box-value">${o.formula_value==null?"—":fmtNum(o.formula_value,2)}</div><div class="score-box-sub">${o.matches_page?"与页面一致":"—"}</div></div><div class="score-box"><div class="score-box-label">证据不足条目</div><div class="score-box-value" id="basisInsufficientCount">${(basis.insufficient_items||[]).length}</div><div class="score-box-sub">${esc((basis.insufficient_items||[]).join("、")||"无")}</div></div></div>${(basis.reasons||[]).length?`<p class="help">${basis.reasons.map(esc).join("；")}</p>`:""}<p class="help">${esc(basis.formula?.rule||"")}${basis.formula?.expression?`：${esc(basis.formula.expression)} = ${esc(basis.formula.result)}`:""}</p>`;
tb.innerHTML=(basis.items||[]).map((it,n)=>{const shown=it.status==="scored"||it.status==="pending_review";return `<tr data-basis-item="${esc(it.id)}"><td><span class="item-no sm">${n+1}</span>${esc(it.label)}</td><td class="num">${scoreOrUnrated(it.school_score,1)}${it.school_grade?` <small>${esc(it.school_grade)}</small>`:""}</td><td class="num">${shown?fmtNum(it.enhanced_score,1):'<span class="unscored">—</span>'}</td><td>${shown?`${esc(it.anchor_level)} 档 · ${esc(it.anchor_label)}`:"—"}</td><td>${(it.data_sources||[]).map(esc).join("、")||"无"}</td><td>${shown?esc(it.status_label):`<strong class="basis-insufficient">${esc(it.status_label)}</strong><br><small>${esc(it.reason)}</small>`}</td><td>${basisButton(rec,it.id,"依据")}</td></tr>`;}).join("");}
renderEvalRubricDetail();}
function renderEvalRubricDetail(){const box=byId("evalRubricDetail");if(!box||box.dataset.ready)return;const d=EVAL_RUBRIC_DETAIL;box.dataset.ready="1";
box.innerHTML=`<h3 id="evalRubricTitle">分档锚点细则 <span class="rubric-version" id="evalRubricVersion">规则 ${esc(d.rule_version)} · 细则 ${esc(d.detail_version)}</span></h3><p class="policy-note">${esc(d.anchor_rule)} 学校单项：${d.school_grades.map(g=>`${esc(g.grade)} ${g.low}—${g.high}`).join(" / ")}。不计分情形：${d.not_scored.map(esc).join("；")}。</p><p class="policy-note">通用锚点：${d.general_anchors.map(a=>`${a.level} 分「${esc(a.label)}」`).join("、")}。</p>${d.items.map((it,n)=>`<details class="rubric-dim" data-rubric-item="${esc(it.id)}"><summary><b>${n+1}. ${esc(it.label)}</b> <small>${esc(it.category_label)} · 增强权重 ${fmtNum(it.enhanced_weight*100,0)}%</small></summary><table class="anchor-table"><tbody>${it.anchors.map(a=>`<tr${a.level>=6?' class="pass"':""}><th scope="row">${a.level} 分</th><td>${esc(a.text)}</td></tr>`).join("")}</tbody></table><p class="rd-line"><b>核对要点：</b>${esc(it.check_point)}</p><p class="rd-line"><b>证据要求：</b>${esc(it.evidence)}</p></details>`).join("")}`;}
function resetForm(){
formGuard.clean();
activeRecord=null;previewResult=null;byId("resultCard").hidden=true;
sourceLabel(null);
byId("formCard").hidden=false;
renderedRecord=null;byId("fReviewed").checked=false;byId("fLessonId").disabled=false;byId("fLessonDate").disabled=false;
byId("fLessonId").value="";byId("fLessonDate").value="";byId("fCourseName").value="";
byId("fSubject").value="";byId("fSubject").disabled=false;
byId("fTemplate").value="";byId("fTemplate").disabled=false;
byId("fWeightPolicy").value="school_context";byId("fWeightPolicy").disabled=false;document.querySelectorAll("#domainChoices input").forEach(el=>{el.checked=false;el.disabled=false;});updatePolicy();
byId("fGoalContext").value="";byId("fGoalContext").disabled=false;
byId("fSchoolSource").value="teacher_recorded";byId("fSchoolRater").value="";
byId("lockNotice").hidden=true;byId("focusHint").hidden=true;
byId("formTitle").textContent="新建评价记录";
byId("itemsTbody").innerHTML='<p class="empty-hint">请先在第 2 步选择评价模板</p>';
byId("qingpuNotice").hidden=true;clearFmsg();clearFieldErrors();onSchoolSourceChange();
if(taskSource){byId("fLessonId").value=taskSource.course_id||taskSource.task_id;byId("fCourseName").value=taskSource.course_name||"";}
evalCourseTask=null;renderCourseTaskCard();loadCourseTaskFor(byId("fLessonId").value.trim(),{fill:true});
if(taskSource&&courseData&&courseData.task_id===taskSource.task_id&&(workspace?.templates||[]).some(t=>t.id===COURSE_TEMPLATE)){byId("fTemplate").value=COURSE_TEMPLATE;byId("fWeightPolicy").value="common";onTemplateChange();if(!byId("fCourseName").value)byId("fCourseName").value=courseData.course_name||"";}
renderCourseBanner();
maxStep=1;showStep(1,true);}
function renderRecordList(records){
const el=byId("recordList");
if(!records.length){el.innerHTML='<p style="color:#8a9bb0;font-size:13px">暂无评价记录。点「新建」开始第一条。</p>';return;}
el.innerHTML=records.map(r=>`<div class="record-item${activeRecord?.record_id===r.record_id?" active":""}" data-id="${esc(r.record_id)}" tabindex="0" role="button" aria-pressed="${activeRecord?.record_id===r.record_id}">
<div class="record-item-title">${esc(r.course_name||r.lesson_id||r.record_id)}${r.status==="withdrawn"?'<span class="withdrawn-badge">已撤销</span>':""}</div>
<div class="record-item-meta">${esc(r.lesson_date||"")} · ${statusLabel(r.result?.status||r.status)}${r.course_evaluation?' · <span class="status-badge success">课程评价</span>':""}${r.course_evaluation_stale?.stale?' <span class="status-badge warning">依据已变化</span>':""}</div>
</div>`).join("");
el.querySelectorAll(".record-item").forEach(el=>{
el.addEventListener("click",()=>selectRecord(el.dataset.id));
el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectRecord(el.dataset.id);}});});}
function selectRecord(id){
if(busy)return;
const rec=(workspace?.records||[]).find(r=>r.record_id===id);
if(!rec)return;
loadRecordIntoForm(rec);
renderRecordList(workspace.records);}
async function loadWorkspace(){
try{
const d=await api(API+"/evaluations");
workspace=d.workspace||{records:[],templates:[],subjects:[],references:[]};
byId("domainChoices").innerHTML=(workspace.weight_policy?.domains||[]).map(d=>`<label><input type="checkbox" value="${esc(d.id)}">${esc(d.label)}</label>`).join("");byId("anchorList").innerHTML=(workspace.weight_policy?.anchors||[]).map(a=>`<p><strong>${a.score}分 · ${esc(a.label)}</strong><br>${esc(a.detail)}</p>`).join("");
if(workspace.needs_school_context){msg("请先到学校信息页填写所属学校，再保存课堂评价。");}
populateSubjects();populateTemplates();
renderRecordList(workspace.records||[]);
byId("fSchoolSource").addEventListener("change",onSchoolSourceChange);
onSchoolSourceChange();
if(sourceError)throw new Error(sourceError);
if(requestedTask){const source=await api(API+"/identity/workspace?task_id="+encodeURIComponent(requestedTask));
if(!source.workspace?.media_available||!source.workspace.frame_revision)throw new Error("任务证据未就绪，暂不能关联评价。");
taskSource={task_id:requestedTask,frame_revision:source.workspace.frame_revision,course_id:source.workspace.course_id||"",course_name:source.workspace.course_name||""};
workspace.records=workspace.records.filter(r=>r.task_id===requestedTask);renderRecordList(workspace.records);sourceLabel(null);
byId("fLessonId").value=source.workspace.course_id||requestedTask;byId("fCourseName").value=source.workspace.course_name||"";
await loadCourseData(requestedTask);}
if(workspace.records?.length)selectRecord(workspace.records[0].record_id);
else if(requestedTask)resetForm();
else loadCourseTaskFor(byId("fLessonId").value.trim(),{fill:true});
}catch(e){sourceError=e.message;sourceLabel(null);byId("previewBtn").disabled=true;byId("saveBtn").disabled=true;msg("工作台数据加载失败："+apiErrorText(e));}}
function apiErrorText(e){if(window.RxUI?.describeError&&(e.status||e instanceof TypeError||e.name==="TimeoutError"))return RxUI.fromError(e).full;return (e.status===400?"提交数据有误：":e.status===403?"权限不足：":e.status===409?"版本冲突，请重新加载记录：":"")+e.message;}
byId("previewBtn").addEventListener("click",async()=>{
if(busy)return;clearFmsg();
let payload;try{payload=collectPayload(activeRecord?.record_id,activeRecord?.version);}catch(e){fmsg(e.message);focusAfter=e.focusId||"";focusInvalid();return;}
setBusy(true);
try{
const d=await api(API+"/evaluations/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
previewResult=d.result;renderResult(d.result,null);
msg("预览已生成（尚未保存）。可直接点「保存记录」；如需改分点「返回修改」。","info");
}catch(e){invalidate();goalNameError(e);courseSaveError(e);fmsg(apiErrorText(e));focusAfter=e.focusId||"";}finally{setBusy(false);focusInvalid();}});
byId("saveBtn").addEventListener("click",async()=>{
if(busy)return;clearFmsg();
let payload;try{payload=collectPayload(activeRecord?.record_id,activeRecord?.version??0);}catch(e){fmsg(e.message);focusAfter=e.focusId||"";focusInvalid();return;}
setBusy(true);
try{
const d=await api(API+"/evaluations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
const saved=d.record;
if(!workspace.records.find(r=>r.record_id===saved.record_id)){workspace.records.unshift(saved);}
else{workspace.records=workspace.records.map(r=>r.record_id===saved.record_id?saved:r);}
setBusy(false);loadRecordIntoForm(saved);renderRecordList(workspace.records);formGuard.clean();
msg(saved.version>1?"修改已保存。":"记录已保存，课程口径已锁定。","success");if(saved.course_evaluation&&saved.task_id)loadCourseData(saved.task_id);okToast(saved.version>1?"课堂评价修改已保存":"课堂评价已保存");
}catch(e){goalNameError(e);courseSaveError(e);fmsg(apiErrorText(e));focusAfter=e.focusId||"";}finally{if(busy)setBusy(false);focusInvalid();}});
byId("withdrawBtn").addEventListener("click",async()=>{
if(!activeRecord||busy)return;
const target=activeRecord;
const reason=await askReason({title:"撤销这条课堂评价？",message:"将撤销课节「"+(target.course_name||target.lesson_id||"未命名")+"」的课堂评价记录。",
consequences:["撤销后该记录不再出现在评价列表和课堂报告中。","撤销原因会写入审计日志，此操作不能在页面上恢复。"],
confirmLabel:"确认撤销",cancelLabel:"取消",input:{label:"撤销原因",required:true,maxLength:500,example:"例如：评价对象选错了课节"}});
if(!reason||activeRecord!==target)return;
setBusy(true);
try{
const d=await api(API+"/evaluations/withdraw",{method:"POST",headers:{"Content-Type":"application/json"},
body:JSON.stringify({record_id:target.record_id,expected_version:target.version,reason})});
const updated=d.record;
workspace.records=workspace.records.filter(r=>r.record_id!==updated.record_id);
setBusy(false);resetForm();renderRecordList(workspace.records);
fmsg("记录已撤销。","info");okToast("课堂评价已撤销");
}catch(e){fmsg(apiErrorText(e));}finally{if(busy)setBusy(false);}});
byId("newBtn").addEventListener("click",()=>{resetForm();renderRecordList(workspace?.records||[]);msg("");byId("fLessonId").focus();});
byId("resultSaveBtn").addEventListener("click",()=>{if(!busy)byId("saveBtn").click();});
byId("editRecordBtn").addEventListener("click",()=>{const step=renderedRecord?3:4;byId("formCard").hidden=false;msg("");showStep(step,true);byId("formCard").scrollIntoView({block:"start"});byId("stepTitle"+step).focus({preventScroll:true});dbg("evaluation_edit",renderedRecord?"opened":"back_from_preview",{step});});
byId("stepPrev").addEventListener("click",()=>tryGo(currentStep-1));
byId("stepNext").addEventListener("click",()=>tryGo(currentStep+1));
byId("stepBar").addEventListener("click",e=>{const b=e.target.closest("[data-step]");if(b)tryGo(Number(b.dataset.step));});
byId("reviewSummary").addEventListener("click",e=>{const b=e.target.closest("[data-goto]");if(b){clearFmsg();showStep(Number(b.dataset.goto));}});
byId("itemsTbody").addEventListener("click",e=>{const btn=e.target.closest("[data-anchor]");if(btn){const pop=byId("anchorPop_"+btn.dataset.anchor);const open=pop.hidden;pop.hidden=!open;btn.setAttribute("aria-expanded",String(open));return;}
const close=e.target.closest("[data-close]");if(close){const id=close.dataset.close;byId("anchorPop_"+id).hidden=true;const b=document.querySelector(`[data-anchor="${id}"]`);b?.setAttribute("aria-expanded","false");b?.focus();}});
document.addEventListener("keydown",e=>{if(e.key!=="Escape")return;const pop=e.target.closest?.(".anchor-pop")||document.querySelector(".anchor-pop:not([hidden])");if(!pop)return;pop.hidden=true;const id=pop.id.replace("anchorPop_","");const b=document.querySelector(`[data-anchor="${id}"]`);b?.setAttribute("aria-expanded","false");b?.focus();});
byId("exportJsonBtn").addEventListener("click",()=>{
if(!renderedRecord)return;
const blob=new Blob([JSON.stringify(renderedRecord,null,2)],{type:"application/json"});
const url=URL.createObjectURL(blob);const a=document.createElement("a");
a.href=url;a.download=`eval_${renderedRecord.record_id||"record"}.json`;a.click();URL.revokeObjectURL(url);});
window.addEventListener("beforeprint",()=>document.querySelectorAll("#resultCard details").forEach(d=>d.open=true));
document.querySelectorAll(".tab-btn").forEach(btn=>{
btn.addEventListener("click",()=>{
document.querySelectorAll(".tab-btn").forEach(b=>{b.setAttribute("aria-selected","false");});
btn.setAttribute("aria-selected","true");
const panel=btn.getAttribute("aria-controls");
["panelSchool","panelEnhanced","panelCompare","panelBasis","panelRefs"].forEach(id=>{
const el=byId(id);if(el)el.hidden=id!==panel;});});});
document.querySelector(".tab-bar").addEventListener("keydown",e=>{const tabs=[...document.querySelectorAll(".tab-btn")];const index=tabs.indexOf(document.activeElement);if(index<0||!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();const next=e.key==="Home"?0:e.key==="End"?tabs.length-1:(index+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;tabs[next].click();tabs[next].focus();});
byId("logoutBtn").addEventListener("click",async()=>{
try{await api(API+"/auth/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});}finally{window.location.assign("/demo2/login");}});
byId("accountName").textContent=SERVER_ACCOUNT.login_alias||SERVER_ACCOUNT.username||"—";
byId("fWeightPolicy").addEventListener("change",updatePolicy);byId("domainChoices").addEventListener("change",updateWeightHints);byId("fSubject").addEventListener("change",updateWeightHints);
function changedInput(e){const t=e.target;if(t.getAttribute?.("aria-invalid")==="true"&&String(t.value||"").trim())fieldError(t,"");if(t.id!=="fReviewed")byId("fReviewed").checked=false;
if(t.tagName==="TEXTAREA")autoGrow(t);if(t.closest?.("#itemsTbody")&&(t.tagName==="INPUT"||t.tagName==="SELECT"))updateLive(t);
invalidate();updateSummary();}
byId("formCard").addEventListener("input",changedInput);byId("formCard").addEventListener("change",changedInput);
window.addEventListener("resize",()=>{if(currentStep===3||currentStep===2)growAll();});
const DIMENSION_LABELS={goals:"目标适配与分层要求",content:"内容设计与教学组织",process:"过程支持与目标达成",teacher:"教师表达与响应调节",outcomes:"学习效果"};
function courseTaskGoalText(task){const lines=(task.goals||[]).map(g=>`${g.goal_code} ${g.description}${g.pass_criteria?`（通过标准：${g.pass_criteria}）`:""}`);
const text=`本课课程任务目标（课程任务版本 ${task.version}）：\n`+lines.join("\n");return text.length>2000?text.slice(0,1999)+"…":text;}
function courseTaskPayload(){if(activeRecord)return activeRecord.course_task_doc_id?{course_task_doc_id:activeRecord.course_task_doc_id}:{};
return evalCourseTask&&evalCourseTask.course_task_doc_id&&evalCourseTask.course_id===byId("fLessonId").value.trim()?{course_task_doc_id:evalCourseTask.course_task_doc_id}:{};}
function courseTaskFromRecord(rec){evalCourseTask=rec.course_task_doc_id?{course_task_doc_id:rec.course_task_doc_id,version:rec.course_task_version,course_id:rec.course_id||rec.lesson_id,goals:rec.course_task_goals||[],locked:true}:null;renderCourseTaskCard();}
function applyCourseTaskGoals(force){if(!evalCourseTask||activeRecord)return;const node=byId("fGoalContext");if(node.disabled)return;
const current=node.value.trim();if(force||!current||current===courseTaskAutoText){courseTaskAutoText=courseTaskGoalText(evalCourseTask);node.value=courseTaskAutoText;if(typeof autoGrow==="function")autoGrow(node);fieldError(node,"");}}
async function loadCourseTaskFor(courseId,opts){const request=++courseTaskRequest;
if(activeRecord||!courseId){if(!activeRecord){evalCourseTask=null;renderCourseTaskCard();}return;}
try{const d=await api(API+"/course-tasks?course_id="+encodeURIComponent(courseId));if(request!==courseTaskRequest||activeRecord)return;
evalCourseTask=d.current?{...d.current}:null;renderCourseTaskCard();if(evalCourseTask&&opts?.fill)applyCourseTaskGoals(false);annotateItemsWithGoals();}
catch(_){if(request===courseTaskRequest){evalCourseTask=null;renderCourseTaskCard();}}}
function renderCourseTaskCard(){const card=byId("courseTaskCard");if(!card)return;const task=evalCourseTask;
if(!task){card.hidden=true;card.innerHTML="";return;}
const goals=(task.goals||[]).map(g=>`<li><strong>${esc(g.goal_code)}</strong> ${esc(g.description)}<span class="ct-meta">${g.pass_criteria?"通过标准："+esc(g.pass_criteria)+" · ":""}${g.measurement_conditions?"测量条件："+esc(g.measurement_conditions)+" · ":""}对应维度：${esc(DIMENSION_LABELS[g.rubric_dimension]||"过程支持与目标达成")}</span></li>`).join("");
card.hidden=false;card.innerHTML=`<div class="ct-card-head"><p id="courseTaskCardTitle"><span class="status-badge success">已带入课程任务目标（版本 ${esc(task.version)}）</span> ${(task.goals||[]).length} 个目标${task.locked?" · 已随评价保存":""}</p>${task.locked?"":'<div class="ct-card-actions"><button type="button" class="button quiet" id="courseTaskApply">重新带入本课目标</button><button type="button" class="button quiet" id="courseTaskDetach">不使用课程任务</button></div>'}</div><ol class="course-task-goals">${goals}</ol><p class="field-tip">学校评分沿用学校模板；系统增强评分按以上目标对应的评分条目逐条给出依据，计算口径不变。</p>`;
const apply=byId("courseTaskApply");if(apply)apply.addEventListener("click",()=>{applyCourseTaskGoals(true);invalidate();});
const detach=byId("courseTaskDetach");if(detach)detach.addEventListener("click",()=>{if(byId("fGoalContext").value.trim()===courseTaskAutoText)byId("fGoalContext").value="";evalCourseTask=null;renderCourseTaskCard();annotateItemsWithGoals();invalidate();});}
function annotateItemsWithGoals(){document.querySelectorAll("#itemsTbody .ct-goal-chip").forEach(el=>el.remove());const task=evalCourseTask,tmpl=currentTemplate();if(!task||!tmpl)return;
const cats=new Set((tmpl.items||[]).map(i=>i.category_id));
(tmpl.items||[]).forEach(item=>{const codes=(task.goals||[]).filter(g=>{const d=cats.has(g.rubric_dimension)?g.rubric_dimension:"process";return d===item.category_id;}).map(g=>g.goal_code);
if(!codes.length)return;const meta=document.querySelector(`[data-item="${item.id}"] .item-card-meta`);if(!meta)return;
const chip=document.createElement("span");chip.className="ct-goal-chip";chip.textContent="对应课程目标 "+codes.join("、");meta.appendChild(chip);});}
function renderCourseTaskBasis(result,rec){const box=byId("resultCourseTask");if(!box)return;const basis=(rec&&rec.course_task_goal_basis)||result.course_task_goal_basis||[];
if(!basis.length){box.hidden=true;byId("resultCourseTaskList").innerHTML="";return;}
box.hidden=false;const refs=(rec&&rec.measurement_refs)||result.measurement_refs||[];byId("resultCourseTaskList").innerHTML=basis.map(b=>{const linked=refs.filter(r=>r.goal_id===b.goal_code);const chips=linked.map(r=>`<a class="ct-goal-chip" href="/demo2/measurement?student_id=${encodeURIComponent(r.student_id)}&record_id=${encodeURIComponent(r.record_id)}#tab-report" title="打开该测量记录的单次报告">测量 ${esc(String(r.record_id).slice(0,8))} · ${r.reviewed?"已复核":"待复核"}${r.source_type==="video"?" · 视频":""}</a>`).join(" ");return `<li><strong>${esc(b.goal_code)}</strong> · ${esc(b.dimension_label||"")}<p>${esc(b.basis_text||"")}</p>${chips?`<p class="ct-measure-refs">系统轨引用：${chips}</p>`:""}</li>`;}).join("");}
function suggestionFor(id){return (courseData?.suggestions?.items||[]).find(i=>i.id===id)||null;}
function courseMode(){const tid=(activeRecord||taskSource)?.task_id;return !!(courseData&&tid&&courseData.task_id===tid&&byId("fTemplate").value===COURSE_TEMPLATE);}
async function loadCourseData(taskId){const req=++courseRequest;
try{const d=await api(API+"/evaluations/course?task_id="+encodeURIComponent(taskId));if(req!==courseRequest)return null;courseData=d.course;courseError="";
const fresh=(d.course.evaluations||[]).find(r=>r.record_id===activeRecord?.record_id);if(fresh&&activeRecord){activeRecord.course_evaluation_stale=fresh.course_evaluation_stale;}
renderCourseBanner();renderSuggestionBoxes(null);updateSummary();if(renderedRecord)renderCourseResult(renderedRecord.result,renderedRecord);return courseData;}
catch(e){if(req===courseRequest){courseData=null;courseError=apiErrorText(e);renderCourseBanner();renderSuggestionBoxes(null);}return null;}}
function renderCourseBanner(){const box=byId("courseBanner");if(!box)return;const tid=(activeRecord||taskSource)?.task_id;
if(!tid){box.hidden=true;box.innerHTML="";return;}
if(courseError){box.hidden=false;box.innerHTML=`<strong>系统建议分暂不可用</strong><span class="cb-counts">${esc(courseError)}</span><button type="button" class="button quiet" data-course-refresh>重新读取</button>`;return;}
if(!courseData||courseData.task_id!==tid){box.hidden=true;return;}
const sg=courseData.suggestions;const tmplOk=byId("fTemplate").value===COURSE_TEMPLATE;
box.hidden=false;box.innerHTML=`<strong>课程评价 · 系统建议分</strong><span class="cb-counts" id="courseSuggestCounts">${sg.suggested_count} / ${sg.items.length} 个条目按本课数据给出建议分，${sg.insufficient_count} 个条目证据不足，待教师评分</span>${tmplOk?"":'<span class="cb-counts">（系统建议分仅用于「课堂教学基本评价指标 · 100分原表」）</span>'}<button type="button" class="button quiet" data-course-refresh>刷新系统建议分</button>`;}
function suggestionEvidenceText(sg){const parts=(sg.evidence_refs||[]).slice(0,4).map(r=>r.text).filter(Boolean);const src=(sg.data_sources||[]).filter(x=>x.available).map(x=>x.label).join("、");
const text=`系统依据（${src}）：${parts.join("；")}`;return text.length>600?text.slice(0,599)+"…":text;}
function renderSuggestionBoxes(existingItems){document.querySelectorAll("#itemsTbody .sugg-box").forEach(el=>{el.remove();});
if(!courseMode())return;const saved=activeRecord?.course_evaluation;
(courseData.suggestions.items||[]).forEach(sg=>{const card=document.querySelector(`#itemsTbody [data-item="${sg.id}"]`);if(!card)return;
const anchor=card.querySelector(".item-scores");const box=document.createElement("div");box.dataset.suggFor=sg.id;
const chips=(sg.data_sources||[]).filter(x=>x.available).map(x=>`<span class="sugg-chip">${esc(x.label)}</span>`).join("");
if(sg.suggested_score!=null){box.className="sugg-box";
const prior=(saved?.items||[]).find(i=>i.id===sg.id)?.modify_reason||"";
box.innerHTML=`<div class="sugg-head"><span>系统建议分</span><span class="sugg-score" id="suggScore_${sg.id}">${fmtNum(sg.suggested_score,1)}</span><span class="sugg-state" data-sugg-state="${sg.id}">未填</span>${chips}</div><p class="sugg-formula">${esc(sg.formula)}</p><div class="sugg-actions"><button type="button" class="button quiet" data-sugg-adopt="${sg.id}">采纳建议分</button><button type="button" class="sb-btn" data-sugg-basis="${sg.id}">查看依据</button></div><div class="field sugg-reason" data-sugg-reason-field="${sg.id}" hidden><label for="suggestion_reason_${sg.id}">修改系统建议分的理由 <abbr title="必填">*</abbr></label><textarea id="suggestion_reason_${sg.id}" name="suggestion_reason_${sg.id}" rows="2" maxlength="2000" data-autogrow placeholder="例如：视频未拍到小组活动环节，按现场观察评分">${esc(prior)}</textarea></div>`;}
else{box.className="sugg-box insufficient";box.innerHTML=`<div class="sugg-head"><strong data-sugg-insufficient="${sg.id}">证据不足，待教师评分</strong><button type="button" class="sb-btn" data-sugg-basis="${sg.id}">查看依据</button></div><p class="sugg-formula">${esc(sg.reason)}</p>`;}
if(anchor)anchor.insertAdjacentElement("afterend",box);else card.appendChild(box);});
updateSuggestionStates();}
function updateSuggestionStates(){if(!courseMode())return;(courseData.suggestions.items||[]).forEach(sg=>{if(sg.suggested_score==null)return;
const ef=fieldByName("enhanced_"+sg.id);const state=document.querySelector(`[data-sugg-state="${sg.id}"]`);const rf=document.querySelector(`[data-sugg-reason-field="${sg.id}"]`);if(!ef||!state)return;
const v=ef.value===""?null:Number(ef.value);const modified=v!=null&&v!==sg.suggested_score;
state.textContent=v==null?"未填":modified?"已修改":"已采纳";state.className="sugg-state"+(v==null?"":modified?" modified":" adopted");
if(rf){rf.hidden=!modified;if(!modified){const t=rf.querySelector("textarea");if(t)fieldError(t,"");}}});}
function isAutoEvidence(v){return String(v||"").trim().startsWith("系统依据（");}
function isAutoReason(v){return String(v||"").trim().startsWith("采纳系统建议分：");}
function autoReasonText(sg){return "采纳系统建议分："+(sg.formula.length>300?sg.formula.slice(0,299)+"…":sg.formula);}
function prefillSuggestions(onlyId,refreshAuto){if(!courseMode())return;let refreshed=0;(courseData.suggestions.items||[]).forEach(sg=>{if(sg.suggested_score==null||(onlyId&&sg.id!==onlyId))return;
const ef=fieldByName("enhanced_"+sg.id),vf=fieldByName("evidence_"+sg.id),rf=fieldByName("reason_"+sg.id);if(!ef)return;
if(!refreshAuto&&(onlyId||ef.value===""))ef.value=String(sg.suggested_score);
const adopted=ef.value!==""&&Number(ef.value)===sg.suggested_score;
if(vf&&(!refreshAuto&&!vf.value.trim()||isAutoEvidence(vf.value))){const nv=suggestionEvidenceText(sg);if(vf.value!==nv){vf.value=nv;refreshed++;}}
if(rf&&(!refreshAuto&&!rf.value.trim()||isAutoReason(rf.value)&&adopted)){const nr=autoReasonText(sg);if(rf.value!==nr){rf.value=nr;refreshed++;}}
updateLive(ef);fieldError(ef,"");});growAll();updateSummary();return refreshed;}
function coursePayload(){if(!courseMode())return{};const reasons={};
(courseData.suggestions.items||[]).forEach(sg=>{if(sg.suggested_score==null)return;const ef=fieldByName("enhanced_"+sg.id);const rf=fieldByName("suggestion_reason_"+sg.id);
if(ef&&ef.value!==""&&Number(ef.value)!==sg.suggested_score&&rf&&rf.value.trim())reasons[sg.id]=rf.value.trim();});
return {system_suggestions:{fingerprint:courseData.suggestions.fingerprint.fingerprint,reasons}};}
function courseSaveError(e){if(e?.code==="suggestion_reason_required"&&e.field){showStep(3,true);updateSuggestionStates();const f=fieldByName(e.field);if(f){f.closest("[data-sugg-reason-field]")?.removeAttribute("hidden");fieldError(f,"修改了系统建议分，请填写修改理由");e.focusId=e.field;}}
if(e?.code==="suggestion_basis_changed"){const tid=(activeRecord||taskSource)?.task_id;if(tid)loadCourseData(tid);}}
function openSuggestionBasis(id){const sg=suggestionFor(id);if(!sg)return;if(window.ScoreBasis?.openSuggestion)ScoreBasis.openSuggestion(sg,courseData.suggestions);}
function renderCourseResult(result,rec){const box=byId("courseResult");const notice=byId("courseStaleNotice");if(!box)return;
const snap=(rec&&rec.course_evaluation)||result?.course_evaluation;const stale=rec?.course_evaluation_stale;
if(notice){if(stale?.stale){notice.hidden=false;notice.innerHTML=`<strong id="courseStaleText">依据数据已变化，建议重新核对</strong><span>${(stale.messages||[]).map(esc).join("；")}。原分数保持不变，重新核对后保存才会更新。</span><button type="button" class="button quiet no-print" id="courseRecheckBtn">刷新建议分并重新核对</button>`;}else{notice.hidden=true;notice.innerHTML="";}}
if(!snap||!snap.summary){box.hidden=true;return;}
box.hidden=false;const sm=snap.summary;const cmp=result?.comparison||{};
const grade=g=>g?`等级 ${esc(g)}`:"评分未完整";
byId("courseTotals").innerHTML=`<div><span>学校总分（10 项 × 10 分）</span><b id="courseSchoolRaw">${sm.school_raw_100==null?"—":fmtNum(sm.school_raw_100,1)}</b><small>满分 100 · ${grade(sm.school_grade)}</small></div><div><span>学校平均分</span><b id="courseSchool10">${fmtNum(sm.school_score_10,2)}</b><small>教学评价总分（70%）${fmtNum(sm.teaching_score_70,1)}</small></div><div><span>系统分</span><b id="courseSystem10">${fmtNum(sm.system_score_10,2)}</b><small>${grade(sm.system_grade)}</small></div><div><span>总分差（系统−学校）</span><b id="courseGap" class="${deltaClass(sm.total_gap)}">${sm.total_gap==null?"不可用":signed(sm.total_gap,2)}</b><small>${esc(statusLabel(sm.status))}</small></div>`;
byId("courseCategoryTbody").innerHTML=(sm.categories||[]).map(c=>`<tr data-course-cat="${esc(c.id)}"><th scope="row">${esc(c.label)}</th><td class="num">${c.school_score==null?'<span class="unscored">未评完</span>':fmtNum(c.school_score,2)}</td><td class="num">${c.system_score==null?'<span class="unscored">未评完</span>':fmtNum(c.system_score,2)}</td><td class="num ${deltaClass(c.gap)}">${c.gap==null?"—":signed(c.gap,2)}</td></tr>`).join("");
renderBarChart("courseItemChart",cmp.items||[],"school_score","enhanced_score",["学校","系统"]);
const n=snap.counts||{};byId("courseDecisionLine").textContent=`系统建议分：采纳 ${n.adopted||0} 项 · 修改 ${n.modified||0} 项（均已填写理由）· 证据不足由教师评分 ${n.teacher_scored||0} 项 · 未使用 ${(n.not_used||0)+(n.not_scored||0)} 项。依据计算于 ${String(snap.computed_at||"").replace("T"," ").slice(0,16)}，引用本课测量记录 ${snap.measurement_summary?.record_count||0} 条（只存记录编号与汇总值）。`;}
byId("itemsTbody").addEventListener("click",e=>{const adopt=e.target.closest("[data-sugg-adopt]");if(adopt){const id=adopt.dataset.suggAdopt;prefillSuggestions(id);byId("fReviewed").checked=false;invalidate();updateSummary();dbg("course_eval_adopt","adopted",{item_id:id,step:3});fieldByName("enhanced_"+id)?.focus();return;}
const basis=e.target.closest("[data-sugg-basis]");if(basis)openSuggestionBasis(basis.dataset.suggBasis);});
function syncAutoReason(sg,value){const rf=fieldByName("reason_"+sg.id);if(!rf)return;const cur=rf.value.trim();
const auto=cur===""||cur.indexOf("采纳系统建议分：")===0||cur.indexOf("修改系统建议分：")===0;if(!auto||value==null)return;
if(value===sg.suggested_score){if(cur.indexOf("修改系统建议分：")===0)rf.value="采纳系统建议分："+(sg.formula.length>300?sg.formula.slice(0,299)+"…":sg.formula);}
else if(cur!=="")rf.value=`修改系统建议分：建议 ${fmtNum(sg.suggested_score,1)} 分 → 教师改为 ${fmtNum(value,1)} 分（理由见「修改系统建议分的理由」）`;
growAll();}
byId("itemsTbody").addEventListener("change",e=>{const t=e.target;if(!courseMode()||!t.name||!t.name.startsWith("enhanced_"))return;const id=t.name.slice(9);const sg=suggestionFor(id);
if(sg&&sg.suggested_score!=null)syncAutoReason(sg,t.value===""?null:Number(t.value));
if(sg&&sg.suggested_score!=null&&t.value!==""&&Number(t.value)!==sg.suggested_score&&!modifiedLogged.has(id)){modifiedLogged.add(id);dbg("course_eval_modify","modified",{item_id:id,step:3});}});
document.addEventListener("click",e=>{const t=e.target.closest?.("[data-course-refresh],#courseRecheckBtn");if(!t)return;const tid=(activeRecord||taskSource)?.task_id;if(!tid)return;
loadCourseData(tid).then(d=>{if(!d)return;if(t.id==="courseRecheckBtn"){byId("formCard").hidden=false;showStep(3,true);const autoRefreshed=prefillSuggestions(null,true);if(autoRefreshed)dbg("evaluation_edit","auto_basis_refreshed",{step:3});byId("formCard").scrollIntoView({block:"start"});msg("已按最新数据刷新系统建议分。请逐项核对后重新勾选「已核对」再保存；原分数在保存前不会改变。","info");}else okToast("系统建议分已刷新");});});
byId("fLessonId").addEventListener("change",()=>{if(!activeRecord)loadCourseTaskFor(byId("fLessonId").value.trim(),{fill:true});});
showStep(1,true);
loadWorkspace();
"""


def render_evaluation(account: Any | None = None) -> str:
    account_json = _account_payload(account)
    body = (
        teacher_header("evaluation", account, logout_id="logoutBtn", page="evaluation",
                       extra_actions='<a href="/demo2/safety" class="button quiet no-print">安全核查</a>')
        + '<main id="mainContent" class="page-shell">'
        '<div class="page-heading eval-heading"><div>'
        '<span class="eyebrow">教师工作台</span>'
        '<h1>评课</h1>'
        '<p class="lead">课堂教学双轨评价：按学校「课堂教学基本评价指标」4 个类目、10 个条目给整节课评分，'
        '学校分由教师录入，系统建议分按本课数据预填并附依据。不涉及学生个体能力评分。</p>'
        '<details class="rubric-note" id="evalRubricNote">'
        '<summary>本次评课引用的测量口径（' + RUBRIC_VERSION + '）</summary>'
        '<p>学生测量采用 10 分制，四维权重：' + '、'.join(f'{label} {round(weight*100)}%' for label, weight in zip(DIMENSION_LABELS.values(), DIMENSION_WEIGHTS.values())) + '。'
        '教师完成复核、四个维度均有有效分且观察机会不少于 2 次，才生成综合分；未观察的维度留空，不按 0 分计入。'
        '<a href="/demo2/measurement">查看完整量表与评分标准</a></p>'
        '</details>'
        '</div></div>'
        '<div id="pageMsg" class="page-msg" role="alert" aria-live="polite"></div>'
        '<div class="eval-layout">'
        '<aside class="eval-sidebar" aria-label="评价记录列表">'
        '<div class="sidebar-head"><h2>评价记录</h2>'
        '<button id="newBtn" class="button primary no-print" style="min-height:36px;padding:6px 12px;font-size:13px">新建</button>'
        '</div><div id="recordList" class="record-list"><p class="loading-line">加载中…</p></div>'
        '</aside>'
        '<div class="eval-main">'
        + _FORM_HTML
        + '</div>'
        + _RESULT_HTML
        + '</div>'
        '</main>'
    )
    script = _SCRIPT.replace("__ACCOUNT_JSON__", account_json).replace("__API__", _API)
    detail = json.dumps(evaluation_rubric_detail(), ensure_ascii=False).replace("</", "<\\/")
    return _document(
        title="课程评价",
        body=body,
        page_style=_WORKSPACE_STYLE + _EVAL_STYLE + SCORE_BASIS_CSS,
        script=UI_DRAFT_STORE_JS + SCORE_BASIS_JS + f"const EVAL_RUBRIC_DETAIL={detail};\n" + script,
    )


__all__ = ["render_evaluation"]
