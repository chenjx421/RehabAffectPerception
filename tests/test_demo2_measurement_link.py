"""Archive → video-source measurement records → trend/report/evaluation/completeness/ID chain (修改意见第 5 条).

Synthetic task, fictional student and fictional IEP/course-task content only.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("docx")

from rehab_affect import demo2_course_task_store as course_tasks  # noqa: E402
from rehab_affect import demo2_person_filter  # noqa: E402
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore  # noqa: E402
from rehab_affect.demo2_measurement_link import (  # noqa: E402
    SUGGESTION_LABEL,
    MeasurementLinkService,
    LinkError,
    suggest_scores,
    video_metrics,
)
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError  # noqa: E402
from rehab_affect.demo2_report_store import Demo2ReportStore  # noqa: E402
from rehab_affect.video_applicability import ApplicabilityStore  # noqa: E402
from test_demo2_course_task import GOALS  # noqa: E402
from test_demo2_dossier_store import day, env, task, template  # noqa: E402,F401
from test_demo2_evaluation_store import payload as evaluation_payload  # noqa: E402
from test_demo2_iep_intake import _parse, service  # noqa: E402,F401

_SPEC = importlib.util.spec_from_file_location(
    "verify_id_chain_link", Path(__file__).resolve().parents[1] / "scripts" / "verify_id_chain.py")
verify_id_chain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify_id_chain)

STUDENT_NAME = "虚构同名学生"
MANUAL = "上课前先展示当天流程图（虚构）。"
PERSON = {
    "person_id": "person_1", "display_name": "学生 1", "average_student_score": 6.8,
    "dominant_student_state_zh": "稳定参与",
    "windows": [
        {"start_sec": 0.0, "end_sec": 0.25, "student_state": "engaged", "student_state_zh": "稳定参与", "student_score": 7.2},
        {"start_sec": 0.25, "end_sec": 0.5, "student_state": "active_response", "student_state_zh": "出现回应或操作", "student_score": 8.0},
        {"start_sec": 0.5, "end_sec": 0.75, "student_state": "low_response", "student_state_zh": "回应信号较低", "student_score": 4.1},
        {"start_sec": 0.75, "end_sec": 1.0, "student_state": "uncertain", "student_state_zh": "证据不足"},
    ],
}


@pytest.fixture
def flow(env, service, monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_MEASUREMENT_DEBUG_LOG_DIR", str(tmp_path / "measure_logs"))
    analysis = {"available": True, "persons": [PERSON]}
    monkeypatch.setattr(env.records, "_read_simple_analysis_cache",
                        lambda task, version: {"status": "completed", "analysis": analysis})
    monkeypatch.setattr(env.records, "_simple_binding_matches_analysis", lambda analysis, binding, person_id: True)
    monkeypatch.setattr(demo2_person_filter, "excluded_person_ids", lambda analysis: set())
    svc, documents = service
    token, student = env.tokens["a"], env.pupils["a1"]["student_id"]
    video = task(env)
    with env.records._connect() as db:
        course_tasks.ensure_schema(db)
        task_row = db.execute("SELECT course_id FROM video_analysis_tasks WHERE task_id=?", (video.task_id,)).fetchone()
        doc_id = "ctd-" + "1" * 32
        db.execute(
            "INSERT INTO demo2_course_task_documents (course_task_doc_id, course_id, owner_account_id, version, status, "
            "original_path, original_extension, original_sha256, byte_size, parse_id, course_name, lesson_date, goal_count, "
            "goals_json, created_at, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, task_row["course_id"], env.accounts["a"]["account_id"], 1, "confirmed", "x", ".pdf", "0" * 64, 1,
             "dp-" + "0" * 32, "合成课程", date.today().isoformat(), len(GOALS),
             json.dumps({"goals": GOALS, "notes": []}, ensure_ascii=False),
             "2026-10-31T00:00:00+00:00", "2026-10-31T00:00:00+00:00"))
    parse_id = _parse(env, documents)
    summary = svc.generate_summary(token, {"parse_id": parse_id})
    items = [{"item_id": i["item_id"], "text": i["text"]} for i in summary["items"]]
    iep = svc.commit(token, student, {"mode": "new", "parse_id": parse_id, "items": items, "manual_supplement": MANUAL,
                                      "confirmed": True,
                                      "authorization": {"reference": "虚构授权-061", "valid_until": day(30), "confirmed": True}},
                     task_id=video.task_id)
    archive = env.records.archive_simple_lesson(token, {
        "task_id": video.task_id, "person_id": "person_1", "student_id": student,
        "binding_id": video.binding["binding_id"], "main_state": "稳定参与", "average_score": 6.8,
        "key_times_sec": [0], "state_breakdown": {"稳定参与": 2}, "lesson_summary": "合成课堂总结：能跟随流程完成任务。",
        "iep_document_id": iep["document_id"], "iep_reference_id": iep["reference_id"],
        "iep_manual_supplement": MANUAL, "iep_item_count": iep["item_count"]})

    def loader(tok, sid, document_id):
        workspace = env.store.student_workspace(tok, sid)
        return next((d for d in workspace["documents"] if d["document_id"] == document_id), None)

    link = MeasurementLinkService(env.records, iep_loader=loader)
    measurements = Demo2MeasurementStore(env.records)
    reports = Demo2ReportStore(env.records)

    def regenerate():
        return reports.save_from_workspace(token, measurements.course_workspace(token, video.task_id))

    return type("Flow", (), dict(env=env, token=token, student=student, video=video, doc_id=doc_id, iep=iep,
                                 items=items, archive=archive, link=link, measurements=measurements,
                                 reports=reports, regenerate=staticmethod(regenerate),
                                 logs=tmp_path / "measure_logs"))


def _lines(folder, prefix):
    return [json.loads(line) for path in sorted(folder.glob(f"{prefix}_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_metrics_and_suggestions_are_marked_and_never_formal():
    metrics = video_metrics(PERSON)
    assert (metrics["engaged_segments"], metrics["low_response_segments"], metrics["away_segments"]) == (2, 1, 1)
    assert metrics["engaged_ratio"] == 0.5 and metrics["participation_score_ref"] == 6.8
    suggestion = suggest_scores(metrics)
    assert suggestion["scores"]["transfer"] is None and suggestion["scores"]["accuracy"] == 7.0
    assert suggestion["observed"] <= suggestion["opportunities"]


def test_archive_creates_pending_video_records_with_full_chain(flow):
    created = flow.link.create_from_archive(flow.token, flow.archive)
    assert created["created"] == len(GOALS) and created["status"] == "pending_review"
    again = flow.link.create_from_archive(flow.token, flow.archive)  # idempotent
    assert again["created"] == 0 and again["unchanged"] == len(GOALS)
    work = flow.measurements.workspace(flow.token)
    video = [r for r in work["records"] if r["source_type"] == "video"]
    assert sorted(r["goal_id"] for r in video) == ["G-01", "G-02"]
    first = next(r for r in video if r["goal_id"] == "G-01")
    assert first["reviewed"] is False and first["assessment"]["score"] is None
    assert all(v is None for v in first["scores"].values())
    assert first["suggestion_label"] == SUGGESTION_LABEL and first["suggested_scores"]["accuracy"] is not None
    assert first["criterion"] == "3次中正确2次" and first["measurement_context"] == "模拟超市，口头提示"
    assert first["course_task_doc_id"] == flow.doc_id and first["video_task_id"] == flow.video.task_id
    assert first["iep_document_id"] == flow.iep["document_id"] and first["school_id"]
    assert [i["item_id"] for i in first["iep_support"]] == [i["item_id"] for i in flow.items]
    assert first["iep_manual_supplement"] == MANUAL and first["iep_status"] == "available"
    assert first["evidence_segments"][0]["url"].startswith(f"/demo2/video?id={flow.video.task_id}&t=")
    assert first["lesson_date"] == date.today().isoformat() and first["lesson_date_source"] == "course_task"
    # Unreviewed points stay out of the score line (null lesson point, no formal score).
    trend = next(t for t in work["trends"] if t["goal_id"] == "G-01" and t["student_id"] == flow.student)
    assert trend["series"]["lesson"] and all(p["score"] is None for p in trend["series"]["lesson"])
    prefill = flow.link.prefill(flow.token, first["record_id"])
    assert prefill["record_id"] == first["record_id"] and prefill["pass_criteria"] == "3次中正确2次"
    with pytest.raises(LinkError):
        flow.link.prefill(flow.env.tokens["b"], first["record_id"])
    lines = _lines(flow.logs, "measurement_link")
    assert {"video_measurement_create", "measurement_prefill"} <= {line["operation"] for line in lines}
    raw = json.dumps(lines, ensure_ascii=False)
    assert STUDENT_NAME not in raw and MANUAL not in raw and flow.student not in raw
    assert flow.student[:8] in raw and "模拟超市" not in raw


def test_report_completeness_backfill_review_and_id_chain(flow, capsys):
    flow.link.create_from_archive(flow.token, flow.archive)
    check = flow.link.completeness(flow.token, flow.video.task_id)
    assert check["status"] == "incomplete" and {m["kind"] for m in check["missing"]} == {"report"}
    snapshot = flow.regenerate()
    check = flow.link.completeness(flow.token, flow.video.task_id)
    assert check["status"] == "complete", check["missing"]
    assert check["students"][0]["goal_found"] == len(GOALS) and check["students"][0]["iep_item_total"] == len(flow.items) + 1

    # Teacher view/download carries measurement + teacher-only IEP chapters; the stored snapshot does not.
    teacher = flow.reports.get(flow.token, snapshot["report_id"])
    titles = [s["title"] for s in teacher["payload"]["report"]["sections"]]
    assert "学生测量结果" in titles and "IEP 支持要点（教师侧）" in titles and "本课任务目标与达成情况" in titles
    with flow.env.records._connect() as db:
        stored = db.execute("SELECT payload_json FROM demo2_reports WHERE report_id=?", (snapshot["report_id"],)).fetchone()[0]
    assert MANUAL not in stored and "IEP 支持要点（教师侧）" not in stored
    md, _, _ = flow.reports.download(flow.token, snapshot["report_id"], fmt="md")
    as_json, _, _ = flow.reports.download(flow.token, snapshot["report_id"], fmt="json")
    for text in (md, as_json):
        assert "学生测量结果" in text and "本课任务目标与达成情况" in text and MANUAL in text
    assert "| 学生 | 目标编号 | 通过标准 |" in md and SUGGESTION_LABEL in md
    rows = json.loads(as_json)["report"]["student_measurements"]
    assert {r["goal_id"] for r in rows} == {"G-01", "G-02"} and all(r["suggestion_label"] == SUGGESTION_LABEL for r in rows)
    admin = flow.reports.get(flow.env.tokens["admin"], snapshot["report_id"])
    admin_md, _, _ = flow.reports.download(flow.env.tokens["admin"], snapshot["report_id"], fmt="md")
    for text in (json.dumps(admin, ensure_ascii=False), admin_md):
        assert STUDENT_NAME not in text and MANUAL not in text and "iep_support" not in text
        assert "IEP 支持要点" not in text and "学生测量结果" in text

    # A deleted (withdrawn) record shows up as not entered; one-click backfill restores it.
    record = next(r for r in flow.measurements.workspace(flow.token)["records"] if r["goal_id"] == "G-02")
    flow.measurements.withdraw(flow.token, {"record_id": record["record_id"], "expected_version": record["version"],
                                            "reason": "验收：人为删除一条"})
    check = flow.link.completeness(flow.token, flow.video.task_id)
    assert check["status"] == "incomplete"
    assert any(m["kind"] == "course_goal" and m["key"] == "G-02" for m in check["missing"])
    assert check["message"].startswith("以下内容尚未录入：")
    restored = flow.link.backfill(flow.token, flow.video.task_id, regenerate_report=flow.regenerate)
    assert restored["status"] == "complete" and restored["backfill"]["created"] == 1
    assert restored["backfill"]["report_regenerated"] is True

    # Client cannot create a video-source record; teacher review needs applicability, then scores count.
    with pytest.raises(MeasurementError) as error:
        flow.measurements.save(flow.token, {**{k: record[k] for k in ("student_id", "lesson_date", "lesson_id", "course_name",
                                                                       "goal_id", "measurement_context", "criterion",
                                                                       "evidence", "task_id", "start_sec", "end_sec")},
                                            "record_id": "manual-video-1", "expected_version": 0, "source_type": "video",
                                            "scores": {"accuracy": 7}, "opportunities": 3, "observed": 3, "reviewed": False})
    assert error.value.code == "video_source_reserved"
    current = next(r for r in flow.measurements.workspace(flow.token)["records"] if r["goal_id"] == "G-01")
    review = {k: current[k] for k in ("record_id", "student_id", "lesson_date", "lesson_id", "course_name", "goal_id",
                                      "measurement_context", "criterion", "evidence", "task_id", "start_sec", "end_sec")}
    review.update(expected_version=current["version"], source_type="video", reviewed=True, opportunities=4, observed=3,
                  scores={"accuracy": 7, "independence": 6.5, "consistency": 8, "transfer": 6})
    with pytest.raises(MeasurementError) as error:
        flow.measurements.save(flow.token, review)
    assert error.value.code == "applicability_required"
    suitability = ApplicabilityStore(flow.env.records)
    state = suitability.workspace(flow.token, flow.video.task_id)
    suitability.save(flow.token, dict(task_id=flow.video.task_id, version=state["version"], revision=state["revision"],
                                      category="special", goal="合成课堂分类目标", reason="合成视频工程测试", confirmed=True))
    saved = flow.measurements.save(flow.token, review)
    assert saved["assessment"]["score"] is not None and saved["iep_support"] and saved["video_metrics"]
    assert saved["course_task_doc_id"] == flow.doc_id  # system-owned link fields survive the teacher save
    debug_ops = [line["operation"] for line in _lines(flow.logs, "measurement_debug") if line.get("record_id") == current["record_id"]]
    # Unchanged per-save sequence; the applicability rejection above is logged first as before.
    assert debug_ops == ["measurement_rejected", "measurement_update", "measurement_review", "score_compute"]
    assert any(line["operation"] == "measurement_review" and line["result"] == "reviewed"
               for line in _lines(flow.logs, "measurement_link"))

    # System track of the dual evaluation cites the measurement records per course goal.
    evaluation = Demo2EvaluationStore(flow.env.records).save(flow.token, evaluation_payload(
        task_id=flow.video.task_id, frame_revision=flow.video.revision, course_task_doc_id=flow.doc_id,
        lesson_id=flow.measurements.workspace(flow.token)["records"][0]["lesson_id"]))
    assert {r["record_id"] for r in evaluation["measurement_refs"]} >= {current["record_id"]}
    basis = {b["goal_code"]: b for b in evaluation["course_task_goal_basis"]}
    assert current["record_id"] in basis["G-01"]["measurement_record_ids"]

    final = flow.regenerate()
    assert flow.link.completeness(flow.token, flow.video.task_id)["status"] == "complete"
    code = verify_id_chain.main(["--db", str(flow.env.records.db_path), "--json", "--quiet", "--no-log-file",
                                 "--report-id", final["report_id"], "--require-iep"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, json.dumps(out, ensure_ascii=False)[:3000]
    linked = out["results"][0]["linked"]
    assert linked["course_task_doc_id"] == flow.doc_id and linked["course_task_exists"] is True
    assert {m["course_task_doc_id"] for m in linked["measurements"]} == {flow.doc_id}
    assert all(m["iep_document_id"] == flow.iep["document_id"] for m in linked["measurements"])
    operations = {line["operation"] for line in _lines(flow.logs, "measurement_link")}
    assert {"video_measurement_create", "completeness_check", "completeness_backfill", "measurement_review"} <= operations


def test_withdrawn_authorization_hides_iep_points(flow):
    flow.link.create_from_archive(flow.token, flow.archive)
    auth = flow.env.store.student_workspace(flow.token, flow.student)["authorization"]
    flow.env.store.withdraw_authorization(flow.token, {"student_id": flow.student,
                                                       "authorization_id": auth["authorization_id"], "confirmed": True})
    records = [r for r in flow.measurements.workspace(flow.token)["records"] if r["source_type"] == "video"]
    assert records and all(r["iep_support"] == [] and r["iep_manual_supplement"] == "" for r in records)
    assert all(r["iep_status"] == "authorization_withdrawn" for r in records)
    work = flow.measurements.course_workspace(flow.token, flow.video.task_id)
    assert MANUAL not in json.dumps(work["report"], ensure_ascii=False)
    check = flow.link.completeness(flow.token, flow.video.task_id)
    assert not any(m["kind"] == "iep_item" for m in check["missing"])


def test_second_current_iep_marks_chain_ambiguous_without_measurement_mismatch(flow, service, capsys):
    """A second valid IEP for the same student is reported once as ambiguous (exit 3), never as broken links."""
    flow.link.create_from_archive(flow.token, flow.archive)
    Demo2EvaluationStore(flow.env.records).save(flow.token, evaluation_payload(
        task_id=flow.video.task_id, frame_revision=flow.video.revision, course_task_doc_id=flow.doc_id,
        lesson_id=flow.measurements.workspace(flow.token)["records"][0]["lesson_id"]))
    report = flow.regenerate()
    _, documents = service
    parse_id = _parse(flow.env, documents)
    svc, _ = service
    summary = svc.generate_summary(flow.token, {"parse_id": parse_id})
    second = svc.commit(flow.token, flow.student, {
        "mode": "new", "parse_id": parse_id, "confirmed": True, "manual_supplement": "第二份虚构 IEP。",
        "items": [{"item_id": i["item_id"], "text": i["text"]} for i in summary["items"]]}, origin="dossier")
    assert second["document_id"] != flow.iep["document_id"]
    assert svc.student_status(flow.token, flow.student)["iep_status"] == "ambiguous"
    code = verify_id_chain.main(["--db", str(flow.env.records.db_path), "--json", "--quiet", "--no-log-file",
                                 "--report-id", report["report_id"], "--require-iep"])
    out = json.loads(capsys.readouterr().out)
    level = out["results"][0]["levels"]["iep_document_id"]
    assert code == 3 and out["final_status"] == "ambiguous", json.dumps(out["results"][0].get("errors"), ensure_ascii=False)[:2000]
    assert level["status"] == "ambiguous"
    assert {p["code"] for p in level["problems"]} == {"multiple_current_iep"}
    assert set(level["entries"][0]["candidates"]) == {flow.iep["document_id"], second["document_id"]}
