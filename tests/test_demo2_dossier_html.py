"""Dossier UI contracts and serial browser tests using disposable SQLite and files.

The HTTP adapter below exists only inside the fixture, on a random loopback port.
It never opens live 8792 or a production database. Production HTTP security is
covered by the backend/release owners; these tests exercise real store results.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
import pytest

from rehab_affect.demo2_dossier import COMMON, render_admin, render_student, render_task
from rehab_affect.demo2_dossier_store import Demo2DossierStore, DossierError
from rehab_affect.demo2_identity import render_students
from rehab_affect.demo2_identity_store import Demo2IdentityStore
from rehab_affect.demo2_portal import render_demo2_admin_html
from rehab_affect.demo2_video_review import render_video_review
from rehab_affect.student_record_store import Demo2StudentRecordStore
from test_demo2_identity_store import binding_payload, login, make_task


TEACHER = {"role": "school_uploader", "username": "synthetic-ui-teacher"}
ADMIN = {"role": "company_admin", "username": "synthetic-ui-admin"}


@pytest.mark.parametrize("render", [render_student, render_task, render_admin])
def test_html_structure_and_inline_script_safety(render):
    html = render({**TEACHER, "username": "</script><script>bad()</script>"})
    assert '<html lang="zh-CN">' in html
    assert 'name="viewport"' in html
    assert 'href="#mainContent"' in html
    assert "credentials:'same-origin'" in html
    assert "cache:'no-store'" in html
    assert "AbortController" in html and "if(response.status===401)" in html
    assert "</script><script>bad()" not in html
    assert "<script src=" not in html and "localStorage" not in html
    assert "window.confirm" in html and "beforeunload" in html
    assert "不宣称已完成法律合规认证" in html
    node = shutil.which("node")
    assert node, "Installed Node.js required; no downloads"
    result = subprocess.run([node, "-e", "JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
                            input=json.dumps(re.findall(r"<script>(.*?)</script>", html, re.S)),
                            text=True, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_minimal_navigation_and_unchecked_authorization():
    student = render_student(TEACHER)
    assert 'id="studentVerified" type="checkbox" disabled' in student
    assert 'id="authorizationConfirmed" type="checkbox" required' in student
    assert 'id="storageMode" required><option value="">' in student
    assert 'type="checkbox" checked' not in student
    assert "不会读取或上传原件" in student and "即将到期" in student
    assert "file=original?" in student and "filename:file?file.name:''" in student
    assert "content_base64:''" in student and "supersedes_id:" in student
    assert "/demo2/dossier?student_id=" in render_students(TEACHER)
    assert "/demo2/course-dossier?task_id=" in render_video_review(TEACHER)
    assert "/demo2/admin/dossiers" in render_demo2_admin_html(ADMIN)
    assert "千字报告已读取" not in render_task(TEACHER)
    assert "所选日期零点起不可访问" in student
    assert "Asia/Shanghai" in student


@pytest.mark.parametrize("now,expected,next_day", [
    ("2026-09-11T00:30:00+08:00", "2026-09-11", "2026-09-12"),
    ("2026-09-30T23:55:00+08:00", "2026-09-30", "2026-10-01"),
    ("2026-12-31T23:55:00+08:00", "2026-12-31", "2027-01-01"),
])
def test_local_date_and_fifteen_day_reminder_boundaries(now, expected, next_day):
    helpers = "\n".join(line for line in COMMON.splitlines()
                        if line.startswith(("const dateString=", "const today=", "const usableDocument=", "const expiryNotice=")))
    script = r"""
const {now,expected,next_day,helpers}=JSON.parse(require('fs').readFileSync(0,'utf8'));
const assert=require('node:assert/strict'),RealDate=Date;
global.Date=class extends RealDate{constructor(...args){super(...(args.length?args:[now]));}static now(){return new RealDate(now).valueOf();}};
const esc=value=>String(value);
eval(helpers+`;assert.equal(today(),expected);assert.equal(future(1),next_day);
assert.equal(usableDocument({available:true,retain_until:today()}),false);
assert.equal(expiryNotice({available:true,retain_until:today()}),'');
assert.match(expiryNotice({available:true,retain_until:future(1)}),/即将到期/);
assert.match(expiryNotice({available:true,retain_until:future(15)}),/即将到期/);
assert.equal(expiryNotice({available:true,retain_until:future(16)}),'');
assert.equal(expiryNotice({available:false,retain_until:future(1)}),'');`);
"""
    result = subprocess.run([shutil.which("node"), "-e", script],
                            input=json.dumps({"now": now, "expected": expected, "next_day": next_day, "helpers": helpers}),
                            text=True, encoding="utf-8", capture_output=True, timeout=15,
                            env={**os.environ, "TZ": "Asia/Shanghai"})
    assert result.returncode == 0, result.stderr


@pytest.fixture
def ui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "IdentityTest-")
    monkeypatch.setenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", "5")
    monkeypatch.setenv("REHAB_DEMO2_DOSSIER_KEY", Fernet.generate_key().decode())
    records = Demo2StudentRecordStore(tmp_path / "dossier_ui.sqlite3", tmp_path / "documents")
    env = SimpleNamespace(record=records, identity=Demo2IdentityStore(records), sessions={}, tmp=tmp_path)
    env.task = make_task(env, count=1)
    env.token = env.task.token
    env.student = env.identity.create_student(env.token, {"display_name": "虚构测试学生（非真实资料）", "student_code": "UI-01", "class_name": "虚构一班"})
    env.identity.save_binding(env.token, binding_payload(env.task, env.student["student_id"]))
    env.admin_token = login(env, "company_admin")[1]
    env.dossiers = Demo2DossierStore(records, env.identity)
    env.today = date.today().isoformat()
    env.until = (date.today() + timedelta(days=30)).isoformat()
    env.retain = (date.today() + timedelta(days=10)).isoformat()
    env.calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body, content_type="application/json", filename=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, private")
            if filename:
                self.send_header("Content-Disposition", 'attachment; filename="fixture.txt"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_dossier(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            token = env.admin_token if "role=admin" in self.headers.get("Cookie", "") else env.token
            env.calls.append((self.command, parsed.path))
            pages = {"/demo2/dossier": (render_student, TEACHER), "/demo2/course-dossier": (render_task, TEACHER),
                     "/demo2/admin/dossiers": (render_admin, ADMIN)}
            if parsed.path in pages:
                renderer, account = pages[parsed.path]
                return self.respond(200, renderer(account).encode(), "text/html; charset=utf-8")
            if parsed.path == "/demo2/login":
                return self.respond(200, b"<h1>Isolated login fixture</h1>", "text/html")
            prefix = "/api/v1/demo2/dossier"
            if not parsed.path.startswith(prefix):
                return self.respond(404, {"error": {"message": "Isolated route not found"}})
            route = parsed.path[len(prefix):]
            try:
                if self.command == "POST":
                    payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    methods = {"/authorization": (env.dossiers.save_authorization, "authorization"),
                               "/authorization/withdraw": (env.dossiers.withdraw_authorization, "result"),
                               "/documents": (env.dossiers.create_document, "document"),
                               "/documents/delete": (env.dossiers.delete_document, "result"),
                               "/references": (env.dossiers.create_reference, "reference")}
                    method, key = methods[route]
                    return self.respond(200, {"ok": True, key: method(token, payload)})
                if route == "/student":
                    return self.respond(200, {"ok": True, "workspace": env.dossiers.student_workspace(token, query["student_id"][0])})
                if route == "/task":
                    return self.respond(200, {"ok": True, "workspace": env.dossiers.task_workspace(token, query["task_id"][0])})
                if route == "/admin":
                    return self.respond(200, {"ok": True, "summary": env.dossiers.admin_summary(token)})
                if route == "/document":
                    data, name, mime = env.dossiers.document_download(token, query["document_id"][0])
                    return self.respond(200, data, mime, name)
                if route == "/reference":
                    return self.respond(200, env.dossiers.reference_export(token, query["reference_id"][0]), filename="reference.json")
                return self.respond(404, {"error": {"message": "Isolated route not found"}})
            except DossierError as error:
                return self.respond(error.status, {"error": {"code": error.code, "message": error.message}})

        do_GET = handle_dossier
        do_POST = handle_dossier

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    env.base = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield env
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def seed_document(env, mode="summary_only"):
    auth = env.dossiers.save_authorization(env.token, {"student_id": env.student["student_id"], "reference": "虚构授权编号 UI-TEST（非真实授权）", "storage_mode": mode, "valid_until": env.until, "confirmed": True})
    return env.dossiers.create_document(env.token, {"student_id": env.student["student_id"], "authorization_id": auth["authorization_id"], "document_type": "iep", "document_date": env.today, "source_ref": "虚构资料出处 UI-TEST", "retain_until": env.retain, "summary": {"learning_goals": "仅用于界面测试的虚构目标", "support_methods": "", "safety_notes": "", "professional_conclusion": ""}, "filename": "", "content_base64": "", "supersedes_id": ""})


BROWSER = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8')),assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require(input.module);const browser=await chromium.launch({headless:true,executablePath:input.executable});
try{const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true,reducedMotion:'reduce',timezoneId:'Asia/Shanghai'});const page=await context.newPage();const errors=[],posts=[];page.setDefaultTimeout(12000);page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.method()==='POST')posts.push({url:request.url(),data:request.postDataJSON()});});
await context.route('**/*',route=>new URL(route.request().url()).origin===input.base?route.continue():route.abort());
await page.addInitScript(()=>{const original=window.fetch;window.fetch=(url,options)=>{if(options?.credentials!=='same-origin')throw new Error('same-origin credentials missing');return original(url,options);};});
const studentUrl=input.base+'/demo2/dossier?student_id='+input.student_id,taskUrl=input.base+'/demo2/course-dossier?task_id='+input.task_id;
const ready=async()=>{await page.waitForFunction(()=>!document.getElementById('refreshButton').disabled);};
const openStudent=async()=>{await page.goto(studentUrl);await ready();};
const saved=async()=>{await page.locator('#pageMessage.success').waitFor();await ready();};
const authorize=async(mode='summary_only')=>{await page.locator('#studentVerified').check();await page.locator('#tabAuthorization').click();await page.locator('#authorizationReference').fill('虚构授权 UI-TEST');await page.locator('#storageMode').selectOption(mode);await page.locator('#authorizationUntil').fill(input.until);await page.locator('#authorizationConfirmed').check();await page.locator('#saveAuthorization').click();await saved();};
const fillDocument=async()=>{await page.locator('#tabDocuments').click();if(await page.locator('#documentType').isEnabled())await page.locator('#documentType').selectOption('iep');await page.locator('#documentDate').fill(input.today);await page.locator('#retainUntil').fill(input.retain);await page.locator('#sourceRef').fill('虚构资料出处 UI-TEST');await page.locator('#learning_goals').fill('仅用于界面验证的虚构学习目标');};
const noOverflow=async()=>assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
const capture=async(name)=>{if(input.screenshots){fs.mkdirSync(input.screenshots,{recursive:true});await page.screenshot({path:require('path').join(input.screenshots,name+'.png'),fullPage:true});}};
__SCENARIO__
assert.deepEqual(errors,[]);await context.close();}finally{await browser.close();}
"""


def browser(env, scenario):
    node = shutil.which("node")
    modules = [Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright",
               Path.home() / "AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright"]
    module = next((str(path) for path in modules if path.exists()), None)
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "ms-playwright"
    executables = [Path(os.environ.get("DEMO2_BROWSER_EXECUTABLE", "not-configured")),
                   *sorted(root.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)]
    executable = next((str(path) for path in executables if path.is_file()), None)
    if not node or not module or not executable:
        pytest.skip("Installed Node and Playwright Chromium required; no browser downloads")
    data = {"base": env.base, "student_id": env.student["student_id"], "task_id": env.task.task_id,
            "today": env.today, "until": env.until, "retain": env.retain, "module": module, "executable": executable,
            "screenshots": os.environ.get("DEMO2_DOSSIER_UI_SCREENSHOTS")}
    result = subprocess.run([node, "-e", "(async()=>{" + BROWSER.replace("__SCENARIO__", scenario) + "})().catch(e=>{console.error(e);process.exit(1)});"],
                            input=json.dumps(data), encoding="utf-8", text=True, capture_output=True, timeout=75)
    assert result.returncode == 0, result.stdout + result.stderr


def test_browser_summary_versions_reference_and_withdrawal(ui_env):
    browser(ui_env, r"""
    await openStudent();assert.equal(await page.locator('#authorizationFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#authorizationConfirmed').isChecked(),false);assert.equal(await page.locator('#storageMode').inputValue(),'');assert.equal(posts.length,0);
    await authorize();assert.deepEqual(Object.keys(posts[0].data).sort(),['student_id','reference','storage_mode','valid_until','confirmed'].sort());await fillDocument();
    await page.locator('#documentFile').setInputFiles({name:'must-not-upload.txt',mimeType:'text/plain',buffer:Buffer.from('SYNTHETIC ORIGINAL NOT AUTHORIZED')});
    await page.evaluate(()=>{FileReader.prototype.readAsDataURL=()=>{throw new Error('Summary mode must never read a file');};});
    await page.locator('#saveDocument').click();await saved();assert.equal(posts[1].data.filename,'');assert.equal(posts[1].data.content_base64,'');assert.equal(posts[1].data.student_id,input.student_id);assert.equal(posts[1].data.supersedes_id,'');assert.match(await page.locator('#documentList').textContent(),/即将到期/);assert.deepEqual(Object.keys(posts[1].data).sort(),['student_id','authorization_id','document_type','document_date','source_ref','retain_until','summary','filename','content_base64','supersedes_id'].sort());assert.deepEqual(Object.keys(posts[1].data.summary).sort(),['learning_goals','support_methods','safety_notes','professional_conclusion'].sort());
    const first=(await (await page.request.get(input.base+'/api/v1/demo2/dossier/student?student_id='+input.student_id)).json()).workspace.documents[0];
    await page.locator('[data-version]').click();await fillDocument();await page.locator('#learning_goals').fill('第二版虚构目标');await page.locator('#saveDocument').click();await saved();assert.equal(posts[2].data.supersedes_id,first.document_id);assert.equal(await page.locator('#documentList .record').count(),2);
    await page.goto(taskUrl);await ready();assert.equal(await page.locator('#referenceStudent option').count(),2);await page.locator('#referenceStudent').selectOption(input.student_id);await page.locator('[data-doc-id="'+first.document_id+'"]').check();assert.equal(await page.locator('#saveReference').isEnabled(),false);await page.locator('#referenceConfirmed').check();await page.locator('#saveReference').click();await saved();assert.deepEqual(Object.keys(posts[3].data).sort(),['task_id','student_id','frame_revision','document_ids','confirmed'].sort());assert.deepEqual(posts[3].data.document_ids,[first.document_id]);
    const event=page.waitForEvent('download');await page.locator('[data-reference]').click();const file=await event;const exported=JSON.parse(fs.readFileSync(await file.path(),'utf8'));assert.equal(exported.document_versions[0].version,1);assert.equal(exported.document_versions[0].document_id,first.document_id);
    await openStudent();await page.locator('#studentVerified').check();await page.locator('#tabAuthorization').click();const before=posts.length;page.once('dialog',dialog=>dialog.dismiss());await page.locator('#withdrawAuthorization').click();assert.equal(posts.length,before);page.once('dialog',dialog=>dialog.accept());await page.locator('#withdrawAuthorization').click();await saved();await page.locator('#tabDocuments').click();assert.equal(await page.locator('[data-document],[data-delete]').count(),0);assert.doesNotMatch(await page.locator('#documentList').textContent(),/第二版虚构目标|虚构资料出处/);await page.locator('#tabReferences').click();assert.match(await page.locator('#referenceList').textContent(),/资料来源已不可用/);
    """)
    work = ui_env.dossiers.student_workspace(ui_env.token, ui_env.student["student_id"])
    assert work["authorization"] is None
    assert len(work["documents"]) == 2 and all(not doc["available"] for doc in work["documents"])


def test_browser_optional_original_download_and_delete(ui_env):
    browser(ui_env, r"""
    await openStudent();await authorize('original_and_summary');await fillDocument();await page.locator('#learning_goals').fill('');await page.locator('#documentFile').setInputFiles({name:'fixture.txt',mimeType:'text/plain',buffer:Buffer.from('SYNTHETIC UI FIXTURE ONLY')});await page.locator('#saveDocument').click();await saved();assert.equal(posts[1].data.filename,'fixture.txt');assert.equal(Buffer.from(posts[1].data.content_base64,'base64').toString(),'SYNTHETIC UI FIXTURE ONLY');
    const wait=page.waitForEvent('download');await page.locator('[data-document]').click();assert.equal(fs.readFileSync(await (await wait).path(),'utf8'),'SYNTHETIC UI FIXTURE ONLY');
    page.once('dialog',dialog=>dialog.accept());await page.locator('[data-delete]').click();await saved();assert.equal(await page.locator('[data-document]').count(),0);assert.match(await page.locator('#documentList').textContent(),/已删除|不可访问/);
    """)


def test_browser_uncertain_write_locks_until_real_refresh(ui_env):
    browser(ui_env, r"""
    await openStudent();await authorize();await fillDocument();await page.route('**/dossier/documents',async route=>{await route.fetch();await route.abort('internetdisconnected');});await page.locator('#saveDocument').click();await page.waitForFunction(()=>document.getElementById('pageMessage').textContent.includes('暂停写入'));assert.equal(await page.locator('#pageMessage.success').count(),0);assert.equal(await page.locator('#documentFields').evaluate(el=>el.disabled),true);assert.equal(posts.filter(p=>p.url.endsWith('/documents')).length,1);
    await page.unroute('**/dossier/documents');page.once('dialog',dialog=>dialog.accept());await page.locator('#refreshButton').click();await ready();assert.equal(await page.locator('#documentList .record').count(),1);assert.equal(posts.filter(p=>p.url.endsWith('/documents')).length,1);
    """)


@pytest.mark.parametrize("status", [401, 403, 503])
def test_browser_read_errors_never_enable_writes(ui_env, status):
    browser(ui_env, f"const status={status};" + r"""
    await page.route('**/dossier/student?*',route=>route.fulfill({status,contentType:'application/json',body:JSON.stringify({error:{message:'测试服务拒绝当前请求'}})}));if(status===401)await page.goto(studentUrl);else await openStudent();
    if(status===401)await page.waitForURL('**/demo2/login');else{assert.equal(await page.locator('#authorizationFields').evaluate(el=>el.disabled),true);assert.match(await page.locator('#pageMessage').textContent(),status===403?/无权/:/测试服务拒绝/);}assert.equal(posts.length,0);
    """)


def test_browser_mobile_expired_redaction_and_admin_metadata_only(ui_env):
    seed_document(ui_env)
    browser(ui_env, r"""
    await openStudent();await page.locator('#studentVerified').check();for(const width of [1440,768,390,320]){await page.setViewportSize({width,height:950});await noOverflow();if(width===390)await capture('dossier-student-390');}
    await page.route('**/dossier/student?*',async route=>{const response=await route.fetch(),body=await response.json();body.workspace.documents[0]={...body.workspace.documents[0],available:false,status:'expired',source_ref:'MUST_NOT_RENDER_SOURCE',filename:'MUST_NOT_RENDER_FILE',summary:{learning_goals:'MUST_NOT_RENDER_SUMMARY'}};body.workspace.references=[{reference_id:'synthetic-ref',created_at:'2026-09-11',available:true,evidence_status:'outdated_revision',document_versions:[{document_id:'synthetic-doc',version:1}]}];await route.fulfill({response,json:body});});await page.locator('#refreshButton').click();await ready();assert.doesNotMatch(await page.locator('#documentList').textContent(),/MUST_NOT_RENDER/);await page.locator('#tabReferences').click();assert.match(await page.locator('#referenceList').textContent(),/身份版本已变化|不可用或未确认/);
    await page.goto(taskUrl);await ready();await page.locator('#referenceStudent').selectOption(input.student_id);assert.ok((await page.locator('#selectedStudentContext').textContent()).includes(input.student_id));await noOverflow();await capture('dossier-task-320');
    await context.addCookies([{name:'role',value:'admin',url:input.base}]);await page.route('**/dossier/admin',async route=>{const response=await route.fetch(),body=await response.json();body.summary.student_name='MUST_NOT_RENDER_NAME';body.summary.filename='MUST_NOT_RENDER_FILE';body.summary.reference='MUST_NOT_RENDER_REFERENCE';body.summary.channels[0].summary='MUST_NOT_RENDER_SUMMARY';await route.fulfill({response,json:body});});await page.goto(input.base+'/demo2/admin/dossiers');await ready();for(const width of [1440,768,390,320]){await page.setViewportSize({width,height:950});await noOverflow();if(width===390)await capture('dossier-admin-390');}assert.doesNotMatch(await page.locator('body').textContent(),/MUST_NOT_RENDER|虚构测试学生|虚构资料出处/);assert.equal(await page.locator('form,[data-document],[data-reference]').count(),0);
    """)
