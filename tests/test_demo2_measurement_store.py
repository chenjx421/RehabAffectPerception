from __future__ import annotations

from pathlib import Path

import pytest

from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture()
def measurement_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "MeasurementTest-")
    records = Demo2StudentRecordStore(tmp_path / "measurements.sqlite3", tmp_path / "documents")
    teacher = records.authenticate_account("school_uploader_01", "MeasurementTest-school_uploader_01")
    admin = records.authenticate_account("company_admin", "MeasurementTest-company_admin")
    teacher_token = records.create_account_session(teacher)["token"]
    admin_token = records.create_account_session(admin)["token"]
    records.save_account_school_context(teacher_token, {"city": "测试市", "district": "测试区", "school_name": "测试学校"})
    store = Demo2MeasurementStore(records)
    student = store.identities.create_student(teacher_token, {"display_name": "合成学生"})
    return records, store, teacher_token, admin_token, student["student_id"]


def _payload(student_id: str, **overrides):
    payload = {
        "record_id": "measurement-1",
        "expected_version": 0,
        "student_id": student_id,
        "lesson_date": "2026-09-10",
        "lesson_id": "lesson-1",
        "course_name": "合成课程",
        "goal_id": "goal-1",
        "measurement_context": "独立完成",
        "criterion": "三次机会中至少两次独立完成",
        "scores": {"accuracy": 8, "independence": 7, "consistency": 6, "transfer": 5},
        "opportunities": 3,
        "observed": 2,
        "reviewed": True,
        "evidence": "合成观察证据",
        "source_type": "classroom_observation",
    }
    payload.update(overrides)
    return payload


def test_reviewed_complete_measurement_enters_trend_and_duplicate_is_rejected(measurement_env):
    _, store, teacher, _, student_id = measurement_env
    saved = store.save(teacher, _payload(student_id))
    assert saved["assessment"]["overall_score"] == 6.85
    assert saved["assessment"]["confidence"] is None
    workspace = store.workspace(teacher)
    assert workspace["records"][0]["record_id"] == "measurement-1"
    assert workspace["trends"][0]["series"]["lesson"][0]["score"] == 6.85
    with pytest.raises(MeasurementError) as exc:
        store.save(teacher, _payload(student_id, record_id="measurement-2"))
    assert exc.value.code == "duplicate_lesson"


def test_unreviewed_or_incomplete_measurement_has_no_formal_score(measurement_env):
    _, store, teacher, _, student_id = measurement_env
    saved = store.save(teacher, _payload(student_id, reviewed=False, observed=1, scores={"accuracy": 8, "independence": None, "consistency": None, "transfer": None}))
    assessment = saved["assessment"]
    assert assessment["overall_score"] is None
    assert assessment["provisional_score"] is None
    assert assessment["confidence"] is None
    assert store.workspace(teacher)["trends"][0]["series"]["lesson"][0]["score"] is None


def test_accounts_are_isolated_and_admin_only_sees_aggregates(measurement_env):
    _, store, teacher, admin, student_id = measurement_env
    store.save(teacher, _payload(student_id))
    summary = store.admin_summary(admin)
    assert summary["records"] == 1
    assert summary["channels"][0]["records"] == 1
    assert "student" not in str(summary).lower()
