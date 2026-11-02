"""「我的课堂分析」入口：教师任务报告状态、过期重建提示与调试日志。"""
import json

import pytest

from rehab_affect import demo2_course_page
from rehab_affect.demo2_report_store import Demo2ReportStore, ReportError, stale_reason_codes
from rehab_affect.scenario_lab_server import _render_admin_analysis_guide
from test_demo2_dossier_store import env, template  # noqa: F401  (pytest fixtures)
from test_demo2_iep_report_integration import prepared


@pytest.fixture
def report_logs(tmp_path, monkeypatch):
    folder = tmp_path / "report-logs"
    monkeypatch.setenv("REHAB_DEMO2_REPORT_DEBUG_LOG_DIR", str(folder))

    def read():
        lines = []
        for path in sorted(folder.glob("report_debug_*.jsonl")):
            lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return lines
    return read


def test_task_list_reports_only_own_snapshots_and_flags_stale(env, report_logs):
    video, auth, _, _, measurements, _, _, _, _ = prepared(env)
    reports = Demo2ReportStore(env.records)
    assert reports.teacher_task_reports(env.tokens['a'], [video.task_id]) == {}
    snapshot = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    assert snapshot['previous_stale'] is False and snapshot['previous_stale_codes'] == []
    listed = reports.teacher_task_reports(env.tokens['a'], [video.task_id])[video.task_id]
    assert listed['report_id'] == snapshot['report_id'] and listed['report_short'] == snapshot['report_id'][:8]
    assert listed['stale'] is False and listed['status'] == 'saved'
    # Another school's teacher never sees this task's report.
    assert reports.teacher_task_reports(env.tokens['b'], [video.task_id]) == {}
    with pytest.raises(ReportError) as denied:
        reports.teacher_task_reports(env.tokens['admin'], [video.task_id])
    assert denied.value.status == 403

    env.store.withdraw_authorization(env.tokens['a'], {'student_id': env.pupils['a1']['student_id'],
        'authorization_id': auth['authorization_id'], 'confirmed': True})
    listed = reports.teacher_task_reports(env.tokens['a'], [video.task_id])[video.task_id]
    assert listed['stale'] is True and listed['status_label'] == '已过期'
    assert listed['stale_codes'] == ['iep_source_unavailable']
    with pytest.raises(ReportError) as stale:
        reports.download(env.tokens['a'], snapshot['report_id'])
    assert stale.value.code == 'report_stale' and stale.value.status == 409

    regenerated = reports.save_from_workspace(env.tokens['a'], measurements.course_workspace(env.tokens['a'], video.task_id))
    assert regenerated['report_id'] == snapshot['report_id']
    assert regenerated['previous_stale'] is True and 'iep_source_unavailable' in regenerated['previous_stale_codes']
    for fmt in ('md', 'json'):
        reports.download(env.tokens['a'], regenerated['report_id'], fmt=fmt)

    logs = report_logs()
    listing = [e for e in logs if e['operation'] == 'analysis_task_list']
    assert listing and listing[-1]['role'] == 'teacher' and listing[-1]['stale_count'] == 1
    assert all(e['ts'] for e in listing)
    rebuilt = [e for e in logs if e['operation'] == 'report_generate' and e.get('previous_stale')]
    assert rebuilt and rebuilt[-1]['report_short'] == snapshot['report_id'][:8]
    assert any(r.startswith('iep_source_unavailable') for r in rebuilt[-1]['stale_reasons'])
    downloads = [e for e in logs if e['operation'] == 'report_download']
    assert downloads and all(e['report_short'] == snapshot['report_id'][:8] for e in downloads)
    assert env.pupils['a1']['display_name'] not in json.dumps(logs, ensure_ascii=False)


def test_stale_reason_codes_drop_record_ids():
    assert stale_reason_codes(['record_changed:abc', 'record_changed:def', 'iep_source_unavailable:doc:withdrawn',
                               'source_changed']) == ['record_changed', 'iep_source_unavailable', 'source_changed']


def test_analysis_page_has_task_list_cover_toc_and_grouped_downloads():
    html = demo2_course_page.render_course_analysis({"role": "school_uploader", "username": "t1"})
    for text in ('我的课堂分析', 'id="taskList"', '去上传课堂视频', 'id="legacyNote"', '未迁移、未分配给任何账号，也未删除',
                 '仅凭姓名不能关联历史资料', 'class="analysis-tabs rx-tabs"', 'class="rx-tab"', 'id="reportToc"',
                 'id="reportCover"', 'class="dl-group"', '页面已按最新数据重新生成', '下载前请刷新', '查看分析',
                 'reportBadge', '报告已过期', 'data-toc-title', 'figcaption'):
        assert text in html, text
    for element_id in ('tab-group', 'tab-person', 'tab-review', 'tab-report', 'downloadHtml', 'downloadMd',
                       'downloadJson', 'printReport', 'regenerateReport', 'reportState', 'reportBody', 'picker'):
        assert html.count(f'id="{element_id}"') == 1, element_id


def test_admin_guide_stays_static_with_task_query_button():
    page = _render_admin_analysis_guide({"role": "company_admin", "username": "admin"})
    assert '请从任务记录进入' in page and '前往任务查询' in page
    assert "href='/demo2/admin#taskQueryTitle'" in page
    assert 'fetch(' not in page.split('<main', 1)[1].split('</main>', 1)[0]
