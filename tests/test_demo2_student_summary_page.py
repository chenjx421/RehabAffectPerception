"""Synthetic UI contracts only; never connect to a running school service."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_student_summary_page import (
    render_student_summary_html, render_admin_student_summaries_html,
)
from test_demo2_portal_html import _run_page_js


ENV = r"""
location.search='?student_id=s1';
Element.prototype.replaceChildren=function(...items){this.children=items;this.textContent='';this.innerHTML='';};
Element.prototype.appendChild=function(item){(this.children??=[]).push(item);return item;};
Element.prototype.reportValidity=function(){return this.valid!==false;};
Element.prototype.remove=function(){this.removed=true;};
const clicks=[];Element.prototype.click=function(){clicks.push(this);};
document.createElement=tag=>new Element(tag);document.body=new Element('body');
const blobs=[],revoked=[];
URL.createObjectURL=blob=>{blobs.push(blob);return 'blob:synthetic';};URL.revokeObjectURL=url=>revoked.push(url);
const text=node=>node.textContent+(node.children||[]).map(text).join(' ');
const submit={preventDefault(){}};
const levels={cognition:'unknown',communication:'with_support',motor:'developing',sensory:'independent',social_adaptation:'unknown'};
const snapshot={snapshot_id:'ss1',recorded_on:'2026-01-01',learning_goals:'Goal',support_methods:'Support',domains:levels,
  provenance:{source_type:'classroom_observation',source_version:2,rule_version:'v1',source_date:'2026-01-01',source_ref:'NEVER-EXPORT'},reviewed:true,
  measurement:{opportunities:8,observed:6,scores:{accuracy:2},assessment:{passed:false},source_ref:'NEVER-EXPORT',student_name:'NEVER-NAME'}};
const ws=(status='active',records=[])=>({student:{student_id:'s1',display_name:'Synthetic student',student_code:'T-1',class_name:'Synthetic class'},
  authorization:status===null?null:{authorization_id:'auth1',valid_until:status==='expired'?'2000-01-01':'2099-01-01',status},snapshots:records});
const verify=async()=>{byId('studentVerified').checked=true;await byId('studentVerified').fire('change');};
const fillSnapshot=()=>{byId('sourceRef').value='Local record';byId('learningGoals').value='Goal';byId('supportMethods').value='Support';
  Object.entries(levels).forEach(([key,value])=>byId('domain_'+key).value=value);byId('snapshotReviewed').checked=true;};
const confirmReview=async()=>{byId('reviewConfirmed').checked=true;await byId('reviewConfirmed').fire('change');};
const archive=(page=1,total=21)=>({items:[{public_id:'ps1',channel_id:'channel_1',snapshot_count:1,latest_recorded_on:'2026-01-01',valid_until:'2099-01-01'}],
  pagination:{page,page_size:20,total,total_pages:Math.ceil(total/20)},policy:{research:false,training:false}});
const policy={purpose:'educational_followup',research:false,training:false,pseudonymous_not_anonymous:true,expiry_exclusive:true,raw_retention_days:60,maximum_authorization_days:365,free_text_requires_no_identifiers:true,stale_measurement_snapshots:'withheld',cleanup_scope:'logical_database_blobs_only'};
const exported=()=>({public_id:'ps1',valid_until:'2099-01-01',policy:{...policy,source_ref:'NEVER-EXPORT'},snapshots:[{...snapshot,source_ref:'NEVER-EXPORT',display_name:'NEVER-NAME'}],student_name:'NEVER-NAME'});
const course=(status='reviewed')=>({entry_id:'course-public-1',recorded_on:'2026-10-16',date_basis:'upload_date',revision:2,status,reviewed:status==='reviewed',
  media:{duration_sec:123.5,has_audio:true,filename:'NEVER-FILENAME',scene_score:999},
  measurements:[{measurement:{...snapshot.measurement,assessment:{overall_score:6.85}},provenance:{...snapshot.provenance,source_status:'current'},task_id:'NEVER-TASK'}],
  provenance:{source_type:'automatic_course_archive',rule_version:'course-archive-v1',source_status:status==='source_withheld'?'withheld':status==='pending_review'?'technical_only':'current',identity_scope:'confirmed_sample_frame',whole_lesson_tracking:false,scene_metrics_attributed_to_student:false,source_ref:'NEVER-SOURCE'},
  created_at:'2026-10-16T10:00:00+08:00',updated_at:'2026-10-16T11:00:00+08:00',task_id:'NEVER-TASK',name:'NEVER-NAME',courseName:'NEVER-COURSE'});
const historicalEntry=()=>{
  const row=course();row.status='historical_reviewed';row.live_evidence_available=false;
  row.provenance={...row.provenance,source_status:'historical_reviewed',live_evidence_available:false};
  row.measurements[0].provenance={...row.measurements[0].provenance,source_status:'historical_reviewed',live_evidence_available:false};
  row.measurements[0].goal_key='goal_'+('a'.repeat(64));row.measurements[0].context_key='ctx_'+('b'.repeat(64));return row;
};
"""


def teacher(assertions, setup="replies.push({ok:true,workspace:ws()});", role="school_uploader"):
    _run_page_js(render_student_summary_html({"role": role}), ENV + setup, assertions)


def admin(assertions, setup="replies.push({ok:true,workspace:archive()});", role="company_admin"):
    _run_page_js(render_admin_student_summaries_html({"role": role}), ENV + setup, assertions)


@pytest.mark.parametrize("renderer", [render_student_summary_html, render_admin_student_summaries_html])
def test_page_scope_safety_and_emitted_javascript(renderer):
    html = renderer({"username": "</script><script>alert(1)</script>", "role": "school_uploader"})
    assert "</script><script>alert(1)</script>" not in html
    assert "公开编号不等于匿名化" in html and "再识别" in html
    assert "研究或模型训练权限" in html and "原有 60 天" in html
    assert 'name="viewport"' in html and 'id="mainContent"' in html
    assert '.skip-link:not(:focus-visible)' in html and 'clip-path:inset(50%)' in html
    assert 'id="mainContent" tabindex="-1"' in html
    assert not re.search(r'<script[^>]+src=', html)
    script = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    assert ".innerHTML" not in script
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for generated JavaScript validation")
    result = subprocess.run([node, "--check"], input=script, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_teacher_requires_role_student_and_explicit_verification():
    teacher("assert.equal(requests.length,0);assert.equal(byId('snapshotFields').disabled,true);", "", role="company_admin")
    teacher("assert.equal(requests.length,0);", "location.search='';")
    teacher(r"""
    assert.equal(future('2099-01-01'),true);assert.equal(future('2000-01-01'),false);
    assert.equal(future('2099-01-01T00:00:00+08:00'),true);assert.equal(future('dddd-dd-dd'),false);
    assert.equal(requests[0].url,'/api/v1/demo2/student-summaries/student?student_id=s1');
    assert.equal(byId('snapshotFields').disabled,true);await verify();assert.equal(byId('snapshotFields').disabled,false);
    assert.equal(byId('authorizationFields').disabled,true);
    assert.match(byId('studentMeta').textContent,/T-1.*Synthetic class/);
    """)


def test_authorization_default_limit_reference_review_and_exact_payload():
    teacher(r"""
    assert.equal(byId('validUntil').value,dayAfter(60));assert.equal(byId('validUntil').max,dayAfter(365));
    await verify();byId('authorizationConfirmed').checked=true;
    await byId('authorizationForm').fire('submit',submit);assert.equal(pending,null);
    byId('authorizationReference').value='Synthetic approval';byId('validUntil').value=dayAfter(366);
    await byId('authorizationForm').fire('submit',submit);assert.equal(pending,null);
    byId('validUntil').value=dayAfter(60);await byId('authorizationForm').fire('submit',submit);
    assert.equal(requests.length,1);assert.equal(byId('commitButton').disabled,true);
    await confirmReview();window.confirm=()=>false;await byId('commitButton').fire('click');assert.equal(requests.length,1);
    window.confirm=()=>true;replies.push({ok:true},{ok:true,workspace:ws()});await byId('commitButton').fire('click');
    const post=requests.find(x=>x.options.method==='POST');
    assert.deepEqual(JSON.parse(post.options.body),{student_id:'s1',reference:'Synthetic approval',valid_until:dayAfter(60),confirmed:true});
    assert.equal(post.url,'/api/v1/demo2/student-summaries/authorization');
    assert.equal(requests.at(-1).options.method,undefined);assert.match(byId('pageMessage').textContent,/重新读取/);
    assert.equal(byId('studentVerified').checked,false);
    """, "replies.push({ok:true,workspace:ws(null)});")


@pytest.mark.parametrize("measurement_id", ["", "verified-measurement"])
def test_snapshot_exact_fields_optional_measurement_and_double_save_guard(measurement_id):
    teacher(r"""
    await verify();fillSnapshot();byId('measurementId').value=__ID__;
    await byId('snapshotForm').fire('submit',submit);assert.equal(requests.length,1);
    assert.match(byId('reviewPayload').textContent,/Local record/);await confirmReview();
    let finish;replies.push(()=>new Promise(resolve=>finish=()=>resolve({status:200,ok:true,json:async()=>({ok:true})})),{ok:true,workspace:ws('active',[snapshot])});
    const saving=byId('commitButton').fire('click');await flush();await byId('commitButton').fire('click');
    assert.equal(requests.filter(x=>x.options.method==='POST').length,1);assert.ok(!byId('pageMessage').textContent.includes('提交完成'));
    finish();await saving;
    const post=requests.find(x=>x.options.method==='POST');
    assert.equal(post.url,'/api/v1/demo2/student-summaries/snapshots');
    assert.deepEqual(JSON.parse(post.options.body),{student_id:'s1',authorization_id:'auth1',recorded_on:today(),source_ref:'Local record',learning_goals:'Goal',support_methods:'Support',domains:levels,measurement_id:__ID__,reviewed:true});
    assert.match(text(byId('snapshotList')),/Goal/);assert.equal(byId('learningGoals').value,'');
    assert.equal(byId('snapshotReviewed').checked,false);
    """.replace("__ID__", json.dumps(measurement_id)))


def test_draft_changes_invalidate_review_and_invalid_domains_never_post():
    teacher(r"""
    await verify();fillSnapshot();await byId('snapshotForm').fire('submit',submit);await confirmReview();
    await byId('snapshotForm').fire('input');assert.equal(pending,null);assert.equal(byId('reviewPanel').hidden,true);
    byId('domain_motor').value='diagnosis';await byId('snapshotForm').fire('submit',submit);assert.equal(pending,null);
    assert.equal(requests.length,1);
    """)


def test_write_disconnect_requires_reload_and_never_claims_saved():
    teacher(r"""
    await verify();fillSnapshot();await byId('snapshotForm').fire('submit',submit);await confirmReview();
    replies.push(new TypeError('offline'));await byId('commitButton').fire('click');
    assert.equal(uncertain,true);assert.equal(byId('snapshotFields').disabled,true);
    assert.match(byId('pageMessage').textContent,/结果待核对/);assert.equal(byId('learningGoals').value,'Goal');
    await byId('commitButton').fire('click');assert.equal(requests.filter(x=>x.options.method==='POST').length,1);
    replies.push({ok:true,workspace:ws()});await byId('reloadButton').fire('click');assert.equal(uncertain,false);
    assert.equal(byId('studentVerified').checked,false);
    """)


def test_reload_failure_after_write_does_not_claim_success_or_zero_records():
    teacher(r"""
    await verify();fillSnapshot();await byId('snapshotForm').fire('submit',submit);await confirmReview();
    replies.push({ok:true},{status:503,body:{error:{}}});await byId('commitButton').fire('click');
    assert.match(byId('pageMessage').textContent,/保存状态待核对/);
    assert.equal(workspace,null);assert.equal(byId('snapshotFields').disabled,true);
    assert.match(byId('snapshotList').textContent,/不能据此判断/);
    """)


@pytest.mark.parametrize("status", ["expired", "revoked"])
def test_inactive_authorization_redacts_even_if_response_includes_content(status):
    teacher(r"""
    await verify();assert.equal(byId('snapshotFields').disabled,true);
    assert.ok(!text(byId('snapshotList')).includes('Goal'));
    assert.match(byId('authorizationStatus').textContent,/到期|撤回/);
    """, f"replies.push({{ok:true,workspace:ws('{status}',[snapshot])}});")


def test_withdraw_uses_exact_contract_and_reloads():
    teacher(r"""
    await verify();await byId('withdrawButton').fire('click');await confirmReview();
    replies.push({ok:true},{ok:true,workspace:ws('revoked')});await byId('commitButton').fire('click');
    const post=requests.find(x=>x.options.method==='POST');
    assert.equal(post.url,'/api/v1/demo2/student-summaries/authorization/withdraw');
    assert.deepEqual(JSON.parse(post.options.body),{student_id:'s1',authorization_id:'auth1',confirmed:true});
    assert.match(byId('authorizationStatus').textContent,/撤回/);assert.equal(byId('snapshotFields').disabled,true);
    """)


def test_admin_role_search_pagination_and_failed_reads_are_not_empty():
    admin("assert.equal(requests.length,0);", "", role="school_uploader")
    admin(r"""
    assert.equal(requests[0].url,'/api/v1/demo2/student-summaries/admin?page=1&query=');
    const rows=text(byId('archiveRows'));assert.match(rows,/ps1.*channel_1/);
    replies.push({ok:true,workspace:archive(2)});await byId('nextPage').fire('click');assert.equal(page,2);
    byId('archiveQuery').value='channel_1 & test';replies.push({ok:true,workspace:archive()});await byId('searchForm').fire('submit',submit);
    assert.match(requests.at(-1).url,/page=1&query=channel_1%20%26%20test/);
    replies.push({status:503,body:{error:{}}});await byId('reloadButton').fire('click');
    assert.match(byId('resultStatus').textContent,/保留上次列表/);assert.equal(text(byId('archiveRows')),rows);
    """)


def test_admin_inspection_and_download_allowlist_no_identity_source_or_html():
    admin(r"""
    const value=exported();value.snapshots[0].learning_goals='<img src=x onerror=alert(1)>';
    replies.push(value);await openDetail('ps1');
    assert.ok(text(byId('detailRecords')).includes('<img src=x onerror=alert(1)>'));
    assert.ok(!text(byId('detailRecords')).includes('NEVER-EXPORT'));
    assert.ok(!text(byId('detailRecords')).includes('NEVER-NAME'));
    assert.ok(!byId('detailRecords').innerHTML.includes('<img'));
    replies.push(value);await byId('exportButton').fire('click');
    assert.equal(requests.filter(x=>x.url.includes('/export?')).length,2);
    const downloaded=JSON.parse(await blobs[0].text());
    assert.deepEqual(Object.keys(downloaded).sort(),['course_history','policy','public_id','snapshots','valid_until']);
    assert.deepEqual(downloaded.course_history,[]);
    assert.deepEqual(downloaded.policy,policy);
    assert.deepEqual(downloaded.snapshots[0].provenance,{source_type:'classroom_observation',source_version:2,rule_version:'v1',source_date:'2026-01-01'});
    assert.equal(downloaded.snapshots[0].reviewed,true);
    assert.ok(!JSON.stringify(downloaded).includes('NEVER-'));
    assert.deepEqual(downloaded.snapshots[0].measurement,{opportunities:8,observed:6,scores:{accuracy:2},assessment:{passed:false}});
    assert.equal(clicks[0].download,'authorized-student-summary.json');assert.deepEqual(revoked,['blob:synthetic']);
    """)


def test_admin_export_rechecks_authority_and_rejects_mismatched_or_expired_detail():
    admin(r"""
    replies.push(exported());await openDetail('ps1');assert.equal(byId('exportButton').disabled,false);
    replies.push({status:410,body:{error:{}}});await byId('exportButton').fire('click');
    assert.equal(blobs.length,0);assert.equal(detail,null);assert.equal(byId('detailSection').hidden,true);
    replies.push({...exported(),public_id:'another'});await openDetail('ps1');assert.equal(detail,null);
    replies.push({...exported(),valid_until:'2000-01-01'});await openDetail('ps1');assert.equal(detail,null);
    """)


@pytest.mark.parametrize("status,label", [
    ("withheld", "原测量已失效，仅保留教师核对摘要"),
    ("current", "原测量已核验，当前有效"),
    ("manual_reviewed", "教师已核对摘要，未关联测量记录"),
])
def test_source_lifecycle_keeps_reviewed_summary_and_export_metadata(status, label):
    assertions = r"""
    const value=exported(),row=value.snapshots[0];row.provenance.source_status=__STATUS__;
    if(__STATUS__!=='current')row.measurement=null;
    replies.push(value);await openDetail('ps1');
    const rendered=text(byId('detailRecords'));
    assert.ok(rendered.includes(__LABEL__));assert.ok(rendered.includes('Goal'));assert.ok(rendered.includes('Support'));
    assert.equal(byId('exportButton').disabled,false);
    replies.push(value);await byId('exportButton').fire('click');
    const result=JSON.parse(await blobs[0].text());
    assert.equal(result.snapshots[0].provenance.source_status,__STATUS__);
    assert.equal(result.snapshots[0].reviewed,true);assert.deepEqual(result.policy,policy);
    assert.equal(result.snapshots[0].learning_goals,'Goal');assert.deepEqual(result.snapshots[0].domains,levels);
    if(__STATUS__!=='current')assert.equal(result.snapshots[0].measurement,null);
    """.replace("__STATUS__", json.dumps(status)).replace("__LABEL__", json.dumps(label))
    admin(assertions)
    teacher(r"""
    assert.ok(text(byId('snapshotList')).includes(__LABEL__));
    assert.ok(text(byId('snapshotList')).includes('Goal'));
    """.replace("__LABEL__", json.dumps(label)),
        "const value=ws('active',[{...snapshot,measurement:null,provenance:{...snapshot.provenance,source_status:"
        + json.dumps(status) + "}}]);replies.push({ok:true,workspace:value});")


def test_admin_forbidden_read_clears_stale_archive_and_detail():
    admin(r"""
    replies.push(exported());await openDetail('ps1');
    replies.push({status:403,body:{error:{}}});await byId('reloadButton').fire('click');
    assert.equal(workspace,null);assert.equal(text(byId('archiveRows')),'');
    assert.equal(detail,null);assert.equal(byId('detailSection').hidden,true);
    """)


def test_teacher_timeout_and_student_mismatch_fail_closed():
    teacher(r"""
    assert.equal(workspace,null);assert.equal(byId('snapshotFields').disabled,true);
    assert.match(byId('snapshotList').textContent,/不能据此判断/);
    """, "const wrong=ws();wrong.student.student_id='other';replies.push({ok:true,workspace:wrong});")
    teacher(r"""
    [...timers.values()][0].fn();await flush();assert.equal(workspace,null);
    assert.match(byId('pageMessage').textContent,/超时/);assert.equal(timers.size,0);
    """, "replies.push((_url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})))));")


@pytest.mark.parametrize("include_existing", [False, True])
def test_automatic_opt_in_review_exact_payload_and_readback(include_existing):
    teacher(r"""
    assert.equal(byId('autoEnabled').checked,false);assert.equal(byId('automaticFields').disabled,true);
    assert.equal(byId('includeExisting').checked,false);assert.equal(byId('includeExisting').disabled,true);
    await byId('automaticForm').fire('submit',submit);assert.equal(pending,null);
    await verify();await byId('automaticForm').fire('submit',submit);assert.equal(pending,null);
    byId('autoEnabled').checked=true;await byId('autoEnabled').fire('change');
    assert.equal(byId('includeExisting').disabled,false);byId('includeExisting').checked=__EXISTING__;
    await byId('automaticForm').fire('submit',submit);assert.equal(requests.length,1);
    assert.match(byId('reviewTitle').textContent,/开启/);assert.equal(byId('commitButton').disabled,true);
    await confirmReview();window.confirm=()=>false;await byId('commitButton').fire('click');assert.equal(requests.length,1);
    const next=ws();next.authorization.automatic_archiving={enabled:true,include_existing:__EXISTING__,enabled_at:'2026-10-16T10:00:00+08:00'};
    next.course_history=[course('pending_review')];window.confirm=()=>true;replies.push({ok:true,workspace:next},{ok:true,workspace:next});
    await byId('commitButton').fire('click');
    const post=requests.find(x=>x.options.method==='POST');assert.equal(post.url,API+'/automatic');
    assert.deepEqual(JSON.parse(post.options.body),{student_id:'s1',authorization_id:'auth1',enabled:true,confirmed:true,include_existing:__EXISTING__});
    assert.equal(requests.at(-1).url,API+'/student?student_id=s1');assert.equal(byId('studentVerified').checked,false);
    assert.equal(byId('autoEnabled').checked,true);assert.equal(byId('includeExisting').checked,false);
    assert.match(byId('automaticStatus').textContent,/已开启/);assert.match(text(byId('courseHistoryList')),/course-public-1/);
    assert.equal(requests.filter(x=>x.url.endsWith('/snapshots')).length,0);
    """.replace("__EXISTING__", json.dumps(include_existing)))


def test_automatic_pause_keeps_history_and_invalidates_changed_preview():
    teacher(r"""
    assert.equal(byId('autoEnabled').checked,true);await verify();
    byId('includeExisting').checked=true;await byId('automaticForm').fire('submit',submit);await confirmReview();
    await byId('automaticForm').fire('input');assert.equal(pending,null);
    byId('autoEnabled').checked=false;await byId('autoEnabled').fire('change');
    assert.equal(byId('includeExisting').checked,false);assert.equal(byId('includeExisting').disabled,true);
    await byId('automaticForm').fire('submit',submit);assert.match(byId('reviewTitle').textContent,/暂停/);await confirmReview();
    let confirmation='';window.confirm=value=>{confirmation=value;return true;};
    const next=ws();next.authorization.automatic_archiving={enabled:false,include_existing:false};next.course_history=[course()];
    replies.push({ok:true,workspace:next},{ok:true,workspace:next});await byId('commitButton').fire('click');
    assert.match(confirmation,/不会删除/);assert.equal(byId('autoEnabled').checked,false);
    assert.match(text(byId('courseHistoryList')),/course-public-1/);
    assert.deepEqual(JSON.parse(requests.find(x=>x.options.method==='POST').options.body),{student_id:'s1',authorization_id:'auth1',enabled:false,confirmed:true,include_existing:false});
    """, "const initial=ws();initial.authorization.automatic_archiving={enabled:true,include_existing:true};initial.course_history=[course()];replies.push({ok:true,workspace:initial});")


def test_automatic_timeout_locks_writes_and_stale_authorization_never_posts():
    teacher(r"""
    await verify();byId('autoEnabled').checked=true;await byId('automaticForm').fire('submit',submit);await confirmReview();
    workspace.authorization.valid_until='2000-01-01';await byId('commitButton').fire('click');
    assert.equal(requests.length,1);assert.equal(pending,null);
    workspace.authorization.valid_until='2099-01-01';await byId('automaticForm').fire('submit',submit);await confirmReview();
    replies.push(new TypeError('offline'));await byId('commitButton').fire('click');
    assert.equal(uncertain,true);assert.equal(byId('automaticFields').disabled,true);
    assert.match(byId('pageMessage').textContent,/结果待核对/);
    await byId('commitButton').fire('click');assert.equal(requests.filter(x=>x.options.method==='POST').length,1);
    """)


@pytest.mark.parametrize("status", ["pending_review", "reviewed", "source_withheld"])
def test_course_history_same_teacher_company_allowlist_and_score_gating(status):
    shared = r"""
    const records=[course(__STATUS__)];
    const safe=safeCourseHistory(records)[0];
    assert.equal(safe.entry_id,'course-public-1');assert.equal(safe.revision,2);assert.equal(safe.date_basis,'upload_date');
    assert.deepEqual(safe.media,{duration_sec:123.5,has_audio:true});
    assert.equal(safe.provenance.source_type,'automatic_course_archive');assert.equal(safe.provenance.rule_version,'course-archive-v1');
    assert.ok(!JSON.stringify(safe).includes('NEVER-'));assert.ok(!JSON.stringify(safe).includes('999'));
    if(__STATUS__==='reviewed')assert.equal(safe.measurements[0].measurement.scores.accuracy,2);
    else assert.deepEqual(safe.measurements,[]);
    """.replace("__STATUS__", json.dumps(status))
    teacher(shared + r"""
    const rendered=text(byId('courseHistoryList'));assert.match(rendered,/course-public-1/);
    assert.match(rendered,/上传日期：2026-10-16/);assert.match(rendered,/技术信息（不代表学生表现）/);
    assert.match(rendered,/单帧人工确认/);assert.match(rendered,/不代表整段持续追踪/);
    assert.equal(rendered.includes('已核验测量（非预测）'),__STATUS__==='reviewed');
    assert.equal(rendered.includes('6.85'),__STATUS__==='reviewed');
    if(__STATUS__==='pending_review')assert.match(rendered,/本课身份已绑定 · 待复核/);
    if(__STATUS__==='source_withheld')assert.match(rendered,/依据失效/);
    """.replace("__STATUS__", json.dumps(status)),
        "const next=ws();next.course_history=[course(" + json.dumps(status) + ")];replies.push({ok:true,workspace:next});")
    admin(shared + r"""
    const value=exported();value.course_history=records;replies.push(value);await openDetail('ps1');
    assert.match(text(byId('detailCourseHistory')),/course-public-1/);
    assert.equal(text(byId('detailCourseHistory')).includes('6.85'),safe.status==='reviewed');
    replies.push(value);await byId('exportButton').fire('click');const downloaded=JSON.parse(await blobs[0].text());
    assert.deepEqual(downloaded.course_history,[safe]);assert.deepEqual(downloaded.policy,policy);
    assert.equal(downloaded.snapshots[0].reviewed,true);assert.ok(!JSON.stringify(downloaded).includes('NEVER-'));
    """)


def test_course_history_rejects_unreviewed_stale_or_unknown_measurement_sources():
    admin(r"""
    for(const change of [row=>row.reviewed=false,row=>row.provenance.source_status='withheld',row=>delete row.provenance.source_status]){
      const row=course();change(row);const safe=safeCourseHistory([row])[0];assert.deepEqual(safe.measurements,[]);
    }
    const row=course();row.measurements.push({measurement:snapshot.measurement,provenance:{source_status:'withheld'}});
    row.measurements.push({measurement:snapshot.measurement,provenance:{}});
    row.provenance.whole_lesson_tracking=false;row.provenance.scene_metrics_attributed_to_student=false;
    const clean=safeCourseHistory([row])[0];assert.equal(clean.measurements[1].measurement,null);assert.equal(clean.measurements[2].measurement,null);
    assert.equal(clean.provenance.whole_lesson_tracking,false);assert.equal(clean.provenance.scene_metrics_attributed_to_student,false);
    assert.equal(clean.provenance.identity_scope,'confirmed_sample_frame');
    assert.equal(safeCourseHistory([course('pending_review')])[0].provenance.source_status,'technical_only');
    const bad=course();bad.media={duration_sec:Infinity,has_audio:'true',filename:'NEVER-FILENAME'};
    bad.measurements[0].measurement={opportunities:{name:'NEVER-NAME'},observed:true,scores:{accuracy:'NEVER-NAME',independence:NaN},assessment:{passed:'NEVER-NAME',confidence:Infinity}};
    const strict=safeCourseHistory([bad])[0];assert.deepEqual(strict.media,{});assert.deepEqual(strict.measurements[0].measurement,{scores:{},assessment:{}});
    const value=exported();value.course_history=[{...course(),entry_id:'<img src=x onerror=alert(1)>'}];
    replies.push(value);await openDetail('ps1');assert.ok(text(byId('detailCourseHistory')).includes('<img'));
    assert.equal(byId('detailCourseHistory').innerHTML,'');
    """)


def test_course_history_missing_malformed_expired_and_denied_are_distinct():
    teacher(r"""
    assert.match(text(byId('courseHistoryList')),/尚无已归档课程/);assert.equal(byId('autoEnabled').checked,false);
    """)
    teacher(r"""
    assert.equal(workspace,null);assert.match(text(byId('courseHistoryList')),/不能据此判断/);
    assert.equal(byId('automaticFields').disabled,true);
    """, "const next=ws();next.course_history={};replies.push({ok:true,workspace:next});")
    teacher(r"""
    assert.ok(!text(byId('courseHistoryList')).includes('course-public-1'));assert.equal(byId('autoEnabled').checked,false);
    """, "const next=ws('expired');next.course_history=[course()];next.authorization.automatic_archiving={enabled:true};replies.push({ok:true,workspace:next});")
    admin(r"""
    const value=exported();value.course_history=[course()];replies.push(value);await openDetail('ps1');
    replies.push({status:403,body:{error:{}}});await byId('reloadButton').fire('click');
    assert.equal(text(byId('detailCourseHistory')),'');assert.equal(detail,null);
    const invalid=exported();invalid.course_history={};assert.throws(()=>cleanExport(invalid));
    invalid.course_history=[{...course(),status:'invented'}];assert.throws(()=>cleanExport(invalid));
    """)


def test_historical_approved_course_visible_but_not_current_and_export_preserved():
    message = '历史已核准 · 原视频已按期清理，无法回看原始证据'
    checks = r"""
    const rendered=text(byId(__TARGET__));
    assert.ok(rendered.includes(__MESSAGE__));assert.ok(rendered.includes('6.85'));
    assert.ok(rendered.includes('历史已核准测量（非当前证据、非预测）'));
    assert.ok(!rendered.includes('已核验测量（非预测）'));
    """.replace('__MESSAGE__', json.dumps(message))
    teacher(checks.replace('__TARGET__', "'courseHistoryList'"),
            "const initial=ws();initial.course_history=[historicalEntry()];replies.push({ok:true,workspace:initial});")
    admin(r"""
    const value=exported();value.course_history=[historicalEntry()];replies.push(value);await openDetail('ps1');
    """ + checks.replace('__TARGET__', "'detailCourseHistory'") + r"""
    replies.push(value);await byId('exportButton').fire('click');const downloaded=JSON.parse(await blobs[0].text());
    const row=downloaded.course_history[0];assert.equal(row.status,'historical_reviewed');assert.equal(row.reviewed,true);
    assert.equal(row.live_evidence_available,false);assert.equal(row.provenance.live_evidence_available,false);
    assert.equal(row.provenance.source_status,'historical_reviewed');
    assert.equal(row.measurements[0].provenance.source_status,'historical_reviewed');
    assert.equal(row.measurements[0].provenance.live_evidence_available,false);
    assert.equal(row.measurements[0].measurement.assessment.overall_score,6.85);
    assert.equal(row.measurements[0].goal_key,'goal_'+('a'.repeat(64)));assert.equal(row.measurements[0].context_key,'ctx_'+('b'.repeat(64)));
    assert.deepEqual(downloaded.policy,policy);assert.ok(!JSON.stringify(downloaded).includes('NEVER-'));
    """)


def test_historical_status_never_promotes_unreviewed_withheld_or_current_measurements():
    admin(r"""
    for(const change of [row=>row.reviewed=false,row=>row.status='pending_review',row=>row.status='source_withheld',
      row=>row.provenance.source_status='withheld',row=>row.provenance.source_status='current',
      row=>{delete row.provenance.source_status;},
      row=>{delete row.live_evidence_available;delete row.provenance.live_evidence_available;},
      row=>row.live_evidence_available=true,row=>row.provenance.live_evidence_available=true]){
      const row=historicalEntry();change(row);const safe=safeCourseHistory([row])[0];
      assert.deepEqual(safe.measurements,[]);assert.equal(historicalCourse(safe),false);showCourseHistory('detailCourseHistory',[safe]);
      const rendered=text(byId('detailCourseHistory'));assert.ok(!rendered.includes('6.85'));assert.ok(!rendered.includes('历史已核准测量'));
    }
    for(const change of [item=>item.provenance.source_status='current',item=>item.provenance.source_status='withheld',
      item=>{delete item.provenance.source_status;},item=>item.reviewed=false,item=>item.provenance.live_evidence_available=true]){
      const row=historicalEntry();change(row.measurements[0]);const safe=safeCourseHistory([row])[0];
      assert.equal(safe.measurements[0].measurement,null);showCourseHistory('detailCourseHistory',[safe]);assert.ok(!text(byId('detailCourseHistory')).includes('6.85'));
    }
    const live=course();live.measurements[0].provenance.source_status='historical_reviewed';
    assert.equal(safeCourseHistory([live])[0].measurements[0].measurement,null);
    for(const flagLocation of ['root','provenance']){
      const row=historicalEntry();if(flagLocation==='root')delete row.provenance.live_evidence_available;else delete row.live_evidence_available;
      assert.equal(safeCourseHistory([row])[0].measurements[0].measurement.assessment.overall_score,6.85);
    }
    """)
    teacher(r"""
    assert.ok(!text(byId('courseHistoryList')).includes('6.85'));assert.match(text(byId('courseHistoryList')),/不可访问/);
    """, "const initial=ws('expired');initial.course_history=[historicalEntry()];replies.push({ok:true,workspace:initial});")


def test_course_short_titles_beijing_times_and_unchanged_export_values():
    setup = r"""
    const longCourse=course();longCourse.entry_id='ch_0123456789abcdef0123456789abcdef';
    longCourse.created_at='2026-10-16T16:02:59.123456Z';longCourse.updated_at='2026-10-17T00:03:59.999999+08:00';
    """
    assertions = r"""
    process.env.TZ='America/Los_Angeles';
    assert.equal(beijingTime('2026-10-16T16:02:59.123456Z'),'2026-10-17 00:02');
    assert.equal(beijingTime('2026-10-17T00:03:59.999999+08:00'),'2026-10-17 00:03');
    for(const value of [null,undefined,'','broken','2026-10-17','2026-10-17T00:03:00'])assert.equal(beijingTime(value),'未返回');
    assert.equal(shortCourseId('course-public-1'),'course-public-1');
    const list=byId(__TARGET__),heading=list.children[0].children[0];
    assert.equal(heading.textContent,'课程 ch_01234567...cdef');assert.equal(heading.title,longCourse.entry_id);
    const rendered=text(list);assert.ok(!rendered.includes(longCourse.entry_id));
    assert.match(rendered,/归档时间（北京时间）：2026-10-17 00:02 · 更新时间：2026-10-17 00:03/);
    assert.ok(!rendered.includes('T16:02'));assert.ok(!rendered.includes('999999'));
    """
    teacher(assertions.replace('__TARGET__', "'courseHistoryList'") + r"""
    assert.match(byId('automaticStatus').textContent,/开启时间（北京时间）：2026-10-17 00:02/);
    assert.ok(!byId('automaticStatus').textContent.includes('123456'));
    """, setup + "const initial=ws();initial.course_history=[longCourse];initial.authorization.automatic_archiving={enabled:true,enabled_at:longCourse.created_at};replies.push({ok:true,workspace:initial});")
    admin(r"""
    const value=exported();value.course_history=[longCourse];replies.push(value);await openDetail('ps1');
    """ + assertions.replace('__TARGET__', "'detailCourseHistory'") + r"""
    replies.push(value);await byId('exportButton').fire('click');const downloaded=JSON.parse(await blobs[0].text());
    assert.equal(downloaded.course_history[0].entry_id,longCourse.entry_id);
    assert.equal(downloaded.course_history[0].created_at,longCourse.created_at);
    assert.equal(downloaded.course_history[0].updated_at,longCourse.updated_at);
    """, setup + "replies.push({ok:true,workspace:archive()});")


def test_export_keeps_only_safe_goal_and_context_keys_without_grouping_scores():
    admin(r"""
    const value=exported(),row=course();value.course_history=[row];
    row.measurements[0].goal_key='goal_'+('0123456789abcdef'.repeat(4));row.measurements[0].context_key='ctx_'+('abcdef0123456789'.repeat(4));
    row.measurements[0].goal_id='NEVER-PRIVATE';row.measurements[0].context='NEVER-CONTEXT';row.measurements[0].name='NEVER-NAME';
    const invalidKeys=['goal_<img src=x>','goal_name','goal_'+('a'.repeat(65)),'goal_'+('a'.repeat(63)),'ctx_1234','goal_',42,{},['goal_abcd']];
    for(const goal of invalidKeys){const candidate=course();candidate.measurements[0].goal_key=goal;assert.equal(safeCourseHistory([candidate])[0].measurements[0].goal_key,undefined);}
    for(const context of ['ctx_<img>','ctx_name','ctx_',42,{},'goal_abc']){const candidate=course();candidate.measurements[0].context_key=context;assert.equal(safeCourseHistory([candidate])[0].measurements[0].context_key,undefined);}
    replies.push(value);await openDetail('ps1');replies.push(value);await byId('exportButton').fire('click');
    const downloaded=JSON.parse(await blobs[0].text()),measurement=downloaded.course_history[0].measurements[0];
    assert.equal(measurement.goal_key,row.measurements[0].goal_key);assert.equal(measurement.context_key,row.measurements[0].context_key);
    assert.equal(measurement.measurement.assessment.overall_score,6.85);assert.ok(!JSON.stringify(downloaded).includes('NEVER-'));
    assert.ok(!text(byId('detailCourseHistory')).includes('平均分'));
    """)


def test_mock_browser_teacher_save_admin_preview_and_mobile_layout(tmp_path):
    node = shutil.which("node")
    candidates = [os.environ.get("DEMO2_PLAYWRIGHT_MODULE", ""),
                  str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"),
                  str(Path.home() / "AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright")]
    module = next((value for value in candidates if value and Path(value).exists()), None)
    if not node or not module:
        pytest.skip("Installed Node and Playwright required; no downloads")
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "AppData/Local/ms-playwright")))
    executables = [os.environ.get("DEMO2_BROWSER_EXECUTABLE", ""),
                   *(str(p) for p in sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)),
                   "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]
    executable = next((value for value in executables if value and Path(value).exists()), None)
    data = dict(module=module, executable=executable, shots=str(tmp_path),
                teacher=render_student_summary_html({"role": "school_uploader"}),
                admin=render_admin_student_summaries_html({"role": "company_admin"}))
    script = r"""
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8')),assert=require('node:assert/strict');
const {chromium}=require(input.module),browser=await chromium.launch({headless:true,...(input.executable?{executablePath:input.executable}:{})});
try{
 const page=await browser.newPage(),errors=[],external=[],posts=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 let auth=null,snapshots=[],courseHistory=[];
 const courseRows=['pending_review','reviewed','source_withheld'].map((status,index)=>({entry_id:'course-public-'+(index+1),recorded_on:'2026-10-16',date_basis:index?'lesson_date':'upload_date',revision:1,status,reviewed:status==='reviewed',media:{duration_sec:90,has_audio:true,filename:'DO-NOT-DISPLAY'},measurements:[{measurement:{scores:{accuracy:2},assessment:{overall_score:6.85},scene_metric:'DO-NOT-DISPLAY'},provenance:{source_type:'classroom_observation',source_status:'current'}}],provenance:{source_type:'automatic_course_archive',rule_version:'course-archive-v1',source_status:status==='source_withheld'?'withheld':status==='pending_review'?'technical_only':'current',identity_scope:'confirmed_sample_frame',whole_lesson_tracking:false,scene_metrics_attributed_to_student:false},created_at:'2026-10-16T10:00:00+08:00',updated_at:'2026-10-16T11:00:00+08:00',task_id:'DO-NOT-DISPLAY'}));
 courseRows[0].entry_id='ch_0123456789abcdef0123456789abcdef';
 courseRows[0].created_at='2026-10-16T02:00:00.123456Z';courseRows[0].updated_at='2026-10-16T03:00:00.654321Z';
 courseRows[1].measurements[0].goal_key='goal_'+('a'.repeat(64));courseRows[1].measurements[0].context_key='ctx_'+('b'.repeat(64));
 async function assertSkipHidden(){
  const value=await page.locator('.skip-link').evaluate(node=>({opacity:getComputedStyle(node).opacity,clip:getComputedStyle(node).clipPath,visible:node.matches(':focus-visible'),pointer:getComputedStyle(node).pointerEvents}));
  assert.equal(value.visible,false);assert.equal(value.opacity,'0');assert.equal(value.clip,'inset(50%)');assert.equal(value.pointer,'none');
 }
 async function checkSkipKeyboardAndPointer(){
  await assertSkipHidden();await page.keyboard.press('Tab');
  const value=await page.locator('.skip-link').evaluate(node=>({focused:document.activeElement===node,visible:node.matches(':focus-visible'),opacity:getComputedStyle(node).opacity,rect:{x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y}}));
  assert.equal(value.focused,true);assert.equal(value.visible,true);assert.equal(value.opacity,'1');assert.equal(value.rect.x,8);assert.equal(value.rect.y,8);
  await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>document.activeElement.id),'mainContent');await assertSkipHidden();
  await page.locator('#reloadButton').click();await page.waitForFunction(()=>!document.getElementById('reloadButton').disabled);
  await page.locator('.skip-link').evaluate(node=>node.focus());await assertSkipHidden();await page.locator('h1').click();
 }
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;
  if(url.origin!=='http://summary.test'){external.push(req.url());return route.abort();}
  const json=value=>route.fulfill({contentType:'application/json',body:JSON.stringify(value)});
  if(path==='/demo2/student-summary')return route.fulfill({contentType:'text/html',body:input.teacher});
  if(path==='/demo2/admin/student-summaries')return route.fulfill({contentType:'text/html',body:input.admin});
  if(path.endsWith('/student'))return json({ok:true,workspace:{student:{student_id:'s1',display_name:'Synthetic student',student_code:'TEST',class_name:'Class'},authorization:auth,snapshots,course_history:courseHistory}});
  if(req.method()==='POST'){
   const payload=req.postDataJSON();posts.push({path,payload});
   if(path.endsWith('/authorization'))auth={authorization_id:'a1',status:'active',valid_until:payload.valid_until};
   if(path.endsWith('/snapshots'))snapshots.push({...payload,snapshot_id:'ss1'});
   if(path.endsWith('/automatic')){auth.automatic_archiving={enabled:payload.enabled,include_existing:payload.include_existing,enabled_at:'2026-10-16T10:00:00+08:00'};if(payload.enabled)courseHistory=courseRows;}
   if(path.endsWith('/withdraw')){auth.status='revoked';snapshots=[];}
   return json({ok:true});
  }
  if(path.endsWith('/admin'))return json({ok:true,workspace:{items:[{public_id:'ps1',channel_id:'channel_1',course_count:courseHistory.length,latest_course_at:'2026-10-16',snapshot_count:1,latest_recorded_on:'2026-01-01',valid_until:'2099-01-01'}],pagination:{page:1,page_size:20,total:1,total_pages:1},policy:{}}});
  if(path.endsWith('/export'))return json({public_id:'ps1',valid_until:'2099-01-01',course_history:courseHistory,policy:{purpose:'educational_followup',research:false,training:false,pseudonymous_not_anonymous:true,expiry_exclusive:true},snapshots:[{recorded_on:'2026-01-01',learning_goals:'<img src=x onerror=alert(1)>',support_methods:'Support',domains:{},provenance:{source_type:'manual_pedagogic_summary',source_version:1,rule_version:'v1',source_date:'2026-01-01'},reviewed:true,source_ref:'DO-NOT-DISPLAY',student_name:'DO-NOT-DISPLAY'}]});
  return route.abort();
 });
 await page.goto('http://summary.test/demo2/student-summary?student_id=s1');
 await checkSkipKeyboardAndPointer();
 await page.locator('#studentVerified').check();
 await page.locator('#authorizationReference').fill('Synthetic approval');await page.locator('#authorizationConfirmed').check();
 await page.getByRole('button',{name:'核对授权内容',exact:true}).click();assert.equal(posts.length,0);
 await page.locator('#reviewConfirmed').check();await page.locator('#commitButton').click();
 await page.waitForFunction(()=>document.getElementById('authorizationStatus').textContent.includes('授权有效'));
 await page.locator('#studentVerified').check();await page.locator('#sourceRef').fill('Synthetic local record');
 await page.locator('#learningGoals').fill('Goal');await page.locator('#supportMethods').fill('Support');await page.locator('#snapshotReviewed').check();
 await page.getByRole('button',{name:'核对选定摘要',exact:true}).click();await page.locator('#reviewConfirmed').check();await page.locator('#commitButton').click();
 await page.waitForFunction(()=>document.getElementById('snapshotList').textContent.includes('Goal'));
 assert.equal(posts.length,2);assert.equal(posts[1].payload.measurement_id,'');assert.equal(posts[1].payload.reviewed,true);
 await page.locator('#studentVerified').check();assert.equal(await page.locator('#autoEnabled').isChecked(),false);
 await page.locator('#autoEnabled').check();assert.equal(await page.locator('#includeExisting').isChecked(),false);
 await page.locator('#automaticReviewButton').click();assert.equal(posts.length,2);
 await page.locator('#reviewConfirmed').check();await page.locator('#commitButton').click();
 await page.waitForFunction(()=>document.getElementById('automaticStatus').textContent.includes('已开启'));
 assert.deepEqual(posts[2].payload,{student_id:'s1',authorization_id:'a1',enabled:true,confirmed:true,include_existing:false});
 assert.equal(await page.locator('#courseHistoryList article').count(),3);
 assert.equal(await page.locator('#courseHistoryList article h3').first().textContent(),'课程 ch_01234567...cdef');
 assert.equal(await page.locator('#courseHistoryList article h3').first().getAttribute('title'),courseRows[0].entry_id);
 assert.ok((await page.locator('#courseHistoryList article').first().textContent()).includes('2026-10-16 10:00'));
 assert.ok(!(await page.locator('#courseHistoryList').textContent()).includes('T02:00'));
 assert.ok((await page.locator('#automaticStatus').textContent()).includes('2026-10-16 10:00'));
 assert.equal(await page.locator('#courseHistoryList article').nth(0).textContent().then(t=>t.includes('已核验测量')),false);
 assert.equal(await page.locator('#courseHistoryList article').nth(1).textContent().then(t=>t.includes('已核验测量')),true);
 assert.equal(await page.locator('#courseHistoryList article').nth(1).textContent().then(t=>t.includes('6.85')),true);
 assert.equal(await page.locator('#courseHistoryList article').nth(0).getAttribute('data-course-status'),'pending_review');
 assert.equal(await page.locator('#courseHistoryList article').nth(2).textContent().then(t=>t.includes('已核验测量')),false);
 await page.locator('#studentVerified').check();await page.locator('#autoEnabled').uncheck();await page.locator('#automaticReviewButton').click();
 await page.locator('#reviewConfirmed').check();await page.locator('#commitButton').click();
 await page.waitForFunction(()=>document.getElementById('automaticStatus').textContent.includes('已暂停新增归档'));
 assert.equal(posts[3].payload.enabled,false);assert.equal(await page.locator('#courseHistoryList article').count(),3);
 await page.locator('#studentVerified').check();await page.locator('#autoEnabled').check();await page.locator('#includeExisting').check();
 await page.locator('#automaticReviewButton').click();await page.locator('#reviewConfirmed').check();await page.locator('#commitButton').click();
 await page.waitForFunction(()=>document.getElementById('automaticStatus').textContent.includes('已授权补录已有课程'));assert.equal(posts[4].payload.include_existing,true);
 for(const width of [320,390,768,1366]){await page.setViewportSize({width,height:900});await page.evaluate(()=>window.scrollTo(0,600));await assertSkipHidden();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:input.shots+'/teacher-'+width+'.png',fullPage:true});}
 await page.goto('http://summary.test/demo2/admin/student-summaries');await checkSkipKeyboardAndPointer();await page.getByRole('button',{name:'查看摘要',exact:true}).click();
 await page.waitForFunction(()=>!document.getElementById('exportButton').disabled);
 assert.equal(await page.locator('#detailRecords img').count(),0);assert.ok((await page.locator('#detailRecords').textContent()).includes('<img'));
 assert.ok(!(await page.locator('#detailRecords').textContent()).includes('DO-NOT-DISPLAY'));
 assert.equal(await page.locator('#detailCourseHistory article').count(),3);
 assert.equal(await page.locator('#detailCourseHistory article h3').first().textContent(),'课程 ch_01234567...cdef');
 assert.equal(await page.locator('#detailCourseHistory article h3').first().getAttribute('title'),courseRows[0].entry_id);
 assert.equal(await page.locator('#detailCourseHistory article').nth(1).textContent().then(t=>t.includes('6.85')),true);
 assert.ok(!(await page.locator('#detailCourseHistory').textContent()).includes('DO-NOT-DISPLAY'));
 const downloadPending=page.waitForEvent('download');await page.locator('#exportButton').click();const download=await downloadPending;
 const stream=await download.createReadStream(),chunks=[];for await(const chunk of stream)chunks.push(chunk);
 const exported=JSON.parse(Buffer.concat(chunks).toString('utf8'));
 assert.equal(exported.policy.purpose,'educational_followup');assert.equal(exported.policy.research,false);assert.equal(exported.course_history.length,3);
 assert.deepEqual(exported.course_history[0].measurements,[]);assert.equal(exported.course_history[1].measurements[0].measurement.scores.accuracy,2);
 assert.equal(exported.course_history[1].measurements[0].measurement.assessment.overall_score,6.85);
 assert.equal(exported.course_history[1].measurements[0].goal_key,'goal_'+('a'.repeat(64)));
 assert.equal(exported.course_history[1].measurements[0].context_key,'ctx_'+('b'.repeat(64)));
 assert.equal(exported.course_history[0].entry_id,courseRows[0].entry_id);assert.equal(exported.course_history[0].created_at,courseRows[0].created_at);
 assert.equal(exported.course_history[0].provenance.source_status,'technical_only');
 assert.equal(exported.course_history[0].provenance.whole_lesson_tracking,false);assert.equal(exported.course_history[0].provenance.scene_metrics_attributed_to_student,false);
 assert.deepEqual(exported.course_history[2].measurements,[]);assert.ok(!JSON.stringify(exported).includes('DO-NOT-DISPLAY'));
 for(const width of [320,390,1366]){await page.setViewportSize({width,height:900});await page.evaluate(()=>window.scrollTo(0,500));await assertSkipHidden();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:input.shots+'/admin-'+width+'.png',fullPage:true});}
 const historical=courseRows[1];historical.status='historical_reviewed';historical.reviewed=true;historical.live_evidence_available=false;
 historical.provenance.source_status='historical_reviewed';historical.provenance.live_evidence_available=false;
 historical.measurements[0].provenance.source_status='historical_reviewed';historical.measurements[0].provenance.live_evidence_available=false;
 await page.locator('#reloadButton').click();await page.getByRole('button',{name:'查看摘要',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('detailCourseHistory').textContent.includes('历史已核准 · 原视频已按期清理，无法回看原始证据'));
 const historyText=await page.locator('#detailCourseHistory article').nth(1).textContent();
 assert.ok(historyText.includes('历史已核准测量（非当前证据、非预测）'));assert.ok(historyText.includes('6.85'));assert.ok(!historyText.includes('已核验测量（非预测）'));
 const historyDownload=page.waitForEvent('download');await page.locator('#exportButton').click();const savedHistory=await historyDownload;
 const historyStream=await savedHistory.createReadStream(),historyChunks=[];for await(const chunk of historyStream)historyChunks.push(chunk);
 const historyJSON=JSON.parse(Buffer.concat(historyChunks).toString('utf8')).course_history[1];
 assert.equal(historyJSON.status,'historical_reviewed');assert.equal(historyJSON.live_evidence_available,false);
 assert.equal(historyJSON.measurements[0].provenance.source_status,'historical_reviewed');assert.equal(historyJSON.measurements[0].provenance.live_evidence_available,false);
 assert.equal(historyJSON.measurements[0].measurement.assessment.overall_score,6.85);
 await page.goto('http://summary.test/demo2/student-summary?student_id=s1');
 await page.waitForFunction(()=>document.getElementById('courseHistoryList').textContent.includes('历史已核准 · 原视频已按期清理，无法回看原始证据'));
 assert.ok((await page.locator('#courseHistoryList article').nth(1).textContent()).includes('历史已核准测量（非当前证据、非预测）'));
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
}finally{await browser.close();}
"""
    result = subprocess.run([node, "-e", "(async()=>{" + script + "})().catch(e=>{console.error(e);process.exit(1)});"],
                            input=json.dumps(data), encoding="utf-8", capture_output=True, timeout=80)
    assert result.returncode == 0, result.stdout + result.stderr
