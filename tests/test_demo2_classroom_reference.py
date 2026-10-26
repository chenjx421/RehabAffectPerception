"""Classroom dossier references: stable IDs, re-verification, withdrawal and debug logs (synthetic only)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from rehab_affect import demo2_dossier_store as module
from rehab_affect.demo2_dossier import render_task
from rehab_affect.demo2_measurement_store import MeasurementError
from test_demo2_dossier_store import (SECRET, SUMMARY_FIELDS, assert_error, authorize, day, document,  # noqa: F401
                                      document_payload, env, query, reference, reference_payload, task, template)
from test_demo2_iep_report_integration import prepared


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    folder = tmp_path / "reference_logs"
    monkeypatch.setenv(module.DEBUG_LOG_DIR_ENV, str(folder))
    return folder


def log_entries(folder):
    return [json.loads(line) for path in sorted(folder.glob("dossier_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def summary_only(**changes):
    return {"filename": "", "content_base64": "", **changes}


def test_page_layout_matches_reference_design():
    html = render_task({"role": "school_uploader", "username": "t1"})
    for text in ("课堂证据 · 资料版本引用", "关联学生资料", 'id="taskGate"', "本次课堂引用", "已确认学生（必选）",
                 "请选择已确认学生", "已核对该学生的当前画面身份与资料版本，确认用于本次课堂教育支持。",
                 "保存课堂引用记录", "已留存的引用", "导出时重新核验授权、资料和身份依据", "60 天是内测保存上限",
                 "下载课堂引用记录", "请选择一位当前已确认的学生。", "请至少勾选 1 个资料版本后再保存。",
                 "最多勾选 10 个资料版本", "撤回本课引用授权", "返回视频任务"):
        assert text in html, text
    assert html.index('id="taskGate"') < html.index("本次课堂引用") < html.index("已留存的引用") < html.index('class="policy-note"')
    assert 'id="saveReference" type="submit" disabled' in html


def test_task_workspace_lists_only_usable_versions_for_bound_students(env):
    auth = authorize(env)
    usable = document(env, authorization=auth, **summary_only())
    deleted = document(env, authorization=auth, document_type="professional_assessment", **summary_only())
    env.store.delete_document(env.tokens["a"], {"student_id": auth["student_id"], "document_id": deleted["document_id"], "confirmed": True})
    document(env, "a2", **summary_only())
    video = task(env)
    workspace = env.store.task_workspace(env.tokens["a"], video.task_id)
    assert [student["student_id"] for student in workspace["students"]] == [env.pupils["a1"]["student_id"]]
    assert [doc["document_id"] for doc in workspace["students"][0]["documents"]] == [usable["document_id"]]
    assert "仅列出当前版本有效学生身份绑定" in workspace["notice"]
    unbound = task(env, bind=False)
    assert env.store.task_workspace(env.tokens["a"], unbound.task_id)["students"] == []


def test_zero_or_more_than_ten_versions_cannot_be_saved(env):
    auth = authorize(env)
    docs = [document(env, authorization=auth, **summary_only()) for _ in range(11)]
    video = task(env)
    assert_error(400, "invalid_document_ids", env.store.create_reference, env.tokens["a"], reference_payload(env, video, []))
    assert_error(400, "invalid_document_ids", env.store.create_reference, env.tokens["a"], reference_payload(env, video, docs))
    assert query(env, "SELECT * FROM demo2_dossier_references") == []
    saved = env.store.create_reference(env.tokens["a"], reference_payload(env, video, docs[:10]))
    assert len(saved["document_versions"]) == 10 and saved["available"] is True


def test_reference_keeps_stable_ids_and_does_not_follow_new_versions(env):
    auth = authorize(env)
    iep = document(env, authorization=auth, **summary_only())
    professional = document(env, authorization=auth, document_type="professional_assessment", **summary_only())
    video = task(env)
    saved = reference(env, video, [iep, professional])
    assert saved["video_task_id"] == video.task_id == saved["task_id"]
    assert saved["student_id"] == env.pupils["a1"]["student_id"]
    assert saved["iep_document_ids"] == [iep["document_id"]]
    assert saved["document_versions"] == [{"document_id": iep["document_id"], "version": 1},
                                          {"document_id": professional["document_id"], "version": 1}]
    rows = query(env, "SELECT * FROM demo2_dossier_reference_documents WHERE reference_id = ? ORDER BY ordinal", (saved["reference_id"],))
    assert [(row["document_id"], row["version"]) for row in rows] == [(iep["document_id"], 1), (professional["document_id"], 1)]
    newer = env.store.create_document(env.tokens["a"], document_payload(auth, supersedes_id=iep["document_id"],
        summary={key: "NEW-VERSION-TEXT" for key in SUMMARY_FIELDS}, **summary_only()))
    assert newer["version"] == 2
    exported = env.store.reference_export(env.tokens["a"], saved["reference_id"])
    assert exported["document_versions"] == saved["document_versions"]
    assert exported["iep_document_ids"] == [iep["document_id"]]
    assert "NEW-VERSION-TEXT" not in json.dumps(exported, ensure_ascii=False)
    assert exported["export"]["valid_evidence"] is True and exported["export"]["invalid_sources"] == []
    assert {item["document_id"] for item in exported["export"]["valid_sources"]} == {iep["document_id"], professional["document_id"]}


@pytest.mark.parametrize("change,reason", [("delete", "document_deleted"), ("withdraw", "authorization_withdrawn"),
                                           ("expire", "document_expired")])
def test_invalid_sources_are_marked_and_never_valid_on_export(env, monkeypatch, log_dir, change, reason):
    auth = authorize(env)
    lost = document(env, authorization=auth, **summary_only())
    kept = document(env, authorization=auth, document_type="safety_support", **summary_only(retain_until=day(25)))
    video = task(env)
    saved = reference(env, video, [lost, kept])
    if change == "delete":
        env.store.delete_document(env.tokens["a"], {"student_id": auth["student_id"], "document_id": lost["document_id"], "confirmed": True})
    elif change == "withdraw":
        env.store.withdraw_authorization(env.tokens["a"], {"student_id": auth["student_id"], "authorization_id": auth["authorization_id"], "confirmed": True})
    else:
        later = module._today() + timedelta(days=21)
        monkeypatch.setattr(module, "_today", lambda: later)
        env.store.cleanup_expired()
    exported = env.store.reference_export(env.tokens["a"], saved["reference_id"])
    assert exported["available"] is False and exported["status"] == "sources_unavailable"
    invalid = {item["document_id"]: item for item in exported["export"]["invalid_sources"]}
    assert invalid[lost["document_id"]]["reason"] == reason
    assert lost["document_id"] not in {item["document_id"] for item in exported["export"]["valid_sources"]}
    assert exported["export"]["valid_evidence"] is False
    marked = next(item for item in exported["sources"] if item["document_id"] == lost["document_id"])
    assert marked["valid_as_evidence"] is False
    lost_public = next(doc for doc in exported["documents"] if doc["document_id"] == lost["document_id"])
    assert lost_public["summary"] == {} and lost_public["source_ref"] == ""
    assert SECRET not in json.dumps(lost_public, ensure_ascii=False)
    workspace = env.store.task_workspace(env.tokens["a"], video.task_id)
    assert workspace["references"][0]["available"] is False
    entries = log_entries(log_dir)
    export_log = [entry for entry in entries if entry["operation"] == "reference_export"][-1]
    assert export_log["result"] == "invalid" and export_log["reference_id"] == saved["reference_id"]
    assert export_log["task_id"] == video.task_id and export_log["student_id"] == auth["student_id"]
    assert export_log["invalid_source_count"] >= 1 and "ts" in export_log
    checks = [entry for entry in entries if entry["operation"] == "reference_validity_check" and entry["result"] == "invalid"]
    assert checks and checks[-1]["reason"] == reason
    assert SECRET not in "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries)


def test_withdrawn_classroom_reference_stops_iep_in_analysis_and_scoring(env, log_dir):
    video, auth, doc, ref, measurements, _, evaluations, evaluation_payload, _ = prepared(env)
    token = env.tokens["a"]
    before = env.store.analysis_context(token, video.task_id)
    assert before["reads_iep"] is True and before["iep_included_count"] == 1
    assert before["references"][0]["included"] == [{"document_id": doc["document_id"], "version": 1, "document_type": "iep"}]
    work = measurements.course_workspace(token, video.task_id)
    assert work["people"][0]["iep_context"]["status"] == "available"
    withdrawn = env.store.withdraw_reference(token, {"reference_id": ref["reference_id"], "confirmed": True})
    assert withdrawn["withdrawn"] is True and withdrawn["status"] == "withdrawn" and withdrawn["available"] is False
    assert withdrawn["document_versions"] == ref["document_versions"]
    assert_error(409, "reference_already_withdrawn", env.store.withdraw_reference, token,
                 {"reference_id": ref["reference_id"], "confirmed": True})
    after = env.store.analysis_context(token, video.task_id)
    assert after["reads_iep"] is False and after["reads_professional_materials"] is False
    assert after["references"][0]["included"] == []
    assert after["references"][0]["excluded"][0]["reason"] == "reference_withdrawn"
    work = measurements.course_workspace(token, video.task_id)
    person = work["people"][0]
    assert person["iep_context"]["documents"] == [] and not person.get("iep_summary_id")
    assert person["iep_context"]["reason"] == "reference_withdrawn"
    assert SECRET not in json.dumps(work, ensure_ascii=False)
    with pytest.raises(MeasurementError) as error:
        evaluations.preview(token, {**evaluation_payload, "expected_version": 1})
    assert error.value.code == "iep_link_unavailable"
    exported = env.store.reference_export(token, ref["reference_id"])
    assert exported["export"]["valid_sources"] == [] and exported["export"]["invalid_sources"][0]["reason"] == "reference_withdrawn"
    operations = {(entry["operation"], entry["result"]) for entry in log_entries(log_dir)}
    assert ("reference_withdraw", "withdrawn") in operations
    assert ("analysis_context_snapshot", "included") in operations and ("analysis_context_snapshot", "none") in operations


def test_withdrawn_dossier_authorization_removes_materials_from_analysis_snapshot(env):
    video, auth, doc, ref, *_ = prepared(env)
    env.store.withdraw_authorization(env.tokens["a"], {"student_id": auth["student_id"], "authorization_id": auth["authorization_id"], "confirmed": True})
    snapshot = env.store.analysis_context(env.tokens["a"], video.task_id)
    assert snapshot["reads_iep"] is False and snapshot["references"][0]["included"] == []
    assert snapshot["references"][0]["excluded"][0]["reason"] == "authorization_withdrawn"


def test_reference_create_logs_ids_and_rejections(env, log_dir):
    auth = authorize(env)
    doc = document(env, authorization=auth, **summary_only())
    video = task(env)
    saved = reference(env, video, [doc])
    assert_error(400, "invalid_document_ids", env.store.create_reference, env.tokens["a"], reference_payload(env, video, []))
    entries = log_entries(log_dir)
    created = next(entry for entry in entries if entry["operation"] == "reference_create" and entry["result"] == "created")
    assert created["reference_id"] == saved["reference_id"] and created["task_id"] == video.task_id
    assert created["student_id"] == auth["student_id"] and created["document_count"] == 1
    assert created["evidence_status"] == "current" and created["ts"]
    rejected = next(entry for entry in entries if entry["operation"] == "reference_create" and entry["result"] == "rejected")
    assert rejected["code"] == "invalid_document_ids" and rejected["http_status"] == 400
