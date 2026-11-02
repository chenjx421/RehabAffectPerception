"""Shared「最小 IEP 支持摘要」component: Word/PDF upload → system summary → teacher confirmation.

Used by the classroom result page (/demo2/simple-result) and the student dossier
page (/demo2/dossier). Plain inline CSS/JS, no build step or CDN. The component
never talks to the archive itself; pages read ``controller.payload()`` and
``controller.validate()`` and send the payload with their own save request.
"""
from __future__ import annotations

IEP_INTAKE_CSS = r"""
.iep-intake [hidden],.iep-intake[hidden]{display:none!important}
.iep-intake label.iep-check,.iep-item label,.iep-choice label{justify-content:flex-start;text-align:left}
.iep-intake input[type=checkbox],.iep-intake input[type=radio]{width:auto;min-height:0;flex:0 0 auto;margin:3px 0 0}
.iep-intake{grid-column:1/-1;border:1px solid #d8e5ef;border-radius:8px;background:#fbfdff;padding:14px 16px;display:grid;gap:12px}
.iep-intake.has-error{border-color:#c74a4a;box-shadow:0 0 0 3px #fde5e5}
.iep-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.iep-head label{font-weight:800;color:#173553;font-size:14px}
.iep-head .iep-req{color:#c74a4a;margin:0 2px}
.iep-state{font-size:12px;font-weight:700;padding:2px 8px;border-radius:4px;background:#eef2f6;color:#4d5b6d}
.iep-state[data-tone=ok]{background:#e5f6ed;color:#17684f}.iep-state[data-tone=warn]{background:#fff1c9;color:#8c5b10}.iep-state[data-tone=bad]{background:#ffe9e9;color:#943e3e}
.iep-hint{margin:0;color:#70849a;font-size:12px;line-height:1.7}
.iep-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.iep-file{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.iep-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;padding:0 12px;border:1px solid #c8d8e6;border-radius:6px;background:#fff;color:#2163c4;font-weight:700;cursor:pointer;font-size:13px}
.iep-btn.primary{background:#2163c4;border-color:#2163c4;color:#fff}.iep-btn.danger{color:#b23b3b;border-color:#efc9c9}
.iep-btn:disabled{opacity:.5;cursor:not-allowed}.iep-btn:focus-visible,.iep-file:focus-visible+label{outline:3px solid #9cc0f5;outline-offset:2px}
.iep-file-status{font-size:12px;color:#53697c}
.iep-choice{display:grid;gap:6px;padding:10px 12px;border:1px dashed #c8d8e6;border-radius:6px;background:#fff}
.iep-choice label{display:flex;gap:8px;align-items:flex-start;font-size:13px;cursor:pointer}
.iep-choice .iep-warn{margin:0;color:#8c5b10;font-size:12px}
.iep-summary{display:grid;gap:8px}
.iep-summary-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.iep-summary-head strong{font-size:14px}.iep-summary-head small{color:#70849a}
.iep-items{list-style:none;margin:0;padding:0;display:grid;gap:8px;max-height:420px;overflow:auto}
.iep-item{display:grid;grid-template-columns:auto 84px minmax(0,1fr) auto auto;gap:8px;align-items:start;padding:8px;border:1px solid #e1eaf2;border-radius:6px;background:#fff}
.iep-item.is-off{opacity:.55;background:#f5f7f9}.iep-item.is-off textarea{text-decoration:line-through}
.iep-item.is-edited{border-color:#9cc0f5}
.iep-item label{display:flex;gap:4px;align-items:center;font-size:12px;white-space:nowrap;padding-top:6px}
.iep-cat{display:inline-block;font-size:12px;font-weight:700;color:#2163c4;background:#eef5ff;border-radius:4px;padding:3px 6px;text-align:center;margin-top:4px}
.iep-cat[data-cat=precautions]{color:#8c5b10;background:#fff5d8}.iep-cat[data-cat=assessment_methods]{color:#5e4b96;background:#eee9ff}
.iep-item textarea{min-height:38px;resize:vertical;width:100%;border:1px solid #d8e5ef;border-radius:4px;padding:6px 8px;font:inherit;font-size:13px;line-height:1.6}
.iep-item textarea[readonly]{background:#f8fbfe;border-color:transparent}
.iep-page{font-size:12px;color:#53697c;white-space:nowrap;padding-top:6px}
.iep-confirm-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.iep-confirmed{display:none;color:#17684f;font-weight:700;font-size:13px}.iep-intake[data-confirmed=true] .iep-confirmed{display:inline}
.iep-manual{display:grid;gap:4px}.iep-manual label{font-weight:700;font-size:13px}
.iep-manual textarea{min-height:64px;width:100%;border:1px solid #d8e5ef;border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;line-height:1.6}
.iep-tag{display:inline-block;font-size:11px;font-weight:800;color:#fff;background:#087f78;border-radius:4px;padding:1px 6px;margin-right:6px}
.iep-tag.system{background:#2163c4}
.iep-count{font-size:12px;color:#70849a}.iep-count.over{color:#c74a4a}
.iep-settings{border-top:1px solid #e1eaf2;padding-top:8px}.iep-settings summary{cursor:pointer;font-size:13px;font-weight:700;color:#2163c4;min-height:30px}
.iep-settings-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-top:8px}
.iep-settings-grid .iep-field{display:grid;gap:4px;font-size:12px}.iep-settings-grid .iep-field.full{grid-column:1/-1}
.iep-settings-grid input,.iep-settings-grid textarea{border:1px solid #d8e5ef;border-radius:6px;padding:6px 8px;font:inherit;font-size:13px}
.iep-auth{display:grid;gap:8px;padding:10px 12px;border-left:4px solid #d69d31;background:#fff9e8;border-radius:4px}
.iep-auth strong{font-size:13px;color:#77591c}
.iep-auth label.iep-check{display:flex;gap:8px;align-items:flex-start;font-size:12px}
.iep-field-error{border-color:#c74a4a!important;box-shadow:0 0 0 2px #fde5e5}
.iep-error{margin:0;color:#b23b3b;font-size:13px;font-weight:700}
.iep-preview{display:grid;gap:6px;padding:10px 12px;border:1px solid #e1eaf2;border-radius:6px;background:#fff}
.iep-preview p{margin:0;font-size:13px;line-height:1.7;color:#344b60}
@media(max-width:720px){.iep-item{grid-template-columns:auto minmax(0,1fr);}.iep-item .iep-cat{grid-column:2}.iep-item textarea{grid-column:1/-1}.iep-item .iep-page,.iep-item .iep-del{grid-column:auto}}
"""

IEP_INTAKE_JS = r"""
window.IepIntake=(function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pad=n=>String(n).padStart(2,'0');
  const ymd=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  const plusDays=n=>{const d=new Date();d.setDate(d.getDate()+n);return ymd(d);};
  const REQUIRED='请上传 IEP 文件或填写 IEP 支持摘要';
  const FIELD_MAP={iepSummary:'file',iepFile:'file',iepItems:'items',iepConfirm:'confirm',iepManual:'manual',iepExisting:'choice',
    iepAuthReference:'authRef',iepAuthUntil:'authUntil',iepAuthConfirmed:'authOk',iepDocumentDate:'docDate',iepRetainUntil:'retain',iepSourceRef:'source'};
  async function api(path,options){
    const response=await fetch('/api/v1/demo2'+path,{credentials:'same-origin',cache:'no-store',...(options||{})});
    let body=null;try{body=await response.json();}catch(_){body=null;}
    if(!response.ok||!body||body.ok===false){const e=new Error(body?.error?.message||('请求失败（'+response.status+'）'));e.status=response.status;e.code=body?.error?.code||'';e.field=body?.error?.field||'';throw e;}
    return body;
  }
  function create(root,opts){
    opts=opts||{};
    const p=(opts.prefix||'iep').replace(/[^A-Za-z0-9_]/g,'');
    const embedded=!!opts.embedded;
    const st={studentId:'',status:null,statusError:'',mode:'new',existingId:'',supersedesId:'',parse:null,items:[],confirmed:false,busy:false};
    const id=name=>p+'_'+name;
    const $=name=>document.getElementById(id(name));
    root.innerHTML=`<div class="iep-intake" id="${id('box')}" data-confirmed="false">
      <div class="iep-head"><label for="${id('file')}">最小 IEP 支持摘要 <span class="iep-req">*</span>（必填）</label><span class="iep-state" id="${id('state')}">待填写</span></div>
      <p class="iep-hint">上传 IEP 文件（Word/PDF），系统自动筛查长期/短期目标、支持方式、教学策略、注意事项和评估方式，生成带页码的条目摘要；诊断原文、身份证号、手机号、住址不会进入摘要。也可直接在「人工补充」中填写。</p>
      <div class="iep-choice" id="${id('choice')}" hidden></div>
      <div class="iep-row" id="${id('uploadRow')}"><input class="iep-file" id="${id('file')}" type="file" accept=".pdf,.docx,.doc,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword"><label class="iep-btn" for="${id('file')}" id="${id('fileBtn')}">上传 IEP 文件（Word/PDF）</label><span class="iep-file-status" id="${id('fileStatus')}" role="status">尚未上传；支持 PDF、DOCX、DOC，最大 20 MB</span></div>
      <div class="iep-summary" id="${id('summary')}" hidden>
        <div class="iep-summary-head"><strong id="${id('summaryTitle')}">系统摘要（待确认）</strong><small id="${id('summaryMeta')}"></small></div>
        <p class="iep-hint" id="${id('summaryNotice')}" hidden></p>
        <ol class="iep-items" id="${id('items')}"></ol>
        <div class="iep-confirm-row"><button class="iep-btn primary" type="button" id="${id('confirm')}">确认摘要</button><button class="iep-btn" type="button" id="${id('unlock')}" hidden>修改摘要</button><span class="iep-confirmed" id="${id('confirmedText')}">已确认</span></div>
      </div>
      <div class="iep-manual"><label for="${id('manual')}"><span class="iep-tag">教师补充</span>人工补充（文档中没有、但课堂需要的支持信息）</label><textarea id="${id('manual')}" maxlength="1000" placeholder="例如：上课前先展示当天流程图；操作环节需要一对一示范一次。请不要填写诊断原文、身份证号、电话或住址"></textarea><span class="iep-count" id="${id('manualCount')}">0 / 1000 字</span></div>
      ${embedded?'':`<details class="iep-settings" id="${id('settings')}"><summary>保存到学生资料库的设置（资料日期、保存期限、授权）</summary>
        <div class="iep-auth" id="${id('auth')}" hidden><strong>该学生还没有有效的资料授权：IEP 需在授权范围内加密保存</strong>
          <div class="iep-settings-grid"><div class="iep-field full"><label for="${id('authRef')}">授权依据（必填）</label><textarea id="${id('authRef')}" maxlength="500" placeholder="授权记录编号、签署日期和校内保管部门"></textarea></div>
          <div class="iep-field"><label for="${id('authUntil')}">授权有效期至（必填，≤60 天）</label><input id="${id('authUntil')}" type="date"></div></div>
          <label class="iep-check"><input type="checkbox" id="${id('authOriginal')}" checked>允许加密保存 IEP 原件（可下载）</label>
          <label class="iep-check"><input type="checkbox" id="${id('authOk')}">已核实本学生 IEP 资料的实际授权，覆盖教育支持用途、保存范围和期限</label></div>
        <div class="iep-settings-grid"><div class="iep-field"><label for="${id('docDate')}">资料日期</label><input id="${id('docDate')}" type="date"></div>
          <div class="iep-field"><label for="${id('retain')}">资料保存至（不晚于授权截止日）</label><input id="${id('retain')}" type="date"></div>
          <div class="iep-field full"><label for="${id('source')}">资料来源</label><input id="${id('source')}" maxlength="200" placeholder="默认：教师上传的 IEP 文件（课堂分析页确认摘要）"></div></div></details>`}
      <p class="iep-error" id="${id('error')}" role="alert" hidden></p>
    </div>`;
    const box=$('box');
    if(!embedded){$('docDate').value=ymd(new Date());$('docDate').max=ymd(new Date());$('authUntil').min=plusDays(1);$('authUntil').max=plusDays(60);$('authUntil').value=plusDays(30);$('retain').min=plusDays(1);}
    function changed(){if(typeof opts.onChange==='function')opts.onChange(api_);}
    function setError(text,field){const node=$('error');document.querySelectorAll('#'+id('box')+' .iep-field-error').forEach(n=>n.classList.remove('iep-field-error'));box.classList.toggle('has-error',!!text);node.textContent=text||'';node.hidden=!text;if(text&&field){const target=$(FIELD_MAP[field]||field);if(target){target.classList.add('iep-field-error');if(['authRef','authUntil','authOk','docDate','retain','source'].includes(FIELD_MAP[field]||field)&&$('settings'))$('settings').open=true;try{target.focus({preventScroll:false});}catch(_){target.focus();}}}}
    function kept(){return st.items.filter(item=>item.keep&&item.text.trim());}
    function authNeeded(){return !embedded&&st.mode==='new'&&!(st.status&&st.status.authorization&&st.status.authorization.active);}
    function refreshState(){
      const node=$('state');let text='待填写',tone='bad';
      if(st.mode==='existing'&&st.existingId){text='沿用已有 IEP';tone='ok';}
      else if(st.busy){text='正在处理文件…';tone='';}
      else if(st.parse&&kept().length&&!st.confirmed){text='系统摘要待确认';tone='warn';}
      else if(st.confirmed||$('manual').value.trim()){text=(st.confirmed?'已确认 '+kept().length+' 条':'')+($('manual').value.trim()?((st.confirmed?' + ':'')+'教师补充'):'');tone='ok';}
      node.textContent=text;node.dataset.tone=tone;box.dataset.confirmed=String(st.confirmed);
      $('summaryTitle').textContent=st.confirmed?'系统摘要（已确认）':'系统摘要（待确认）';
      $('confirm').hidden=st.confirmed;$('unlock').hidden=!st.confirmed;
      $('items').querySelectorAll('textarea').forEach(t=>{t.readOnly=st.confirmed;});
      $('items').querySelectorAll('input[type=checkbox],button').forEach(b=>{b.disabled=st.confirmed;});
      $('uploadRow').hidden=st.mode==='existing';$('summary').hidden=st.mode==='existing'||!st.parse;
      if(!embedded){$('auth').hidden=!authNeeded();}
      $('fileBtn').classList.toggle('iep-btn-disabled',st.busy);
    }
    function unconfirm(){if(st.confirmed){st.confirmed=false;refreshState();changed();}}
    function renderItems(){
      const list=$('items');
      if(!st.items.length){list.innerHTML='<li class="iep-hint">文件中没有筛查到可用于课堂支持的条目，请在下方「人工补充」中填写。</li>';return;}
      list.innerHTML=st.items.map((item,index)=>`<li class="iep-item${item.keep?'':' is-off'}${item.text!==item.original?' is-edited':''}" data-index="${index}" data-item="${esc(item.item_id)}"><label><input type="checkbox" data-keep ${item.keep?'checked':''}>保留</label><span class="iep-cat" data-cat="${esc(item.category)}">${esc(item.category_label)}</span><textarea data-text aria-label="${esc(item.category_label)}摘要条目 ${index+1}" maxlength="300">${esc(item.text)}</textarea><span class="iep-page">${item.page?'第 '+esc(item.page)+' 页':'页码未标注'}</span><button class="iep-btn danger iep-del" type="button" data-del title="删除此条">删除</button></li>`).join('');
    }
    function renderSummary(summary){
      st.parse=summary;st.confirmed=false;
      st.items=(summary.items||[]).map(item=>({...item,original:item.text,keep:true}));
      const meta=['共 '+(summary.item_count||0)+' 条',summary.page_count?('文件 '+summary.page_count+' 页'+(summary.page_count_estimated?'（估算）':'')):'',summary.excluded_sensitive_count?('已剔除 '+summary.excluded_sensitive_count+' 条含'+(summary.excluded_sensitive_labels||[]).join('、')+'的内容'):'未发现需剔除的敏感内容'].filter(Boolean).join(' · ');
      $('summaryMeta').textContent=meta;
      $('summaryNotice').textContent=summary.notice||'';$('summaryNotice').hidden=!summary.notice;
      renderItems();refreshState();changed();
    }
    async function upload(file){
      setError('');
      if(!file)return;
      if(!/\.(pdf|docx|doc)$/i.test(file.name)){setError('只支持 PDF、DOCX 或 DOC 格式的 IEP 文件','iepFile');$('file').value='';return;}
      if(file.size<=0||file.size>20*1024*1024){setError('IEP 文件须大于 0 且不超过 20 MB','iepFile');$('file').value='';return;}
      st.busy=true;st.parse=null;st.items=[];st.confirmed=false;refreshState();
      $('fileStatus').textContent='正在上传并解析：'+file.name+'（'+(file.size/1048576).toFixed(2)+' MB）…';
      try{
        const form=new FormData();form.append('purpose','iep');form.append('file',file,file.name);
        const parsed=await api('/documents/parse',{method:'POST',body:form});
        const parseId=parsed.result&&parsed.result.parse_id;
        if(!parseId)throw new Error('解析结果缺少编号，请重新上传');
        $('fileStatus').textContent='正在自动筛查课堂支持要点…';
        const generated=await api('/dossier/iep-intake/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parse_id:parseId})});
        renderSummary(generated.summary);
        $('fileStatus').textContent='已解析：'+file.name+'。请逐条核对、删改后点击「确认摘要」。';
      }catch(error){st.parse=null;st.items=[];$('fileStatus').textContent='上传或解析未完成';setError((error.message||'IEP 文件解析失败')+(error.code?'（错误码：'+error.code+'）':''),'iepFile');}
      finally{st.busy=false;$('file').value='';refreshState();changed();}
    }
    function renderChoice(){
      const node=$('choice'),s=st.status;
      if(embedded||!s||!['available','ambiguous'].includes(s.iep_status)){node.hidden=true;node.innerHTML='';st.mode='new';st.existingId='';st.supersedesId='';refreshState();return;}
      if(s.iep_status==='available'&&s.current){
        const c=s.current;
        if(!st.existingId&&st.mode==='new'&&!st.parse&&!st.supersedesId){st.mode='existing';st.existingId=c.document_id;}
        node.innerHTML=`<strong style="font-size:13px">该学生已有有效 IEP，请选择本课使用方式</strong><label><input type="radio" name="${id('mode')}" value="existing" ${st.mode==='existing'?'checked':''}>沿用已有 IEP（版本 ${esc(c.version)} · 资料日期 ${esc(c.document_date)}）</label><label><input type="radio" name="${id('mode')}" value="new" ${st.mode==='new'?'checked':''}>上传新版本（替换版本 ${esc(c.version)}，旧版本保留历史）</label>`;
        if(st.mode==='new')st.supersedesId=c.document_id;
      }else{
        const list=s.candidates||[];
        if(st.mode==='new'&&!st.parse&&!st.supersedesId)st.mode='existing';
        if(st.mode==='existing'&&!list.some(c=>c.document_id===st.existingId)){st.existingId='';}
        node.innerHTML=`<p class="iep-warn">该学生同时存在 ${list.length} 份有效 IEP（ambiguous），系统不自动选择。请选择本课使用的一份，或上传新版本替换所选的一份。</p>`+list.map(c=>`<label><input type="radio" name="${id('pick')}" value="${esc(c.document_id)}" ${(st.existingId||st.supersedesId)===c.document_id?'checked':''}>IEP 版本 ${esc(c.version)} · 资料日期 ${esc(c.document_date)} · 保存至 ${esc(c.retain_until)}</label>`).join('')+`<label><input type="checkbox" id="${id('ambNew')}" ${st.mode==='new'?'checked':''}>改为上传新版本，替换所选的这一份</label>`;
      }
      node.hidden=false;refreshState();
    }
    async function setStudent(studentId){
      st.studentId=studentId||'';st.status=null;st.statusError='';st.mode='new';st.existingId='';st.supersedesId='';
      if(!embedded&&st.studentId){
        try{const r=await api('/dossier/iep-intake/status?student_id='+encodeURIComponent(st.studentId));if(st.studentId===studentId)st.status=r.status;}
        catch(error){st.status=null;st.statusError=error.message||'';}
        if(!embedded&&st.status&&st.status.authorization&&st.status.authorization.active){$('retain').max=st.status.authorization.valid_until;if(!$('retain').value||$('retain').value>st.status.authorization.valid_until)$('retain').value=st.status.authorization.valid_until;}
      }
      renderChoice();refreshState();if(authNeeded()&&$('settings'))$('settings').open=true;changed();
    }
    root.addEventListener('change',event=>{
      const t=event.target;
      if(t===$('file')){upload(t.files&&t.files[0]);return;}
      if(t.matches('[data-keep]')){const li=t.closest('[data-index]'),item=st.items[Number(li.dataset.index)];item.keep=t.checked;li.classList.toggle('is-off',!t.checked);unconfirm();refreshState();changed();return;}
      if(t.name===id('mode')){st.mode=t.value;const c=st.status&&st.status.current;st.existingId=st.mode==='existing'&&c?c.document_id:'';st.supersedesId=st.mode==='new'&&c?c.document_id:'';setError('');refreshState();changed();return;}
      if(t.name===id('pick')){if(st.mode==='existing')st.existingId=t.value;else st.supersedesId=t.value;setError('');refreshState();changed();return;}
      if(t.id===id('ambNew')){const picked=st.existingId||st.supersedesId;st.mode=t.checked?'new':'existing';st.existingId=st.mode==='existing'?picked:'';st.supersedesId=st.mode==='new'?picked:'';refreshState();changed();return;}
    });
    root.addEventListener('input',event=>{
      const t=event.target;
      if(t.matches('[data-text]')){const li=t.closest('[data-index]'),item=st.items[Number(li.dataset.index)];item.text=t.value;li.classList.toggle('is-edited',item.text!==item.original);unconfirm();changed();return;}
      if(t===$('manual')){const n=t.value.length;$('manualCount').textContent=n+' / 1000 字';$('manualCount').classList.toggle('over',n>1000);setError('');refreshState();changed();}
      if(t.classList.contains('iep-field-error'))t.classList.remove('iep-field-error');
    });
    root.addEventListener('click',event=>{
      const t=event.target.closest('button');if(!t||!root.contains(t))return;
      if(t.matches('[data-del]')){const li=t.closest('[data-index]');st.items.splice(Number(li.dataset.index),1);renderItems();unconfirm();refreshState();changed();return;}
      if(t===$('confirm')){
        const keptItems=kept();
        if(!keptItems.length){setError('没有保留任何系统摘要条目；如文件中确无可用内容，请在「人工补充」中填写','iepItems');return;}
        const blank=st.items.find(item=>item.keep&&!item.text.trim());if(blank){setError('保留的条目不能为空，请填写或取消勾选','iepItems');return;}
        st.confirmed=true;setError('');refreshState();changed();
        if(window.RxUI?.toast)RxUI.toast('已确认 '+keptItems.length+' 条 IEP 摘要','success',2400);return;
      }
      if(t===$('unlock')){st.confirmed=false;refreshState();changed();return;}
    });
    function validate(){
      if(st.busy)return {ok:false,message:'IEP 文件仍在处理中，请稍候',field:'iepFile'};
      if(st.mode==='existing'){if(!st.existingId)return {ok:false,message:'请选择本课使用的 IEP 版本',field:'iepExisting'};return {ok:true};}
      const manual=$('manual').value.trim();
      if(manual.length>1000)return {ok:false,message:'人工补充不能超过 1000 字',field:'iepManual'};
      if(st.parse&&kept().length&&!st.confirmed)return {ok:false,message:'请先核对系统摘要并点击「确认摘要」',field:'iepConfirm'};
      if(!(st.confirmed&&kept().length)&&!manual)return {ok:false,message:REQUIRED,field:'iepSummary',required:true};
      if(st.status&&st.status.iep_status==='ambiguous'&&!st.supersedesId&&!embedded)return {ok:false,message:'该学生有多份有效 IEP，请先选择要替换的一份',field:'iepExisting'};
      if(authNeeded()){
        if(!$('authRef').value.trim())return {ok:false,message:'请填写授权依据（该学生还没有有效资料授权）',field:'iepAuthReference'};
        if(!$('authUntil').value)return {ok:false,message:'请填写授权有效期',field:'iepAuthUntil'};
        if(!$('authOk').checked)return {ok:false,message:'请勾选「已核实本学生 IEP 资料的实际授权」',field:'iepAuthConfirmed'};
      }
      return {ok:true};
    }
    function payload(){
      if(st.mode==='existing')return {mode:'existing',document_id:st.existingId,manual_supplement:$('manual').value.trim()};
      const body={mode:'new',parse_id:st.parse?st.parse.parse_id:'',items:st.confirmed?kept().map(item=>({item_id:item.item_id,text:item.text.trim()})):[],
        manual_supplement:$('manual').value.trim(),confirmed:!!st.confirmed||!st.parse,supersedes_id:st.supersedesId||''};
      if(!embedded){body.document_date=$('docDate').value||'';body.retain_until=$('retain').value||'';body.source_ref=$('source').value.trim();
        if(authNeeded())body.authorization={reference:$('authRef').value.trim(),valid_until:$('authUntil').value,allow_original:$('authOriginal').checked,confirmed:$('authOk').checked};}
      return body;
    }
    function isEmpty(){return st.mode!=='existing'&&!st.parse&&!$('manual').value.trim();}
    function reset(){st.parse=null;st.items=[];st.confirmed=false;st.busy=false;$('manual').value='';$('manualCount').textContent='0 / 1000 字';$('fileStatus').textContent='尚未上传；支持 PDF、DOCX、DOC，最大 20 MB';setError('');renderItems();renderChoice();refreshState();}
    const api_={setStudent,validate,payload,reset,isEmpty,showError:(text,field)=>setError(text,field),
      setSupersedes:value=>{st.supersedesId=value||'';},state:()=>({...st,kept:kept().length,manual:$('manual').value.trim()}),
      fieldId:field=>id(FIELD_MAP[field]||field)};
    renderItems();refreshState();
    return api_;
  }
  function previewHtml(intake){
    if(!intake)return '';
    const items=(intake.items||[]).map(item=>`<p><span class="iep-tag system">${esc(item.category_label||'摘要')}</span>${esc(item.text)}${item.page?'（第 '+esc(item.page)+' 页）':''}</p>`).join('');
    const manual=intake.manual_supplement?`<p><span class="iep-tag">教师补充</span>${esc(intake.manual_supplement)}</p>`:'';
    return `<div class="iep-preview">${items?'<strong style="font-size:13px">系统摘要（已确认）</strong>'+items:''}${manual}</div>`;
  }
  return {create,previewHtml};
})();
"""
