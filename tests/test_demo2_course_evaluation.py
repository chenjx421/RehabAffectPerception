"""课程评价：系统建议分、采纳/修改理由、类目汇总、依据过期与权限（调整意见第 3 条）。

只用合成任务、虚构学生与虚构课程任务目标。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from rehab_affect.classroom_rubric import TEMPLATES
from rehab_affect.demo2_course_evaluation import (
    INSUFFICIENT_LABEL,
    apply_teacher_decisions,
    build_suggestions,
    category_summary,
    data_fingerprint,
    stale_reasons,
)
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_measurement_store import MeasurementError

pytest.importorskip("docx")

from test_demo2_course_task import GOALS  # noqa: E402
from test_demo2_dossier_store import day, env, task, template  # noqa: E402,F401
from test_demo2_evaluation_store import payload as evaluation_payload  # noqa: E402
from test_demo2_iep_intake import service  # noqa: E402,F401
from test_demo2_measurement_link import flow  # noqa: E402,F401


def _segments(states):
    return [{"start_sec": float(n * 20), "end_sec": float(n * 20 + 20), "state": state, "state_label": state,
             "url": f"/demo2/video?id=task-x&t={n * 20}"} for n, state in enumerate(states)]


def _video_record(rid, student, goal, *, engaged, low, away, ref, states, reviewed=False, score=None, independence=None):
    total = engaged + low + away
    return {"record_id": rid, "student_id": student, "goal_id": goal, "version": 1, "payload": {
        "source_type": "video", "reviewed": reviewed, "saved_by": "system:video_archive" if not reviewed else "t1",
        "evidence": "教师复核：学生在提示后完成分类（虚构）" if reviewed else "系统待复核说明",
        "assessment": {"score": score}, "scores": {"independence": independence},
        "video_metrics": {"engaged_segments": engaged, "low_response_segments": low, "away_segments": away,
                          "not_observed_segments": 0, "engaged_seconds": engaged * 20.0,
                          "low_response_seconds": low * 20.0, "observed_seconds": total * 20.0,
                          "engaged_ratio": engaged / total, "low_response_ratio": low / total,
                          "participation_score_ref": ref},
        "evidence_segments": _segments(states)}}


def _three_students(reviewed=False):
    goals = [dict(g, goal_code=g.get("goal_code") or f"G-0{n + 1}") for n, g in enumerate(GOALS)]
    return {
        "task_id": "task-x", "course_id": "course-x",
        "course_task": {"course_task_doc_id": "ctd-" + "2" * 32, "version": 1, "goals": goals},
        "archived_students": ["s1", "s2", "s3"],
        "measurements": [
            _video_record("vm-1", "s1", "G-01", engaged=3, low=1, away=0, ref=7.2,
                          states=["engaged", "low_response", "engaged", "engaged"], reviewed=reviewed,
                          score=7.5 if reviewed else None, independence=7.0 if reviewed else None),
            _video_record("vm-2", "s2", "G-01", engaged=2, low=1, away=1, ref=6.0,
                          states=["engaged", "low_response", "away", "engaged"]),
            _video_record("vm-3", "s3", "G-01", engaged=0, low=0, away=4, ref=None, states=["away"] * 4),
        ],
    }


def test_three_student_lesson_prefills_at_least_five_items_with_basis():
    result = build_suggestions(_three_students())
    items = {i["id"]: i for i in result["items"]}
    assert [i["id"] for i in result["items"]] == [f"i{n}" for n in range(1, 11)]
    labels = {c["label"] for c in TEMPLATES["basic_100"]["categories"]}
    assert {i["category_label"] for i in result["items"]} == labels == {
        "目标适配与分层要求", "内容设计与教学组织", "过程支持与目标达成", "教师表达与响应调节"}
    suggested = [i for i in result["items"] if i["status"] == "suggested"]
    assert len(suggested) >= 5 and result["suggested_count"] == len(suggested)
    for item in suggested:
        assert 1 <= item["suggested_score"] <= 10 and item["formula"] and item["evidence_refs"]
        assert any(s["available"] for s in item["data_sources"])
    # Data sources named in the card: course goals / coverage / measurement / video.
    assert any(s["label"] == "课程任务目标" and s["available"] for s in items["i1"]["data_sources"])
    assert any(s["label"] == "学生覆盖率" and s["available"] for s in items["i7"]["data_sources"])
    assert any(s["label"] == "测量综合分" and s["available"] for s in items["i8"]["data_sources"])
    assert any(r["kind"] == "video" and r["url"].startswith("/demo2/video?id=task-x&t=") for r in items["i7"]["evidence_refs"])
    # Coverage 2/3 participating, engaged ratio avg (0.75+0.5+0)/3 → 10×(0.6×0.667+0.4×0.4167)=5.67 → 5.5
    assert items["i7"]["inputs"]["participating_students"] == 2 and items["i7"]["suggested_score"] == 5.5
    for teacher_only in ("i2", "i3", "i9"):
        assert items[teacher_only]["suggested_score"] is None
        assert items[teacher_only]["status_label"] == INSUFFICIENT_LABEL and items[teacher_only]["reason"]
    # No teacher observation → adjustment is not invented.
    assert items["i10"]["suggested_score"] is None
    assert "student_score" not in json.dumps(result) and "ability_score" not in json.dumps(result)


def test_reviewed_measurements_replace_video_cues_and_enable_adjustment():
    items = {i["id"]: i for i in build_suggestions(_three_students(reviewed=True))["items"]}
    assert items["i8"]["confidence"] == "data" and items["i8"]["suggested_score"] == 7.5
    assert items["i6"]["suggested_score"] == 7.0
    # One teacher observation; s1 and s2 both recover after a low-response segment → 2 + 8×2/2 = 10.
    assert items["i10"]["suggested_score"] == 10.0 and items["i10"]["inputs"]["students_recovered"] == 2
    assert items["i4"]["suggested_score"] is not None


def test_no_data_gives_insufficient_everywhere():
    result = build_suggestions({"task_id": "t", "course_id": "", "course_task": None,
                                "archived_students": [], "measurements": []})
    assert result["suggested_count"] == 0
    assert all(i["status_label"] == INSUFFICIENT_LABEL and i["reason"] for i in result["items"])


def test_decisions_require_reason_only_for_modified_suggestions():
    suggestions = build_suggestions(_three_students())
    by_id = {i["id"]: i for i in suggestions["items"]}
    rows = [{"id": i, "enhanced_score": by_id[i]["suggested_score"]} for i in by_id]
    rows[0]["enhanced_score"] = 3  # modify i1
    rows[1]["enhanced_score"] = 6  # teacher scores i2 (no suggestion)
    snapshot, missing = apply_teacher_decisions(suggestions, rows, {})
    assert missing == ["i1"]
    snapshot, missing = apply_teacher_decisions(suggestions, rows, {"i1": "教案中目标未分层（虚构）"})
    decisions = {i["id"]: i["decision"] for i in snapshot["items"]}
    assert missing == [] and decisions["i1"] == "modified" and decisions["i2"] == "teacher_scored"
    assert decisions["i7"] == "adopted" and snapshot["counts"]["modified"] == 1


def test_fingerprint_detects_course_task_and_measurement_changes():
    data = _three_students()
    saved = data_fingerprint(data)
    assert stale_reasons(saved, data_fingerprint(data)) == []
    data["measurements"][0]["version"] = 2
    assert stale_reasons(saved, data_fingerprint(data)) == ["measurements_changed"]
    data["course_task"]["version"] = 2
    assert "course_task_changed" in stale_reasons(saved, data_fingerprint(data))


def _course_payload(flow, course, **changes):
    suggestions = course["suggestions"]
    items = []
    for item in suggestions["items"]:
        items.append(dict(id=item["id"], school_score=8, enhanced_score=item["suggested_score"] if item["suggested_score"] is not None else 7,
                          evidence="课堂观察 00:20 提供回应机会（虚构）", reason="依据本课数据复核", suggestion="下一课增加独立回应机会"))
    lesson_id = flow.measurements.workspace(flow.token)["records"][0]["lesson_id"]
    base = evaluation_payload(record_id="course-eval-1", task_id=flow.video.task_id, frame_revision=flow.video.revision,
                              course_task_doc_id=flow.doc_id, lesson_id=lesson_id, items=items,
                              system_suggestions={"fingerprint": suggestions["fingerprint"]["fingerprint"], "reasons": {}})
    base.update(changes)
    return base


def _lines(folder):
    return [json.loads(line) for path in sorted(folder.glob("evaluation_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_course_evaluation_save_preview_lock_stale_and_access(flow, monkeypatch, tmp_path):
    logs = tmp_path / "eval_logs"
    monkeypatch.setenv("REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR", str(logs))
    flow.link.create_from_archive(flow.token, flow.archive)
    store = Demo2EvaluationStore(flow.env.records)
    course = store.course_suggestions(flow.token, flow.video.task_id)
    assert course["suggestions"]["suggested_count"] >= 3 and course["evaluations"] == []

    # Modified suggestion without reason → 400 with the field to mark.
    p = _course_payload(flow, course)
    suggested = next(i for i in course["suggestions"]["items"] if i["suggested_score"] is not None)
    row = next(r for r in p["items"] if r["id"] == suggested["id"])
    row["enhanced_score"] = 2 if suggested["suggested_score"] != 2 else 3
    with pytest.raises(MeasurementError) as error:
        store.preview(flow.token, p)
    assert error.value.code == "suggestion_reason_required" and error.value.field == f"suggestion_reason_{suggested['id']}"
    p["system_suggestions"]["reasons"][suggested["id"]] = "课堂中该环节明显超时（虚构）"
    preview = store.preview(flow.token, p)
    snapshot = preview["course_evaluation"]
    assert snapshot["counts"]["modified"] == 1 and len(snapshot["summary"]["categories"]) == 4
    saved = store.save(flow.token, p)
    assert saved["result"]["enhanced"]["score_10"] == preview["enhanced"]["score_10"]
    assert saved["course_evaluation"]["summary"] == snapshot["summary"]
    assert saved["evaluation_id"] == "evaluation-course-eval-1" and saved["video_task_id"] == flow.video.task_id
    assert saved["course_id"] and saved["evaluation_scope"] == "classroom" and saved["evaluation_kind"] == "course"
    text = json.dumps(saved, ensure_ascii=False)
    assert "ability_score" not in text and "student_score" not in text
    with flow.env.records._connect() as db:
        stored = json.loads(db.execute("SELECT payload_json FROM demo2_classroom_evaluations WHERE record_id='course-eval-1'")
                            .fetchone()["payload_json"])
    assert stored == saved

    # Fresh: not stale; then a measurement changes → stale flag, scores untouched.
    record = store.workspace(flow.token)["records"][0]
    assert record["course_evaluation_stale"]["stale"] is False
    with flow.env.records._connect() as db:
        db.execute("UPDATE demo2_measurements SET version=version+1 WHERE status='active' AND record_id=(SELECT MIN(record_id) "
                   "FROM demo2_measurements WHERE status='active')")
    record = store.workspace(flow.token)["records"][0]
    assert record["course_evaluation_stale"]["stale"] is True
    assert record["course_evaluation_stale"]["notice"] == "依据数据已变化，建议重新核对"
    assert record["result"] == saved["result"]
    # Saving with the old fingerprint is refused, not silently rescored.
    with pytest.raises(MeasurementError) as error:
        store.save(flow.token, dict(p, expected_version=1))
    assert error.value.status == 409 and error.value.code == "suggestion_basis_changed"

    # Other school → 403; no session → 401.
    with pytest.raises(MeasurementError) as error:
        store.course_suggestions(flow.env.tokens["b"], flow.video.task_id)
    assert error.value.status == 403
    with pytest.raises(MeasurementError) as error:
        store.course_suggestions("not-a-session", flow.video.task_id)
    assert error.value.status == 401

    lines = _lines(logs)
    operations = {line["operation"] for line in lines}
    assert {"course_eval_suggest", "course_eval_decision", "course_eval_save", "course_eval_lock",
            "course_eval_basis_stale"} <= operations
    for line in lines:
        assert line["ts"]
        assert "课堂中该环节明显超时" not in json.dumps(line, ensure_ascii=False)
        assert "虚构同名学生" not in json.dumps(line, ensure_ascii=False)
    save_line = next(line for line in lines if line["operation"] == "course_eval_save")
    assert save_line["evaluation_short"] == "course-e" and save_line["item_count"] == 10
    assert save_line["task_short"] == flow.video.task_id[:8]


def test_category_summary_matches_result():
    from rehab_affect.classroom_rubric import evaluate
    result = evaluate(evaluation_payload())
    cats = category_summary(result)
    assert [c["label"] for c in cats] == ["目标适配与分层要求", "内容设计与教学组织", "过程支持与目标达成", "教师表达与响应调节"]
    assert all(c["school_score"] == 8 and c["system_score"] == 7 and c["gap"] == -1 for c in cats)


def test_legacy_evaluation_without_suggestions_is_unchanged(flow):
    store = Demo2EvaluationStore(flow.env.records)
    saved = store.save(flow.token, evaluation_payload(record_id="legacy-1"))
    assert "course_evaluation" not in saved and "evaluation_kind" not in saved
    with sqlite3.connect(flow.env.records.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM demo2_classroom_evaluations").fetchone()[0] == 1
