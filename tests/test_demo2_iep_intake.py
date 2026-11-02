"""IEP Word/PDF intake → confirmed summary → dossier IEP version → classroom reference (fictional data only)."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from rehab_affect import demo2_iep_intake as intake_module  # noqa: E402
from rehab_affect.demo2_document_parser import parse_document  # noqa: E402
from rehab_affect.demo2_document_store import DocumentParseStore  # noqa: E402
from rehab_affect.demo2_iep_intake import IepIntakeError, IepIntakeService, build_iep_summary  # noqa: E402
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore  # noqa: E402
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore  # noqa: E402
from rehab_affect.video_applicability import ApplicabilityStore  # noqa: E402
from rehab_affect.demo2_report_store import Demo2ReportStore, ReportError  # noqa: E402
from test_demo2_document_parser import _table, http_env  # noqa: E402,F401
from test_demo2_dossier_store import authorize, day, env, task, template  # noqa: E402,F401
from test_demo2_evaluation_store import payload as evaluation_payload  # noqa: E402

STUDENT = "林小禾"
DIAGNOSIS = "孤独症谱系障碍（虚构）"
ID_CARD = "110101201603081234"
MOBILE = "13812345678"
ADDRESS = "北京市东城区和平路12号3单元201室"

_SPEC = importlib.util.spec_from_file_location(
    "verify_id_chain", Path(__file__).resolve().parents[1] / "scripts" / "verify_id_chain.py")
verify_id_chain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify_id_chain)


def build_iep() -> bytes:
    document = docx.Document()
    document.add_heading("个别化教育计划（IEP）· 虚构样例", level=1)
    _table(document, [["学生姓名", STUDENT, "出生日期", "2016-03-08"],
                      ["班级", "三年级（2）班", "诊断", DIAGNOSIS],
                      ["身份证号", ID_CARD, "家庭住址", ADDRESS]])
    document.add_heading("长期目标", level=2)
    document.add_paragraph(f"{STUDENT}一学期内能独立完成三步以内的生活数学任务。", style="List Bullet")
    document.add_paragraph("能在集体课中保持专注10分钟。", style="List Bullet")
    document.add_paragraph("因多动症（虚构）需把任务拆成5分钟以内的小段。", style="List Bullet")
    document.add_paragraph().add_run().add_break(docx.enum.text.WD_BREAK.PAGE)
    document.add_heading("短期目标", level=2)
    _table(document, [["短期目标", "教学策略", "评估方式"],
                      ["能认出1元硬币", "视觉提示卡", "课堂观察记录"],
                      ["能在提示下付款", "分步骤指令", "任务分析检核"]])
    document.add_paragraph("支持需求：需要视觉流程图和个别口头提示。")
    document.add_paragraph(f"家长电话 {MOBILE}，周末可联系。")
    document.add_paragraph("注意事项")
    document.add_paragraph("操作剪刀等工具时需要教师在旁。", style="List Bullet")
    document.add_paragraph("环境噪音过大时允许暂时离开座位。", style="List Bullet")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _no_sensitive(text: str) -> None:
    for value in (STUDENT, DIAGNOSIS, "孤独症", ID_CARD, MOBILE, "和平路", "诊断"):
        assert value not in text


def test_summary_is_itemized_paged_and_filters_sensitive_content():
    summary = build_iep_summary(parse_document("iep", "docx", build_iep()))
    texts = [item["text"] for item in summary["items"]]
    _no_sensitive(json.dumps(summary["items"], ensure_ascii=False))
    categories = {item["category"] for item in summary["items"]}
    assert {"long_term_goals", "short_term_goals", "support_needs", "teaching_strategies",
            "assessment_methods", "precautions"} <= categories
    assert all(isinstance(item["page"], int) and item["page"] >= 1 for item in summary["items"])
    assert any(item["page"] == 2 for item in summary["items"] if item["category"] == "short_term_goals")
    assert any("该生" in text for text in texts)  # the student's name is replaced, never copied
    assert "操作剪刀等工具时需要教师在旁" in texts
    assert [item["item_id"] for item in summary["items"]] == [f"s{i:02d}" for i in range(1, len(texts) + 1)]
    assert summary["excluded_sensitive_count"] >= 1


@pytest.fixture
def service(env, monkeypatch, tmp_path):
    monkeypatch.setenv(intake_module.DEBUG_LOG_DIR_ENV, str(tmp_path / "iep_logs"))
    documents = DocumentParseStore(env.records)
    return IepIntakeService(env.records, env.store, documents), documents


def _parse(env, documents, data=None):
    account_id = env.accounts["a"]["account_id"]
    return documents.parse_upload(account_id, "iep", "虚构IEP.docx", data or build_iep())["parse_id"]


def _logs(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "iep_logs").glob("iep_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_required_rule_rejects_empty_and_unconfirmed(env, service, tmp_path):
    svc, documents = service
    student = env.pupils["a1"]["student_id"]
    for empty in (None, {}, {"mode": "new", "items": [], "manual_supplement": "  ", "confirmed": True}):
        with pytest.raises(IepIntakeError) as error:
            svc.commit(env.tokens["a"], student, empty, task_id="t")
        assert (error.value.status, error.value.code) == (400, "iep_summary_required")
    parse_id = _parse(env, documents)
    summary = svc.generate_summary(env.tokens["a"], {"parse_id": parse_id})
    items = [{"item_id": i["item_id"], "text": i["text"]} for i in summary["items"]]
    with pytest.raises(IepIntakeError) as error:
        svc.commit(env.tokens["a"], student, {"mode": "new", "parse_id": parse_id, "items": items, "confirmed": False})
    assert error.value.code == "iep_summary_unconfirmed"
    with pytest.raises(IepIntakeError) as error:
        svc.commit(env.tokens["a"], student, {"mode": "new", "parse_id": parse_id, "confirmed": True,
                                              "items": [{"item_id": items[0]["item_id"], "text": "电话 " + MOBILE}]})
    assert error.value.code == "iep_summary_sensitive"
    lines = _logs(tmp_path)
    assert [line["operation"] for line in lines if line["operation"] == "iep_required_rejected"]
    raw = json.dumps(lines, ensure_ascii=False)
    _no_sensitive(raw)
    assert all(item["text"] not in raw for item in summary["items"])


def test_confirmed_summary_creates_iep_version_reference_and_full_chain(env, service, tmp_path, capsys):
    svc, documents = service
    token, student = env.tokens["a"], env.pupils["a1"]["student_id"]
    video = task(env)
    source = build_iep()
    parse_id = _parse(env, documents, source)
    summary = svc.generate_summary(token, {"parse_id": parse_id})
    kept = [{"item_id": i["item_id"], "text": i["text"]} for i in summary["items"][1:]]
    kept[0]["text"] += "（教师已核对）"
    manual = "上课前先展示当天流程图。"
    request = {"mode": "new", "parse_id": parse_id, "items": kept, "manual_supplement": manual, "confirmed": True,
               "authorization": {"reference": "虚构授权记录-001", "valid_until": day(30), "confirmed": True}}
    result = svc.commit(token, student, request, task_id=video.task_id)
    assert result["created"] and result["original_saved"] and result["reference_id"]
    again = svc.commit(token, student, request, task_id=video.task_id)  # retry is idempotent
    assert again["document_id"] == result["document_id"] and not again["created"]
    workspace = env.store.student_workspace(token, student)
    iep_docs = [d for d in workspace["documents"] if d["document_type"] == "iep" and d["available"]]
    assert len(iep_docs) == 1 and iep_docs[0]["has_file"]
    doc = iep_docs[0]
    assert doc["intake"]["manual_supplement"] == manual
    assert [i["item_id"] for i in doc["intake"]["items"]] == [k["item_id"] for k in kept]
    assert all(i["page"] for i in doc["intake"]["items"])
    assert "教师补充：" + manual in doc["summary"]["support_methods"]
    _no_sensitive(json.dumps(doc["summary"], ensure_ascii=False))
    data, filename, mime = env.store.document_download(token, doc["document_id"])
    assert data == source and filename.endswith(".docx") and STUDENT not in filename
    status = svc.student_status(token, student)
    assert status["iep_status"] == "available" and status["current"]["document_id"] == doc["document_id"]
    refs = env.store.task_workspace(token, video.task_id)["references"]
    assert [r["iep_document_id"] for r in refs if r["available"]] == [doc["document_id"]]
    # Downstream: evaluation system track + analysis read the confirmed summary; the stored snapshot drops it.
    suitability = ApplicabilityStore(env.records)
    state = suitability.workspace(token, video.task_id)
    suitability.save(token, dict(task_id=video.task_id, version=state["version"], revision=state["revision"],
                                 category="special", goal="合成课堂分类目标", reason="合成视频工程测试", confirmed=True))
    Demo2EvaluationStore(env.records).save(token, evaluation_payload(task_id=video.task_id, frame_revision=video.revision,
                                                                     iep_summary_id=doc["document_id"]))
    work = Demo2MeasurementStore(env.records).course_workspace(token, video.task_id)
    assert work["people"][0]["iep_context"]["status"] == "available"
    assert work["people"][0]["identifiers"]["iep_summary_id"] == doc["document_id"]
    assert "教师补充" in json.dumps(work["report"], ensure_ascii=False)
    reports = Demo2ReportStore(env.records)
    snapshot = reports.save_from_workspace(token, work)
    code = verify_id_chain.main(["--db", str(env.records.db_path), "--json", "--quiet", "--no-log-file",
                                 "--video-task-id", video.task_id, "--require-iep"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, json.dumps(out, ensure_ascii=False)[:3000]
    assert out["results"][0]["chain"]["iep_document_id"] == [doc["document_id"]]
    admin = reports.get(env.tokens["admin"], snapshot["report_id"])
    assert "iep_links" not in admin["payload"]["report"]
    assert "教师补充" not in json.dumps(admin, ensure_ascii=False)
    # Withdrawal: report goes stale, the regenerated analysis no longer reads the IEP.
    auth = workspace["authorization"]
    env.store.withdraw_authorization(token, {"student_id": student, "authorization_id": auth["authorization_id"],
                                             "confirmed": True})
    with pytest.raises(ReportError) as stale:
        reports.get(token, snapshot["report_id"])
    assert stale.value.code == "report_stale"
    later = Demo2MeasurementStore(env.records).course_workspace(token, video.task_id)
    assert later["people"][0]["iep_context"]["status"] != "available"
    assert all(link["available"] is False for link in later["report"].get("iep_links", []))
    assert "教师补充" not in json.dumps(later["report"], ensure_ascii=False)
    operations = {line["operation"] for line in _logs(tmp_path)}
    assert {"iep_summary_generate", "iep_summary_confirm", "iep_manual_supplement", "iep_document_create",
            "iep_reference_create"} <= operations
    raw = json.dumps(_logs(tmp_path), ensure_ascii=False)
    assert manual not in raw and student not in raw and doc["document_id"] not in raw
    assert doc["document_id"][:8] in raw


def test_second_family_is_ambiguous_and_existing_choice_links_one(env, service):
    svc, documents = service
    token, student = env.tokens["a"], env.pupils["a1"]["student_id"]
    authorize(env)
    first = svc.commit(token, student, {"mode": "new", "manual_supplement": "需要分步骤指令。", "confirmed": True})
    second = svc.commit(token, student, {"mode": "new", "manual_supplement": "需要视觉提示卡。", "confirmed": True})
    status = svc.student_status(token, student)
    assert status["iep_status"] == "ambiguous"
    assert {c["document_id"] for c in status["candidates"]} == {first["document_id"], second["document_id"]}
    video = task(env)
    linked = svc.commit(token, student, {"mode": "existing", "document_id": second["document_id"]}, task_id=video.task_id)
    assert linked["reference_id"] and not linked["created"]
    with pytest.raises(IepIntakeError) as error:
        svc.commit(token, student, {"mode": "existing", "document_id": "f" * 32}, task_id=video.task_id)
    assert error.value.code == "iep_document_not_current"
    # A new version supersedes one family (history stays); the other family keeps the student ambiguous.
    replaced = svc.commit(token, student, {"mode": "new", "manual_supplement": "替换为新版本。", "confirmed": True,
                                           "supersedes_id": first["document_id"]})
    assert replaced["version"] == 2
    after = svc.student_status(token, student)
    assert after["iep_status"] == "ambiguous"
    assert {c["document_id"] for c in after["candidates"]} == {replaced["document_id"], second["document_id"]}


def test_http_archive_requires_iep_summary(http_env):
    env = http_env.env
    for body in ({"task_id": "task-x", "person_id": "p1", "student_id": "s1", "binding_id": "b1"},
                 {"task_id": "task-x", "person_id": "p1", "student_id": "s1", "binding_id": "b1",
                  "iep": {"mode": "new", "items": [], "manual_supplement": "", "confirmed": True}}):
        status, payload = http_env.call("POST", "/api/v1/demo2/simple-result/archive", env.tokens["a"],
                                        json.dumps(body).encode(), "application/json")
        assert status == 400 and payload["error"]["code"] == "iep_summary_required"
        assert payload["error"]["field"] == "iepSummary"
    status, payload = http_env.call("POST", "/api/v1/demo2/simple-result/archive", env.tokens["a"],
                                    json.dumps({"task_id": "t", "person_id": "p", "student_id": "s", "binding_id": "b",
                                                "iep_support_summary": "需要视觉提示"}).encode(), "application/json")
    assert status == 400 and payload["error"]["code"] == "iep_summary_legacy_field"


def test_http_upload_summary_and_status(http_env):
    env = http_env.env
    status, parsed = http_env.upload(env.tokens["a"], "iep", "虚构IEP.docx", build_iep())
    assert status == 200
    status, body = http_env.call("POST", "/api/v1/demo2/dossier/iep-intake/summary", env.tokens["a"],
                                 json.dumps({"parse_id": parsed["result"]["parse_id"]}).encode(), "application/json")
    assert status == 200 and body["summary"]["status"] == "pending_confirmation"
    _no_sensitive(json.dumps(body["summary"]["items"], ensure_ascii=False))
    status, body = http_env.call("POST", "/api/v1/demo2/dossier/iep-intake/summary", env.tokens["b"],
                                 json.dumps({"parse_id": parsed["result"]["parse_id"]}).encode(), "application/json")
    assert status == 403
    student = env.pupils["a1"]["student_id"]
    status, body = http_env.call("GET", f"/api/v1/demo2/dossier/iep-intake/status?student_id={student}", env.tokens["a"])
    assert status == 200 and body["status"]["iep_status"] == "no_authorization"
    status, body = http_env.call("POST", "/api/v1/demo2/dossier/iep-intake/commit", env.tokens["a"],
                                 json.dumps({"student_id": student, "iep": {"mode": "new", "manual_supplement": "",
                                                                            "confirmed": True, "items": []}}).encode(),
                                 "application/json")
    assert status == 400 and body["error"]["code"] == "iep_summary_required"
