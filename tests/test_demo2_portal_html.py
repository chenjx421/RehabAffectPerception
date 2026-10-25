from __future__ import annotations

import re
import json
import shutil
import subprocess

import pytest

from rehab_affect.demo2_portal import (
    render_demo2_admin_html,
    render_demo2_login_html,
    render_demo2_register_html,
    render_demo2_school_html,
    render_demo2_privacy_html,
    render_demo2_membership_html,
    render_demo2_upload_html,
)
from rehab_affect.demo2_video_review import render_video_review


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {
        "login": render_demo2_login_html(),
        "upload": render_demo2_upload_html(
            {
                "account_id": "school-account-1",
                "username": "school-uploader-1",
                "role": "school_uploader",
                "bound_channel_id": "channel-01",
                "course_upload_limit": 5,
            }
        ),
        "admin": render_demo2_admin_html(
            {
                "account_id": "company-admin",
                "username": "company-admin",
                "role": "company_admin",
            }
        ),
    }


def test_portal_exports_three_real_pages(pages: dict[str, str]) -> None:
    assert "登录课堂工作台" in pages["login"]
    assert "上传课堂视频" in pages["upload"]
    assert "学校内测运行状态" in pages["admin"]
    assert len(set(pages.values())) == 3
    for html in pages.values():
        assert html.startswith("<!doctype html>")
        assert '<html lang="zh-CN">' in html
        assert 'name="viewport"' in html
        assert 'href="#mainContent"' in html
        assert "seewo_student_demo2" not in html
        assert 'data-tab="' not in html


def test_login_has_role_selection_and_registration_flow(pages: dict[str, str]) -> None:
    html = pages["login"]
    for text in (
        "学校内测",
        "账号",
        "密码",
        "用户登录",
        "管理员登录",
        "会员注册",
        "数据安全与隐私说明",
    ):
        assert text in html
    assert 'type="password"' in html
    assert 'value=' not in re.search(r'<input id="password"[^>]*>', html).group(0)
    assert "/api/v1/demo2/auth/login" in html
    assert "credentials:'same-origin'" in html
    assert "company_admin" in html
    assert "role:selectedRole" in html
    assert "/demo2/school" in html
    assert 'aria-checked="true"' in html


def test_upload_page_has_quota_chunk_and_task_contract(pages: dict[str, str]) -> None:
    html = pages["upload"]
    for text in (
        "学校视频上传工作台",
        "登录账号",
        "当前通道",
        "上传通道",
        "课程批次号",
        "课程名称",
        "五个视频名额",
        "已用",
        "剩余",
        "数据使用与保存设置",
        "开始上传并分析",
        "允许脱敏结构化结果长期归档（不含原视频）",
        "最近授权确认",
        "本课程尚未留存确认",
        "文件名、上传进度、处理状态和结果下载",
        "课堂复核与报告",
    ):
        assert text in html
    assert "4 * 1024 * 1024" in html
    assert "/api/v1/demo2/upload/tasks" in html
    assert "/api/v1/demo2/upload/chunks" in html
    assert "/api/v1/demo2/upload/tasks/cancel" in html
    assert "/api/v1/demo2/upload/workspace" in html
    assert "credentials:'same-origin'" in html
    assert "window.location.assign('/demo2/login')" in html
    assert "当前账号无权访问该通道或任务" in html
    assert "workspace?.tasks" in html
    assert "security_confirmed:true" in html
    assert "allow_company_archive:byId('allowCompanyArchive').value==='yes'" in html
    assert "workspace?.latest_security_acceptance" in html
    assert "workspace?.security_acceptance" in html
    assert "task.secure_result_download_url||task.result_download_url" in html
    assert "取消并释放名额" in html
    assert "课程批次号已修改，请重新读取课程工作区" in html
    assert "byId('allowCompanyArchive').value='no'" in html
    assert 'id="securityConfirmed"' not in html
    assert 'value="no">不允许' in html
    assert "byId('uploadProgress').classList.remove('visible')" in html
    assert "beforeunload" in html
    assert "如需继续上传，请重新选择视频并确认授权" in html
    assert "channelLabel" in html
    assert 'id="channelSelect"' in html
    assert "workspace?.channels" in html
    assert "channel_id:channelId" in html
    assert "demo2-${new Date().toISOString().slice(0,10)}" in html
    assert 'class="file-input-accessible"' in html
    assert 'class="file-picker"' in html
    assert "选择课堂视频" in html
    assert 'id="selectedFileName"' in html
    assert ".file-input-accessible:focus-visible + .file-picker" in html
    assert "display:none" not in re.search(
        r"\.file-input-accessible\s*\{([^}]*)\}", html
    ).group(1)


def test_admin_page_is_interface_driven(pages: dict[str, str]) -> None:
    html = pages["admin"]
    for text in (
        "4 账号 / 4 通道状态",
        "每课程名额使用",
        "任务状态",
        "总存储",
        "保存周期",
        "提前提醒",
        "到期处理",
        "自动清理",
        "近期上传",
        "近期安全授权确认",
        "刷新数据",
        "测量记录汇总",
        "退出",
        "不补造统计",
    ):
        assert text in html
    assert "/api/v1/demo2/admin/summary" in html
    assert "/api/v1/demo2/auth/logout" in html
    assert "summary.upload_accounts" in html
    assert "summary.channels" in html
    assert "summary.course_usage" in html
    assert "summary.task_status" in html
    assert "summary.storage" in html
    assert "summary.retention" in html
    assert "summary.recent_security_acceptances" in html
    assert "Array.isArray(summary.recent_uploads)" in html
    assert "summary.recent_tasks" not in html
    assert "汇总接口暂未返回近期上传明细" in html
    for raw, translated in (
        ("active", "启用"),
        ("completed", "已完成"),
        ("uploaded_pending_worker", "历史预检"),
        ("uploading", "上传中"),
        ("failed", "处理失败"),
    ):
        assert f"{raw}:'{translated}'" in html
    assert "statusLabel(task.upload_status)" in html
    assert "statusLabel(task.analysis_status)" in html


def test_shared_visual_accessibility_and_responsive_contract(pages: dict[str, str]) -> None:
    forbidden_emoji = ("✅", "⚠", "📄", "📊", "👤", "🤖", "🔒", "🚀")
    for html in pages.values():
        assert "--blue:#1f63c6" in html
        assert "overflow-x:hidden" in html
        assert "@media (max-width:780px)" in html
        assert "@media (max-width:720px)" in html
        assert "@media (prefers-reduced-motion:reduce)" in html
        assert ":focus-visible" in html
        assert "min-height:44px" in html
        assert "<svg" in html
        assert "https://" not in html and "http://" not in html
        assert all(emoji not in html for emoji in forbidden_emoji)
        radii = [int(value) for value in re.findall(r"border-radius:(\d+)px", html)]
        assert radii and max(radii) <= 8


def test_mobile_header_keeps_brand_and_account_details_readable(
    pages: dict[str, str],
) -> None:
    for page_name in ("upload", "admin"):
        html = pages[page_name]
        mobile_header = re.search(
            r"@media \(max-width:720px\)\s*\{(.*?)\n\}", html, re.DOTALL
        ).group(1)
        assert ".header-inner { display:grid" in mobile_header
        assert "grid-template-columns:minmax(0,1fr)" in mobile_header
        assert ".brand-copy span { display:block; }" in mobile_header
        assert ".header-actions" in mobile_header
        assert "flex-wrap:wrap" in mobile_header
        assert ".account-chip strong" in mobile_header
        assert "text-overflow:clip" in mobile_header
        assert "white-space:normal" in mobile_header
        assert "overflow-wrap:anywhere" in mobile_header
        assert ".header-actions .button { flex:0 0 44px" in mobile_header
    assert ".account-chip { max-width:112px" not in pages["upload"]


def test_account_json_cannot_break_the_inline_script() -> None:
    html = render_demo2_upload_html(
        {
            "username": "</script><script>alert(1)</script>",
            "role": "school_uploader",
            "bound_channel_id": "channel-01",
        }
    )
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html


def test_onboarding_pages_have_persistent_endpoints_and_explicit_consent() -> None:
    school = render_demo2_school_html({"username": "t1"})
    register = render_demo2_register_html()
    privacy = render_demo2_privacy_html()
    assert "/api/v1/demo2/school/context" in school
    assert all(f'id="{field}"' in school for field in ("city", "district", "schoolName"))
    # School selection now reads the authenticated server context, not a JS account constant.
    assert "credentials:'same-origin'" in school
    assert "ready=data.selection_enabled===true" in school
    assert "expected_context:currentContext" in school
    assert "/api/v1/demo2/auth/register" in register
    assert "accepted:true" in register
    assert "注册并前往会员开通" in register
    assert "/api/v1/demo2/auth/sms-code" in register
    assert "agreement_version:AGREEMENT_VERSION" in register
    assert "const AGREEMENT_VERSION='2026-09-09'" in register
    assert "/^[A-Za-z0-9]{8,72}$/" in register
    assert "response.result||response" in register
    assert all(f'id="{field}"' in register for field in ("phone", "code", "password", "confirmPassword"))
    assert 'id="schoolName"' not in register
    assert "同意并提交申请" not in register
    assert "不会因填写学校或创建账号自动上传云端" in privacy
    assert "登录本身不代表同意上传学生资料" in privacy


def test_video_review_has_accessible_controls_and_honest_evidence_scope() -> None:
    html = render_video_review({"role": "school_uploader"})
    for text in (
        'id="classVideo"', 'id="audioPlayer"', 'id="seekSlider"',
        'id="refreshButton"', 'id="retryButton"', 'id="segments"',
        'id="pollStatus" role="status"', 'tabindex="-1"',
        'aria-label="本任务课堂录像"', 'aria-label="本任务同期音轨"',
        "学生状态已生成", "学生课堂状态", "simple_student_analysis", "画面变化幅度",
        "width:44px; height:44px", "min-width:0; max-width:100%",
        "grid-template-columns:minmax(0,1fr) auto",
        "@media(max-width:720px)", "flex:0 1 auto",
    ):
        assert text in html
    assert "/upload/tasks/enqueue" in html
    assert "/upload/tasks/retry" in html
    assert "asset=audio" in html
    assert 'href="/demo2/analysis' not in html
    assert "注意力评分" not in html and "学习成绩" not in html


def test_upload_links_to_task_scoped_analysis_and_specific_evidence(pages):
    html = pages["upload"]
    assert "课堂复核与图文报告" in html
    assert "/demo2/analysis?task_id=" in html
    assert "'/demo2/video?id='+encodeURIComponent(task.task_id" in html
    assert "/demo2/analysis?course_id=" not in html
    assert 'id="refreshTasksButton"' in html
    assert "task.processing_error" in html
    assert "原片与派生音轨不可用" in html
    assert "visibilitychange" in html and "pagehide" in html and "pageshow" in html
    assert "setUploadBusy(true)" in html and "setUploadBusy(false)" in html


# Exercise the emitted JS without a browser or the E2E team's QA session.
# The small DOM double covers event/state behavior, not visual layout.
_JS_ENV = r"""
const assert=require('node:assert/strict');
const listeners=new Map(),nodes=new Map(),timers=new Map(),requests=[];
let nextTimer=0;
const setTimeout=(fn,delay)=>{timers.set(++nextTimer,{fn,delay});return nextTimer;};
const clearTimeout=id=>timers.delete(id);
class Element {
  constructor(id){this.id=id;this.hidden=true;this.disabled=false;this.attrs={};this.events={};this.textContent='';this.innerHTML='';this.currentTime=0;this.readyState=0;this.duration=NaN;this.value='';this.style={};this.dataset={};this.paused=true;this.files=[];this.options=[];this.classList={add(){},remove(){}};}
  set src(value){this.attrs.src=value;} get src(){return this.attrs.src||'';}
  set value(value){this._value=value;if(this.id==='videoFile'&&value==='')this.files=[];} get value(){return this._value;}
  set href(value){this.attrs.href=value;} get href(){return this.attrs.href||'';}
  setAttribute(key,value){this.attrs[key]=String(value);}
  getAttribute(key){return this.attrs[key]??null;}
  removeAttribute(key){delete this.attrs[key];}
  addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
  async fire(name,event={}){for(const fn of this.events[name]||[])await fn(event);}
  pause(){this.paused=true;} load(){this.readyState=0;this.currentTime=0;}
  focus(){document.activeElement=this;}
  querySelector(){return new Element('progress');}
  querySelectorAll(selector){if(selector!=='[data-index]')return [];return [...this.innerHTML.matchAll(/data-index="(\d+)"/g)].map(m=>{const e=new Element('segment'+m[1]);e.dataset.index=m[1];return e;});}
}
const document={hidden:false,activeElement:null,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},addEventListener(name,fn){listeners.set(name,fn);}};
const location={origin:'http://local.test',search:'?id=video-1',assign(value){this.assigned=value;}};
const sessionStorage={setItem(){}};
const history={replaceState(){}};
const window={location,confirm(){return true;},addEventListener(name,fn){listeners.set(name,fn);}};
const replies=[];
const fetch=async(url,options)=>{requests.push({url,options});assert.equal(options.credentials,'same-origin');const next=replies.shift();if(next instanceof Error)throw next;assert.ok(next,'Unexpected request: '+url);if(typeof next==='function')return next(url,options);return {status:next.status??200,ok:(next.status??200)<400,headers:{get:name=>next.headers?.[name]??null},json:async()=>next.body??next};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const baseTask={task_id:'video-1',course_id:'course-1',course_name:'数学',upload_status:'completed',analysis_status:'queued',processing_progress:0,media_url:'/api/v1/demo2/upload/media?id=video-1'};
const evidence={media:{duration_sec:1000,width:640,height:360,has_audio:true},segments:Array.from({length:25},(_,i)=>({start_sec:i*30,end_sec:(i+1)*30,visual:{sampled_frames:30,mean_motion:0.0123},audio:{available:true,rms:0.2}}))};
"""


def _run_page_js(html: str, setup: str, assertions: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for browserless page interaction checks")
    script = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    source = (
        "(async()=>{\n" + _JS_ENV + "\n" + setup + "\n" + script
        + "\nawait flush();\n" + assertions
        + "\n})().catch(error=>{console.error(error);process.exit(1);});"
    )
    completed = subprocess.run(
        [node, "-"], input=source, text=True, encoding="utf-8",
        capture_output=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_all_portal_inline_scripts_parse_without_browser(pages):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for JS syntax checks")
    pages_to_check = [*pages.values(), render_video_review(),
                      render_demo2_register_html(), render_demo2_school_html(),
                      render_demo2_privacy_html(), render_demo2_membership_html()]
    scripts = [script for html in pages_to_check
               for script in re.findall(r"<script>(.*?)</script>", html, re.S)]
    completed = subprocess.run(
        [node, "-e", "for(const s of JSON.parse(require('fs').readFileSync(0,'utf8')))new Function(s)"],
        input=json.dumps(scripts), text=True, capture_output=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("role,show_link,path,label", [
    ("company_admin", True, "/demo2/admin", "返回公司后台"),
    ("school_uploader", True, "/demo2/school", "进入学校工作台"),
    ("registered_member", False, "/demo2/school", "进入学校工作台"),
])
def test_membership_keeps_role_specific_access_and_never_orders_by_default(role, show_link, path, label):
    # Deliberately return school_access for the new member: the role gate still hides it.
    setup = "replies.push({membership:{status:'internal_trial',school_access:true,payment_available:false,plans:[],orders:[]}});"
    assertions = f"""
        assert.equal(byId('schoolWorkspaceLink').hidden,{json.dumps(not show_link)});
        assert.equal(byId('schoolWorkspaceLink').href,{json.dumps(path)});
        assert.equal(byId('schoolWorkspaceLink').textContent,{json.dumps(label)});
        assert.equal(byId('membershipStatus').textContent,'内测账号');
        assert.equal(byId('orderButton').disabled,true);
        assert.ok(byId('membershipOrders').innerHTML.includes('暂无订单'));
        assert.equal(requests.length,1);
        assert.equal(requests[0].url,'/api/v1/demo2/membership');
    """
    if role == "company_admin":
        assertions += "assert.ok(byId('schoolAccessStatus').textContent.includes('原有管理权限保留'));"
    _run_page_js(render_demo2_membership_html({"role": role}), setup, assertions)


def test_membership_unavailable_plan_and_legacy_amount_field():
    _run_page_js(render_demo2_membership_html({"role": "registered_member"}),
        "replies.push({membership:{status:'inactive',school_access:false,payment_available:true,plans:[{plan_id:'month',price_cents:1200,available:false}],orders:[{order_id:'order-1',price_cents:1200,status:'pending'}]}});",
        """
        selectedPlan='month';updateOrderButton();
        assert.equal(byId('orderButton').disabled,true);
        assert.ok(byId('membershipPlans').innerHTML.includes('暂未开放购买'));
        assert.ok(byId('membershipOrders').innerHTML.includes('¥12.00'));
        assert.ok(byId('membershipOrders').innerHTML.includes('待支付'));
        await byId('orderButton').fire('click');assert.equal(requests.length,1);
        """)


@pytest.mark.parametrize("role", ["school_uploader", "company_admin"])
def test_trial_roles_cannot_order_even_if_payment_is_configured(role):
    _run_page_js(render_demo2_membership_html({"role": role}),
        "replies.push({membership:{status:'internal_trial',payment_available:true,plans:[{plan_id:'month',price_cents:1200,available:true}],orders:[]}});",
        """
        selectedPlan='month';updateOrderButton();
        assert.equal(byId('orderButton').disabled,true);
        await byId('orderButton').fire('click');assert.equal(requests.length,1);
        """)


def test_admin_memberships_preserve_legacy_sections_and_empty_records():
    html = render_demo2_admin_html({"role": "company_admin"})
    for element in ("membershipSummary", "membershipAccounts", "membershipOrdersSummary",
                    "registrationRequests", "schoolContexts", "recentUploads"):
        assert f'id="{element}"' in html
    assert "历史学校开通申请" in html
    assert "/api/v1/demo2/admin/memberships" in html
    _run_page_js(html,
        "replies.push({account:{role:'company_admin'}},{summary:{}},{summary:{members:[],orders:[],sms_available:false,payment_available:false}},{reports:[]});",
        """
        assert.ok(byId('membershipSummary').innerHTML.includes('暂未配置，不可付款'));
        assert.ok(byId('membershipAccounts').innerHTML.includes('暂无注册会员'));
        assert.ok(byId('membershipOrdersSummary').innerHTML.includes('暂无会员订单'));
        assert.ok(byId('registrationRequests').innerHTML.includes('暂无历史学校开通申请'));
        assert.ok(requests.some(item=>item.url==='/api/v1/demo2/admin/memberships'));
        assert.ok(requests.every(item=>!item.options.method||item.options.method==='GET'));
        """)


def test_admin_membership_failure_does_not_hide_legacy_summary_or_fake_zero():
    _run_page_js(render_demo2_admin_html({"role": "company_admin"}),
        "replies.push({account:{role:'company_admin'}},{summary:{upload_accounts:[{username:'t1'}]}},{status:503,body:{error:{message:'会员服务暂不可用'}}},{reports:[]});",
        """
        assert.ok(byId('accountList').innerHTML.includes('t1'));
        assert.ok(byId('membershipSummary').textContent.includes('会员服务暂不可用'));
        assert.ok(byId('membershipOrdersSummary').innerHTML.includes('不能据此判断没有订单'));
        assert.ok(!byId('membershipAccounts').innerHTML.includes('暂无注册会员'));
        assert.ok(byId('pageMessage').textContent.includes('部分后台数据未能刷新'));
        """)


def test_admin_memberships_render_only_returned_escaped_records_and_prices():
    _run_page_js(render_demo2_admin_html({"role": "company_admin"}),
        "replies.push({account:{role:'company_admin'}},{summary:{}},{summary:{members:[{account_id:'member-1',phone_masked:'138****0000',status:'inactive'}],orders:[{order_id:'order-1',account_id:'member-1',plan_name:'<img src=x>',price_cents:1500,status:'pending'}],sms_available:true,payment_available:false}},{reports:[]});",
        """
        assert.ok(byId('membershipAccounts').innerHTML.includes('138****0000'));
        assert.ok(byId('membershipAccounts').innerHTML.includes('未开通'));
        assert.ok(byId('membershipOrdersSummary').innerHTML.includes('¥15.00'));
        assert.ok(byId('membershipOrdersSummary').innerHTML.includes('&lt;img src=x&gt;'));
        assert.ok(byId('membershipOrdersSummary').innerHTML.includes('待支付'));
        assert.equal(membershipMoney(null),'待公布');
        renderMembershipSummary({});
        assert.ok(byId('membershipSummary').innerHTML.includes('未返回'));
        assert.ok(!byId('membershipAccounts').innerHTML.includes('暂无注册会员'));
        """)


@pytest.mark.parametrize("slow_panel", ["school", "membership"])
def test_admin_summaries_render_independently_and_recover_after_timeout(slow_panel):
    school = "{summary:{upload_accounts:[{username:'t1'}]}}"
    member = "{summary:{members:[],orders:[],sms_available:false,payment_available:false}}"
    replies = f"slow,{member}" if slow_panel == "school" else f"{school},slow"
    early_assertion = (
        "assert.ok(byId('membershipAccounts').innerHTML.includes('暂无注册会员'));"
        if slow_panel == "school" else
        "assert.ok(byId('accountList').innerHTML.includes('t1'));"
    )
    _run_page_js(render_demo2_admin_html({"role": "company_admin"}),
        """
        const slow=(_url,options)=>new Promise((resolve,reject)=>{
            options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true});
        });
        """ + f"replies.push({{account:{{role:'company_admin'}}}},{replies},{{reports:[]}});",
        early_assertion + """
        assert.equal(byId('refreshButton').disabled,true);
        const pending=[...timers.values()];assert.equal(pending.length,1);
        assert.equal(pending[0].delay,10000);pending[0].fn();await flush();
        assert.equal(byId('refreshButton').disabled,false);
        assert.ok(byId('pageMessage').textContent.includes('请求超时'));
        assert.ok(byId('pageMessage').textContent.includes('重试'));
        assert.equal(timers.size,0);
        replies.push({account:{role:'company_admin'}},{summary:{}},{summary:{members:[],orders:[]}},{reports:[]});
        await byId('refreshButton').fire('click');
        assert.equal(byId('refreshButton').disabled,false);
        assert.equal(byId('pageMessage').textContent,'后台数据已刷新。');
        assert.equal(timers.size,0);
        """)


def test_admin_timeout_while_reading_body_is_not_swallowed():
    _run_page_js(render_demo2_admin_html({"role": "company_admin"}),
        """
        const slowBody=(_url,options)=>({status:200,ok:true,json:()=>new Promise((resolve,reject)=>{
            options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true});
        })});
        replies.push({account:{role:'company_admin'}},{summary:{upload_accounts:[{username:'t1'}]}},slowBody,{reports:[]});
        """,
        """
        assert.ok(byId('accountList').innerHTML.includes('t1'));
        [...timers.values()][0].fn();await flush();
        assert.ok(byId('membershipSummary').textContent.includes('请求超时'));
        assert.ok(!byId('membershipAccounts').innerHTML.includes('暂无注册会员'));
        assert.equal(byId('refreshButton').disabled,false);
        """)


@pytest.mark.parametrize("render,error_id", [
    (render_demo2_membership_html, "formError"),
    (render_demo2_upload_html, "pageMessage"),
    (render_demo2_admin_html, "pageMessage"),
])
@pytest.mark.parametrize("network_error", [True, False])
def test_request_errors_translate_network_failure_without_replacing_business_message(render, error_id, network_error):
    setup = (
        "replies.push(new TypeError('Failed to fetch'));" if network_error else
        "replies.push({status:503,body:{error:{message:'业务接口返回的具体原因'}}});"
    )
    if render == render_demo2_upload_html:
        setup = "replies.push({context:{}});" + setup
    expected = "网络连接失败，请检查网络后重试。" if network_error else "业务接口返回的具体原因"
    _run_page_js(render(), setup,
        f"assert.ok(byId({json.dumps(error_id)}).textContent.includes({json.dumps(expected)}));"
        + f"assert.ok(!byId({json.dumps(error_id)}).textContent.includes('Failed to fetch'));"
        + ("assert.equal(byId('refreshButton').disabled,false);" if render == render_demo2_admin_html else ""))


def test_admin_empty_membership_tables_wrap_without_affecting_real_data_tables():
    html = render_demo2_admin_html()
    assert ".membership-admin-section table:has(tbody > tr:only-child > td[colspan]) { min-width:0; table-layout:fixed; }" in html
    assert ".membership-admin-section table:has(tbody > tr:only-child > td[colspan]) thead { display:none; }" in html
    assert ".membership-admin-section td[colspan] { white-space:normal; overflow-wrap:anywhere; }" in html
    assert "table { width:100%; min-width:680px" in html
    assert 'id="membershipOrdersSummary"><tr><td colspan="6">' in html


def test_video_review_polls_recovers_and_stops_when_ready():
    _run_page_js(render_video_review(),
        "replies.push({task:baseTask,result:null});",
        r"""
        assert.equal($('stageLabel').textContent,'等待处理');
        assert.ok([...timers.values()].some(t=>t.delay===2000));
        replies.push(new Error('network offline'));await refresh();
        assert.ok([...timers.values()].some(t=>t.delay===5000));
        assert.match($('pollStatus').textContent,/自动重连/);
        replies.push({task:{...baseTask,analysis_status:'processing',processing_stage:'sampling_video',processing_progress:32},result:null});await refresh();
        assert.equal($('stageDetail').textContent,'读取画面');
        assert.equal($('stagePercent').textContent,'32%');
        assert.equal($('pageMessage').className,'page-message');
        replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:evidence});await refresh();
        assert.equal($('stagePercent').textContent,'100%');
        assert.equal($('downloadResult').hidden,false);assert.equal(segments.length,25);
        assert.equal(audio.hidden,false);assert.match(audio.src,/asset=audio/);
        assert.equal(timers.size,0);
        """)


@pytest.mark.parametrize(("status", "endpoint", "label"), [
    ("precheck_complete", "enqueue", "开始处理"),
    ("uploaded_pending_worker", "enqueue", "开始处理"),
    ("failed", "retry", "重新处理"),
])
def test_video_review_legacy_enqueue_and_failure_retry_are_distinct(status, endpoint, label):
    _run_page_js(render_video_review(),
        f"replies.push({{task:{{...baseTask,analysis_status:{json.dumps(status)}}},result:null}});",
        f"""
        assert.equal($('retryButton').hidden,false);
        assert.equal($('retryButton').textContent,{json.dumps(label)});
        replies.push({{task:baseTask}},{{task:baseTask,result:null}});
        await $('retryButton').fire('click');
        const post=requests.find(r=>r.options.method==='POST');
        assert.equal(post.url,'/api/v1/demo2/upload/tasks/{endpoint}');
        assert.deepEqual(JSON.parse(post.options.body),{{task_id:'video-1'}});
        assert.equal($('stageLabel').textContent,'等待处理');
        assert.equal($('retryButton').hidden,true);
        """)


def test_video_review_expired_media_keeps_records_without_loading_audio():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'evidence_ready',raw_media_deleted_at:'2026-09-08',media_url:null},result:evidence});",
        r"""
        assert.equal(segments.length,25);assert.equal($('downloadResult').hidden,false);
        assert.equal(video.getAttribute('src'),null);assert.equal(audio.getAttribute('src'),null);
        assert.equal(audio.hidden,true);assert.equal(video.hidden,true);
        assert.equal($('retryButton').hidden,true);assert.equal($('seekSlider').disabled,true);
        assert.match($('mediaEmpty').textContent,/到期/);assert.equal(timers.size,0);
        """)


def test_video_review_playback_follows_slices_and_preserves_pending_seek():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:evidence});",
        r"""
        selectSegment(3);assert.equal(pendingVideoTime,90);
        video.readyState=1;video.duration=750;await video.fire('loadedmetadata');
        assert.equal(video.currentTime,90);assert.equal(pendingVideoTime,null);
        audio.readyState=1;audio.duration=750;await audio.fire('loadedmetadata');
        assert.equal(audio.currentTime,90);
        video.currentTime=635;await video.fire('timeupdate');
        assert.equal(selected,21);assert.equal(page,1);
        assert.equal($('selectedPeriod').textContent,'10:30 - 11:00');
        assert.equal($('motionMetric').textContent,'0.0123');
        $('seekSlider').value='45';await $('seekSlider').fire('input');
        assert.equal(selected,1);assert.equal(page,0);
        audio.currentTime=100;await audio.fire('timeupdate');assert.equal(selected,3);
        video.paused=false;await audio.fire('play');assert.equal(video.paused,true);
        audio.paused=false;await video.fire('play');assert.equal(audio.paused,true);
        """)


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_video_review_access_errors_stop_polling_and_clear_playback(status):
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:evidence});",
        f"""
        replies.push({{status:{status},body:{{}}}});await refresh();
        assert.equal(timers.size,0);assert.equal(video.src,'');assert.equal(audio.src,'');
        assert.equal($('downloadResult').hidden,true);assert.equal($('retryButton').hidden,true);
        assert.equal(segments.length,0);
        {'assert.equal(location.assigned,"/demo2/login");' if status == 401 else ''}
        """)


def test_video_review_empty_and_missing_results_are_not_learning_failures():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:null});",
        r"""
        assert.equal($('downloadResult').hidden,true);assert.match($('segmentsEmpty').textContent,/同步/);
        assert.ok([...timers.values()].some(t=>t.delay===2000));
        replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:{media:{has_audio:false},segments:[]}});await refresh();
            assert.equal($('reviewState').textContent,'暂无可查看切片');
        assert.equal($('durationMetric').textContent,'未取得');assert.equal(audio.hidden,true);
        assert.equal(timers.size,0);
        """)


def test_video_review_visibility_pauses_polling_and_restores_it():
    _run_page_js(render_video_review(),
        "replies.push({task:baseTask,result:null});",
        r"""
        document.hidden=true;listeners.get('visibilitychange')();assert.equal(timers.size,0);
        replies.push({task:baseTask,result:null});document.hidden=false;
        listeners.get('visibilitychange')();await flush();assert.equal(timers.size,1);
        listeners.get('pagehide')();assert.equal(timers.size,0);assert.equal(stopped,true);
        replies.push({task:baseTask,result:null});listeners.get('pageshow')({persisted:true});
        await flush();assert.equal(stopped,false);assert.equal(timers.size,1);
        """)


def test_upload_polling_recovers_without_focusing_an_error_banner():
    _run_page_js(render_demo2_upload_html(),
        "location.search='';replies.push({context:{}},{account:{username:'teacher',bound_channel_id:'channel_1'}});",
        r"""
        byId('courseId').value='course-1';
        const initial={course_id:'course-1',remaining_slots:4,used_slots:1,max_slots:5,tasks:[baseTask]};
        replies.push({workspace:initial});await loadWorkspace();
        assert.ok([...timers.values()].some(t=>t.delay===4000));
        replies.push(new Error('network offline'));await timers.get(taskPollTimer).fn();
        assert.ok([...timers.values()].some(t=>t.delay===5000));
        assert.match(byId('taskPollStatus').textContent,/5 秒/);
        assert.equal(document.activeElement,null);
        replies.push({workspace:{...initial,tasks:[{...baseTask,analysis_status:'evidence_ready',processing_progress:100}]}});
        await timers.get(taskPollTimer).fn();
        assert.match(byId('taskList').innerHTML,/查看视频证据/);
        assert.match(byId('taskList').innerHTML,/学生课堂状态/);
        assert.equal(timers.size,0);
        """)


def test_upload_success_clears_file_and_consent_but_keeps_processing_entry():
    _run_page_js(render_demo2_upload_html(),
        r"""
        location.search='';replies.push({context:{city:'Synthetic City',district:'Synthetic District',school_name:'Synthetic School'}},{account:{username:'teacher',bound_channel_id:'channel_1'}});
        class XMLHttpRequest {
          constructor(){this.upload={};}
          open(method,url){this.url=url;}setRequestHeader(){}
          send(){this.status=200;this.responseText=JSON.stringify({task:{...baseTask,byte_size:1,received_bytes:1,next_chunk_index:1}});this.onload();this.onloadend?.();}
        }
        """,
        r"""
        byId('courseId').value='course-1';byId('courseName').value='数学';
        const initial={course_id:'course-1',remaining_slots:5,used_slots:0,max_slots:5,tasks:[]};
        replies.push({workspace:initial});await loadWorkspace();
        byId('videoFile').files=[{name:'class.mp4',size:1,type:'video/mp4',slice(){return {};}}];
        preflightVideo=async()=>60;
        byId('allowCompanyArchive').value='yes';
        replies.push({task:{...baseTask,upload_status:'uploading'}},{task:{...baseTask,upload_status:'uploading',byte_size:1,received_bytes:0,next_chunk_index:0}},{workspace:{...initial,remaining_slots:4,used_slots:1,tasks:[baseTask]}});
        await uploadVideo();
        const create=requests.find(r=>r.url==='/api/v1/demo2/upload/tasks');
        const payload=JSON.parse(create.options.body);
        assert.equal(payload.security_confirmed,true);assert.equal(payload.allow_company_archive,true);
        assert.equal(payload.channel_id,'channel_1');assert.equal(payload.total_chunks,1);
        assert.equal(byId('videoFile').files.length,0);assert.equal(byId('allowCompanyArchive').value,'no');
        assert.equal(byId('uploadButton').disabled,true);assert.equal(byId('courseId').disabled,false);
        assert.match(byId('taskList').innerHTML,/查看处理任务/);
        assert.match(byId('pageMessage').textContent,/正在后台分析/);
        """)


def test_video_review_missing_task_and_untrusted_media_do_not_start_playback():
    _run_page_js(render_video_review(), "location.search='';",
        r"""
        assert.equal(requests.length,0);assert.equal(timers.size,0);
        assert.equal($('stageLabel').textContent,'未选择任务');
        assert.equal(sameOriginUrl('https://other.test/video.mp4'),'');
        assert.equal(sameOriginUrl('javascript:alert(1)'),'');
        assert.equal(sameOriginUrl('/api/v1/demo2/upload/media?id=video-1'),'/api/v1/demo2/upload/media?id=video-1');
        """)


def test_video_review_retains_legacy_download_without_claiming_video_evidence():
    _run_page_js(render_video_review(),
        "replies.push({task:{...baseTask,analysis_status:'precheck_complete',secure_result_download_url:'/api/v1/demo2/upload/result?id=video-1'},result:{precheck:{frames:40}}});",
        r"""
        assert.equal($('downloadResult').hidden,false);
        assert.equal($('downloadLabel').textContent,'下载历史预检记录');
        assert.equal($('downloadResult').href,'/api/v1/demo2/upload/result?id=video-1');
        assert.equal(segments.length,0);assert.equal(loadedResult,false);
        assert.equal($('retryButton').textContent,'开始处理');
        assert.match($('segmentsEmpty').textContent,/开始处理/);
        assert.equal(timers.size,0);
        """)
