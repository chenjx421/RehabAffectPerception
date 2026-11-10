"""Course-task / IEP document intake: type checks, lossless extraction, field candidates.

Only ``.pdf`` / ``.docx`` / ``.doc`` are accepted, and the file header must match
the extension; anything else is rejected instead of being read as plain text.
Every paragraph, list item, text box, header/footer line and table cell becomes a
``block`` with its page / paragraph / cell location, so nothing in the original is
dropped. Field candidates point back to those blocks; blocks that fit no field are
listed under ``other_content``. Sensitive fragments (ID numbers, phone numbers,
detailed addresses, diagnosis wording, names) are flagged for teacher review.

This module is pure: it never logs document text and never writes to disk except
temporary files for ``.doc`` conversion and OCR, removed before returning.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_MULTIPART_OVERHEAD = 256 * 1024
MAX_PDF_PAGES = 300
MAX_OCR_PAGES = 40
OCR_TIMEOUT_SECONDS = 90
DOC_CONVERT_TIMEOUT_SECONDS = 120
MAX_DOCX_ENTRIES = 3000
MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".doc")
PURPOSES = ("course_task", "iep")
OCR_ENV = "REHAB_DEMO2_DOCUMENT_OCR"
TESSERACT_ENV = "REHAB_TESSERACT"
SOFFICE_ENV = "REHAB_SOFFICE"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MESSAGES = {
    "unsupported_document_type": "仅支持上传 PDF、Word（.docx / .doc）文件，文件内容需与扩展名一致",
    "document_too_large": "文件不能超过 20 MB",
    "document_too_many_pages": f"PDF 页数不能超过 {MAX_PDF_PAGES} 页",
    "document_empty": "文件为空，请重新选择",
    "document_parse_failed": "文件已损坏或无法读取，请在 Word/PDF 软件中重新导出后上传",
    "document_encrypted": "文件设置了打开密码，请取消密码保护后重新上传",
    "doc_conversion_unavailable": "当前服务器无法直接读取 .doc 旧格式，请在 Word 中另存为 .docx 或 PDF 后再上传",
    "invalid_purpose": "请选择文件用途：课程任务（course_task）或 IEP（iep）",
    "invalid_multipart": "上传内容格式无效，请从平台页面重新选择文件",
}


class DocumentError(Exception):
    """Safe error: code and Chinese message only, never document content."""

    def __init__(self, status: int, code: str, message: str = ""):
        self.status = status
        self.code = code
        self.message = message or _MESSAGES.get(code, "文件处理失败")
        super().__init__(self.message)


def fail(status: int, code: str, message: str = "") -> DocumentError:
    return DocumentError(status, code, message)


# ---------------------------------------------------------------------------
# multipart / type validation
# ---------------------------------------------------------------------------

def _disposition_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for match in re.finditer(r';\s*([A-Za-z0-9_*.-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)', value):
        key, raw = match.group(1).lower(), match.group(2).strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = re.sub(r'\\(.)', r'\1', raw[1:-1])
        params[key] = raw
    star = params.get("filename*")
    if star and "''" in star:
        from urllib.parse import unquote
        charset, _, encoded = star.partition("''")
        try:
            params["filename"] = unquote(encoded, encoding=charset or "utf-8", errors="strict")
        except (LookupError, UnicodeDecodeError):
            pass
    return params


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """Split a multipart/form-data body exactly; returns (fields, files)."""
    main, _, rest = (content_type or "").partition(";")
    if main.strip().lower() != "multipart/form-data":
        raise fail(415, "multipart_required", "请使用平台页面上传文件（multipart/form-data）")
    match = re.search(r'boundary\s*=\s*("?)([^";]{1,200})\1', rest, re.IGNORECASE)
    if not match:
        raise fail(400, "invalid_multipart")
    delimiter = b"\r\n--" + match.group(2).encode("latin-1")
    segments = (b"\r\n" + body).split(delimiter)
    if len(segments) < 3 or not segments[-1].startswith(b"--"):
        raise fail(400, "invalid_multipart")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for segment in segments[1:-1]:
        if not segment.startswith(b"\r\n"):
            raise fail(400, "invalid_multipart")
        head, separator, content = segment[2:].partition(b"\r\n\r\n")
        if not separator:
            raise fail(400, "invalid_multipart")
        headers: dict[str, str] = {}
        for line in head.split(b"\r\n"):
            name, colon, value = line.partition(b":")
            if not colon:
                raise fail(400, "invalid_multipart")
            headers[name.strip().lower().decode("latin-1")] = value.strip().decode("utf-8", "replace")
        disposition = headers.get("content-disposition", "")
        if not disposition.lower().startswith("form-data"):
            raise fail(400, "invalid_multipart")
        params = _disposition_params(disposition)
        name = params.get("name", "")
        if not name or name in fields or name in files:
            raise fail(400, "invalid_multipart")
        if "filename" in params:
            files[name] = (params["filename"], content)
        else:
            try:
                fields[name] = content.decode("utf-8")
            except UnicodeDecodeError:
                raise fail(400, "invalid_multipart") from None
    return fields, files


def extension_of(filename: str) -> str:
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(name).suffix.lower()
    return suffix


def detect_document_type(filename: str, data: bytes) -> str:
    """Extension whitelist AND file-header check; returns ``pdf`` / ``docx`` / ``doc``."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise fail(413, "document_too_large")
    suffix = extension_of(filename)
    if suffix not in ALLOWED_EXTENSIONS:
        raise fail(400, "unsupported_document_type")
    if not data:
        raise fail(400, "document_empty")
    if suffix == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise fail(400, "unsupported_document_type")
        return "pdf"
    if suffix == ".doc":
        if not data.startswith(_OLE_MAGIC):
            raise fail(400, "unsupported_document_type")
        return "doc"
    if not data.startswith(b"PK\x03\x04"):
        raise fail(400, "unsupported_document_type")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise fail(400, "unsupported_document_type")
            if (len(entries) > MAX_DOCX_ENTRIES
                    or sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED):
                raise fail(400, "document_parse_failed", "Word 文件解压后内容过大，请精简后重新上传")
    except zipfile.BadZipFile:
        raise fail(400, "unsupported_document_type") from None
    return "docx"


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200d\ufeff]")
_LIST_MARKER = re.compile(
    r"^\s*(?:[\(（]?\s*(?:\d{1,3}|[一二三四五六七八九十百]{1,4}|[a-zA-Z])\s*[\)）]|"
    r"(?:\d{1,3}(?:\.\d{1,3}){0,3}|[a-zA-Z])\s*[.、．](?!\d)|"
    r"[一二三四五六七八九十百]{1,4}\s*[、.．]|"
    r"[①-⑳⑴-⒇●○◆◇■□▪•·\-–—*✓√]|第[一二三四五六七八九十百\d]{1,4}[条点项步课节])\s*"
)
_HEADING_MARKER = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百\d]{1,4}[部分章节单元]|[一二三四五六七八九十]{1,3}\s*[、.．]|[（(][一二三四五六七八九十]{1,3}[)）])"
)
_SENTENCE_END = tuple("。！？；：:.!?;）)」』”")


def clean_text(value: Any) -> str:
    text = _CONTROL.sub("", str(value or ""))
    # PDFs exported from Word often carry Kangxi radicals (⽬) for common ideographs.
    text = "".join(unicodedata.normalize("NFKC", ch) if "\u2e80" <= ch <= "\u2fdf" else ch for ch in text)
    text = text.replace("\u3000", " ").replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def match_key(text: str) -> str:
    """Comparison key: width-folded, no spaces, no list/heading numbering."""
    key = unicodedata.normalize("NFKC", text or "")
    key = _LIST_MARKER.sub("", key, count=1)
    key = _HEADING_MARKER.sub("", key, count=1)
    return re.sub(r"\s+", "", key)


def is_list_like(text: str) -> bool:
    return bool(_LIST_MARKER.match(text or ""))


# ---------------------------------------------------------------------------
# sensitive information
# ---------------------------------------------------------------------------

_ID_CARD = re.compile(r"(?<![0-9A-Za-z])(\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]|\d{15})(?![0-9A-Za-z])")
_MOBILE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")
_ADDRESS = re.compile(
    r"(?:[\u4e00-\u9fa5]{2,}(?:省|自治区|市|区|县|镇|乡|街道))+[\u4e00-\u9fa5\d\-]{0,30}?"
    r"(?:\d+\s*(?:号|弄|栋|幢|单元|室|楼)|路\d+|村\d+组|小区|公寓|新村|花园\d*)"
)
_ADDRESS_LABEL = re.compile(r"(?:家庭住址|现住址|户籍地址|联系地址|住址|地址)\s*[:：]\s*\S")
_DIAGNOSIS_WORDS = (
    "诊断", "确诊", "自闭症", "孤独症", "阿斯伯格", "智力障碍", "智力低下", "精神发育迟滞", "发育迟缓", "脑瘫",
    "脑性瘫痪", "唐氏", "21三体", "癫痫", "多动症", "注意缺陷", "ADHD", "抽动", "听力障碍", "听障", "视力障碍",
    "视障", "言语障碍", "语言障碍", "精神障碍", "精神分裂", "抑郁", "焦虑症", "病史", "用药", "服药", "药物",
    "残疾证", "残疾等级", "医院", "智商", "IQ", "韦氏", "染色体", "基因",
)


def sensitive_types(text: str) -> list[str]:
    found: list[str] = []
    value = unicodedata.normalize("NFKC", text or "")
    # A mistyped checksum is still somebody's ID number: the format alone is enough.
    if _ID_CARD.search(value):
        found.append("id_card")
    if _MOBILE.search(value) or _LANDLINE.search(value):
        found.append("phone")
    if _ADDRESS.search(value) or _ADDRESS_LABEL.search(value):
        found.append("address")
    upper = value.upper()
    if any(word.upper() in upper for word in _DIAGNOSIS_WORDS):
        found.append("diagnosis")
    return found


SENSITIVE_LABELS = {
    "id_card": "身份证号", "phone": "联系电话", "address": "详细住址", "diagnosis": "诊断/病历信息",
    "name": "学生姓名", "birth_date": "出生日期",
}


# ---------------------------------------------------------------------------
# field dictionaries
# ---------------------------------------------------------------------------

PERSONAL_ALIASES = ("身份证号码", "身份证号", "身份证", "证件号码", "家庭住址", "现住址", "户籍地址", "联系地址", "住址",
                    "家长联系电话", "家长电话", "联系电话", "联系方式", "手机号码", "手机号", "手机", "电话", "监护人")
# (field, label, aliases, multi-valued)
COURSE_FIELDS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("course_name", "课程名称", ("课程名称", "课程名", "课题名称", "课题", "课名", "教学内容", "课程"), False),
    ("subject", "学科/领域", ("学科领域", "学科", "科目", "领域"), False),
    ("grade_class", "年级/班级", ("年级班级", "年级/班级", "授课班级", "班级", "年级"), False),
    ("lesson_date", "上课日期", ("上课日期", "授课日期", "上课时间", "授课时间", "教学日期", "日期", "时间"), False),
    ("teacher", "授课教师", ("授课教师", "任课教师", "执教教师", "执教者", "执教", "授课人", "教师"), False),
    ("course_goals", "课程任务目标", ("课程任务目标", "课堂任务目标", "教学目标", "课程目标", "任务目标", "学习目标",
                                     "本课目标", "课时目标", "目标"), True),
    ("evaluation_criteria", "评价标准", ("评价标准", "评估标准", "评分标准", "评价要点", "评价方式", "评价方法", "评价"), True),
    ("pass_criteria", "通过标准", ("通过标准", "达成标准", "合格标准", "达标标准", "掌握标准", "完成标准"), True),
    ("measurement_conditions", "测量条件", ("测量条件", "测评条件", "评估条件", "观察条件", "测量环境", "施测条件",
                                          "测量方式", "测量方法", "观测条件"), True),
    ("personal_info", "身份与联系信息", PERSONAL_ALIASES, True),
)
IEP_FIELDS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("student_name", "学生姓名", ("学生姓名", "姓名"), False),
    ("birth_date", "出生日期", ("出生日期", "出生年月", "生日"), False),
    ("grade_class", "年级/班级", ("年级班级", "就读班级", "班级", "年级"), False),
    ("diagnosis", "诊断/障碍类型", ("医学诊断", "诊断结果", "诊断", "障碍类型", "残疾类型", "障碍类别"), False),
    ("present_level", "现有能力水平", ("现有能力水平", "现有能力", "能力现状", "现状描述", "现有水平", "学生现状",
                                      "能力评估", "基本情况", "优势与不足", "优势", "弱势"), True),
    ("long_term_goals", "长期目标", ("长期目标", "学年目标", "年度目标", "学期目标"), True),
    ("short_term_goals", "短期目标", ("短期目标", "阶段目标", "月目标", "单元目标", "具体目标"), True),
    ("support_needs", "支持需求", ("支持需求", "支持需要", "所需支持", "支持与服务", "相关服务", "辅助支持", "支持方式"), True),
    ("teaching_strategies", "教学策略", ("教学策略", "教学方法", "教学措施", "干预策略", "教学建议", "策略"), True),
    ("assessment_methods", "评估方式", ("评估方式", "评估方法", "评价方式", "评量方式", "评估标准", "评价方法", "评估"), True),
    ("responsible_persons", "负责人", ("负责人", "执行人", "责任人", "负责教师", "实施者", "实施人"), True),
    ("period", "周期", ("实施周期", "起止时间", "起止日期", "执行时间", "时间安排", "周期", "期限", "评估日期"), True),
    ("personal_info", "身份与联系信息", PERSONAL_ALIASES, True),
)
_ALWAYS_SENSITIVE = {"student_name": "name", "birth_date": "birth_date", "diagnosis": "diagnosis"}
# personal_info values are flagged by content (ID/phone/address); a bare label still needs review.
_REVIEW_FIELDS = {"personal_info"}
_GOAL_FIELDS = {"course_goals", "long_term_goals", "short_term_goals"}
_GOAL_DETAIL_FIELDS = {"evaluation_criteria", "pass_criteria", "measurement_conditions", "assessment_methods",
                       "teaching_strategies", "support_needs", "responsible_persons", "period"}


_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_ORDINAL = r"(\d{1,2}|[一二三四五六七八九十]{1,3}|[（(]\d{1,2}[)）]|[（(][一二三四五六七八九十]{1,3}[)）])"
# "目标1" / "目标一" / "目标(2)": a goal label followed by the goal's own number.
_NUMBERED_LABEL = re.compile(r"^([\u4e00-\u9fa5]{2,8}?)" + _ORDINAL + r"$")
# A table cell that only points back to a goal: "目标1"、"目标一"、"1"、"（2）".
_GOAL_REFERENCE = re.compile(r"^([\u4e00-\u9fa5]{0,8}?)" + _ORDINAL + r"[.、．:：]?$")


def ordinal_number(token: str) -> int | None:
    token = re.sub(r"[（()）]", "", token)
    if token.isdigit():
        return int(token)
    if not token or any(ch not in _CN_DIGITS for ch in token):
        return None
    if token == "十":
        return 10
    if token.startswith("十"):
        return 10 + _CN_DIGITS[token[1]]
    if len(token) == 1:
        return _CN_DIGITS[token]
    if len(token) == 2 and token[1] == "十":
        return _CN_DIGITS[token[0]] * 10
    if len(token) == 3 and token[1] == "十":
        return _CN_DIGITS[token[0]] * 10 + _CN_DIGITS[token[2]]
    return None


def field_spec(purpose: str) -> tuple[tuple[str, str, tuple[str, ...], bool], ...]:
    return COURSE_FIELDS if purpose == "course_task" else IEP_FIELDS


class _Labels:
    _PERSONAL_NO_COLON = re.compile(
        "^(" + "|".join(sorted(map(re.escape, PERSONAL_ALIASES), key=len, reverse=True)) + r")\s+(?=\S*\d)(.+)$")

    def _personal_without_colon(self, text: str) -> tuple[str, str] | None:
        """``家长电话 021-…`` — contact lines are often written without a colon."""
        if "personal_info" not in self.labels:
            return None
        match = self._PERSONAL_NO_COLON.match(text.strip())
        return ("personal_info", match.group(2).strip()) if match else None

    def __init__(self, purpose: str):
        self.spec = field_spec(purpose)
        self.labels = {field: label for field, label, _, _ in self.spec}
        self.multi = {field: multi for field, _, _, multi in self.spec}
        pairs = [(alias, field) for field, _, aliases, _ in self.spec for alias in aliases]
        # Longest alias first: 课程任务目标 must win over 目标.
        self.aliases = sorted(pairs, key=lambda pair: -len(pair[0]))

    def exact(self, text: str) -> str | None:
        key = match_key(text).rstrip(":：")
        key = re.sub(r"[（(][^）)]{0,12}[）)]$", "", key)
        if not key or len(key) > 16:
            return None
        for alias, field in self.aliases:
            if key == alias:
                return field
        return None

    def key_value(self, text: str) -> tuple[str, str] | None:
        """``标签：值`` (the value may be empty → section heading)."""
        personal = self._personal_without_colon(text)
        if personal:
            return personal
        stripped = _HEADING_MARKER.sub("", _LIST_MARKER.sub("", unicodedata.normalize("NFKC", text), count=1), count=1)
        head, sep, value = stripped.partition(":")
        if not sep or len(head) > 20:
            return None
        head_key = re.sub(r"\s+", "", head)
        numbered = _NUMBERED_LABEL.match(head_key)
        if numbered and value.strip():
            # "目标1：能指认…" (Word auto-numbering leaves no list marker): the label carries the goal's
            # own number, so it is one goal item whose text keeps that number for later references.
            for alias, field in self.aliases:
                if numbered.group(1) == alias and field in _GOAL_FIELDS:
                    return field, _LIST_MARKER.sub("", text, count=1).strip()
        head_key = re.sub(r"[（(][^）)]{0,12}[）)]$", "", head_key)
        for alias, field in self.aliases:
            if head_key == alias:
                # Keep the original (non-folded) value text.
                original = re.split(r"[:：]", text, maxsplit=1)
                return field, (original[1] if len(original) == 2 else value).strip()
        return None


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def _pdf_open(data: bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise fail(503, "document_parser_unavailable", "文档解析组件未安装，请联系管理员") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        encrypted = bool(reader.is_encrypted)
    except Exception:
        raise fail(400, "document_parse_failed") from None
    password = None
    if encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise fail(400, "document_encrypted")
        password = ""
    try:
        page_count = len(reader.pages)
    except Exception:
        raise fail(400, "document_parse_failed") from None
    if page_count <= 0:
        raise fail(400, "document_parse_failed")
    if page_count > MAX_PDF_PAGES:
        raise fail(413, "document_too_many_pages")
    try:
        import pdfplumber
    except ImportError:
        raise fail(503, "document_parser_unavailable", "文档解析组件未安装，请联系管理员") from None
    try:
        pdf = pdfplumber.open(io.BytesIO(data), password=password)
        _ = len(pdf.pages)
    except Exception as exc:
        if "password" in type(exc).__name__.lower() or "encrypt" in type(exc).__name__.lower():
            raise fail(400, "document_encrypted") from None
        raise fail(400, "document_parse_failed") from None
    return pdf, page_count


def _line_size(line: dict[str, Any]) -> float:
    chars = line.get("chars") or []
    sizes = [float(c.get("size") or 0) for c in chars if str(c.get("text", "")).strip()]
    return round(sum(sizes) / len(sizes), 1) if sizes else 0.0


def _pdf_page_items(page) -> tuple[list[dict[str, Any]], bool]:
    """Lines (outside tables) and tables of one page in reading order."""
    try:
        tables = page.find_tables()
    except Exception:
        tables = []
    boxes = [table.bbox for table in tables]

    def outside(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 - 1 <= cx <= x1 + 1 and top - 1 <= cy <= bottom + 1 for x0, top, x1, bottom in boxes)

    items: list[dict[str, Any]] = []
    try:
        lines = page.filter(outside).extract_text_lines(strip=True, return_chars=True)
    except Exception:
        lines = []
    for line in lines:
        text = clean_text(line.get("text", ""))
        if text:
            items.append(dict(type="line", top=float(line["top"]), bottom=float(line["bottom"]),
                              x0=float(line["x0"]), x1=float(line["x1"]), text=text, size=_line_size(line)))
    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            rows = []
        if rows:
            items.append(dict(type="table", top=float(table.bbox[1]), rows=rows))
    has_text = bool(page.chars)
    items.sort(key=lambda item: (round(item["top"], 0), item.get("x0", 0)))
    return items, has_text


def _merge_lines(lines: list[dict[str, Any]], body_size: float) -> list[dict[str, Any]]:
    """Join wrapped lines of one paragraph; list items and headings stay separate."""
    if not lines:
        return []
    right = max(line["x1"] for line in lines)
    paragraphs: list[dict[str, Any]] = []
    for line in lines:
        previous = paragraphs[-1] if paragraphs else None
        size = line["size"] or body_size
        if (previous is not None
                and not previous["text"].endswith(_SENTENCE_END)
                and previous["last_x1"] >= right - 1.6 * max(size, 1)
                and abs(previous["size"] - line["size"]) < 0.6
                and line["top"] - previous["bottom"] < 1.2 * max(size, 1)
                and not is_list_like(line["text"])
                and not _HEADING_MARKER.match(line["text"])):
            joiner = " " if re.search(r"[A-Za-z0-9]$", previous["text"]) and re.match(r"[A-Za-z0-9]", line["text"]) else ""
            previous["text"] += joiner + line["text"]
            previous["bottom"] = line["bottom"]
            previous["last_x1"] = line["x1"]
            previous["line_count"] += 1
            continue
        paragraphs.append(dict(text=line["text"], top=line["top"], bottom=line["bottom"], last_x1=line["x1"],
                               size=line["size"], line_count=1))
    return paragraphs


def _heading_level(text: str, size: float, body_size: float) -> int:
    if len(text) > 40 or text.endswith(("。", "；", ";")):
        return 0
    if body_size and size >= body_size + 3:
        return 1
    if body_size and size >= body_size + 1:
        return 2
    if re.match(r"^\s*第[一二三四五六七八九十百\d]{1,4}[部分章节单元]", text) or re.match(r"^\s*[一二三四五六七八九十]{1,3}\s*[、.．]", text):
        return 2
    if re.match(r"^\s*[（(][一二三四五六七八九十]{1,3}[)）]", text):
        return 3
    return 0


@lru_cache(maxsize=1)
def _tesseract_info() -> tuple[str, str] | None:
    if os.getenv(OCR_ENV, "").strip().lower() in {"0", "false", "off", "no"}:
        return None
    binary = os.getenv(TESSERACT_ENV, "").strip() or shutil.which("tesseract") or ""
    if not binary or not Path(binary).is_file():
        return None
    try:
        output = subprocess.run([binary, "--list-langs"], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    langs = set((output.stdout + output.stderr).decode("utf-8", "replace").split())
    if "chi_sim" in langs:
        return binary, "chi_sim+eng" if "eng" in langs else "chi_sim"
    return None


def ocr_available() -> bool:
    return _tesseract_info() is not None


def reset_ocr_cache() -> None:
    _tesseract_info.cache_clear()


def _ocr_page(page) -> str:
    info = _tesseract_info()
    if info is None:
        return ""
    binary, langs = info
    with tempfile.TemporaryDirectory(prefix="rx-ocr-") as folder:
        image_path = Path(folder) / "page.png"
        page.to_image(resolution=220).original.convert("L").save(image_path)
        try:
            result = subprocess.run([binary, str(image_path), "stdout", "-l", langs, "--psm", "6"],
                                    capture_output=True, timeout=OCR_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode != 0:
            return ""
        text = result.stdout.decode("utf-8", "replace")
    # Tesseract puts spaces between CJK glyphs; drop them, keep Latin word spacing.
    text = re.sub(r"(?<=[\u4e00-\u9fff，。：；、！？（）])[ \t]+(?=[\u4e00-\u9fff，。：；、！？（）\d])|"
                  r"(?<=[\u4e00-\u9fff\d])[ \t]+(?=[\u4e00-\u9fff])", "", text)
    # A leading "1." is commonly read as "|." or "l.".
    text = re.sub(r"(?m)^[ \t]*[|lI][ \t]*[.．、](?=[ \t]*[\u4e00-\u9fff])", "1.", text)
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t]*:[ \t]*", "：", text)


class _Blocks:
    def __init__(self):
        self.items: list[dict[str, Any]] = []
        self.paragraph_index = 0
        self.table_index = 0

    def add(self, kind: str, text: str, *, page: int | None, source: str, heading_level: int = 0,
            list_level: int | None = None, page_paragraph: int | None = None) -> dict[str, Any] | None:
        text = clean_text(text)
        if not text:
            return None
        self.paragraph_index += 1
        block = dict(block_id=f"b{len(self.items) + 1:04d}", kind=kind, page=page,
                     paragraph_index=self.paragraph_index, page_paragraph=page_paragraph,
                     heading_level=heading_level, list_level=list_level, text=text, source=source)
        self.items.append(block)
        return block

    def add_table(self, rows: list[list[Any]], *, page: int | None, source: str,
                  merged: set[tuple[int, int]] | None = None) -> dict[str, Any] | None:
        cells: list[dict[str, Any]] = []
        col_count = 0
        for r, row in enumerate(rows):
            col_count = max(col_count, len(row))
            for c, value in enumerate(row):
                if value is None or (merged and (r, c) in merged):
                    continue
                text = clean_text(value)
                if text:
                    cells.append(dict(cell_id=f"r{r + 1}c{c + 1}", row=r + 1, col=c + 1, text=text))
        if not cells:
            return None
        self.table_index += 1
        self.paragraph_index += 1
        block = dict(block_id=f"b{len(self.items) + 1:04d}", kind="table", page=page,
                     paragraph_index=self.paragraph_index, page_paragraph=None, heading_level=0, list_level=None,
                     table_index=self.table_index, row_count=len(rows), col_count=col_count,
                     cells=cells, text="\n".join(" | ".join(clean_text(v) for v in row if v) for row in rows if row),
                     source=source)
        self.items.append(block)
        return block


def extract_pdf(data: bytes) -> dict[str, Any]:
    pdf, page_count = _pdf_open(data)
    blocks = _Blocks()
    empty_pages: list[int] = []
    ocr_pages: list[int] = []
    ocr_failed_pages: list[int] = []
    ocr_ms = 0.0
    try:
        page_items: list[tuple[int, list[dict[str, Any]], bool, Any]] = []
        sizes: list[float] = []
        for number, page in enumerate(pdf.pages, start=1):
            try:
                items, has_text = _pdf_page_items(page)
            except Exception:
                raise fail(400, "document_parse_failed") from None
            page_items.append((number, items, has_text, page))
            sizes += [item["size"] for item in items if item["type"] == "line" and item["size"]]
        body_size = sorted(sizes)[len(sizes) // 2] if sizes else 0.0
        ocr_on = ocr_available()
        for number, items, has_text, page in page_items:
            if not items:
                if not ocr_on or len(ocr_pages) + len(ocr_failed_pages) >= MAX_OCR_PAGES:
                    empty_pages.append(number)
                    continue
                started = time.monotonic()
                try:
                    text = _ocr_page(page)
                except Exception:
                    text = ""
                ocr_ms += (time.monotonic() - started) * 1000
                paragraphs = [p for p in re.split(r"\n\s*\n", text) if clean_text(p)]
                if not paragraphs:
                    ocr_failed_pages.append(number)
                    empty_pages.append(number)
                    continue
                ocr_pages.append(number)
                for index, paragraph in enumerate(paragraphs, start=1):
                    for line_index, line in enumerate(clean_text(paragraph).split("\n")):
                        kind = "list_item" if is_list_like(line) else "paragraph"
                        blocks.add(kind, line, page=number, source="ocr", page_paragraph=index)
                continue
            lines: list[dict[str, Any]] = []
            ordinal = 0

            def flush() -> None:
                nonlocal ordinal
                for paragraph in _merge_lines(lines, body_size):
                    ordinal += 1
                    level = _heading_level(paragraph["text"], paragraph["size"], body_size)
                    kind = "heading" if level else "list_item" if is_list_like(paragraph["text"]) else "paragraph"
                    blocks.add(kind, paragraph["text"], page=number, source="text_layer", heading_level=level,
                               page_paragraph=ordinal)
                lines.clear()

            for item in items:
                if item["type"] == "line":
                    lines.append(item)
                else:
                    flush()
                    blocks.add_table(item["rows"], page=number, source="text_layer")
            flush()
    finally:
        try:
            pdf.close()
        except Exception:
            pass
    return dict(blocks=blocks.items, page_count=page_count, page_count_estimated=False, empty_pages=empty_pages,
                ocr=dict(available=ocr_available(), used=bool(ocr_pages), pages=ocr_pages,
                         failed_pages=ocr_failed_pages, duration_ms=round(ocr_ms, 1)))


# ---------------------------------------------------------------------------
# Word extraction
# ---------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _xml_paragraph_text(element) -> str:
    """Text of one w:p including tabs/breaks but excluding nested text boxes."""
    parts: list[str] = []
    for node in element.iter():
        tag = node.tag
        if tag == _W + "t":
            # Skip runs that live inside a text box of this paragraph.
            parent = node.getparent()
            inside_box = False
            while parent is not None and parent is not element:
                if parent.tag == _W + "txbxContent":
                    inside_box = True
                    break
                parent = parent.getparent()
            if not inside_box:
                parts.append(node.text or "")
        elif tag == _W + "tab":
            parts.append("\t")
        elif tag in (_W + "br", _W + "cr"):
            parts.append("\n")
    return "".join(parts)


def _paragraph_style(paragraph) -> tuple[int, int | None]:
    """(heading level, list level) from style / outline / numbering."""
    level = 0
    try:
        style_name = paragraph.style.name if paragraph.style is not None else ""
    except Exception:
        style_name = ""
    match = re.search(r"(?:Heading|标题)\s*(\d)", style_name or "", re.IGNORECASE)
    if match:
        level = int(match.group(1))
    elif (style_name or "").lower() in {"title", "标题"}:
        level = 1
    ppr = paragraph._p.pPr
    if not level and ppr is not None:
        outline = ppr.find(_W + "outlineLvl")
        if outline is not None:
            try:
                value = int(outline.get(_W + "val"))
                if value < 9:
                    level = value + 1
            except (TypeError, ValueError):
                pass
    list_level = None
    if ppr is not None and ppr.find(_W + "numPr") is not None:
        ilvl = ppr.find(_W + "numPr").find(_W + "ilvl")
        try:
            list_level = int(ilvl.get(_W + "val")) if ilvl is not None else 0
        except (TypeError, ValueError):
            list_level = 0
    elif "list" in (style_name or "").lower() or "列表" in (style_name or ""):
        list_level = 0
    return level, list_level


def _docx_table_rows(table) -> tuple[list[list[str]], set[tuple[int, int]]]:
    rows: list[list[str]] = []
    merged: set[tuple[int, int]] = set()
    # Hold the element proxies themselves: id() of a freed lxml proxy can be reused.
    seen: set[Any] = set()
    for r, row in enumerate(table.rows):
        values: list[str] = []
        try:
            cells = row.cells
        except Exception:
            cells = []
        for c, cell in enumerate(cells):
            tc = cell._tc
            if tc in seen:
                merged.add((r, c))
                values.append("")
                continue
            seen.add(tc)
            tcpr = tc.tcPr
            vmerge = tcpr.find(_W + "vMerge") if tcpr is not None else None
            if vmerge is not None and vmerge.get(_W + "val") in (None, "continue"):
                merged.add((r, c))
                values.append("")
                continue
            # Every paragraph in the cell, including nested tables and text boxes.
            texts = [_xml_paragraph_text(p) for p in tc.iter(_W + "p")]
            values.append("\n".join(t for t in texts if t.strip()))
        rows.append(values)
    return rows, merged


def extract_docx(data: bytes) -> dict[str, Any]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        raise fail(503, "document_parser_unavailable", "文档解析组件未安装，请联系管理员") from None
    try:
        document = Document(io.BytesIO(data))
    except Exception:
        raise fail(400, "document_parse_failed") from None
    blocks = _Blocks()
    body = document.element.body
    uses_rendered_breaks = bool(body.xpath(".//w:lastRenderedPageBreak"))
    page = 1

    def page_breaks(element) -> int:
        if uses_rendered_breaks:
            return len(element.xpath(".//w:lastRenderedPageBreak"))
        return len(element.xpath('.//w:br[@w:type="page"]'))

    def walk(container) -> None:
        nonlocal page
        for child in container.iterchildren():
            tag = child.tag
            if tag == _W + "p":
                paragraph = Paragraph(child, document)
                breaks = page_breaks(child)
                ppr = child.pPr
                if ppr is not None and ppr.find(_W + "pageBreakBefore") is not None and not uses_rendered_breaks:
                    page += 1
                text = _xml_paragraph_text(child)
                level, list_level = _paragraph_style(paragraph)
                if text.strip():
                    if level:
                        kind = "heading"
                    elif list_level is not None or is_list_like(text):
                        kind = "list_item"
                    else:
                        kind = "paragraph"
                    # Soft line breaks inside one paragraph stay one block.
                    blocks.add(kind, text, page=page, source="docx", heading_level=level, list_level=list_level)
                seen_boxes: set[str] = set()
                for box in child.iter(_W + "txbxContent"):
                    for box_paragraph in box.iterchildren(_W + "p"):
                        box_text = clean_text(_xml_paragraph_text(box_paragraph))
                        if box_text and box_text not in seen_boxes:
                            seen_boxes.add(box_text)
                            blocks.add("textbox", box_text, page=page, source="docx")
                page += breaks
            elif tag == _W + "tbl":
                rows, merged = _docx_table_rows(Table(child, document))
                blocks.add_table(rows, page=page, source="docx", merged=merged)
                page += page_breaks(child)
            elif tag == _W + "sdt":
                content = child.find(_W + "sdtContent")
                if content is not None:
                    walk(content)

    try:
        walk(body)
        seen: set[tuple[str, str]] = set()
        for section in document.sections:
            for kind, part in (("header", section.header), ("footer", section.footer)):
                try:
                    if part.is_linked_to_previous:
                        continue
                    texts = [_xml_paragraph_text(p) for p in part._element.iter(_W + "p")]
                except Exception:
                    continue
                for text in texts:
                    cleaned = clean_text(text)
                    if cleaned and (kind, cleaned) not in seen:
                        seen.add((kind, cleaned))
                        blocks.add(kind, cleaned, page=None, source="docx")
    except DocumentError:
        raise
    except Exception:
        raise fail(400, "document_parse_failed") from None
    return dict(blocks=blocks.items, page_count=page, page_count_estimated=True, empty_pages=[],
                ocr=dict(available=ocr_available(), used=False, pages=[], failed_pages=[], duration_ms=0.0))


def _soffice_binary() -> str:
    configured = os.getenv(SOFFICE_ENV, "").strip()
    candidates = [configured, shutil.which("soffice") or "", shutil.which("libreoffice") or "",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def convert_doc_to_docx(data: bytes) -> bytes:
    binary = _soffice_binary()
    if not binary:
        raise fail(422, "doc_conversion_unavailable")
    with tempfile.TemporaryDirectory(prefix="rx-doc-") as folder:
        source = Path(folder) / "source.doc"
        source.write_bytes(data)
        profile = Path(folder) / "profile"
        command = [binary, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                   "--convert-to", "docx", "--outdir", folder, str(source)]
        try:
            subprocess.run(command, capture_output=True, timeout=DOC_CONVERT_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise fail(400, "document_parse_failed", "旧版 .doc 文件转换超时，请另存为 .docx 或 PDF 后再上传") from None
        except OSError:
            raise fail(422, "doc_conversion_unavailable") from None
        target = Path(folder) / "source.docx"
        if not target.is_file() or target.stat().st_size == 0:
            raise fail(400, "document_parse_failed", "旧版 .doc 文件无法读取，请另存为 .docx 或 PDF 后再上传")
        return target.read_bytes()


# ---------------------------------------------------------------------------
# field candidates
# ---------------------------------------------------------------------------

def _split_items(text: str, *, wrapped: bool) -> list[str]:
    """Split a multi-valued cell/paragraph into items only where the text is a list.

    PDF table cells wrap long text onto new lines, so plain line breaks there are
    re-joined; Word cell paragraphs and numbered lines stay separate items.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        starts = [index for index, line in enumerate(lines) if is_list_like(line)]
        if len(starts) >= 2 or (starts == [0] and not wrapped):
            if starts[0] != 0:
                starts.insert(0, 0)
            joiner = "" if wrapped else "\n"
            return [joiner.join(lines[a:b]) for a, b in zip(starts, starts[1:] + [len(lines)])]
        return ["".join(lines)] if wrapped else lines
    if lines:
        pieces = re.split(r"(?<=[。；;])\s*(?=(?:\d{1,2}|[（(]\d{1,2}[)）])[.、．)）])", lines[0])
        if len(pieces) > 1:
            return [piece.strip() for piece in pieces if piece.strip()]
    return lines


def _display_value(field_multi: bool, value: str) -> str:
    """Strip a leading list marker (``1.``、``（2）``) from list values; the block keeps the original."""
    if not field_multi:
        return value
    stripped = _LIST_MARKER.sub("", value, count=1).strip()
    return stripped or value


class _Candidates:
    def __init__(self, purpose: str, labels: _Labels):
        self.purpose = purpose
        self.labels = labels
        self.items: list[dict[str, Any]] = []
        self.used_blocks: set[str] = set()
        self.used_cells: set[tuple[str, str]] = set()
        self.goal_count = 0
        self.current_goal: str | None = None

    def add(self, field: str, value: str, block: dict[str, Any], confidence: float, *, method: str,
            cell: dict[str, Any] | None = None, group: str | None = None) -> None:
        value = clean_text(value)
        if not value:
            return
        if block.get("source") == "ocr":
            confidence *= 0.7
        matches = None
        if field in _GOAL_FIELDS:
            matches = self._same_goal(field, value)
            if matches is not None:
                group = matches["group"]
            else:
                self.goal_count += 1
                group = f"goal-{self.goal_count}"
            self.current_goal = group
        kinds = sensitive_types(value)
        if field in _ALWAYS_SENSITIVE and _ALWAYS_SENSITIVE[field] not in kinds:
            kinds.insert(0, _ALWAYS_SENSITIVE[field])
        source = dict(block_id=block["block_id"], page=block.get("page"), paragraph_index=block.get("paragraph_index"),
                      page_paragraph=block.get("page_paragraph"), kind=block["kind"])
        if block.get("kind") == "table":
            source["table_index"] = block.get("table_index")
        if cell is not None:
            source.update(cell_id=cell["cell_id"], row=cell["row"], col=cell["col"])
            self.used_cells.add((block["block_id"], cell["cell_id"]))
        else:
            self.used_blocks.add(block["block_id"])
        sensitive = bool(kinds) or field in _REVIEW_FIELDS
        self.items.append(dict(
            candidate_id=f"c{len(self.items) + 1:04d}", field=field, label=self.labels.labels[field],
            value=_display_value(self.labels.multi.get(field, False), value), original_text=value,
            group=group, source=source, confidence=round(min(max(confidence, 0.05), 0.99), 2), method=method,
            sensitive=sensitive, sensitive_types=kinds or (["personal"] if sensitive else []),
            sensitive_labels=[SENSITIVE_LABELS.get(k, "个人信息") for k in (kinds or (["personal"] if sensitive else []))],
            requires_confirmation=True, decision="pending" if sensitive else "auto",
            same_goal_as=matches["candidate_id"] if matches else None,
        ))

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        letters = re.sub(r"[\s\W_]+", "", _LIST_MARKER.sub("", unicodedata.normalize("NFKC", text), count=1))
        return {letters[i:i + 2] for i in range(len(letters) - 1)}

    def _same_goal(self, field: str, value: str) -> dict[str, Any] | None:
        """The same goal listed again (e.g. in the evaluation table) keeps its group."""
        referenced = self._goal_by_reference(field, value)
        if referenced is not None:
            return referenced
        mine = self._bigrams(value)
        if len(mine) < 3:
            return None
        mine_number = _numbered_goal(value)
        best, best_score = None, 0.0
        for item in self.items:
            if item["field"] != field or item.get("same_goal_as") or item["source"]["block_id"] == "":
                continue
            theirs_number = _numbered_goal(item["original_text"])
            if mine_number is not None and theirs_number is not None and mine_number != theirs_number:
                # 1. 能… and 2. 能… are distinct objectives even when the wording is close.
                continue
            theirs = self._bigrams(item["original_text"])
            if len(theirs) < 3:
                continue
            score = len(mine & theirs) / min(len(mine), len(theirs))
            if score > best_score:
                best, best_score = item, score
        return best if best is not None and best_score >= 0.6 else None

    def _goal_by_reference(self, field: str, value: str) -> dict[str, Any] | None:
        """``目标1`` in an evaluation table names goal 1 listed earlier; it is not a new goal."""
        match = _GOAL_REFERENCE.match(re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)))
        if not match:
            return None
        prefix, number = match.group(1), ordinal_number(match.group(2))
        if number is None or (prefix and self.labels.exact(prefix) not in _GOAL_FIELDS):
            return None
        goals = [item for item in self.items if item["field"] == field and not item.get("same_goal_as")]
        for item in goals:
            own = _NUMBERED_LABEL.match(re.split(r"[:：]", match_key(item["original_text"]), maxsplit=1)[0])
            if own and ordinal_number(own.group(2)) == number:
                return item
        # Unlabelled list goals ("1. 能指认…") are referenced by position.
        if goals and 1 <= number <= len(goals) and not any(
                _NUMBERED_LABEL.match(re.split(r"[:：]", match_key(item["original_text"]), maxsplit=1)[0])
                for item in goals):
            return goals[number - 1]
        return None

    def add_values(self, field: str, value: str, block: dict[str, Any], confidence: float, *, method: str,
                   cell: dict[str, Any] | None = None, group: str | None = None) -> None:
        wrapped = block.get("source") in {"text_layer", "ocr"}
        if self.labels.multi.get(field):
            values = _split_items(value, wrapped=wrapped)
        else:
            values = ["".join(value.split("\n")) if wrapped else value]
        for item in values:
            self.add(field, item, block, confidence, method=method, cell=cell, group=group)


def _header_fields(labels: _Labels, row: dict[int, dict[str, Any]]) -> dict[int, str]:
    mapped = {col: labels.exact(cell["text"]) for col, cell in row.items()}
    mapped = {col: field for col, field in mapped.items() if field}
    if len(mapped) < 2 or len(mapped) * 2 <= len(row):
        return {}
    # "姓名 | 王小明 | 班级 | 三(2)" alternates label/value: that is a key-value row, not a header.
    columns = sorted(row)
    alternating = all(
        (col in mapped) == (index % 2 == 0) for index, col in enumerate(columns)
    ) and len(columns) >= 4
    return {} if alternating else mapped


_HEADER_SUFFIX = re.compile(r"(方式|标准|条件|目标|内容|评价|方法|要求|维度|备注|说明|指标|项目)$")


def _header_like(value: str) -> bool:
    """Short column captions such as 支持方式/通过标准 are headers, not values."""
    text = unicodedata.normalize("NFKC", value or "").strip()
    return 0 < len(text) <= 8 and bool(_HEADER_SUFFIX.search(text))


def _numbered_goal(value: str) -> int | None:
    """Ordinal of ``1. …`` / ``目标2：…``; None for unnumbered table-row goals."""
    raw = unicodedata.normalize("NFKC", value or "").strip()
    marker = _LIST_MARKER.match(raw)
    if marker:
        token = re.sub(r"[^0-9一二三四五六七八九十百a-zA-Z]", "", marker.group(0))
        number = ordinal_number(token)
        if number is not None:
            return number
    head = re.split(r"[:：]", match_key(value), maxsplit=1)[0]
    match = _NUMBERED_LABEL.match(head)
    return ordinal_number(match.group(2)) if match else None


def _table_candidates(block: dict[str, Any], collector: _Candidates, labels: _Labels,
                      section: str | None) -> str | None:
    grid: dict[int, dict[int, dict[str, Any]]] = {}
    for cell in block["cells"]:
        grid.setdefault(cell["row"], {})[cell["col"]] = cell
    # A "目标 | 支持方式" caption row is a header even when the second caption is
    # not a recognised course-task field; its rows are the real goals.
    if len(grid) >= 2 and not _header_fields(labels, grid[min(grid)]):
        first_row = min(grid)
        first_cells = grid[first_row]
        first_cols = sorted(first_cells)
        if len(first_cols) >= 2:
            goal_field = labels.exact(first_cells[first_cols[0]]["text"])
            if goal_field in _GOAL_FIELDS and _header_like(first_cells[first_cols[1]]["text"]):
                for row_number in sorted(r for r in grid if r > first_row):
                    row = grid[row_number]
                    goal_cell = row.get(first_cols[0])
                    if goal_cell and goal_cell["text"].strip():
                        collector.add_values(goal_field, goal_cell["text"], block, 0.85,
                                             method="table_header_goal", cell=goal_cell)
                return None
    header_row = None
    header_fields: dict[int, str] = {}
    for row_number in sorted(grid)[:3]:
        header_fields = _header_fields(labels, grid[row_number])
        if header_fields:
            header_row = row_number
            break
    if header_row is not None:
        for col in header_fields:
            collector.used_cells.add((block["block_id"], grid[header_row][col]["cell_id"]))
        goal_col = next((col for col, field in header_fields.items() if field in _GOAL_FIELDS), None)
        for row_number in sorted(r for r in grid if r > header_row):
            row = grid[row_number]
            group = None
            if goal_col is not None and goal_col in row:
                collector.add_values(header_fields[goal_col], row[goal_col]["text"], block, 0.85,
                                     method="table_column", cell=row[goal_col])
                group = collector.current_goal
            for col, field in header_fields.items():
                if col == goal_col or col not in row:
                    continue
                collector.add_values(field, row[col]["text"], block, 0.85, method="table_column",
                                     cell=row[col], group=group)
            # Ordinal columns (序号) are structure, not content.
            for col, cell in row.items():
                if col not in header_fields and re.fullmatch(r"\d{1,3}[.、．]?", cell["text"]):
                    collector.used_cells.add((block["block_id"], cell["cell_id"]))
        # A header table is self-contained: the section that introduced it ends with it.
        return None
    # Real school lesson plans often put goals in one merged cell such as
    # "5.教学目标\n1）…\n2）…", not in a goal column. Extract those numbered
    # lines as course goals so the teacher can confirm them.
    goal_label = next((label for label in ("教学目标", "课程目标", "单元目标")
                       if any(label in cell["text"] for cell in block["cells"])), "")
    if goal_label and not any(item["field"] in _GOAL_FIELDS for item in collector.items):
        for cell in block["cells"]:
            if goal_label not in cell["text"]:
                continue
            segment = cell["text"].split(goal_label, 1)[1]
            for line in re.split(r"\n+", segment):
                match = re.match(r"\s*(?:\d+[）).、]|[（(]\d+[）)])\s*(.+)", line)
                if match and match.group(1).strip():
                    collector.add_values("course_goals", match.group(1).strip(), block, 0.85,
                                         method="table_goal_list", cell=cell)
            collector.used_cells.add((block["block_id"], cell["cell_id"]))
            break
    for row_number in sorted(grid):
        row = grid[row_number]
        columns = sorted(row)
        index = 0
        while index < len(columns):
            cell = row[columns[index]]
            field = labels.exact(cell["text"])
            if field:
                collector.used_cells.add((block["block_id"], cell["cell_id"]))
                value_cell = row.get(columns[index + 1]) if index + 1 < len(columns) else None
                if value_cell is not None and not labels.exact(value_cell["text"]):
                    collector.add_values(field, value_cell["text"], block, 0.9, method="table_key_value",
                                         cell=value_cell)
                    index += 2
                    continue
                section = field
                index += 1
                continue
            pair = labels.key_value(cell["text"])
            if pair and pair[1]:
                collector.add_values(pair[0], pair[1], block, 0.9, method="table_inline_key_value", cell=cell)
            elif section and len(row) == 1:
                collector.add_values(section, cell["text"], block, 0.7, method="table_section", cell=cell)
            index += 1
    return section


_UNKNOWN_LABEL = re.compile(r"^[^\s:：，。]{1,8}[:：]")


def extract_candidates(purpose: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    labels = _Labels(purpose)
    collector = _Candidates(purpose, labels)
    section: str | None = None
    # A soft section is opened by "目标：第一条" and only continues through list items.
    soft = False
    for block in blocks:
        kind = block["kind"]
        if kind == "table":
            section = _table_candidates(block, collector, labels, section)
            soft = False
            continue
        if kind in {"header", "footer"}:
            pair = labels.key_value(block["text"])
            if pair and pair[1]:
                collector.add_values(pair[0], pair[1], block, 0.8, method="key_value")
            continue
        text = block["text"]
        field = labels.exact(text)
        if field:
            section, soft = field, False
            collector.used_blocks.add(block["block_id"])
            continue
        pair = labels.key_value(text)
        if pair:
            field, value = pair
            if value:
                group = collector.current_goal if field in _GOAL_DETAIL_FIELDS and section in _GOAL_FIELDS else None
                collector.add_values(field, value, block, 0.9, method="key_value", group=group)
                if field in _GOAL_DETAIL_FIELDS and section in _GOAL_FIELDS:
                    continue
                section, soft = (field, True) if labels.multi.get(field) else (None, False)
            else:
                section, soft = field, False
                collector.used_blocks.add(block["block_id"])
            continue
        if kind == "heading" or _UNKNOWN_LABEL.match(unicodedata.normalize("NFKC", text)):
            section, soft = None, False
            continue
        if section and soft and kind != "list_item":
            section, soft = None, False
            continue
        if section:
            confidence = 0.8 if kind == "list_item" else 0.7
            if labels.multi.get(section):
                collector.add_values(section, text, block, confidence, method="section_item")
            elif not any(item["field"] == section for item in collector.items):
                collector.add_values(section, text, block, confidence - 0.1, method="section_item")
    other: list[dict[str, Any]] = []
    for block in blocks:
        location = dict(block_id=block["block_id"], page=block.get("page"), paragraph_index=block.get("paragraph_index"),
                        kind=block["kind"])
        if block["kind"] == "table":
            for cell in block["cells"]:
                if (block["block_id"], cell["cell_id"]) not in collector.used_cells:
                    kinds = sensitive_types(cell["text"])
                    other.append(dict(location, cell_id=cell["cell_id"], row=cell["row"], col=cell["col"],
                                      text=cell["text"], sensitive=bool(kinds), sensitive_types=kinds))
        elif block["block_id"] not in collector.used_blocks:
            kinds = sensitive_types(block["text"])
            other.append(dict(location, text=block["text"], sensitive=bool(kinds), sensitive_types=kinds))
    fields = []
    for field, label, _, multi in labels.spec:
        ids = [item["candidate_id"] for item in collector.items if item["field"] == field]
        fields.append(dict(field=field, label=label, multiple=multi, candidate_ids=ids, found=bool(ids)))
    goals: list[dict[str, Any]] = []
    for item in collector.items:
        if item["field"] in _GOAL_FIELDS:
            if item.get("same_goal_as"):
                continue
            details = [c["candidate_id"] for c in collector.items
                       if c["group"] == item["group"] and c["candidate_id"] != item["candidate_id"]]
            goals.append(dict(group=item["group"], field=item["field"], goal_candidate_id=item["candidate_id"],
                              detail_candidate_ids=details))
    return dict(candidates=collector.items, fields=fields, goals=goals, other_content=other)


def flag_blocks(blocks: list[dict[str, Any]]) -> int:
    count = 0
    for block in blocks:
        if block["kind"] == "table":
            for cell in block["cells"]:
                kinds = sensitive_types(cell["text"])
                cell["sensitive"] = bool(kinds)
                cell["sensitive_types"] = kinds
                count += bool(kinds)
            block["sensitive"] = any(cell["sensitive"] for cell in block["cells"])
            block["sensitive_types"] = sorted({k for cell in block["cells"] for k in cell["sensitive_types"]})
        else:
            kinds = sensitive_types(block["text"])
            block["sensitive"] = bool(kinds)
            block["sensitive_types"] = kinds
            count += bool(kinds)
    return count


def parse_document(purpose: str, file_type: str, data: bytes) -> dict[str, Any]:
    """Full structured result for one validated file (``detect_document_type`` first)."""
    if purpose not in PURPOSES:
        raise fail(400, "invalid_purpose")
    converted = False
    if file_type == "doc":
        data = convert_doc_to_docx(data)
        file_type_used = "docx"
        converted = True
    else:
        file_type_used = file_type
    extracted = extract_pdf(data) if file_type_used == "pdf" else extract_docx(data)
    blocks = extracted["blocks"]
    sensitive_block_count = flag_blocks(blocks)
    candidates = extract_candidates(purpose, blocks)
    cell_count = sum(len(block["cells"]) for block in blocks if block["kind"] == "table")
    empty_pages = extracted["empty_pages"]
    if not blocks:
        status = "needs_manual_entry"
    elif empty_pages:
        status = "partial_manual_entry"
    elif extracted["ocr"]["used"]:
        status = "parsed_with_ocr"
    else:
        status = "parsed"
    if status == "needs_manual_entry":
        reason = "ocr_no_text" if extracted["ocr"]["available"] else "ocr_unavailable"
        notice = ("文件中没有可识别的文字（可能是扫描件或图片），请在下方人工补充栏中录入内容"
                  if reason == "ocr_no_text" else
                  "这是扫描件或图片型 PDF，服务器未启用文字识别（OCR），请在下方人工补充栏中录入内容")
    elif status == "partial_manual_entry":
        reason = "pages_without_text"
        notice = f"第 {', '.join(str(p) for p in empty_pages)} 页没有可识别的文字，请核对后人工补充这些页的内容"
    else:
        reason = ""
        notice = ""
    if status == "parsed_with_ocr":
        notice = f"第 {', '.join(str(p) for p in extracted['ocr']['pages'])} 页通过文字识别（OCR）读取，请逐条核对"
    return dict(
        status=status,
        manual_entry_required=status in {"needs_manual_entry", "partial_manual_entry"},
        manual_entry_reason=reason,
        notice=notice,
        purpose=purpose,
        file_type=file_type,
        converted_from_doc=converted,
        page_count=extracted["page_count"],
        page_count_estimated=extracted["page_count_estimated"],
        manual_entry_pages=empty_pages,
        ocr=extracted["ocr"],
        blocks=blocks,
        candidates=candidates["candidates"],
        fields=candidates["fields"],
        goals=candidates["goals"],
        other_content=candidates["other_content"],
        coverage=dict(
            block_count=len(blocks),
            paragraph_count=sum(1 for b in blocks if b["kind"] != "table"),
            table_count=sum(1 for b in blocks if b["kind"] == "table"),
            table_cell_count=cell_count,
            candidate_count=len(candidates["candidates"]),
            other_count=len(candidates["other_content"]),
        ),
        sensitive_count=sum(1 for c in candidates["candidates"] if c["sensitive"]),
        sensitive_block_count=sensitive_block_count,
    )
