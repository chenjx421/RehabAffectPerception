from __future__ import annotations

import hashlib
import json
import shutil
import textwrap
import zipfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = PROJECT_ROOT / "dist"
PACKAGE_NAME = "RehabAffect_Seewo_Student_Demo_Offline_20260731"
STAGE_DIR = DIST_ROOT / PACKAGE_NAME
ZIP_PATH = DIST_ROOT / f"{PACKAGE_NAME}.zip"
SOURCE_CODE_DOCX = (
    PROJECT_ROOT
    / "docs"
    / "辅读学校Demo_源码汇编与通俗说明_20260731.docx"
)


def _safe_reset_directory(path: Path) -> None:
    resolved = path.resolve()
    expected_parent = DIST_ROOT.resolve()
    if resolved.parent != expected_parent or resolved.name != PACKAGE_NAME:
        raise RuntimeError(f"Refusing to reset unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if not isinstance(value, str):
        return value
    replacements = {
        "Student H": "student_A",
        str(PROJECT_ROOT): "<PACKAGE_ROOT>",
        str(PROJECT_ROOT).replace("\\", "\\\\"): "<PACKAGE_ROOT>",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def _write_sanitized_json(source: Path, destination: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload = _sanitize_value(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _write_runtime_files() -> None:
    _write_text(
        STAGE_DIR / "requirements.txt",
        """
        numpy>=1.24,<3
        """,
    )
    _write_text(
        STAGE_DIR / "requirements-reanalysis.txt",
        """
        numpy>=1.24,<3
        opencv-python>=4.8
        python-docx>=1.1
        Pillow>=10.0
        imageio-ffmpeg>=0.5
        """,
    )
    _write_text(
        STAGE_DIR / "requirements-dev.txt",
        """
        -r requirements.txt
        pytest>=8.0
        """,
    )
    _write_text(
        STAGE_DIR / "install_environment.ps1",
        r"""
        $ErrorActionPreference = "Stop"
        $root = (Resolve-Path $PSScriptRoot).Path
        $venvPython = Join-Path $root ".venv\Scripts\python.exe"

        if (-not (Test-Path $venvPython)) {
            $launcher = Get-Command py -ErrorAction SilentlyContinue
            if ($launcher) {
                & $launcher.Source -3 -m venv (Join-Path $root ".venv")
            }
            else {
                $python = (Get-Command python -ErrorAction Stop).Source
                & $python -m venv (Join-Path $root ".venv")
            }
        }

        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r (Join-Path $root "requirements.txt")
        Write-Output "Environment ready: $venvPython"
        """,
    )
    _write_text(
        STAGE_DIR / "install_environment.cmd",
        r"""
        @echo off
        cd /d "%~dp0"
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_environment.ps1"
        if errorlevel 1 pause
        """,
    )
    _write_text(
        STAGE_DIR / "start_demo.ps1",
        r"""
        param(
            [int]$Port = 8791,
            [switch]$NoBrowser
        )

        $ErrorActionPreference = "Stop"
        $root = (Resolve-Path $PSScriptRoot).Path
        $url = "http://127.0.0.1:$Port/seewo_student_demo"
        $healthUrl = "http://127.0.0.1:$Port/api/health"
        $runtimeDir = Join-Path $root ".runtime"
        $venvPython = Join-Path $root ".venv\Scripts\python.exe"

        function Test-DemoServer {
            try {
                $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
                return $response.ok -eq $true
            }
            catch {
                return $false
            }
        }

        if (-not (Test-DemoServer)) {
            [System.IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
            if (Test-Path $venvPython) {
                $python = $venvPython
            }
            else {
                $python = (Get-Command python -ErrorAction Stop).Source
            }
            $stdout = Join-Path $runtimeDir "demo_stdout.log"
            $stderr = Join-Path $runtimeDir "demo_stderr.log"
            $arguments = @(
                "-m", "src.rehab_affect.scenario_lab_server",
                "--host", "127.0.0.1",
                "--port", $Port,
                "--policy", "rule"
            )
            Start-Process `
                -FilePath $python `
                -ArgumentList $arguments `
                -WorkingDirectory $root `
                -WindowStyle Hidden `
                -RedirectStandardOutput $stdout `
                -RedirectStandardError $stderr | Out-Null

            $ready = $false
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                Start-Sleep -Milliseconds 500
                if (Test-DemoServer) {
                    $ready = $true
                    break
                }
            }
            if (-not $ready) {
                Write-Error "Demo failed to start. Check $stderr"
            }
        }

        Write-Output "Demo ready: $url"
        if (-not $NoBrowser) {
            Start-Process $url
        }
        """,
    )
    _write_text(
        STAGE_DIR / "start_demo.cmd",
        r"""
        @echo off
        cd /d "%~dp0"
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_demo.ps1"
        if errorlevel 1 pause
        """,
    )
    _write_text(
        STAGE_DIR / "verify_demo.cmd",
        r"""
        @echo off
        cd /d "%~dp0"
        if exist ".venv\Scripts\python.exe" (
          ".venv\Scripts\python.exe" tools\smoke_test.py
        ) else (
          python tools\smoke_test.py
        )
        if errorlevel 1 pause
        """,
    )
    _write_text(
        STAGE_DIR / "tools" / "smoke_test.py",
        """
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))

        from src.rehab_affect.seewo_student_demo import (
            load_seewo_student_demo,
            render_seewo_student_demo_html,
        )


        data = load_seewo_student_demo()
        assert data.get("ui_version") == "student_support_v4"
        assert len(data.get("timeline", [])) == 77
        assert data.get("teacher_effectiveness", {}).get("overall_score") == 71
        assert data.get("target_student", {}).get("student_id") == "student_A"
        assert (root / "outputs/seewo_xiaoyudi_demo/frames/target_roi_reference.jpg").exists()
        html = render_seewo_student_demo_html()
        assert "学生个体状态追踪与课堂支持 Demo" in html
        assert "教师支持效果评估" in html
        print("PASS: cached analysis, assets, HTML rendering and teacher-effectiveness data are ready.")
        """,
    )


def _write_private_data_notice() -> None:
    _write_text(
        STAGE_DIR / "data" / "raw" / "seewo_xiaoyudi_001" / "README_PRIVATE_DATA.md",
        r"""
        # 原始数据未随包分发

        本离线展示包不包含原始课堂视频、学生原始照片、原始 IEP、PDF、Excel 或其他可识别个人身份的材料。页面默认读取 `outputs/seewo_xiaoyudi_demo/analysis.json` 中的匿名化缓存结果，因此无需这些文件即可展示。

        只有在学校授权的受控环境中重新分析视频时，才应放入：

        - `lesson_video.mp4`：Seewo 导出的课堂视频，音轨保留在视频中；
        - `seewo_lesson_report.docx`：Seewo 导出的评课详情；
        - `target_student.png`：目标学生定位参考图；
        - 必要的授权证明和数据处理记录。

        重新分析前安装 `requirements-reanalysis.txt`，并在项目根目录执行：

        ```powershell
        .venv\Scripts\python -c "from src.rehab_affect.seewo_student_demo import load_seewo_student_demo; load_seewo_student_demo(force=True)"
        ```

        原始数据不得放入公开网盘、公开代码仓库或无权限控制的云服务。
        """,
    )


def _write_readme() -> None:
    _write_text(
        STAGE_DIR / "README.md",
        r"""
        # 辅读学校 Seewo 单学生状态追踪 Demo

        **版本：** Offline Demo 2026-07-31  
        **交付类型：** 内部受限展示版  
        **默认地址：** `http://127.0.0.1:8791/seewo_student_demo`

        > 本系统用于课堂状态辅助观察、教师复核和低刺激支持动作建议，不做医学诊断，不给学生贴固定标签，不替代教师判断。本压缩包含低清课堂示例画面和匿名化教育支持信息，仅限经授权的校内沟通与研发验证，不得公开传播。

        **非技术管理者建议先阅读：** `docs/辅读学校Demo_源码汇编与通俗说明_20260731.docx`。文档前半部分用通俗语言说明项目作用、输入输出、页面含义、完成状态和风险边界；后半部分完整收录交付源码。

        ## 1. 系统定位

        系统复用学校已有的 Seewo 课堂视频、视频音轨、评课报告和学生个体评估摘要，针对一个目标学生建立按时间窗口组织的课堂状态记录。它把分析结果进一步转换为屏幕提示、短句语音、机器人低刺激动作和老师端提醒，并保留教师复核入口。

        核心流程：

        ```text
        Seewo 导出视频/音轨 + 评课报告 + 学生支持档案
          -> 目标学生 ROI 与 30 秒时间窗口
          -> 粗粒度动作、声音、遮挡和课堂背景特征
          -> 状态时间线、关键复核片段和教师支持效果
          -> 屏幕/语音/机器人/老师端动作建议
          -> 教师确认，形成后续个体化校准数据
        ```

        当前离线包直接读取匿名化缓存结果，启动时不会重新处理整段视频，也不会连接 Seewo 网站或上传数据。

        ## 2. 压缩包目录

        | 路径 | 内容 |
        | --- | --- |
        | `src/rehab_affect/` | 完整 Python 源程序，共 29 个文件 |
        | `configs/` | 状态标签、知识约束和课堂场景配置 |
        | `outputs/seewo_xiaoyudi_demo/` | 匿名化缓存分析 JSON 与页面所需图片 |
        | `data/processed/` | 匿名化学生支持画像摘要 |
        | `data/raw/.../README_PRIVATE_DATA.md` | 原始授权数据放置和隐私说明 |
        | `tests/` | 项目自动测试代码 |
        | `tools/smoke_test.py` | 离线包快速完整性检查 |
        | `docs/screenshots/` | 页面、教师效果和 JSON 状态截图 |
        | `docs/辅读学校Demo_源码汇编与通俗说明_20260731.docx` | 面向管理者的通俗说明与完整源码汇编 |
        | `docs/seewo_school_demo_rehearsal_zh.md` | 现场演示顺序与问答提纲 |
        | `install_environment.cmd` | Windows 一键创建 Python 虚拟环境 |
        | `start_demo.cmd` | Windows 一键启动 Demo |
        | `verify_demo.cmd` | Windows 一键运行离线包冒烟测试 |

        ## 3. 开发的硬件环境

        当前版本在以下开发电脑上完成和验证：

        - CPU：13th Gen Intel Core i5-13420H，8 核 12 线程；
        - 内存：16 GB；
        - 图形设备：Intel UHD Graphics 集成显卡；
        - 存储：普通本地 SSD；
        - 摄像头/麦克风：离线演示不需要实时设备，原始音频来自课堂视频音轨。

        本项目没有依赖独立 GPU。当前 Demo 的核心是缓存结果展示和可解释规则，不从零训练大模型。

        ## 4. 运行的硬件环境

        **最低展示配置：** 2 核 CPU、4 GB RAM、约 300 MB 可用磁盘、1280×720 屏幕。  
        **推荐展示配置：** 4 核 CPU、8 GB RAM、1920×1080 屏幕。  
        **重新分析 38 分钟视频：** 推荐 8 核 CPU、16 GB RAM，并预留 1 GB 以上临时空间；无需独立 GPU，但处理时间取决于 CPU 和视频编码。

        ## 5. 开发操作系统与兼容环境

        - 已验证：Windows 11 64 位，版本 10.0.26200；
        - 目标兼容：Windows 10/11 64 位；
        - Python：3.10 至 3.12，当前验证版本为 3.12.7；
        - 浏览器：Microsoft Edge 或 Google Chrome 的近两年版本；
        - Linux/macOS 可运行 Python 服务，但本包的一键 `.cmd/.ps1` 脚本面向 Windows。

        ## 6. 软件开发环境与工具

        - Python 3.12.7；
        - NumPy 2.5.0；
        - Git 2.47.1；
        - PowerShell、Windows 命令脚本；
        - pytest 自动测试；
        - OpenCV、python-docx、Pillow、imageio-ffmpeg 仅在重新分析原始视频和报告时使用；
        - 前端为 Python 生成的原生 HTML/CSS/JavaScript，不依赖 Node.js 构建。

        ## 7. 运行平台与操作系统

        程序运行在本机 Python HTTP 服务上，浏览器访问 `127.0.0.1`。页面和数据均保留在当前电脑，不需要公网，不依赖学校网络。默认端口为 `8791`，可在 PowerShell 中通过 `-Port` 修改。

        ## 8. 编程语言类型

        - Python：数据读取、特征计算、状态估计、策略、接口和 HTTP 服务；
        - HTML/CSS/JavaScript：浏览器界面和交互；
        - JSON：分析结果、学生状态、动作方案和配置；
        - PowerShell/Batch：Windows 环境安装与启动；
        - Markdown：说明文档。

        ## 9. 源程序量

        `src/rehab_affect/` 当前包含 **29 个 Python 文件、约 11,881 行源代码**。压缩包同时附带配置、测试、启动脚本和页面截图。代码规模统计不含第三方库、缓存数据和生成图片。

        ## 10. 主要功能介绍

        1. 读取 Seewo 导出的课堂视频、视频音轨和评课报告；
        2. 使用人工 ROI 明确目标学生，并排除左右教师/秩序维护人员区域；
        3. 将约 38.3 分钟课堂切分为 77 个 30 秒窗口；
        4. 输出参与、注意力下降、困惑/停滞、成人遮挡不确定等状态；
        5. 汇总参与基线、需要支持窗口、教师复核窗口和状态分布；
        6. 结合匿名化 IEP 与认知、语言沟通、运动评估形成个体化支持约束；
        7. 量化本节课对目标学生的支持效果，但不作为教师个人考核；
        8. 输出屏幕、语音、机器人动作和老师端提醒；
        9. 提供“符合观察、需要修正、不确定”教师复核入口；
        10. 输出结构化 JSON，便于后续接数据库、WebSocket、ROS2 或机器人控制端。

        ## 11. 点击下方时间段的作用

        下方每个时间段代表课堂视频中的一个 **30 秒分析窗口**，不是单独的视频播放器按钮。点击后会：

        1. 把该时间窗口设为当前复核对象；
        2. 更新右侧的状态、置信度、底层证据和课堂场景；
        3. 更新屏幕提示、短句语音、机器人动作和老师提醒；
        4. 更新当前窗口的 `human_state` 与完整 JSON；
        5. 允许老师对该片段选择“符合观察、需要修正、不确定”。

        它的核心价值是把“整节课一个总分”下钻到“具体什么时候、为什么需要看一眼、下一步可以怎么支持”。当前 Demo 没有直接嵌入原始视频播放器，因此点击时间段不会播放对应视频；后续可根据 `start_sec` 和 `end_sec` 接入视频跳转。

        ## 12. 技术特点概览

        - **Seewo 互补：** 在整体评课数据上增加单学生时间线、个体档案、跨课追踪和动作建议；
        - **多模态时间对齐：** 把画面动作、课堂声音、遮挡、画面质量和评课背景放到统一窗口；
        - **显式不确定性：** 成人靠近或画质不足时不强行判断，转交老师复核；
        - **低刺激动作：** 机器人不直接自由行动，动作受白名单、低速度、距离和老师确认约束；
        - **可解释证据：** 每个状态附带特征、证据、质量、置信度和建议动作；
        - **人机闭环：** 教师复核结果可沉淀为后续个体化校准和训练数据；
        - **隐私优先：** 离线运行，原始学生资料不随展示包分发。

        ## 13. 程序组成与设计说明

        | 模块 | 主要职责 |
        | --- | --- |
        | `seewo_student_demo.py` | 课堂视频/音频/报告处理、状态窗口、教师效果和页面渲染 |
        | `scenario_lab_server.py` | HTTP 路由、JSON API、页面和图片资源服务 |
        | `schema.py` | `human_state`、`robot_action` 等结构化对象 |
        | `smoothing.py` / `fusion.py` | 时间平滑与多模态融合 |
        | `policy.py` | 人类状态到机器人动作的规则映射与安全约束 |
        | `pipeline.py` | 感知、状态估计和动作建议的主流程 |
        | `sim_runner.py` / `closed_loop.py` | 轻量具身仿真和动作反馈闭环 |
        | `education_demo.py` / `showcase.py` | 其他演示页面，保留为完整源码的一部分 |

        页面为三栏结构：左侧显示数据来源与学生画像，中间显示整课结论、教师支持效果和时间线，右侧显示当前片段证据、动作方案、教师复核和 JSON。

        ## 14. 功能规格与当前开发情况

        **已完成：** 离线缓存演示、77 个时间窗口、关键片段筛选、学生支持档案、教师支持效果、动作建议、JSON 输出、教师复核 UI、Windows 一键启动。  
        **当前原型限制：** 状态估计主要采用可解释视觉/音频特征和规则，不是训练完成的深度多模态模型；低清全景视频不支持可靠的精细表情或稳定眼神识别。  
        **尚未完成：** Seewo 官方接口自动同步、多节课数据库、教师复核结果持久化、视频时间轴联动、真实机器人联调和基于校方标注的模型训练。

        ## 15. 测试结果

        - 项目自动测试：`28 passed, 5 skipped`；
        - 浏览器检查：页面加载、关键片段切换、教师复核按钮、教师效果页签均正常；
        - 浏览器控制台：0 个错误、0 个警告；
        - API：`/api/health`、`/api/seewo_student_demo` 和页面资源返回正常；
        - 本包附带 `verify_demo.cmd`，用于检查缓存 JSON、77 个窗口、教师效果数据、页面图片和 HTML 渲染。

        跳过的测试主要对应未安装的可选 MuJoCo/训练环境，不影响当前 Seewo 离线展示。

        ## 16. 安装与使用方法

        ### 第一次使用

        1. 解压到不含特殊权限限制的本地目录；
        2. 安装 Python 3.10 至 3.12，并勾选“Add Python to PATH”；
        3. 双击 `install_environment.cmd`；
        4. 双击 `verify_demo.cmd`，应看到 `PASS`；
        5. 双击 `start_demo.cmd`；
        6. 浏览器自动打开 Demo。

        ### 已有 Python 和 NumPy

        可直接双击 `start_demo.cmd`。若没有自动打开浏览器，手动访问：

        ```text
        http://127.0.0.1:8791/seewo_student_demo
        ```

        ### 命令行启动

        ```powershell
        .venv\Scripts\python -m src.rehab_affect.scenario_lab_server `
          --host 127.0.0.1 --port 8791 --policy rule
        ```

        ## 17. 输入与输出

        | 类别 | 当前离线包 | 授权环境下的完整版本 |
        | --- | --- | --- |
        | 视频 | 不含原始 MP4，读取缓存结果 | 手动放入 Seewo 导出 MP4 |
        | 音频 | 缓存中保留音频活动特征 | 从课堂视频音轨自动提取 |
        | 评课报告 | 缓存中保留必要课堂背景 | 手动放入 Seewo 导出 Word |
        | 学生档案 | 匿名化摘要 | 授权后从 IEP/五大领域资料提取 |
        | 页面输出 | 状态趋势、关键片段、教师效果和动作建议 | 相同 |
        | 接口输出 | JSON API | 可继续接数据库、WebSocket 和 ROS2 |

        ## 18. 系统页面与状态展示

        ### 页面总览

        ![Demo 页面总览](docs/screenshots/demo_overview.png)

        ### 教师支持效果

        ![教师支持效果](docs/screenshots/teacher_effectiveness.png)

        ### 结构化 JSON

        ![教师效果 JSON](docs/screenshots/teacher_effectiveness_json.png)

        ## 19. 隐私与安全边界

        - 原始课堂视频、照片、IEP、PDF 和 Excel 未放入本包；
        - 页面示例仍包含低清课堂画面和匿名化教育支持信息，压缩包本身应按受限资料管理；
        - 不在公开代码仓库、公开网盘或无访问控制的服务器部署；
        - 不把状态输出解释为医学诊断，不将教师支持指数用于个人绩效排名；
        - 机器人高影响动作必须经过动作白名单、安全控制器和老师确认；
        - 真实数据重新分析必须取得学校/监护人授权，并记录用途、保存期限和删除方式。

        ## 20. 常见问题

        **页面打不开：** 先运行 `verify_demo.cmd`，再查看 `.runtime/demo_stderr.log`。  
        **端口占用：** PowerShell 执行 `./start_demo.ps1 -Port 8792`。  
        **没有网络：** 当前 Demo 是离线本地服务，不需要网络。  
        **换一台电脑能否打开：** 可以，但需要先解压、安装 Python 环境并在那台电脑上启动；`127.0.0.1` 不是公网地址。  
        **能否重新分析视频：** 可以，但原始数据未随包提供，需要授权后补齐并安装 `requirements-reanalysis.txt`。  
        **能否直接控制机器人：** 当前只输出动作协议和建议，真实机器人需要额外完成 WebSocket/ROS2 适配及安全验收。
        """,
    )


def _copy_project_files() -> None:
    _copy_tree(PROJECT_ROOT / "src", STAGE_DIR / "src")
    _copy_tree(PROJECT_ROOT / "configs", STAGE_DIR / "configs")
    _copy_tree(PROJECT_ROOT / "tests", STAGE_DIR / "tests")
    shutil.copy2(PROJECT_ROOT / "pyproject.toml", STAGE_DIR / "pyproject.toml")

    output_source = PROJECT_ROOT / "outputs" / "seewo_xiaoyudi_demo"
    output_destination = STAGE_DIR / "outputs" / "seewo_xiaoyudi_demo"
    _write_sanitized_json(
        output_source / "analysis.json",
        output_destination / "analysis.json",
    )
    for relative in (
        Path("frames/target_roi_reference.jpg"),
        Path("frames/timeline_contact_sheet.jpg"),
    ):
        destination = output_destination / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_source / relative, destination)

    _write_sanitized_json(
        PROJECT_ROOT / "data" / "processed" / "seewo_xiaoyudi_001" / "student_A_support_profile.json",
        STAGE_DIR / "data" / "processed" / "seewo_xiaoyudi_001" / "student_A_support_profile.json",
    )

    screenshot_sources = {
        "demo_overview.png": PROJECT_ROOT / "outputs" / "playwright" / "seewo_student_demo_ui_polished.png",
        "student_profile.png": PROJECT_ROOT / "outputs" / "playwright" / "manager_01_overview_with_profile.png",
        "teacher_effectiveness.png": PROJECT_ROOT / "outputs" / "playwright" / "seewo_teacher_effectiveness.png",
        "teacher_effectiveness_json.png": PROJECT_ROOT / "outputs" / "playwright" / "seewo_teacher_effectiveness_json.png",
    }
    screenshot_dir = STAGE_DIR / "docs" / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    for name, source in screenshot_sources.items():
        shutil.copy2(source, screenshot_dir / name)

    shutil.copy2(
        PROJECT_ROOT / "docs" / "seewo_school_demo_rehearsal_zh.md",
        STAGE_DIR / "docs" / "seewo_school_demo_rehearsal_zh.md",
    )
    shutil.copy2(
        SOURCE_CODE_DOCX,
        STAGE_DIR / "docs" / SOURCE_CODE_DOCX.name,
    )


def _write_manifest() -> None:
    lines = []
    for path in sorted(item for item in STAGE_DIR.rglob("*") if item.is_file()):
        if path.name == "MANIFEST_SHA256.txt":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(STAGE_DIR).as_posix()
        lines.append(f"{digest}  {relative}")
    (STAGE_DIR / "MANIFEST_SHA256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _privacy_scan() -> None:
    forbidden = ("Student H", str(PROJECT_ROOT), r"C:\Path\To\Developer")
    text_suffixes = {".json", ".md", ".py", ".toml", ".txt", ".ps1", ".cmd", ".csv"}
    findings = []
    for path in STAGE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in forbidden:
            if needle in text:
                findings.append(f"{path.relative_to(STAGE_DIR)}: {needle}")
    if findings:
        raise RuntimeError("Privacy scan failed:\n" + "\n".join(findings))


def _write_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in STAGE_DIR.rglob("*") if item.is_file()):
            archive.write(path, Path(PACKAGE_NAME) / path.relative_to(STAGE_DIR))


def build() -> None:
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    _safe_reset_directory(STAGE_DIR)
    _copy_project_files()
    _write_runtime_files()
    _write_private_data_notice()
    _write_readme()
    _privacy_scan()
    _write_manifest()
    _write_zip()
    print(STAGE_DIR)
    print(ZIP_PATH)


if __name__ == "__main__":
    build()
