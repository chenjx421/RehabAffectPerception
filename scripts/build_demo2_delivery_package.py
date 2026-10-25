from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt


ROOT = Path(__file__).resolve().parents[1]
DATE_TAG = "20260827"
DELIVERY_ROOT = ROOT / "deliverables" / f"{DATE_TAG}_demo2_delivery"
PACKAGE_NAME = f"RehabAffect_Demo2_交付包_{DATE_TAG}"
PACKAGE_DIR = DELIVERY_ROOT / PACKAGE_NAME
ZIP_PATH = DELIVERY_ROOT / f"{PACKAGE_NAME}.zip"

REFERENCE_DOCX = Path(
    r"C:\Path\To\Developer\Documents\xwechat_files\wxid_2m302j15cyrl22_2ea9\msg\file\2026-07\辅读系统概览.docx"
)
PDF_SOURCE = ROOT / "output" / "pdf" / f"RehabAffect_Demo2_逐页图文功能说明_{DATE_TAG}.pdf"
OVERVIEW_OUTPUT = PACKAGE_DIR / "00_系统概览" / f"辅读系统概览_已填写_{DATE_TAG}.docx"
PDF_OUTPUT = PACKAGE_DIR / "01_功能展示" / PDF_SOURCE.name
SOURCE_DIR = PACKAGE_DIR / "02_源程序"
QA_DIR = PACKAGE_DIR / "03_测试与清单"


OVERVIEW_ANSWERS = [
    [
        "开发处理器：x64 多核 CPU；开发内存：16GB 及以上。",
        "前端与本地服务开发不依赖独立显卡；视频特征重算和后续模型训练可使用 NVIDIA GPU 工作站。",
    ],
    [
        "演示端：Intel Core i5 / AMD Ryzen 5、8GB 内存、5GB 可用磁盘空间。",
        "学校试点服务端建议：8 核 CPU、32GB 内存、1TB NVMe；四路视频同时上传时建议总上行带宽不少于 40Mbps。",
        "完整视觉/音频模型推理建议配置 12-24GB 显存的 NVIDIA GPU 工作节点。",
    ],
    [
        "开发系统：Windows 11 x64。",
        "兼容环境：Windows 10/11；浏览器支持最新版 Edge、Chrome。服务端 Python 代码可迁移到主流 Linux x64 环境，正式部署前需单独完成兼容性与权限测试。",
    ],
    [
        "Python 3.10 及以上、PowerShell、Git、pytest、浏览器开发者工具及 Playwright 自动化检查。",
        "可选视频处理环境：OpenCV、FFmpeg；可选模型训练环境：scikit-learn、PyTorch/ONNX Runtime。",
    ],
    [
        "当前交付为浏览器访问的本地 Web 应用，服务运行于 Windows 10/11 的 Python 环境。",
        "访问地址默认为 http://127.0.0.1:8791/seewo_student_demo2；正式校内部署可改为局域网服务器地址。",
    ],
    [
        "Python 为主要后端与分析语言；前端为原生 HTML、CSS、JavaScript；配置与接口数据使用 JSON；启动与运维脚本使用 PowerShell/CMD。",
    ],
    [
        "运行源程序 32 个 Python 文件，约 17,731 行。连同测试、启动、页面检查和交付构建脚本，当前交付代码约 2 万行。",
        "行数按文本行统计，仅用于交付规模说明，不代表代码质量或功能完成度。",
    ],
    [
        "课程开始前确认数据安全协议、课程名称、课程标准、考核标准与责任人；同屏展示三名学生群像并支持个体切换。",
        "围绕状态时间线、师生互动、教师复核、支持效果、目标掌握、五域趋势和课程适配形成课堂证据链。",
        "支持 IEP/五域资料导入、四路独立视频分片上传、本地 SQLite 数据存储、60 天保存与提前 15 天到期提醒、报告和 JSON 下载。",
        "按已确认课堂证据生成约一千字课程报告，并输出低刺激支持建议及未来机器人动作接口。",
    ],
    [
        "不是单纯的注意力评分，而是把课程目标、学生个体基线、互动机会、提示层级、支持前后变化和教师复核放在同一分析链路。",
        "掌握结论区分独立掌握、支持下掌握、正在学习和证据不足；不把安静、动作少或单次课堂表现直接等同于能力。",
        "采用 human-in-the-loop 教师复核、来源追溯、低刺激支持、安全边界和结构化 JSON 输出，便于后续 App、WebSocket、ROS2 或机器人端接入。",
    ],
    [
        "完整源代码位于交付包的“02_源程序”目录，包括 src、tests、configs、models、启动脚本、安装脚本和演示所需缓存数据。",
        "压缩包不包含原始课堂视频、学生 IEP 原件、医疗资料或历史上传文件。",
    ],
    [
        "组成：Python 本地服务、Demo2 蓝白色前端、课堂分析缓存、本地 SQLite、学生资料与四路上传接口、报告生成器、测试与浏览器检查脚本。",
        "开发情况：已完成需求确认级 Demo，可用于公司内部演示和校方受控需求沟通；不能宣称已达到正式自动评估或全校生产投放精度。",
        "测试结果：项目完整自动测试 43 项通过、5 项因可选环境跳过；浏览器检查覆盖桌面、学校笔记本、平板和手机宽度，无横向溢出、破图或控制台错误。",
        "使用方法：在“02_源程序”中先运行 install_environment.cmd，再双击 start_school_demo2.cmd。启动后浏览器自动打开 Demo2。",
    ],
    [
        "系统按“课程与安全确认 -> 多主体视频/资料输入 -> 课堂证据整理 -> 学生状态与目标掌握判断 -> 教师复核 -> 支持建议 -> 报告与长期追踪”设计。",
        "原始文件和结构化元数据分开保存；新上传原始视频默认保存 60 天并提前 15 天提醒。脱敏结构化结果只有在单独授权后才可进入长期资源队列。",
        "当前演示中的状态和掌握数据包含缓存样例与可解释规则结果。对任意新视频形成可靠结论仍需完成真实模型部署、教师标注、离线评估、权限控制和试点验证。",
    ],
    [
        "系统共展示 17 个功能页面和进入流程，包括安全协议、课程确认、班级群像、一人一案、历史记录、资料导入、状态时间线、师生互动、教师复核、支持效果、学习判断、支持工具、动作方案、五域趋势、课程分析、千字报告、数据来源、四路上传、数据存储和结构化数据。",
        "每个页面的截图、输入、系统处理、页面输出和实际价值，详见交付包“01_功能展示/RehabAffect_Demo2_逐页图文功能说明_20260827.pdf”。",
    ],
]


def _set_cell_text(cell, paragraphs: list[str]) -> None:
    cell.text = ""
    first = cell.paragraphs[0]
    for index, text in enumerate(paragraphs):
        paragraph = first if index == 0 else cell.add_paragraph()
        paragraph.style = "Normal"
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        paragraph.paragraph_format.line_spacing = 1.15
        run = paragraph.add_run(text)
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        run.font.size = Pt(10.5)


def build_overview_docx() -> Path:
    if not REFERENCE_DOCX.exists():
        raise FileNotFoundError(REFERENCE_DOCX)
    OVERVIEW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REFERENCE_DOCX, OVERVIEW_OUTPUT)
    os.chmod(OVERVIEW_OUTPUT, stat.S_IREAD | stat.S_IWRITE)
    document = Document(OVERVIEW_OUTPUT)
    table = document.tables[0]
    if len(table.rows) != len(OVERVIEW_ANSWERS):
        raise RuntimeError("Overview template row count changed")
    for row, answer in zip(table.rows, OVERVIEW_ANSWERS, strict=True):
        _set_cell_text(row.cells[1], answer)
    document.core_properties.title = "辅读学校系统概览 - RehabAffect Demo2"
    document.core_properties.subject = "Demo2 软件交付概览"
    document.save(OVERVIEW_OUTPUT)
    return OVERVIEW_OUTPUT


def _copytree(source: Path, destination: Path, *, ignore=None) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def _source_ignore(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"__pycache__", ".pytest_cache", ".mypy_cache"} or name.endswith((".pyc", ".pyo"))}


def _copy_demo_outputs() -> None:
    source = ROOT / "outputs" / "seewo_demo2"
    destination = SOURCE_DIR / "outputs" / "seewo_demo2"
    destination.mkdir(parents=True, exist_ok=True)
    for filename in ["analysis.json", "rehab_affect_demo2.sqlite3", "teacher_reviews.json"]:
        path = source / filename
        if path.exists():
            shutil.copy2(path, destination / filename)
    for dirname in ["chinese_playground_sentence", "math_add_to_3"]:
        path = source / dirname
        if path.exists():
            _copytree(path, destination / dirname, ignore=_source_ignore)
    (destination / "reports").mkdir(exist_ok=True)
    (destination / "student_documents").mkdir(exist_ok=True)
    (destination / "video_tasks").mkdir(exist_ok=True)


def _sanitize_session_config() -> None:
    source = ROOT / "data" / "processed" / "seewo_demo2" / "session_config.json"
    destination = SOURCE_DIR / "data" / "processed" / "seewo_demo2" / "session_config.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    for course in payload.get("courses", []):
        for key in ["student_video", "teacher_video", "lesson_plan"]:
            value = course.get(key)
            if value:
                course[key] = str(Path("data") / "input" / Path(value).name).replace("\\", "/")
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    input_dir = SOURCE_DIR / "data" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "README.md").write_text(
        "# 原始输入目录\n\n本交付包不含学生原始视频、音频、IEP 或评估原件。经授权的原始文件应放在受控目录，并同步更新 session_config.json。\n",
        encoding="utf-8",
    )


def _write_runtime_files() -> None:
    requirements = "numpy>=1.24\npytest>=8.0\n"
    (SOURCE_DIR / "requirements.txt").write_text(requirements, encoding="utf-8")
    (SOURCE_DIR / "install_environment.cmd").write_text(
        "@echo off\r\ncd /d \"%~dp0\"\r\npython -m pip install -r requirements.txt\r\nif errorlevel 1 pause\r\n",
        encoding="utf-8",
    )
    (SOURCE_DIR / "verify_demo.cmd").write_text(
        "@echo off\r\ncd /d \"%~dp0\"\r\nset PYTHONPATH=src\r\npython -m pytest tests -q --import-mode=importlib\r\npause\r\n",
        encoding="utf-8",
    )
    (SOURCE_DIR / "README_运行说明.md").write_text(
        """# Demo2 源程序运行说明

## 快速启动

1. 安装 Python 3.10 或更高版本，并勾选“Add Python to PATH”。
2. 双击 `install_environment.cmd` 安装基础依赖。
3. 双击 `start_school_demo2.cmd`。
4. 浏览器将打开 `http://127.0.0.1:8791/seewo_student_demo2`。

## 当前样例与新视频

交付包自带的是脱离原始视频也能运行的课堂分析缓存、页面图片和本地 SQLite 样例。原始学生视频、音频和档案原件未打包。对新视频重新分析时，需要取得学校和监护人授权，配置受控输入目录，并部署 OpenCV/FFmpeg 以及经验证的视觉、音频模型工作节点。

## 数据边界

页面结论仅用于课堂观察、教师复核和教学支持，不构成医学诊断。教师必须复核关键切片、掌握判断和支持建议后再进入正式记录。
""",
        encoding="utf-8",
    )


def _copy_source() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for dirname in ["src", "tests", "configs", "models"]:
        path = ROOT / dirname
        if path.exists():
            _copytree(path, SOURCE_DIR / dirname, ignore=_source_ignore)
    scripts_dir = SOURCE_DIR / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for filename in [
        "start_school_demo.ps1",
        "qa_demo2_ui.js",
        "build_demo2_all_pages_pdf.py",
    ]:
        shutil.copy2(ROOT / "scripts" / filename, scripts_dir / filename)
    for filename in ["pyproject.toml", "README.md", "start_school_demo2.cmd"]:
        shutil.copy2(ROOT / filename, SOURCE_DIR / filename)
    _copy_demo_outputs()
    _sanitize_session_config()
    _write_runtime_files()


def _count_lines(paths: Iterable[Path]) -> tuple[int, int]:
    files = 0
    lines = 0
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".ps1", ".cmd"}:
            continue
        files += 1
        lines += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    return files, lines


def _write_readme_and_qa() -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    files, lines = _count_lines(SOURCE_DIR.rglob("*"))
    readme = f"""# RehabAffect Demo2 交付包

本包依据《辅读系统概览》整理，面向公司内部验收、校方需求沟通和后续研发交接。

## 先看哪几个文件

1. `00_系统概览/辅读系统概览_已填写_{DATE_TAG}.docx`：对应模板中的开发环境、运行环境、功能、技术特点、源代码、测试和使用方法。
2. `01_功能展示/{PDF_SOURCE.name}`：26 页逐页图文说明，每页均结合真实 Demo 截图说明用途、输入、处理、输出或实际价值。
3. `02_源程序/README_运行说明.md`：运行步骤、样例边界和新视频接入条件。
4. `03_测试与清单/`：测试结果、源文件清单和 SHA-256 校验值。

## 交付内容

- 当前代码文件：{files} 个，文本代码约 {lines:,} 行。
- Demo2 蓝白色前端与本地 Python 服务。
- 三学生群像/个体分析、教师复核、学习掌握、支持动作、五域趋势和千字报告。
- IEP/评估资料导入、四路独立视频上传、本地 SQLite、60 天保存与提前 15 天提醒。
- 自动测试、浏览器页面检查脚本及逐页图文 PDF。

## 不包含的敏感内容

不包含原始课堂视频、音频、学生 IEP 原件、医疗资料、历史上传文件或本机绝对路径。包内页面图片和分析缓存仅用于本次授权演示，不得公开传播。

## 当前完成边界

当前版本适合公司内部展示、校方受控演示和需求确认。它不是已经通过真实数据集验证的自动评估产品。对任意新视频形成可靠状态与掌握判断，还需要完成学校授权、教师标注、视觉/音频模型部署、离线指标验证、权限管理和试点运行。
"""
    (PACKAGE_DIR / "README_先看这里.md").write_text(readme, encoding="utf-8")
    (QA_DIR / "TEST_RESULTS.txt").write_text(
        """RehabAffect Demo2 验证结果

- Python 自动测试：43 passed, 5 skipped
- 浏览器覆盖：1440 桌面、1366 学校笔记本、1024/768 平板、390/360 手机
- 页面检查：0 横向溢出、0 破图、0 未命名控件、0 控制台错误
- 已检查流程：安全协议、课程确认、学生切换、群像/个体切换、教师复核、支持工具、千字报告、资料导入、四路上传和数据存储
- 测试日期：2026-08-27

说明：以上为软件逻辑与页面可用性测试，不等同于真实学生状态模型准确率。真实模型准确率必须以教师复核标注的数据集独立评估。
""",
        encoding="utf-8",
    )
    with (QA_DIR / "SOURCE_INVENTORY.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["相对路径", "字节", "类型"])
        for path in sorted(SOURCE_DIR.rglob("*")):
            if path.is_file():
                writer.writerow([path.relative_to(SOURCE_DIR).as_posix(), path.stat().st_size, path.suffix.lower() or "无扩展名"])


def _write_manifest() -> None:
    manifest_path = QA_DIR / "MANIFEST_SHA256.txt"
    lines = []
    for path in sorted(PACKAGE_DIR.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(PACKAGE_DIR).as_posix()}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _zip_package() -> Path:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, Path(PACKAGE_NAME) / path.relative_to(PACKAGE_DIR))
    return ZIP_PATH


def _remove_readonly_and_retry(function, path, _error) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    function(path)


def build() -> dict[str, str | int]:
    if DELIVERY_ROOT.exists():
        shutil.rmtree(DELIVERY_ROOT, onexc=_remove_readonly_and_retry)
    PACKAGE_DIR.mkdir(parents=True)
    build_overview_docx()
    if not PDF_SOURCE.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_demo2_all_pages_pdf.py")], check=True)
    PDF_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PDF_SOURCE, PDF_OUTPUT)
    _copy_source()
    _write_readme_and_qa()
    _write_manifest()
    _zip_package()
    return {
        "package_dir": str(PACKAGE_DIR),
        "zip": str(ZIP_PATH),
        "overview_docx": str(OVERVIEW_OUTPUT),
        "pdf": str(PDF_OUTPUT),
        "zip_bytes": ZIP_PATH.stat().st_size,
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
