"""Pure safety/selection tests; no browser, service or retained credentials."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SPEC = importlib.util.spec_from_file_location('cloud_browser_acceptance', SCRIPTS / 'cloud_browser_acceptance.py')
runner = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(runner)
finally:
    sys.path.remove(str(SCRIPTS))


def task(**changes):
    return {'task_id':'synthetic-123', 'course_id':'cloud-e2e-0123456789abcdef',
            'course_name':'SYNTHETIC HTTP acceptance', 'filename':'synthetic.mp4',
            'analysis_status':'evidence_ready', **changes}


def workspace():
    return {'task_id':task()['task_id'], 'course_id':task()['course_id'],
        'course_name':task()['course_name'], 'frame_revision':'synthetic-revision',
        'people':[], 'records':[],
        'technical_evidence':{'status':'available','source_bound':True,
            'task_id':task()['task_id'],'frame_revision':'synthetic-revision'},
        'automatic_report':{'ready':True,'kind':'technical_summary','source_bound':True,
            'task_id':task()['task_id'],'frame_revision':'synthetic-revision'}}


def test_existing_e2e_and_explicit_cloud_e2e_titles():
    assert runner.synthetic_task(task())
    assert runner.synthetic_task(task(course_name='cloud e2e synthetic lesson'))
    assert runner.synthetic_task(task(course_name='CLOUD-E2E acceptance'))


@pytest.mark.parametrize('changes', [
    {'course_name':'Real classroom'}, {'course_name':'old cloud e2e video'},
    {'course_id':'real-course'}, {'filename':'real_student.mp4'},
    {'task_id':'../../student'}, {'analysis_status':'processing'}, {'course_name':None},
])
def test_no_real_or_unready_task_substitution(changes):
    assert not runner.synthetic_task(task(**changes))


def test_clean_synthetic_workspace_only():
    runner.validate_workspace(workspace(), task())
    for key in ('people','records'):
        work = workspace()
        work[key] = [{'name':'DO NOT CAPTURE'}]
        with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_synthetic_workspace'):
            runner.validate_workspace(work, task())


@pytest.mark.parametrize('key', ['technical_evidence','automatic_report'])
def test_stale_result_cannot_be_claimed_current(key):
    work = workspace()
    work[key]['frame_revision'] = 'other'
    with pytest.raises(runner.BrowserAcceptanceError, match='technical_result_missing'):
        runner.validate_workspace(work, task())


@pytest.mark.parametrize('url,method,accepted', [
    ('http://127.0.0.1:8793/demo2/login','GET',True),
    ('http://127.0.0.1:8793/api/v1/demo2/auth/login','POST',True),
    ('http://127.0.0.1:8793/api/v1/demo2/auth/logout','POST',True),
    ('http://127.0.0.1:8793/api/v1/demo2/course-analysis?task_id=test','GET',True),
    ('http://127.0.0.1:8793/api/v1/demo2/upload/tasks','POST',False),
    ('http://127.0.0.1:8793/api/v1/demo2/measurements','POST',False),
    ('http://127.0.0.1:8793/api/v1/demo2/school/context','POST',False),
    ('https://external.example/api/v1/demo2/auth/login','POST',False),
    ('http://127.0.0.1:9999/api/v1/demo2/auth/login','POST',False),
    ('http://private:secret@127.0.0.1:8793/demo2/login','GET',False),
])
def test_real_network_guard_does_not_mock_or_allow_mutations(url, method, accepted):
    assert runner.allowed_request(url, method, 'http://127.0.0.1:8793') is accepted


def test_exception_messages_never_become_report_details():
    assert runner.safe_code(RuntimeError('password=PRIVATE cookie=PRIVATE')) == 'browser_failed'
    assert runner.safe_code(runner.BrowserAcceptanceError('synthetic_task_missing')) == 'synthetic_task_missing'
    assert runner.safe_code(runner.AcceptanceError('unsafe_credentials')) == 'unsafe_credentials'


def test_private_output_outside_application_tree(tmp_path):
    parent = tmp_path / 'private'
    output = runner.private_output(parent)
    assert output.parent == parent
    if os.name == 'posix':
        assert output.stat().st_mode & 0o777 == 0o700
    with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_output'):
        runner.private_output(runner.ROOT / 'output' / 'not-private')


@pytest.mark.skipif(os.name != 'posix', reason='Linux private-directory permission check')
def test_shared_artifact_root_rejected(tmp_path):
    parent = tmp_path / 'shared'
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_output'):
        runner.private_output(parent)


def test_screenshot_masks_cover_passwords_invites_and_admin_data():
    for selector in ('input:visible', '#accountList', '#channelList', '#membershipAccounts',
                     '#registrationRequests', '#recentUploads', 'a[href*="invite" i]'):
        assert selector in runner.MASK_SELECTORS


@pytest.fixture
def installed_browser(tmp_path, monkeypatch):
    root = tmp_path / 'browsers'
    root.mkdir()
    executable = root / 'chromium' / 'chrome'
    executable.parent.mkdir()
    executable.write_bytes(b'synthetic executable fixture, never run')
    executable.chmod(0o700)
    monkeypatch.setattr(runner, 'BROWSER_ROOT', root)
    return root, executable


def test_browser_default_and_existing_executable(installed_browser):
    _, executable = installed_browser
    assert runner.browser_executable(None) is None
    assert runner.browser_executable(executable) == str(executable.resolve())


@pytest.mark.parametrize('kind', ['relative', 'outside', 'prefix', 'traversal', 'missing', 'directory'])
def test_browser_path_restrictions(installed_browser, kind):
    root, executable = installed_browser
    paths = {'relative':Path('chromium/chrome'), 'outside':root.parent / 'chrome',
             'prefix':root.with_name(root.name + '-other') / 'chrome',
             'traversal':root / 'chromium' / '..' / 'chromium' / 'chrome',
             'missing':root / 'absent', 'directory':executable.parent}
    with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_executable'):
        runner.browser_executable(paths[kind])


@pytest.mark.parametrize('component', ['file', 'directory', 'root'])
def test_browser_rejects_symlink_at_each_level(installed_browser, monkeypatch, component):
    root, executable = installed_browser
    blocked = {'file':executable, 'directory':executable.parent, 'root':root}[component]
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == blocked or original(path))
    with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_executable'):
        runner.browser_executable(executable)


def test_browser_must_be_executable(installed_browser, monkeypatch):
    _, executable = installed_browser
    monkeypatch.setattr(runner.os, 'access', lambda path, mode: False)
    with pytest.raises(runner.BrowserAcceptanceError, match='unsafe_executable'):
        runner.browser_executable(executable)
