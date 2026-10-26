"""Local synthetic end-to-end acceptance for the Demo2 1-10 integration.

Runs one complete classroom flow over loopback HTTP against an isolated,
temporary server (temporary SQLite database, temporary upload directory,
temporary Fernet dossier key, random account password prefix)::

    登录 -> 上传 -> 后台处理 -> 学生状态 -> 学校评分/系统评分 -> 分差说明
      -> 报告生成 -> 报告下载 -> 公司后台查询 -> 视频/报告下载

Only FFmpeg-generated test patterns and fictional students are used. Passing
this script proves the software path and the stable-ID joins; it does not
validate educational accuracy of any state or score.

Every step is written as a timestamped JSON line. Logs contain IDs, HTTP
statuses and counts only: never passwords, session cookies, Fernet keys or
dossier summary text.

Usage (from the repository root)::

    PYTHONPATH=src .venv/bin/python scripts/local_synthetic_e2e_20261026.py --port 9185
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import importlib.util
import json
import math
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

ALLOWED_PORTS = range(9180, 9200)
# Marker inside synthetic dossier text: must never appear in an admin export.
SYNTHETIC_IEP_MARKER = "SYNTHETIC-IEP-" + secrets.token_hex(4)
STEPS = (
    ("login", "登录（学校上传账号 + 公司管理员）"),
    ("upload", "上传合成视频（分片上传 + SHA256 校验）"),
    ("processing", "后台处理（真实 FFmpeg + 分析 worker）"),
    ("student_state", "学生状态结果（任务范围内）"),
    ("school_system_scoring", "学校评分 / 系统评分"),
    ("score_gap", "分差说明"),
    ("report_generation", "报告生成（课程报告快照）"),
    ("report_download", "教师报告下载（md/json）"),
    ("admin_query", "公司后台查询（任务 + 报告）"),
    ("admin_downloads", "公司后台视频 / 报告下载"),
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_local_e2e_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloud_e2e = _load("cloud_e2e_acceptance")
API = cloud_e2e.API
route = cloud_e2e.route


class StepFailed(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


def check(condition: Any, step: str, message: str) -> None:
    if not condition:
        raise StepFailed(step, message)


class JsonLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, step: str, result: str, **fields: Any) -> dict[str, Any]:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                 "group": "synthetic_e2e", "step": step, "result": result, **fields}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"[{entry['ts']}] synthetic_e2e {step} -> {result}"
              + (" | " + json.dumps(fields, ensure_ascii=False, sort_keys=True) if fields else ""), flush=True)
        return entry


class Client(cloud_e2e.Client):
    """Loopback client with a page helper for non-API safety checks."""

    def call(self, path: str, step: str, *, payload: Any = None) -> dict[str, Any]:
        status, _, body = self.request(path, payload=payload)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            data = {}
        if status != 200 or not isinstance(data, dict) or data.get("ok") is False:
            error = data.get("error") if isinstance(data, dict) else None
            code = (error or {}).get("code") if isinstance(error, dict) else data.get("code") if isinstance(data, dict) else None
            raise StepFailed(step, f"{path.split('?')[0]} HTTP {status} code={code}")
        return data

    def page(self, path: str) -> tuple[int, str]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request("GET", path, headers={"Cookie": self.cookie, "Accept": "text/html"})
            response = connection.getresponse()
            return response.status, response.read(2 * 1024 * 1024).decode("utf-8", "replace")
        finally:
            connection.close()


@contextmanager
def isolated_server(directory: Path, port: int):
    """Temporary DB/uploads/key; never touches outputs/ or .runtime databases."""
    from cryptography.fernet import Fernet
    from rehab_affect import scenario_lab_server as server
    from rehab_affect.demo2_media_worker import VideoAnalysisWorker
    from rehab_affect.student_record_store import Demo2StudentRecordStore

    saved_env = {name: os.environ.get(name) for name in
                 ("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "REHAB_DEMO2_DOSSIER_KEY")}
    prefix = secrets.token_urlsafe(24) + "-"
    os.environ["REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX"] = prefix
    os.environ["REHAB_DEMO2_DOSSIER_KEY"] = Fernet.generate_key().decode("ascii")
    original = server.get_demo2_student_store
    httpd = worker = thread = None
    try:
        records = Demo2StudentRecordStore(directory / "isolated.sqlite3", directory / "uploads")
        school = {"username": "school_uploader_01", "password": prefix + "school_uploader_01"}
        admin = {"username": "company_admin", "password": prefix + "company_admin"}
        server.get_demo2_student_store = lambda: records
        handler = server.create_handler(scenario_dir=directory, model_path=directory / "unused", policy_name="rule")
        handler.log_message = lambda *args, **kwargs: None
        httpd = server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        worker = VideoAnalysisWorker(records, poll_seconds=0.2)
        worker.start()
        yield f"http://127.0.0.1:{port}", school, admin, records
    finally:
        if worker is not None:
            worker.stop()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(5)
        server.get_demo2_student_store = original
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def generate_video(directory: Path, ffmpeg: str) -> bytes:
    """Synthetic test pattern + sine tone; no people, no real classroom."""
    path = directory / "synthetic_lesson.mp4"
    command = [ffmpeg, "-v", "error", "-nostdin", "-n",
               "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=4",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "64k",
               "-map_metadata", "-1", "-movflags", "+faststart", str(path)]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, timeout=60, check=False)
    if result.returncode != 0:
        raise StepFailed("upload", "合成视频生成失败: " + result.stderr.decode("utf-8", "replace")[-300:])
    return path.read_bytes()


def run(port: int, log: JsonLog, ffmpeg: str, worker_timeout: int = 300) -> dict[str, Any]:
    outcome: dict[str, Any] = {"steps": {}, "ids": {}, "checks": {}, "ok": False}
    ids = outcome["ids"]

    def passed(step: str, **fields: Any) -> None:
        outcome["steps"][step] = {"result": "PASS", **fields}
        log.event(step, "PASS", **fields)

    with tempfile.TemporaryDirectory(prefix="rehab-local-e2e-") as temporary:
        directory = Path(temporary)
        blob = generate_video(directory, ffmpeg)
        outcome["checks"]["video"] = {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                                      "source": "ffmpeg lavfi testsrc2 320x240 10fps 4s + sine 440Hz"}
        log.event("generate_video", "PASS", **outcome["checks"]["video"])
        with isolated_server(directory, port) as (base_url, school_credentials, admin_credentials, records):
            teacher, admin, anonymous = Client(base_url), Client(base_url), Client(base_url)
            current = "login"
            try:
                # 1. login
                teacher_account = teacher.login(school_credentials, "school_uploader")
                admin_account = admin.login(admin_credentials, "company_admin")
                check(teacher_account["role"] == "school_uploader" and admin_account["role"] == "company_admin",
                      current, "角色不匹配")
                teacher.call(route("/school/context"), current, payload={
                    "city": "合成市", "district": "合成区", "school_name": "合成验收学校"})
                context = teacher.call(route("/school/context"), current)["context"]
                check(context.get("school_name") == "合成验收学校", current, "学校信息未保存")
                check(anonymous.request(route("/admin/summary"))[0] == 401, current, "匿名访问后台未被拒绝")
                check(teacher.request(route("/admin/summary"))[0] == 403, current, "学校账号访问后台未被拒绝")
                passed(current, school_account_id=teacher_account["account_id"],
                       admin_account_id=admin_account["account_id"],
                       bound_channel_id=teacher_account.get("bound_channel_id"))

                # 2. upload
                current = "upload"
                course_id = "synthetic-course-20261026"
                workspace = teacher.call(route("/upload/workspace", course_id=course_id), current)["workspace"]
                channel_id = workspace["channel"]["channel_id"]
                check(channel_id == teacher_account["bound_channel_id"], current, "上传通道不是账号绑定通道")
                task = teacher.call(route("/upload/tasks"), current, payload={
                    "channel_id": channel_id, "course_id": course_id, "course_name": "合成数学课（验收）",
                    "session_id": "synthetic-session-" + secrets.token_hex(4), "uploader_name": "合成验收教师",
                    "filename": "synthetic_lesson.mp4", "mime_type": "video/mp4", "byte_size": len(blob),
                    "total_chunks": math.ceil(len(blob) / cloud_e2e.CHUNK_SIZE), "security_confirmed": True,
                    "allow_company_archive": False})["task"]
                task_id = task["task_id"]
                ids.update(course_id=task["course_id"], video_task_id=task_id)
                try:
                    cloud_e2e.upload(teacher, task, blob)
                except cloud_e2e.AcceptanceError as exc:
                    raise StepFailed(current, exc.code) from None
                passed(current, video_task_id=task_id, course_id=course_id, channel_id=channel_id, bytes=len(blob))

                # 3. background processing
                current = "processing"
                deadline = time.monotonic() + worker_timeout
                started = time.monotonic()
                while True:
                    state = teacher.call(route("/upload/task", id=task_id), current)["task"]
                    check(state["analysis_status"] not in {"failed", "cancelled"}, current,
                          f"analysis_status={state['analysis_status']}")
                    if state["analysis_status"] in {"evidence_ready", "completed"}:
                        break
                    check(time.monotonic() < deadline, current, "后台处理超时")
                    time.sleep(0.5)
                passed(current, analysis_status=state["analysis_status"],
                       seconds=round(time.monotonic() - started, 1))

                # 4. student state (task-scoped)
                current = "student_state"
                simple = teacher.call(route("/simple-result", task_id=task_id), current)
                check(simple.get("task", {}).get("task_id") == task_id, current, "学生状态结果不属于本任务")
                analysis = simple.get("analysis") or {}
                status, html = teacher.page("/demo2/simple-result?task_id=" + task_id)
                check(status == 200, current, f"学生状态页 HTTP {status}")
                identity = teacher.call(route("/identity/workspace", task_id=task_id), current)["workspace"]
                check(identity.get("frames"), current, "没有可用于核对的分析画面")
                student = teacher.call(route("/identity/students"), current, payload={
                    "display_name": "虚构学生甲", "student_code": "SYN-001", "class_name": "合成班"})["student"]
                ids["student_id"] = student["student_id"]
                frame = identity["frames"][0]
                binding = teacher.call(route("/identity/bindings"), current, payload={
                    "task_id": task_id, "frame_key": frame["frame_key"], "frame_revision": identity["frame_revision"],
                    "role": "student", "student_id": student["student_id"],
                    "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}})["binding"]
                applicability = teacher.call(route("/applicability", task_id=task_id), current)["result"]
                teacher.call(route("/applicability"), current, payload={
                    "task_id": task_id, "version": applicability["version"], "revision": applicability["revision"],
                    "category": "special", "goal": "合成课堂分类目标（验收用）", "reason": "合成视频工程验收", "confirmed": True})
                measurement = teacher.call(route("/measurements"), current, payload={
                    "record_id": "synthetic-measurement-1", "expected_version": 0, "student_id": student["student_id"],
                    "lesson_date": date.today().isoformat(), "lesson_id": "synthetic-lesson-1", "course_name": "合成数学课（验收）",
                    "goal_id": "synthetic-goal-1", "measurement_context": "独立完成", "criterion": "三次机会中至少两次独立完成",
                    "scores": {"accuracy": 8, "independence": 7, "consistency": 6, "transfer": 5},
                    "opportunities": 3, "observed": 2, "reviewed": True, "evidence": "合成观察证据",
                    "source_type": "video_review", "task_id": task_id, "start_sec": 0, "end_sec": 1,
                    "support_level": "visual", "observed_state": "participating",
                    "teacher_prompt": "分类", "student_response": "指认"})["record"]
                passed(current, simple_analysis_available=bool(analysis.get("available")),
                       simple_analysis_reason=analysis.get("reason") or analysis.get("refresh_status"),
                       student_id=student["student_id"], binding_id=binding.get("binding_id"),
                       frame_revision=identity["frame_revision"], frames=len(identity["frames"]),
                       measurement_record_id=measurement.get("record_id"),
                       measurement_overall_score=(measurement.get("assessment") or {}).get("overall_score"))

                # IEP dossier (synthetic text only) linked by stable IDs.
                authorization = teacher.call(API + "/dossier/authorization", current, payload={
                    "student_id": student["student_id"], "reference": "合成授权依据（验收）",
                    "storage_mode": "original_and_summary",
                    "valid_until": (date.today() + timedelta(days=30)).isoformat(), "confirmed": True})["authorization"]
                document = teacher.call(API + "/dossier/documents", current, payload={
                    "student_id": student["student_id"], "authorization_id": authorization["authorization_id"],
                    "document_type": "iep", "document_date": (date.today() - timedelta(days=1)).isoformat(),
                    "source_ref": "合成来源", "retain_until": (date.today() + timedelta(days=20)).isoformat(),
                    "summary": {key: f"{SYNTHETIC_IEP_MARKER}-{key}" for key in
                                ("learning_goals", "support_methods", "safety_notes", "professional_conclusion")},
                    "filename": "synthetic_iep.txt",
                    "content_base64": base64.b64encode(b"synthetic iep original").decode("ascii"),
                    "supersedes_id": ""})["document"]
                ids["iep_document_id"] = document["document_id"]
                reference = teacher.call(API + "/dossier/references", current, payload={
                    "task_id": task_id, "student_id": student["student_id"],
                    "frame_revision": identity["frame_revision"],
                    "document_ids": [document["document_id"]], "confirmed": True})["reference"]
                log.event("iep_link", "PASS", authorization_id=authorization["authorization_id"],
                          iep_document_id=document["document_id"], reference_id=reference["reference_id"])

                # 5. school score / system score
                current = "school_system_scoring"
                items = [{"id": f"i{index}", "school_score": 8, "enhanced_score": 7 if index % 2 else 8,
                          "evidence": "合成课堂观察\n00:01 提供回应机会", "reason": "补充证据后复核调整",
                          "suggestion": "下一课安排独立回应机会"} for index in range(1, 11)]
                evaluation_payload = {
                    "record_id": "synthetic-evaluation-1", "expected_version": 0, "lesson_id": "synthetic-lesson-1",
                    "lesson_date": date.today().isoformat(), "course_name": "合成数学课（验收）", "subject_id": "math",
                    "template_id": "basic_100", "goal_context": "在约定支持下完成三次实物分类；仅合成记录",
                    "school_source": "teacher_recorded", "school_rater": "合成评课人", "reviewed": True,
                    "items": items, "task_id": task_id, "frame_revision": identity["frame_revision"],
                    "iep_summary_id": document["document_id"]}
                preview = teacher.call(route("/evaluations/preview"), current, payload=evaluation_payload)["result"]
                record = teacher.call(route("/evaluations"), current, payload=evaluation_payload)["record"]
                ids["evaluation_id"] = record.get("evaluation_id") or record.get("record_id")
                result = record["result"]
                check(result == preview, current, "保存结果与预览不一致")
                check(result["school"].get("raw_score") is not None and result["enhanced"].get("score_10") is not None,
                      current, "学校评分或系统评分缺失")
                passed(current, evaluation_id=ids["evaluation_id"], version=record.get("version"),
                       school_raw_score=result["school"].get("raw_score"),
                       school_teaching_score_70=result["school"].get("teaching_score_70"),
                       system_score_10=result["enhanced"].get("score_10"))

                # 6. score gap explanation
                current = "score_gap"
                comparison = result.get("comparison") or {}
                check(comparison.get("available") is not False and "total_delta" in comparison, current, "无分差说明")
                status, html = teacher.page("/demo2/evaluation")
                check(status == 200 and "分差不表示系统比教师更准确" in html, current, "评分页缺少分差说明文本")
                passed(current, total_delta=comparison.get("total_delta"), evidence_delta=comparison.get("evidence_delta"),
                       weight_delta=comparison.get("weight_delta"))

                # 7. report generation
                current = "report_generation"
                course = teacher.call(route("/course-analysis", task_id=task_id), current)
                saved = course.get("report_saved") or {}
                check(saved.get("report_id") and saved.get("status") == "saved" and saved.get("ready"), current,
                      f"报告快照未保存 code={saved.get('code')}")
                ids["report_id"] = saved["report_id"]
                ids["content_report_id"] = saved.get("content_report_id")
                person = next((item for item in course["workspace"].get("people", [])
                               if item.get("student_id") == student["student_id"]), {})
                check((person.get("identifiers") or {}).get("iep_summary_id") == document["document_id"],
                      current, "课程报告未按 iep_document_id 关联学生")
                passed(current, report_id=saved["report_id"], content_report_id=saved.get("content_report_id"),
                       evaluation_count=saved.get("evaluation_count"))

                # 8. teacher report download
                current = "report_download"
                listed = teacher.call(route("/reports", task_id=task_id), current)
                check(any(item.get("report_id") == ids["report_id"] for item in listed.get("reports", [])),
                      current, "教师报告列表缺少本报告")
                downloads = {}
                for fmt in ("md", "json"):
                    status, headers, body = teacher.request(route("/reports/download", report_id=ids["report_id"], fmt=fmt))
                    check(status == 200 and "attachment" in headers.get("content-disposition", ""), current,
                          f"{fmt} 下载 HTTP {status}")
                    check(SYNTHETIC_IEP_MARKER.encode() not in body, current, "报告下载含 IEP 原文")
                    downloads[fmt] = len(body)
                teacher_view = teacher.call(route("/reports", report_id=ids["report_id"]), current)["report"]
                status, headers, raw = teacher.request(route("/course-analysis/report", task_id=task_id))
                check(status == 200, current, f"课程报告 JSON 下载 HTTP {status}")
                passed(current, md_bytes=downloads["md"], json_bytes=downloads["json"],
                       teacher_iep_links=len((teacher_view.get("payload") or {}).get("report", {}).get("iep_links") or []))

                # 9. company admin query
                current = "admin_query"
                found = admin.call(route("/admin/tasks", q=task_id), current)
                match = next((item for item in found.get("tasks", []) if item.get("task_id") == task_id), None)
                check(match is not None, current, "后台任务查询未找到本任务")
                check(any(item.get("report_id") == ids["report_id"] for item in match.get("reports", [])),
                      current, "后台任务查询未关联本报告")
                admin_reports = admin.call(route("/admin/reports"), current)
                check(any(item.get("report_id") == ids["report_id"] for item in admin_reports.get("reports", [])),
                      current, "后台报告列表缺少本报告")
                summary = admin.call(route("/admin/summary"), current)["summary"]
                status, html = admin.page("/demo2/analysis")
                check(status == 200 and "请从任务记录进入" in html, current, f"无 task_id 安全引导页 HTTP {status}")
                check(task_id not in html, current, "无 task_id 安全引导页读取了课堂数据")
                passed(current, admin_task_status=match.get("analysis_status"),
                       admin_report_rows=len(admin_reports.get("reports", [])),
                       recent_uploads=len(summary.get("recent_uploads", [])),
                       analysis_without_task_id_status=status)

                # 10. company admin video/report downloads
                current = "admin_downloads"
                admin_report = admin.call(route("/reports", report_id=ids["report_id"]), current)["report"]
                check("iep_links" not in (admin_report.get("payload") or {}).get("report", {}), current,
                      "管理员报告视图未移除 iep_links")
                admin_sizes = {}
                for fmt in ("md", "json"):
                    status, headers, body = admin.request(route("/reports/download", report_id=ids["report_id"], fmt=fmt))
                    check(status == 200, current, f"管理员 {fmt} 报告下载 HTTP {status}")
                    check(SYNTHETIC_IEP_MARKER.encode() not in body, current, "管理员报告下载含 IEP 原文")
                    if fmt == "json":
                        check("iep_links" not in json.loads(body).get("report", {}), current, "管理员 JSON 报告含 iep_links")
                    admin_sizes[fmt] = len(body)
                status, _, source = admin.request(route("/upload/media", id=task_id, asset="source"))
                check(status == 200 and source == blob, current, f"管理员视频下载 HTTP {status} 或内容不一致")
                status, headers, evidence = admin.request(route("/upload/result", id=task_id))
                check(status == 200 and "attachment" in headers.get("content-disposition", ""), current,
                      f"管理员分析结果下载 HTTP {status}")
                check(json.loads(evidence).get("task_id") == task_id, current, "分析结果不属于本任务")
                passed(current, report_md_bytes=admin_sizes["md"], report_json_bytes=admin_sizes["json"],
                       video_bytes=len(source), video_sha256_match=True, result_bytes=len(evidence))

                outcome["ok"] = True
            except StepFailed as exc:
                outcome["steps"][exc.step] = {"result": "FAIL", "message": exc.message}
                log.event(exc.step, "FAIL", message=exc.message)
            except cloud_e2e.AcceptanceError as exc:
                outcome["steps"][current] = {"result": "FAIL", "message": exc.code}
                log.event(current, "FAIL", message=exc.code)
            finally:
                for client in (teacher, admin):
                    if client.cookie:
                        try:
                            client.request(route("/auth/logout"), payload={})
                        except Exception:
                            pass
            db_path = records.db_path
            if ids.get("report_id"):
                outcome["id_chain"] = verify_chain(db_path, ids["report_id"], log)
                with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
                    raw = "\n".join(row[0] for row in db.execute("SELECT payload_json FROM demo2_reports"))
                outcome["checks"]["report_snapshot_without_iep_text"] = SYNTHETIC_IEP_MARKER not in raw
    for step, _ in STEPS:
        outcome["steps"].setdefault(step, {"result": "NOT_RUN"})
    return outcome


def verify_chain(db_path: Path, report_id: str, log: JsonLog) -> dict[str, Any]:
    """Independent read-only trace with scripts/verify_id_chain.py."""
    command = [sys.executable, str(SCRIPTS / "verify_id_chain.py"), "--db", str(db_path),
               "--report-id", report_id, "--json", "--require-iep", "--quiet", "--log-file", str(log.path.with_suffix(".idchain.jsonl"))]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, env=env, check=False)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = {"raw_stdout": result.stdout[-2000:], "raw_stderr": result.stderr[-2000:]}
    log.event("id_chain", "PASS" if result.returncode == 0 else "FAIL", exit_code=result.returncode)
    return {"exit_code": result.returncode, "result": data, "command": " ".join(
        ["PYTHONPATH=src", ".venv/bin/python", "scripts/verify_id_chain.py", "--db", "<临时库>",
         "--report-id", report_id, "--json", "--require-iep"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9185)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "")
    parser.add_argument("--log", type=Path,
                        default=ROOT.parent / ".runtime" / "logs" / f"local_e2e_{datetime.now():%Y%m%d_%H%M%S}.jsonl")
    parser.add_argument("--output", type=Path, help="write the outcome JSON here")
    parser.add_argument("--worker-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.port not in ALLOWED_PORTS:
        parser.error("port must be within 9180-9199")
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        import imageio_ffmpeg
        args.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    outcome = run(args.port, JsonLog(args.log), args.ffmpeg, args.worker_timeout)
    outcome["log"] = str(args.log)
    outcome["ffmpeg"] = args.ffmpeg
    text = json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
