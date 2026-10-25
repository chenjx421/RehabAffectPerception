"""Generated admin JavaScript, fake network only; no live server or database."""
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_portal import render_demo2_admin_html
from test_demo2_portal_html import _run_page_js


SETUP = r"""
let clockNow=1800000000000;
Date.now=()=>clockNow;
Object.defineProperty(document,'visibilityState',{get:()=>document.hidden?'hidden':'visible'});
const summary=(page=1,total=43)=>({
  upload_accounts:[{username:'synthetic-school'}],channels:[{channel_name:'Original channel'}],
  task_status:{total,by_upload_status:{completed:total},by_analysis_status:{evidence_ready:total}},
  storage:{video:{byte_size:1024}},
  recent_uploads:[{task_id:'task-'+page,original_filename:'page-'+page+'.mp4',course_name:'Synthetic course',
    upload_status:'completed',analysis_status:'evidence_ready',created_at:'2026-10-16T12:00:00+08:00'}],
  upload_pagination:{page,page_size:20,total,total_pages:Math.ceil(total/20)}
});
const fullReplies=(page=1,total=43)=>replies.push({account:{role:'company_admin'}},{summary:summary(page,total)},
  {summary:{members:[],orders:[]}},{reports:[],pagination:{page:1,page_size:20,total:0,total_pages:1}});
const tick=async()=>{
  const timer=timers.get(adminPollTimer);assert.ok(timer,'Expected a scheduled poll');
  clockNow+=timer.delay;await timer.fn();await flush();
};
const assertPoll=delay=>{assert.equal(timers.size,1);assert.equal(timers.get(adminPollTimer).delay,delay);};
"""


def check(assertions, setup="fullReplies();"):
    _run_page_js(render_demo2_admin_html({"role": "company_admin"}), SETUP + setup, assertions)


def test_generated_admin_script_syntax_and_controls():
    html = render_demo2_admin_html()
    for name in ("previousUploads", "nextUploads", "uploadPageStatus", "adminRefreshStatus"):
        assert f'id="{name}"' in html
    assert 'aria-label="近期上传分页"' in html
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for generated JavaScript validation")
    script = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    result = subprocess.run([node, "--check"], input=script, text=True, encoding="utf-8",
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_timer_updates_only_activity_and_keeps_drafts_focus_and_messages():
    check(r"""
    assertPoll(30000);
    const untouched=['accountList','channelList','registrationRequests','schoolContexts','courseUsage',
      'recentSecurityAcceptances','membershipSummary','membershipAccounts','membershipOrdersSummary'];
    untouched.forEach(id=>byId(id).innerHTML='unsaved-'+id);
    byId('channelName').value='Unsaved channel name';byId('channelName').focus();
    byId('pageMessage').textContent='Keep existing form feedback';
    const before=requests.length;
    const updated=summary(1,44);updated.recent_uploads[0].original_filename='<img src=x>';
    replies.push({summary:updated});await tick();
    assert.equal(requests.length,before+1);
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/summary?upload_page=1');
    assert.equal(requests.at(-1).options.method,undefined);
    assert.equal(requests.at(-1).options.cache,'no-store');
    assert.equal(byId('taskCount').textContent,'44');
    assert.match(byId('recentUploads').innerHTML,/&lt;img src=x&gt;/);
    assert.match(byId('recentUploads').innerHTML,/\/demo2\/video\?id=task-1/);
    assert.match(byId('adminRefreshStatus').textContent,/最近更新/);
    untouched.forEach(id=>assert.equal(byId(id).innerHTML,'unsaved-'+id));
    assert.equal(byId('channelName').value,'Unsaved channel name');
    assert.equal(document.activeElement,byId('channelName'));
    assert.equal(byId('pageMessage').textContent,'Keep existing form feedback');
    assertPoll(30000);
    """)


def test_pagination_timer_manual_refresh_and_backend_clamp():
    check(r"""
    assert.equal(byId('previousUploads').disabled,true);assert.equal(byId('nextUploads').disabled,false);
    assert.match(byId('uploadPageStatus').textContent,/43.*1 \/ 3/);
    byId('channelList').innerHTML='Keep edited channel panel';
    replies.push({summary:summary(2)});await byId('nextUploads').fire('click');
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/summary?upload_page=2');
    assert.equal(adminUploadPage,2);assert.equal(byId('previousUploads').disabled,false);
    assert.equal(byId('channelList').innerHTML,'Keep edited channel panel');
    replies.push({summary:summary(2)});await tick();
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/summary?upload_page=2');
    const before=requests.length;fullReplies(2);await byId('refreshButton').fire('click');
    assert.equal(requests.length,before+4);assert.equal(adminUploadPage,2);
    assert.ok(requests.slice(-4).some(item=>item.url==='/api/v1/demo2/admin/summary?upload_page=2'));
    replies.push({summary:summary(3)});await byId('nextUploads').fire('click');
    assert.equal(byId('nextUploads').disabled,true);
    replies.push({summary:summary(2)});await byId('previousUploads').fire('click');
    assert.equal(adminUploadPage,2);
    replies.push({summary:summary(1,8)});await tick();
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/summary?upload_page=2');
    assert.equal(adminUploadPage,1);assert.match(byId('uploadPageStatus').textContent,/8.*1 \/ 1/);
    assert.equal(byId('nextUploads').disabled,true);assert.equal(byId('previousUploads').disabled,true);
    """)


def test_failed_page_navigation_keeps_current_page_rows_and_timestamp():
    check(r"""
    const rows=byId('recentUploads').innerHTML,last=adminLastUpdated;
    replies.push(new TypeError('offline'));await byId('nextUploads').fire('click');
    assert.equal(adminUploadPage,1);assert.equal(byId('recentUploads').innerHTML,rows);
    assert.equal(adminLastUpdated,last);assert.match(byId('adminRefreshStatus').textContent,/暂时无法更新/);
    assertPoll(60000);
    replies.push({summary:summary(1)});await tick();
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/summary?upload_page=1');
    """)


def test_request_guard_covers_timer_page_navigation_and_manual_refresh():
    check(r"""
    let finish;
    replies.push(()=>new Promise(resolve=>finish=()=>resolve({status:200,ok:true,json:async()=>({summary:summary(1,45)})})));
    const pending=timers.get(adminPollTimer).fn();await flush();
    const before=requests.length;
    assert.equal(adminRefreshing,true);assert.equal(byId('refreshButton').disabled,true);
    await refresh();await refresh({partial:true,automatic:true});await byId('nextUploads').fire('click');
    listeners.get('visibilitychange')();
    assert.equal(requests.length,before);
    finish();await pending;assert.equal(adminRefreshing,false);assertPoll(30000);
    fullReplies();await byId('refreshButton').fire('click');assert.equal(requests.length,before+4);
    """)


def test_backoff_capped_and_success_resets_without_erasing_stale_data():
    check(r"""
    const rows=byId('recentUploads').innerHTML,last=adminLastUpdated;
    for(const delay of [60000,120000,240000,300000,300000]){
      replies.push({status:503,body:{error:{message:'Unavailable'}}});await tick();assertPoll(delay);
      assert.equal(byId('recentUploads').innerHTML,rows);assert.equal(adminLastUpdated,last);
    }
    replies.push({summary:summary(1)});await tick();assertPoll(30000);assert.equal(adminPollFailures,0);
    assert.ok(!byId('adminRefreshStatus').textContent.includes('暂时无法更新'));
    """)


def test_hidden_tabs_pause_and_resume_without_bypassing_backoff():
    check(r"""
    replies.push(new Error('offline'));await tick();assertPoll(60000);
    document.hidden=true;listeners.get('visibilitychange')();assert.equal(timers.size,0);
    const before=requests.length;await refresh({partial:true,automatic:true});assert.equal(requests.length,before);
    clockNow+=10000;document.hidden=false;listeners.get('visibilitychange')();assertPoll(50000);
    listeners.get('pagehide')();assert.equal(timers.size,0);assert.equal(adminPollStopped,true);
    listeners.get('pageshow')({persisted:true});assert.equal(adminPollStopped,false);assertPoll(50000);
    """)


def test_initially_hidden_page_waits_until_visible():
    check(r"""
    assert.equal(requests.length,0);assert.equal(timers.size,0);
    fullReplies();document.hidden=false;listeners.get('visibilitychange')();await flush();
    assert.equal(requests.length,4);assertPoll(30000);
    """, "document.hidden=true;")


def test_inflight_poll_hidden_completion_does_not_render_or_reschedule():
    check(r"""
    const rows=byId('recentUploads').innerHTML;
    let finish;replies.push(()=>new Promise(resolve=>finish=()=>resolve({status:200,ok:true,json:async()=>({summary:summary(1,99)})})));
    const pending=timers.get(adminPollTimer).fn();await flush();
    document.hidden=true;listeners.get('visibilitychange')();finish();await pending;
    assert.equal(byId('recentUploads').innerHTML,rows);assert.equal(byId('taskCount').textContent,'43');
    assert.equal(timers.size,0);document.hidden=false;listeners.get('visibilitychange')();assertPoll(30000);
    """)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_stops_polling(status):
    check(f"""
    replies.push({{status:{status},body:{{error:{{}}}}}});await tick();
    assert.equal(adminPollStopped,true);assert.equal(timers.size,0);
    const before=requests.length;listeners.get('visibilitychange')();
    await refresh({{partial:true,automatic:true}});assert.equal(requests.length,before);
    """ + ("assert.equal(location.assigned,'/demo2/login');" if status == 401 else ""))


def test_timeout_and_malformed_summary_keep_existing_data():
    check(r"""
    const rows=byId('recentUploads').innerHTML;
    replies.push((_url,options)=>new Promise((resolve,reject)=>{
      options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true});
    }));
    const pending=timers.get(adminPollTimer).fn();await flush();
    assert.equal(timers.size,1);[...timers.values()][0].fn();await pending;
    assert.equal(byId('recentUploads').innerHTML,rows);assertPoll(60000);
    replies.push({summary:null});await tick();assert.equal(byId('recentUploads').innerHTML,rows);assertPoll(120000);
    """)


def test_empty_and_legacy_pagination_are_not_fabricated():
    check(r"""
    const empty=summary(1,0);empty.recent_uploads=[];
    replies.push({summary:empty});await tick();
    assert.match(byId('uploadPageStatus').textContent,/共 0 条/);
    assert.equal(byId('previousUploads').disabled,true);assert.equal(byId('nextUploads').disabled,true);
    const legacy=summary();delete legacy.upload_pagination;replies.push({summary:legacy});await tick();
    assert.equal(byId('uploadPageStatus').textContent,'分页信息暂不可用');
    assert.equal(byId('nextUploads').disabled,true);
    """)


def test_report_failure_is_partial_failure_and_manual_refresh_recovers():
    check(r"""
    assert.ok(byId('pageMessage').textContent.includes('部分后台数据未能刷新'));
    assert.match(byId('recentReports').innerHTML,/Reports offline/);
    assert.ok(byId('accountList').innerHTML.includes('synthetic-school'));
    fullReplies();await byId('refreshButton').fire('click');
    assert.equal(byId('pageMessage').textContent,'后台数据已刷新。');
    """, "replies.push({account:{role:'company_admin'}},{summary:summary()},{summary:{members:[],orders:[]}},{status:503,body:{error:{message:'Reports offline'}}});")


def test_report_pagination_failure_and_retry_use_shared_request_guard():
    check(r"""
    adminReportPages=3;updateAdminControls();
    replies.push(new TypeError('offline'));await byId('nextReports').fire('click');
    assert.equal(adminReportPage,1);assert.equal(adminRefreshing,false);
    replies.push({reports:[],pagination:{page:2,total_pages:3,total:41}});
    await byId('nextReports').fire('click');assert.equal(adminReportPage,2);
    assert.equal(requests.at(-1).url,'/api/v1/demo2/admin/reports?page=2');
    let finish;replies.push(()=>new Promise(resolve=>finish=()=>resolve({status:200,ok:true,json:async()=>({reports:[],pagination:{page:3,total_pages:3,total:41}})})));
    const pending=byId('nextReports').fire('click');await flush();const before=requests.length;
    await refresh();await reportPage(-1);assert.equal(requests.length,before);
    finish();await pending;assert.equal(adminReportPage,3);assertPoll(30000);
    """)
