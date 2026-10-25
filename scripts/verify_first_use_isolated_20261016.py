"""Real HTTP/media acceptance on disposable storage, never a live instance.

Run as a fresh process. Names, pixels, teacher observations and applicability
confirmation are synthetic test inputs, not inferred classroom assessments.
"""
from __future__ import annotations

import base64
from datetime import date
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from urllib.parse import urlencode


def main():
    root = Path(tempfile.mkdtemp(prefix="rehab-first-use-SYNTHETIC-20261016-")).resolve()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    os.environ["REHAB_DEMO2_DB_PATH"] = str(root / "database" / "acceptance.sqlite3")
    os.environ["REHAB_DEMO2_UPLOAD_DIR"] = str(root / "uploads")
    os.environ["REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX"] = "SyntheticAcceptance-"
    from rehab_affect import scenario_lab_server as backend
    from rehab_affect.student_record_store import get_demo2_student_store
    from rehab_affect.demo2_identity_store import Demo2IdentityStore
    from rehab_affect.demo2_media_worker import VideoAnalysisWorker
    import cv2
    import numpy as np

    store = get_demo2_student_store()
    for path in (store.db_path, store.upload_dir, store.video_task_dir):
        assert path.resolve().is_relative_to(root), "Refusing non-isolated storage"
    source = root / "SYNTHETIC-geometric-test.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    assert writer.isOpened(), "Synthetic encoder unavailable"
    for frame_index in range(30):
        frame = np.full((360, 640, 3), 225, dtype=np.uint8)
        cv2.putText(frame, "SYNTHETIC TEST - NO REAL STUDENTS", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, .7, (20, 20, 20), 2)
        cv2.rectangle(frame, (100 + frame_index, 90), (270 + frame_index, 290), (30, 150, 70), -1)
        writer.write(frame)
    writer.release()
    media = source.read_bytes()
    identities = Demo2IdentityStore(store)
    handler = backend.create_handler(scenario_dir=root, model_path=root / "unused", policy_name="rule", identity_store=identities)
    httpd = backend.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{httpd.server_port}"
    rows, browser_accounts = [], []
    clients = []

    def call(client, path, payload=None, expected=200):
        request = urllib.request.Request(origin + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Origin": origin})
        try:
            response = client.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            assert response.status == expected, (path, response.status, raw.decode(errors="replace"))
            return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw

    try:
        for number in range(1, 5):
            jar = http.cookiejar.CookieJar()
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
            clients.append(client)
            username = f"school_uploader_{number:02d}"
            call(client, "/api/v1/demo2/auth/login", {"username": username, "password": "SyntheticAcceptance-" + username, "role": "school_uploader"})
            initial = call(client, "/api/v1/demo2/school/context")
            assert not any(initial["context"].values())
            assert call(client, "/api/v1/demo2/identity/roster")["roster"]["students"] == []
            school = {"selection_source": "other", "province": "合成测试省", "city": "合成测试市",
                      "district": f"隔离测试区{number}", "street": "合成测试街道", "address": f"合成测试路{number}号",
                      "school_name": f"SYNTHETIC-隔离验收学校-{number}", "confirmed": True, "expected_context": initial["context"]}
            saved = call(client, "/api/v1/demo2/school/context", school)
            assert saved["context"]["school_name"] == school["school_name"]
            assert call(client, "/api/v1/demo2/school/context")["details"]["source_status"] == "pending"
            name = f"SYNTHETIC-测试学生-{number}"
            student = call(client, "/api/v1/demo2/identity/students", {"display_name": name, "student_code": f"TEST-{number}", "class_name": "合成测试班", "note": "Synthetic acceptance only"})["student"]
            course = f"synthetic-course-{number}"
            task = call(client, "/api/v1/demo2/upload/tasks", {
                "course_id": course, "course_name": "SYNTHETIC MEDIA ACCEPTANCE", "session_id": course,
                "uploader_name": "SYNTHETIC TEST UPLOADER",
                "channel_id": f"channel_{number}", "filename": source.name, "byte_size": len(media),
                "total_chunks": 1, "security_confirmed": True, "allow_company_archive": False,
            })["task"]
            task_id = task["task_id"]
            call(client, "/api/v1/demo2/upload/chunks", {"course_id": course, "task_id": task_id,
                 "chunk_index": 0, "content_base64": base64.b64encode(media).decode()})
            assert VideoAnalysisWorker(store).run_once(), "No uploaded task claimed"
            task_result = call(client, "/api/v1/demo2/upload/task?" + urlencode({"id": task_id}))
            assert task_result["task"]["analysis_status"] in {"evidence_ready", "completed"}, task_result["task"]
            assert task_result["result"]["provenance"]["video"] == "ffmpeg_full_decode_and_fps_filter"
            query = urlencode({"task_id": task_id})
            workspace = call(client, "/api/v1/demo2/identity/workspace?" + query)["workspace"]
            assert workspace["media_available"] and workspace["frames"]
            frame = workspace["frames"][0]
            frame_query = urlencode({"task_id": task_id, "frame_key": frame["frame_key"], "frame_revision": workspace["frame_revision"]})
            jpeg = call(client, "/api/v1/demo2/identity/frame?" + frame_query)
            decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None and float(decoded.std()) > 10
            box = {"x": .15, "y": .2, "width": .35, "height": .65}
            binding = call(client, "/api/v1/demo2/identity/bindings", {
                "task_id": task_id, "frame_key": frame["frame_key"], "frame_revision": workspace["frame_revision"],
                "role": "student", "student_id": student["student_id"], "bbox": box,
            })["binding"]
            reloaded = call(client, "/api/v1/demo2/identity/workspace?" + query)["workspace"]
            assert any(b["binding_id"] == binding["binding_id"] and b["student_id"] == student["student_id"] and b["bbox"] == box for b in reloaded["bindings"])
            report = call(client, "/api/v1/demo2/identity/export?" + query)
            assert report["school_context"] == saved["context"]
            assert report["students"][0]["display_name"] == name
            assert report["bindings"][0]["student_id"] == student["student_id"]
            (root / f"SYNTHETIC-school-{number}-identity-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            assessment_checks = verify_teacher_reports(call, client, root, number, task_id, course,
                student, binding, workspace["frame_revision"], task_result["result"]["source_sha256"], saved["context"])
            rows.append({"account": username, "school": school["school_name"], "student": name, "task_id": task_id,
                         "scope_key": reloaded["scope_key"], "real_media_decode": True, "named_binding_saved_reloaded": True,
                         "identity_report_verified": True, "teacher_reports": assessment_checks})
            browser_accounts.append({"cookie": next(c.value for c in jar if c.name == "rehab_demo2_session"), "task_id": task_id, "student": name})
        assert len({row["scope_key"] for row in rows}) == 4
        for index, client in enumerate(clients):
            roster = call(client, "/api/v1/demo2/identity/roster")["roster"]
            assert [s["display_name"] for s in roster["students"]] == [rows[index]["student"]]
            denied = call(client, "/api/v1/demo2/identity/workspace?" + urlencode({"task_id": rows[(index + 1) % 4]["task_id"]}), expected=404)
            assert denied["error"]["code"] == "task_unavailable"
            course_denied = call(client, "/api/v1/demo2/course-analysis?" + urlencode({"task_id": rows[(index + 1) % 4]["task_id"]}), expected=404)
            assert course_denied["error"]["code"] == "task_unavailable"
            measures = call(client, "/api/v1/demo2/measurements")["workspace"]["records"]
            assert len(measures) == 1 and measures[0]["task_id"] == rows[index]["task_id"]
            evaluations = call(client, "/api/v1/demo2/evaluations")["workspace"]["records"]
            assert len(evaluations) == 1 and evaluations[0]["lesson_id"] == f"synthetic-course-{index + 1}"
        browser_status = browser_check(origin, browser_accounts, root)
        summary = {"status": "passed", "isolated_root": str(root), "database": str(store.db_path),
                   "upload_dir": str(store.upload_dir), "video_dir": str(store.video_task_dir), "schools": rows,
                   "browser": browser_status, "report_type": "identity export and task-linked teacher-grounded course/measurement reports; separate manual classroom evaluation",
                   "assessment_limitation": "Known synthetic teacher inputs and simulated applicability confirmation; not automatic assessment or real classroom observations",
                   "evaluation_provenance_gap": "Evaluation API has no task_id/student_id fields; source references there are manual text, not enforced links",
                   "live_instance_accessed": False, "external_api_calls": False}
        (root / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=True))
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)
        assert not thread.is_alive(), "Isolated HTTP server failed to stop"


def verify_teacher_reports(call, client, root, number, task_id, course, student, binding, revision, sha256, school):
    """Exercise existing contracts without injecting DB rows or analysis results."""
    query = urlencode({"task_id": task_id})
    endpoint = "/api/v1/demo2/course-analysis?" + query
    initial = call(client, endpoint)["workspace"]
    assert initial["task_id"] == task_id and initial["school_context"] == school
    assert initial["summary"]["scored"] == 0 and initial["report"]["ready"] is False
    assert initial["applicability"]["allowed"] is False
    prompt = f"SYNTHETIC teacher {number}: point to the green test rectangle"
    response = f"SYNTHETIC response {number}: two fixture opportunities with visual support"
    evidence = f"SYNTHETIC OBSERVATION ONLY; task={task_id}; student={student['student_id']}; frame={binding['frame_key']}; fixture inputs, not inferred behavior"
    payload = dict(record_id=f"synthetic-measure-{number}", expected_version=0,
        student_id=student["student_id"], lesson_id=course, lesson_date=date.today().isoformat(),
        course_name="SYNTHETIC MEDIA ACCEPTANCE", goal_id="SYNTHETIC-shape-goal",
        measurement_context="SYNTHETIC visual support", criterion="Synthetic fixture criterion: two observed opportunities",
        scores=dict(accuracy=None, independence=None, consistency=None, transfer=None),
        opportunities=3, observed=1, reviewed=False, evidence=evidence, source_type="video_review",
        task_id=task_id, start_sec=0, end_sec=2, teacher_prompt=prompt, student_response=response,
        support_level="visual", observed_state="participating", response_mode="gesture",
        audio_quality="missing", vocalization="unknown", speaker_confirmed=False)
    draft = call(client, "/api/v1/demo2/measurements", payload)["record"]
    assert draft["assessment"]["overall_score"] is None and draft["assessment"]["provisional_score"] is None
    assert call(client, endpoint)["workspace"]["report"]["ready"] is False
    complete = dict(accuracy=8, independence=7, consistency=6, transfer=5)
    scored = {**payload, "expected_version": 1, "reviewed": True, "observed": 2, "scores": complete}
    denied = call(client, "/api/v1/demo2/measurements", scored, expected=409)
    assert denied["error"]["code"] == "applicability_required"
    applicability = call(client, "/api/v1/demo2/applicability?" + query)["result"]
    call(client, "/api/v1/demo2/applicability", dict(task_id=task_id,
        version=applicability["version"], revision=applicability["revision"], category="special", confirmed=True,
        goal="SYNTHETIC acceptance: simulate teacher-confirmed eligibility, not actual special-education footage",
        reason="SYNTHETIC geometry fixture; this test input exercises the human-confirmation gate only"))
    partial = call(client, "/api/v1/demo2/measurements", {**scored, "scores": {**complete, "transfer": None}})["record"]
    assert partial["assessment"]["overall_score"] is None and partial["assessment"]["passed"] is None
    incomplete_work = call(client, endpoint)["workspace"]
    assert incomplete_work["summary"]["scored"] == 0
    assert "证据尚不足以形成总分" in json.dumps(incomplete_work["report"], ensure_ascii=False)
    final = call(client, "/api/v1/demo2/measurements", {**scored, "expected_version": 2})["record"]
    assert final["assessment"]["overall_score"] == 6.85
    assert final["assessment"]["confidence"] is None
    assert final["binding_id"] == binding["binding_id"] and final["frame_revision"] == revision
    assert final["source_sha256"] == sha256 and final["student_id"] == student["student_id"]
    report = call(client, endpoint)["workspace"]
    assert report["task_id"] == task_id and report["school_context"] == school
    assert [p["student_id"] for p in report["people"]] == [student["student_id"]]
    assert len(report["records"]) == 1
    assert all(report["records"][0][key] == value for key, value in final.items())
    assert report["records"][0]["evidence_status"] == "current"
    assert report["records"][0]["applicability_blocked"] is False
    assert report["records"][0]["course_batch_id"] == course
    assert report["summary"]["scored"] == 1 and report["report"]["ready"] is True
    text = " ".join(section["text"] for section in report["report"]["sections"])
    assert student["display_name"] in text and prompt in text and "6.85/10" in text
    assert "教师复核" in report["source_note"]
    assert report["report"]["record_versions"] == [{"record_id": payload["record_id"], "version": 3}]
    measurement = call(client, "/api/v1/demo2/measurements")["workspace"]
    assert measurement["records"][0]["task_id"] == task_id
    assert measurement["trends"][0]["student_id"] == student["student_id"]
    assert measurement["trends"][0]["series"]["lesson"][0]["score"] == 6.85

    # Evaluation is school/lesson-scoped only. Do not pretend manual text links
    # provide the task/student provenance that the measurement endpoint enforces.
    evaluation = dict(record_id=f"synthetic-evaluation-{number}", expected_version=0,
        lesson_id=course, lesson_date=date.today().isoformat(), course_name="SYNTHETIC teacher evaluation",
        subject_id="math", template_id="basic_100", goal_context=evidence,
        school_source="teacher_recorded", school_rater=f"SYNTHETIC teacher {number}", reviewed=False,
        items=[dict(id=f"i{i}", school_score=8, enhanced_score=7, evidence=evidence,
                    reason="SYNTHETIC teacher rubric input, not media inference", suggestion="SYNTHETIC follow-up observation") for i in range(1, 11)])
    invalid = call(client, "/api/v1/demo2/evaluations", {**evaluation, "task_id": task_id, "student_id": student["student_id"]}, expected=400)
    assert invalid["error"]["code"] == "invalid_payload"
    evaluation["items"][0].update(school_score=None, enhanced_score=None, evidence="")
    preview = call(client, "/api/v1/demo2/evaluations/preview", evaluation)["result"]
    assert preview["status"] == "incomplete"
    for mode in ("school", "enhanced"):
        assert preview[mode]["score_10"] is None and preview[mode]["passed"] is None
    assert call(client, "/api/v1/demo2/evaluations")["workspace"]["records"] == []
    evaluation_draft = call(client, "/api/v1/demo2/evaluations", evaluation)["record"]
    assert evaluation_draft["result"] == preview
    evaluation.update(expected_version=1, reviewed=True)
    evaluation["items"][0].update(school_score=8, enhanced_score=7, evidence=evidence)
    evaluated = call(client, "/api/v1/demo2/evaluations", evaluation)["record"]
    assert evaluated["result"]["school"]["raw_score"] == 80
    assert evaluated["result"]["enhanced"]["score_10"] == 7
    reopened = call(client, "/api/v1/demo2/evaluations")["workspace"]
    assert reopened["school_context"] == school and reopened["records"] == [evaluated]
    bundle = {"synthetic_only": True, "automatic_assessment": False,
              "incomplete_course": incomplete_work, "course_report": report,
              "measurement_workspace": measurement, "incomplete_evaluation": evaluation_draft,
              "manual_evaluation": evaluated,
              "evaluation_provenance": "Manual text only: API rejects task_id/student_id"}
    (root / f"SYNTHETIC-school-{number}-teacher-reports.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"task_student_source_verified": True, "teacher_course_report_verified": True,
            "measurement_score": 6.85, "incomplete_measurement_score": None,
            "incomplete_evaluation_score": None, "applicability_gate_verified": True,
            "manual_evaluation_reloaded": True, "evaluation_structured_task_student_binding": False}


def browser_check(origin, accounts, root):
    module = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"
    node = shutil.which("node")
    if not node or not module.exists():
        return "not run: installed Node/Playwright unavailable"
    cache = Path.home() / "AppData/Local/ms-playwright"
    candidates = sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)
    executable = str(candidates[0]) if candidates else "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    code = r"""
const fs=require('fs'),assert=require('assert/strict');const d=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const browser=await require(d.module).chromium.launch({headless:true,executablePath:d.executable});
try{for(let i=0;i<d.accounts.length;i++){
 const a=d.accounts[i],context=await browser.newContext(),page=await context.newPage();
 await context.route('**/*',route=>new URL(route.request().url()).origin===d.origin?route.continue():route.abort());
 await context.addCookies([{name:'rehab_demo2_session',value:a.cookie,url:d.origin}]);
 await page.goto(d.origin+'/demo2/identity?task_id='+a.task_id);
 await page.waitForFunction(name=>document.querySelector('#bindingList')?.textContent.includes(name),a.student,{timeout:20000});
 await page.reload();await page.waitForFunction(name=>document.querySelector('#bindingList')?.textContent.includes(name),a.student,{timeout:20000});
 await page.waitForFunction(()=>Array.from(document.images).some(img=>img.complete&&img.naturalWidth>100),null,{timeout:20000});
 await page.screenshot({path:d.root+'/SYNTHETIC-identity-'+(i+1)+'.png',fullPage:true});
 await context.close();
}}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run([node, "-e", code], input=json.dumps({"module": str(module), "origin": origin,
        "accounts": accounts, "executable": executable, "root": str(root)}), text=True, encoding="utf-8", capture_output=True, timeout=100)
    assert result.returncode == 0, result.stderr
    return "4/4 real identity pages: named saved binding, browser reload, decoded image, screenshot; creation/bbox save via HTTP API"


if __name__ == "__main__":
    main()
