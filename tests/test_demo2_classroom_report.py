"""Synthetic acceptance for the 千字图文课堂报告 (subtask 7).

Covers: report layout contract, >=1000 characters, stat cards equal to the
database, stable report_id/task_id/evaluation_id links, 「已过期」 on scoring
change, company-admin iep_links redaction and structured debug logs.
"""
import json

import pytest

from rehab_affect import demo2_course_page
from rehab_affect.demo2_report_store import Demo2ReportStore, ReportError
from test_demo2_dossier_store import env, template  # noqa: F401  (fixtures)
from test_demo2_iep_report_integration import prepared
from test_demo2_measurement_store import _payload


@pytest.fixture
def report_logs(tmp_path, monkeypatch):
    folder = tmp_path / "report-logs"
    monkeypatch.setenv("REHAB_DEMO2_REPORT_DEBUG_LOG_DIR", str(folder))

    def read():
        lines = []
        for path in sorted(folder.glob("report_debug_*.jsonl")):
            lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return lines
    return read


def _with_pending_record(env, video, measurements):
    """A second, unreviewed observation so 待处理记录 is non-zero."""
    measurements.save(env.tokens["a"], _payload(
        env.pupils["a1"]["student_id"], record_id="measurement-pending", goal_id="goal-pending",
        source_type="video_review", task_id=video.task_id, start_sec=0, end_sec=1,
        reviewed=False, observed=1, scores={"accuracy": 5, "independence": None,
                                            "consistency": None, "transfer": None}))


def _db_counts(env, task_id):
    with env.records._connect() as db:
        rows = [json.loads(r[0]) for r in db.execute(
            "SELECT payload_json FROM demo2_measurements WHERE status='active' "
            "AND json_extract(payload_json,'$.task_id')=?", (task_id,)).fetchall()]
    reviewed = [r for r in rows if r.get("reviewed")]
    scored = [r for r in rows if r.get("reviewed") and r.get("observed", 0) >= 2
              and all(r["scores"].get(k) is not None for k in ("accuracy", "independence", "consistency", "transfer"))]
    return {"students": len({r["student_id"] for r in rows}), "reviewed": len(reviewed),
            "scored": len(scored), "pending": len(rows) - len(reviewed)}


def test_report_body_stats_and_stable_links(env, report_logs):
    video, _, doc, _, measurements, _, _, _, evaluation = prepared(env)
    _with_pending_record(env, video, measurements)
    work = measurements.course_workspace(env.tokens["a"], video.task_id)
    report = work["report"]
    # 正文字数 = sum of section bodies, and a ready report is a 千字 report.
    assert report["ready"] is True
    assert report["character_count"] == sum(len(s["text"]) for s in report["sections"])
    assert report["character_count"] >= 1000
    assert "未调用外部大模型" in report["generation"] and "本地规则与教师复核记录" in report["generation"]
    titles = [s["title"] for s in report["sections"]]
    for title in ("本次范围", "目标与课堂证据", "互动记录核对", "学生回应与支持"):
        assert title in titles
    # Bars only carry reviewed goals; the empty one is not turned into 0.
    assert [m["record_id"] for m in report["measurements"]] == ["measurement-1"]
    assert report["measurements"][0]["score"] is not None

    store = Demo2ReportStore(env.records)
    meta = store.save_from_workspace(env.tokens["a"], work)
    assert meta["stats"] == _db_counts(env, video.task_id) == {"students": 1, "reviewed": 1, "scored": 1, "pending": 1}
    assert meta["character_count"] >= 1000
    assert len(meta["report_id"]) == 32
    assert meta["task_id"] == meta["video_task_id"] == video.task_id
    assert meta["evaluation_id"] == evaluation["record_id"] or meta["evaluation_id"] in meta["evaluation_ids"]
    with env.records._connect() as db:
        row = db.execute("SELECT * FROM demo2_reports WHERE report_id=?", (meta["report_id"],)).fetchone()
    assert row["task_id"] == video.task_id
    assert json.loads(row["evaluation_ids_json"]) == meta["evaluation_ids"] != []
    assert json.loads(row["student_ids_json"]) == [env.pupils["a1"]["student_id"]]
    payload = json.loads(row["payload_json"])
    # Links are ids; the display name is never a key of the stored joins.
    assert env.pupils["a1"]["display_name"] not in row["student_ids_json"] + row["evaluation_ids_json"]
    assert payload["report"]["character_count"] >= 1000

    generated = [e for e in report_logs() if e["operation"] == "report_generate"]
    assert generated and generated[-1]["report_id"] == meta["report_id"]
    entry = generated[-1]
    for key in ("ts", "report_id", "evaluation_id", "version_fingerprint", "role", "result", "frame_revision"):
        assert entry.get(key), key
    assert entry["role"] == "teacher" and entry["result"] == "created"
    assert env.pupils["a1"]["display_name"] not in json.dumps(report_logs(), ensure_ascii=False)


def test_scoring_change_marks_report_stale_until_regenerated(env, report_logs):
    video, _, _, _, measurements, _, evaluations, evaluation_payload, _ = prepared(env)
    store = Demo2ReportStore(env.records)
    snapshot = store.save_from_workspace(env.tokens["a"], measurements.course_workspace(env.tokens["a"], video.task_id))
    # Unchanged scoring: both roles download normally.
    for user in ("a", "admin"):
        store.download(env.tokens[user], snapshot["report_id"], fmt="md")
        store.download(env.tokens[user], snapshot["report_id"], fmt="json")

    measurements.save(env.tokens["a"], _payload(
        env.pupils["a1"]["student_id"], expected_version=1, source_type="video_review", task_id=video.task_id,
        start_sec=0, end_sec=1, support_level="visual", observed_state="participating",
        teacher_prompt="分类", student_response="指认", scores={"accuracy": 9, "independence": 7,
                                                             "consistency": 6, "transfer": 5}))
    for user in ("a", "admin"):
        for call in (lambda t: store.download(t, snapshot["report_id"]), lambda t: store.get(t, snapshot["report_id"])):
            with pytest.raises(ReportError) as exc:
                call(env.tokens[user])
            assert exc.value.status == 409 and exc.value.code == "report_stale"
            assert "已过期" in exc.value.message and "重新生成" in exc.value.message
    listed = store.list_for_task(env.tokens["a"], video.task_id)["reports"][0]
    assert listed["stale"] is True and listed["status_label"] == "已过期"
    assert store.list_admin(env.tokens["admin"])["reports"][0]["status_label"] == "已过期"

    stale_checks = [e for e in report_logs() if e["operation"] == "report_stale_check" and e["result"] == "stale"]
    assert stale_checks and any(r.startswith("record_changed:") for r in stale_checks[-1]["stale_reasons"])
    assert {e["role"] for e in stale_checks} == {"teacher", "company_admin"}
    assert any(e["operation"] == "report_rejected" and e["code"] == "report_stale" for e in report_logs())

    regenerated = store.save_from_workspace(env.tokens["a"], measurements.course_workspace(env.tokens["a"], video.task_id))
    assert regenerated["report_id"] == snapshot["report_id"]
    assert regenerated["status"] == "saved" and regenerated["stale"] is False
    assert regenerated["version_fingerprint"] != snapshot["version_fingerprint"]
    text, _, _ = store.download(env.tokens["a"], snapshot["report_id"], fmt="md")
    assert "已记录目标测量 · 10分制" in text and "待处理记录" in text

    # Evaluation (学校/系统评分) changes are checked the same way.
    evaluations.save(env.tokens["a"], {**evaluation_payload, "expected_version": 1})
    with pytest.raises(ReportError) as exc:
        store.download(env.tokens["a"], snapshot["report_id"])
    assert exc.value.code == "report_stale"
    assert any(r.startswith("evaluation_changed:") for r in
               [e for e in report_logs() if e["operation"] == "report_stale_check"][-1]["stale_reasons"])


def test_admin_report_has_no_iep_links_but_teacher_keeps_them(env, report_logs):
    video, _, _, ref, measurements, *_ = prepared(env)
    work = measurements.course_workspace(env.tokens["a"], video.task_id)
    work["report"].setdefault("identifiers", {})["iep_links"] = [{"reference_id": ref["reference_id"]}]
    store = Demo2ReportStore(env.records)
    snapshot = store.save_from_workspace(env.tokens["a"], work)

    teacher = store.get(env.tokens["a"], snapshot["report_id"])
    assert teacher["payload"]["report"]["iep_links"][0]["reference_id"] == ref["reference_id"]
    teacher_json = json.loads(store.download(env.tokens["a"], snapshot["report_id"], fmt="json")[0])
    assert teacher_json["report"]["iep_links"]

    admin_view = store.get(env.tokens["admin"], snapshot["report_id"])
    assert "iep_links" not in json.dumps(admin_view, ensure_ascii=False)
    for fmt in ("json", "md"):
        text = store.download(env.tokens["admin"], snapshot["report_id"], fmt=fmt)[0]
        assert "iep_links" not in text
    assert "iep_links" not in json.dumps(store.list_admin(env.tokens["admin"]), ensure_ascii=False)

    redactions = [e for e in report_logs() if e["operation"] == "report_admin_redact"]
    assert redactions and all(e["role"] == "company_admin" for e in redactions)
    assert redactions[-1]["result"] == "redacted" and redactions[-1]["removed_fields"] == ["iep_links"]
    assert redactions[-1]["removed_count"] == 2
    downloads = [e for e in report_logs() if e["operation"] == "report_download"]
    assert {e["role"] for e in downloads} == {"teacher", "company_admin"}
    assert all(e.get("version_fingerprint") and e.get("evaluation_id") for e in downloads)
    views = [e for e in report_logs() if e["operation"] == "report_view"]
    assert {e["role"] for e in views} == {"teacher", "company_admin"}


def test_report_page_matches_reference_layout():
    html = demo2_course_page.render_course_analysis()
    for text in ("正文 ${r.character_count} 字符", "已记录目标测量 · 10分制", "不同学生、目标与支持条件不合并排名",
                 "6分为试行参考线", "空缺不是0分", "关联学生", "已复核目标", "可计分目标", "待处理记录",
                 "bar-ref", "reportCheck", "/reports/download?report_id=", "已过期", "重新生成报告"):
        assert text in html, text
