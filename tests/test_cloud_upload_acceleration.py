"""Cloud-only upload regressions; no listening sockets or production data.

Load overrides in a private package, with src used for unchanged dependencies.
REHAB_CLOUD_REFERENCE_SOURCE selects an original rehab_affect package directory
for the reference backend (defaults to local src). Never replace app imports.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.machinery
import io
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import urlencode, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / ".runtime" / "cloud_release_overrides"
SOURCE = ROOT / "src" / "rehab_affect"
NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
SCHOOL = {"city": "Synthetic City", "district": "Synthetic District", "school_name": "Synthetic School"}


@contextmanager
def _modules(name, paths):
    package = ModuleType(name)
    package.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    package.__path__ = [str(path) for path in paths]
    sys.modules[name] = package
    try:
        loaded = SimpleNamespace(**{
            key: importlib.import_module(f"{name}.{filename}")
            for key, filename in (("store", "student_record_store"),
                                  ("server", "scenario_lab_server"), ("portal", "demo2_portal"))
        })
        for module in vars(loaded).values():
            assert Path(module.__file__).resolve().parent == paths[0]
        assert loaded.server.VideoUploadError is loaded.store.VideoUploadError
        assert loaded.server.get_demo2_student_store is loaded.store.get_demo2_student_store
        yield loaded
    finally:
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                del sys.modules[key]


@pytest.fixture(scope="module")
def cloud():
    # The first search path MUST be the cloud overrides, not src or PYTHONPATH.
    with _modules("_cloud_upload_acceleration", [OVERRIDES, SOURCE]) as modules:
        yield modules


@pytest.fixture(scope="module")
def source_reference():
    reference = Path(os.environ.get("REHAB_CLOUD_REFERENCE_SOURCE", str(SOURCE))).expanduser().resolve()
    with _modules("_cloud_upload_source_reference", [reference]) as modules:
        yield modules


@pytest.fixture()
def make_env(tmp_path, monkeypatch):
    def create(modules, name="cloud"):
        monkeypatch.setattr(modules.store, "_now", lambda: NOW)
        monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "CloudRegression-")
        store = modules.store.Demo2StudentRecordStore(tmp_path / name / "db.sqlite3", tmp_path / name / "documents")
        accounts, tokens = {}, {}
        with store._connect() as db:
            for row in db.execute("SELECT * FROM platform_accounts"):
                accounts[row["username"]] = store._public_account(dict(row))
        for username in ("school_uploader_01", "school_uploader_02", "company_admin"):
            tokens[username] = store.create_account_session(accounts[username])["token"]
        owner = accounts["school_uploader_01"]["account_id"]
        with store._connect() as db:
            db.execute(
                "INSERT INTO school_contexts (account_id,city,district,school_name,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?)", (owner, *SCHOOL.values(), modules.store._iso(), modules.store._iso()),
            )
        monkeypatch.setattr(modules.server, "get_demo2_student_store", lambda: store)
        handler_type = modules.server.create_handler(
            scenario_dir=tmp_path, model_path=tmp_path / "unused.json", policy_name="rule",
        )
        return SimpleNamespace(modules=modules, store=store, accounts=accounts, tokens=tokens,
                               owner=owner, handler_type=handler_type)
    return create


@pytest.fixture()
def env(make_env, cloud):
    return make_env(cloud)


def _create(env, **changes):
    size = changes.pop("byte_size", 3)
    return env.store.create_video_task({
        "account_id": env.owner, "channel_id": "channel_1", "session_id": "synthetic-session",
        "course_id": "synthetic-course", "course_name": "Synthetic Course", "uploader_name": "Test",
        "filename": "synthetic.mp4", "byte_size": size,
        "total_chunks": (size + env.modules.store.MAX_VIDEO_CHUNK_BYTES - 1) // env.modules.store.MAX_VIDEO_CHUNK_BYTES,
        **changes,
    })


def _raw(env, task):
    with env.store._connect() as db:
        return dict(db.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task["task_id"],)).fetchone())


def _append(env, task, index, data):
    return env.store.append_video_chunk({
        "task_id": task["task_id"], "course_id": task["course_id"], "chunk_index": index,
        "account_session_token": env.tokens["school_uploader_01"],
    }, chunk=data)


class _Connection:
    timeout = None

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value


def _post(env, payload, *, binary=False, username="school_uploader_01", origin=None, before_read=None):
    """Execute the actual POST dispatch/body/auth path without opening a socket."""
    handler = env.handler_type.__new__(env.handler_type)
    handler.command = "POST"
    handler.path = "/api/v1/demo2/upload/chunks"
    if binary:
        handler.path += "?" + urlencode({key: payload[key] for key in ("task_id", "course_id", "chunk_index")})
        body, content_type = b"end", "application/octet-stream"
    else:
        body, content_type = json.dumps(payload).encode(), "application/json"
    handler.headers = Message()
    for key, value in {
        "Content-Type": content_type, "Content-Length": str(len(body)), "Host": "cloud.test",
        "Cookie": "rehab_demo2_session=" + env.tokens.get(username, "invalid-token"),
        **({"Origin": origin} if origin else {}),
    }.items():
        handler.headers[key] = value
    handler.rfile, handler.wfile, handler.connection = io.BytesIO(body), io.BytesIO(), _Connection()
    handler.close_connection = False
    responses = []
    handler._send_demo2_json = lambda data, *, status=200, headers=None: responses.append((status, data))
    handler._send_json_error = lambda status, code, message: responses.append((status, {"error": {"code": code}}))
    if before_read:
        read = handler._read_upload_body

        def mutate_then_read(**kwargs):
            before_read()
            return read(**kwargs)
        handler._read_upload_body = mutate_then_read
    handler._handle_demo2_api_post(urlparse(handler.path))
    assert len(responses) == 1
    return responses[0]


def test_all_three_modules_are_overrides(cloud):
    for module in vars(cloud).values():
        assert Path(module.__file__).resolve().parent == OVERRIDES
        assert Path(module.__spec__.origin).resolve() == Path(module.__file__).resolve()


def test_same_second_skips_only_redundant_updates_and_advances_next_second(env, monkeypatch):
    module, store, statements = env.modules.store, env.store, []
    token = env.tokens["school_uploader_01"]
    with store._connect() as db:
        db.execute("UPDATE account_sessions SET last_seen_at='' WHERE account_id=?", (env.owner,))
    connect = store._connect

    @contextmanager
    def traced():
        with connect() as db:
            db.set_trace_callback(statements.append)
            yield db
    monkeypatch.setattr(store, "_connect", traced)
    first = store.account_from_session(token)
    for _ in range(5):
        assert store.account_from_session(token) == first
    updates = lambda: [sql for sql in statements if re.match(r"\s*UPDATE account_sessions SET last_seen_at", sql)]
    assert len(updates()) == 1
    assert sum("JOIN platform_accounts" in sql for sql in statements) == 6
    monkeypatch.setattr(module, "_now", lambda: NOW + timedelta(seconds=1))
    assert store.account_from_session(token) == first
    store.account_from_session(token)
    assert len(updates()) == 2
    with store._connect() as db:
        row = db.execute("SELECT last_seen_at, expires_at FROM account_sessions WHERE session_id=?", (first["session_id"],)).fetchone()
    assert row["last_seen_at"] == module._iso(NOW + timedelta(seconds=1))
    assert row["expires_at"] == first["session_expires_at"]  # No sliding expiry.
    assert "session_last_seen_at" not in first and "password_hash" not in first


@pytest.mark.parametrize("mutation", ["revoked", "disabled", "deleted", "expired", "at_expiry", "malformed_expiry"])
def test_same_second_session_permission_changes_are_not_cached(env, mutation):
    store, token = env.store, env.tokens["school_uploader_01"]
    account = store.account_from_session(token)
    with store._connect() as db:
        if mutation == "revoked":
            db.execute("UPDATE account_sessions SET revoked_at=? WHERE session_id=?", (env.modules.store._iso(), account["session_id"]))
        elif mutation == "disabled":
            db.execute("UPDATE platform_accounts SET status='disabled' WHERE account_id=?", (env.owner,))
        elif mutation == "deleted":
            db.execute("DELETE FROM account_sessions WHERE session_id=?", (account["session_id"],))
        else:
            expiry = {"expired": env.modules.store._iso(NOW - timedelta(seconds=1)),
                      "at_expiry": env.modules.store._iso(), "malformed_expiry": "not-a-date"}[mutation]
            db.execute("UPDATE account_sessions SET expires_at=? WHERE session_id=?", (expiry, account["session_id"]))
    for _ in range(2):
        with pytest.raises(ValueError):
            store.account_from_session(token)
    if mutation in {"expired", "at_expiry", "malformed_expiry"}:
        with store._connect() as db:
            assert db.execute("SELECT revoked_at FROM account_sessions WHERE session_id=?", (account["session_id"],)).fetchone()[0]
            assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='session_expired' AND object_id=?", (account["session_id"],)).fetchone()[0] == 1
    with pytest.raises(ValueError):
        store.account_from_session("invalid-token")


def test_same_second_reads_live_role_binding_and_limit(env):
    token = env.tokens["school_uploader_01"]
    env.store.account_from_session(token)
    with env.store._connect() as db:
        db.execute("UPDATE platform_accounts SET role='company_admin',bound_channel_id=NULL,course_upload_limit=3 WHERE account_id=?", (env.owner,))
    account = env.store.account_from_session(token)
    assert (account["role"], account["bound_channel_id"], account["course_upload_limit"]) == ("company_admin", None, 3)


PERMISSION_CASES = [
    ("owner", 200), ("foreign_owner", 403), ("forged_account", 403), ("missing_task", 403),
    ("anonymous", 401), ("blank_task", 400), ("legacy_empty_school", 200), ("legacy_unowned_task", 403),
    ("wrong_course", 403), ("blank_course", 400), ("unbound_channel", 403), ("rebound_channel", 403),
    ("changed_school", 403), ("disabled", 401), ("admin", 403), ("revoked", 401),
    ("expired_session", 401), ("cancelled", 409), ("expired_media", 400), ("paused_channel", 200),
]


def _mutate_permission(env, task, mutation, payload):
    username = "school_uploader_01"
    if mutation in {"foreign_owner", "forged_account"}:
        username = "school_uploader_02"
        if mutation == "forged_account":
            payload.update(account_id=env.owner, account_session_token=env.tokens["school_uploader_01"],
                           auth_token=env.tokens["school_uploader_01"])
    elif mutation == "anonymous":
        username = "anonymous"
    elif mutation == "missing_task":
        payload["task_id"] = "missing-task"
    elif mutation == "blank_task":
        payload["task_id"] = " "
    elif mutation == "wrong_course":
        payload["course_id"] = "another-course"
    elif mutation == "blank_course":
        payload["course_id"] = " "
    elif mutation == "admin":
        username = "company_admin"
    else:
        with env.store._connect() as db:
            if mutation == "legacy_empty_school":
                db.execute("UPDATE video_analysis_tasks SET school_context_json='{}' WHERE task_id=?", (task["task_id"],))
            elif mutation == "legacy_unowned_task":
                db.execute("UPDATE video_analysis_tasks SET account_id=NULL WHERE task_id=?", (task["task_id"],))
            elif mutation == "unbound_channel":
                db.execute("UPDATE platform_accounts SET bound_channel_id=NULL WHERE account_id=?", (env.owner,))
            elif mutation == "rebound_channel":
                # Avoid the unique channel binding held by uploader 2.
                db.execute("UPDATE platform_accounts SET bound_channel_id=NULL WHERE bound_channel_id='channel_2'")
                db.execute("UPDATE platform_accounts SET bound_channel_id='channel_2' WHERE account_id=?", (env.owner,))
            elif mutation == "changed_school":
                db.execute("UPDATE school_contexts SET school_name='Another School' WHERE account_id=?", (env.owner,))
            elif mutation == "disabled":
                db.execute("UPDATE platform_accounts SET status='disabled' WHERE account_id=?", (env.owner,))
            elif mutation == "revoked":
                db.execute("UPDATE account_sessions SET revoked_at=? WHERE account_id=?", (env.modules.store._iso(), env.owner))
            elif mutation == "expired_session":
                db.execute("UPDATE account_sessions SET expires_at=? WHERE account_id=?", (env.modules.store._iso(), env.owner))
            elif mutation == "cancelled":
                db.execute("UPDATE video_analysis_tasks SET upload_status='cancelled' WHERE task_id=?", (task["task_id"],))
            elif mutation == "expired_media":
                db.execute("UPDATE video_analysis_tasks SET expires_at=? WHERE task_id=?", (env.modules.store._iso(), task["task_id"]))
            elif mutation == "paused_channel":
                db.execute("UPDATE video_upload_channels SET status='paused' WHERE channel_id='channel_1'")
    return username


@pytest.mark.parametrize("binary", [False, True], ids=["json", "binary"])
@pytest.mark.parametrize("mutation,expected", PERMISSION_CASES)
def test_chunk_permissions_match_source_without_loading_workspace(
    make_env, cloud, source_reference, monkeypatch, mutation, expected, binary,
):
    for name, modules in (("source", source_reference), ("cloud", cloud)):
        current = make_env(modules, name)
        task = _create(current)
        payload = {"task_id": task["task_id"], "course_id": task["course_id"], "chunk_index": 0,
                   "content_base64": base64.b64encode(b"end").decode()}
        username = _mutate_permission(current, task, mutation, payload)
        before = _raw(current, task)
        part = Path(before["file_path"] + ".part")
        calls = []
        workspace = current.store.account_upload_workspace

        def tracked_workspace(*args):
            calls.append(args)
            assert name == "source", "Cloud chunks must not load course/student/task workspaces"
            return workspace(*args)
        monkeypatch.setattr(current.store, "account_upload_workspace", tracked_workspace)
        status, result = _post(current, payload, binary=binary, username=username)
        # The old workspace gate used a generic 400 for missing channel binding.
        source_expected = 400 if name == "source" and mutation == "unbound_channel" else expected
        assert status == source_expected, (name, mutation, result)
        if expected == 200:
            assert result["task"]["received_bytes"] == 3
            assert Path(before["file_path"]).read_bytes() == b"end"
        else:
            assert _raw(current, task) == before
            assert part.read_bytes() == b""
            if status == 403 and mutation != "admin":
                assert result["error"]["code"] == "task_forbidden"
        if name == "cloud":
            assert calls == []
        elif expected == 200:
            assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["revoked", "disabled", "admin", "rebound_channel", "changed_school"])
def test_changes_after_handler_auth_are_rechecked_before_chunk_write(env, mutation):
    task = _create(env)
    payload = {"task_id": task["task_id"], "course_id": task["course_id"], "chunk_index": 0}

    def change():
        if mutation == "admin":
            with env.store._connect() as db:
                db.execute("UPDATE platform_accounts SET role='company_admin' WHERE account_id=?", (env.owner,))
        else:
            _mutate_permission(env, task, mutation, payload)
    status, _ = _post(env, payload, binary=True, before_read=change)
    assert status in {400, 403}
    assert _raw(env, task)["received_bytes"] == 0
    assert Path(_raw(env, task)["file_path"] + ".part").read_bytes() == b""


@pytest.mark.parametrize("binary", [False, True])
def test_origin_checks_still_run_before_store_writes(env, binary):
    task = _create(env)
    payload = {"task_id": task["task_id"], "course_id": task["course_id"], "chunk_index": 0,
               "content_base64": "ZW5k"}
    status, response = _post(env, payload, binary=binary, origin="https://another.test")
    assert (status, response["error"]["code"]) == (403, "origin_forbidden")
    assert _raw(env, task)["received_bytes"] == 0


def test_replayed_chunks_preserve_bytes_and_enqueue_analysis_once(env):
    chunk_size = env.modules.store.MAX_VIDEO_CHUNK_BYTES
    task = _create(env, byte_size=chunk_size + 3)
    first = _append(env, task, 0, b"a" * chunk_size)
    part = Path(_raw(env, task)["file_path"] + ".part")
    mtime = part.stat().st_mtime_ns
    assert _append(env, task, 0, b"a" * chunk_size) == first
    assert part.stat().st_mtime_ns == mtime
    with pytest.raises(env.modules.store.VideoUploadError) as error:
        _append(env, task, 0, b"b" * chunk_size)
    assert error.value.code == "chunk_replay_mismatch"
    completed = _append(env, task, 1, b"end")
    assert _append(env, task, 1, b"end") == completed
    with env.store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='complete' AND object_id=?", (task["task_id"],)).fetchone()[0] == 1
    assert Path(_raw(env, task)["file_path"]).read_bytes() == b"a" * chunk_size + b"end"


@pytest.mark.parametrize("case", ["canonical", "wrong_name", "wrong_size", "first_hash", "second_hash", "missing_hash"])
def test_resume_filename_normalization_does_not_bypass_size_or_any_prefix_hash(env, case):
    chunk_size = env.modules.store.MAX_VIDEO_CHUNK_BYTES
    original = "lesson|take.mp4"
    task = _create(env, filename=original, byte_size=2 * chunk_size + 3)
    assert task["original_filename"] == "lesson_take.mp4"
    for index, block in enumerate((b"a" * chunk_size, b"b" * chunk_size)):
        _append(env, task, index, block)
    before = _raw(env, task)
    payload = {"task_id": task["task_id"], "course_id": task["course_id"], "byte_size": task["byte_size"],
               "filename": original, "chunk_sha256": [hashlib.sha256(value * chunk_size).hexdigest() for value in (b"a", b"b")]}
    if case == "wrong_name":
        payload["filename"] = "another.mp4"
    elif case == "wrong_size":
        payload["byte_size"] += 1
    elif case in {"first_hash", "second_hash"}:
        payload["chunk_sha256"][0 if case == "first_hash" else 1] = "0" * 64
    elif case == "missing_hash":
        payload["chunk_sha256"].pop()
    if case == "canonical":
        result = env.store.resume_video_upload(env.tokens["school_uploader_01"], payload)
        assert result["next_chunk_index"] == 2
        assert "file_path" not in result and "chunk_sha256" not in result
    else:
        with pytest.raises(env.modules.store.VideoUploadError) as error:
            env.store.resume_video_upload(env.tokens["school_uploader_01"], payload)
        assert error.value.code == ("resume_offset_changed" if case == "missing_hash" else "resume_file_mismatch")
    assert _raw(env, task) == before
    assert Path(before["file_path"] + ".part").read_bytes() == b"a" * chunk_size + b"b" * chunk_size


_JS_ENV = r"""
const assert=require('node:assert/strict');
const {File,Blob}=require('node:buffer');
const crypto=require('node:crypto').webcrypto;
Object.defineProperty(globalThis,'crypto',{value:crypto,configurable:true});
const nodes=new Map(),timers=new Map(),requests=[];let nextTimer=0;
const setTimeout=(fn,delay)=>{timers.set(++nextTimer,{fn,delay});return nextTimer;};
const clearTimeout=id=>timers.delete(id);
class Element {
  constructor(){this.value='';this.files=[];this.style={};this.dataset={};this.options=[];
    this.classList={add(){},remove(){}};this.textContent='';this.innerHTML='';}
  addEventListener(){} setAttribute(){} removeAttribute(){} focus(){} click(){}
  querySelectorAll(){return [];} querySelector(){return new Element();}
}
const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},addEventListener(){}};
const location={origin:'https://cloud.test',search:'',assign(){}};
const window={location,addEventListener(){},confirm(){return true;}};
const sessionStorage={setItem(){}};
const replies=[{context:{city:'Synthetic',district:'Synthetic',school_name:'Synthetic'}},
  {account:{username:'teacher',role:'school_uploader',bound_channel_id:'channel_1'}}];
let fetch=async(url,options)=>{requests.push({url,options});assert.equal(options.credentials,'same-origin');
  const body=replies.shift();assert.ok(body,'Unexpected request: '+url);
  return {status:200,ok:true,json:async()=>body};};
"""


def _run_js(cloud, assertions):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the actual cloud upload JavaScript")
    html = cloud.portal.render_demo2_upload_html()
    script = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    assert script
    source = "(async()=>{\n" + _JS_ENV + "\n" + script + "\nawait new Promise(resolve=>setImmediate(resolve));\n" + assertions
    source += "\n})().catch(error=>{console.error(error);process.exit(1);});"
    result = subprocess.run([node, "-"], input=source, text=True, encoding="utf-8", capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("committed", [False, True], ids=["timeout-before-write", "timeout-after-commit"])
def test_cloud_xhr_timeout_budget_and_reconciliation_never_restart_task(cloud, committed):
    _run_js(cloud, "const committed=" + json.dumps(committed) + r""";
    assert.equal(UPLOAD_REQUEST_TIMEOUT_MS,330000);
    assert.ok(UPLOAD_REQUEST_TIMEOUT_MS>(10+180+120)*1000);
    workspace={course_id:'course-1',remaining_slots:0,used_slots:5,tasks:[]};
    byId('courseId').value='course-1';
    const file=new File(['end'],'synthetic.mp4');
    const s={file,courseId:'course-1',taskId:'task-1',next:0,sentThrough:0,total:1,acknowledged:0,paused:false,running:false,completed:false};
    uploadSession=s;setUploadBusy(true);let sends=0,serverNext=0;
    const serverTask=()=>({task_id:s.taskId,course_id:s.courseId,byte_size:file.size,next_chunk_index:serverNext,
      received_bytes:serverNext?file.size:0,upload_status:serverNext?'completed':'uploading'});
    class XMLHttpRequest {
      constructor(){this.upload={};} open(method,url){assert.equal(method,'POST');this.url=url;}
      setRequestHeader(key,value){assert.equal(value,'application/octet-stream');}
      send(chunk){assert.equal(this.timeout,330000);assert.equal(this.withCredentials,true);assert.equal(chunk.size,3);
        sends++;if(sends===1){if(committed)serverNext=1;this.ontimeout();}
        else{serverNext=1;this.status=200;this.responseText=JSON.stringify({task:serverTask()});this.onload();}
        this.onloadend();}
    }
    api=async url=>{assert.ok(url.startsWith(API_ROUTES.task+'?id='));return {task:serverTask()};};
    retryDelay=async()=>{};loadWorkspace=async()=>{};scheduleTaskPoll=()=>{};
    await runUpload(s);
    assert.equal(s.completed,true);assert.equal(s.acknowledged,3);assert.equal(uploadSession,null);
    assert.equal(sends,committed?1:2);assert.equal(workspace.used_slots,5);assert.equal(workspace.remaining_slots,0);
    """)


def test_cloud_resume_timeout_aborts_and_clears_timer(cloud):
    _run_js(cloud, r"""
    timers.clear();assert.equal(RESUME_REQUEST_TIMEOUT_MS,180000);
    assert.ok(RESUME_REQUEST_TIMEOUT_MS>(30+10+120)*1000);
    fetch=async(url,options)=>new Promise((resolve,reject)=>{
      assert.equal(url,API_ROUTES.resume);
      options.signal.addEventListener('abort',()=>{const e=new Error('aborted');e.name='AbortError';reject(e);});
    });
    const pending=api(API_ROUTES.resume,{method:'POST',timeoutMs:RESUME_REQUEST_TIMEOUT_MS});
    assert.equal(timers.size,1);const timer=[...timers.values()][0];assert.equal(timer.delay,180000);
    timer.fn();await assert.rejects(pending);assert.equal(timers.size,0);
    """)


@pytest.mark.parametrize("case", ["canonical", "server_rejects", "wrong_size", "wrong_course", "changed_offset"])
def test_cloud_frontend_sends_original_name_and_all_hashes_before_resuming(cloud, case):
    _run_js(cloud, "const scenario=" + json.dumps(case) + r""";
    workspace={course_id:'course-1',remaining_slots:0,used_slots:5,tasks:[]};
    byId('courseId').value='course-1';scheduleTaskPoll=()=>{};
    const file=new File([new Uint8Array(2*CHUNK_SIZE+3)],'lesson|take.mp4');
    const task={task_id:'task-1',course_id:'course-1',filename:'lesson_take.mp4',original_filename:'lesson_take.mp4',
      byte_size:file.size,next_chunk_index:2,received_bytes:2*CHUNK_SIZE,upload_status:'uploading'};
    if(scenario==='wrong_size')task.byte_size++;
    if(scenario==='wrong_course')task.course_id='another-course';
    resumeTaskId=task.task_id;byId('resumeVideoFile').files=[file];
    let verified=false,resumed=false;
    api=async(url,options)=>{
      if(url.startsWith(API_ROUTES.task+'?id='))return {task};
      assert.equal(url,API_ROUTES.resume);assert.equal(options.method,'POST');assert.equal(options.timeoutMs,180000);
      const body=JSON.parse(options.body);assert.equal(body.filename,file.name);assert.equal(body.byte_size,file.size);
      assert.equal(body.course_id,'course-1');assert.equal(body.task_id,task.task_id);
      const digest=require('node:crypto').createHash('sha256').update(new Uint8Array(CHUNK_SIZE)).digest('hex');
      assert.deepEqual(body.chunk_sha256,[digest,digest]);verified=true;
      if(scenario==='server_rejects'){const e=new Error('resume_file_mismatch');e.status=409;throw e;}
      return {task:scenario==='changed_offset'?{...task,next_chunk_index:3,received_bytes:file.size}:task};
    };
    runUpload=async s=>{assert.equal(verified,true);assert.equal(s.file,file);assert.equal(s.next,2);resumed=true;};
    await resumeSelectedFile();assert.equal(resumed,scenario==='canonical');
    assert.equal(verified,!['wrong_size','wrong_course'].includes(scenario));
    assert.equal(workspace.used_slots,5);assert.equal(workspace.remaining_slots,0);
    if(scenario!=='canonical'){assert.equal(uploadSession,null);assert.equal(uploadInProgress,false);}
    """)
