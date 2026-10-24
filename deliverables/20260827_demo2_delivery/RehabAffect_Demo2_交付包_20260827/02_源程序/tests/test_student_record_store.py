from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture()
def store(tmp_path: Path) -> Demo2StudentRecordStore:
    result = Demo2StudentRecordStore(tmp_path / "demo2.sqlite3", tmp_path / "student_documents")
    result.ensure_students(
        [
            {"student_id": "student_A", "display_name": "学生甲"},
            {"student_id": "student_B", "display_name": "学生乙"},
        ]
    )
    return result


def test_store_initializes_students_policies_and_four_channels(store: Demo2StudentRecordStore) -> None:
    summary = store.storage_summary()
    channels = store.video_channels()

    assert summary["database"]["engine"] == "SQLite 3"
    assert summary["database"]["schema_version"] == 2
    assert summary["counts"]["students"] == 2
    assert len(summary["policies"]) == 4
    raw_policy = next(policy for policy in summary["policies"] if policy["data_type"] == "raw_media")
    assert raw_policy["retention_days"] == 60
    assert raw_policy["reminder_days"] == 15
    assert [channel["channel_no"] for channel in channels["channels"]] == [1, 2, 3, 4]


def test_student_document_and_support_profile_are_persisted(store: Demo2StudentRecordStore) -> None:
    uploaded = store.save_document(
        {
            "student_id": "student_A",
            "document_type": "iep",
            "filename": "IEP摘要.txt",
            "mime_type": "text/plain",
            "content_base64": base64.b64encode("短句指令；等待六秒".encode("utf-8")).decode("ascii"),
            "source_org": "测试学校",
            "document_date": "2026-08-26",
            "note": "经授权测试资料",
        }
    )
    profile = store.save_support_profile(
        {
            "student_id": "student_A",
            "professional_conclusion": "仅记录既有专业结论",
            "support_summary": "当前目标为完成单步任务",
            "effective_support": "视觉提示与短句",
            "safety_constraints": "避免突然大声",
            "updated_by": "测试教师",
        }
    )
    record = store.student_record("student_A")

    assert uploaded["document_type_label"] == "IEP / 个别化教育计划"
    assert "短句指令" in uploaded["extracted_preview"]
    assert "file_path" not in uploaded
    assert len(record["documents"]) == 1
    assert record["support_profile"]["updated_by"] == "测试教师"
    assert profile["safety_constraints"] == "避免突然大声"

    source_path, _ = store.document_for_download(uploaded["document_id"])
    assert source_path.read_text(encoding="utf-8") == "短句指令；等待六秒"
    store.delete_document(uploaded["document_id"])
    assert not source_path.exists()
    assert store.student_record("student_A")["documents"] == []


def test_retention_policy_is_configurable_and_audited(store: Demo2StudentRecordStore) -> None:
    policy = store.update_policy(
        {
            "data_type": "raw_media",
            "retention_days": 80,
            "reminder_days": 15,
            "auto_delete": True,
        }
    )
    summary = store.storage_summary()

    assert policy["retention_days"] == 80
    assert policy["reminder_days"] == 15
    assert policy["auto_delete"] is True
    assert summary["counts"]["audit_events"] == 1
    with pytest.raises(ValueError):
        store.update_policy({"data_type": "raw_media", "retention_days": 0})


def test_video_channel_accepts_chunk_and_exposes_downloadable_precheck(store: Demo2StudentRecordStore) -> None:
    content = b"not-a-real-video-but-valid-upload-bytes"
    task = store.create_video_task(
        {
            "channel_id": "channel_1",
            "session_id": "lesson-20260826",
            "uploader_name": "一号上传主体",
            "course_id": "course_1",
            "course_name": "生活语文",
            "subject_id": "student_A",
            "filename": "classroom.mp4",
            "mime_type": "video/mp4",
            "byte_size": len(content),
            "total_chunks": 1,
        }
    )
    completed = store.append_video_chunk(
        {
            "task_id": task["task_id"],
            "chunk_index": 0,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    )

    assert completed["upload_status"] == "completed"
    assert completed["progress_percent"] == 100
    assert completed["analysis_status"] in {"precheck_complete", "uploaded_pending_worker"}
    assert completed["result_download_url"]
    result_path, filename = store.video_result_for_download(task["task_id"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert filename.endswith("上传预检结果.json")
    assert result["analysis_scope"].startswith("上传完整性")
    assert store.video_channels()["channels"][0]["tasks"][0]["task_id"] == task["task_id"]


def test_security_acceptance_allows_deidentified_result_archive(
    store: Demo2StudentRecordStore,
) -> None:
    content = b"archive-test-video"
    task = store.create_video_task(
        {
            "channel_id": "channel_2",
            "session_id": "lesson-archive",
            "uploader_name": "测试教师",
            "course_id": "course_archive",
            "course_name": "生活数学",
            "subject_id": "student_A",
            "filename": "student-name.mp4",
            "mime_type": "video/mp4",
            "byte_size": len(content),
            "total_chunks": 1,
        }
    )
    store.append_video_chunk(
        {
            "task_id": task["task_id"],
            "chunk_index": 0,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    )
    with pytest.raises(ValueError, match="尚未获得"):
        store.archive_video_result({"task_id": task["task_id"]})

    acceptance = store.record_security_acceptance(
        {
            "course_id": "course_archive",
            "course_name": "生活数学",
            "confirmed_by": "测试教师",
            "security_confirmed": True,
            "allow_company_archive": True,
        }
    )
    resource = store.archive_video_result(
        {"task_id": task["task_id"], "created_by": "测试教师"}
    )
    summary = store.storage_summary()

    assert acceptance["allow_company_archive"] is True
    assert resource["status"] == "local_approved_pending_company_sync"
    assert "不含姓名" in resource["deidentification_level"]
    assert summary["counts"]["archive_records"] == 1
    assert summary["counts"]["security_acceptances"] == 1
    assert summary["archive_records"][0]["source_id"] == task["task_id"]
