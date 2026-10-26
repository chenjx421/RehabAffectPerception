"""Run the Demo2 1-10 local acceptance and write docs/local_acceptance_20261026.md.

Steps (each logged as a timestamped JSON line under ../.runtime/logs/):

1. Three focused regression groups with ``PYTHONPATH=src`` and an isolated,
   writable ``--basetemp`` per group: data loop, upload/media/FFmpeg, and
   portal/admin (including the gateway suite on its own).
2. ``compileall`` and ``git diff --check``.
3. ``scripts/local_synthetic_e2e_20261026.py``: one synthetic-video flow from
   login to admin downloads, plus a read-only ID-chain trace.

The results are compared with the 2026-10-25 baselines. Historical full
media/browser/recovery suites are intentionally not run or mixed in here.

Usage (from the repository root)::

    PYTHONPATH=src .venv/bin/python scripts/run_local_acceptance_20261026.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parent / ".runtime"
DOC = ROOT / "docs" / "local_acceptance_20261026.md"

GROUPS: list[dict[str, Any]] = [
    {
        "key": "data", "name": "数据闭环（IEP、学生关联、评分、报告）",
        "baseline": {"passed": 47, "max_skipped": None},
        "files": [
            "tests/test_demo2_iep_report_integration.py", "tests/test_demo2_report_store.py",
            "tests/test_demo2_course_analysis.py", "tests/test_demo2_evaluation_provenance.py",
            "tests/test_demo2_evaluation_store.py", "tests/test_demo2_dossier_iep_access.py",
            "tests/test_demo2_measurement_store.py", "tests/test_demo2_dual_track_evaluation.py",
            "tests/test_demo2_evaluation_api.py", "tests/test_demo2_classroom_report.py",
            "tests/test_demo2_classroom_report_http.py", "tests/test_verify_id_chain.py",
            "tests/test_measurement_scoring_standard.py",
        ],
    },
    {
        "key": "media", "name": "上传 / 媒体 / FFmpeg 调用路径",
        "baseline": {"passed": 350, "max_skipped": 3},
        "files": [
            "tests/test_demo2_media_analysis.py", "tests/test_demo2_media_api.py",
            "tests/test_demo2_media_cache.py", "tests/test_demo2_media_store.py",
            "tests/test_demo2_media_worker.py", "tests/test_demo2_upload_analysis_flow.py",
            "tests/test_demo2_upload_repair.py", "tests/test_demo2_upload_recovery_frontend.py",
            "tests/test_prepare_upload_video.py", "tests/test_cloud_media_smoke.py",
            "tests/test_demo2_frame_preview.py", "tests/test_video_applicability.py",
            "tests/test_student_record_store.py",
        ],
    },
    {
        "key": "portal", "name": "门户与后台（含网关、通道管理、后台刷新）",
        "baseline": {"passed": 340, "max_skipped": 1},
        "files": [
            "tests/test_demo2_manager_gateway.py", "tests/test_demo2_gateway_reject_drain.py",
            "tests/test_demo2_portal_html.py", "tests/test_demo2_portal_api.py",
            "tests/test_demo2_admin_refresh.py", "tests/test_demo2_admin_overview_tasks.py",
            "tests/test_demo2_channel_admin_html.py", "tests/test_demo2_channel_admin_store.py",
            "tests/test_scenario_lab_server.py",
        ],
    },
    {
        "key": "gateway", "name": "网关专项（门户组子集，单独复核）",
        "baseline": {"passed": 137, "max_skipped": 0},
        "files": ["tests/test_demo2_manager_gateway.py"],
    },
    {
        "key": "admin_analysis_guide", "name": "管理员无 task_id 访问 /demo2/analysis 断言（门户组子集）",
        "baseline": {"passed": 2, "max_skipped": 0},
        "files": ["tests/test_demo2_admin_overview_tasks.py", "tests/test_demo2_portal_api.py"],
        "select": "test_analysis_guide_reads_no_classroom_data or test_portal_pages_redirect_and_enforce_roles",
    },
]


class Log:
    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict[str, Any]] = []
        path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, group: str, step: str, result: str, **fields: Any) -> dict[str, Any]:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "group": group, "step": step, "result": result, **fields}
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"[{entry['ts']}] {group} {step} -> {result} "
              + json.dumps({k: v for k, v in fields.items() if k != "failed_cases"}, ensure_ascii=False), flush=True)
        return entry


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def junit_counts(path: Path) -> dict[str, Any]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    failed: list[str] = []
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0))
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(f"{case.get('classname')}::{case.get('name')}")
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    totals["failed_cases"] = failed
    return totals


def run_group(group: dict[str, Any], stamp: str, log: Log) -> dict[str, Any]:
    basetemp = RUNTIME / "pytest-tmp" / f"local_acceptance_{stamp}" / group["key"]
    junit = RUNTIME / "logs" / f"local_acceptance_{stamp}_{group['key']}.xml"
    # pytest creates --basetemp itself but not its parent directories.
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", "-q", "-rfEs", "-p", "no:cacheprovider",
               f"--basetemp={basetemp}", f"--junitxml={junit}", *group["files"]]
    if group.get("select"):
        command += ["-k", group["select"]]
    shown = "PYTHONPATH=src .venv/bin/python -m pytest -q -rfEs -p no:cacheprovider " \
            f"--basetemp=../.runtime/pytest-tmp/local_acceptance_{stamp}/{group['key']} " \
            + " ".join(group["files"]) + (f" -k \"{group['select']}\"" if group.get("select") else "")
    log.event(group["key"], "start", "INFO", name=group["name"], command=shown)
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True, text=True, check=False)
    seconds = round(time.monotonic() - started, 1)
    output = completed.stdout + completed.stderr
    (RUNTIME / "logs" / f"local_acceptance_{stamp}_{group['key']}.txt").write_text(output, encoding="utf-8")
    summary = next((line.strip("= ").strip() for line in reversed(output.splitlines())
                    if re.search(r"\d+ (passed|failed|error)", line)), "")
    skips = [line.strip() for line in output.splitlines() if line.startswith("SKIPPED")]
    counts = junit_counts(junit) if junit.exists() else {"tests": 0, "passed": 0, "failures": 0, "errors": 0,
                                                          "skipped": 0, "failed_cases": ["junit report missing"]}
    baseline = group["baseline"]
    meets = (completed.returncode == 0 and counts["failures"] == 0 and counts["errors"] == 0
             and counts["passed"] >= baseline["passed"]
             and (baseline["max_skipped"] is None or counts["skipped"] <= baseline["max_skipped"]))
    result = {**group, "command": shown, "exit_code": completed.returncode, "seconds": seconds,
              "summary": summary, "skip_reasons": skips, "meets_baseline": meets, **counts}
    log.event(group["key"], "finish", "PASS" if meets else "FAIL", name=group["name"], command=shown,
              exit_code=completed.returncode, passed=counts["passed"], failed=counts["failures"],
              errors=counts["errors"], skipped=counts["skipped"], failed_cases=counts["failed_cases"],
              baseline_passed=baseline["passed"], baseline_max_skipped=baseline["max_skipped"],
              summary=summary, seconds=seconds)
    return result


def run_simple(key: str, name: str, command: list[str], shown: str, log: Log) -> dict[str, Any]:
    log.event(key, "start", "INFO", name=name, command=shown)
    completed = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True, text=True, check=False)
    output = (completed.stdout + completed.stderr).strip()
    ok = completed.returncode == 0 and not output
    log.event(key, "finish", "PASS" if ok else "FAIL", name=name, command=shown,
              exit_code=completed.returncode, output=output[-2000:])
    return {"key": key, "name": name, "command": shown, "ok": ok, "exit_code": completed.returncode,
            "output": output[-2000:]}


def check_untracked_whitespace(log: Log) -> dict[str, Any]:
    """`git diff --check` ignores untracked files; apply the same rules to new text files."""
    key, name = "untracked_whitespace", "新增未跟踪文件空白检查"
    shown = "git ls-files --others --exclude-standard（逐行检查行尾空白 / 冲突标记）"
    log.event(key, "start", "INFO", name=name, command=shown)
    listed = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT,
                            capture_output=True, text=True, check=False).stdout.splitlines()
    problems, checked = [], 0
    for relative in listed:
        path = ROOT / relative
        if path.suffix not in {".py", ".md", ".js", ".json", ".txt", ".html", ".css", ".sh", ".toml"}:
            continue
        checked += 1
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line != line.rstrip() or line.startswith(("<<<<<<< ", ">>>>>>> ")):
                problems.append(f"{relative}:{number}")
    output = "\n".join(problems[:50])
    log.event(key, "finish", "FAIL" if problems else "PASS", name=name, command=shown,
              files_checked=checked, output=output)
    return {"key": key, "name": name, "command": shown, "ok": not problems, "exit_code": 1 if problems else 0,
            "output": output or f"检查 {checked} 个新增文本文件，无问题"}


def run_e2e(stamp: str, port: int, log: Log) -> dict[str, Any]:
    output = RUNTIME / "logs" / f"local_acceptance_{stamp}_e2e.json"
    e2e_log = RUNTIME / "logs" / f"local_acceptance_{stamp}_e2e.jsonl"
    shown = f"PYTHONPATH=src .venv/bin/python scripts/local_synthetic_e2e_20261026.py --port {port}"
    log.event("synthetic_e2e", "start", "INFO", command=shown)
    started = time.monotonic()
    completed = subprocess.run([sys.executable, "scripts/local_synthetic_e2e_20261026.py", "--port", str(port),
                                "--log", str(e2e_log), "--output", str(output)],
                               cwd=ROOT, env=environment(), capture_output=True, text=True, check=False)
    outcome = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {
        "ok": False, "steps": {}, "ids": {}, "error": completed.stderr[-2000:]}
    outcome.update(command=shown, exit_code=completed.returncode, seconds=round(time.monotonic() - started, 1),
                   step_log=[json.loads(line) for line in e2e_log.read_text(encoding="utf-8").splitlines()]
                   if e2e_log.exists() else [])
    chain = (((outcome.get("id_chain") or {}).get("result") or {}).get("results") or [{}])[0].get("chain", {})
    ids = outcome.get("ids", {})
    mismatches = [level for level in ("student_id", "iep_document_id", "course_id", "video_task_id",
                                      "evaluation_id", "report_id")
                  if ids.get(level) and chain.get(level) != [ids[level]]]
    outcome["chain"] = chain
    outcome["chain_matches_flow"] = bool(chain) and not mismatches
    outcome["chain_mismatches"] = mismatches
    ok = completed.returncode == 0 and outcome.get("ok") and outcome["chain_matches_flow"] \
        and (outcome.get("id_chain") or {}).get("exit_code") == 0 \
        and (outcome.get("checks") or {}).get("report_snapshot_without_iep_text") is True
    outcome["ok"] = bool(ok)
    steps = outcome.get("steps", {})
    log.event("synthetic_e2e", "finish", "PASS" if ok else "FAIL", command=shown,
              passed=sum(1 for item in steps.values() if item.get("result") == "PASS"),
              failed=sum(1 for item in steps.values() if item.get("result") == "FAIL"),
              not_run=sum(1 for item in steps.values() if item.get("result") == "NOT_RUN"),
              failed_cases=[key for key, item in steps.items() if item.get("result") != "PASS"],
              chain_matches_flow=outcome["chain_matches_flow"], seconds=outcome["seconds"])
    return outcome


def git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return completed.stdout.strip()


def cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\n", " ")


def render(stamp: str, groups: list[dict[str, Any]], checks: list[dict[str, Any]], e2e: dict[str, Any],
           log: Log, ffmpeg_info: str) -> str:
    # Local import keeps this runner usable even if the E2E module is edited.
    sys.path.insert(0, str(ROOT / "scripts"))
    from local_synthetic_e2e_20261026 import STEPS  # noqa: E402

    regression_ok = all(item["meets_baseline"] for item in groups)
    checks_ok = all(item["ok"] for item in checks)
    overall = regression_ok and checks_ok and e2e.get("ok")
    head, branch = git("rev-parse", "--short", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = len([line for line in git("status", "--porcelain").splitlines() if line.strip()])
    lines = [
        "# Demo2 1-10 本地验收记录（2026-10-26）",
        "",
        "> **数据声明**：本次验收只使用 FFmpeg 生成的合成测试图案视频（`testsrc2` 彩条 + 440 Hz 正弦音）、"
        "虚构学生（“虚构学生甲”，编号 `SYN-001`）和合成 IEP 摘要文本；未使用任何真实学生视频、真实学生资料、"
        "人脸截图或 IEP 原件。",
        ">",
        "> **准确性声明**：本文记录的是软件流程与数据链路的验收结果。流程中“输出了学生状态 / 评分 / 报告”只说明"
        "接口、存储、权限和关联关系可用，**教育准确性未验证**，不能作为学生识别、状态判断或评分准确的证据。",
        ">",
        "> **凭据声明**：测试账号由临时库按随机前缀生成，密码、会话 Cookie、Fernet 密钥只存在于测试进程内存，"
        "本文和日志不含任何密码、API Key、邀请密钥或部署私钥。本次未执行 GitHub 推送或云端部署，不代表“已发布”。",
        "",
        "## 1. 执行环境",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 执行时间 | {log.entries[0]['ts']} ~ {log.entries[-1]['ts']} |",
        f"| 分支 / HEAD | `{branch}` / `{head}`（工作区含 {dirty} 个未提交改动或新增文件，来自本轮 1-10 整合子任务） |",
        f"| 平台 | {platform.system()} {platform.release()} {platform.machine()}（macOS 开发机，非云端） |",
        f"| Python | {platform.python_version()}（仓库 `.venv`，uv 管理） |",
        f"| FFmpeg | {ffmpeg_info} |",
        "| 运行方式 | `PYTHONPATH=src`；每组独立可写 `--basetemp`（`../.runtime/pytest-tmp/local_acceptance_"
        f"{stamp}/<组名>`） |",
        f"| 原始日志 | `../.runtime/logs/local_acceptance_{stamp}.jsonl`（.runtime 不入库） |",
        "",
        "本机 FFmpeg 状态不能代替云端 `/usr/bin/ffmpeg`、`/usr/bin/ffprobe` 的确认。",
        "",
        "## 2. 三组回归测试",
        "",
        "| 测试组 | 文件数 | passed | failed | errors | skipped | 基线 | 结论 | 耗时 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in groups:
        base = item["baseline"]
        base_text = f"≥{base['passed']} passed" + ("" if base["max_skipped"] is None else f"，skipped ≤{base['max_skipped']}")
        lines.append(f"| {item['name']} | {len(item['files'])} | {item['passed']} | {item['failures']} | {item['errors']} | "
                     f"{item['skipped']} | {base_text} | {'通过' if item['meets_baseline'] else '**未通过**'} | {item['seconds']}s |")
    lines += ["", "基线来源：2026-10-25 交接说明（数据闭环 47 passed；媒体 350 passed, 3 skipped；门户 340 passed, "
              "1 skipped；网关专项 137 passed）。本次按同一范围选取文件，并补入后续子任务新增的相关测试，"
              "因此数量高于基线。历史全量媒体 / 浏览器 / 恢复套件未在本次运行，也不与本表混写。", ""]
    for item in groups:
        lines += [f"### {item['name']}", "", "```bash", item["command"], "```", "",
                  f"- pytest 汇总：`{item['summary']}`", f"- 退出码：{item['exit_code']}",
                  "- 失败用例：" + ("无" if not item["failed_cases"] else "、".join(f"`{c}`" for c in item["failed_cases"]))]
        if item["skip_reasons"]:
            lines.append("- 跳过原因：")
            lines += [f"  - `{reason}`" for reason in item["skip_reasons"]]
        lines.append("")
    lines += [
        "门户组中管理员访问无 `task_id` 的 `/demo2/analysis` 的断言为 **HTTP 200 安全引导页且不读取课堂数据**"
        "（`tests/test_demo2_admin_overview_tasks.py::test_analysis_guide_reads_no_classroom_data`、`tests/test_demo2_portal_api.py::test_portal_pages_redirect_and_enforce_roles`），"
        "上表“管理员无 task_id”行单独复核该断言；端到端第 9 步也在真实 HTTP 下再次确认。",
        "",
        "## 3. compileall 与 git diff --check",
        "",
        "| 检查 | 命令 | 结果 | 输出 |",
        "|---|---|---|---|",
    ]
    for item in checks:
        lines.append(f"| {item['name']} | `{item['command']}` | {'通过' if item['ok'] else '**未通过**'} | "
                     f"{cell(item['output'] or '无输出')} |")
    steps = e2e.get("steps", {})
    lines += [
        "",
        "## 4. 合成视频端到端流程",
        "",
        "```bash",
        e2e.get("command", ""),
        "```",
        "",
        "脚本在 `127.0.0.1:9185`（项目端口范围 9180-9199）启动隔离服务：临时 SQLite、临时上传目录、临时 Fernet "
        "资料密钥、真实 FFmpeg 和真实后台分析 worker；不触碰 `outputs/` 或任何正式数据库。合成视频："
        f"{(e2e.get('checks') or {}).get('video', {}).get('source', '')}，"
        f"{(e2e.get('checks') or {}).get('video', {}).get('bytes', '')} 字节，SHA256 "
        f"`{(e2e.get('checks') or {}).get('video', {}).get('sha256', '')}`。",
        "",
        "| # | 步骤 | 结果 | 关键记录 |",
        "|---|---|---|---|",
    ]
    for index, (key, label) in enumerate(STEPS, 1):
        step = steps.get(key, {"result": "NOT_RUN"})
        details = {k: v for k, v in step.items() if k != "result"}
        result = {"PASS": "通过", "FAIL": "**失败**", "NOT_RUN": "**未执行**"}.get(step.get("result"), step.get("result"))
        lines.append(f"| {index} | {label} | {result} | {cell(details)} |")
    student_state = steps.get("student_state", {})
    lines += [
        "",
        "说明：",
        "",
        "- 第 4 步“学生状态”：`/api/v1/demo2/simple-result` 与 `/demo2/simple-result` 页面均在任务范围内返回。"
        f"合成彩条画面中没有人脸，自动人物状态返回 `available={student_state.get('simple_analysis_available')}`、"
        f"`reason={student_state.get('simple_analysis_reason')}`，这是预期的诚实结果；随后教师在分析画面中把区域"
        "确认为虚构学生，并录入一条已复核的课堂测量记录，学生状态由该记录进入课程工作区。",
        "- 第 5、6 步：学校评分为教师录入的 10 项分数，系统评分为增强轨（证据修正 + 权重）结果；"
        "分差说明来自同一记录的 `comparison`，评分页同时展示“分差不表示系统比教师更准确”。",
        "- 第 7~10 步：教师侧报告保留 `iep_links`；公司管理员查看和下载（md/json）报告时 `iep_links` 已移除，"
        "合成 IEP 摘要文本未出现在任何下载内容或报告快照中"
        f"（快照检查：{(e2e.get('checks') or {}).get('report_snapshot_without_iep_text')}）。"
        "管理员下载的源视频与上传字节完全一致。",
        "",
        "### 4.1 贯通的 ID 链路（实际值）",
        "",
        "由 `scripts/verify_id_chain.py --report-id <report_id> --json --require-iep` 以只读方式从报告反向追溯，"
        f"退出码 `{(e2e.get('id_chain') or {}).get('exit_code')}`，并与端到端流程中接口返回的 ID 逐一比对"
        f"（一致：{e2e.get('chain_matches_flow')}{'' if not e2e.get('chain_mismatches') else '，不一致层级：' + '、'.join(e2e['chain_mismatches'])}）。",
        "",
        "| 层级 | 实际值 | 流程中接口返回值 |",
        "|---|---|---|",
    ]
    chain, ids = e2e.get("chain", {}), e2e.get("ids", {})
    for level in ("school_id", "student_id", "iep_document_id", "course_id", "video_task_id", "evaluation_id", "report_id"):
        lines.append(f"| `{level}` | `{', '.join(chain.get(level, [])) or '缺失'}` | "
                     f"`{ids.get(level, '（由学校快照派生，接口不直接返回）' if level == 'school_id' else '缺失')}` |")
    lines += [
        "",
        f"报告内容编号 `content_report_id` = `{ids.get('content_report_id', '')}`（与快照 `report_id` 按设计不同）。"
        "以上 ID 均来自本次临时库，测试结束后临时库随目录删除。",
        "",
        "## 5. 执行日志",
        "",
        "| 时间 | 测试组 | 步骤 | 结果 | 命令 | passed | failed | skipped | 失败用例 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in log.entries:
        if entry["step"] == "start":
            continue
        lines.append(f"| {entry['ts']} | {entry['group']} | {entry['step']} | {entry['result']} | "
                     f"`{cell(entry.get('command') or '-')}` |{entry.get('passed', '-')} | "
                     f"{entry.get('failed', '-') if 'errors' not in entry else entry['failed'] + entry['errors']} | "
                     f"{entry.get('skipped', entry.get('not_run', '-'))} | "
                     f"{cell('、'.join(entry.get('failed_cases') or []) or '无')} |")
    lines += ["", "端到端逐步日志：", "", "| 时间 | 步骤 | 结果 |", "|---|---|---|"]
    for entry in e2e.get("step_log", []):
        lines.append(f"| {entry['ts']} | {entry['step']} | {entry['result']} |")
    lines += [
        "",
        "## 6. 结论与仍存在的限制",
        "",
        f"- 三组回归：{'全部通过且不低于基线' if regression_ok else '存在未通过项，见上表'}。",
        f"- compileall / git diff --check：{'通过' if checks_ok else '未通过'}。",
        f"- 合成端到端：{'10 个步骤全部通过，ID 链路完整贯通' if e2e.get('ok') else '存在失败步骤，见第 4 节'}。",
        f"- 总体：{'本地验收通过' if overall else '本地验收未通过'}。",
        "- 限制：本地 macOS 结果不代表腾讯云环境；云端仍需按 `docs/integration_handoff_20261025.md` 完成备份、"
        "FFmpeg/ffprobe 确认、预检、`cloud_media_smoke.py` 和完整 `cloud_e2e_acceptance.py`。",
        "- 限制：合成彩条视频不含人物，不验证人脸检测、学生识别或状态判断的准确性；评分仅验证计算与存储链路。",
        "- 限制：GitHub 推送与云端部署未执行，不得描述为“已发布”。",
        "",
    ]
    return "\n".join(lines)


def scan_sensitive(text: str) -> list[str]:
    patterns = {
        "private_key": r"BEGIN [A-Z ]*PRIVATE KEY",
        "api_key": r"\b(sk|ak|AKID)[-_][A-Za-z0-9]{16,}",
        "fernet_key": r"\b[A-Za-z0-9_-]{43}=",
        "password_assignment": r"(?i)password\s*[:=]\s*\S{4,}",
        "github_token": r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9185)
    parser.add_argument("--output", type=Path, default=DOC)
    args = parser.parse_args(argv)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = Log(RUNTIME / "logs" / f"local_acceptance_{stamp}.jsonl")
    log.event("setup", "start", "INFO", root=str(ROOT.name), python=platform.python_version())
    groups = [run_group(group, stamp, log) for group in GROUPS]
    checks = [
        run_simple("compileall", "compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"],
                   "PYTHONPATH=src .venv/bin/python -m compileall -q src tests scripts", log),
        run_simple("git_diff_check", "git diff --check", ["git", "diff", "--check"], "git diff --check", log),
        check_untracked_whitespace(log),
    ]
    e2e = run_e2e(stamp, args.port, log)
    ffmpeg_path = e2e.get("ffmpeg") or ""
    version = ""
    if ffmpeg_path:
        probe = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, check=False)
        version = (probe.stdout.splitlines() or [""])[0]
    ffmpeg_info = f"`{ffmpeg_path}`（{version.split(' Copyright')[0]}）" if ffmpeg_path else "未找到"
    log.event("finish", "summary", "PASS" if all(g["meets_baseline"] for g in groups)
              and all(c["ok"] for c in checks) and e2e.get("ok") else "FAIL")
    document = render(stamp, groups, checks, e2e, log, ffmpeg_info)
    leaks = scan_sensitive(document)
    if leaks:
        log.event("finish", "sensitive_scan", "FAIL", patterns=leaks)
        print("sensitive patterns found: " + ", ".join(leaks), file=sys.stderr)
        return 2
    args.output.write_text(document, encoding="utf-8")
    log.event("finish", "document", "PASS", path=str(args.output.relative_to(ROOT)))
    return 0 if log.entries[-2]["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
