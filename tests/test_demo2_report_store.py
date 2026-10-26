"""Synthetic integration coverage for persistent Demo2 classroom reports."""

from __future__ import annotations

import json

from rehab_affect.demo2_measurement_store import Demo2MeasurementStore
from rehab_affect.demo2_report_store import Demo2ReportStore, ReportError
from test_demo2_evaluation_store import env
from test_demo2_evaluation_api import http_env
from test_demo2_identity_store import make_task


def report_workspace(env, task):
    return Demo2MeasurementStore(env.record).course_workspace(task.token, task.task_id)


def test_report_snapshot_is_idempotent_and_downloads_current_payload(env):
    env.record = env.records
    env.sessions = {
        "school_uploader_01": (env.records.account_from_session(env.tokens["t1"]), env.tokens["t1"]),
    }
    task = make_task(env)
    store = Demo2ReportStore(env.records)
    workspace = report_workspace(env, task)

    first = store.save_from_workspace(task.token, workspace)
    second = store.save_from_workspace(task.token, workspace)

    assert first["report_id"] == second["report_id"]
    assert first["task_id"] == task.task_id
    assert first["source_sha256"] == task.result["source_sha256"]

    listed = store.list_for_task(task.token, task.task_id)
    assert [item["report_id"] for item in listed["reports"]] == [first["report_id"]]

    markdown, filename, content_type = store.download(task.token, first["report_id"], fmt="md")
    assert filename.endswith(".md")
    assert content_type.startswith("text/markdown")
    assert first["title"] in markdown

    encoded, filename, content_type = store.download(task.token, first["report_id"], fmt="json")
    assert filename.endswith(".json")
    assert content_type.startswith("application/json")
    assert json.loads(encoded)["task_id"] == task.task_id


def test_company_admin_can_list_and_download_but_other_school_cannot(env):
    env.record = env.records
    env.sessions = {
        "school_uploader_01": (env.records.account_from_session(env.tokens["t1"]), env.tokens["t1"]),
    }
    task = make_task(env)
    store = Demo2ReportStore(env.records)
    report = store.save_from_workspace(task.token, report_workspace(env, task))

    admin = store.list_admin(env.tokens["admin"])
    assert admin["pagination"]["total"] == 1
    assert admin["reports"][0]["report_id"] == report["report_id"]
    assert store.get(env.tokens["admin"], report["report_id"])["payload"]

    try:
        store.get(env.tokens["t2"], report["report_id"])
    except ReportError as exc:
        assert exc.status == 403
        assert exc.code == "report_forbidden"
    else:
        raise AssertionError("a different school account must not read the report")


def test_course_analysis_endpoint_persists_report_and_admin_route_lists_it(env, http_env):
    env.record = env.records
    env.sessions = {
        "school_uploader_01": (env.records.account_from_session(env.tokens["t1"]), env.tokens["t1"]),
    }
    task = make_task(env)

    status, _, body = http_env(f"/api/v1/demo2/course-analysis?task_id={task.task_id}")
    assert status == 200
    report = body["report_saved"]
    assert report["report_id"]

    status, _, body = http_env("/api/v1/demo2/admin/reports", user="admin")
    assert status == 200
    assert body["reports"][0]["report_id"] == report["report_id"]

    status, headers, body = http_env(
        f"/api/v1/demo2/reports/download?report_id={report['report_id']}&fmt=json",
        user="admin",
    )
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert body["report_id"] == report["report_id"]
