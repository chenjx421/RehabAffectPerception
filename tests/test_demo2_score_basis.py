"""Subtask 76: score rubric detail and per-score basis (measurement + dual-track system score)."""
from __future__ import annotations

from datetime import date
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from rehab_affect.assessment_rubric import (
    ANCHOR_LEVELS,
    RUBRIC_DETAIL_VERSION,
    RUBRIC_VERSION,
    anchor_level,
    build_assessment_summary,
    rubric_contract,
)
from rehab_affect.classroom_rubric import evaluate
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_measurement import render_measurement
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore, MeasurementError
from rehab_affect.score_basis import (
    NOT_SCORED_LABEL,
    evaluation_basis_sentence,
    evaluation_rubric_detail,
    evaluation_score_basis,
    measurement_basis_sentence,
    measurement_score_basis,
    redact_for_admin,
    rubric_appendix_text,
)
from rehab_affect.student_record_store import Demo2StudentRecordStore

# Synthetic dual-track lesson whose results were verified on the page before this change:
# school raw 79.0 / 7.90 / 55.3, system 7.54, deltas −0.10 / −0.26 / −0.36.
SCHOOL = [8, 8, 8, 8, 8, 8, 8, 7, 8, 8]
SYSTEM = [6, 7, 6, 8, 9, 8, 9, 7, 9, 9]
STUDENT_NAME = "虚构依据学生"


def _items(system=SYSTEM, evidence=True):
    return [dict(id=f"i{k + 1}", school_score=SCHOOL[k], enhanced_score=system[k],
                 evidence=f"合成观察 0{k}:20 学生回应" if evidence else "",
                 reason="合成复核原因" if system[k] != SCHOOL[k] else "", suggestion="")
            for k in range(10)]


def _evaluation_payload(**changes):
    payload = dict(record_id="basis-eval-1", expected_version=0, lesson_id="basis-lesson-1",
                   lesson_date=date.today().isoformat(), course_name="合成数学课 · 依据验收", subject_id="math",
                   template_id="basic_100", goal_context="合成目标：实物分类，允许指认回应。",
                   school_source="teacher_recorded", school_rater="合成评课人", reviewed=True,
                   items=_items(), weight_policy="common")
    payload.update(changes)
    return payload


# ------------------------------------------------------------------ contract

def test_rubric_contract_has_six_anchors_evidence_sources_and_not_scored_per_dimension():
    contract = rubric_contract()
    assert contract["rubric_version"] == RUBRIC_VERSION
    assert contract["detail_version"] == RUBRIC_DETAIL_VERSION
    assert len(contract["dimensions"]) == 4
    for dim in contract["dimensions"]:
        assert [a["level"] for a in dim["anchors"]] == [10, 8, 6, 4, 2, 0]
        assert all(a["text"] for a in dim["anchors"])
        assert dim["evidence"] and dim["not_scored"]
        assert {s["key"] for s in dim["data_sources"]} <= {"video", "teacher_observation", "course_goal", "iep"}
    independence = next(d for d in contract["dimensions"] if d["key"] == "independence")
    texts = {a["level"]: a["text"] for a in independence["anchors"]}
    assert "完全独立" in texts[10] and "手势" in texts[8] and "口语" in texts[6]
    assert "示范" in texts[4] and "部分肢体" in texts[2] and "全程" in texts[0]
    assert anchor_level(7.5) == 6 and anchor_level(10) == 10 and anchor_level(0) == 0 and anchor_level(None) is None


def test_measurement_page_renders_detail_tab_and_basis_drawer():
    html = render_measurement({"role": "school_uploader", "username": "t1"})
    assert "rubricDetailHtml" in html and 'id="stdAnchors"' in html and "printRubricBtn" in html
    assert RUBRIC_DETAIL_VERSION in html and "window.ScoreBasis" in html
    assert "/measurements/score-basis" in html and "basisBtn(" in html
    assert html.count("<script") == html.count("</script>") == 2


def test_evaluation_page_shows_ten_items_with_level_anchors():
    detail = evaluation_rubric_detail()
    assert len(detail["items"]) == 10
    for item in detail["items"]:
        assert [a["level"] for a in item["anchors"]] == list(ANCHOR_LEVELS)
        assert item["evidence"] and item["check_point"]
    html = render_evaluation({"username": "school_uploader_01", "login_alias": "t1"})
    assert 'id="tabBasis"' in html and 'id="panelBasis"' in html and "EVAL_RUBRIC_DETAIL" in html
    assert "renderEvalRubricDetail" in html and detail["detail_version"] in html
    ids = re.findall(r'\bid="([^"$]+)"', html)
    assert len(ids) == len(set(ids))


# --------------------------------------------------------- measurement basis

@pytest.fixture()
def menv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "BasisTest-")
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("REHAB_DEMO2_MEASUREMENT_DEBUG_LOG_DIR", str(log_dir))
    monkeypatch.setenv("REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR", str(log_dir))
    records = Demo2StudentRecordStore(tmp_path / "basis.sqlite3", tmp_path / "documents")
    tokens = {}
    for key, user in (("t1", "school_uploader_01"), ("t2", "school_uploader_02"), ("admin", "company_admin")):
        account = records.authenticate_account(user, "BasisTest-" + user)
        tokens[key] = records.create_account_session(account)["token"]
        if key != "admin":
            records.save_account_school_context(tokens[key], {"city": "测试市", "district": "测试区",
                                                             "school_name": f"测试学校{key}"})
    store = Demo2MeasurementStore(records)
    student = store.identities.create_student(tokens["t1"], {"display_name": STUDENT_NAME})
    return SimpleNamespace(records=records, store=store, tokens=tokens, student_id=student["student_id"],
                           log_dir=log_dir, evaluations=Demo2EvaluationStore(records))


def _measurement(student_id, **overrides):
    payload = {
        "record_id": "basis-m-1", "expected_version": 0, "student_id": student_id,
        "lesson_date": "2026-09-10", "lesson_id": "lesson-basis", "course_name": "合成课程",
        "goal_id": "G-01", "measurement_context": "图卡分类", "criterion": "三次中两次独立完成",
        "scores": {"accuracy": 8, "independence": 7.5, "consistency": 6, "transfer": 5},
        "opportunities": 4, "observed": 3, "reviewed": True, "support_level": "verbal",
        "evidence": "合成观察：学生指认图卡并完成分类", "source_type": "classroom_observation",
    }
    payload.update(overrides)
    return payload


def _logs(folder: Path, prefix: str):
    lines = []
    for path in sorted(folder.glob(f"{prefix}_*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return lines


def test_saved_measurement_keeps_basis_snapshot_and_formula_equals_page_score(menv):
    saved = menv.store.save(menv.tokens["t1"], _measurement(menv.student_id))
    with menv.records._connect() as db:
        stored = json.loads(db.execute("SELECT payload_json FROM demo2_measurements").fetchone()[0])
    assert stored == saved and "score_basis" in stored
    basis = stored["score_basis"]
    assert basis["rubric_version"] == RUBRIC_VERSION and basis["status"] == "scored"
    assert saved["assessment"]["score"] == 7.0
    assert basis["overall"]["score"] == 7.0 and basis["overall"]["matches_page"] is True
    contributions = {d["key"]: d["contribution"] for d in basis["dimensions"]}
    assert contributions == {"accuracy": 2.8, "independence": 2.25, "consistency": 1.2, "transfer": 0.75}
    assert round(sum(contributions.values()), 2) == saved["assessment"]["score"]
    assert [d["anchor_level"] for d in basis["dimensions"]] == [8, 6, 6, 4]
    assert basis["inputs"]["observed"] == 3 and basis["inputs"]["opportunities"] == 4
    assert basis["inputs"]["support_label"] == "口语提示"
    assert any(ref["kind"] == "course_goal" and ref["goal_id"] == "G-01" for ref in basis["evidence_refs"])

    view = menv.store.score_basis(menv.tokens["t1"], "basis-m-1")
    assert view["basis_source"] == "saved" and view["saved_matches"] is True
    assert view["formula"]["result"] == "7.00" and view["student_name"] == STUDENT_NAME
    assert "学生指认图卡" in json.dumps(view, ensure_ascii=False)
    sentence = measurement_basis_sentence(saved)
    assert "= 7.00" in sentence and "口语提示" in sentence


def test_insufficient_measurement_basis_shows_reason_and_no_score(menv):
    saved = menv.store.save(menv.tokens["t1"], _measurement(menv.student_id, observed=1,
                                                             scores={"accuracy": 8, "independence": 7,
                                                                     "consistency": 6, "transfer": None}))
    basis = saved["score_basis"]
    assert basis["status"] == "insufficient" and basis["status_label"] == NOT_SCORED_LABEL
    assert basis["overall"]["score"] is None and basis["overall"]["display"] is None
    assert any("观察次数不足" in r for r in basis["reasons"])
    transfer = next(d for d in basis["dimensions"] if d["key"] == "transfer")
    assert transfer["status"] == "not_observed" and transfer["contribution"] is None and "不填 0" in transfer["reason"]
    menv.store.score_basis(menv.tokens["t1"], "basis-m-1")
    operations = [line["operation"] for line in _logs(menv.log_dir, "measurement_debug")]
    assert "score_basis_view" in operations and "score_basis_insufficient" in operations


def test_video_segment_refs_link_to_video_time():
    scores = {"accuracy": 8, "independence": 8, "consistency": 8, "transfer": None}
    record = {"record_id": "vm-abcdef0123", "scores": scores, "observed": 4, "opportunities": 5, "reviewed": False,
              "source_type": "video", "task_id": "task-xyz", "saved_by": "system:video_archive",
              "evidence_segments": [{"start_sec": 65.4, "end_sec": 85.0, "state_label": "稳定参与"}],
              "video_metrics": {"engaged_segments": 3, "low_response_segments": 1, "away_segments": 0,
                                "not_observed_segments": 1, "engaged_ratio": 0.7, "participation_score_ref": 7.5},
              "assessment": build_assessment_summary(scores, opportunities=5, observed=4, reviewed=False)}
    basis = measurement_score_basis(record)
    video = [ref for ref in basis["evidence_refs"] if ref["kind"] == "video"]
    assert video[0]["url"] == "/demo2/video?id=task-xyz&t=65"
    assert basis["inputs"]["video"]["success_segments"] == 3
    assert basis["status"] == "insufficient" and basis["record_short"] == "abcdef01"


def test_other_school_gets_403_and_admin_view_is_redacted(menv):
    menv.store.save(menv.tokens["t1"], _measurement(menv.student_id))
    with pytest.raises(MeasurementError) as exc:
        menv.store.score_basis(menv.tokens["t2"], "basis-m-1")
    assert exc.value.status == 403 and exc.value.code == "score_basis_forbidden"
    with pytest.raises(MeasurementError) as missing:
        menv.store.score_basis(menv.tokens["t1"], "missing-record")
    assert missing.value.status == 404
    admin = menv.store.score_basis(menv.tokens["admin"], "basis-m-1")
    text = json.dumps(admin, ensure_ascii=False)
    assert admin["view"] == "admin" and admin["overall"]["score"] == 7.0
    assert STUDENT_NAME not in text and "学生指认图卡" not in text and "student_name" not in admin
    basis = measurement_score_basis({**_measurement("s"), "assessment": build_assessment_summary(
        {"accuracy": 8, "independence": 7.5, "consistency": 6, "transfer": 5}, opportunities=4, observed=3, reviewed=True),
        "iep_document_id": "doc-1234567890", "iep_support": [{"category_label": "支持方式", "text": "IEP原文要点"}]})
    teacher_iep = [r for r in basis["evidence_refs"] if r["kind"] == "iep"][0]
    teacher_iep["items"] = [{"category_label": "支持方式", "text": "IEP原文要点"}]
    redacted = json.dumps(redact_for_admin(basis), ensure_ascii=False)
    assert "IEP原文要点" not in redacted and "IEP 原文不对管理员展示" in redacted
    lines = _logs(menv.log_dir, "measurement_debug")
    denied = [l for l in lines if l["operation"] == "score_basis_view" and l["result"] == "score_basis_forbidden"]
    assert denied and denied[0]["record_id"] == "basis-m-1"
    views = [l for l in lines if l["operation"] == "score_basis_view" and l["result"] == "ok"]
    assert views and all(v["ts"] and v["record_short"] and v["rubric_version"] == RUBRIC_VERSION for v in views)
    assert "学生指认图卡" not in json.dumps(lines, ensure_ascii=False)


# ---------------------------------------------------------- evaluation basis

def test_dual_track_numbers_unchanged_and_basis_reproduces_system_score():
    data = _evaluation_payload()
    result = evaluate(data)
    assert result["school"]["raw_score"] == 79.0 and result["school"]["score_10"] == 7.9
    assert result["school"]["teaching_score_70"] == 55.3 and result["enhanced"]["score_10"] == 7.54
    comparison = result["comparison"]
    assert (comparison["evidence_delta"], comparison["weight_delta"], comparison["total_delta"]) == (-0.1, -0.26, -0.36)
    assert round(result["sensitivity"]["low"], 2) == 7.51 and round(result["sensitivity"]["high"], 2) == 7.57
    basis = evaluation_score_basis({**data, "result": result})
    assert basis["status"] == "scored" and basis["overall"]["system_score"] == 7.54
    assert basis["overall"]["formula_value"] == 7.54 and basis["overall"]["matches_page"] is True
    assert round(sum(item["contribution"] for item in basis["items"]), 4) == 7.54
    first = basis["items"][0]
    assert first["anchor_level"] == 6 and first["item_anchor_text"] and first["school_grade"] == "B"
    assert any(ref.get("url") == "/demo2/video?id=&t=20" or ref.get("text") == "00:20" for ref in first["evidence_refs"])
    assert "7.54" in evaluation_basis_sentence({**data, "result": result})


def test_missing_system_item_is_marked_not_scored_without_fake_score():
    system = list(SYSTEM)
    system[2] = None
    data = _evaluation_payload(items=_items(system), reviewed=False)
    result = evaluate(data)
    basis = evaluation_score_basis({**data, "result": result})
    item = next(i for i in basis["items"] if i["id"] == "i3")
    assert item["status"] == "not_scored" and item["status_label"] == NOT_SCORED_LABEL
    assert item["enhanced_score"] is None and item["contribution"] is None and item["reason"]
    assert basis["status"] == "insufficient" and basis["overall"]["system_score"] is None
    assert basis["insufficient_items"] == ["i3"]
    no_evidence = evaluation_score_basis({**_evaluation_payload(items=_items(evidence=False), reviewed=False),
                                          "result": evaluate(_evaluation_payload(items=_items(evidence=False),
                                                                                 reviewed=False))})
    assert {i["status"] for i in no_evidence["items"]} == {"no_evidence"}
    assert all(i["contribution"] is None for i in no_evidence["items"])


def test_saved_evaluation_payload_equals_returned_record_with_basis(menv):
    saved = menv.evaluations.save(menv.tokens["t1"], _evaluation_payload())
    assert saved["result"]["enhanced"]["score_10"] == 7.54 and saved["result"]["school"]["raw_score"] == 79.0
    with menv.records._connect() as db:
        stored = json.loads(db.execute("SELECT payload_json FROM demo2_classroom_evaluations").fetchone()[0])
    assert stored == saved and stored["score_basis"]["overall"]["system_score"] == 7.54
    view = menv.evaluations.score_basis(menv.tokens["t1"], "basis-eval-1")
    assert view["basis_source"] == "saved" and len(view["items"]) == 10
    with pytest.raises(MeasurementError) as exc:
        menv.evaluations.score_basis(menv.tokens["t2"], "basis-eval-1")
    assert exc.value.status == 403
    admin = menv.evaluations.score_basis(menv.tokens["admin"], "basis-eval-1")
    text = json.dumps(admin, ensure_ascii=False)
    assert "合成观察" not in text and "合成复核原因" not in text and admin["overall"]["system_score"] == 7.54
    lines = _logs(menv.log_dir, "evaluation_debug")
    ops = {line["operation"] for line in lines}
    assert {"score_basis_compute", "score_basis_view"} <= ops
    compute = [l for l in lines if l["operation"] == "score_basis_compute"][-1]
    assert compute["record_short"] == "basis-ev" and compute["rubric_version"] and compute["result"] == "scored"
    assert "合成观察" not in json.dumps(lines, ensure_ascii=False)


def test_report_appendix_lists_rubric_detail():
    text = rubric_appendix_text()
    assert RUBRIC_DETAIL_VERSION in text and "完全独立" in text and "i10" in text


def test_report_gets_basis_summary_and_appendix_without_changing_body_count():
    from rehab_affect.score_basis import attach_score_basis_report

    scores = {"accuracy": 8, "independence": 7.5, "consistency": 6, "transfer": 5}
    record = {**_measurement("stu-1"), "evidence_status": "current",
              "assessment": build_assessment_summary(scores, opportunities=4, observed=3, reviewed=True)}
    data = _evaluation_payload()
    evaluation = {**data, "result": evaluate(data)}
    report = {"sections": [{"title": "正文", "text": "正文内容"}], "character_count": 4}
    attach_score_basis_report({"report": report, "records": [record],
                               "people": [{"student_id": "stu-1", "display_name": STUDENT_NAME}]}, [evaluation])
    assert report["character_count"] == 4 and len(report["sections"]) == 1
    titles = [s["title"] for s in report["appendix_sections"]]
    assert titles == ["评分依据摘要", "附录：评分标准细则"]
    summary = report["appendix_sections"][0]["text"]
    assert "综合 7.00/10" in summary and "= 7.00" in summary and "7.54" in summary
