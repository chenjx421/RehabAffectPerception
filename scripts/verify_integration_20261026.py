"""Verify the Demo2 1-10 integration branch before further feature work.

The script is read-only for source code. It records every check as a
timestamped JSON line under ``.runtime/logs`` and writes a Markdown copy to
``docs/integration_check_log_20261026.md`` so a later reviewer can see which
branch, commits, entry files, ignore rules and Python checks were confirmed.

Usage (from the repository root)::

    PYTHONPATH=src .venv/bin/python scripts/verify_integration_20261026.py
    PYTHONPATH=src .venv/bin/python scripts/verify_integration_20261026.py --fetch --pytest
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "integration/demo2-1-10"
REMOTE_URL = "https://github.com/chenjx421/RehabAffectPerception"
LEGACY_REMOTE_HEAD = "7b6a3d6"

REQUIRED_COMMITS = (
    ("051b0ab", "Keep upload flow focused and refresh legacy checks"),
    ("df0710f", "Harden IEP joins and admin report privacy"),
    ("a3208e0", "Require task scope for company analysis access"),
    ("3b355be", "Fix Demo2 upload processing and cloud deployment integration"),
)

# Each entry: (capability, file, required substrings). Substrings are function
# names or route literals; a missing file or substring means the original
# Demo1/Demo2 capability was lost.
LEGACY_ENTRIES = (
    ("Demo2 上传页", "src/rehab_affect/demo2_portal.py", ("def render_demo2_upload_html", "uploadProgress")),
    ("Demo2 分片上传/续传 API", "src/rehab_affect/demo2_manager_gateway.py",
     ("/api/v1/demo2/upload/chunks", "/api/v1/demo2/upload/resume", "/api/v1/demo2/upload/task")),
    ("Demo2 上传任务建档", "src/rehab_affect/student_record_store.py", ("def create_video_task",)),
    ("Demo1/旧版视频分片上传", "src/rehab_affect/scenario_lab_server.py",
     ("/api/seewo_demo2/video_chunk", "/api/seewo_demo2/video_task")),
    ("Demo1 单学生状态时间轴", "src/rehab_affect/seewo_student_demo.py", ("timeline",)),
    ("Demo1 多学生状态时间轴", "src/rehab_affect/seewo_multi_student_demo.py", ("timeline",)),
    ("Demo2 人物学生状态时间轴页", "src/rehab_affect/demo2_simple_result.py",
     ("def render_simple_result", "学生状态时间轴")),
    ("Demo2 学生跟踪", "src/rehab_affect/demo2_student_tracking.py", ("timeline",)),
    ("Demo2 媒体分析", "src/rehab_affect/demo2_media_analysis.py", ("timeline",)),
    ("Demo1 长报告", "src/rehab_affect/seewo_long_report.py", ("def build_long_course_report",)),
    ("Demo2 课程报告构建", "src/rehab_affect/demo2_course_analysis.py", ("def build_workspace", "def build_report")),
    ("Demo2 报告快照与下载", "src/rehab_affect/demo2_report_store.py",
     ("def save_from_workspace", "def download", "def list_admin")),
    ("报告/分析 API", "src/rehab_affect/demo2_manager_gateway.py",
     ("/api/v1/demo2/course-analysis", "/api/v1/demo2/reports/download", "/api/v1/demo2/admin/reports")),
    ("视频结果下载", "src/rehab_affect/scenario_lab_server.py", ("/api/seewo_demo2/video_result_download",)),
    ("视频结果下载存储", "src/rehab_affect/student_record_store.py",
     ("def video_result_for_download", "def account_video_result_for_download")),
    ("资料原件下载", "src/rehab_affect/demo2_dossier_store.py", ("def document_download",)),
    ("页面路由", "src/rehab_affect/scenario_lab_server.py",
     ('"/demo2/upload"', '"/demo2/analysis"', '"/demo2/simple-result"', '"/demo2/admin"', '"/seewo_student_demo"')),
    ("公司后台页", "src/rehab_affect/demo2_portal.py", ("def render_demo2_admin_html",)),
    ("Windows 启动入口 Demo1", "start_school_demo.cmd", ()),
    ("Windows 启动入口 Demo2", "start_school_demo2.cmd", ()),
)

ID_CHAIN = ("school_id", "student_id", "iep_document_id", "iep_summary_id", "course_id",
            "video_task_id", "task_id", "evaluation_id", "report_id")

IGNORE_PROBES = (
    ".runtime/demo2.sqlite3",
    ".runtime/demo2.sqlite3-wal",
    ".runtime/demo2.sqlite3-shm",
    ".runtime/keys/dossier.key",
    ".runtime/secrets/fernet.key",
    ".runtime/invitations.json",
    ".runtime/uploads/lesson.mp4",
    ".runtime/cloud_candidate_20261026/source.tar.gz",
    "data/raw/real_lesson.mov",
    "classroom.db",
    "deploy/cloud/.env",
    "deploy/cloud/id_ed25519",
    "deploy/cloud/server.pem",
)

PYTEST_DATA_LOOP = (
    "tests/test_demo2_iep_report_integration.py",
    "tests/test_demo2_report_store.py",
    "tests/test_demo2_course_analysis.py",
    "tests/test_demo2_evaluation_provenance.py",
)


class CheckLog:
    def __init__(self, jsonl_path: Path) -> None:
        self.path = jsonl_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict[str, Any]] = []

    def record(self, operation: str, status: str, **params: Any) -> dict[str, Any]:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "op": operation, "status": status, **params}
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        detail = " ".join(f"{k}={v}" for k, v in params.items() if k != "output")
        print(f"[{entry['ts']}] {operation:<14} {status:<5} {detail}")
        return entry

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["status"] == "FAIL"]


def run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_git(log: CheckLog, fetch: bool) -> None:
    if fetch:
        code, out = run(["git", "fetch", "origin", BRANCH], timeout=300)
        log.record("fetch", "PASS" if code == 0 else "FAIL", remote=REMOTE_URL, branch=BRANCH, output=out[-500:])
    code, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    log.record("checkout", "PASS" if code == 0 and branch == BRANCH else "FAIL", expected=BRANCH, actual=branch)
    code, head = run(["git", "rev-parse", "--short=7", "HEAD"])
    log.record("head", "PASS" if code == 0 else "FAIL", sha=head)
    code, remote_head = run(["git", "rev-parse", "--short=7", f"origin/{BRANCH}"])
    if code == 0:
        log.record("remote-head", "FAIL" if remote_head == LEGACY_REMOTE_HEAD else "PASS",
                   sha=remote_head, legacy_head=LEGACY_REMOTE_HEAD,
                   note="remote still at legacy head" if remote_head == LEGACY_REMOTE_HEAD else "remote advanced past legacy head")
    else:
        log.record("remote-head", "FAIL", sha="", output=remote_head)
    for sha, subject in REQUIRED_COMMITS:
        code, out = run(["git", "log", "-1", "--format=%h|%ad|%s", "--date=iso", sha])
        found = code == 0 and out.split("|")[-1] == subject
        ancestor_code, _ = run(["git", "merge-base", "--is-ancestor", sha, "HEAD"])
        log.record("log-check", "PASS" if found and ancestor_code == 0 else "FAIL",
                   sha=sha, subject=subject, in_head_history=ancestor_code == 0, actual=out)
    code, status = run(["git", "status", "--porcelain", "--untracked-files=no"])
    log.record("worktree", "PASS" if code == 0 else "FAIL", tracked_changes=len(status.splitlines()) if status else 0)


def check_legacy_entries(log: CheckLog) -> None:
    for capability, rel, needles in LEGACY_ENTRIES:
        path = ROOT / rel
        if not path.is_file():
            log.record("entry-file", "FAIL", capability=capability, file=rel, missing="file")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [needle for needle in needles if needle not in text]
        log.record("entry-file", "FAIL" if missing else "PASS", capability=capability, file=rel,
                   missing=",".join(missing) or "-")


def check_id_chain(log: CheckLog) -> None:
    sources = list((ROOT / "src" / "rehab_affect").glob("*.py"))
    for field in ID_CHAIN:
        files = sorted(p.name for p in sources if field in p.read_text(encoding="utf-8", errors="replace"))
        # Missing aliases are expected; the gap report explains the mapping.
        log.record("id-field", "PASS" if files else "INFO", field=field, file_count=len(files),
                   files=",".join(files[:8]))


def check_ignore(log: CheckLog) -> None:
    code, tracked = run(["git", "ls-files", ".runtime"])
    log.record("tracked-runtime", "PASS" if code == 0 and not tracked else "FAIL",
               tracked_count=len(tracked.splitlines()) if tracked else 0)
    code, tracked_sensitive = run(["git", "ls-files", "*.db", "*.sqlite", "*.sqlite3", "*.pem", "*.key", "*.mp4", "*.mov"])
    log.record("tracked-sensitive", "PASS" if code == 0 and not tracked_sensitive else "FAIL",
               files=tracked_sensitive.replace("\n", ",") or "-")
    for probe in IGNORE_PROBES:
        code, out = run(["git", "check-ignore", "-v", "--no-index", probe])
        log.record("gitignore", "PASS" if code == 0 else "FAIL", path=probe, rule=out or "not ignored")


def check_python(log: CheckLog, with_pytest: bool) -> None:
    env = dict(os.environ, PYTHONPATH="src")
    code, out = run([sys.executable, "-c", "import rehab_affect, rehab_affect.scenario_lab_server, "
                     "rehab_affect.demo2_manager_gateway, rehab_affect.demo2_report_store; "
                     "print(rehab_affect.__file__)"], env=env)
    log.record("import", "PASS" if code == 0 else "FAIL", python=sys.version.split()[0], output=out[-300:])
    code, out = run([sys.executable, "-m", "compileall", "-q", "src"], env=env)
    log.record("compileall", "PASS" if code == 0 else "FAIL", target="src", warnings=out.count("Warning"),
               output=out[-300:])
    if not with_pytest:
        return
    tmp = ROOT / ".runtime" / "pytest-tmp" / datetime.now().strftime("%Y%m%d%H%M%S")
    tmp.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={tmp}", *PYTEST_DATA_LOOP]
    code, out = run(cmd, env=env, timeout=1800)
    summary = out.splitlines()[-1] if out else ""
    log.record("pytest", "PASS" if code == 0 else "FAIL", basetemp=str(tmp.relative_to(ROOT)), summary=summary,
               output=out[-1500:] if code else "")


def write_markdown(log: CheckLog, target: Path) -> None:
    lines = [
        "# Demo2 1-10 整合核对日志（2026-10-26）",
        "",
        f"由 `scripts/verify_integration_20261026.py` 生成；原始 JSONL：`{log.path.relative_to(ROOT).as_posix()}`（.runtime 不入库）。",
        "",
        f"失败项：{len(log.failures)}",
        "",
        "| 时间 | 操作 | 结果 | 关键参数 |",
        "|---|---|---|---|",
    ]
    for entry in log.entries:
        params = "; ".join(f"{k}={v}" for k, v in entry.items() if k not in {"ts", "op", "status", "output"} and v != "")
        lines.append(f"| {entry['ts']} | {entry['op']} | {entry['status']} | {params.replace('|', '/')} |")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="fetch the integration branch before checking")
    parser.add_argument("--pytest", action="store_true", help="run the focused data-loop tests in an isolated basetemp")
    parser.add_argument("--markdown", default="docs/integration_check_log_20261026.md")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = CheckLog(ROOT / ".runtime" / "logs" / f"integration_check_{stamp}.jsonl")
    log.record("start", "INFO", root=str(ROOT), branch=BRANCH)
    check_git(log, args.fetch)
    check_legacy_entries(log)
    check_id_chain(log)
    check_ignore(log)
    check_python(log, args.pytest)
    log.record("finish", "PASS" if not log.failures else "FAIL", failures=len(log.failures))
    write_markdown(log, ROOT / args.markdown)
    return 0 if not log.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
