"""Company backend overview, task query, report/video download and the
task-less analysis guide (synthetic accounts and media only)."""
import json

import pytest

from src.rehab_affect import demo2_manager_gateway as gateway
from src.rehab_affect.demo2_admin_debug import DEBUG_LOG_DIR_ENV, admin_debug_event
from src.rehab_affect.demo2_portal import render_demo2_admin_html
from test_demo2_evaluation_store import env  # noqa: F401  (fixture)
from test_demo2_evaluation_api import http_env  # noqa: F401  (fixture)
from test_demo2_identity_store import make_task


@pytest.fixture
def admin_log(tmp_path, monkeypatch):
    folder = tmp_path / "admin-logs"
    monkeypatch.setenv(DEBUG_LOG_DIR_ENV, str(folder))

    def read():
        lines = []
        for path in sorted(folder.glob("admin_debug_*.jsonl")):
            lines.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return lines
    return read


def _prepare(env):
    env.record = env.records
    env.sessions = {"school_uploader_01": (env.records.account_from_session(env.tokens["t1"]),
                                           env.tokens["t1"])}
    return make_task(env)


def test_overview_layout_matches_design():
    html = render_demo2_admin_html({"username": "admin", "role": "company_admin"})
    for text in ("学校内测运行状态", "账号、通道、课程名额、任务和存储数据全部来自后台汇总接口。", "刷新数据",
                 "学生资料运行状态（仅元数据）", "测量记录与保存状态", "学校上传账号", "视频通道", "任务总数",
                 "包含已完成、上传中和已取消", "总存储", "通道运行状态", "管理上传通道", "测量记录汇总", "退出",
                 "后台数据已刷新", "任务查询"):
        assert text in html
    shortcuts = html.split('class="admin-shortcuts"', 1)[1].split("</nav>", 1)[0]
    assert shortcuts.count("<a ") == 2
    assert "/demo2/admin/dossiers" in shortcuts and "/demo2/admin/measurements" in shortcuts
    # The previous summary-library entry is kept, just outside the shortcut row.
    assert "/demo2/admin/student-summaries" in html
    assert "byId('accountTitle').textContent=`${accounts.length} 账号 / ${channels.length} 通道状态`" in html


def test_admin_task_query_store_filters_and_role(env):
    task = _prepare(env)
    admin = env.tokens["admin"]
    found = env.records.admin_task_query(admin)
    assert [item["task_id"] for item in found["tasks"]] == [task.task_id]
    row = found["tasks"][0]
    assert row["username"] == "school_uploader_01" and row["upload_status"] == "completed"
    assert row["analysis_status"] == "evidence_ready" and row["media_available"] is True
    assert "file_path" not in row and "processing_result_json" not in row
    assert env.records.admin_task_query(admin, query=task.task_id)["pagination"]["total"] == 1
    assert env.records.admin_task_query(admin, query="身份绑定")["pagination"]["total"] == 1
    assert env.records.admin_task_query(admin, query="100%_")["pagination"]["total"] == 0
    assert env.records.admin_task_query(admin, analysis_status="failed")["tasks"] == []
    with pytest.raises(ValueError):
        env.records.admin_task_query(env.tokens["t1"])
    with pytest.raises(ValueError):
        env.records.admin_task_query(admin, analysis_status="bad status")
    with pytest.raises(ValueError):
        env.records.admin_task_query(admin, query="x" * 81)


def test_task_query_reports_and_downloads_without_iep_links(env, http_env, admin_log):
    task = _prepare(env)
    status, _, body = http_env(f"/api/v1/demo2/course-analysis?task_id={task.task_id}")
    assert status == 200
    report_id = body["report_saved"]["report_id"]

    assert http_env("/api/v1/demo2/admin/tasks")[0] == 403
    assert http_env("/api/v1/demo2/admin/tasks?bogus=1", user="admin")[0] == 400
    assert http_env("/api/v1/demo2/admin/tasks?page=0", user="admin")[0] == 400
    status, _, body = http_env(f"/api/v1/demo2/admin/tasks?q={task.task_id}", user="admin")
    assert status == 200 and body["pagination"]["total"] == 1
    item = body["tasks"][0]
    assert item["task_id"] == task.task_id and item["analysis_status"] == "evidence_ready"
    assert [report["report_id"] for report in item["reports"]] == [report_id]

    status, _, view = http_env(f"/api/v1/demo2/reports?report_id={report_id}", user="admin")
    assert status == 200 and "iep_links" not in json.dumps(view, ensure_ascii=False)
    for fmt in ("md", "json"):
        status, headers, raw = http_env(f"/api/v1/demo2/reports/download?report_id={report_id}&fmt={fmt}",
                                        user="admin")
        assert status == 200 and "attachment" in headers["Content-Disposition"]
        assert "iep_links" not in (raw if isinstance(raw, (bytes, bytearray)) else json.dumps(raw)).__str__()

    status, headers, raw = http_env(f"/api/v1/demo2/upload/media?id={task.task_id}&download=1", user="admin")
    assert status == 200 and raw == b"synthetic uploaded source, not real student media"
    assert headers["Content-Disposition"].startswith("attachment;") and task.task_id in headers["Content-Disposition"]
    status, headers, _ = http_env(f"/api/v1/demo2/upload/media?id={task.task_id}", user="admin")
    assert status == 200 and "Content-Disposition" not in headers

    entries = admin_log()
    operations = {entry["operation"] for entry in entries}
    assert {"admin_task_query", "admin_report_view", "admin_report_download",
            "admin_video_download", "admin_video_view"} <= operations
    for entry in entries:
        assert entry["ts"] and entry["result"] and entry["admin_account"] == "company_admin"
    query = next(entry for entry in entries if entry["operation"] == "admin_task_query" and entry["result"] == "ok")
    assert query["task_id"] == task.task_id and query["result_count"] == 1 and query["report_count"] == 1
    download = next(entry for entry in entries if entry["operation"] == "admin_report_download")
    assert download["task_id"] == task.task_id and download["report_id"] == report_id
    video = next(entry for entry in entries if entry["operation"] == "admin_video_download")
    assert video["task_id"] == task.task_id and video["http_status"] == 200
    # Search text never reaches the log, only its length.
    assert all(task.task_id not in str(entry.get("message", "")) for entry in entries)


def test_summary_refresh_logs_counts(env, http_env, admin_log):
    _prepare(env)
    status, _, body = http_env("/api/v1/demo2/admin/summary", user="admin")
    assert status == 200
    summary = body["summary"]
    entry = [item for item in admin_log() if item["operation"] == "admin_refresh"][-1]
    assert entry["result"] == "ok" and entry["admin_account"] == "company_admin"
    assert entry["account_count"] == len(summary["upload_accounts"])
    assert entry["channel_count"] == len(summary["channels"])
    assert entry["task_total"] == summary["task_status"]["total"] == 1
    assert entry["storage_bytes"] == sum(item["byte_size"] for item in summary["storage"].values())


def test_analysis_guide_reads_no_classroom_data(env, http_env, admin_log, monkeypatch):
    _prepare(env)
    touched = []
    for name in ("admin_task_query", "account_video_task", "account_simple_analysis", "admin_platform_summary"):
        monkeypatch.setattr(env.records, name, lambda *args, _name=name, **kwargs: touched.append(_name))
    status, headers, raw = http_env("/demo2/analysis", user="admin")
    assert status == 200 and "no-store" in headers["Cache-Control"]
    page = raw.decode("utf-8")
    assert "请从任务记录进入" in page and "请选择课堂任务" in page
    assert touched == []
    entry = [item for item in admin_log() if item["operation"] == "admin_analysis_guide"][-1]
    assert entry["result"] == "guide_shown" and entry["classroom_data_read"] is False
    assert entry["admin_account"] == "company_admin" and entry["http_status"] == 200


def test_analysis_with_task_id_checks_authorization(env, http_env, admin_log):
    task = _prepare(env)
    assert http_env("/demo2/analysis?task_id=unknown-task", user="admin")[0] == 403
    assert http_env("/demo2/analysis?task_id=unknown-task", user="t2")[0] == 403
    assert http_env(f"/demo2/analysis?task_id={task.task_id}", user="t2")[0] == 403
    # The owner still opens the classroom workspace normally.
    assert http_env(f"/demo2/analysis?task_id={task.task_id}", user="t1")[0] == 200
    # Company admins never read the teacher classroom workspace; the task-scoped
    # check runs and refuses with 403 instead of falling back to any data.
    assert http_env(f"/demo2/analysis?task_id={task.task_id}", user="admin")[0] == 403
    entries = admin_log()
    denied = [item for item in entries if item["operation"] == "admin_analysis_denied"]
    assert [item["task_id"] for item in denied] == ["unknown-task", task.task_id]
    assert all(item["http_status"] == 403 and item["admin_account"] == "company_admin" for item in denied)
    # The admin role is refused before the task row is even looked up.
    assert {item["code"] for item in denied} == {"measurement_forbidden"}
    # Teacher traffic is not written to the admin log.
    assert not [item for item in entries if item.get("role") != "company_admin"]


def test_gateway_and_log_sanitizing(tmp_path, monkeypatch):
    assert "/api/v1/demo2/admin/tasks" in gateway._GET_API
    monkeypatch.setenv(DEBUG_LOG_DIR_ENV, str(tmp_path))
    entry = admin_debug_event(None, "admin_task_query", "ok", task_id="张三.mp4", admin_account="admin",
                              query_length=4, secret="never")
    assert entry["task_id"] == "<invalid>" and "secret" not in entry
    assert admin_debug_event(None, "drop_table", "ok")["operation"] == "<invalid>"
