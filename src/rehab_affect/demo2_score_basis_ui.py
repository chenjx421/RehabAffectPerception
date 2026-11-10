"""「查看依据」drawer shared by the measurement and evaluation pages.

``SCORE_BASIS_CSS`` is appended to the page style and ``SCORE_BASIS_JS`` to the
page's existing script (pages keep their fixed number of ``<script>`` blocks).
The script exposes ``window.ScoreBasis.open(kind, recordId, focus)`` which
reads ``/api/v1/demo2/{measurements|evaluations}/score-basis`` and renders the
formula with substituted numbers, the anchor hit, cited evidence (video time
points link to ``/demo2/video?id=&t=``) and the reasons a score was not given.
"""
from __future__ import annotations

SCORE_BASIS_CSS = """
.rx-drawer.sb-drawer{width:min(620px,100vw)}
.sb-drawer .rx-drawer-close{flex-shrink:0;white-space:nowrap}
.sb-drawer table{min-width:0}
.sb-btn{display:inline-flex;align-items:center;gap:4px;min-height:28px;padding:2px 10px;border:1px solid #b9cdea;border-radius:6px;background:#f5f9ff;color:#1f5fbf;font:inherit;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap}
.sb-btn:hover{background:#e8f1ff}.sb-btn:focus-visible{outline:3px solid rgba(31,95,191,.35);outline-offset:2px}
.sb-btn[disabled]{cursor:not-allowed;opacity:.55}
.sb-status{display:inline-block;padding:2px 10px;border-radius:8px;font-size:12px;font-weight:800}
.sb-status.ok{background:#eaf7f2;color:#0d6042}.sb-status.warn{background:#fff5e3;color:#7b4708}.sb-status.na{background:#eef2f7;color:#4a5b70}
.sb-sec{margin:0 0 18px}.sb-sec h3{margin:0 0 8px;color:#123b70;font-size:15px}
.sb-meta{margin:0 0 12px;color:#5b6b80;font-size:12px;line-height:1.7}
.sb-formula{padding:10px 12px;border-left:3px solid #1f5fbf;background:#f5f9ff;border-radius:6px;font-size:13px;line-height:1.7;word-break:break-word}
.sb-formula code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:#123b70}
.sb-table{width:100%;border-collapse:collapse;font-size:12.5px}
.sb-table th,.sb-table td{border:1px solid #dde6f0;padding:6px 8px;text-align:left;vertical-align:top}
.sb-table th{background:#eef4fb;color:#123b70;white-space:nowrap}.sb-table td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.sb-table tr.sb-focus td{background:#fff8e6}
.sb-table tfoot td{font-weight:800;background:#f7faff}
.sb-match{color:#0d6042;font-weight:800}.sb-mismatch{color:#a23b1d;font-weight:800}
.sb-insufficient{padding:10px 12px;border:1px solid #f0c987;border-left:4px solid #d48a10;border-radius:6px;background:#fff8ec;color:#7b4708;font-size:13px}
.sb-insufficient strong{display:block;margin-bottom:4px}
.sb-insufficient ul{margin:4px 0 0;padding-left:18px}
.sb-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.sb-kv div{padding:8px 10px;border:1px solid #dde6f0;border-radius:6px;background:#fff;font-size:12px;color:#5b6b80}
.sb-kv b{display:block;margin-top:2px;color:#172b4d;font-size:15px}
.sb-refs{display:grid;gap:8px;margin:0;padding:0;list-style:none}
.sb-refs li{padding:8px 10px;border:1px solid #dde6f0;border-radius:6px;font-size:13px;line-height:1.6}
.sb-refs .sb-kind{display:inline-block;margin-right:6px;padding:0 6px;border-radius:6px;background:#eef4fb;color:#1f5fbf;font-size:11px;font-weight:800}
.sb-refs a{color:#1f5fbf;font-weight:700}
.sb-item{border:1px solid #dde6f0;border-radius:8px;margin:0 0 8px;background:#fff}
.sb-item>summary{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:8px 10px;cursor:pointer;font-size:13px}
.sb-item>summary b{flex:1 1 220px;color:#172b4d}
.sb-item[open]>summary{border-bottom:1px solid #e6edf5}
.sb-item.sb-focus{border-color:#d48a10;box-shadow:0 0 0 2px rgba(212,138,16,.18)}
.sb-item-body{padding:10px 12px;font-size:13px;line-height:1.7}
.sb-item-body p{margin:0 0 6px}
.sb-anchor{padding:6px 10px;border-radius:6px;background:#f5f9ff;color:#123b70}
.sb-chips{display:flex;flex-wrap:wrap;gap:4px}
.sb-chip{display:inline-block;padding:1px 8px;border-radius:8px;border:1px solid #cfdcea;background:#fff;font-size:11.5px;color:#3d526d}
.sb-chip.off{border-style:dashed;color:#8a96a8}
.sb-loading{color:#5b6b80;font-size:13px}
.sb-error{color:#a23b1d;font-size:13px}
.sb-actions{display:flex;gap:8px;margin:0 0 14px}
.rubric-detail{display:grid;gap:12px}
.rubric-dim{border:1px solid #dde6f0;border-radius:8px;padding:12px 14px;background:#fff;break-inside:avoid}
.rubric-dim h4{margin:0 0 6px;color:#123b70;font-size:15px}
.rubric-dim h4 small{margin-left:6px;color:#5b6b80;font-size:12px;font-weight:600}
.anchor-table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}
.anchor-table th,.anchor-table td{border:1px solid #dde6f0;padding:5px 8px;text-align:left;vertical-align:top}
.anchor-table th{width:64px;background:#eef4fb;color:#123b70;white-space:nowrap}
.anchor-table tr.pass th{background:#e6f4ee;color:#0d6042}
.rubric-dim .rd-line{margin:4px 0;font-size:12.5px;color:#3d526d}
.rubric-dim .rd-line b{color:#123b70}
.rubric-version{display:inline-block;padding:2px 8px;border-radius:6px;background:#eef4fb;color:#1f5fbf;font-size:12px;font-weight:700}
@media print{
  .sb-drawer,.rx-drawer-backdrop{display:none!important}
  body.rx-print-rubric header,body.rx-print-rubric .ws-sidebar,body.rx-print-rubric .view-tabs,body.rx-print-rubric .measure-switch-host,
  body.rx-print-rubric .switch-hint,body.rx-print-rubric #pageMsg,body.rx-print-rubric .no-print,body.rx-print-rubric .rx-history{display:none!important}
  body.rx-print-rubric .ws-layout{display:block}
  .rubric-dim{break-inside:avoid}
}
"""

SCORE_BASIS_JS = r"""
(function(){
  const API_BASE='/api/v1/demo2';
  const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const num=(v,d)=>v==null||isNaN(v)?'—':(d==null?String(Number(v)):Number(v).toFixed(d));
  const signed=(v,d)=>{if(v==null||isNaN(v))return'—';const n=Number(v);const t=Math.abs(n).toFixed(d==null?2:d);return n>0?'+'+t:n<0?'−'+t:t;};
  let drawer=null,backdrop=null,lastFocus=null,seq=0;
  function ensure(){
    if(drawer)return;
    backdrop=document.createElement('div');backdrop.className='rx-drawer-backdrop';backdrop.id='scoreBasisDrawerBackdrop';backdrop.hidden=true;
    drawer=document.createElement('aside');drawer.className='rx-drawer sb-drawer';drawer.id='scoreBasisDrawer';
    drawer.setAttribute('role','dialog');drawer.setAttribute('aria-modal','true');drawer.setAttribute('aria-labelledby','scoreBasisTitle');drawer.hidden=true;
    drawer.innerHTML='<div class="rx-drawer-head"><div><h2 class="rx-drawer-title" id="scoreBasisTitle" tabindex="-1">评分依据</h2><p class="rx-drawer-sub" id="scoreBasisSub"></p></div><button class="rx-btn rx-btn-text rx-drawer-close" type="button" id="scoreBasisClose" aria-label="关闭">关闭</button></div><div class="rx-drawer-body" id="scoreBasisBody"></div>';
    document.body.appendChild(backdrop);document.body.appendChild(drawer);
    backdrop.addEventListener('click',close);
    document.getElementById('scoreBasisClose').addEventListener('click',close);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&drawer&&!drawer.hidden)close();});
  }
  function close(){if(!drawer)return;drawer.hidden=true;backdrop.hidden=true;if(lastFocus&&lastFocus.focus)lastFocus.focus();}
  function show(title,sub){ensure();lastFocus=document.activeElement;document.getElementById('scoreBasisTitle').textContent=title;document.getElementById('scoreBasisSub').textContent=sub||'';drawer.hidden=false;backdrop.hidden=false;document.getElementById('scoreBasisTitle').focus();}
  function body(html){document.getElementById('scoreBasisBody').innerHTML=html;}
  function statusHtml(b){const cls=b.status==='scored'?'ok':b.status==='not_available'?'na':'warn';return `<span class="sb-status ${cls}" id="sbStatus">${esc(b.status_label)}</span>`;}
  function refHtml(r){
    const kind=`<span class="sb-kind">${esc(r.label||r.kind)}</span>`;
    if(r.kind==='video')return `<li data-ref-kind="video">${kind}${r.url?`<a href="${esc(r.url)}" class="sb-video-link" title="打开视频回放并跳到该时间点">▶ ${esc(r.text||'')}</a>`:esc(r.text||'')}</li>`;
    if(r.kind==='teacher_observation')return `<li data-ref-kind="teacher_observation">${kind}${esc(r.text||'')}${r.prompt?`<br><small>教师任务：${esc(r.prompt)}</small>`:''}${r.response?`<br><small>学生回应：${esc(r.response)}</small>`:''}${r.reason?`<br><small>评分理由：${esc(r.reason)}</small>`:''}${r.note?`<br><small>${esc(r.note)}</small>`:''}</li>`;
    if(r.kind==='course_goal')return `<li data-ref-kind="course_goal">${kind}<b>${esc(r.goal_id||'')}</b> ${r.text&&r.text!==r.goal_id?esc(r.text):''}${r.pass_criteria?`<br><small>通过标准：${esc(r.pass_criteria)}</small>`:''}</li>`;
    if(r.kind==='iep')return `<li data-ref-kind="iep">${kind}${esc(r.text||'')}${r.document_short?` <small>IEP ${esc(r.document_short)}</small>`:''}${(r.items||[]).length?`<ul>${r.items.map(i=>`<li>${esc(i.category_label)}：${esc(i.text)}</li>`).join('')}</ul>`:''}</li>`;
    if(r.kind==='coverage')return `<li data-ref-kind="coverage">${kind}${esc(r.text||'')}</li>`;
    if(r.kind==='measurement')return `<li data-ref-kind="measurement">${kind}${esc(r.text||'')}${(r.record_shorts||[]).length?` <small>${r.record_shorts.map(esc).join('、')}</small>`:''}</li>`;
    return `<li>${kind}${esc(r.text||'')}</li>`;
  }
  function insufficientHtml(b){return b.status==='scored'?'':`<div class="sb-insufficient" id="sbInsufficient"><strong>${b.status==='provisional'?'未复核暂算':'证据不足，未计分'}</strong>${(b.reasons||[]).length?`<ul>${b.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`:''}</div>`;}
  function measurementHtml(b,focus){
    const o=b.overall||{},f=b.formula||{},inp=b.inputs||{};
    const rows=(b.dimensions||[]).map(d=>`<tr data-dim="${esc(d.key)}"${focus===d.key?' class="sb-focus"':''}><td>${esc(d.label)}</td><td class="num">${d.score==null?'<span class="sb-chip off">留空</span>':esc(num(d.score))}</td><td class="num">${esc(num(d.weight,2))}</td><td class="num">${d.contribution==null?'—':esc(d.contribution_text||num(d.contribution))}</td><td class="num">${d.anchor_level==null?'—':esc(d.anchor_level)+' 档'}</td><td>${esc(d.status_label)}</td></tr>`).join('');
    const total=f.weighted_sum==null?'':`<tfoot><tr><td>合计</td><td></td><td class="num">${esc(num(f.total_weight))}</td><td class="num">${o.score==null?'—':esc(f.weighted_sum_text||num(f.weighted_sum))}</td><td colspan="2">${o.score==null?'':`综合分 ${f.renormalized?`${esc(f.weighted_sum_text)} ÷ ${esc(num(f.total_weight))} = `:''}`}<b id="sbFormulaResult">${o.score==null?'证据不足，未计分':esc(f.result||'—')}</b></td></tr></tfoot>`;
    const match=o.score==null?`<span class="sb-mismatch">未生成综合分</span>`:o.matches_page?`<span class="sb-match" data-sb="match">✓ 与页面综合分 ${esc(o.display)} 完全一致</span>`:`<span class="sb-mismatch" data-sb="match">与页面综合分 ${esc(o.display)} 不一致，请刷新</span>`;
    const dimDetail=(b.dimensions||[]).map(d=>`<details class="sb-item${focus===d.key?' sb-focus':''}" data-dim-detail="${esc(d.key)}"${focus===d.key?' open':''}><summary><b>${esc(d.label)} · 权重 ${esc(d.weight_percent)}%</b><span>${d.score==null?'留空':esc(num(d.score))+' 分'}</span><span class="sb-status ${d.status==='scored'?'ok':'warn'}">${esc(d.status_label)}</span></summary><div class="sb-item-body">${d.anchor_text?`<p class="sb-anchor">命中锚点 ${esc(d.anchor_level)} 分档：${esc(d.anchor_text)}</p>`:''}${d.reason?`<p class="sb-insufficient">${esc(d.reason)}</p>`:''}<p><b>证据要求：</b>${esc(d.evidence_requirement)}</p><p><b>数据来源：</b><span class="sb-chips">${(d.data_sources||[]).map(s=>`<span class="sb-chip${s.available?'':' off'}" title="${s.available?'本记录有该来源':'本记录暂无该来源'}">${esc(s.label)}${s.available?'':'（无）'}</span>`).join('')}</span></p></div></details>`).join('');
    const video=inp.video?`<div><span>视频稳定参与片段（成功回应）</span><b>${esc(num(inp.video.success_segments))}</b></div><div><span>回应偏低 / 离开或不可见</span><b>${esc(num(inp.video.low_response_segments))} / ${esc(num(inp.video.away_segments))}</b></div>`:'';
    return `${insufficientHtml(b)}
<section class="sb-sec"><h3>计算公式与代入数值</h3><div class="sb-formula"><p style="margin:0 0 4px">${esc(f.rule||'')}</p><code data-sb="expression">${esc(f.expression||'')}${o.score!=null&&f.result?` = ${esc(f.result)}`:''}</code><p style="margin:6px 0 0">${match}</p></div></section>
<section class="sb-sec"><h3>观察输入</h3><div class="sb-kv"><div><span>学习机会次数</span><b id="sbOpportunities">${esc(num(inp.opportunities))}</b></div><div><span>实际观察次数（≥${esc(inp.min_observed)} 才计分）</span><b id="sbObserved">${esc(num(inp.observed))}</b></div><div><span>观察率</span><b>${inp.observation_rate==null?'—':Math.round(inp.observation_rate*100)+'%'}</b></div><div><span>提示层级</span><b>${esc(inp.support_label||'—')}${inp.support_anchor_level!=null?` · 参考 ${esc(inp.support_anchor_level)} 档`:''}</b></div><div><span>教师复核</span><b>${inp.reviewed?'已复核':'未复核'}</b></div>${video}</div>${inp.suggestion_note?`<p class="sb-meta">${esc(inp.suggestion_note)}</p>`:''}</section>
<section class="sb-sec"><h3>各维度分、权重与加权贡献</h3><table class="sb-table" id="sbDimTable"><thead><tr><th>维度</th><th>分数</th><th>权重</th><th>加权贡献</th><th>命中锚点</th><th>状态</th></tr></thead><tbody>${rows}</tbody>${total}</table></section>
<section class="sb-sec"><h3>逐维度锚点与数据来源</h3>${dimDetail}</section>
<section class="sb-sec"><h3>引用的证据</h3>${(b.evidence_refs||[]).length?`<ul class="sb-refs" id="sbRefs">${b.evidence_refs.map(refHtml).join('')}</ul>`:'<p class="sb-meta">本记录没有可引用的证据。</p>'}</section>`;
  }
  function evaluationHtml(b,focus){
    const o=b.overall||{},f=b.formula||{};
    const items=(b.items||[]).map((it,n)=>{
      const shown=it.status==='scored'||it.status==='pending_review';
      return `<details class="sb-item${focus===it.id?' sb-focus':''}" data-item="${esc(it.id)}"${focus===it.id?' open':''}><summary><b>${n+1}. ${esc(it.label)}</b><span>学校 ${esc(num(it.school_score))}${it.school_grade?'（'+esc(it.school_grade)+'）':''}</span><span>系统 ${shown?esc(num(it.enhanced_score)):'—'}</span><span class="sb-status ${it.status==='scored'?'ok':it.status==='not_available'?'na':'warn'}">${esc(it.status_label)}</span></summary><div class="sb-item-body">
${it.reason?`<p class="sb-insufficient" data-item-reason>${esc(it.reason)}</p>`:''}
${shown?`<p class="sb-anchor">命中锚点 ${esc(it.anchor_level)} 分档 · ${esc(it.anchor_label)}：${esc(it.item_anchor_text||it.anchor_text)}</p><p><b>计算：</b>${esc(num(it.enhanced_score))} × 权重 ${esc(num(it.weight,4))} = ${esc(it.contribution_text||num(it.contribution,4))}</p>`:''}
<p><b>核对要点：</b>${esc(it.check_point)}</p><p><b>证据要求：</b>${esc(it.evidence_requirement)}</p>
<p><b>数据来源：</b>${(it.data_sources||[]).length?`<span class="sb-chips">${it.data_sources.map(s=>`<span class="sb-chip">${esc(s)}</span>`).join('')}</span>`:'<span class="sb-chip off">无</span>'}</p>
${(it.evidence_refs||[]).length?`<ul class="sb-refs">${it.evidence_refs.map(refHtml).join('')}</ul>`:''}
${it.delta&&it.delta.total_delta!=null?`<p class="sb-meta">分差：证据 ${esc(signed(it.delta.evidence_delta))} · 权重 ${esc(signed(it.delta.weight_delta))} · 合计 ${esc(signed(it.delta.total_delta))}</p>`:''}
</div></details>`;}).join('');
    const match=o.system_score==null?'<span class="sb-mismatch">系统增强总分未生成</span>':o.matches_page?`<span class="sb-match" data-sb="match">✓ 与页面系统增强分 ${esc(num(o.system_score,2))} 一致</span>`:'<span class="sb-mismatch" data-sb="match">与页面不一致，请刷新</span>';
    return `${insufficientHtml(b)}
<section class="sb-sec"><h3>系统增强分与分差</h3><div class="sb-kv"><div><span>学校原始分 / 折算</span><b>${esc(num(o.school_raw,1))} / ${esc(num(o.school_score,2))}</b></div><div><span>教学质量分（70 分制）</span><b>${esc(num(o.teaching_score_70,1))}</b></div><div><span>系统增强分</span><b id="sbSystemScore">${esc(num(o.system_score,2))}</b></div><div><span>证据 / 权重 / 总分差</span><b>${esc(signed(o.evidence_delta))} / ${esc(signed(o.weight_delta))} / ${esc(signed(o.total_delta))}</b></div></div></section>
<section class="sb-sec"><h3>计算公式与代入数值</h3><div class="sb-formula"><p style="margin:0 0 4px">${esc(f.rule||'')}</p>${f.expression?`<code data-sb="expression">${esc(f.expression)}${o.system_score!=null&&f.result!=null?` = ${esc(f.result)}`:''}</code>`:''}<p style="margin:6px 0 0">${match}</p><p class="sb-meta" style="margin:6px 0 0">${esc(f.comparison_rule||'')}</p></div></section>
<section class="sb-sec"><h3>逐条目依据（${(b.items||[]).length} 项）</h3>${items}</section>`;
  }
  async function open(kind,recordId,focus){
    const label=kind==='evaluation'?'系统增强评分依据':'测量评分依据';
    show(label,'正在读取…');body('<p class="sb-loading">正在读取评分依据…</p>');
    const mine=++seq;
    try{
      const path=kind==='evaluation'?'/evaluations/score-basis':'/measurements/score-basis';
      const res=await fetch(API_BASE+path+'?record_id='+encodeURIComponent(recordId),{credentials:'include'});
      let j={};try{j=await res.json();}catch(_){j={};}
      if(mine!==seq)return;
      if(!res.ok){const e=new Error(j?.error?.message||'评分依据读取失败');e.status=res.status;e.code=j?.error?.code;throw e;}
      const b=j.basis;
      document.getElementById('scoreBasisSub').innerHTML=`${statusHtml(b)} 记录 ${esc(b.record_short)} · 量表 ${esc(b.rubric_version)} · 细则 ${esc(b.detail_version)}${b.basis_source==='computed_on_read'?' · 旧记录按当前数据补算':''}${b.student_name?' · '+esc(b.student_name):''}`;
      body(`${b.privacy_note?`<p class="sb-meta">${esc(b.privacy_note)}</p>`:''}`+(kind==='evaluation'?evaluationHtml(b,focus):measurementHtml(b,focus))+`<p class="sb-meta">依据计算时间：${esc(b.computed_at||'')} · 依据版本 ${esc(b.basis_version)}</p>`);
      const target=focus&&document.querySelector(`#scoreBasisBody [data-dim-detail="${focus}"],#scoreBasisBody [data-item="${focus}"]`);
      if(target&&target.scrollIntoView)target.scrollIntoView({block:'center'});
    }catch(e){
      if(mine!==seq)return;
      document.getElementById('scoreBasisSub').textContent='';
      const text=window.RxUI&&RxUI.describeError?RxUI.errorHtml(RxUI.fromError(e)):esc(e.message);
      body(`<p class="sb-error" id="sbError">${e.status===403?'无权查看该记录的评分依据。':e.status===404?'记录不存在或已撤销。':''}${text}</p>`);
    }
  }
  // 课程评价的系统建议分：依据已随建议分一起返回，直接在同一抽屉里展示，不再请求接口。
  function openSuggestion(item,context){
    const ok=item.suggested_score!=null;
    show('系统建议分依据',`${item.id.replace('i','第 ')} 项 · ${item.label}`);
    const sub=document.getElementById('scoreBasisSub');
    sub.innerHTML=`<span class="sb-status ${ok?'ok':'warn'}" data-sb="suggestion-status">${esc(ok?item.status_label:'证据不足，待教师评分')}</span> ${esc(item.category_label||'')} · 建议规则 ${esc((context&&context.suggestion_version)||'')}`;
    const inputs=Object.entries(item.inputs||{}).map(([k,v])=>`<div><span>${esc(INPUT_LABELS[k]||k)}</span><b>${esc(typeof v==='number'&&/ratio|coverage|share/.test(String(k))?Math.round(v*100)+'%':typeof v==='boolean'?(v?'是':'否'):v==null?'—':String(v))}</b></div>`).join('');
    const sources=(item.data_sources||[]).map(s=>`<span class="sb-chip${s.available?'':' off'}">${esc(s.label)}${s.available?'':'（无）'}</span>`).join('');
    body(`${ok?'':`<div class="sb-insufficient" data-sb="suggestion-insufficient"><strong>证据不足，待教师评分</strong><ul><li>${esc(item.reason)}</li></ul></div>`}
<section class="sb-sec"><h3>系统建议分</h3><div class="sb-kv"><div><span>建议分</span><b data-sb="suggested-score">${ok?esc(num(item.suggested_score)):'—'}</b></div>${ok?`<div><span>命中锚点</span><b>${esc(item.anchor_level)} 分档</b></div>`:''}<div><span>可信程度</span><b>${item.confidence==='unreviewed'?'含未复核视频线索':ok?'本课已确认数据':'—'}</b></div></div>${ok&&item.item_anchor_text?`<p class="sb-anchor" style="margin-top:8px">${esc(item.item_anchor_text)}</p>`:''}</section>
${ok?`<section class="sb-sec"><h3>计算公式与代入数值</h3><div class="sb-formula"><code data-sb="expression">${esc(item.formula)}</code></div></section>`:''}
<section class="sb-sec"><h3>数据来源</h3><p class="sb-chips" data-sb="sources">${sources||'<span class="sb-chip off">无</span>'}</p>${inputs?`<div class="sb-kv" style="margin-top:8px">${inputs}</div>`:''}</section>
<section class="sb-sec"><h3>引用的证据</h3>${(item.evidence_refs||[]).length?`<ul class="sb-refs" data-sb="suggestion-refs">${item.evidence_refs.map(refHtml).join('')}</ul>`:'<p class="sb-meta">没有可引用的本课数据。</p>'}</section>
<section class="sb-sec"><h3>核对要点</h3><p class="sb-meta">${esc(item.check_point||'')}</p><p class="sb-meta"><b>证据要求：</b>${esc(item.evidence_requirement||'')}</p></section>
<p class="sb-meta">${esc((context&&context.note)||'')} 依据计算时间：${esc((context&&context.computed_at)||'')}</p>`);
  }
  const INPUT_LABELS={goal_count:'课程目标数',goals_with_pass_criteria:'有通过标准的目标',goals_with_conditions:'有测量条件的目标',layered:'多目标分层',course_task_version:'课程任务版本',goals_with_reviewed_records:'有复核记录的目标',goals_achieved:'已达成目标',student_count:'学生数',average_in_task_ratio:'平均在任务时长占比',reviewed_records:'已复核记录数',average_independence:'独立性平均',average_stable_share:'稳定参与占比',included_students:'纳入检测学生',participating_students:'有参与/回应的学生',coverage:'学生覆盖率',average_engaged_ratio:'平均稳定参与时长占比',students_with_reviewed_scores:'有复核综合分的学生',average_composite:'综合分平均',students_with_video_reference:'有视频线索分的学生',average_participation_ref:'视频参与线索平均',students_with_low_response:'出现回应偏低的学生',students_recovered:'之后恢复参与的学生',teacher_observations:'教师观察记录'};
  function button(kind,recordId,focus,label){return `<button type="button" class="sb-btn no-print" data-sb-kind="${esc(kind)}" data-sb-record="${esc(recordId)}"${focus?` data-sb-focus="${esc(focus)}"`:''}>${esc(label||'查看依据')}</button>`;}
  // Test harnesses run page scripts without a full DOM; only bind when it exists.
  if(typeof document!=='undefined'&&document.addEventListener)document.addEventListener('click',e=>{const t=e.target&&e.target.closest?e.target.closest('[data-sb-record]'):null;if(!t||t.disabled)return;e.preventDefault();open(t.getAttribute('data-sb-kind'),t.getAttribute('data-sb-record'),t.getAttribute('data-sb-focus')||'');});
  if(typeof window!=='undefined')window.ScoreBasis={open,close,button,openSuggestion};
})();
"""

__all__ = ["SCORE_BASIS_CSS", "SCORE_BASIS_JS"]
