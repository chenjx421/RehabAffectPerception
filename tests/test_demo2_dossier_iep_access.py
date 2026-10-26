"""IEP/professional separation, ambiguity, access reasons and debug logs (synthetic only)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from rehab_affect import demo2_dossier_store as module
from rehab_affect.demo2_dossier_store import SUMMARY_FIELDS
from rehab_affect.demo2_iep_context import attach_iep_context
from rehab_affect.demo2_measurement_store import MeasurementError
from test_demo2_dossier_store import (SECRET, assert_error, authorize, day, document, document_payload, env,  # noqa: F401
                                      query, reference, task, template)
from test_demo2_iep_report_integration import prepared


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    folder = tmp_path / "debug_logs"
    monkeypatch.setenv(module.DEBUG_LOG_DIR_ENV, str(folder))
    return folder


def summary_only(**changes):
    return {"filename": "", "content_base64": "", **changes}


def log_entries(folder):
    return [json.loads(line) for path in sorted(folder.glob("dossier_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_retention_after_authorization_deadline_is_rejected_in_chinese(env):
    auth = authorize(env, valid_until=day(10))
    error = assert_error(400, "retention_after_authorization", env.store.create_document, env.tokens["a"],
                         document_payload(auth, retain_until=day(11)))
    assert auth["valid_until"] in error.message and "不得晚于授权截止日" in error.message
    assert query(env, "SELECT * FROM demo2_dossier_documents") == []
    accepted = env.store.create_document(env.tokens["a"], document_payload(auth, retain_until=day(10)))
    assert accepted["retain_until"] == auth["valid_until"]


def test_new_version_keeps_old_version_and_historical_reference(env):
    auth = authorize(env)
    first = document(env, authorization=auth, **summary_only())
    video = task(env)
    old_reference = reference(env, video, [first])
    second = env.store.create_document(env.tokens["a"], document_payload(auth, supersedes_id=first["document_id"],
        summary={key: "VERSION-TWO" for key in SUMMARY_FIELDS}, **summary_only()))
    assert second["version"] == 2 and second["family_id"] == first["family_id"] and second["supersedes_id"] == first["document_id"]
    workspace = env.store.student_workspace(env.tokens["a"], env.pupils["a1"]["student_id"])
    assert {doc["document_id"] for doc in workspace["documents"]} == {first["document_id"], second["document_id"]}
    saved = env.store.reference_export(env.tokens["a"], old_reference["reference_id"])
    assert saved["document_versions"] == [{"document_id": first["document_id"], "version": 1}]
    assert "VERSION-TWO" not in json.dumps(saved, ensure_ascii=False)
    env.store.delete_document(env.tokens["a"], {"student_id": env.pupils["a1"]["student_id"],
                                                "document_id": first["document_id"], "confirmed": True})
    after = env.store.student_workspace(env.tokens["a"], env.pupils["a1"]["student_id"])
    deleted = next(doc for doc in after["documents"] if doc["document_id"] == first["document_id"])
    assert deleted["available"] is False and deleted["summary"] == {} and deleted["source_ref"] == "" and deleted["filename"] == ""
    assert env.store.reference_export(env.tokens["a"], old_reference["reference_id"])["document_versions"][0]["document_id"] == first["document_id"]


def test_iep_context_only_reads_iep_documents(env):
    auth = authorize(env)
    professional = document(env, authorization=auth, document_type="professional_assessment",
                            summary={key: "PROFESSIONAL-ONLY" for key in SUMMARY_FIELDS}, **summary_only())
    student_id = env.pupils["a1"]["student_id"]
    empty = env.store.iep_context(env.tokens["a"], student_id)
    assert empty["status"] == "not_found" and empty["iep"] is None
    assert "PROFESSIONAL-ONLY" not in json.dumps(empty, ensure_ascii=False)
    iep = document(env, authorization=auth, **summary_only())
    context = env.store.iep_context(env.tokens["a"], student_id)
    assert context["status"] == "available" and context["iep_document_id"] == iep["document_id"]
    assert context["iep"]["document_type"] == "iep"
    assert professional["document_id"] not in json.dumps(context) and "PROFESSIONAL-ONLY" not in json.dumps(context, ensure_ascii=False)


def test_iep_successor_version_is_not_ambiguous(env):
    auth = authorize(env)
    first = document(env, authorization=auth, **summary_only())
    second = env.store.create_document(env.tokens["a"], document_payload(auth, supersedes_id=first["document_id"], **summary_only()))
    context = env.store.iep_context(env.tokens["a"], env.pupils["a1"]["student_id"])
    assert context["status"] == "available" and context["iep_document_id"] == second["document_id"] and context["iep"]["version"] == 2


def test_two_current_ieps_are_ambiguous_without_silent_pick(env):
    auth = authorize(env)
    first = document(env, authorization=auth, **summary_only())
    second = document(env, authorization=auth, **summary_only())
    context = env.store.iep_context(env.tokens["a"], env.pupils["a1"]["student_id"])
    assert context["status"] == "ambiguous" and context["reason"] == "multiple_current_iep"
    assert context["iep"] is None and context["iep_document_id"] == ""
    assert {item["document_id"] for item in context["candidates"]} == {first["document_id"], second["document_id"]}
    assert SECRET not in json.dumps(context, ensure_ascii=False)
    env.store.delete_document(env.tokens["a"], {"student_id": env.pupils["a1"]["student_id"],
                                                "document_id": first["document_id"], "confirmed": True})
    resolved = env.store.iep_context(env.tokens["a"], env.pupils["a1"]["student_id"])
    assert resolved["status"] == "available" and resolved["iep_document_id"] == second["document_id"]


def test_analysis_context_is_ambiguous_when_one_reference_holds_two_ieps(env):
    auth = authorize(env)
    first = document(env, authorization=auth, **summary_only())
    second = document(env, authorization=auth, **summary_only())
    professional = document(env, authorization=auth, document_type="professional_assessment", **summary_only())
    video = task(env)
    reference(env, video, [first, second, professional])
    workspace = {"task_id": video.task_id, "people": [{"student_id": env.pupils["a1"]["student_id"], "display_name": "虚构同名学生"}],
                 "report": {"sections": [], "character_count": 0}}
    attach_iep_context(env.records, env.tokens["a"], workspace)
    person = workspace["people"][0]
    assert workspace["iep_status"] == "ambiguous"
    assert person["iep_context"]["status"] == "ambiguous" and person["iep_summary_id"] == ""
    assert person["iep_context"]["documents"] == []
    assert SECRET not in json.dumps(workspace, ensure_ascii=False)


def test_professional_material_never_fills_the_iep_field_in_analysis(env):
    auth = authorize(env)
    professional = document(env, authorization=auth, document_type="professional_assessment", **summary_only())
    video = task(env)
    reference(env, video, [professional])
    workspace = {"task_id": video.task_id, "people": [{"student_id": env.pupils["a1"]["student_id"], "display_name": "虚构同名学生"}],
                 "report": {"sections": [], "character_count": 0}}
    attach_iep_context(env.records, env.tokens["a"], workspace)
    person = workspace["people"][0]
    assert person["iep_context"]["status"] == "no_iep_summary" and person["iep_summary_id"] == ""
    assert professional["document_id"] not in json.dumps(person["iep_context"])


@pytest.mark.parametrize("change,reason,word", [("withdraw", "authorization_withdrawn", "撤回"),
                                                ("expiry", "authorization_expired", "到期")])
def test_withdrawn_or_expired_material_is_unavailable_for_analysis_and_scoring(env, monkeypatch, change, reason, word):
    video, auth, doc, _, measurements, _, evaluations, evaluation_payload, _ = prepared(env)
    student_id = env.pupils["a1"]["student_id"]
    for purpose in ("analysis", "scoring"):
        assert env.store.material_access(env.tokens["a"], student_id, purpose)["available"] is True
    if change == "withdraw":
        env.store.withdraw_authorization(env.tokens["a"], {"student_id": student_id, "authorization_id": auth["authorization_id"], "confirmed": True})
    else:
        later = module._today() + timedelta(days=31)
        monkeypatch.setattr(module, "_today", lambda: later)
    for purpose in ("analysis", "scoring"):
        state = env.store.material_access(env.tokens["a"], student_id, purpose)
        assert state["available"] is False and state["reason"] == reason and word in state["message"]
    context = env.store.iep_context(env.tokens["a"], student_id)
    assert context["status"] == "unavailable" and context["reason"] == reason and context["iep"] is None
    work = measurements.course_workspace(env.tokens["a"], video.task_id)
    person = work["people"][0]
    assert person["iep_context"]["documents"] == [] and not person.get("iep_summary_id")
    assert person["iep_context"]["reason"] in {reason, "document_withdrawn", "document_expired"}
    assert word in person["iep_context"]["message"]
    assert SECRET not in json.dumps(work, ensure_ascii=False)
    with pytest.raises(MeasurementError) as error:
        evaluations.preview(env.tokens["a"], {**evaluation_payload, "expected_version": 1})
    assert error.value.code == "iep_link_unavailable" and word in error.value.message


def test_material_access_rejects_unknown_purpose(env):
    assert_error(400, "invalid_purpose", env.store.material_access, env.tokens["a"], env.pupils["a1"]["student_id"], "training")


def test_debug_log_covers_lifecycle_without_sensitive_content(env, log_dir, monkeypatch):
    student_id = env.pupils["a1"]["student_id"]
    auth = authorize(env, valid_until=day(10))
    assert_error(400, "retention_after_authorization", env.store.create_document, env.tokens["a"],
                 document_payload(auth, retain_until=day(11)))
    first = document(env, authorization=auth, retain_until=day(5))
    second = env.store.create_document(env.tokens["a"], document_payload(auth, supersedes_id=first["document_id"], retain_until=day(5)))
    env.store.delete_document(env.tokens["a"], {"student_id": student_id, "document_id": second["document_id"], "confirmed": True})
    env.store.iep_context(env.tokens["a"], student_id)
    env.store.material_access(env.tokens["a"], student_id, "scoring")
    later = module._today() + timedelta(days=6)
    monkeypatch.setattr(module, "_today", lambda: later)
    env.store.cleanup_expired()
    other = authorize(env, pupil="a2")
    env.store.withdraw_authorization(env.tokens["a"], {"student_id": env.pupils["a2"]["student_id"],
                                                       "authorization_id": other["authorization_id"], "confirmed": True})
    entries = log_entries(log_dir)
    operations = {entry["operation"] for entry in entries}
    assert {"authorization_save", "document_create", "document_version_create", "document_delete", "iep_context_query",
            "material_access_check", "document_expiry_check", "authorization_withdraw"} <= operations
    for entry in entries:
        assert entry["ts"] and entry["operation"] and entry["result"]
    created = next(entry for entry in entries if entry["operation"] == "document_create" and entry["result"] == "ok")
    assert created["student_id"] == student_id and created["document_id"] == first["document_id"] and created["document_type"] == "iep"
    version = next(entry for entry in entries if entry["operation"] == "document_version_create")
    assert version["supersedes_id"] == first["document_id"] and version["version"] == 2
    rejected = next(entry for entry in entries if entry["result"] == "rejected")
    assert rejected["code"] == "retention_after_authorization" and rejected["student_id"] == student_id
    deleted = next(entry for entry in entries if entry["operation"] == "document_delete")
    assert deleted["document_id"] == second["document_id"] and deleted["document_type"] == "iep" and deleted["status"] in {"deleted", "deletion_pending"}
    expired = [entry for entry in entries if entry["operation"] == "document_expiry_check"]
    assert any(entry["document_id"] == first["document_id"] and entry["result"] == "expired" and entry["document_type"] == "iep" for entry in expired)
    withdrawn = next(entry for entry in entries if entry["operation"] == "authorization_withdraw")
    assert withdrawn["result"] == "ok" and withdrawn["status"] == "withdrawn"
    raw = "\n".join(path.read_text(encoding="utf-8") for path in log_dir.glob("*.jsonl"))
    for secret in (SECRET, "虚构同名学生", "测试班", "-authorization", "-source"):
        assert secret not in raw
