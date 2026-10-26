"""HTTP contract for stale classroom report downloads (synthetic data only)."""
from test_demo2_evaluation_store import env  # noqa: F401  (fixture)
from test_demo2_evaluation_api import http_env  # noqa: F401  (fixture)
from test_demo2_identity_store import make_task


def test_http_stale_download_returns_expired_flag(env, http_env):
    env.record = env.records
    env.sessions = {"school_uploader_01": (env.records.account_from_session(env.tokens["t1"]),
                                                env.tokens["t1"])}
    task = make_task(env)
    status, _, body = http_env(f"/api/v1/demo2/course-analysis?task_id={task.task_id}")
    assert status == 200
    report_id = body["report_saved"]["report_id"]
    assert body["report_saved"]["status_label"] in {"可下载", "证据待补充"}
    status, _, _ = http_env(f"/api/v1/demo2/reports/download?report_id={report_id}&fmt=md")
    assert status == 200
    with env.records._connect() as db:
        db.execute("UPDATE video_analysis_tasks SET sha256=? WHERE task_id=?", ("0" * 64, task.task_id))
    for user in ("t1", "admin"):
        status, _, body = http_env(f"/api/v1/demo2/reports/download?report_id={report_id}&fmt=json", user=user)
        assert status == 409
        assert body["error"]["code"] == "report_stale"
        assert body["error"]["stale"] is True and body["error"]["status_label"] == "已过期"
        assert body["error"]["action"] == "regenerate"
    status, _, body = http_env("/api/v1/demo2/admin/reports", user="admin")
    assert body["reports"][0]["stale"] is True
