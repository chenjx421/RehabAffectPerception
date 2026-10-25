"""Private, isolated real-material acceptance. No public service or original is modified."""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import logging
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".runtime" / "real_material_test_20261016"
SOURCE = Path.home() / "Desktop" / "3\u540d\u4e0d\u540c\u969c\u788d\u7c7b\u578b\u5b66\u751f\u57fa\u7840\u6570\u636e"
CHUNK = 4 * 1024 * 1024
API = "/api/v1/demo2"


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def digest(file):
    result = hashlib.sha256()
    with file.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            result.update(block)
    return result.hexdigest()


def restrict(directory):
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
        return "owner_only_mode_0700"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
        "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    sid = result.stdout.strip()
    require(result.returncode == 0 and sid.startswith("S-1-"), "acl_identity_unavailable")
    result = subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r",
        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
        capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    require(result.returncode == 0, "private_acl_failed")
    return "inheritance_removed_current_user_system_administrators_only"


def document_counts(file, alias):
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(file) as archive:
        require(archive.testzip() is None, "docx_zip_integrity_failed")
        require(archive.getinfo("word/document.xml").file_size < 32 * 1024 * 1024, "docx_xml_limit")
        xml = archive.read("word/document.xml")
        require(b"<!DOCTYPE" not in xml and b"<!ENTITY" not in xml, "docx_external_entities_rejected")
        document = ET.fromstring(xml)
        texts = document.findall(".//w:t", namespaces)
        return {"alias": alias, "zip_valid": True, "xml_valid": True,
            "paragraphs": len(document.findall(".//w:p", namespaces)),
            "tables": len(document.findall(".//w:tbl", namespaces)),
            "text_nodes": len(texts), "characters": sum(len(node.text or "") for node in texts),
            "embedded_images": sum(name.startswith("word/media/") for name in archive.namelist()),
            "content_retained": False}


def aggregate_progress(report):
    videos = report.get("videos", [])
    return {
        "started_at": report["started_at"], "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "finished_at": report.get("finished_at"), "phase": report.get("phase", "preflight"),
        "passed": report["passed"], "elapsed_seconds": report.get("elapsed_seconds"),
        "total_videos": report["source_video_count"], "total_video_bytes": report["source_video_bytes"],
        "uploaded_videos": sum(bool(item.get("http_upload_complete")) for item in videos),
        "ready_videos": sum(item.get("processing", {}).get("analysis_status") in {"evidence_ready", "completed"} for item in videos),
        "parsed_documents": len(report.get("documents", [])),
        "total_duration_seconds": sum(item.get("duration_sec", 0) for item in videos),
        "total_decoded_frames": sum(item.get("decoded_frames", 0) for item in videos),
        "total_sampled_frames": sum(item.get("sampled_frames", 0) for item in videos),
        "browser_playbacks_passed": sum(bool(item.get("time_advanced")) for item in report.get("browser", {}).get("checks", [])),
        "resources": report.get("resources", {}), "failure": report.get("failure"),
        "videos": [{key: item.get(key) for key in ("alias", "bytes", "duration_sec", "processing")} for item in videos],
        "identities_or_document_text_included": False,
    }


def process_peak_memory():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        function = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if function(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return None
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


BROWSER_JS = r"""
const fs=require('node:fs');
const {chromium}=require('playwright');
const config=JSON.parse(fs.readFileSync(0,'utf8'));
const base=new URL(config.base);let browser;
const report={checks:[],external_requests_blocked:0,page_errors:0,passed:false};
const check=(value,code)=>{if(!value){const e=new Error(code);e.safeCode=code;throw e;}};
(async()=>{try{
 check(base.hostname==='127.0.0.1'&&base.protocol==='http:','loopback_required');
 browser=await chromium.launch({channel:'msedge',headless:true,args:[
  '--disable-background-networking','--disable-component-update','--disable-sync',
  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
  '--proxy-server=http://127.0.0.1:9','--proxy-bypass-list=127.0.0.1;localhost']});
 for(const account of [...config.accounts,config.admin]){
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:true});
  await context.route('**/*',route=>{
   const u=new URL(route.request().url());
   if(u.origin===base.origin||['data:','blob:'].includes(u.protocol))return route.continue();
   report.external_requests_blocked++;return route.abort('blockedbyclient');
  });
  const page=await context.newPage();page.setDefaultTimeout(60000);
  page.on('pageerror',()=>report.page_errors++);
  await page.goto(base.origin+'/demo2/login');
  if(account.admin)await page.locator('#adminRole').click();
  await page.locator('#username').fill(account.username);await page.locator('#password').fill(account.password);
  await page.locator('#loginButton').click();
  await page.waitForURL(base.origin+(account.admin?'/demo2/admin':'/demo2/school'));
  for(const item of config.tasks.filter(t=>account.admin||t.username===account.username)){
   const response=await page.goto(base.origin+'/demo2/video?id='+item.task_id);
   check(response.status()===200,'video_page_unavailable');
   await page.locator('#downloadResult').waitFor();
   await page.waitForFunction(()=>{const v=document.querySelector('#classVideo');return v&&v.readyState>=2&&v.videoWidth>0;});
   const meta=await page.locator('#classVideo').evaluate(async v=>{
    v.muted=true;v.currentTime=0;await v.play();return {duration:v.duration,width:v.videoWidth,height:v.videoHeight,source:v.currentSrc};
   });
   check(new URL(meta.source).searchParams.get('id')===item.task_id,'wrong_player_source');
   check(Math.abs(meta.duration-item.duration_sec)<1,'wrong_player_duration');
   await page.waitForFunction(()=>{const v=document.querySelector('#classVideo');return v.currentTime>.5&&!v.paused&&!v.error;});
   await page.locator('#classVideo').evaluate(v=>v.pause());
   const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#downloadResult').click()]);
   check(!await download.failure(),'result_download_failed');
   const result=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
   check(result.task_id===item.task_id&&result.source_sha256===item.sha256,'download_result_wrong_source');
   await download.delete();
   report.checks.push({alias:item.alias,admin:!!account.admin,video_ready:true,time_advanced:true,
    duration_sec:meta.duration,width:meta.width,height:meta.height,result_download_matches:true});
  }
  await context.close();
 }
 check(report.external_requests_blocked===0,'unexpected_external_requests');
 check(report.page_errors===0,'browser_javascript_error');report.passed=true;
}catch(e){report.failure=e.safeCode||(e.name==='TimeoutError'?'browser_timeout':'browser_operation_failed');}
finally{if(browser)await browser.close();process.stdout.write(JSON.stringify(report));process.exitCode=report.passed?0:1;}})();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--timeout-minutes", type=int, default=180)
    args = parser.parse_args()
    started_monotonic = time.monotonic()
    source = args.source.resolve(strict=True)
    require(source.is_dir() and not str(source).startswith("\\\\"), "local_source_directory_required")
    videos = sorted(source.rglob("*.mp4"))
    documents = sorted(source.rglob("*.docx"))
    require(len(videos) == 4 and len(documents) == 5, "expected_four_videos_five_documents")
    sources = videos + documents
    require(all(file.resolve().is_relative_to(source) and not file.is_symlink() for file in sources), "source_path_escape")
    originals = {file: (file.stat().st_size, file.stat().st_mtime_ns) for file in sources}
    total = sum(file.stat().st_size for file in videos)
    require(shutil.disk_usage(ROOT).free > total * 3 + 8 * 1024**3, "insufficient_private_disk_space")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    output = PRIVATE / (time.strftime("run_%Y%m%d_%H%M%S_") + secrets.token_hex(4))
    acl = restrict(output)
    report = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "isolated": True, "synthetic": False,
        "source_video_count": len(videos), "source_video_bytes": total, "source_document_count": len(documents),
        "acl": acl, "network_scope": "random_loopback_port_only_no_public_forwarding",
        "scope": "Real full-file upload, technical media processing, persistence, playback and authorization; no learning or diagnostic scores.",
        "dossier_import": "not_attempted_no_confirmed_student_identity_mapping", "documents": [], "videos": [],
        "checks": [], "passed": False}
    report_path = output / "report.json"
    phase = "preflight"
    httpd = worker = None
    server_thread = None
    forbidden_network = []
    source_hashes = {}

    def save():
        report["phase"] = phase
        report["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 2)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        (output / "progress.json").write_text(json.dumps(aggregate_progress(report), indent=2, ensure_ascii=True), encoding="utf-8")

    def checkpoint(name, **evidence):
        report["checks"].append({"name": name, "passed": True, **evidence})
        save()
        print(name, flush=True)

    def network_audit(event, values):
        if event == "socket.connect":
            address = values[1]
            if not (isinstance(address, tuple) and address[0] == "127.0.0.1"
                    and httpd is not None and address[1] == httpd.server_port):
                forbidden_network.append("blocked_non_test_connection")
                raise PermissionError("non_test_network_disabled")

    try:
        save()
        sys.addaudithook(network_audit)
        for index, file in enumerate(documents, 1):
            source_hashes[file] = digest(file)
            report["documents"].append(document_counts(file, f"document_{index:02d}"))
        checkpoint("five_documents_zip_xml_count_only")
        os.environ.update(REHAB_DEMO2_DB_PATH=str(output / "isolated.sqlite3"),
            REHAB_DEMO2_UPLOAD_DIR=str(output / "documents"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        sys.path.insert(0, str(ROOT / "src"))
        import imageio_ffmpeg
        from rehab_affect import scenario_lab_server as server
        from rehab_affect.demo2_media_worker import VideoAnalysisWorker
        from rehab_affect.student_record_store import Demo2StudentRecordStore
        logging.disable(logging.CRITICAL)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe = ROOT / ".tools" / "ffprobe.exe"
        require(Path(ffmpeg).is_file() and ffprobe.is_file(), "local_media_tools_missing")
        os.environ.update(REHAB_FFMPEG=ffmpeg, REHAB_FFPROBE=str(ffprobe))
        store = Demo2StudentRecordStore(output / "isolated.sqlite3", output / "documents")
        require(store.video_task_dir.resolve().is_relative_to(output), "upload_root_not_isolated")
        passwords = {username: secrets.token_urlsafe(24) for username in ["t1", "t2", "t3", "t4", "admin"]}
        store.set_seeded_pilot_passwords(store.db_path, passwords)
        server.get_demo2_student_store = lambda: store
        server.load_seewo_demo2 = lambda force=False: {"students": []}
        base_handler = server.create_handler(scenario_dir=output, model_path=output / "unused.json", policy_name="rule")

        class PrivateHandler(base_handler):
            def log_message(self, *unused):
                pass

            def do_GET(self):
                route = urlsplit(self.path).path
                if not (route.startswith(API + "/") or route in {"/demo2/login", "/demo2/school", "/demo2/admin", "/demo2/video"}):
                    self.send_error(404)
                    return
                super().do_GET()

            def do_POST(self):
                if urlsplit(self.path).path not in {API + "/auth/login", API + "/upload/tasks", API + "/upload/chunks"}:
                    self.send_error(403)
                    return
                super().do_POST()

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), PrivateHandler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}"
        report["isolated_port"] = httpd.server_port

        def request(route, *, cookie="", payload=None, headers=None, stream_hash=False):
            require(route.startswith(API + "/"), "non_api_request_rejected")
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=180)
            try:
                head = {"Content-Type": "application/json", "Origin": base, **(headers or {})}
                if cookie:
                    head["Cookie"] = cookie
                connection.request("POST" if payload is not None else "GET", route,
                    json.dumps(payload).encode() if payload is not None else None, head)
                response = connection.getresponse()
                response_headers = {key.lower(): value for key, value in response.getheaders()}
                if stream_hash:
                    hashed = hashlib.sha256()
                    size = 0
                    for block in iter(lambda: response.read(CHUNK), b""):
                        hashed.update(block)
                        size += len(block)
                    body = {"sha256": hashed.hexdigest(), "bytes": size}
                else:
                    raw = response.read()
                    body = json.loads(raw) if "application/json" in response_headers.get("content-type", "") else raw
                return response.status, response_headers, body
            finally:
                connection.close()

        cookies = {}
        for username, password in passwords.items():
            status, headers, body = request(API + "/auth/login", payload={"username": username, "password": password,
                "role": "company_admin" if username == "admin" else "school_uploader"})
            require(status == 200, "isolated_login_failed")
            cookies[username] = headers["set-cookie"].split(";", 1)[0]
        worker = VideoAnalysisWorker(store, poll_seconds=0.5)
        require(worker.start(), "isolated_worker_start_failed")
        checkpoint("isolated_http_and_current_worker_started")
        course = "private-real-materials-20261016"
        for index, file in enumerate(videos, 1):
            phase = f"video_{index:02d}_upload"
            alias, username = f"video_{index:02d}", f"t{index}"
            size = file.stat().st_size
            source_hashes[file] = digest(file)
            item = {"alias": alias, "username": username, "bytes": size, "sha256": source_hashes[file]}
            report["videos"].append(item)
            status, _, body = request(API + "/upload/tasks", cookie=cookies[username], payload={
                "course_id": course, "course_name": "Private authorized material " + alias,
                "session_id": course, "filename": alias + ".mp4", "uploader_name": "Private local acceptance",
                "byte_size": size, "total_chunks": math.ceil(size / CHUNK), "channel_id": f"channel_{index}",
                "mime_type": "video/mp4", "security_confirmed": True, "allow_company_archive": False})
            require(status == 200, "task_creation_failed")
            item["task_id"] = body["task"]["task_id"]
            with file.open("rb") as handle:
                for chunk_index, block in enumerate(iter(lambda: handle.read(CHUNK), b"")):
                    status, _, body = request(API + "/upload/chunks", cookie=cookies[username], payload={
                        "task_id": item["task_id"], "course_id": course, "chunk_index": chunk_index,
                        "content_base64": base64.b64encode(block).decode("ascii")})
                    require(status == 200 and body["task"]["next_chunk_index"] == chunk_index + 1, "http_chunk_upload_failed")
                    if chunk_index % 25 == 0:
                        item["processing"] = {"analysis_status": "uploading", "processing_stage": "http_chunks",
                            "processing_progress": round((chunk_index + 1) * 100 / math.ceil(size / CHUNK), 1)}
                        save()
                        print(f"{alias}: uploaded {chunk_index + 1}/{math.ceil(size / CHUNK)} chunks", flush=True)
            require(body["task"]["sha256"] == item["sha256"], "uploaded_hash_mismatch")
            item["http_upload_complete"] = True
            checkpoint(alias + "_full_http_upload_hash_verified")

        phase = "full_decode_wait"
        deadline = time.monotonic() + args.timeout_minutes * 60
        while time.monotonic() < deadline:
            terminal = True
            for item in report["videos"]:
                status, _, body = request(API + "/upload/task?id=" + item["task_id"], cookie=cookies[item["username"]])
                require(status == 200, "task_poll_failed")
                task = body["task"]
                current = {key: task.get(key) for key in ("analysis_status", "processing_stage", "processing_progress")}
                if item.get("processing") != current:
                    item["processing"] = current
                    print(item["alias"] + ": " + json.dumps(current), flush=True)
                    save()
                if task["analysis_status"] == "failed":
                    item["worker_error_code"] = task.get("processing_error", {}).get("code", "unknown")
                terminal = terminal and task["analysis_status"] in {"failed", "evidence_ready", "completed"}
            if terminal:
                break
            time.sleep(5)
        else:
            raise RuntimeError("worker_wait_timeout")

        phase = "persistence_and_admin_retrieval"
        for item in report["videos"]:
            require(item["processing"]["analysis_status"] in {"evidence_ready", "completed"}, "real_worker_processing_failed")
            task_id = item["task_id"]
            with sqlite3.connect(store.db_path) as connection:
                row = connection.execute("SELECT sha256,file_path,processing_result_json FROM video_analysis_tasks WHERE task_id=?", (task_id,)).fetchone()
            uploaded = Path(row[1]).resolve()
            require(uploaded.is_relative_to(output) and digest(uploaded) == row[0] == item["sha256"], "persisted_file_hash_mismatch")
            result = json.loads(row[2])
            require(result["task_id"] == task_id and result["source_sha256"] == item["sha256"], "persisted_result_task_mismatch")
            require(result["provenance"]["network_used"] is False and result["provenance"]["models_downloaded"] is False, "worker_network_used")
            item.update(duration_sec=result["media"]["duration_sec"], has_audio=result["media"]["has_audio"],
                decoded_frames=result["summary"]["decoded_frames"], sampled_frames=result["summary"]["sampled_frames"],
                segments=len(result["segments"]), persisted_hash_verified=True, persisted_result_verified=True)
            require(item["decoded_frames"] > 0 and item["sampled_frames"] > 0, "real_decode_evidence_missing")
            item["retrieval"] = []
            for username in (item["username"], "admin"):
                status, _, served = request(API + "/upload/result?id=" + task_id, cookie=cookies[username])
                require(status == 200 and served["task_id"] == task_id and served["source_sha256"] == item["sha256"], "authorized_result_mismatch")
                status, _, served = request(API + "/upload/media?id=" + task_id + "&asset=source", cookie=cookies[username], stream_hash=True)
                require(status == 200 and served["sha256"] == item["sha256"] and served["bytes"] == item["bytes"], "full_media_retrieval_mismatch")
                status, head, audio = request(API + "/upload/media?id=" + task_id + "&asset=audio", cookie=cookies[username], headers={"Range": "bytes=0-127"})
                require((status == 206 and len(audio) > 0) if item["has_audio"] else status == 404, "audio_retrieval_mismatch")
                item["retrieval"].append({"admin": username == "admin", "full_source_sha256_verified": True, "result_verified": True, "audio_status": status})
            for cookie, statuses in (("", {401, 403}), (cookies["t2" if item["username"] == "t1" else "t1"], {403, 404})):
                for route in ("/upload/result?id=", "/upload/media?id=", "/upload/task?id="):
                    status, _, _ = request(API + route + task_id, cookie=cookie, headers={"Range": "bytes=0-127"})
                    require(status in statuses, "unauthorized_material_access")
            checkpoint(item["alias"] + "_persisted_result_admin_full_download_and_denials")

        phase = "real_browser_playback"
        config = {"base": base, "accounts": [{"username": key, "password": passwords[key]} for key in ("t1", "t2", "t3", "t4")],
            "admin": {"username": "admin", "password": passwords["admin"], "admin": True}, "tasks": report["videos"]}
        node_paths = [Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"]
        node_paths += list((Path.home() / "AppData/Local/npm-cache/_npx").glob("*/node_modules"))
        modules = next((directory for directory in node_paths if (directory / "playwright/package.json").is_file()), None)
        require(modules is not None, "local_playwright_missing")
        env = {**os.environ, "NODE_PATH": str(modules), "TEMP": str(output), "TMP": str(output)}
        browser = subprocess.run(["node", "-e", BROWSER_JS], input=json.dumps(config), text=True,
            encoding="utf-8", capture_output=True, timeout=600, env=env, cwd=ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        require(browser.stdout.strip().startswith("{"), "browser_report_missing")
        report["browser"] = json.loads(browser.stdout)
        require(browser.returncode == 0 and report["browser"]["passed"], "browser_acceptance_failed")
        checkpoint("eight_real_browser_playbacks_and_result_downloads")
        phase = "source_integrity"
        require(all((file.stat().st_size, file.stat().st_mtime_ns) == originals[file]
            and digest(file) == source_hashes[file] for file in sources), "original_material_changed")
        require(not forbidden_network, "unexpected_external_network_attempt")
        report["originals_unchanged"] = True
        report["passed"] = True
        phase = "complete"
    except Exception as error:
        # Never retain exception strings, decoder stderr, paths, credentials or medical text.
        code = str(error) if isinstance(error, RuntimeError) and str(error).isascii() and str(error).replace("_", "").isalnum() else type(error).__name__
        report["failure"] = {"phase": phase, "code": code}
        print("Stopped: " + phase + " / " + code, flush=True)
    finally:
        if worker is not None:
            worker.stop(timeout=60)
            if worker.thread and worker.thread.is_alive():
                report["passed"] = False
                report["cleanup_error"] = "worker_not_stopped"
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if server_thread is not None:
            server_thread.join(timeout=10)
        report["server_stopped"] = httpd is not None and server_thread is not None and not server_thread.is_alive()
        report["external_connections_blocked"] = len(forbidden_network)
        report["resources"] = {"python_peak_working_set_bytes": process_peak_memory(),
            "memory_scope": "harness_process_only_excludes_ffmpeg_and_browser",
            "private_artifact_bytes_at_finalize": sum(file.stat().st_size for file in output.rglob("*") if file.is_file())}
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save()
        print(json.dumps({"passed": report["passed"], "report": str(report_path)}, ensure_ascii=True), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Private acceptance preflight failed: " + type(error).__name__, flush=True)
        raise SystemExit(1) from None
