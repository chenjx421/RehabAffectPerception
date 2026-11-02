"""Course-task / IEP document upload and parsing service (demo2_document_parser / _store).

Every fixture is a fictional document generated here; no real student data.
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

docx = pytest.importorskip("docx")
pdfplumber = pytest.importorskip("pdfplumber")
pypdf = pytest.importorskip("pypdf")

from docx.enum.text import WD_BREAK  # noqa: E402

from rehab_affect import demo2_document_parser as parser  # noqa: E402
from rehab_affect import demo2_manager_gateway as gateway  # noqa: E402
from rehab_affect import scenario_lab_server as server  # noqa: E402
from rehab_affect.demo2_document_store import DocumentParseStore  # noqa: E402
from test_demo2_dossier_store import env, template  # noqa: E402,F401

COURSE_PARAGRAPHS = [
    "生活数学课程任务书", "课程名称：认识人民币", "年级/班级：三年级（2）班", "上课日期：2026-11-05", "授课教师：林晓",
    "课程任务目标", "能认出1元、5角、1角三种人民币。", "能在提示下用1元购买一件物品。", "能说出物品价格并找到对应的钱币。",
    "测量条件", "在模拟超市情境中进行，每名学生操作3次，教师仅给予口头提示。", "目标与评价标准",
    "家长联系电话：13812345678（仅用于课后沟通）", "教学过程", "导入：出示超市图片，引导学生说出想买的物品。",
    "练习：分组模拟购物，教师巡回记录。", "备注：本课所有学生姓名均为虚构。",
]
COURSE_TABLE = [["序号", "课程任务目标", "评价标准", "通过标准"],
                ["1", "认出三种人民币", "指认正确次数", "3次中正确2次及以上"],
                ["2", "用1元购买物品", "独立完成交易步骤", "在1次口头提示内完成"],
                ["3", "说出物品价格", "语言或指认表达价格", "3次中正确2次"]]
IEP_INFO = [["学生姓名", "王小明", "出生日期", "2016-03-08"],
            ["班级", "三年级（2）班", "诊断", "孤独症谱系障碍（虚构）"],
            ["身份证号", "110101201603081234", "家庭住址", "北京市东城区和平路12号3单元201室"]]
IEP_GOALS = [["短期目标", "教学策略", "评估方式", "负责人", "周期"],
             ["能认出1元硬币", "视觉提示卡", "课堂观察记录", "林晓", "2026年11月"],
             ["能在提示下付款", "情境模拟", "任务分析检核", "张老师", "2026年12月"]]
IEP_PARAGRAPHS = ["个别化教育计划（IEP）", "现有能力水平", "能听懂简单指令，能用单词表达需求。", "长期目标",
                  "一学期内能独立完成三步以内的生活数学任务。", "能在集体课中保持专注10分钟。", "短期目标",
                  "支持需求：需要视觉流程图和个别口头提示。", "家长电话 021-62345678，周末可联系。",
                  "其他说明：本计划每学期复核一次。"]


def _table(document, rows):
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value


def _page_break(document):
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def build_course_docx() -> bytes:
    document = docx.Document()
    document.add_heading(COURSE_PARAGRAPHS[0], level=1)
    for text in COURSE_PARAGRAPHS[1:5]:
        document.add_paragraph(text)
    document.add_heading(COURSE_PARAGRAPHS[5], level=2)
    for text in COURSE_PARAGRAPHS[6:9]:
        document.add_paragraph(text, style="List Number")
    document.add_heading(COURSE_PARAGRAPHS[9], level=2)
    document.add_paragraph(COURSE_PARAGRAPHS[10])
    _page_break(document)
    document.add_heading(COURSE_PARAGRAPHS[11], level=2)
    _table(document, COURSE_TABLE)
    document.add_paragraph(COURSE_PARAGRAPHS[12])
    _page_break(document)
    document.add_heading(COURSE_PARAGRAPHS[13], level=2)
    for text in COURSE_PARAGRAPHS[14:]:
        document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def build_iep_docx() -> bytes:
    document = docx.Document()
    document.add_heading(IEP_PARAGRAPHS[0], level=1)
    _table(document, IEP_INFO)
    document.add_heading(IEP_PARAGRAPHS[1], level=2)
    document.add_paragraph(IEP_PARAGRAPHS[2])
    document.add_heading(IEP_PARAGRAPHS[3], level=2)
    document.add_paragraph(IEP_PARAGRAPHS[4], style="List Bullet")
    document.add_paragraph(IEP_PARAGRAPHS[5], style="List Bullet")
    document.add_heading(IEP_PARAGRAPHS[6], level=2)
    _table(document, IEP_GOALS)
    for text in IEP_PARAGRAPHS[7:]:
        document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _soffice_convert(source: Path, target_format: str) -> Path:
    binary = parser._soffice_binary()
    if not binary:
        pytest.skip("LibreOffice 不可用，无法生成测试 PDF")
    folder = source.parent
    subprocess.run([binary, f"-env:UserInstallation={(folder / 'profile').as_uri()}", "--headless", "--norestore",
                    "--convert-to", target_format, "--outdir", str(folder), str(source)],
                   capture_output=True, timeout=240, check=False)
    target = source.with_suffix("." + target_format)
    if not target.is_file():
        pytest.skip("LibreOffice 转换失败")
    return target


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    folder = tmp_path_factory.mktemp("document_samples")
    course_docx = folder / "course_task.docx"
    course_docx.write_bytes(build_course_docx())
    pdf = _soffice_convert(course_docx, "pdf")
    iep = folder / "iep.docx"
    iep.write_bytes(build_iep_docx())
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(image).rectangle((100, 100, 600, 300), fill="black")
    scanned = io.BytesIO()
    image.save(scanned, "PDF", resolution=150)
    png = io.BytesIO()
    image.save(png, "PNG")
    writer = pypdf.PdfWriter(clone_from=str(pdf))
    writer.encrypt(user_password="secret", owner_password="owner")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    return SimpleNamespace(pdf=pdf.read_bytes(), iep=iep.read_bytes(), scanned=scanned.getvalue(), png=png.getvalue(),
                           encrypted=encrypted.getvalue(), folder=folder)


def _chars(text: str) -> Counter:
    return Counter(ch for ch in text if not ch.isspace())


def _block_texts(result):
    texts = []
    for block in result["blocks"]:
        if block["kind"] == "table":
            texts += [cell["text"] for cell in block["cells"]]
        else:
            texts.append(block["text"])
    return texts


def _by_field(result, field):
    return [c for c in result["candidates"] if c["field"] == field]


# ---------------------------------------------------------------------------
# acceptance 1: lossless blocks and field candidates
# ---------------------------------------------------------------------------

def test_course_task_pdf_blocks_cover_every_paragraph_and_cell(samples):
    result = parser.parse_document("course_task", parser.detect_document_type("课程.pdf", samples.pdf), samples.pdf)
    assert result["status"] == "parsed" and result["page_count"] == 3
    joined = "".join(_block_texts(result)).replace("\n", "")
    for text in COURSE_PARAGRAPHS:
        assert text.replace(" ", "") in joined.replace(" ", ""), text
    tables = [b for b in result["blocks"] if b["kind"] == "table"]
    assert len(tables) == 1 and tables[0]["page"] == 2
    cells = {(c["row"], c["col"]): c["text"].replace("\n", "") for c in tables[0]["cells"]}
    for r, row in enumerate(COURSE_TABLE, start=1):
        for c, value in enumerate(row, start=1):
            assert cells[(r, c)] == value
    # Every non-blank character of the PDF text layer is in some block, nothing extra or missing.
    with pdfplumber.open(io.BytesIO(samples.pdf)) as pdf:
        layer = _chars("".join(page.extract_text() or "" for page in pdf.pages))
    assert _chars("".join(_block_texts(result))) == layer
    pages = {b["page"] for b in result["blocks"]}
    assert pages == {1, 2, 3}


def test_course_task_candidates_are_classified_and_located(samples):
    result = parser.parse_document("course_task", "pdf", samples.pdf)
    single = {field: _by_field(result, field)[0] for field in ("course_name", "grade_class", "lesson_date", "teacher")}
    assert single["course_name"]["value"] == "认识人民币"
    assert single["grade_class"]["value"] == "三年级（2）班"
    assert single["lesson_date"]["value"] == "2026-11-05"
    assert all(c["source"]["page"] == 1 and c["source"]["paragraph_index"] and c["confidence"] >= 0.8
               for c in single.values())
    goals = [c for c in _by_field(result, "course_goals") if not c["same_goal_as"]]
    assert [g["value"] for g in goals] == [
        "能认出1元、5角、1角三种人民币。", "能在提示下用1元购买一件物品。", "能说出物品价格并找到对应的钱币。"]
    assert all(g["source"]["page"] == 1 for g in goals)
    criteria = _by_field(result, "evaluation_criteria")
    passes = _by_field(result, "pass_criteria")
    assert [c["value"] for c in passes] == ["3次中正确2次及以上", "在1次口头提示内完成", "3次中正确2次"]
    assert [c["group"] for c in criteria] == [g["group"] for g in goals]
    assert all(c["source"]["page"] == 2 and c["source"]["cell_id"] for c in criteria + passes)
    assert _by_field(result, "measurement_conditions")[0]["value"].startswith("在模拟超市情境中进行")
    summary = {goal["group"]: goal for goal in result["goals"]}
    assert len(summary) == 3 and all(len(goal["detail_candidate_ids"]) >= 3 for goal in summary.values())
    others = [o["text"] for o in result["other_content"]]
    assert "导入：出示超市图片，引导学生说出想买的物品。" in others and "备注：本课所有学生姓名均为虚构。" in others
    assert all(field["found"] for field in result["fields"] if field["field"] != "subject")


def test_iep_docx_fields_coverage_and_sensitive_flags(samples):
    result = parser.parse_document("iep", parser.detect_document_type("王小明_IEP.docx", samples.iep), samples.iep)
    texts = _block_texts(result)
    for text in IEP_PARAGRAPHS:
        assert text in texts
    for row in IEP_INFO + IEP_GOALS:
        for value in row:
            assert value in texts
    values = {field: [c["value"] for c in _by_field(result, field)] for field in (
        "student_name", "diagnosis", "long_term_goals", "short_term_goals", "teaching_strategies",
        "assessment_methods", "responsible_persons", "period", "support_needs", "present_level", "personal_info")}
    assert values["long_term_goals"] == IEP_PARAGRAPHS[4:6]
    assert values["short_term_goals"] == ["能认出1元硬币", "能在提示下付款"]
    assert values["teaching_strategies"] == ["视觉提示卡", "情境模拟"]
    assert values["responsible_persons"] == ["林晓", "张老师"]
    assert values["period"] == ["2026年11月", "2026年12月"]
    assert values["support_needs"] == ["需要视觉流程图和个别口头提示。"]
    assert values["present_level"] == ["能听懂简单指令，能用单词表达需求。"]
    short = _by_field(result, "short_term_goals")
    assert [c["group"] for c in _by_field(result, "assessment_methods")] == [c["group"] for c in short]
    sensitive = {c["value"]: c for c in result["candidates"] if c["sensitive"]}
    assert "id_card" in sensitive["110101201603081234"]["sensitive_types"]
    assert "address" in sensitive["北京市东城区和平路12号3单元201室"]["sensitive_types"]
    assert any("phone" in c["sensitive_types"] for c in sensitive.values())
    assert "diagnosis" in sensitive["孤独症谱系障碍（虚构）"]["sensitive_types"]
    assert "name" in sensitive["王小明"]["sensitive_types"]
    assert all(c["decision"] == "pending" and c["requires_confirmation"] for c in sensitive.values())
    assert not any(c["sensitive"] for c in short)
    assert [o["text"] for o in result["other_content"]] == ["个别化教育计划（IEP）", "其他说明：本计划每学期复核一次。"]


def test_docx_text_boxes_headers_and_merged_cells_are_kept():
    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = "虚构学校课程任务页眉"
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "合并单元格内容"
    table.cell(0, 2).text = "右侧"
    table.cell(1, 0).text = "左下"
    nested = table.cell(1, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "嵌套表格文字"
    output = io.BytesIO()
    document.save(output)
    result = parser.parse_document("course_task", "docx", output.getvalue())
    texts = _block_texts(result)
    assert "虚构学校课程任务页眉" in texts
    assert texts.count("合并单元格内容") == 1
    assert any("嵌套表格文字" in text for text in texts)


def test_numbered_goal_labels_and_table_references_stay_one_goal_each():
    """Word auto-numbering leaves "目标1：…" without a list marker; the table's "目标1" points back to it."""
    document = docx.Document()
    document.add_heading("教学目标", level=2)
    for text in ("目标1：能指认钟面上的时针和分针。", "目标2：能在提示下读出整点时间。", "目标三：能按口令拨出半点时间。"):
        document.add_paragraph(text, style="List Number")
    _table(document, [["目标", "评价方式", "通过标准"], ["目标1", "实物指认", "连续3次指认正确"],
                      ["目标2", "口头回答", "5题中答对4题"], ["目标3", "操作钟面", "独立完成2次"]])
    output = io.BytesIO()
    document.save(output)
    result = parser.parse_document("course_task", "docx", output.getvalue())
    goals = result["goals"]
    by_id = {item["candidate_id"]: item for item in result["candidates"]}
    assert [by_id[g["goal_candidate_id"]]["value"] for g in goals] == [
        "目标1：能指认钟面上的时针和分针。", "目标2：能在提示下读出整点时间。", "目标三：能按口令拨出半点时间。"]
    for goal, (method, passing) in zip(goals, [("实物指认", "连续3次指认正确"), ("口头回答", "5题中答对4题"),
                                                ("操作钟面", "独立完成2次")]):
        details = {by_id[cid]["field"]: by_id[cid]["value"] for cid in goal["detail_candidate_ids"]
                   if by_id[cid]["field"] != "course_goals"}
        assert details == {"evaluation_criteria": method, "pass_criteria": passing}
    references = [c for c in result["candidates"] if c["field"] == "course_goals" and c["same_goal_as"]]
    assert [c["same_goal_as"] for c in references] == [g["goal_candidate_id"] for g in goals]
    assert not [o for o in result["other_content"] if o["text"].startswith("目标")]


# ---------------------------------------------------------------------------
# acceptance 2 / 4: type checks, scanned, damaged and encrypted files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, payload", [
    ("notes.pdf", "课程名称：这是纯文本冒充的PDF".encode("utf-8")),
    ("photo.png", None),
    ("photo.pdf", None),
    ("setup.exe", b"MZ\x90\x00" + bytes(200)),
    ("setup.pdf", b"MZ\x90\x00" + bytes(200)),
    ("fake.docx", b"PK\x03\x04garbage"),
    ("fake.doc", b"plain text"),
    ("notes.txt", "课程名称：文本".encode("utf-8")),
])
def test_unsupported_types_are_rejected_not_read_as_text(samples, name, payload):
    with pytest.raises(parser.DocumentError) as caught:
        parser.detect_document_type(name, payload if payload is not None else samples.png)
    assert (caught.value.status, caught.value.code) == (400, "unsupported_document_type")


def test_oversized_document_is_413():
    with pytest.raises(parser.DocumentError) as caught:
        parser.detect_document_type("big.pdf", b"%PDF-1.4\n" + bytes(parser.MAX_DOCUMENT_BYTES))
    assert (caught.value.status, caught.value.code) == (413, "document_too_large")


def test_scanned_pdf_without_ocr_needs_manual_entry(samples, monkeypatch):
    monkeypatch.setenv(parser.OCR_ENV, "0")
    parser.reset_ocr_cache()
    try:
        result = parser.parse_document("iep", "pdf", samples.scanned)
    finally:
        parser.reset_ocr_cache()
    assert result["status"] == "needs_manual_entry"
    assert result["manual_entry_required"] is True and result["manual_entry_reason"] == "ocr_unavailable"
    assert result["manual_entry_pages"] == [1] and "人工补充" in result["notice"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract 未安装")
def test_scanned_pdf_uses_ocr_when_available(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw, ImageFont
    fonts = [p for p in ("/System/Library/Fonts/STHeiti Medium.ttc", "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc")
             if Path(p).is_file()]
    if not fonts:
        pytest.skip("没有中文字体生成扫描样本")
    monkeypatch.delenv(parser.OCR_ENV, raising=False)
    parser.reset_ocr_cache()
    if not parser.ocr_available():
        pytest.skip("tesseract 缺少 chi_sim 语言包")
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(fonts[0], 48)
    for index, text in enumerate(["课程名称：认识钟表", "教学目标：", "1. 能认出整点。", "2. 能说出半点。"]):
        draw.text((120, 150 + index * 110), text, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, "PDF", resolution=150)
    try:
        result = parser.parse_document("course_task", "pdf", output.getvalue())
    finally:
        parser.reset_ocr_cache()
    assert result["status"] == "parsed_with_ocr" and result["ocr"]["pages"] == [1]
    assert _by_field(result, "course_name")[0]["value"] == "认识钟表"
    assert all(b["source"] == "ocr" for b in result["blocks"])
    assert all(c["confidence"] < 0.7 for c in result["candidates"])


def test_damaged_and_encrypted_pdf_have_clear_codes(samples):
    with pytest.raises(parser.DocumentError) as damaged:
        parser.parse_document("course_task", "pdf", samples.pdf[:3000])
    assert (damaged.value.status, damaged.value.code) == (400, "document_parse_failed")
    with pytest.raises(parser.DocumentError) as locked:
        parser.parse_document("course_task", "pdf", samples.encrypted)
    assert (locked.value.status, locked.value.code) == (400, "document_encrypted")
    assert "密码" in locked.value.message


def test_doc_without_libreoffice_asks_for_docx_or_pdf(monkeypatch):
    monkeypatch.setattr(parser, "_soffice_binary", lambda: "")
    data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(600)
    assert parser.detect_document_type("旧课程.doc", data) == "doc"
    with pytest.raises(parser.DocumentError) as caught:
        parser.parse_document("course_task", "doc", data)
    assert caught.value.code == "doc_conversion_unavailable" and "另存为 .docx 或 PDF" in caught.value.message


def test_multipart_parser_is_exact():
    body = (b"--XyZ\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\niep\r\n"
            b"--XyZ\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n"
            b"Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n--Xy\r\n--XyZ--\r\n")
    fields, files = parser.parse_multipart("multipart/form-data; boundary=XyZ", body)
    assert fields == {"purpose": "iep"} and files["file"] == ("a.pdf", b"%PDF-1.4\r\n--Xy")
    with pytest.raises(parser.DocumentError):
        parser.parse_multipart("multipart/form-data; boundary=XyZ", b"--XyZ\r\nbroken")
    with pytest.raises(parser.DocumentError) as caught:
        parser.parse_multipart("application/json", b"{}")
    assert caught.value.status == 415


# ---------------------------------------------------------------------------
# HTTP API, isolation, encryption and debug log
# ---------------------------------------------------------------------------

def _multipart(purpose, filename, data, boundary="rxBoundary7MA4YWxkTrZu0gW"):
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n{purpose}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", head + data + f"\r\n--{boundary}--\r\n".encode()


@pytest.fixture
def http_env(env, monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_DOCUMENT_DEBUG_LOG_DIR", str(tmp_path / "document_logs"))
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: env.records)
    handler = server.create_handler(scenario_dir=Path("configs/scenarios"),
                                    model_path=server.DEFAULT_LEARNED_POLICY_PATH, policy_name="rule")
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def call(method, path, token=None, body=b"", content_type=None, headers=None):
        sent = {"Connection": "close", **(headers or {})}
        if token:
            sent["Cookie"] = "rehab_demo2_session=" + token
        if content_type:
            sent["Content-Type"] = content_type
        conn = HTTPConnection("127.0.0.1", http.server_port, timeout=120)
        try:
            conn.request(method, path, body=body if method == "POST" else None, headers=sent)
            response = conn.getresponse()
            return response.status, json.loads(response.read() or b"{}")
        finally:
            conn.close()

    def upload(token, purpose, filename, data):
        content_type, body = _multipart(purpose, filename, data)
        return call("POST", "/api/v1/demo2/documents/parse", token, body, content_type)

    yield SimpleNamespace(call=call, upload=upload, env=env, logs=tmp_path / "document_logs", port=http.server_port)
    http.shutdown()
    http.server_close()
    thread.join(3)


def _log_lines(folder):
    return [json.loads(line) for path in sorted(folder.glob("document_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_http_parse_read_isolation_and_expiry(http_env, samples):
    env, upload, call = http_env.env, http_env.upload, http_env.call
    status, body = upload(env.tokens["a"], "course_task", "林晓-认识人民币.pdf", samples.pdf)
    assert status == 200, body
    result = body["result"]
    parse_id = result["parse_id"]
    assert parse_id.startswith("dp-") and result["status"] == "parsed" and result["page_count"] == 3
    assert "original_name" not in result and result["expires_at"] > result["created_at"]

    status, body = call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}", env.tokens["a"])
    assert status == 200 and body["result"]["candidates"] == result["candidates"]
    assert call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}")[0] == 401
    status, body = call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}", env.tokens["b"])
    assert (status, body["error"]["code"]) == (403, "parse_forbidden")
    status, body = call("GET", "/api/v1/demo2/documents/parse?parse_id=dp-" + "0" * 32, env.tokens["a"])
    assert (status, body["error"]["code"]) == (404, "parse_not_found")
    assert call("GET", "/api/v1/demo2/documents/parse?parse_id=../x", env.tokens["a"])[0] == 400
    assert call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}", env.tokens["admin"])[0] == 403

    with env.records._connect() as db:
        just_expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        db.execute("UPDATE demo2_document_parses SET expires_at=? WHERE parse_id=?", (just_expired, parse_id))
    status, body = call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}", env.tokens["a"])
    assert (status, body["error"]["code"]) == (410, "parse_expired")
    # Next upload purges expired content; the tombstone still answers 410.
    upload(env.tokens["a"], "iep", "王小明_IEP.docx", samples.iep)
    with env.records._connect() as db:
        row = db.execute("SELECT body, purged_at FROM demo2_document_parses WHERE parse_id=?", (parse_id,)).fetchone()
    assert row[0] is None and row[1]
    assert call("GET", f"/api/v1/demo2/documents/parse?parse_id={parse_id}", env.tokens["a"])[0] == 410


def test_http_rejections(http_env, samples):
    env, upload, call = http_env.env, http_env.upload, http_env.call
    token = env.tokens["a"]
    cases = [("notes.pdf", "课程名称：纯文本".encode("utf-8"), 400, "unsupported_document_type"),
             ("photo.png", samples.png, 400, "unsupported_document_type"),
             ("setup.exe", b"MZ\x90\x00" + bytes(200), 400, "unsupported_document_type"),
             ("big.pdf", b"%PDF-1.4\n" + bytes(parser.MAX_DOCUMENT_BYTES + 1024), 413, "document_too_large"),
             ("damaged.pdf", samples.pdf[:3000], 400, "document_parse_failed"),
             ("locked.pdf", samples.encrypted, 400, "document_encrypted")]
    for name, data, expected_status, code in cases:
        status, body = upload(token, "course_task", name, data)
        assert (status, body["error"]["code"]) == (expected_status, code), name
    status, body = upload(token, "lesson", "课程.pdf", samples.pdf)
    assert (status, body["error"]["code"]) == (400, "invalid_purpose")
    huge = b"%PDF-1.4\n" + bytes(parser.MAX_DOCUMENT_BYTES + parser.MAX_MULTIPART_OVERHEAD)
    status, body = upload(token, "course_task", "huge.pdf", huge)
    assert (status, body["error"]["code"]) == (413, "document_too_large")
    content_type, multipart = _multipart("iep", "x.pdf", samples.pdf)
    assert call("POST", "/api/v1/demo2/documents/parse", None, multipart, content_type)[0] == 401
    assert call("POST", "/api/v1/demo2/documents/parse", env.tokens["admin"], multipart, content_type)[0] == 403
    status, body = call("POST", "/api/v1/demo2/documents/parse", token, b"{}", "application/json")
    assert (status, body["error"]["code"]) == (415, "multipart_required")


def test_scanned_upload_returns_needs_manual_entry(http_env, samples, monkeypatch):
    monkeypatch.setenv(parser.OCR_ENV, "0")
    parser.reset_ocr_cache()
    try:
        status, body = http_env.upload(http_env.env.tokens["a"], "iep", "scan.pdf", samples.scanned)
    finally:
        parser.reset_ocr_cache()
    assert status == 200
    assert body["result"]["status"] == "needs_manual_entry" and body["result"]["manual_entry_required"] is True
    assert body["result"]["blocks"] == []


def test_originals_and_results_are_encrypted_at_rest(http_env, samples):
    env = http_env.env
    status, body = http_env.upload(env.tokens["a"], "iep", "王小明_IEP.docx", samples.iep)
    assert status == 200
    parse_id = body["result"]["parse_id"]
    store = DocumentParseStore(env.records)
    sealed = store._original_path(parse_id).read_bytes()
    assert sealed.startswith(b"RXDOC1\n") and samples.iep not in sealed and b"word/document.xml" not in sealed
    assert (store._original_path(parse_id).stat().st_mode & 0o777) == 0o600
    with sqlite3.connect(env.records.db_path) as db:
        row = db.execute("SELECT body FROM demo2_document_parses WHERE parse_id=?", (parse_id,)).fetchone()
    for secret in ("王小明", "110101201603081234", "孤独症", "能认出1元硬币"):
        assert secret.encode("utf-8") not in row[0]
    database_bytes = Path(env.records.db_path).read_bytes()
    assert "110101201603081234".encode() not in database_bytes
    account_id = env.accounts["a"]["account_id"]
    assert store.read_original(account_id, parse_id) == ("docx", samples.iep)
    with pytest.raises(parser.DocumentError) as caught:
        store.read_original(env.accounts["b"]["account_id"], parse_id)
    assert caught.value.status == 403


def test_debug_log_records_operations_without_content(http_env, samples, monkeypatch):
    env, upload = http_env.env, http_env.upload
    upload(env.tokens["a"], "iep", "王小明_IEP.docx", samples.iep)
    upload(env.tokens["a"], "course_task", "王小明.png", samples.png)
    monkeypatch.setenv(parser.OCR_ENV, "0")
    parser.reset_ocr_cache()
    try:
        upload(env.tokens["a"], "iep", "王小明扫描.pdf", samples.scanned)
    finally:
        parser.reset_ocr_cache()
    lines = _log_lines(http_env.logs)
    operations = [line["operation"] for line in lines]
    for operation in ("document_upload", "document_parse", "document_reject", "document_ocr"):
        assert operation in operations
    parse = next(line for line in lines if line["operation"] == "document_parse" and line["result"] == "parsed")
    for key in ("ts", "purpose", "file_type", "byte_size", "page_count", "candidate_count", "duration_ms", "result"):
        assert key in parse
    assert parse["purpose"] == "iep" and parse["file_type"] == "docx" and parse["candidate_count"] > 10
    reject = next(line for line in lines if line["operation"] == "document_reject")
    assert reject["code"] == "unsupported_document_type" and reject["http_status"] == 400
    ocr = next(line for line in lines if line["operation"] == "document_ocr")
    assert ocr["result"] == "unavailable"
    raw = "".join(path.read_text(encoding="utf-8") for path in http_env.logs.glob("*.jsonl"))
    for secret in ("王小明", "110101201603081234", "孤独症", "能认出1元硬币", ".docx", "扫描"):
        assert secret not in raw


def test_gateway_allows_document_parse_with_20mb_budget():
    path = "/api/v1/demo2/documents/parse"
    assert path in gateway._GET_API and path in gateway._POST_API and path not in gateway._PUBLIC_UPSTREAM
    assert gateway.DOCUMENT_MAX_BODY_BYTES >= parser.MAX_DOCUMENT_BYTES + 64 * 1024
    assert gateway.MAX_BODY_BYTES == 15 * 1024 * 1024
