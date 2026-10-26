"""Synthetic acceptance for scripts/verify_id_chain.py (stable ID chain).

school_id -> student_id -> iep_document_id -> course_id -> video_task_id
-> evaluation_id -> report_id must be traceable from a report or a task,
breaks must exit non-zero at the right level, ambiguous IEPs must not be
picked, and every step must be logged with a timestamp.
"""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from rehab_affect.demo2_report_store import Demo2ReportStore
from rehab_affect.evaluation_report_contract import school_id_from_context
from test_demo2_dossier_store import document, env, template  # noqa: F401  (fixtures)
from test_demo2_iep_report_integration import prepared

LEVELS = ("school_id", "student_id", "iep_document_id", "course_id",
          "video_task_id", "evaluation_id", "report_id")

_SPEC = importlib.util.spec_from_file_location(
    "verify_id_chain", Path(__file__).resolve().parents[1] / "scripts" / "verify_id_chain.py")
verify_id_chain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify_id_chain)


@pytest.fixture
def chain(env):
    video, auth, doc, ref, measurements, _, evaluations, _, evaluation = prepared(env)
    work = measurements.course_workspace(env.tokens["a"], video.task_id)
    meta = Demo2ReportStore(env.records).save_from_workspace(env.tokens["a"], work)
    return dict(video=video, auth=auth, doc=doc, ref=ref, evaluation=evaluation, report=meta,
                student_id=env.pupils["a1"]["student_id"], name=env.pupils["a1"]["display_name"])


def run(env, capsys, *args):
    log = env.tmp / "chain-logs" / "verify.jsonl"
    code = verify_id_chain.main(["--db", str(env.records.db_path), "--json", "--quiet",
                                 "--log-file", str(log), *args])
    out = json.loads(capsys.readouterr().out)
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    return code, out, entries


def _db_digest(env):
    with sqlite3.connect(env.records.db_path) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode("utf-8")).hexdigest()


def _task_school_id(env, task_id):
    with env.records._connect() as db:
        raw = db.execute("SELECT school_context_json FROM video_analysis_tasks WHERE task_id=?", (task_id,)).fetchone()[0]
    return school_id_from_context(json.loads(raw))


def test_report_id_traces_complete_seven_level_chain(env, chain, capsys):
    before = _db_digest(env)
    code, out, logs = run(env, capsys, "--report-id", chain["report"]["report_id"])
    assert code == 0 and out["final_status"] == "complete" and out["exit_code"] == 0
    result = out["results"][0]
    assert result["errors"] == [] and result["first_broken_level"] is None
    for level in LEVELS:
        info = result["levels"][level]
        assert info["status"] == "ok", level
        assert info["entries"] and all(entry["exists"] for entry in info["entries"]), level
    ids = result["chain"]
    assert ids["school_id"] == [_task_school_id(env, chain["video"].task_id)]
    assert ids["school_id"][0].startswith("school-")
    assert ids["student_id"] == [chain["student_id"]]
    assert ids["iep_document_id"] == [chain["doc"]["document_id"]]
    assert ids["course_id"] == ["dossier-course"]
    assert ids["video_task_id"] == [chain["video"].task_id]
    assert ids["evaluation_id"] == chain["report"]["evaluation_ids"] == [chain["evaluation"]["evaluation_id"]]
    assert ids["report_id"] == [chain["report"]["report_id"]]
    # Strictly read-only.
    assert _db_digest(env) == before

    # Detailed log: timestamps, start ID, each level query, final status; IDs only, never names.
    assert all(entry["ts"] and entry["run_id"] for entry in logs)
    start = next(entry for entry in logs if entry["step"] == "trace_start")
    assert start["start_id"] == chain["report"]["report_id"] and start["start_kind"] == "report_id"
    assert {entry["level"] for entry in logs if entry["step"] == "level_query"} == set(LEVELS)
    final = next(entry for entry in logs if entry["step"] == "run_end")
    assert final["result"] == "complete" and final["exit_code"] == 0 and "elapsed_ms" in final
    assert chain["name"] not in json.dumps(logs, ensure_ascii=False)


def test_video_task_id_traces_forward_to_report(env, chain, capsys):
    code, out, logs = run(env, capsys, "--video-task-id", chain["video"].task_id, "--scan-orphans")
    assert code == 0 and out["final_status"] == "complete" and out["orphans"] == []
    result = out["results"][0]
    assert result["start"] == {"kind": "video_task_id", "id": chain["video"].task_id,
                               "report_id": chain["report"]["report_id"]}
    assert result["chain"]["report_id"] == [chain["report"]["report_id"]]
    assert any(entry["step"] == "orphan_scan" for entry in logs)


def test_task_without_report_breaks_at_report_level(env, capsys):
    video, *_ = prepared(env)
    code, out, logs = run(env, capsys, "--video-task-id", video.task_id)
    assert code == 1
    result = out["results"][0]
    assert result["first_broken_level"] == "report_id"
    assert [error["code"] for error in result["errors"]] == ["report_missing"]
    assert any(entry["step"] == "chain_break" and entry["level"] == "report_id" for entry in logs)


@pytest.mark.parametrize("tamper, level, code_name", [
    ("evaluation_dangling_task", "evaluation_id", "evaluation_task_dangling"),
    ("evaluation_deleted", "evaluation_id", "evaluation_missing"),
    ("evaluation_other_course", "course_id", "evaluation_course_mismatch"),
    ("report_dangling_task", "video_task_id", "task_missing"),
    ("report_course_changed", "course_id", "course_mismatch"),
    ("report_unknown_student", "student_id", "student_missing"),
    ("student_name_as_key", "student_id", "name_join"),
    ("reference_document_deleted", "iep_document_id", "reference_document_orphan"),
    ("task_without_school", "school_id", "school_missing"),
])
def test_tampered_link_exits_non_zero_and_names_the_break(env, chain, capsys, tamper, level, code_name):
    report_id = chain["report"]["report_id"]
    record_id = chain["evaluation"]["record_id"]
    with sqlite3.connect(env.records.db_path) as db:
        db.execute("PRAGMA foreign_keys = OFF")
        if tamper == "evaluation_dangling_task":
            db.execute("UPDATE demo2_classroom_evaluations SET payload_json=json_set(payload_json,'$.task_id','task-does-not-exist') "
                       "WHERE record_id=?", (record_id,))
        elif tamper == "evaluation_deleted":
            db.execute("DELETE FROM demo2_classroom_evaluations WHERE record_id=?", (record_id,))
        elif tamper == "evaluation_other_course":
            db.execute("UPDATE demo2_classroom_evaluations SET payload_json=json_set(payload_json,'$.course_id','other-course') "
                       "WHERE record_id=?", (record_id,))
        elif tamper == "report_dangling_task":
            db.execute("UPDATE demo2_reports SET task_id='task-does-not-exist' WHERE report_id=?", (report_id,))
        elif tamper == "report_course_changed":
            db.execute("UPDATE demo2_reports SET course_id='other-course' WHERE report_id=?", (report_id,))
        elif tamper == "report_unknown_student":
            db.execute("UPDATE demo2_reports SET student_ids_json=? WHERE report_id=?", (json.dumps(["student-ghost"]), report_id))
        elif tamper == "student_name_as_key":
            db.execute("UPDATE demo2_reports SET student_ids_json=? WHERE report_id=?",
                       (json.dumps([chain["name"]], ensure_ascii=False), report_id))
        elif tamper == "reference_document_deleted":
            db.execute("UPDATE demo2_dossier_reference_documents SET document_id='doc-ghost' WHERE reference_id=?",
                       (chain["ref"]["reference_id"],))
        elif tamper == "task_without_school":
            db.execute("UPDATE video_analysis_tasks SET school_context_json='{}' WHERE task_id=?", (chain["video"].task_id,))
    code, out, logs = run(env, capsys, "--report-id", report_id)
    assert code == 1 and out["final_status"] == "broken"
    result = out["results"][0]
    assert any(error["level"] == level and error["code"] == code_name for error in result["errors"]), result["errors"]
    assert result["levels"][level]["status"] == "broken"
    assert result["first_broken_level"] is not None
    breaks = [entry for entry in logs if entry["step"] == "chain_break"]
    assert any(entry["result"] == code_name and entry["level"] == level and entry["reason"] for entry in breaks)
    assert next(entry for entry in logs if entry["step"] == "run_end")["exit_code"] == 1
    assert chain["name"] not in json.dumps(logs, ensure_ascii=False)


def test_orphan_scan_reports_dangling_evaluation(env, chain, capsys):
    with sqlite3.connect(env.records.db_path) as db:
        db.execute("UPDATE demo2_classroom_evaluations SET payload_json=json_set(payload_json,'$.task_id','task-gone') "
                   "WHERE record_id=?", (chain["evaluation"]["record_id"],))
    code, out, _ = run(env, capsys, "--video-task-id", chain["video"].task_id, "--scan-orphans")
    assert code == 1
    assert any(item["code"] == "evaluation_task_dangling" and item["target"] == "task-gone" for item in out["orphans"])


def test_multiple_current_iep_is_reported_ambiguous_not_picked(env, chain, capsys):
    second = document(env, authorization=chain["auth"], filename="", content_base64="")
    assert second["document_id"] != chain["doc"]["document_id"]
    code, out, logs = run(env, capsys, "--report-id", chain["report"]["report_id"])
    assert code == 3 and out["final_status"] == "ambiguous"
    result = out["results"][0]
    info = result["levels"]["iep_document_id"]
    assert info["status"] == "ambiguous"
    assert result["chain"]["iep_document_id"] == ["ambiguous"]
    entry = info["entries"][0]
    assert entry["student_id"] == chain["student_id"]
    assert sorted(entry["candidates"]) == sorted([chain["doc"]["document_id"], second["document_id"]])
    assert result["errors"] == []
    assert any(item["code"] == "multiple_current_iep" for item in info["problems"])
    assert any(e["step"] == "level_query" and e["level"] == "iep_document_id" and e["result"] == "ambiguous" for e in logs)


def test_missing_iep_is_not_linked_unless_required(env, chain, capsys):
    with sqlite3.connect(env.records.db_path) as db:
        db.execute("UPDATE demo2_dossier_references SET withdrawn_at='2026-01-01T00:00:00+08:00' WHERE reference_id=?",
                   (chain["ref"]["reference_id"],))
        db.execute("UPDATE demo2_classroom_evaluations SET payload_json=json_set(payload_json,'$.iep_summary_id','') "
                   "WHERE record_id=?", (chain["evaluation"]["record_id"],))
    code, out, _ = run(env, capsys, "--report-id", chain["report"]["report_id"])
    assert code == 0 and out["final_status"] == "complete_without_iep"
    assert out["results"][0]["levels"]["iep_document_id"]["status"] == "not_linked"
    code, out, _ = run(env, capsys, "--report-id", chain["report"]["report_id"], "--require-iep")
    assert code == 1 and out["results"][0]["first_broken_level"] == "iep_document_id"


def test_usage_errors_exit_two(env, capsys, tmp_path):
    code = verify_id_chain.main(["--db", str(tmp_path / "missing.sqlite3"), "--report-id", "x", "--no-log-file", "--quiet"])
    assert code == 2
    capsys.readouterr()


def test_api_outputs_carry_upstream_ids_not_names(env, chain):
    school_id = _task_school_id(env, chain["video"].task_id)
    evaluation = chain["evaluation"]
    assert evaluation["school_id"] == school_id
    assert evaluation["video_task_id"] == evaluation["task_id"] == chain["video"].task_id
    assert evaluation["course_id"] == "dossier-course"
    assert evaluation["iep_document_id"] == evaluation["iep_summary_id"] == chain["doc"]["document_id"]
    assert evaluation["evaluation_id"] == f"evaluation-{evaluation['record_id']}"

    reference = env.store.task_workspace(env.tokens["a"], chain["video"].task_id)["references"][0]
    assert reference["school_id"] == school_id
    assert reference["student_id"] == chain["student_id"]
    assert reference["video_task_id"] == chain["video"].task_id
    assert reference["course_id"] == "dossier-course"
    assert reference["iep_document_id"] == chain["doc"]["document_id"]
    exported = env.store.reference_export(env.tokens["a"], reference["reference_id"])
    assert exported["school_id"] == school_id and exported["iep_document_id"] == chain["doc"]["document_id"]

    store = Demo2ReportStore(env.records)
    meta = chain["report"]
    assert meta["school_id"] == school_id
    assert meta["student_ids"] == [chain["student_id"]]
    assert meta["video_task_id"] == chain["video"].task_id and meta["course_id"] == "dossier-course"
    assert meta["evaluation_ids"] == [evaluation["evaluation_id"]]
    teacher = store.get(env.tokens["a"], meta["report_id"])
    assert teacher["iep_document_ids"] == [chain["doc"]["document_id"]]
    admin = store.get(env.tokens["admin"], meta["report_id"])
    assert "iep_document_ids" not in admin and "iep_links" not in admin["payload"]["report"]
    assert admin["school_id"] == school_id and admin["student_ids"] == [chain["student_id"]]
    downloaded = json.loads(store.download(env.tokens["admin"], meta["report_id"], fmt="json")[0])
    assert downloaded["school_id"] == school_id and downloaded["video_task_id"] == chain["video"].task_id

    # No output uses the student's display name as a join key.
    for value in (evaluation, reference, meta):
        for key in ("school_id", "student_id", "student_ids", "course_id", "task_id", "video_task_id",
                    "evaluation_id", "evaluation_ids", "iep_document_id", "report_id"):
            if key in value:
                assert chain["name"] not in json.dumps(value[key], ensure_ascii=False), key
