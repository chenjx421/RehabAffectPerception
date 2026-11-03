"""Measurement workspace for Demo2 – teacher-entered classroom observation data.

render_measurement(account) -> standalone HTML page.
school_uploader : full workspace at /demo2/measurement
company_admin   : aggregate summary at /demo2/admin/measurements
No synthetic scores, invented dates, or fabricated confidence values.
"""
from __future__ import annotations

import json
from typing import Any

from .assessment_rubric import rubric_contract
from .demo2_portal import (
    _WORKSPACE_STYLE,
    _account_payload,
    _document,
)
from .demo2_score_basis_ui import SCORE_BASIS_CSS, SCORE_BASIS_JS
from .demo2_ui_kit import UI_DRAFT_STORE_JS, account_role, admin_header, disclosure, empty_state, kpi, teacher_header

_API = "/api/v1/demo2"


_MEAS_STYLE = """
.ws-layout{display:grid;grid-template-columns:264px minmax(0,1fr);min-height:calc(100vh - 64px);background:#f4f7fb;}
.ws-sidebar{border-right:1px solid var(--line);background:#fff;overflow-y:auto;position:sticky;top:64px;max-height:calc(100vh - 64px);}
.ws-sidebar-head{display:grid;gap:10px;padding:14px 14px 12px;border-bottom:1px solid var(--line);}
.ws-sidebar-head h2{font-size:13px;color:var(--muted);font-weight:700;margin:0;letter-spacing:.03em;}
.switch-hint{margin:0;padding:6px 10px;border-radius:6px;background:var(--rx-primary-soft,#eef5ff);color:var(--rx-primary,#1f5fbf);font-size:13px;font-weight:700;}
.switch-hint[hidden]{display:none;}
.measure-switch-host{margin:12px 24px 0;}
.student-search{width:100%;min-height:38px;padding:7px 12px;border:1px solid var(--line-strong);border-radius:6px;font:inherit;font-size:13px;background:#fafcff;}
.student-search:focus{background:#fff;border-color:var(--blue);}
.student-list{padding:6px 0;}
.student-item{display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;border-left:3px solid transparent;font-size:14px;transition:background .12s;}
.student-item:hover{background:var(--blue-soft);}
.student-item.active{background:var(--blue-soft);border-left-color:var(--blue);color:var(--blue-deep);font-weight:600;}
.student-item .rx-avatar{width:32px;height:32px;font-size:14px;}
.s-name{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.s-meta{display:block;color:var(--muted);font-size:11px;font-weight:400;overflow:hidden;text-overflow:ellipsis;}
.s-count{flex:none;min-width:22px;padding:1px 7px;border-radius:11px;background:var(--blue);color:#fff;font-size:11px;font-weight:700;text-align:center;font-variant-numeric:tabular-nums;}
.s-empty{padding:16px;color:var(--muted);font-size:13px;}
.ws-main{min-width:0;display:flex;flex-direction:column;}
.view-tabs{display:flex;gap:0;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:64px;z-index:10;overflow-x:auto;padding:0 12px;}
.view-tab{min-height:46px;padding:10px 16px;border:0;border-bottom:3px solid transparent;background:transparent;color:var(--muted);font-size:14px;font-weight:500;white-space:nowrap;cursor:pointer;transition:color .14s,border-color .14s;}
.view-tab:hover{color:var(--blue);}
.view-tab[aria-selected=true]{color:var(--blue);border-bottom-color:var(--blue);font-weight:700;}
.view-pane{padding:22px 26px 32px;flex:1;max-width:1180px;width:100%;}
.pane-title{font-size:18px;margin:0;color:var(--ink);}
.pane-sub{margin:2px 0 0;color:var(--muted);font-size:13px;}
.pane-muted{color:var(--muted);font-size:14px;}
.ov-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
.ov-head-text{flex:1;min-width:160px;}
.ov-actions{display:flex;gap:10px;flex-wrap:wrap;}
.overview-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px;}
.list-title{display:flex;align-items:baseline;gap:8px;margin:24px 0 10px;font-size:15px;color:var(--ink);}
.list-title span{color:var(--muted);font-size:12px;font-weight:400;}
.rec-list{display:grid;gap:10px;}
.rec-row{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(200px,1fr) auto auto;align-items:center;gap:16px;padding:14px 16px;border:1px solid var(--line);border-radius:8px;background:#fff;font-size:13px;transition:border-color .14s,box-shadow .14s;}
.rec-row:hover{border-color:#a9c4e8;box-shadow:0 4px 14px rgba(23,43,77,.06);}
.rec-row-meta{min-width:0;}
.rec-date{display:inline-block;margin-bottom:4px;padding:1px 8px;border-radius:4px;background:var(--blue-soft);color:var(--blue-deep);font-size:12px;font-weight:700;font-variant-numeric:tabular-nums;}
.rec-row-meta strong{display:block;margin-bottom:2px;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rec-row-meta span.rec-goal{color:var(--muted);font-size:12px;}
.rec-row-actions{display:flex;gap:6px;flex:none;}
.rec-btn{font-size:12px;min-height:36px;padding:6px 12px;}
.rec-btn.danger{color:var(--danger);}
.mini-bars{display:grid;gap:4px;min-width:0;}
.mini-bar{display:grid;grid-template-columns:44px minmax(0,1fr) 40px;align-items:center;gap:6px;font-size:11px;color:var(--muted);}
.mini-track{display:block;height:6px;border-radius:3px;background:#e6edf5;overflow:hidden;}
.mini-fill{display:block;height:100%;border-radius:3px;background:var(--blue);}
.mini-bar b{color:var(--ink);font-weight:700;text-align:right;font-variant-numeric:tabular-nums;}
.mini-bar .mini-empty{color:#8a96a8;text-align:right;font-weight:400;}
.score-pill{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;min-width:76px;padding:6px 10px;border-radius:8px;border:1px solid #a9d8c2;background:var(--success-soft);color:#0d6042;line-height:1.2;}
.score-pill small{font-size:11px;font-weight:600;}
.score-pill strong{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;}
.score-pill.pending{border-color:#ead0a8;background:var(--warning-soft);color:#7b4708;}
.score-pill.pending strong{font-size:13px;}
.score-bar-wrap{margin-top:14px;display:grid;gap:10px;}
.score-bar-row{display:grid;grid-template-columns:64px minmax(0,1fr) minmax(110px,auto);align-items:center;gap:10px;font-size:13px;}
.score-bar-label{color:var(--ink);font-weight:600;}
.score-bar-track{position:relative;height:14px;border-radius:7px;background:#e6edf5;overflow:hidden;}
.score-bar-fill{height:100%;border-radius:7px;background:#1f63c6;}
.score-bar-val{color:var(--ink);font-weight:700;font-variant-numeric:tabular-nums;}
.score-bar-val small{color:var(--muted);font-weight:400;margin-left:4px;}
.score-bar-empty{color:#8a96a8;font-size:12px;}
.form-section{margin-top:16px;padding:16px 18px 6px;border:1px solid var(--line);border-radius:8px;background:#fff;}
.form-section h3{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:700;color:var(--blue-deep);margin:0 0 14px;}
.form-section h3 small{color:var(--muted);font-size:12px;font-weight:400;}
.sec-no{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;flex:none;border-radius:50%;background:var(--blue);color:#fff;font-size:13px;font-weight:800;}
.sub-block{margin:4px 0 12px;padding:12px 14px 2px;border:1px dashed var(--line-strong);border-radius:6px;background:#fafcff;}
.sub-block h4{margin:0 0 10px;font-size:13px;color:var(--blue-deep);}
.form-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px;}
.form-row.three{grid-template-columns:repeat(3,minmax(0,1fr));}
.field-wide{grid-column:1/-1;}
.field textarea{width:100%;border:1px solid var(--line-strong);border-radius:6px;padding:9px 12px;font:inherit;resize:vertical;}
.req{color:var(--danger);}
.score-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:12px;}
.score-card{display:grid;gap:8px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fafcff;}
.score-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:6px;}
.score-card-head label{font-size:14px;font-weight:700;color:var(--ink);}
.score-card-head label small{display:block;color:var(--muted);font-size:11px;font-weight:400;}
.score-state{flex:none;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;white-space:nowrap;}
.score-state.is-empty{background:#eef2f6;color:#6b7788;}
.score-state.has-value{background:var(--blue-soft);color:var(--blue-deep);}
.score-input-row{display:flex;align-items:center;gap:6px;}
.score-input-row input[type=number]{flex:1;min-width:0;text-align:center;}
.score-step{flex:none;width:36px;min-height:38px;border:1px solid var(--line-strong);border-radius:6px;background:#fff;color:var(--blue-deep);font-size:18px;font-weight:700;cursor:pointer;}
.score-step:hover{border-color:var(--blue);background:var(--blue-soft);}
.score-clear{flex:none;min-height:30px;padding:0 6px;border:0;background:transparent;color:var(--muted);font-size:12px;cursor:pointer;text-decoration:underline;}
.score-range{width:100%;accent-color:#1f63c6;}
.score-range.is-empty{opacity:.35;}
.pilot-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;padding:8px 12px;border-left:3px solid var(--warning);border-radius:0 6px 6px 0;background:var(--warning-soft);color:#7b4708;font-size:13px;}
.pilot-line details{flex-basis:100%;}
.pilot-line summary{display:inline;cursor:pointer;color:var(--blue);font-size:12px;font-weight:700;}
.pilot-line details p{margin:6px 0 2px;color:#5f4a2c;font-size:12px;line-height:1.7;}
.notice-pilot{padding:10px 14px;border-left:3px solid var(--warning);background:var(--warning-soft);color:var(--warning);font-size:12px;margin-bottom:12px;border-radius:0 4px 4px 0;}
.form-actions{position:sticky;bottom:0;display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;padding:12px 0;background:linear-gradient(180deg,rgba(244,247,251,0),#f4f7fb 30%);}
.trend-card{margin-top:4px;padding:16px 18px;border:1px solid var(--line);border-radius:8px;background:#fff;}
.trend-controls{display:flex;flex-wrap:wrap;gap:10px 16px;margin:14px 0 6px;align-items:flex-end;}
.trend-meta{font-size:12px;color:var(--muted);margin:6px 0 2px;}
.trend-warn{font-size:12px;color:var(--warning);margin:0 0 6px;}
.chart-wrap{position:relative;width:100%;min-height:280px;margin:10px 0 6px;}
svg.chart-svg{display:block;width:100%;height:auto;min-height:280px;max-width:none;flex:none;overflow:visible;}
.chart-legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:6px;font-size:12px;color:var(--muted);}
.lg{display:inline-flex;align-items:center;gap:6px;}
.lg-line{display:inline-block;width:18px;height:0;border-top:3px solid #1f63c6;}
.lg-gap{display:inline-block;width:18px;height:0;border-top:2px dashed #7aa2db;}
.lg-pass{display:inline-block;width:18px;height:0;border-top:2px dashed #d48a10;}
.lg-dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#1f63c6;border:2px solid #fff;box-shadow:0 0 0 1px #1f63c6;}
.lg-hollow{display:inline-block;width:10px;height:10px;border-radius:50%;background:#fff;border:2px dashed #8a96a8;}
.chart-note{font-size:12px;color:var(--muted);margin-top:6px;}
.trend-empty{margin-top:14px;}
.trend-empty small{color:var(--muted);font-size:12px;}
.report-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px;}
.report-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.report-actions select{font-size:13px;min-height:36px;}
.report-card{margin-bottom:16px;}
.report-card h3{font-size:15px;margin:0 0 12px;color:var(--ink);}
.report-info{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px 16px;font-size:13px;margin-bottom:12px;}
.report-info span{color:var(--muted);}
.report-criterion{font-size:13px;border-left:3px solid var(--blue);padding-left:10px;margin:0;}
.report-score{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px 14px;margin-bottom:6px;}
.report-score .big{font-size:60px;font-weight:800;color:var(--blue-deep);line-height:1;font-variant-numeric:tabular-nums;}
.report-score .of{font-size:15px;color:var(--muted);}
.pass-tag{display:inline-flex;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700;}
.pass-tag.ok{background:var(--success-soft);color:#0d6042;}
.pass-tag.no{background:var(--warning-soft);color:#7b4708;}
.report-note{font-size:12px;color:var(--warning);margin-top:12px;}
.report-dl-notice{font-size:13px;margin:-6px 0 14px;padding:8px 12px;border-radius:8px;}
.report-dl-notice.ok{background:#eef9f3;color:#0d6042;border:1px solid #a8dcc4;}
.report-dl-notice.warn{background:#fff8ec;color:#7b4708;border:1px solid #f0c987;}
.report-text{font-size:13px;line-height:1.8;color:#3d526d;margin:0;}
.iep-banner{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-left:4px solid var(--line);background:#fff;padding:10px 14px;border-radius:8px;margin:14px 0}.iep-banner.ok{border-color:#1d9b70;background:#eef9f3}.iep-banner.warn{border-color:#c98a1b;background:#fff8ec}.iep-banner span{font-size:12px;color:var(--muted)}.iep-banner .button{margin-left:auto}.report-foot{font-size:11px;color:var(--muted);margin-top:8px;}
.std-card{margin-bottom:14px;}
.std-card h3{font-size:15px;margin:0 0 10px;color:var(--ink);}
.std-card p{font-size:13px;line-height:1.8;margin:0;}
.dim-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:14px;}
.dim-card{display:flex;align-items:center;gap:14px;padding:14px;border:1px solid var(--line);border-radius:8px;background:#fafcff;}
.dim-ring{--p:0;display:grid;place-items:center;width:76px;height:76px;flex:none;border-radius:50%;background:conic-gradient(#1f63c6 calc(var(--p) * 1%),#e3eaf3 0);}
.dim-ring span{display:grid;place-items:center;width:56px;height:56px;border-radius:50%;background:#fff;color:var(--blue-deep);font-size:16px;font-weight:800;font-variant-numeric:tabular-nums;}
.dim-card h4{margin:0 0 4px;font-size:15px;color:var(--ink);}
.dim-card p{margin:0;font-size:12px;line-height:1.6;color:var(--muted);}
.std-formula{font-size:12px;color:var(--muted);margin-top:12px!important;}
.point-list{display:grid;gap:8px;margin:0;padding:0;list-style:none;}
.point-list li{display:flex;gap:10px;align-items:flex-start;font-size:13px;line-height:1.7;}
.point-list li::before{content:"";flex:none;width:8px;height:8px;margin-top:8px;border-radius:50%;background:var(--blue);}
.point-list.warn li::before{background:#d48a10;}
.point-list b{flex:none;color:var(--ink);}
.withdraw-note{font-size:13px;color:var(--muted);margin-bottom:8px;}
@media(max-width:900px){
  .rec-row{grid-template-columns:minmax(0,1fr) auto;}
  .rec-row .mini-bars{grid-column:1/-1;grid-row:2;}
  .rec-row-actions{grid-column:1/-1;justify-content:flex-end;}
  .score-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media(max-width:780px){
  .ws-layout{grid-template-columns:1fr;}
  .ws-sidebar{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line);}
  .student-list{display:flex;flex-wrap:wrap;gap:6px;padding:8px;}
  .student-item{border-radius:20px;border-left:0;border:1px solid var(--line);padding:4px 12px 4px 4px;font-size:13px;}
  .student-item.active{border-color:var(--blue);background:var(--blue-soft);}
  .s-meta{display:none;}
  .score-grid{grid-template-columns:1fr;}
  .form-row,.form-row.three{grid-template-columns:1fr;}
  .view-pane{padding:14px 14px 24px;}
  .score-bar-row{grid-template-columns:52px minmax(0,1fr) minmax(92px,auto);}
}
.vlink-card{border:1px solid #cfdcea;border-left:4px solid #1f63c6;border-radius:8px;background:#f7faff;padding:14px 16px;margin:0 0 16px}
.vlink-card h3,.vlink-card h4{margin:0 0 8px;color:#123b70;font-size:15px}
.vlink-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 18px;font-size:13px;margin:0 0 10px}
.vlink-grid div span{color:#5b6b80;margin-right:4px}
.vlink-block{margin:10px 0 0;font-size:13px}
.vlink-block>strong{display:block;color:#123b70;margin-bottom:4px}
.vlink-block ul{margin:0;padding-left:18px}
.vlink-metrics{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}
.vlink-metrics th,.vlink-metrics td{border:1px solid #dde6f0;padding:4px 8px;text-align:left}
.vlink-metrics th{background:#eef4fb;color:#3d526d;font-weight:600}
.seg-links{display:flex;flex-wrap:wrap;gap:6px}
.seg-link{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border:1px solid #b9cdea;border-radius:8px;background:#fff;color:#1f63c6;font-size:12px;text-decoration:none}
.seg-link:hover{background:#eaf2fd}
.suggest-tag{display:inline-block;padding:1px 8px;border-radius:8px;border:1px dashed #d48a10;color:#9a5a08;background:#fff8ec;font-size:12px;font-weight:700}
.review-tag{display:inline-block;padding:1px 8px;border-radius:8px;background:#eaf7f2;color:#0d6042;font-size:12px;font-weight:700}
.suggest-box{border:1px dashed #d48a10;background:#fffaf1;border-radius:8px;padding:12px 14px;margin:0 0 14px;font-size:13px}
.suggest-box p{margin:6px 0 0;color:#7b4708}
.suggest-dims{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.suggest-dims span{border:1px solid #f0d3a3;border-radius:8px;padding:3px 10px;background:#fff}
.recent-lessons{display:grid;gap:8px;margin:0 0 16px}
.recent-lesson{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;border:1px solid #dde6f0;border-radius:8px;padding:8px 12px;background:#fff;font-size:13px}
.recent-lesson .src{color:#5b6b80}
.pending-video{border:1px solid #f0d3a3;background:#fffaf1;border-radius:8px;padding:12px 14px;margin:0 0 16px}
.pending-video h4{margin:0 0 8px;color:#7b4708;font-size:14px}
.pending-video li{margin:4px 0}
@media print{
  .rx-header,.site-header,.skip-link,.ws-sidebar,.ws-sidebar-head,.view-tabs,.rec-row-actions,.form-section,.report-actions,#pageMsg,.rx-toast-region,button,select,nav{display:none!important;}
  body,.ws-layout{display:block;background:#fff!important;}
  .ws-main{display:block;}
  .view-pane{padding:0;max-width:none;}
  .view-pane[hidden]{display:none!important;}
  .report-card,.card{break-inside:avoid;box-shadow:none!important;}
  .score-bar-fill,.dim-ring{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
}
"""

_ADMIN_STYLE = _WORKSPACE_STYLE + """
.admin-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0;}
.admin-grid .rx-kpi-value{color:var(--blue-deep);font-size:30px;}
.channel-table-wrap{margin-top:8px;padding:18px 20px;border:1px solid var(--line);border-radius:8px;background:#fff;}
.channel-table-wrap h2{margin:0 0 4px;font-size:16px;}
.channel-table-wrap .table-sub{margin:0 0 12px;color:var(--muted);font-size:12px;}
.channel-table-wrap td small{display:block;color:var(--muted);font-size:12px;}
.review-bar{display:flex;align-items:center;gap:8px;min-width:120px;}
.review-bar span{flex:1;height:6px;border-radius:3px;background:#eef2f6;overflow:hidden;}
.review-bar span i{display:block;height:100%;background:#146c4b;}
.review-bar b{font-size:12px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums;}
.sparse-card{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:20px;margin-top:16px;padding:18px 20px;border:1px solid #b9cff0;border-radius:8px;background:#f6f9fe;}
.sparse-card h3{margin:0 0 6px;font-size:15px;}
.sparse-card p,.sparse-card li{margin:0;color:var(--text,#26364a);font-size:13px;line-height:1.6;}
.sparse-card ol{margin:6px 0 0;padding-left:20px;}
.sparse-card dl{margin:0;display:grid;gap:8px;font-size:13px;}
.sparse-card dt{font-weight:700;color:var(--ink,#172b4d);}
.sparse-card dd{margin:2px 0 0;color:var(--muted);}
.retention-foot{margin-top:16px;font-size:12px;color:var(--muted);}
#refreshBtn[aria-busy="true"]{cursor:progress;opacity:.8;}
@media(max-width:900px){.admin-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.sparse-card{grid-template-columns:minmax(0,1fr);}}
@media(max-width:460px){.admin-grid{grid-template-columns:minmax(0,1fr);}}
"""

_SPARSE_THRESHOLD = 5


def _teacher_body_html(account_json: str, account: Any = None) -> str:
    """Static HTML skeleton for the teacher measurement workspace."""
    return f"""
{teacher_header("measurement", account, logout_id="logoutBtn", page="measurement")}
<div class="ws-layout" id="wsLayout">
  <aside class="ws-sidebar" aria-label="学生列表">
    <div class="ws-sidebar-head">
      <h2>学生名册 <span id="sCount" style="font-weight:400;color:var(--muted)"></span></h2>
      <input type="search" id="studentSearch" class="student-search" placeholder="搜索姓名或班级" aria-label="搜索学生" autocomplete="off">
      <p class="switch-hint" id="switchHint" hidden>⇆ 切换学生：点击下方姓名，或使用右侧顶部的学生头像卡片</p>
    </div>
    <div class="student-list" id="studentList" role="list" aria-label="选择学生"></div>
  </aside>
  <div class="ws-main">
    <section id="measureSwitch" class="measure-switch-host" hidden></section>
    <div class="view-tabs" role="tablist" aria-label="工作区视图">
      <button role="tab" class="view-tab" data-tab="overview" aria-selected="false" aria-controls="paneOverview">总览</button>
      <button role="tab" class="view-tab" data-tab="form"     aria-selected="false" aria-controls="paneForm">记录测量</button>
      <button role="tab" class="view-tab" data-tab="trends"   aria-selected="false" aria-controls="paneTrends">纵向趋势</button>
      <button role="tab" class="view-tab" data-tab="report"   aria-selected="false" aria-controls="paneReport">单次报告</button>
      <button role="tab" class="view-tab" data-tab="standard" aria-selected="false" aria-controls="paneStandard">评分标准</button>
    </div>
    <div id="mainContent">
      <div id="pageMsg" class="page-message" role="alert" style="margin:12px 24px 0"></div>
      <div class="view-pane" id="paneOverview"  role="tabpanel" hidden></div>
      <div class="view-pane" id="paneForm"      role="tabpanel" hidden></div>
      <div class="view-pane" id="paneTrends"    role="tabpanel" hidden></div>
      <div class="view-pane" id="paneReport"    role="tabpanel" hidden></div>
      <div class="view-pane" id="paneStandard"  role="tabpanel" hidden></div>
    </div>
  </div>
</div>"""


def _admin_body(account_json: str, account: Any = None) -> str:
    tiles = "".join((
        kpi("有效记录", "—", hint="未撤回的教师测量记录", value_id="statTotal", delta_id="statTotalDelta"),
        kpi("已复核", "—", hint="已完成复核、有总分的记录", value_id="statReviewed", tone="success"),
        kpi("待复核", "—", hint="已保存但尚未复核的记录", value_id="statPending", tone="warning"),
        kpi("30天内到期", "—", hint="结构化记录将到保存期限，只提醒不自动删除", value_id="statDue"),
        kpi("视频来源记录", "—", hint="课堂视频绑定后系统生成，教师复核后才计分", value_id="statVideo",
            delta_id="statVideoDetail"),
    ))
    initial_empty = empty_state("正在读取通道明细…", compact=True)
    empty_template = json.dumps(empty_state("__TEXT__", compact=True), ensure_ascii=False).replace("</", "<\\/")
    explain = disclosure("这些数字怎么看", [
        "有效记录：教师在「学生测量」页保存且没有撤回的记录数量。",
        "已复核 / 待复核：已复核记录才有总分；待复核表示教师已保存、还没完成复核。",
        "30 天内到期：结构化记录保存 730 天，临近到期只提醒，人工归档后再处理。",
        "视频来源记录：老师在结果页绑定学生并保存本课记录后，系统按课程目标生成的待复核记录；只统计数量与复核状态。",
        "本页只做运营统计，不返回学生姓名、分数或原文，也不代表教学效果。",
    ], element_id="metricExplain")
    return f"""
{admin_header("measurements", account, logout_id="logoutBtn", page="admin_measurements", extra_actions='<button class="button" id="refreshBtn" type="button" aria-label="刷新数据">刷新</button>')}
<main id="mainContent" class="page-shell">
  <div class="page-heading">
    <div>
      <span class="eyebrow">运营统计</span>
      <h1>测量记录汇总</h1>
      <p class="lead" id="scopeNote">仅显示聚合数量；不含学生姓名、分数或原文。</p>
    </div>
    <span class="refresh-ago" id="refreshAgo" role="status" aria-live="polite" style="color:var(--muted);font-size:12px;">尚未刷新</span>
  </div>
  <div id="pageMsg" class="page-message" role="alert"></div>
  <section class="admin-grid" id="statGrid" aria-label="测量记录关键指标">{tiles}</section>
  <section class="channel-table-wrap" aria-labelledby="channelTableTitle">
    <h2 id="channelTableTitle">通道明细</h2>
    <p class="table-sub">按学校上传通道汇总测量记录数量与复核进度。</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>通道</th><th>记录总数</th><th>已复核</th><th>待复核</th><th>复核进度</th></tr></thead>
        <tbody id="channelBody"><tr><td colspan="5">{initial_empty}</td></tr></tbody>
      </table>
    </div>
  </section>
  <section class="sparse-card" id="sparseCard" aria-labelledby="sparseTitle" hidden>
    <div><h3 id="sparseTitle">数据还比较少</h3><p id="sparseText">教师保存并复核测量记录后，这里会按通道汇总数量。</p>
      <ol><li>老师在「学生测量」页为学生记录课堂表现。</li><li>完成复核后计入「已复核」。</li><li>点击右上角「刷新」查看最新汇总。</li></ol></div>
    <dl><div><dt>原始媒体</dt><dd>上传后保留 60 天，到期自动清理。</dd></div><div><dt>结构化记录</dt><dd>保留 730 天，到期只提醒，人工归档后处理。</dd></div><div><dt>隐私边界</dt><dd>后台不开放学生个人测量正文。</dd></div></dl>
  </section>
  {explain}
  <p class="retention-foot" id="retentionFoot">原始媒体保留60天，结构化记录保留730天。记录到期仅提醒，人工归档后处理。</p>
</main>
<script>
const SA={account_json},SPARSE_THRESHOLD={_SPARSE_THRESHOLD},EMPTY_TEMPLATE={empty_template};
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const byId=id=>document.getElementById(id);
const emptyRow=text=>`<tr><td colspan="5">${{EMPTY_TEMPLATE.replace('__TEXT__',esc(text))}}</td></tr>`;
const count=value=>Number.isInteger(value)&&value>=0?value:null;
const channelLabel=id=>{{const match=/^channel_(\\d+)$/.exec(String(id||''));return match?`上传通道 ${{match[1]}}`:String(id||'未绑定通道');}};
let lastTotal=null,lastRefreshed=0;
async function api(url,opts){{
  const r=await fetch(url,{{credentials:'include',...opts}});
  const j=await r.json().catch(()=>({{}}));
  if(!r.ok||!j.ok){{const code=j.error?.code||'',m=j.error?.message||j.message||'';const e=new Error(window.RxUI?.describeError?RxUI.errorText(r.status,code,m):(r.status===401?'登录已过期，请重新登录':m||'请求失败'));e.status=r.status;e.code=code;throw e;}}
  return j;
}}
function msg(text,type=''){{const el=byId('pageMsg');el.textContent=text;el.className='page-message'+(type?' '+type:'')+(text?' visible':'');}}
function agoText(){{if(!lastRefreshed)return '尚未刷新';const s=Math.max(0,Math.round((Date.now()-lastRefreshed)/1000));return s<5?'刚刚已刷新':s<60?`${{s}} 秒前已刷新`:`${{Math.floor(s/60)}} 分钟前已刷新`;}}
function progressCell(c){{const total=count(c.records)||0,done=count(c.reviewed)||0,pct=total?Math.round(done*100/total):0;return `<div class="review-bar" aria-label="复核进度 ${{pct}}%"><span><i style="width:${{pct}}%"></i></span><b>${{pct}}%</b></div>`;}}
async function refresh(){{
  const btn=byId('refreshBtn');btn.disabled=true;btn.setAttribute('aria-busy','true');btn.textContent='刷新中…';
  try{{
    const d=await api('{_API}/admin/measurements');
    const s=d.summary||{{}};
    const total=count(s.records);
    byId('statTotal').textContent=total??'—';
    byId('statReviewed').textContent=count(s.reviewed)??'—';
    byId('statPending').textContent=count(s.pending)??'—';
    byId('statDue').textContent=count(s.due_30_days)??'—';
    const vs=s.video_source||{{}};
    byId('statVideo').textContent=count(vs.records)??'—';
    byId('statVideoDetail').textContent=count(vs.records)==null?'':`已复核计分 ${{count(vs.reviewed)??0}} · 待复核 ${{count(vs.pending)??0}}`;
    const delta=byId('statTotalDelta');
    delta.textContent=total==null?'':lastTotal==null?'首次读取':total===lastTotal?'较上次刷新无变化':`较上次刷新 ${{total>lastTotal?'+':'-'}}${{Math.abs(total-lastTotal)}}`;
    if(total!=null)lastTotal=total;
    const ch=Array.isArray(s.channels)?s.channels:[];
    byId('channelBody').innerHTML=ch.length
      ?ch.map(c=>`<tr><td><strong>${{esc(channelLabel(c.channel_id))}}</strong><small class="mono">${{esc(c.channel_id)}}</small></td><td>${{esc(c.records)}}</td><td>${{esc(c.reviewed)}}</td><td>${{esc(c.pending)}}</td><td>${{progressCell(c)}}</td></tr>`).join('')
      :emptyRow('还没有通道产生测量记录。');
    const sparse=total!=null&&total<SPARSE_THRESHOLD;
    byId('sparseCard').hidden=!sparse;
    if(sparse)byId('sparseText').textContent=total===0?'目前还没有测量记录。教师保存并复核测量记录后，这里会按通道汇总数量。':`目前共有 ${{total}} 条测量记录，数据还比较少，汇总趋势仅供参考。`;
    if(s.scope)byId('scopeNote').textContent=s.scope;
    if(s.structured_retention_days)byId('retentionFoot').textContent=`原始媒体保留60天，结构化记录保留${{Number(s.structured_retention_days)}}天。记录到期仅提醒，人工归档后处理。`;
    lastRefreshed=Date.now();byId('refreshAgo').textContent=agoText();
    msg('数据已刷新。','success');
  }}catch(e){{msg(e.message);byId('channelBody').innerHTML=emptyRow('通道明细读取失败，请点击「刷新」重试。');}}finally{{btn.disabled=false;btn.removeAttribute('aria-busy');btn.textContent='刷新';}}
}}
byId('accountName').textContent=SA.login_alias||SA.username||'管理员';
byId('refreshBtn').addEventListener('click',refresh);
byId('logoutBtn').addEventListener('click',async()=>{{try{{await api('{_API}/auth/logout',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}})}}finally{{window.location.assign('/demo2/login');}}}});
if(typeof window.setInterval==='function')window.setInterval(()=>{{if(lastRefreshed)byId('refreshAgo').textContent=agoText();}},5000);
refresh();
</script>"""


def _teacher_script(account_json: str) -> str:
    # Same contract the backend scores with; '</' escaped so it cannot close the script tag.
    rubric_json = json.dumps(rubric_contract(), ensure_ascii=False).replace("</", "<\\/")
    init = (
        f"const ACCT={account_json};\n"
        f"const API='{_API}';\n"
        f"const RUBRIC={rubric_json};\n"
    )
    # JS uses raw braces; no f-string needed for the bulk
    rest = r"""
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const byId=id=>document.getElementById(id);
async function api(url,opts){
  const r=await fetch(url,{credentials:'include',...opts});
  // A 401 no longer redirects: the shared notice offers re-login and keeps the unsaved form.
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j.ok){const code=j.error?.code||'',m=j.error?.message||j.message||'';const e=new Error(window.RxUI?.describeError?RxUI.describeError(r.status,code,m).text:(r.status===401?'登录已过期，请重新登录':m||'请求失败'));e.status=r.status;e.code=code;e.serverMessage=m;throw e;}
  return j;
}
const formGuard=(window.RxUI&&RxUI.trackForm)?RxUI.trackForm('#measForm'):{isDirty(){return false;},clean(){},markDirty(){}};
function errHtml(e){return window.RxUI?.errorHtml?RxUI.errorHtml(RxUI.fromError(e)):esc(e&&e.message||'请求失败');}
function errMsg(e){const el=byId('pageMsg');el.innerHTML=errHtml(e);el.className='page-message visible';}
function okToast(text){if(window.RxUI?.success)RxUI.success(text);}
async function askReason(opts){
  if(window.RxUI?.confirmDialog)return RxUI.confirmDialog(opts);
  const v=window.prompt(opts.input.label+'：');return v&&v.trim()?v.trim():null;
}
function msg(text,type=''){const el=byId('pageMsg');el.textContent=text;el.className='page-message'+(type?' '+type:'')+(text?' visible':'');}
function localToday(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function fmtDate(s){if(!s)return'—';const d=new Date(s);if(!isNaN(d)&&window.RxUI)return RxUI.formatDate(s);return isNaN(d)?s:`${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`;}
function scoreLabel(v){return v==null?'—':String(v);}
const DIM_KEYS=RUBRIC.dimensions.map(d=>d.key);
const DIM_LABELS=Object.fromEntries(RUBRIC.dimensions.map(d=>[d.key,d.label]));
const DIM_WEIGHTS=Object.fromEntries(RUBRIC.dimensions.map(d=>[d.key,d.weight_percent+'%']));
const EVIDENCE_INSUFFICIENT=RUBRIC.evidence_status.insufficient;
const SCALE_MAX=Number(RUBRIC.scale.max)||10;
const PASS_SCORE=Number(RUBRIC.scale.pass_score)||6;
const TREND_MIN_POINTS=2;
const CHART_BLUE='#1f63c6',CHART_PASS='#d48a10',CHART_GRID='#e3eaf3',CHART_MUTED='#5b6b80',CHART_HOLLOW='#8a96a8';
function fmtScore(v){return v==null?'—':Number(v).toFixed(RUBRIC.decimals);}
function basisBtn(recordId,focus,label){return `<button type="button" class="sb-btn" data-sb-kind="measurement" data-sb-record="${esc(recordId)}"${focus?` data-sb-focus="${esc(focus)}"`:''} title="查看计算公式、命中锚点与证据">${esc(label||'查看依据')}</button>`;}
function basisSummary(r){const b=r&&r.score_basis;if(!b||!b.formula)return'';const text=b.status!=='scored'?`依据：证据不足，未计分（${(b.reasons||[]).join('；')}）`:`依据：${b.formula.expression} = ${b.formula.result}；观察 ${b.inputs?.observed??'—'}/${b.inputs?.opportunities??'—'} 次，提示层级「${b.inputs?.support_label||'未记录'}」（量表 ${b.rubric_version}）`;return `<p class="report-note" id="reportBasisSummary"${b.status==='scored'?' style="color:var(--muted)"':''}>${esc(text)}</p>`;}
function fmtNum(v){const n=Number(v);return Number.isInteger(n)?String(n):n.toFixed(1);}
function formalScore(a){return a&&a.evidence_status!==EVIDENCE_INSUFFICIENT&&a.score!=null?a.score:null;}
function dimValue(r,key){const raw=r.scores?r.scores[key]:undefined;if(raw!=null)return raw;const d=r.assessment?.dimensions?.[key];return d&&d.score!=null?d.score:null;}
function avatarTone(id){let h=0;for(const c of String(id||''))h=(h*31+c.charCodeAt(0))>>>0;return h%5;}
function firstChar(name){const s=String(name||'').trim();return s?Array.from(s)[0]:'?';}
let state={students:[],records:[],trends:[],stdStatus:'',selectedId:null,currentTab:'overview',saving:false,filter:'',formRecordId:null,avatars:{}};
let measureSwitch=null;
// 统一「切换学生」条（demo2_ui_kit RxUI.studentSwitcher）：URL 写 ?student_id=，后退/前进回到上一名学生。
function measureItems(){return state.students.map(s=>{const vids=state.records.filter(r=>r.student_id===s.student_id&&r.source_type==='video').length;return {key:s.student_id,student_id:s.student_id,title:s.display_name,subtitle:(s.class_name||s.student_code||'名册学生')+' · 测量 '+state.records.filter(r=>r.student_id===s.student_id).length+' 条',initial:s.display_name,avatarUrl:state.avatars[s.student_id]||'',status:vids?'bound':'unbound',statusText:vids?'已绑定视频':'未绑定视频'};});}
function renderMeasureSwitch(){const hint=byId('switchHint');if(hint)hint.hidden=state.students.length<2;if(typeof window==='undefined'||!window.RxUI||!window.RxUI.studentSwitcher)return;const host=byId('measureSwitch');if(!host)return;if(state.students.length<2){host.hidden=true;return;}if(!measureSwitch)measureSwitch=window.RxUI.studentSwitcher(host,{page:'measurement',param:'student_id',label:'切换学生',note:'名册中有 '+state.students.length+' 名学生：点击头像卡片切换，总览、记录测量、纵向趋势和单次报告都会切换到该学生；浏览器后退可回到上一名学生。',onSelect:item=>{if(item.student_id!==state.selectedId)selectStudent(item.student_id,false);}});measureSwitch.update(measureItems(),state.selectedId||undefined);}
async function loadMeasureAvatars(){if(typeof window==='undefined'||!window.RxUI||!window.RxUI.loadLessonPersons)return;const latest={};state.records.forEach(r=>{if(r.source_type==='video'&&r.task_id&&r.person_id&&!latest[r.student_id])latest[r.student_id]=r;});const tasks=[...new Set(Object.values(latest).map(r=>r.task_id))].slice(0,5);for(const t of tasks){const d=await window.RxUI.loadLessonPersons(t);(d&&d.persons||[]).forEach(p=>{Object.keys(latest).forEach(sid=>{const r=latest[sid];if(r.task_id===t&&r.person_id===p.person_id&&p.avatar)state.avatars[sid]=window.RxUI.personAvatarUrl(t,p.avatar);});});}if(tasks.length)renderMeasureSwitch();}
const SOURCE_LABELS={classroom_observation:'现场观察',video_review:'视频复核',video:'课堂视频（系统生成）'};
const SUGGEST_LABEL='建议·待复核';
function isVideoSource(t){return t==='video_review'||t==='video';}
function isPendingVideo(r){return !!r&&r.source_type==='video'&&!r.reviewed;}
function sourceLabel(r){return SOURCE_LABELS[r&&r.source_type]||'现场观察';}
function fmtSec(v){const n=Math.max(0,Math.round(Number(v)||0));return String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0');}
function pct(v){return v==null?'—':Math.round(Number(v)*100)+'%';}
function suggestedText(sc){sc=sc||{};return DIM_KEYS.map(k=>`${DIM_LABELS[k]} ${sc[k]==null?'留空':fmtNum(sc[k])}`).join('、');}
function segUrl(r,s){return s.url||('/demo2/video?id='+encodeURIComponent(r.task_id||'')+'&t='+Math.floor(Number(s.start_sec)||0));}
function segmentLinksHtml(r){const segs=r.evidence_segments||[];if(!segs.length)return '<span class="pane-muted">暂无证据片段</span>';return `<div class="seg-links">${segs.map(s=>`<a class="seg-link" href="${esc(segUrl(r,s))}" title="在视频回放页打开该时间切片">▶ ${esc(fmtSec(s.start_sec))}–${esc(fmtSec(s.end_sec))} ${esc(s.state_label||'')}</a>`).join('')}</div>`;}
function metricsTableHtml(m){m=m||{};return `<table class="vlink-metrics"><thead><tr><th>指标</th><th>片段数</th><th>时长（秒）</th><th>时长占比</th></tr></thead><tbody><tr><td>稳定参与</td><td>${esc(m.engaged_segments??'—')}</td><td>${esc(m.engaged_seconds??'—')}</td><td>${esc(pct(m.engaged_ratio))}</td></tr><tr><td>回应偏低</td><td>${esc(m.low_response_segments??'—')}</td><td>${esc(m.low_response_seconds??'—')}</td><td>${esc(pct(m.low_response_ratio))}</td></tr><tr><td>离开或不可见</td><td>${esc(m.away_segments??'—')}</td><td>${esc(m.away_seconds??'—')}</td><td>${esc(pct(m.away_ratio))}</td></tr><tr><td>未观察</td><td>${esc(m.not_observed_segments??'—')}</td><td>${esc(m.not_observed_seconds??'—')}</td><td>${esc(pct(m.not_observed_ratio))}</td></tr></tbody></table><p class="pane-muted" style="margin:4px 0 0;font-size:12px">参与得分参考：${m.participation_score_ref==null?'—':esc(fmtNum(m.participation_score_ref))} / 10（视频活动线索，不是正式分数）</p>`;}
function iepSupportHtml(r){const items=r.iep_support||[];const manual=r.iep_manual_supplement||'';if(!items.length&&!manual)return `<span class="pane-muted">${esc(r.iep_status_label||'本课未关联 IEP 支持条件')}</span>`;return `<ul>${items.map(i=>`<li><b>${esc(i.category_label||'要点')}</b>：${esc(i.text)}${i.page?` <small class="pane-muted">（第 ${esc(i.page)} 页）</small>`:''}</li>`).join('')}${manual?`<li><b>教师补充</b>：${esc(manual)}</li>`:''}</ul>`;}
function reviewTagHtml(r){return r.reviewed?'<span class="review-tag">教师已复核</span>':`<span class="suggest-tag">${SUGGEST_LABEL}</span>`;}
function videoLinkInfoHtml(r,heading){
  if(r.source_type!=='video')return '';
  return `<div class="vlink-card"><h3>${esc(heading||'本课视频测量依据')} ${reviewTagHtml(r)}</h3>
<div class="vlink-grid"><div><span>课程任务：</span>${r.course_task_doc_id?esc(String(r.course_task_doc_id).slice(0,12))+' · 版本 '+esc(r.course_task_version):'本课未确认课程任务'}</div><div><span>课堂任务：</span><code>${esc(String(r.task_id||'').slice(0,12))}</code></div><div><span>上课日期：</span>${esc(fmtDate(r.lesson_date))}${r.lesson_date_source==='course_task'?'（来自课程任务）':'（来自上传时间）'}</div><div><span>学习目标：</span>${esc(r.goal_id)} ${esc(r.goal_description||'')}</div></div>
<div class="vlink-block"><strong>通过标准</strong>${esc(r.pass_criteria||r.criterion||'未填写')}</div>
<div class="vlink-block"><strong>测量条件</strong>${esc(r.measurement_conditions||r.measurement_context||'未填写')}</div>
<div class="vlink-block"><strong>IEP 支持条件</strong>${iepSupportHtml(r)}</div>
<div class="vlink-block"><strong>视频指标汇总</strong>${metricsTableHtml(r.video_metrics)}</div>
<div class="vlink-block"><strong>证据片段（点击跳转到视频对应时间）</strong>${segmentLinksHtml(r)}</div>
${r.lesson_summary?`<div class="vlink-block"><strong>本课总结</strong>${esc(r.lesson_summary)}</div>`:''}
</div>`;
}
function suggestionHtml(r){
  if(r.source_type!=='video')return '';
  const sc=r.suggested_scores||{};
  return `<div class="suggest-box" id="suggestBox"><span class="suggest-tag">${SUGGEST_LABEL}</span> 系统根据视频片段给出的四维建议分，未复核前不计入趋势得分线和报告综合分。
<div class="suggest-dims">${DIM_KEYS.map(k=>`<span>${esc(DIM_LABELS[k])} <b>${sc[k]==null?'留空':esc(fmtNum(sc[k]))}</b></span>`).join('')}<span>建议机会 <b>${esc(r.suggested_opportunities??'—')}</b> 次</span><span>建议观察 <b>${esc(r.suggested_observed??'—')}</b> 次</span></div>
<p>${esc(r.suggestion_basis||'')}</p>
<button type="button" class="button" id="applySuggestion" style="margin-top:8px">采用系统建议分（仍需逐项核对后勾选复核）</button></div>`;
}

function applyWorkspace(ws){
  state.students=ws.students||[];
  state.records=ws.records||[];
  state.trends=ws.trends||[];
  state.stdStatus=ws.standard_status||'';
}

async function loadWorkspace(){
  msg('加载中…','info');
  try{
    const d=await api(API+'/measurements');
    applyWorkspace(d.workspace||{});
    renderSidebar();
    const wantedStudent=(typeof location!=='undefined'&&location.search)?(new URLSearchParams(location.search).get('student_id')||''):'';
    const firstStudent=state.students.find(s=>s.student_id===wantedStudent)||state.students[0];
    const wantedRecord=(typeof location!=='undefined'&&location.search)?(new URLSearchParams(location.search).get('record_id')||''):'';
    const deepRecord=state.records.find(r=>r.record_id===wantedRecord);
    if(deepRecord)selectStudent(deepRecord.student_id,false);
    else if(firstStudent)selectStudent(firstStudent.student_id,false);
    renderMeasureSwitch();loadMeasureAvatars().catch(()=>{});
    switchTab((tabNav&&tabNav.initial())||'overview');
    if(deepRecord){if(state.currentTab==='report')renderReport(deepRecord.record_id);else editRecord(deepRecord.record_id);}
    msg('');
  }catch(e){errMsg(e);}
}

// After a save or withdrawal the trend series must be rebuilt by the backend.
async function reloadWorkspaceData(){
  try{const d=await api(API+'/measurements');applyWorkspace(d.workspace||{});return true;}
  catch(e){console.warn('[measurement] workspace_reload_failed',e&&e.message);return false;}
}

function recordCounts(){const cnt={};for(const r of state.records)cnt[r.student_id]=(cnt[r.student_id]||0)+1;return cnt;}

function renderSidebar(){
  const sc=byId('sCount');if(sc)sc.textContent='（'+state.students.length+'人）';
  const list=byId('studentList');if(!list)return;
  const cnt=recordCounts();
  const q=String(state.filter||'').trim().toLowerCase();
  const shown=state.students.filter(s=>!q||String(s.display_name||'').toLowerCase().includes(q)||String(s.class_name||s.student_code||'').toLowerCase().includes(q));
  if(!state.students.length){list.innerHTML='<div class="s-empty">暂无学生名册，请先在「学生名册」中建档或完成身份确认。</div>';return;}
  if(!shown.length){list.innerHTML='<div class="s-empty">没有匹配的学生，请换个关键词。</div>';return;}
  list.innerHTML=shown.map(s=>`<div class="student-item${cnt[s.student_id]?' has-records':''}${s.student_id===state.selectedId?' active':''}" data-id="${esc(s.student_id)}" role="listitem" tabindex="0" aria-label="${esc(s.display_name)}"><span class="rx-avatar" data-tone="${avatarTone(s.student_id)}" aria-hidden="true">${esc(firstChar(s.display_name))}</span><span class="s-name">${esc(s.display_name)}<span class="s-meta">${esc(s.class_name||s.student_code||'')}</span></span>${cnt[s.student_id]?`<span class="s-count" title="有效记录 ${cnt[s.student_id]} 条">${cnt[s.student_id]}</span>`:''}</div>`).join('');
  list.querySelectorAll('.student-item').forEach(el=>{
    el.addEventListener('click',()=>selectStudent(el.dataset.id,true,true));
    el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectStudent(el.dataset.id,true,true);}});
  });
}

function selectStudent(id,switchToOverview=true,pushHistory=false){
  state.selectedId=id;
  if(measureSwitch)measureSwitch.select(id,{push:pushHistory,trigger:pushHistory?'click':'init'});
  document.querySelectorAll('.student-item').forEach(el=>el.classList.toggle('active',el.dataset.id===id));
  if(switchToOverview)switchTab('overview');else refreshCurrentPane();
}

function refreshCurrentPane(){switchTab(state.currentTab);}

// URL hash #tab-<name> lets the header back/forward buttons walk between tabs.
const tabNav=(typeof window!=='undefined'&&window.RxUI&&window.RxUI.tabHash)?window.RxUI.tabHash({names:['overview','form','trends','report','standard'],current:()=>state.currentTab,apply:name=>applyTabFromHistory(name)}):null;
if(tabNav&&tabNav.initial())state.currentTab=tabNav.initial();
// 后退/前进回到「记录测量」时恢复刚才正在编辑的记录，而不是变成空白的新增表单。
function applyTabFromHistory(name){
  const id=state.formRecordId;
  if(name==='form'&&id&&state.records.some(r=>r.record_id===id)){editRecord(id);return;}
  switchTab(name);
}
function switchTab(tab,pushHistory=false){
  if(tabNav)tabNav.set(tab,pushHistory&&state.currentTab!==tab);
  if(tab==='form')state.formRecordId=null;
  if(tab!=='form')formGuard.clean();
  state.currentTab=tab;
  document.querySelectorAll('.view-tab').forEach(t=>t.setAttribute('aria-selected',String(t.dataset.tab===tab)));
  ['overview','form','trends','report','standard'].forEach(t=>{const el=byId('pane'+t.charAt(0).toUpperCase()+t.slice(1));if(el)el.hidden=t!==tab;});
  if(tab==='overview')renderOverview();
  else if(tab==='form')renderForm(null);
  else if(tab==='trends')renderTrends();
  else if(tab==='report')renderReport(null);
  else if(tab==='standard')renderStandard();
}

function studentName(id){const s=state.students.find(x=>x.student_id===id);return s?s.display_name:id;}
function studentInfo(id){return state.students.find(x=>x.student_id===id)||{};}
function studentRecords(id){return state.records.filter(r=>r.student_id===id);}
function noStudentHtml(text){return `<div class="rx-empty"><p>${esc(text)}</p></div>`;}

function miniBars(r){
  return `<div class="mini-bars" aria-label="四维分数">${DIM_KEYS.map(k=>{
    const v=dimValue(r,k);
    if(v==null)return `<div class="mini-bar"><span>${esc(DIM_LABELS[k])}</span><span class="mini-track"></span><span class="mini-empty">未观察</span></div>`;
    const pct=Math.min(100,Math.max(0,(Number(v)/SCALE_MAX)*100));
    return `<div class="mini-bar"><span>${esc(DIM_LABELS[k])}</span><span class="mini-track"><span class="mini-fill" style="width:${pct.toFixed(1)}%"></span></span><b>${esc(fmtNum(v))}</b></div>`;
  }).join('')}</div>`;
}

function iepBanner(info){
  const status=String(info?.iep_status||'unavailable');
  const label=status==='available'?'IEP 已关联':status==='not_found'?'尚未上传 IEP':status==='ambiguous'?'存在多份有效 IEP':'IEP 不可用';
  const note=status==='available'?'正式报告可以使用当前 IEP 目标与支持条件。':status==='not_found'?'正式报告会被阻断；请先到学生资料中登记授权并上传 IEP 摘要。':status==='ambiguous'?'请先核实并只保留一份当前有效 IEP。':'授权到期/撤回或资料不可用，请重新登记。';
  const tone=status==='available'?'ok':'warn';
  return `<div class="iep-banner ${tone}" id="iepBanner"><strong>${esc(label)}</strong><span>${esc(note)}</span><a class="button quiet" href="/demo2/dossier?student_id=${encodeURIComponent(info?.student_id||'')}">管理 IEP 与授权</a></div>`;
}
function renderOverview(){
  const pane=byId('paneOverview');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML=noStudentHtml('请从左侧选择学生。');return;}
  const info=studentInfo(sid);
  const recs=studentRecords(sid);
  const reviewed=recs.filter(r=>formalScore(r.assessment)!=null).length;
  const pending=recs.length-reviewed;
  const videoPending=recs.filter(isPendingVideo);
  pane.innerHTML=`<div class="ov-head">
  <span class="rx-avatar rx-avatar-lg" data-tone="${avatarTone(sid)}" aria-hidden="true">${esc(firstChar(studentName(sid)))}</span>
  <div class="ov-head-text"><h2 class="pane-title">${esc(studentName(sid))}</h2><p class="pane-sub">${esc(info.class_name||info.student_code||'学生测量总览')}</p></div>
  <div class="ov-actions"><button class="button primary" onclick="switchTab('form')">+ 新增记录</button><button class="button" onclick="switchTab('trends')">查看趋势</button><a class="button" href="/demo2/long-term?student_id=${encodeURIComponent(sid)}">长期观测 / IEP</a></div>
</div>
${iepBanner(info)}
<div class="overview-cards">
  <article class="rx-kpi"><span class="rx-kpi-label">有效记录</span><strong class="rx-kpi-value" id="kpiTotal">${recs.length}</strong><small class="rx-kpi-hint">未撤销的测量记录</small></article>
  <article class="rx-kpi rx-kpi-success"><span class="rx-kpi-label">已复核得分</span><strong class="rx-kpi-value" id="kpiReviewed">${reviewed}</strong><small class="rx-kpi-hint">满足最低评分条件并已复核</small></article>
  <article class="rx-kpi${pending?' rx-kpi-warning':''}"><span class="rx-kpi-label">待复核</span><strong class="rx-kpi-value" id="kpiPending">${pending}</strong><small class="rx-kpi-hint">未复核或${esc(EVIDENCE_INSUFFICIENT)}；其中视频来源 <b id="kpiVideoPending">${videoPending.length}</b> 条</small></article>
</div>
${videoPending.length?`<div class="pending-video" id="ovVideoPending"><h4>课堂视频生成的待复核记录（${videoPending.length} 条，${SUGGEST_LABEL}）</h4><ul>${videoPending.map(r=>`<li>${esc(fmtDate(r.lesson_date))} · ${esc(r.course_name||r.lesson_id)} · ${esc(r.goal_id)} ${esc(r.goal_description||'')} <button class="button rec-btn" onclick="editRecord(${esc(JSON.stringify(r.record_id))})">补全并复核</button> <button class="button rec-btn" onclick="openReport(${esc(JSON.stringify(r.record_id))})">单次报告</button></li>`).join('')}</ul></div>`:''}
<h3 class="list-title">最近课堂 <span>含视频来源</span></h3>
<div class="recent-lessons" id="ovRecentLessons"></div>
<h3 class="list-title">测量记录 <span>按上课日期倒序</span></h3>
<div class="rec-list" id="ovRecList"></div>`;
  const recList=byId('ovRecList');
  if(!recs.length){recList.innerHTML=`<div class="rx-empty"><p>该学生暂无测量记录。</p><button class="button primary" onclick="switchTab('form')">+ 新增第一条记录</button></div>`;return;}
  const ordered=recs.slice().sort((a,b)=>String(b.lesson_date||'').localeCompare(String(a.lesson_date||''))||String(b.updated_at||'').localeCompare(String(a.updated_at||'')));
  const lessons=[],seen={};
  ordered.forEach(r=>{const k=(r.task_id||'')+'|'+(r.lesson_date||'')+'|'+(r.course_name||r.lesson_id||'');if(!seen[k]){seen[k]={date:r.lesson_date,course:r.course_name||r.lesson_id,task:r.task_id||'',sources:[],count:0,pending:0};lessons.push(seen[k]);}const g=seen[k];const label=sourceLabel(r);if(!g.sources.includes(label))g.sources.push(label);g.count++;if(formalScore(r.assessment)==null)g.pending++;});
  const recentBox=byId('ovRecentLessons');
  if(recentBox)recentBox.innerHTML=lessons.slice(0,5).map(g=>`<div class="recent-lesson"><strong>${esc(fmtDate(g.date))}</strong><span>${esc(g.course)}</span><span class="src">${esc(g.sources.join(' / '))}</span><span>${g.count} 条记录${g.pending?`（待复核 ${g.pending}）`:''}</span>${g.task?`<a href="/demo2/simple-result?task_id=${encodeURIComponent(g.task)}" class="seg-link">课堂结果页</a>`:''}</div>`).join('');
  recList.innerHTML=ordered.map(r=>{
    const sc=formalScore(r.assessment);
    const reasons=(r.assessment?.evidence_reasons||[]).join('；');
    const badge=sc!=null
      ?`<span class="score-pill" title="综合得分（已复核）"><small>综合</small><strong>${fmtScore(sc)}</strong></span>`
      :isPendingVideo(r)?`<span class="score-pill pending" title="${esc(suggestedText(r.suggested_scores))}"><small>${SUGGEST_LABEL}</small><strong>待复核</strong></span>`
      :`<span class="score-pill pending" title="${esc(reasons)}"><small>${r.reviewed?'未达评分条件':'待复核'}</small><strong>${esc(EVIDENCE_INSUFFICIENT)}</strong></span>`;
    return `<div class="rec-row"><div class="rec-row-meta"><span class="rec-date">${esc(fmtDate(r.lesson_date))}</span><strong>${esc(r.course_name||r.lesson_id)}</strong><span class="rec-goal">${esc(r.goal_id)} / ${esc(r.measurement_context)} · ${esc(sourceLabel(r))}</span></div>${miniBars(r)}${badge}<div class="rec-row-actions">${basisBtn(r.record_id)}<button class="button rec-btn" onclick="editRecord(${esc(JSON.stringify(r.record_id))})">${isPendingVideo(r)?'补全并复核':'编辑'}</button><button class="button rec-btn danger" onclick="promptWithdraw(${esc(JSON.stringify(r.record_id))},${Number(r.version)})">撤销</button></div></div>`;
  }).join('');
}

let _editingRecord=null;
const SCORE_INPUTS=[['accuracy','fAcc','acc'],['independence','fInd','ind'],['consistency','fCon','con'],['transfer','fTrf','trf']];

function scoreCardHtml(prev,[key,id,name]){
  const raw=prev.scores?prev.scores[key]:null;
  const has=raw!=null;
  const d=RUBRIC.dimensions.find(x=>x.key===key)||{label:key,weight_percent:''};
  return `<div class="score-card" data-dim="${esc(key)}">
  <div class="score-card-head"><label for="${id}">${esc(d.label)}<small>0–10 分 · 权重${esc(d.weight_percent)}%</small></label><span class="score-state ${has?'has-value':'is-empty'}" id="${id}State" aria-live="polite">${has?esc(fmtNum(raw))+' 分':'未观察'}</span></div>
  <div class="score-input-row"><button type="button" class="score-step" data-step="-1" data-target="${id}" aria-label="${esc(d.label)}减 1 分">−</button><input type="number" id="${id}" name="${name}" min="0" max="10" step="0.1" inputmode="decimal" placeholder="留空=未观察" value="${has?esc(raw):''}"><button type="button" class="score-step" data-step="1" data-target="${id}" aria-label="${esc(d.label)}加 1 分">+</button></div>
  <input type="range" class="score-range${has?'':' is-empty'}" id="${id}Range" min="0" max="10" step="0.5" value="${has?esc(raw):0}" data-target="${id}" aria-label="${esc(d.label)}滑块，拖动即填写分数">
  <button type="button" class="score-clear" data-clear="${id}">清空（设为未观察）</button>
</div>`;
}

function syncScoreCard(id){
  const input=byId(id),stateEl=byId(id+'State'),range=byId(id+'Range');
  if(!input||!stateEl||!range)return;
  const raw=input.value.trim();
  const n=raw===''?null:Number(raw);
  if(n==null||!isFinite(n)){
    stateEl.textContent=raw===''?'未观察':'格式无效';stateEl.className='score-state is-empty';
    range.classList.add('is-empty');if(raw==='')range.value='0';
    return;
  }
  stateEl.textContent=fmtNum(n)+' 分';stateEl.className='score-state has-value';
  range.classList.remove('is-empty');range.value=String(Math.min(10,Math.max(0,n)));
}

function bindScoreCards(){
  SCORE_INPUTS.forEach(([,id])=>{
    const input=byId(id),range=byId(id+'Range');if(!input||!range)return;
    input.addEventListener('input',()=>syncScoreCard(id));
    range.addEventListener('input',()=>{input.value=range.value;syncScoreCard(id);});
  });
  document.querySelectorAll('#measForm .score-step').forEach(btn=>btn.addEventListener('click',()=>{
    const input=byId(btn.dataset.target);if(!input)return;
    const step=Number(btn.dataset.step);
    const cur=input.value.trim()===''?null:Number(input.value);
    let next;
    if(cur==null||!isFinite(cur)){if(step<0)return;next=0;}
    else next=Math.round((cur+step)*10)/10;
    input.value=String(Math.min(10,Math.max(0,next)));syncScoreCard(btn.dataset.target);
  }));
  document.querySelectorAll('#measForm .score-clear').forEach(btn=>btn.addEventListener('click',()=>{
    const input=byId(btn.dataset.clear);if(!input)return;input.value='';syncScoreCard(btn.dataset.clear);input.focus();
  }));
}

function renderForm(existing){
  const pane=byId('paneForm');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML=noStudentHtml('请先从左侧选择学生。');return;}
  formGuard.clean();
  _editingRecord=existing||null;
  const prev=existing||{};
  const isEdit=!!existing;
  const recs=studentRecords(sid);
  const prevGoals=[...new Set(recs.map(r=>r.goal_id).filter(Boolean))];
  const prevContexts=[...new Set(recs.map(r=>r.measurement_context).filter(Boolean))];
  const prevCourses=[...new Set(recs.map(r=>r.course_name).filter(Boolean))];
  function datalistHtml(listId,vals){return `<datalist id="${listId}">${vals.map(v=>`<option value="${esc(v)}">`).join('')}</datalist>`;}
  const star='<span aria-hidden="true" class="req">*</span>';
  pane.innerHTML=`
<h2 class="pane-title">${isEdit?'编辑记录':'新增测量记录'} — ${esc(studentName(sid))}</h2>
<p class="pane-sub" style="margin-bottom:12px">${isEdit?`记录编号 <code>${esc(prev.record_id)}</code>，当前版本 ${esc(prev.version)}`:'填写本课真实观察数据，不得使用虚构日期。带 * 为必填。'}</p>
${videoLinkInfoHtml(prev,'本课视频测量依据（系统带入，复核时请对照视频片段）')}
<div class="pilot-line"><span>四维权重为试行参考，6分为参考合格线（不具法定效力）；没观察到的维度请留空。</span>
  <details id="pilotDetails"><summary>查看试行量表说明</summary><p>试行量表说明：准确性35%、独立性30%、一致性20%、泛化性15%为设计参考，尚待校方确认，不是官方验证权重。6分为参考合格线，不具法定效力。0分表示真实的零成功；缺乏观察机会时请留空，保存后按缺失处理，不按0分计算。</p></details></div>
<div id="formErr" class="form-error" role="alert"></div>
<form id="measForm" novalidate autocomplete="off">
<section class="form-section" aria-labelledby="secLesson"><h3 id="secLesson"><span class="sec-no">1</span>课堂信息</h3>
<div class="form-row">
  <div class="field"><label for="fLessonDate">上课日期 ${star}</label><input type="date" id="fLessonDate" name="lesson_date" required max="${localToday()}" value="${esc(prev.lesson_date||'')}"><small>必须为真实上课日期，不接受未来日期。</small></div>
  <div class="field"><label for="fLessonId">课节编号 ${star}</label><input type="text" id="fLessonId" name="lesson_id" required maxlength="120" value="${esc(prev.lesson_id||'')}" placeholder="如 L2025-11-03-A"></div>
</div>
<div class="form-row">
  <div class="field"><label for="fCourseName">课程名称</label><input type="text" id="fCourseName" name="course_name" maxlength="200" value="${esc(prev.course_name||'')}" list="courseList" placeholder="如 生活自理技能训练">${datalistHtml('courseList',prevCourses)}</div>
  <div class="field"><label for="fSourceType">数据来源 ${star}</label><select id="fSourceType" name="source_type" required><option value="">请选择</option><option value="classroom_observation"${prev.source_type==='classroom_observation'?' selected':''}>现场观察</option><option value="video_review"${prev.source_type==='video_review'?' selected':''}>视频复核</option>${prev.source_type==='video'?'<option value="video" selected>课堂视频（系统生成）</option>':''}</select></div>
</div>
<div class="sub-block" id="videoSection" style="display:none"><h4>视频信息（视频复核必填）</h4>
<div class="form-row three">
  <div class="field"><label for="fTaskId">上传任务编号</label><input type="text" id="fTaskId" name="task_id" maxlength="120" value="${esc(prev.task_id||'')}"><small>需已完成身份确认。<a href="/demo2/identity">去确认</a></small></div>
  <div class="field"><label for="fStartSec">片段起始（秒）</label><input type="number" id="fStartSec" name="start_sec" min="0" max="10800" step="0.1" value="${prev.start_sec!=null?esc(prev.start_sec):''}"></div>
  <div class="field"><label for="fEndSec">片段结束（秒）</label><input type="number" id="fEndSec" name="end_sec" min="0" max="10800" step="0.1" value="${prev.end_sec!=null?esc(prev.end_sec):''}"></div>
</div></div>
</section>
<section class="form-section" aria-labelledby="secGoal"><h3 id="secGoal"><span class="sec-no">2</span>目标与条件<small>同一目标、条件和标准的记录才能放进同一条趋势</small></h3>
<div class="form-row" id="courseGoalPickRow" hidden><div class="field field-wide"><label for="fCourseGoalPick">从本课课程任务目标预填</label><select id="fCourseGoalPick"><option value="">不使用，手工填写</option></select><small>选择已确认的课程任务目标后，自动填入学习目标编号、通过标准与测量条件，可再修改。</small></div></div>
<div class="form-row">
  <div class="field"><label for="fGoalId">学习目标编号 ${star}</label><input type="text" id="fGoalId" name="goal_id" required maxlength="200" value="${esc(prev.goal_id||'')}" list="goalList" placeholder="如 G-ADL-03">${datalistHtml('goalList',prevGoals)}</div>
  <div class="field"><label for="fMeasCtx">测量条件（可比条件） ${star}</label><input type="text" id="fMeasCtx" name="measurement_context" required maxlength="200" value="${esc(prev.measurement_context||'')}" list="ctxList" placeholder="如 独立进餐/勺子/教室">${datalistHtml('ctxList',prevContexts)}</div>
</div>
<div class="form-row">
  <div class="field field-wide"><label for="fCriterion">具体通过标准（6分参考） ${star}</label><textarea id="fCriterion" name="criterion" required maxlength="2000" rows="2">${esc(prev.criterion||'')}</textarea><small>描述可量化、重复测量的行为标准，不要写教学计划。</small></div>
</div>
</section>
<section class="form-section" aria-labelledby="secScore"><h3 id="secScore"><span class="sec-no">3</span>四维评分<small>留空表示本次未观察，不得填写0代替</small></h3>
${suggestionHtml(prev)}
<div class="score-grid">${SCORE_INPUTS.map(x=>scoreCardHtml(prev,x)).join('')}</div>
</section>
<section class="form-section" aria-labelledby="secReview"><h3 id="secReview"><span class="sec-no">4</span>观察次数与复核</h3>
<div class="form-row three">
  <div class="field"><label for="fOpps">提供机会次数 ${star}</label><input type="number" id="fOpps" name="opportunities" min="0" max="9999" step="1" value="${prev.opportunities!=null?esc(prev.opportunities):''}"><small>本课安排的练习机会总数。</small></div>
  <div class="field"><label for="fObs">实际观察次数 ${star}</label><input type="number" id="fObs" name="observed" min="0" max="9999" step="1" value="${prev.observed!=null?esc(prev.observed):''}"><small>教师实际记录的次数，至少${esc(RUBRIC.min_observed)}次才计分。</small></div>
  <div class="field" style="display:flex;align-items:flex-end;gap:10px;padding-bottom:4px"><label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:var(--blue-deep);cursor:pointer"><input type="checkbox" id="fReviewed" name="reviewed" style="width:20px;min-height:20px;flex:none"${prev.reviewed?' checked':''}> 教师已完成复核</label></div>
</div>
<div class="form-row">
  <div class="field field-wide"><label for="fEvidence">观察记录与证据摘要 ${star}</label><textarea id="fEvidence" name="evidence" required maxlength="2000" rows="3">${esc(prev.evidence||'')}</textarea><small>描述具体行为表现，作为评分依据。视频复核请注明片段时间点。</small></div>
</div>
</section>
<div class="form-actions">
  <button type="submit" class="button primary" id="saveBtn">保存记录</button>
  <button type="button" class="button" onclick="switchTab('overview')">取消</button>
</div>
</form>`;
  const srcSel=byId('fSourceType');
  const videoSec=byId('videoSection');
  function toggleVideo(){if(videoSec)videoSec.style.display=isVideoSource(srcSel.value)?'':'none';}
  srcSel.addEventListener('change',toggleVideo);toggleVideo();
  bindScoreCards();
  const applyBtn=byId('applySuggestion');
  if(applyBtn)applyBtn.addEventListener('click',()=>{
    const sg=prev.suggested_scores||{};
    SCORE_INPUTS.forEach(([key,id])=>{const el=byId(id);if(el){el.value=sg[key]==null?'':String(sg[key]);syncScoreCard(id);}});
    if(prev.suggested_opportunities!=null&&byId('fOpps'))byId('fOpps').value=String(prev.suggested_opportunities);
    if(prev.suggested_observed!=null&&byId('fObs'))byId('fObs').value=String(prev.suggested_observed);
    if(formGuard.markDirty)formGuard.markDirty();
    msg('已填入系统建议分。请逐项对照视频片段核对或修改，确认后勾选「教师已完成复核」再保存。','info');
  });
  fillCourseGoalPick();
  const goalPick=byId('fCourseGoalPick');if(goalPick)goalPick.addEventListener('change',applyCourseGoalPick);
  byId('measForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(state.saving)return;
    const errEl=byId('formErr');errEl.className='form-error';errEl.textContent='';
    function fail(text,focusId){errEl.textContent=text;errEl.className='form-error visible';const f=focusId&&byId(focusId);if(f)f.focus();else errEl.scrollIntoView({block:'center'});}
    const fd=new FormData(e.target);
    function fv(n){const v=fd.get(n);return typeof v==='string'?v.trim():v;}
    function fnum(n){const v=fv(n);return v===''||v==null?null:parseFloat(v);}
    function fint(n){const v=fv(n);return v===''||v==null?null:parseInt(v,10);}
    const lessonDate=fv('lesson_date');
    if(!lessonDate){fail('请选择上课日期。','fLessonDate');return;}
    const today=localToday();
    if(lessonDate>today){fail('上课日期不能是未来日期。','fLessonDate');return;}
    const lessonId=fv('lesson_id');
    if(!lessonId){fail('请填写课节编号。','fLessonId');return;}
    const sourceType=fv('source_type');if(!sourceType){fail('请选择数据来源。','fSourceType');return;}
    const goalId=fv('goal_id');if(!goalId){fail('请填写学习目标编号。','fGoalId');return;}
    const measCtx=fv('measurement_context');if(!measCtx){fail('请填写测量条件。','fMeasCtx');return;}
    const criterion=fv('criterion');if(!criterion){fail('请填写通过标准。','fCriterion');return;}
    // Empty inputs stay null (未观察), never 0.
    const scores={accuracy:fnum('acc'),independence:fnum('ind'),consistency:fnum('con'),transfer:fnum('trf')};
    const inputIds={accuracy:'fAcc',independence:'fInd',consistency:'fCon',transfer:'fTrf'};
    for(const[k,v]of Object.entries(scores)){if(v!=null&&(!isFinite(v)||v<0||v>10)){fail(`${DIM_LABELS[k]}分数须在0到10之间。`,inputIds[k]);return;}}
    for(const[k,id]of Object.entries(inputIds)){const el=byId(id);if(el&&el.validity&&el.validity.badInput){fail(`${DIM_LABELS[k]}分数格式无效，请填写数字或留空。`,id);return;}}
    const opportunities=fint('opportunities'),observed=fint('observed');
    if(opportunities==null||opportunities<0){fail('请填写提供机会次数（非负整数）。','fOpps');return;}
    if(observed==null||observed<0){fail('请填写实际观察次数（非负整数）。','fObs');return;}
    if(observed>opportunities){fail('实际观察次数不能大于提供机会次数。','fObs');return;}
    const evidence=fv('evidence');if(!evidence){fail('请填写观察记录与证据摘要（评分依据）。','fEvidence');return;}
    const payload={
      record_id:isEdit?prev.record_id:crypto.randomUUID(),
      expected_version:isEdit?prev.version:0,
      student_id:sid,lesson_date:lessonDate,lesson_id:lessonId,
      course_name:fv('course_name')||lessonId,
      goal_id:goalId,measurement_context:measCtx,criterion,
      scores,
      opportunities,observed,
      reviewed:byId('fReviewed').checked,
      evidence,
      source_type:sourceType,
      task_id:isVideoSource(sourceType)?fv('task_id'):undefined,
      start_sec:isVideoSource(sourceType)?fnum('start_sec'):undefined,
      end_sec:isVideoSource(sourceType)?fnum('end_sec'):undefined,
    };
    if(!isVideoSource(sourceType)){delete payload.task_id;delete payload.start_sec;delete payload.end_sec;}
    state.saving=true;
    const btn=byId('saveBtn');if(btn)btn.disabled=true;
    try{
      const d=await api(API+'/measurements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const saved=d.record;
      if(!(await reloadWorkspaceData())){
        if(isEdit){const idx=state.records.findIndex(r=>r.record_id===saved.record_id);if(idx>=0)state.records[idx]=saved;else state.records.push(saved);}
        else state.records.push(saved);
      }
      formGuard.clean();
      renderSidebar();
      const savedText=d.archive_sync?.status==='pending_retry'?'记录已保存，学生档案同步稍后自动重试。':'记录已保存。';
      msg(savedText,'success');okToast(isEdit?'测量记录已更新':'测量记录已保存');switchTab('overview');
    }catch(e){
      const taskQ=encodeURIComponent(payload.task_id||'');
      if(e.code==='applicability_required'){errEl.innerHTML=`${errHtml(e)} <a href="/demo2/analysis?task_id=${taskQ}">去分析页确认</a>`;}
      else if((e.serverMessage||e.message||'').includes('身份')){errEl.innerHTML=`${esc(e.serverMessage||e.message)} <a href="/demo2/identity?task_id=${taskQ}">去确认身份</a>`;}
      else errEl.innerHTML=errHtml(e);
      errEl.className='form-error visible';
    }finally{state.saving=false;if(btn)btn.disabled=false;}
  });
}

async function editRecord(recordId){
  const r=state.records.find(x=>x.record_id===recordId);
  if(!r){msg('记录未找到。');return;}
  state.selectedId=r.student_id;if(measureSwitch)measureSwitch.select(r.student_id,{trigger:'init'});
  document.querySelectorAll('.student-item').forEach(el=>el.classList.toggle('active',el.dataset.id===r.student_id));
  switchTab('form');
  state.formRecordId=recordId;
  let rec=r;
  if(r.source_type==='video'){
    // Latest prefill (course goal, IEP support, video indicators); falls back to the workspace copy.
    try{const d=await api(API+'/measurements/prefill?record_id='+encodeURIComponent(recordId));if(d.record)rec={...r,...d.record};}
    catch(e){console.warn('[measurement] prefill_failed',e&&e.code);}
  }
  renderForm(rec);
}
function openReport(recordId){
  const r=state.records.find(x=>x.record_id===recordId);if(!r)return;
  state.selectedId=r.student_id;if(measureSwitch)measureSwitch.select(r.student_id,{trigger:'init'});
  document.querySelectorAll('.student-item').forEach(el=>el.classList.toggle('active',el.dataset.id===r.student_id));
  const pane=byId('paneReport');if(pane)pane._selId=recordId;
  switchTab('report',true);
}

async function promptWithdraw(recordId,version){
  const rec=state.records.find(r=>r.record_id===recordId);
  const label=rec?`${fmtDate(rec.lesson_date)} · ${rec.course_name||rec.lesson_id||''}`:'这条记录';
  const reason=await askReason({title:'撤销这条测量记录？',message:`将撤销「${label}」的测量记录。`,
    consequences:['撤销后该记录不再计入趋势、单次报告和学生档案。','撤销原因会写入审计日志，此操作不能在页面上恢复。'],
    confirmLabel:'确认撤销',cancelLabel:'取消',input:{label:'撤销原因',required:true,maxLength:500,example:'例如：录入了错误的课节'}});
  if(!reason)return;
  try{
    await api(API+'/measurements/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({record_id:recordId,expected_version:version,reason})});
    if(!(await reloadWorkspaceData()))state.records=state.records.filter(r=>r.record_id!==recordId);
    renderSidebar();
    msg('记录已撤销。','success');okToast('测量记录已撤销');switchTab('overview');
  }catch(e){errMsg(e);}
}

function scoredLessonCount(t){const l=t&&t.series&&Array.isArray(t.series.lesson)?t.series.lesson:[];return l.filter(p=>p&&p.score!=null).length;}

function trendEmptyHtml(detail,info){
  console.info('[measurement] trend_insufficient '+JSON.stringify(info));
  return `<div class="rx-empty trend-empty" id="trendEmpty" data-trend-empty="1"><p><strong>至少需要 2 次已复核记录才能看趋势</strong></p><small>${esc(detail)}</small><button class="button primary" onclick="switchTab('form')">+ 新增测量记录</button></div>`;
}

function renderTrends(){
  const pane=byId('paneTrends');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML=noStudentHtml('请从左侧选择学生。');return;}
  const studentTrends=state.trends.filter(t=>t.student_id===sid);
  const best=studentTrends.reduce((m,t)=>Math.max(m,scoredLessonCount(t)),0);
  const pendingVideo=studentRecords(sid).filter(isPendingVideo);
  const head=`<h2 class="pane-title">纵向趋势 — ${esc(studentName(sid))}</h2><p class="pane-sub">比较同一目标、同一测量条件下多次课的综合得分变化；已复核的视频来源记录与现场观察记录按同目标、条件、标准合并绘图。</p>`
    +(pendingVideo.length?`<div class="pending-video" id="trendPendingVideo"><h4>本学生有 ${pendingVideo.length} 条课堂视频记录${SUGGEST_LABEL}（不计入得分线，图中以空心点显示）</h4><ul>${pendingVideo.map(r=>`<li>${esc(fmtDate(r.lesson_date))} · ${esc(r.goal_id)} / ${esc(r.measurement_context)} · 建议：${esc(suggestedText(r.suggested_scores))} <button class="button rec-btn" onclick="editRecord(${esc(JSON.stringify(r.record_id))})">去复核</button></li>`).join('')}</ul></div>`:'');
  if(!studentTrends.length||best<TREND_MIN_POINTS){
    pane.innerHTML=head+trendEmptyHtml(`目前已复核且有综合得分的记录：${best} 次。同一目标、条件与通过标准下累计 2 次后即可显示趋势图。`,{student_id:sid,trend_groups:studentTrends.length,scored_points:best,required:TREND_MIN_POINTS,scope:'student'});
    return;
  }
  let selIndex=typeof pane._selIndex==='number'?pane._selIndex:-1;
  if(selIndex<0||selIndex>=studentTrends.length||pane._selStudent!==sid){
    selIndex=studentTrends.findIndex(t=>scoredLessonCount(t)>=TREND_MIN_POINTS);if(selIndex<0)selIndex=0;
  }
  const t=studentTrends[selIndex];
  const seriesKeys=['lesson','week','month','rolling_60_days'].filter(k=>t.series&&k in t.series);
  let selSeries=pane._selSeries||seriesKeys[0]||'lesson';
  if(!seriesKeys.includes(selSeries))selSeries=seriesKeys[0]||'lesson';
  const SERIES_LABELS={lesson:'逐课',week:'周汇总',month:'月汇总',rolling_60_days:'60天滚动'};
  const trendOpts=studentTrends.map((tr,i)=>`<option value="${i}"${i===selIndex?' selected':''}>${esc(tr.goal_id)} / ${esc(tr.measurement_context)}（已复核 ${scoredLessonCount(tr)} 次）</option>`).join('');
  const seriesOpts=seriesKeys.map(k=>`<option value="${k}"${k===selSeries?' selected':''}>${SERIES_LABELS[k]||k}</option>`).join('');
  pane.innerHTML=`${head}
<div class="trend-card">
<div class="trend-controls">
  <div class="field" style="min-width:260px;max-width:440px;flex:1"><label for="trendSel" style="font-size:12px">目标 / 条件</label>
    <select id="trendSel">${trendOpts}</select></div>
  <div class="field"><label for="seriesSel" style="font-size:12px">粒度</label>
    <select id="seriesSel">${seriesOpts}</select></div>
</div>
<p class="trend-meta">标准：${esc(t.criterion||'—')}　量表版本：${esc(t.rubric_version||'—')}</p>
<p class="trend-warn">仅相同目标、条件、标准及量表版本的记录可比较；混合不同版本数据无意义。</p>
<div class="chart-wrap" id="chartWrap"></div>
<div class="chart-legend" id="chartLegend"></div>
<p class="chart-note" id="chartNote"></p>
<details style="margin-top:14px"><summary style="font-size:13px;cursor:pointer;color:var(--blue)">无障碍数据表格</summary>
<div class="table-wrap" style="margin-top:8px" id="trendTable"></div></details>
</div>`;
  pane._selIndex=selIndex;pane._selSeries=selSeries;pane._selStudent=sid;
  byId('trendSel').addEventListener('change',e=>{pane._selIndex=parseInt(e.target.value,10);renderTrends();});
  byId('seriesSel').addEventListener('change',e=>{pane._selSeries=e.target.value;renderTrends();});
  const rawPts=t.series[selSeries];
  const pts=selSeries==='rolling_60_days'
    ? (Array.isArray(rawPts)?rawPts:(rawPts&&typeof rawPts==='object'?[rawPts]:[]))
    : (Array.isArray(rawPts)?rawPts:[]);
  renderTrendTable(byId('trendTable'),pts,selSeries);
  const groupScored=scoredLessonCount(t);
  if(groupScored<TREND_MIN_POINTS){
    byId('chartWrap').innerHTML=trendEmptyHtml(`当前目标/条件下已复核且有综合得分的记录：${groupScored} 次，请切换到其他目标或继续记录。`,{student_id:sid,goal_index:selIndex,scored_points:groupScored,required:TREND_MIN_POINTS,scope:'goal'});
    byId('chartWrap').style.minHeight='0';
    return;
  }
  renderTrendChart(byId('chartWrap'),byId('chartLegend'),byId('chartNote'),pts,selSeries);
}

function pointLabel(p,seriesKey){
  if(seriesKey==='lesson')return (p.date||'').slice(5).replace('-','/');
  if(seriesKey==='rolling_60_days')return `${(p.from||'').slice(5)}~${(p.to||'').slice(5)}`;
  if(seriesKey==='week'){const m=/W(\d+)$/.exec(p.period||'');return m?`第${Number(m[1])}周`:(p.period||'');}
  return p.period||'';
}

function renderTrendTable(tableWrap,pts,seriesKey){
  if(!tableWrap)return;
  if(!pts.length){tableWrap.innerHTML='<p class="pane-muted">本粒度暂无数据。</p>';return;}
  const rows=pts.map(p=>{
    const when=seriesKey==='lesson'?p.date||'—':seriesKey==='rolling_60_days'?`${p.from||''}~${p.to||''}`:p.period||'—';
    const sessions=p.sessions!=null?p.sessions:(seriesKey==='lesson'?(p.score!=null?1:0):'—');
    return `<tr><td>${esc(when)}</td><td>${p.score!=null?fmtScore(p.score):'（未评分）'}</td><td>${p.score!=null?'已复核':'未复核或'+esc(EVIDENCE_INSUFFICIENT)}</td><td>${esc(sessions)}</td></tr>`;
  }).join('');
  tableWrap.innerHTML=`<table><thead><tr><th>${seriesKey==='lesson'?'日期':seriesKey==='rolling_60_days'?'区间':'周期'}</th><th>综合得分</th><th>状态</th><th>计分课次</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderTrendChart(wrap,legend,note,pts,seriesKey){
  if(!wrap)return;
  if(!pts.length){wrap.innerHTML='<p class="pane-muted">本粒度暂无数据。</p>';wrap.style.minHeight='0';return;}
  const hasScore=pts.some(p=>p.score!=null);
  if(!hasScore){wrap.innerHTML='<p class="pane-muted">本段无已复核综合得分。评分需教师复核且满足量表最低条件。</p>';wrap.style.minHeight='0';return;}
  wrap.style.minHeight='';
  const measured=Math.round(wrap.getBoundingClientRect().width||wrap.clientWidth||0);
  const W=Math.max(320,measured||720),H=300,PL=48,PR=24,PT=26,PB=pts.length>8?62:46;
  const IW=W-PL-PR,IH=H-PT-PB;
  const n=pts.length;
  const XPAD=Math.min(36,IW/8);
  const xAt=i=>PL+(n>1?(XPAD+i*(IW-2*XPAD)/(n-1)):IW/2);
  const yAt=v=>PT+IH-(Math.min(SCALE_MAX,Math.max(0,v))/SCALE_MAX)*IH;
  const labels=pts.map(p=>pointLabel(p,seriesKey));
  const grid=[0,2,4,6,8,10].filter(v=>v<=SCALE_MAX).map(v=>{const y=yAt(v).toFixed(1);return `<line x1="${PL}" y1="${y}" x2="${W-PR}" y2="${y}" stroke="${CHART_GRID}" stroke-width="1"/><text x="${PL-8}" y="${(Number(y)+4).toFixed(1)}" text-anchor="end" font-size="12" fill="${CHART_MUTED}">${v}</text>`;}).join('');
  const axes=`<line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PT+IH}" stroke="#9fb3cc" stroke-width="1.2"/><line x1="${PL}" y1="${PT+IH}" x2="${W-PR}" y2="${PT+IH}" stroke="#9fb3cc" stroke-width="1.2"/><text transform="translate(14 ${(PT+IH/2).toFixed(1)}) rotate(-90)" text-anchor="middle" font-size="12" fill="${CHART_MUTED}">综合得分（0–${SCALE_MAX}）</text>`;
  const passY=yAt(PASS_SCORE).toFixed(1);
  const passLine=`<line x1="${PL}" y1="${passY}" x2="${W-PR}" y2="${passY}" stroke="${CHART_PASS}" stroke-width="1.6" stroke-dasharray="6 4"/><text x="${W-PR}" y="${(Number(passY)-6).toFixed(1)}" text-anchor="end" font-size="11" fill="#a86a06">参考合格线 ${PASS_SCORE}分（试行）</text>`;
  let solid='',gaps='',dots='',hollow='';
  let lastScored=-1;
  pts.forEach((p,i)=>{
    const x=xAt(i).toFixed(1);
    if(p.score==null){
      const src=p.record_id?state.records.find(r=>r.record_id===p.record_id):null;
      const tip=isPendingVideo(src)?`课堂视频记录，${SUGGEST_LABEL}（${suggestedText(src.suggested_scores)}），不计入得分线`:`未复核或${EVIDENCE_INSUFFICIENT}（不按0分）`;
      hollow+=`<line x1="${x}" y1="${PT}" x2="${x}" y2="${(PT+IH).toFixed(1)}" stroke="${CHART_HOLLOW}" stroke-width="1" stroke-dasharray="2 4" opacity=".6"/><circle cx="${x}" cy="${(PT+IH-10).toFixed(1)}" r="6" fill="#fff" stroke="${isPendingVideo(src)?'#d48a10':CHART_HOLLOW}" stroke-width="2" stroke-dasharray="3 2"><title>${esc(labels[i])}：${esc(tip)}</title></circle>`;
      return;
    }
    const y=yAt(p.score).toFixed(1);
    if(lastScored>=0){
      const px=xAt(lastScored).toFixed(1),py=yAt(pts[lastScored].score).toFixed(1);
      const seg=`M${px},${py} L${x},${y}`;
      if(lastScored===i-1)solid+=seg+' ';else gaps+=seg+' ';
    }
    lastScored=i;
    dots+=`<circle cx="${x}" cy="${y}" r="6" fill="${CHART_BLUE}" stroke="#fff" stroke-width="2"><title>${esc(labels[i])} 综合得分 ${fmtScore(p.score)}</title></circle><text x="${x}" y="${(Number(y)-12).toFixed(1)}" text-anchor="middle" font-size="12" font-weight="700" fill="#123b70">${fmtScore(p.score)}</text>`;
  });
  const step=n>12?Math.ceil(n/12):1;
  const rotate=n>8;
  const xTicks=pts.map((p,i)=>{
    if(i%step!==0&&i!==n-1)return '';
    const x=xAt(i).toFixed(1),y=(PT+IH+18).toFixed(1);
    return rotate
      ?`<text x="${x}" y="${y}" text-anchor="end" font-size="11" fill="${CHART_MUTED}" transform="rotate(-35 ${x} ${y})">${esc(labels[i])}</text>`
      :`<text x="${x}" y="${y}" text-anchor="middle" font-size="12" fill="${CHART_MUTED}">${esc(labels[i])}</text>`;
  }).join('');
  wrap.innerHTML=`<svg class="chart-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="纵向综合得分趋势图，共${n}个时间点">
<title>纵向趋势</title>${grid}${axes}${passLine}
${gaps?`<path d="${gaps.trim()}" fill="none" stroke="#7aa2db" stroke-width="2" stroke-dasharray="5 5"/>`:''}
${solid?`<path d="${solid.trim()}" fill="none" stroke="${CHART_BLUE}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`:''}
${hollow}${dots}${xTicks}
</svg>`;
  const nonNull=pts.filter(p=>p.score!=null).length;
  if(legend)legend.innerHTML=`<span class="lg"><span class="lg-line"></span><span class="lg-dot"></span>综合得分（已复核）</span><span class="lg"><span class="lg-hollow"></span>未复核 / ${esc(EVIDENCE_INSUFFICIENT)}（不按0分）</span><span class="lg"><span class="lg-gap"></span>跨越空缺的连线</span><span class="lg"><span class="lg-pass"></span>参考合格线（试行）</span>`;
  if(note)note.textContent=`共${n}个时间点，其中${nonNull}个有已复核得分；空心点表示该时间点未达到评分条件或尚未复核，非得分为零。`;
}

function renderReport(recordId){
  const pane=byId('paneReport');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML=noStudentHtml('请从左侧选择学生。');return;}
  const iepState=studentInfo(sid)?.iep_status||'unavailable';
  if(iepState!=='available'){
    const label=iepState==='not_found'?'尚未上传 IEP':iepState==='ambiguous'?'存在多份有效 IEP':'IEP 不可用';
    pane.innerHTML=`<h2 class="pane-title">${esc(studentName(sid))} · 单次记录报告</h2><div class="iep-banner warn" style="margin-top:14px"><strong>${esc(label)}</strong><span>正式报告必须关联学生当前有效的 IEP。请先完成授权和 IEP 上传，再生成报告。</span><a class="button quiet" href="/demo2/dossier?student_id=${encodeURIComponent(sid)}">去管理 IEP</a></div><button class="button" onclick="switchTab('overview')">返回总览</button>`;return;
  }
  const recs=studentRecords(sid).filter(r=>formalScore(r.assessment)!=null||r.source_type==='video');
  if(!recs.length){pane.innerHTML=`<h2 class="pane-title">${esc(studentName(sid))} · 单次记录报告</h2><div class="rx-empty" style="margin-top:14px"><p>该学生暂无已复核且有综合得分的记录，无法生成报告。</p><button class="button" onclick="switchTab('overview')">返回总览</button></div>`;return;}
  let selId=recordId||pane._selId||recs[recs.length-1].record_id;
  if(!recs.find(r=>r.record_id===selId))selId=recs[recs.length-1].record_id;
  pane._selId=selId;
  const r=recs.find(x=>x.record_id===selId);
  const recOpts=recs.slice().reverse().map(x=>`<option value="${esc(x.record_id)}"${x.record_id===selId?' selected':''}>${esc(fmtDate(x.lesson_date))} ${esc(x.goal_id)}${isPendingVideo(x)?' · '+SUGGEST_LABEL:x.source_type==='video'?' · 视频':''}</option>`).join('');
  const asmnt=r.assessment||{};
  const dims=asmnt.dimensions||{};
  const overallScore=formalScore(asmnt);
  const passed=asmnt.passed;
  const scaledMax=asmnt.scale?.max||SCALE_MAX;
  const insufficientEvidence=asmnt.evidence_status===EVIDENCE_INSUFFICIENT||overallScore==null;
  function dimBar(key){
    const d=dims[key];
    if(!d||d.score==null)return`<div class="score-bar-row"><span class="score-bar-label">${esc(DIM_LABELS[key]||key)}</span><div class="score-bar-track"></div><span class="score-bar-empty">未观察 <small>(${esc(DIM_WEIGHTS[key]||'')})</small></span></div>`;
    const pct=Math.min(100,Math.max(0,(d.score/scaledMax)*100));
    return`<div class="score-bar-row"><span class="score-bar-label">${esc(DIM_LABELS[key]||key)}</span><div class="score-bar-track" role="img" aria-label="${esc(DIM_LABELS[key]||key)} ${esc(fmtNum(d.score))} 分"><div class="score-bar-fill" style="width:${pct.toFixed(1)}%"></div></div><span class="score-bar-val">${esc(fmtNum(d.score))} 分<small>(${esc(DIM_WEIGHTS[key]||'')})</small> ${basisBtn(r.record_id,key,'依据')}</span></div>`;
  }
  let scoreBlock='';
  if(isPendingVideo(r)){scoreBlock=`<div class="notice-pilot" id="reportPendingReview"><span class="suggest-tag">${SUGGEST_LABEL}</span> 本记录由课堂视频系统生成，教师复核前不生成综合得分、不进入趋势得分线和课堂报告综合分。系统建议：${esc(suggestedText(r.suggested_scores))}。</div><p style="margin:8px 0 0"><button class="button" onclick="editRecord(${esc(JSON.stringify(r.record_id))})">去补全并复核</button></p>`;}
  else if(insufficientEvidence){scoreBlock=`<div class="notice-pilot" style="border-color:var(--warning)">${esc(EVIDENCE_INSUFFICIENT)}：${esc((asmnt.evidence_reasons||[]).join('；')||'未达到最低评分条件')}。不生成综合得分，避免基于不充分证据给出数字。</div>`;}
  else{
    const passTag=passed===true?'<span class="pass-tag ok">达到参考合格线</span>':passed===false?'<span class="pass-tag no">未达参考合格线</span>':'';
    scoreBlock=`<div class="report-score"><span class="big" id="reportOverall">${fmtScore(overallScore)}</span><span class="of">/ ${esc(scaledMax)}分</span>${passTag}${basisBtn(r.record_id,'','查看依据')}</div>`;
  }
  if(insufficientEvidence&&!isPendingVideo(r))scoreBlock+=`<p style="margin:8px 0 0">${basisBtn(r.record_id,'','查看未计分原因')}</p>`;
  scoreBlock+=basisSummary(r);
  const histTrend=state.trends.find(t=>t.student_id===sid&&t.goal_id===r.goal_id&&t.measurement_context===r.measurement_context&&t.criterion===r.criterion&&t.rubric_version===r.rubric_version);
  const histPts=histTrend?(histTrend.series.lesson||[]):[];
  const histScored=histPts.filter(p=>p.score!=null).length;
  const firstSeg=(r.evidence_segments||[])[0];
  const sourceLink=r.source_type==='video'&&r.task_id?`<a href="${esc(firstSeg?segUrl(r,firstSeg):'/demo2/video?id='+encodeURIComponent(r.task_id))}" style="color:var(--blue);font-size:13px">数据来源：课堂视频（系统生成）· 查看视频片段</a>`:r.source_type==='video_review'&&r.task_id?`<a href="/demo2/video?id=${encodeURIComponent(r.task_id)}&t=${esc(r.start_sec||0)}" style="color:var(--blue);font-size:13px">查看视频片段 (${esc(r.start_sec||0)}s – ${esc(r.end_sec||'')}s)</a>`:'<span style="color:var(--muted);font-size:13px">数据来源：现场课堂观察</span>';
  pane.innerHTML=`
<div class="report-head">
  <h2 class="pane-title">${esc(studentName(sid))} · 单次记录报告</h2>
  <div class="report-actions">
    <select id="reportSel" aria-label="选择记录">${recOpts}</select>
    <button class="button primary" id="reportDocx" style="font-size:12px;min-height:36px" onclick="downloadReportFile('docx')"${isPendingVideo(r)?' title="待复核记录的报告只含系统建议分"':''}>下载 Word</button>
    <button class="button primary" id="reportPdf" style="font-size:12px;min-height:36px" onclick="downloadReportFile('pdf')">下载 PDF</button>
    <button class="button" style="font-size:12px;min-height:36px" onclick="printReport()">打印</button>
    <button class="button" style="font-size:12px;min-height:36px" onclick="downloadReport()" title="网页存档，供技术人员留档">导出 HTML</button>
  </div>
</div>
<p class="report-dl-notice" id="reportDlNotice" role="status" aria-live="polite" hidden></p>
<div id="reportContent">
<div class="card report-card"><div class="card-body">
  <div class="report-info">
    <div><span>日期：</span>${esc(fmtDate(r.lesson_date))}</div>
    <div><span>课节：</span>${esc(r.lesson_id)}</div>
    <div><span>课程：</span>${esc(r.course_name||'—')}</div>
    <div><span>目标：</span>${esc(r.goal_id)}</div>
    <div><span>条件：</span>${esc(r.measurement_context)}</div>
    <div><span>来源：</span>${esc(sourceLabel(r))}</div>
    <div><span>复核状态：</span>${reviewTagHtml(r)}</div>
    <div><span>机会次数：</span>${r.opportunities!=null?esc(r.opportunities):'—'}</div>
    <div><span>观察次数：</span>${r.observed!=null?esc(r.observed):'—'}</div>
  </div>
  <p style="font-size:13px;color:var(--muted);margin:0 0 4px">通过标准：</p>
  <p class="report-criterion">${esc(r.criterion||'—')}</p>
</div></div>
<div class="card report-card"><div class="card-body">
  <h3>综合评分</h3>
  ${scoreBlock}
  <div class="score-bar-wrap">${DIM_KEYS.map(dimBar).join('')}</div>
  <p class="report-note">准确性35%·独立性30%·一致性20%·泛化性15%为试行设计权重，尚待校方确认。6分参考合格线不具法定效力。评分由教师人工依照量表复核，视频处理不自动给分。</p>
  <div style="margin-top:10px">${sourceLink}</div>
</div></div>
${r.source_type==='video'?`<div class="card report-card"><div class="card-body">${videoLinkInfoHtml(r,'本课目标、IEP 支持条件与视频证据')}</div></div>`:''}
${r.evidence?`<div class="card report-card"><div class="card-body"><h3>观察记录摘要</h3><p style="font-size:13px;white-space:pre-wrap;word-break:break-word;margin:0">${esc(r.evidence)}</p></div></div>`:''}
${histPts.length>1?`<div class="card report-card"><div class="card-body"><h3>历史趋势（同目标/条件/标准）</h3>${histScored>=TREND_MIN_POINTS?'<div class="chart-wrap" id="reportChart"></div><div class="chart-legend" id="reportLegend"></div><p class="chart-note" id="reportNote"></p>':'<p class="pane-muted" id="reportChartEmpty">至少需要 2 次已复核记录才能看趋势</p>'}<p style="font-size:11px;color:var(--muted);margin-top:6px">仅相同目标、测量条件、通过标准及量表版本的记录参与比较。空缺表示该课次未达评分条件或未复核，非得分为零。</p></div></div>`:''}
<div class="card report-card"><div class="card-body">
  <h3>评分说明</h3>
  <p class="report-text">本报告呈现教师逐课手工记录数据，经教师依量表复核后生成综合得分。量表采用10分制，6分为试行参考合格线。四个维度为：准确性（目标行为完成正确率）、独立性（完成行为所需提示级别）、一致性（在相同条件下重复出现的稳定程度）、泛化性（在新材料或新场景中是否出现，少于2次观察机会时应留空而非填0）。各维度权重为试行参考，尚待校方结合实际数据校准，不应引用为官方验证结论。本次得分仅反映所记录课次的表现，不代表该学生的整体能力评价；跨课比较需保持相同目标、条件与通过标准，混合不同测量条件的数据不具可比性。视频处理系统不自动给分，所有得分均由教师人工判断后填写。</p>
  <p class="report-foot">量表版本：${esc(r.rubric_version||'—')}　更新时间：${esc(r.updated_at||'—')}</p>
</div></div>
</div>`;
  byId('reportSel').addEventListener('change',e=>{pane._selId=e.target.value;renderReport(e.target.value);});
  if(histPts.length>1&&histScored>=TREND_MIN_POINTS){
    renderTrendChart(byId('reportChart'),byId('reportLegend'),byId('reportNote'),histPts,'lesson');
  }else if(histPts.length>1){
    console.info('[measurement] trend_insufficient '+JSON.stringify({student_id:sid,record_id:r.record_id,scored_points:histScored,required:TREND_MIN_POINTS,scope:'report'}));
  }
}

function printReport(){window.print();}

// Word/PDF 由服务端按同一条记录生成（与本页单次报告内容一致），中文文件名取自 Content-Disposition。
async function downloadReportFile(fmt){
  const pane=byId('paneReport');const recordId=pane&&pane._selId;if(!recordId)return;
  const button=byId(fmt==='pdf'?'reportPdf':'reportDocx');const notice=byId('reportDlNotice');
  if(button&&button.getAttribute('aria-busy')==='true')return;
  const label=button?button.textContent:'';
  if(button){button.setAttribute('aria-busy','true');button.textContent='正在生成…';}
  if(notice){notice.hidden=true;notice.className='report-dl-notice';}
  try{
    const r=await fetch('/api/v1/demo2/measurements/report/download?record_id='+encodeURIComponent(recordId)+'&fmt='+fmt,{cache:'no-store',credentials:'same-origin'});
    if(!r.ok){
      const j=await r.json().catch(()=>({}));const code=j.error&&j.error.code;
      const text=code==='report_renderer_unavailable'&&fmt==='pdf'?'PDF 报告暂时无法生成（服务器未安装 PDF 组件），请改用「下载 Word」，Word / WPS 打开后也可另存为 PDF。':((window.RxUI&&window.RxUI.errorText)?window.RxUI.errorText(r.status,code,j.error&&j.error.message):((j.error&&j.error.message)||'报告下载失败，请稍后重试'));
      if(notice){notice.textContent=text;notice.hidden=false;notice.className='report-dl-notice warn';}
      if(code==='report_renderer_unavailable'&&fmt==='pdf'){const w=byId('reportDocx');if(w)w.focus();}
      return;
    }
    const disposition=r.headers.get('Content-Disposition')||'';const star=/filename\*=UTF-8''([^;]+)/i.exec(disposition);
    let name='measurement_report.'+fmt;if(star){try{name=decodeURIComponent(star[1].trim());}catch(e){name='measurement_report.'+fmt;}}
    const blob=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();
    setTimeout(()=>URL.revokeObjectURL(a.href),2000);
    if(notice){notice.textContent='已下载「'+name+'」';notice.hidden=false;notice.className='report-dl-notice ok';}
  }catch(e){
    if(notice){notice.textContent='网络异常，报告未能下载，请稍后重试';notice.hidden=false;notice.className='report-dl-notice warn';}
  }finally{
    if(button){button.removeAttribute('aria-busy');button.textContent=label;}
  }
}

const REPORT_EXPORT_CSS=':root{--muted:#5b6b80;--blue:#1f63c6;--warning:#9a5a08}body{font-family:"Microsoft YaHei UI","PingFang SC","Segoe UI",sans-serif;font-size:14px;line-height:1.6;color:#172b4d;max-width:860px;margin:auto;padding:24px}h2,h3{color:#123b70;margin:0 0 10px}.card{border:1px solid #cfdcea;border-radius:8px;padding:16px;margin-bottom:16px}.report-info{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px 16px;font-size:13px;margin-bottom:12px}.report-info span{color:#5b6b80}.report-criterion{font-size:13px;border-left:3px solid #1f63c6;padding-left:10px;margin:0}.report-score{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px 14px}.report-score .big{font-size:56px;font-weight:800;color:#123b70;line-height:1}.report-score .of{color:#5b6b80}.pass-tag{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700}.pass-tag.ok{background:#eaf7f2;color:#0d6042}.pass-tag.no{background:#fff5e3;color:#7b4708}.score-bar-wrap{margin-top:14px;display:grid;gap:10px}.score-bar-row{display:grid;grid-template-columns:64px 1fr 110px;align-items:center;gap:10px;font-size:13px}.score-bar-track{height:14px;border-radius:7px;background:#e6edf5;overflow:hidden}.score-bar-fill{height:100%;border-radius:7px;background:#1f63c6;-webkit-print-color-adjust:exact;print-color-adjust:exact}.score-bar-val{font-weight:700}.score-bar-val small,.score-bar-empty small{color:#5b6b80;font-weight:400;margin-left:4px}.score-bar-empty{color:#8a96a8;font-size:12px}.report-note{font-size:12px;color:#9a5a08}.report-text{font-size:13px;line-height:1.8;color:#3d526d}.report-foot{font-size:11px;color:#5b6b80}.notice-pilot{padding:8px 12px;border-left:3px solid #9a5a08;background:#fff7e8;color:#9a5a08;font-size:12px;margin:8px 0}.chart-wrap{width:100%}svg.chart-svg{display:block;width:100%;height:auto}.chart-legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12px;color:#5b6b80}.lg{display:inline-flex;align-items:center;gap:6px}.lg-line{display:inline-block;width:18px;border-top:3px solid #1f63c6}.lg-gap{display:inline-block;width:18px;border-top:2px dashed #7aa2db}.lg-pass{display:inline-block;width:18px;border-top:2px dashed #d48a10}.lg-dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#1f63c6}.lg-hollow{display:inline-block;width:10px;height:10px;border-radius:50%;border:2px dashed #8a96a8}.chart-note{font-size:12px;color:#5b6b80}.vlink-card{border:1px solid #cfdcea;border-left:4px solid #1f63c6;border-radius:8px;background:#f7faff;padding:14px 16px;margin:0 0 16px}.vlink-card h3{margin:0 0 8px;color:#123b70;font-size:15px}.vlink-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 18px;font-size:13px;margin:0 0 10px}.vlink-grid div span{color:#5b6b80}.vlink-block{margin:10px 0 0;font-size:13px}.vlink-block>strong{display:block;color:#123b70;margin-bottom:4px}.vlink-block ul{margin:0;padding-left:18px}.vlink-metrics{width:100%;border-collapse:collapse;font-size:12px}.vlink-metrics th,.vlink-metrics td{border:1px solid #dde6f0;padding:4px 8px;text-align:left}.vlink-metrics th{background:#eef4fb}.seg-links{display:flex;flex-wrap:wrap;gap:6px}.seg-link{display:inline-block;padding:3px 9px;border:1px solid #b9cdea;border-radius:8px;color:#1f63c6;font-size:12px;text-decoration:none}.suggest-tag{display:inline-block;padding:1px 8px;border-radius:8px;border:1px dashed #d48a10;color:#9a5a08;background:#fff8ec;font-size:12px;font-weight:700}.review-tag{display:inline-block;padding:1px 8px;border-radius:8px;background:#eaf7f2;color:#0d6042;font-size:12px;font-weight:700}.pane-muted{color:#5b6b80}';

function downloadReport(){
  const sid=state.selectedId;
  const content=byId('reportContent');
  if(!content){return;}
  const sname=esc(studentName(sid||''));
  // Same content as the page/print view; segment links become absolute, action buttons are dropped.
  const origin=(typeof location!=='undefined'&&location.origin)?location.origin:'';
  const body=content.innerHTML.replace(/<button\b[^>]*>[\s\S]*?<\/button>/g,'').replace(/href="\//g,'href="'+origin+'/');
  const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WeGlow微光系统 · 测量报告 ${sname}</title><style>${REPORT_EXPORT_CSS}</style></head><body><p style="margin:0 0 12px;padding-bottom:8px;border-bottom:2px solid #1f5fbf;color:#1f5fbf;font-weight:700">WeGlow微光系统 · 课堂学习分析</p><h2>${sname} · 单次记录报告</h2>${body}<p style="margin-top:24px;padding-top:8px;border-top:1px solid #d3deea;color:#56657a;font-size:12px">由 WeGlow微光系统 导出 · ${new Date().toISOString().slice(0,10)}</p></body></html>`;
  const blob=new Blob([html],{type:'text/html'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=`report_${(sid||'').slice(0,8)}_${new Date().toISOString().slice(0,10)}.html`;
  a.click();URL.revokeObjectURL(a.href);
}

function renderStandard(){
  const pane=byId('paneStandard');if(!pane)return;
  const dimCards=RUBRIC.dimensions.map(d=>`<article class="dim-card" data-dim="${esc(d.key)}"><div class="dim-ring" style="--p:${Number(d.weight_percent)||0}" role="img" aria-label="${esc(d.label)}权重${esc(d.weight_percent)}%"><span>${esc(d.weight_percent)}%</span></div><div><h4>${esc(d.label)}</h4><p>${esc(d.description)}</p></div></article>`).join('');
  const principles=RUBRIC.principles.map(p=>`<li><b>${esc(p.title)}</b><span>${esc(p.text)}</span></li>`).join('');
  const dimNames=RUBRIC.dimensions.map(d=>d.label).join('、');
  const formula=RUBRIC.dimensions.map(d=>`${d.label}×${d.weight.toFixed(2)}`).join(' + ');
  pane.innerHTML=`\
<h2 class="pane-title" style="margin-bottom:12px">评分标准说明</h2>
<div class="pilot-line"><span>试行说明：以下量表为内测期间设计参考，权重与合格线尚待校方基于实际数据确认，不应作为官方验证标准引用或对外传播。</span></div>
<div class="card std-card" id="stdScoring"><div class="card-body">
  <h3>计分方式</h3>
  <p>采用${esc(RUBRIC.scale.max)}分制，${esc(RUBRIC.scale.pass_score)}分为参考合格线（试行）。综合得分由四个维度加权合成，仅在满足最低观察条件且教师已完成复核后生成。</p>
  <div class="dim-cards" id="stdDimCards">${dimCards}</div>
  <p class="std-formula" id="stdFormula">综合得分 = ${esc(formula)}，结果保留${esc(RUBRIC.decimals)}位小数。</p>
</div></div>
<div class="card std-card" id="stdPrinciples"><div class="card-body">
  <h3>评分原则</h3>
  <ul class="point-list">${principles}</ul>
</div></div>
<div class="card std-card" id="stdMinimum"><div class="card-body">
  <h3>最低评分条件</h3>
  <ul class="point-list warn">
    <li><span>教师须勾选"已完成复核"，否则不生成综合得分。</span></li>
    <li><span>${esc(dimNames)}四个维度都须有有效分数（非空）。</span></li>
    <li><span>观察次数至少为${esc(RUBRIC.min_observed)}次（observed &ge; ${esc(RUBRIC.min_observed)}）。</span></li>
    <li><span>不满足上述任一条件，系统标注"${esc(EVIDENCE_INSUFFICIENT)}"，不输出得分数字，不使用置信度作为替代。</span></li>
  </ul>
  <p style="font-size:12px;color:var(--muted);margin-top:10px">如需查看官方相关文献，请联系管理员在后台添加外部链接。</p>
</div></div>
${rubricDetailHtml()}`;
  const printBtn=byId('printRubricBtn');
  if(printBtn)printBtn.addEventListener('click',()=>{document.body.classList.add('rx-print-rubric');window.print();setTimeout(()=>document.body.classList.remove('rx-print-rubric'),400);});
}
function rubricDetailHtml(){
  const dims=RUBRIC.dimensions.map(d=>`<article class="rubric-dim" data-rubric-dim="${esc(d.key)}"><h4>${esc(d.label)}<small>权重 ${esc(d.weight_percent)}% · ${esc(d.description)}</small></h4>
<table class="anchor-table" aria-label="${esc(d.label)}分档锚点"><tbody>${(d.anchors||[]).map(a=>`<tr${Number(a.level)>=PASS_SCORE?' class="pass"':''}><th scope="row">${esc(a.level)} 分</th><td>${esc(a.text)}</td></tr>`).join('')}</tbody></table>
<p class="rd-line"><b>证据要求：</b>${esc(d.evidence||'')}</p>
<p class="rd-line"><b>数据来源：</b><span class="sb-chips">${(d.data_sources||[]).map(x=>`<span class="sb-chip">${esc(x.label)}</span>`).join('')}</span></p>
<p class="rd-line"><b>不计分情形：</b>${(d.not_scored||[]).map(esc).join('；')}。留空表示未观察，不按 0 分处理。</p></article>`).join('');
  const levels=(RUBRIC.score_levels||[]).map(a=>`<tr><th scope="row">${esc(a.level)} 分</th><td>${esc(a.text)}</td></tr>`).join('');
  const support=(RUBRIC.support_levels||[]).filter(x=>x.anchor_level!=null).map(x=>`${esc(x.label)} → ${esc(x.anchor_level)} 档`).join('；');
  return `<div class="card std-card" id="stdAnchors"><div class="card-body">
  <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px"><h3 style="margin:0">评分标准细则</h3><span><span class="rubric-version" id="rubricVersion">量表 ${esc(RUBRIC.rubric_version)} · 细则 ${esc(RUBRIC.detail_version||'')}</span> <button type="button" class="button no-print" id="printRubricBtn" style="min-height:32px;font-size:12px">打印细则</button></span></div>
  <p style="font-size:13px;color:var(--muted)">每个维度按 0/2/4/6/8/10 分档给出可观察的锚点。${esc(RUBRIC.anchor_rule||'')}独立性参考：${support}。每条测量记录都可在「查看依据」中看到命中的锚点、代入数值与证据。</p>
  <table class="anchor-table" aria-label="通用分档含义" id="stdLevels"><tbody>${levels}</tbody></table>
  <div class="rubric-detail" id="stdAnchorDims">${dims}</div>
</div></div>`;
}

// Boot
document.querySelectorAll('.view-tab').forEach(btn=>{
  btn.addEventListener('click',()=>switchTab(btn.dataset.tab,true));
});
const searchBox=byId('studentSearch');
if(searchBox)searchBox.addEventListener('input',()=>{state.filter=searchBox.value;renderSidebar();});
let _resizeTimer=null;
window.addEventListener('resize',()=>{
  clearTimeout(_resizeTimer);
  _resizeTimer=setTimeout(()=>{if(state.currentTab==='trends')renderTrends();else if(state.currentTab==='report')renderReport(null);},180);
});
byId('logoutBtn').addEventListener('click',async()=>{
  try{await api(API+'/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}
  finally{window.location.assign('/demo2/login');}
});
let courseTaskList=null,courseTaskLoading=false;
async function loadCourseTaskList(){
  if(courseTaskLoading)return;courseTaskLoading=true;
  try{const d=await api(API+'/course-tasks');courseTaskList=Array.isArray(d.course_tasks)?d.course_tasks:[];}
  catch(e){courseTaskList=[];console.warn('[measurement] course_task_list_failed',e&&e.code);}
  finally{courseTaskLoading=false;}
  fillCourseGoalPick();
}
function fillCourseGoalPick(){
  const row=byId('courseGoalPickRow'),sel=byId('fCourseGoalPick');if(!row||!sel)return;
  if(courseTaskList===null){loadCourseTaskList();return;}
  if(!courseTaskList.length){row.hidden=true;return;}
  const lesson=(byId('fLessonId')?.value||'').trim();
  const ordered=courseTaskList.map((t,i)=>[t,i]).sort((a,b)=>(b[0].course_id===lesson)-(a[0].course_id===lesson));
  sel.innerHTML='<option value="">不使用，手工填写</option>'+ordered.map(([t,i])=>`<optgroup label="${esc((t.course_name||'未命名课程')+' · '+t.course_id+' · 版本 '+t.version)}">${(t.goals||[]).map((g,j)=>`<option value="${i}:${j}">${esc(g.goal_code+' '+String(g.description||'').slice(0,40))}</option>`).join('')}</optgroup>`).join('');
  row.hidden=false;
}
function applyCourseGoalPick(){
  const sel=byId('fCourseGoalPick');if(!sel||!sel.value||!courseTaskList)return;
  const [i,j]=sel.value.split(':').map(Number);const task=courseTaskList[i],goal=task&&task.goals&&task.goals[j];if(!goal)return;
  const set=(id,value,onlyEmpty)=>{const el=byId(id);if(el&&value&&(!onlyEmpty||!el.value.trim()))el.value=value;};
  set('fGoalId',String(goal.goal_code).slice(0,200));
  set('fCriterion',String(goal.pass_criteria||goal.description||'').slice(0,2000));
  set('fMeasCtx',String(goal.measurement_conditions||'').slice(0,200));
  set('fLessonId',String(task.course_id).slice(0,120),true);
  set('fCourseName',String(task.course_name||'').slice(0,200),true);
  formGuard.markDirty&&formGuard.markDirty();
}
byId('accountName').textContent=ACCT.login_alias||ACCT.username||'教师';
loadWorkspace();
"""
    # _document owns the script element; return JavaScript source only.
    return init + rest


def render_measurement(account: Any = None) -> str:
    account_json = _account_payload(account)
    role = account_role(account)
    if role == "company_admin":
        return _document(
            title="测量记录汇总",
            body=_admin_body(account_json, account),
            page_style=_ADMIN_STYLE,
            script="",
        )
    # school_uploader (or unauthenticated — server should have already 401'd)
    return _document(
        title="测量记录",
        body=_teacher_body_html(account_json, account),
        page_style=_MEAS_STYLE + SCORE_BASIS_CSS,
        script=UI_DRAFT_STORE_JS + SCORE_BASIS_JS + _teacher_script(account_json),
    )
