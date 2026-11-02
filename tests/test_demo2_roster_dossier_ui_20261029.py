"""Roster / dossier / course-dossier humanized UI contracts and their debug logging."""

from __future__ import annotations

import json

import pytest

from rehab_affect.demo2_dossier import render_student, render_task
from rehab_affect.demo2_dossier_store import debug_event, short_code
from rehab_affect.demo2_identity import render_students
from rehab_affect.demo2_identity_store import IdentityError

TEACHER = {"role": "school_uploader", "username": "t1"}


def test_roster_has_search_duplicate_badge_drawer_and_toast():
    html = render_students(TEACHER)
    for marker in ('id="rosterSearch"', 'id="openCreateDrawer"', "+ 新建学生", 'id="createDrawer"', 'role="dialog"',
                   "同名", "rx-avatar", "RxUI.toast", "is-new", "[s.display_name,s.student_code,s.class_name]"):
        assert marker in html, marker


def test_dossier_page_merges_warnings_and_shows_counts_and_countdown():
    html = render_student(TEACHER)
    for marker in ('id="reminderCard"', "查看完整说明", 'id="countDocuments"', 'id="countAuthorization"',
                   'id="countReferences"', "rx-tabs", "还有 '+days+' 天到期", "days<=soonDays?' soon'",
                   "基本信息", "保存与期限", 'id="documentForm" novalidate', "documentFieldError", "资料来源最多 200 字"):
        assert marker in html, marker
    assert "'学生 ID '+student.student_id" not in html


def test_course_dossier_has_three_steps_and_identity_empty_state():
    html = render_task(TEACHER)
    for marker in ('id="referenceSteps"', "选择已确认学生", "选择资料版本", "确认保存", 'id="noStudentState"',
                   "请先到身份确认页确认画面中的学生", "/demo2/identity?task_id=", 'class="policy-note"', "<details"):
        assert marker in html, marker


def test_debug_event_adds_short_codes_without_free_text(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_DOSSIER_DEBUG_LOG_DIR", str(tmp_path))
    entry = debug_event(None, "document_delete", "ok", student_id="s-1", document_id="c51f899c5dcd43319445891bbf818ab5",
                        source_ref="虚构来源", display_name="虚构学生")
    assert entry["document_short"] == "c51f899c" == short_code(entry["document_id"])
    assert "source_ref" not in entry and "display_name" not in entry
    line = next(tmp_path.glob("dossier_debug_*.jsonl")).read_text(encoding="utf-8")
    assert "虚构" not in line and json.loads(line)["ts"]


def test_student_create_writes_name_free_debug_lines(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from rehab_affect.demo2_identity_store import Demo2IdentityStore

    monkeypatch.setenv("REHAB_DEMO2_DOSSIER_DEBUG_LOG_DIR", str(tmp_path))
    store = Demo2IdentityStore.__new__(Demo2IdentityStore)
    store.record_store = SimpleNamespace(upload_dir=tmp_path / "uploads")
    monkeypatch.setattr(store, "_create_student", lambda token, payload: {"student_id": "stu-0001", "display_name": payload["display_name"]})
    assert store.create_student("tok", {"display_name": "虚构同名学生"})["student_id"] == "stu-0001"

    def reject(token, payload):
        raise IdentityError(409, "student_code_conflict", "当前名册的同一班级已存在此学生编号")

    monkeypatch.setattr(store, "_create_student", reject)
    with pytest.raises(IdentityError):
        store.create_student("tok", {"display_name": "虚构同名学生"})
    lines = [json.loads(line) for line in next(tmp_path.glob("dossier_debug_*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [(e["operation"], e["result"]) for e in lines] == [("student_create", "created"), ("student_create", "rejected")]
    assert lines[0]["student_id"] == "stu-0001" and lines[1]["code"] == "student_code_conflict" and lines[1]["http_status"] == 409
    assert "虚构" not in json.dumps(lines, ensure_ascii=False)
