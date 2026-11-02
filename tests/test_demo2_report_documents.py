"""Word / PDF classroom and measurement reports (调整意见第 2 条：下载报告必须是文字报告).

Synthetic task, fictional students and fictional IEP content only.
"""
from __future__ import annotations

import io
import json
import re
from urllib.parse import unquote

import pytest

pytest.importorskip("docx")

from docx import Document  # noqa: E402

from rehab_affect import demo2_report_render as render_module  # noqa: E402
from rehab_affect.demo2_measurement_store import MeasurementError  # noqa: E402
from rehab_affect.demo2_report_store import ReportError  # noqa: E402
from rehab_affect.demo2_report_render import (  # noqa: E402
    DocumentModel,
    RendererUnavailable,
    classroom_report_model,
    content_disposition,
    plain,
)
from test_demo2_measurement_link import MANUAL, STUDENT_NAME, flow  # noqa: E402,F401  (fixture)
from test_demo2_dossier_store import env, template  # noqa: E402,F401
from test_demo2_iep_intake import service  # noqa: E402,F401
from test_demo2_evaluation_api import http_env  # noqa: E402,F401

MARKUP = re.compile(r"#|\*\*|\|---|```|[{}]")


@pytest.fixture
def logs(tmp_path, monkeypatch):
    folder = tmp_path / "report-logs"
    monkeypatch.setenv("REHAB_DEMO2_REPORT_DEBUG_LOG_DIR", str(folder))

    def read():
        return [json.loads(line) for path in sorted(folder.glob("report_debug_*.jsonl"))
                for line in path.read_text(encoding="utf-8").splitlines() if line]
    return read


def docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts += [cell.text for cell in row.cells]
    for section in document.sections:
        parts += [p.text for p in section.header.paragraphs] + [p.text for p in section.footer.paragraphs]
    return "\n".join(parts)


def pdf_text(data: bytes) -> tuple[str, int]:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def _snapshot(flow):
    flow.link.create_from_archive(flow.token, flow.archive)
    return flow.regenerate()


def test_plain_text_never_carries_markdown_or_json_markup():
    assert plain("## 标题 **粗体** | a | `code` {\"k\": 1}") == "＃＃ 标题 粗体 ／ a ／ 'code' （\"k\": 1）"
    assert not MARKUP.search(plain("```json\n{}\n```|---|"))
    assert (render_module.number(10, 0), render_module.number(60.0, 1), render_module.number(7.50)) == ("10", "60", "7.5")
    assert content_disposition("WeGlow_课堂报告_合成课程_2026-11-01.docx").startswith(
        'attachment; filename="WeGlow_2026-11-01.docx"; filename*=UTF-8\'\'WeGlow_%E8%AF%BE')


def test_teacher_word_and_pdf_are_readable_chinese_reports(flow, logs):
    snapshot = _snapshot(flow)
    data, filename, content_type = flow.reports.download(flow.token, snapshot["report_id"], fmt="docx")
    assert isinstance(data, bytes) and data[:2] == b"PK"
    assert content_type.endswith("wordprocessingml.document")
    assert re.fullmatch(r"WeGlow_课堂报告_.+_\d{4}-\d{2}-\d{2}\.docx", filename)
    text = docx_text(data)
    for heading in ("目录", "课程总览与结论", "课程评价", "学生个体评价", "本课任务目标与达成情况",
                    "附录 A　评分依据摘要", "附录 B　评分标准细则", "使用边界声明", "教师观察摘要", "关键片段时间点"):
        assert heading in text, heading
    assert "WeGlow微光系统 · 课堂观察报告" in text and "由 WeGlow微光系统 生成" in text
    assert STUDENT_NAME in text and MANUAL in text  # teacher keeps the IEP chapter
    assert "G-01" in text and snapshot["report_id"][:8] in text
    assert not MARKUP.search(text), MARKUP.search(text)
    assert len(Document(io.BytesIO(data)).inline_shapes) >= 1  # charts are images

    pytest.importorskip("reportlab")
    pdf, pdf_name, pdf_type = flow.reports.download(flow.token, snapshot["report_id"], fmt="pdf")
    assert pdf.startswith(b"%PDF") and pdf_type == "application/pdf" and pdf_name.endswith(".pdf")
    body, pages = pdf_text(pdf)
    assert pages >= 3
    compact = re.sub(r"\s+", "", body)
    assert "课程总览与结论" in compact and "学生个体评价" in compact and re.sub(r"\s+", "", STUDENT_NAME) in compact
    assert not MARKUP.search(body)

    entries = logs()
    done = [e for e in entries if e["operation"] == "report_render_done"]
    assert {e["fmt"] for e in done} == {"docx", "pdf"}
    for entry in done:
        assert entry["ts"] and entry["result"] == "ok" and entry["role"] == "teacher"
        assert entry["report_short"] == snapshot["report_id"][:8] and entry["byte_size"] > 1000
        assert isinstance(entry["duration_ms"], int)
    assert next(e for e in done if e["fmt"] == "pdf")["page_count"] == pages
    assert {e["fmt"] for e in entries if e["operation"] == "report_render_start"} == {"docx", "pdf"}
    raw = json.dumps(entries, ensure_ascii=False)
    assert STUDENT_NAME not in raw and MANUAL not in raw


def test_admin_documents_use_aliases_and_drop_iep(flow, logs):
    snapshot = _snapshot(flow)
    admin = flow.env.tokens["admin"]
    data, _, _ = flow.reports.download(admin, snapshot["report_id"], fmt="docx")
    text = docx_text(data)
    assert STUDENT_NAME not in text and "学生1" in text
    assert MANUAL not in text and "IEP 支持要点" not in text and "iep_links" not in text
    assert "公司后台（学生已化名）" in text
    pytest.importorskip("reportlab")
    pdf, _, _ = flow.reports.download(admin, snapshot["report_id"], fmt="pdf")
    body = re.sub(r"\s+", "", pdf_text(pdf)[0])
    assert re.sub(r"\s+", "", STUDENT_NAME) not in body and "学生1" in body and "IEP支持要点" not in body
    roles = {e["role"] for e in logs() if e["operation"] == "report_render_done"}
    assert roles == {"company_admin"}


def test_stale_invalid_format_and_missing_renderer(flow, logs, monkeypatch):
    snapshot = _snapshot(flow)
    with pytest.raises(ReportError) as error:
        flow.reports.download(flow.token, snapshot["report_id"], fmt="xlsx")
    assert (error.value.status, error.value.code) == (400, "invalid_format")

    def missing(model):
        raise RendererUnavailable("pdf", "reportlab")
    monkeypatch.setattr(render_module, "render_pdf", missing)
    with pytest.raises(ReportError) as error:
        flow.reports.download(flow.token, snapshot["report_id"], fmt="pdf")
    assert (error.value.status, error.value.code) == (503, "report_renderer_unavailable")
    assert "Word" in error.value.message
    failed = [e for e in logs() if e["operation"] == "report_render_failed"]
    assert failed[-1]["code"] == "report_renderer_unavailable" and failed[-1]["fmt"] == "pdf"
    # Word still works while PDF is unavailable.
    assert flow.reports.download(flow.token, snapshot["report_id"], fmt="docx")[0][:2] == b"PK"

    record = next(r for r in flow.measurements.workspace(flow.token)["records"] if r["goal_id"] == "G-02")
    flow.measurements.withdraw(flow.token, {"record_id": record["record_id"], "expected_version": record["version"],
                                            "reason": "验收：让报告过期"})
    for token in (flow.token, flow.env.tokens["admin"]):
        with pytest.raises(ReportError) as error:
            flow.reports.download(token, snapshot["report_id"], fmt="docx")
        assert (error.value.status, error.value.code) == (409, "report_stale")


def test_measurement_single_report_word_and_pdf(flow, logs):
    flow.link.create_from_archive(flow.token, flow.archive)
    record = next(r for r in flow.measurements.workspace(flow.token)["records"] if r["goal_id"] == "G-01")
    data, filename, content_type = flow.measurements.report_document(flow.token, record["record_id"], "docx")
    assert data[:2] == b"PK" and content_type.endswith("wordprocessingml.document")
    assert filename.startswith(f"WeGlow_测量报告_{STUDENT_NAME}_G-01_") and filename.endswith(".docx")
    text = docx_text(data)
    for expected in (f"{STUDENT_NAME} · G-01", "记录信息", "综合评分", "建议·待复核", "IEP 支持条件", MANUAL,
                     "视频指标汇总", "证据片段时间点", "评分说明", record["criterion"], record["measurement_context"]):
        assert expected in text, expected
    assert not MARKUP.search(text)
    pytest.importorskip("reportlab")
    pdf, pdf_name, _ = flow.measurements.report_document(flow.token, record["record_id"], "pdf")
    assert pdf.startswith(b"%PDF") and pdf_name.endswith(".pdf")
    assert "综合评分" in re.sub(r"\s+", "", pdf_text(pdf)[0])

    with pytest.raises(MeasurementError) as error:
        flow.measurements.report_document(flow.token, record["record_id"], "md")
    assert (error.value.status, error.value.code) == (400, "invalid_format")
    with pytest.raises(MeasurementError) as error:
        flow.measurements.report_document(flow.token, "vm-" + "0" * 32, "docx")
    assert (error.value.status, error.value.code) == (404, "record_unavailable")
    with pytest.raises(MeasurementError) as error:
        flow.measurements.report_document(flow.env.tokens["b"], record["record_id"], "docx")
    assert error.value.status in {403, 409} or error.value.code == "measurement_report_forbidden"
    done = [e for e in logs() if e["operation"] == "report_render_done" and e.get("kind") == "measurement"]
    assert {e["fmt"] for e in done} == {"docx", "pdf"} and all(e["record_short"] == record["record_id"][:8] for e in done)


def test_three_students_get_three_sections():
    students = [{"student_id": f"s{i}", "display_name": f"虚构学生{i}"} for i in range(1, 4)]
    overview = {
        "course_name": "合成课堂", "lesson_date": "2026-11-01",
        "students": [{"student_id": s["student_id"], "display_name": s["display_name"], "composite": 6.5,
                      "attainment": 65.0, "goals_achieved": 1, "goals_total": 2,
                      "dimensions": {"accuracy": 7, "independence": 6, "consistency": 6, "transfer": 5},
                      "timeline": {"segments": [{"start_sec": 0, "end_sec": 30, "state": "engaged", "label": "稳定参与"}],
                                   "duration_sec": 60}} for s in students],
        "indicators": {"categories": [{"id": "goals", "label": "目标适配与分层要求", "school": 8, "system": 7,
                                       "gap": -1, "item_ids": ["i1", "i2"]}],
                       "items": [{"id": "i1", "number": 1, "label": "教学目标落实课标要求", "category_label": "目标适配与分层要求",
                                  "school": 8, "system": 7, "evidence": "现场观察（虚构）"}]},
        "conclusion": {"available": True, "score": 72.0, "grade": {"label": "良好", "range": "70 ~ 84.9"},
                       "strengths": [{"text": "学生覆盖率 100%"}], "improvements": [{"text": "目标 G-02 需调整"}]},
        "state_colors": {"engaged": "#2f9e6b"}, "state_labels": {"engaged": "稳定参与"},
    }
    payload = {"students": students, "report": {"course_overview": overview, "sections": [
        {"title": "本次范围", "text": "合成范围说明。"}], "appendix_sections": []}}
    model = classroom_report_model(payload, {"report_id": "a" * 32, "generated_at": "2026-11-01T10:00:00+08:00",
                                             "stats": {"students": 3}}, admin=False)
    student_headings = [text for level, text in model.headings() if level == 2 and text.startswith("3.")]
    assert student_headings == ["3.1 虚构学生1", "3.2 虚构学生2", "3.3 虚构学生3"]
    assert isinstance(model, DocumentModel) and not MARKUP.search(model.text_content())
    data, info = render_module.render_docx(model)
    assert info["image_count"] >= 4 and docx_text(data).count("本课平均分（10分制）") == 3


def test_http_downloads_use_rfc5987_filenames(flow, http_env):
    snapshot = _snapshot(flow)
    report_id = snapshot["report_id"]
    status, headers, raw = http_env(f"/api/v1/demo2/reports/download?report_id={report_id}&fmt=docx", user="a")
    assert status == 200 and raw[:2] == b"PK"
    disposition = headers["Content-Disposition"]
    assert disposition.startswith('attachment; filename="') and "filename*=UTF-8''" in disposition
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]).startswith("WeGlow_课堂报告_")
    assert http_env(f"/api/v1/demo2/reports/download?report_id={report_id}&fmt=html", user="a")[2]["error"]["code"] == "invalid_format"
    record = next(r for r in flow.measurements.workspace(flow.token)["records"] if r["goal_id"] == "G-01")
    status, headers, raw = http_env(f"/api/v1/demo2/measurements/report/download?record_id={record['record_id']}&fmt=docx",
                                    user="a")
    assert status == 200 and raw[:2] == b"PK"
    assert unquote(headers["Content-Disposition"].split("filename*=UTF-8''", 1)[1]).startswith("WeGlow_测量报告_")
    status, _, body = http_env(f"/api/v1/demo2/measurements/report/download?record_id={record['record_id']}&fmt=json",
                               user="a")
    assert status == 400 and body["error"]["code"] == "invalid_format"
    assert http_env(f"/api/v1/demo2/measurements/report/download?record_id={record['record_id']}&fmt=docx",
                    user=None)[0] == 401
