"""Offline privacy, source binding and actual UI orchestration contracts."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
SPEC = importlib.util.spec_from_file_location('cloud_real_browser_acceptance',
    SCRIPTS / 'cloud_real_browser_acceptance.py')
runner = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(runner)
finally:
    sys.path.remove(str(SCRIPTS))


def task(**changes):
    return {'task_id':'authorized-123', 'course_id':'authorized-course',
        'course_name':runner.COURSE, 'filename':'Sample01.mp4',
        'analysis_status':'evidence_ready', 'sha256':'a' * 64, **changes}


def workspace():
    return {'task_id':task()['task_id'], 'course_id':task()['course_id'],
        'course_name':runner.COURSE, 'people':[], 'records':[],
        'media_available':True, 'frame_revision':'revision-1',
        'technical_evidence':{'status':'available', 'source_bound':True,
            'task_id':task()['task_id'], 'frame_revision':'revision-1'},
        'automatic_report':{'ready':True, 'kind':'technical_summary', 'source_bound':True,
            'task_id':task()['task_id'], 'frame_revision':'revision-1'}}


def manifest(tmp_path, **changes):
    value = {'schema_version':1, 'samples':[{'sample_id':f'Sample{i:02d}',
        'sha256':str(i) * 64, 'size_bytes':10,
        'relative_path':'/NEVER/OPEN/original-private.mp4'} for i in range(1, 5)], **changes}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)
    return path


def test_manifest_only_reads_manifest_not_media(tmp_path, monkeypatch):
    path = manifest(tmp_path)
    original = runner.os.open
    opened = []

    def guarded(path_arg, *args, **kwargs):
        assert Path(path_arg) == path
        opened.append(path_arg)
        return original(path_arg, *args, **kwargs)

    monkeypatch.setattr(runner.os, 'open', guarded)
    result = runner.load_sample_hashes(path)
    assert result == {f'Sample{i:02d}':str(i) * 64 for i in range(1, 5)}
    assert len(opened) == 1
    assert 'original-private' not in json.dumps(result)


@pytest.mark.parametrize('change', ['duplicate', 'hash', 'size', 'schema', 'missing'])
def test_invalid_manifest_rejected(tmp_path, change):
    path = manifest(tmp_path)
    value = json.loads(path.read_text())
    if change == 'duplicate':
        value['samples'][3]['sample_id'] = 'Sample01'
    elif change == 'hash':
        value['samples'][0]['sha256'] = 'A' * 64
    elif change == 'size':
        value['samples'][0]['size_bytes'] = True
    elif change == 'schema':
        value['schema_version'] = True
    else:
        value['samples'].pop()
    path.write_text(json.dumps(value))
    with pytest.raises(runner.RealBrowserError, match='manifest_invalid'):
        runner.load_sample_hashes(path)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX mode enforcement')
@pytest.mark.parametrize('mode', [0o400, 0o644, 0o666])
def test_manifest_requires_exact_private_mode(tmp_path, mode):
    path = manifest(tmp_path)
    path.chmod(mode)
    with pytest.raises(runner.RealBrowserError, match='unsafe_manifest'):
        runner.load_sample_hashes(path)


def test_manifest_symlink_rejected_before_open(tmp_path, monkeypatch):
    path = manifest(tmp_path)
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == path)
    monkeypatch.setattr(runner.os, 'open', lambda *a: pytest.fail('must not open symlink'))
    with pytest.raises(runner.RealBrowserError, match='unsafe_manifest'):
        runner.load_sample_hashes(path)


@pytest.mark.parametrize('changes', [
    {'course_name':'Real classroom'}, {'course_name':runner.COURSE + ' '},
    {'filename':'Sample02.mp4'}, {'filename':'sample01.mp4'},
    {'analysis_status':'processing'}, {'sha256':'b' * 64}, {'task_id':'../private'},
])
def test_task_selection_fails_closed(changes):
    with pytest.raises(runner.RealBrowserError):
        runner.select_task([task(**changes)], 1, 'a' * 64)


def test_exact_hash_candidate_selected_without_substitution():
    correct = task()
    assert runner.select_task([task(sha256='b' * 64), correct], 1, 'a' * 64) is correct


def test_resolves_list_without_digest_and_original_filename_details(monkeypatch):
    row = task()
    row.pop('sha256')
    detail = task()
    detail['original_filename'] = detail.pop('filename')
    calls = []

    def api(page, path):
        calls.append(path)
        return {'task':detail}

    monkeypatch.setattr(runner.shared, 'api', api)
    result = runner.resolve_task(None, [task(course_name='PRIVATE OTHER'), row], 1, 'a' * 64)
    assert result['sha256'] == 'a' * 64 and result['filename'] == 'Sample01.mp4'
    assert calls == ['/upload/task?id=authorized-123']
    detail['sha256'] = 'b' * 64
    with pytest.raises(runner.RealBrowserError, match='sample_hash_mismatch'):
        runner.resolve_task(None, [row], 1, 'a' * 64)


def test_teacher_ui_captures_three_views_without_playback(tmp_path, monkeypatch):
    calls, captures, viewports = [], [], []
    monkeypatch.setattr(runner, 'login', lambda *a:['PRIVATE-CREDENTIAL'])

    def api(page, path):
        calls.append(path)
        if path == '/course-analysis/tasks':
            row = task()
            row.pop('sha256')
            return {'tasks':[row]}
        if path.startswith('/upload/task?'):
            return {'task':task()}
        return {'workspace':workspace()}

    monkeypatch.setattr(runner.shared, 'api', api)
    monkeypatch.setattr(runner.shared, 'goto', lambda *a:calls.append(a[-1]))
    monkeypatch.setattr(runner, 'capture', lambda p,o,n,s:captures.append(n) or n)
    monkeypatch.setattr(runner, 'download_receipt', lambda *a:{'download_event':True})

    class Locator:
        first = property(lambda self:self)
        def wait_for(self, **kwargs): pass
        def inner_text(self): return 'Decoded 120 frames'
        def count(self): return 3
        def click(self):
            assert self.selector == '#tab-report', 'real video/segments must never be played'

    class Page:
        def evaluate(self, script): return workspace()
        def locator(self, selector):
            obj = Locator()
            obj.selector = selector
            return obj
        def set_viewport_size(self, value): viewports.append(value)

    report = runner.teacher(Page(), None, 'http://127.0.0.1:8793', {}, tmp_path, 1, 'a' * 64)
    assert report['ok'] and report['segment_count'] == 3
    assert captures == ['school-1-01-analysis-desktop.png',
        'school-1-02-analysis-mobile.png', 'school-1-03-report.png']
    assert viewports == [{'width':390, 'height':844}, {'width':1440, 'height':1000}]
    assert not any('dossier' in p or 'identity' in p for p in calls)
    serialized = json.dumps(report)
    assert all(v not in serialized for v in ('PRIVATE-CREDENTIAL', task()['task_id'], task()['filename']))


def test_rendered_workspace_change_refused_before_any_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'login', lambda *a:[])
    monkeypatch.setattr(runner, 'resolve_task', lambda *a:task())
    monkeypatch.setattr(runner.shared, 'api', lambda p,path:{'workspace':workspace()})
    monkeypatch.setattr(runner.shared, 'goto', lambda *a:None)
    monkeypatch.setattr(runner, 'capture', lambda *a:pytest.fail('unsafe page must not be captured'))
    unsafe = workspace()
    unsafe['people'] = [{'display_name':'PRIVATE PERSON'}]
    locator = SimpleNamespace(wait_for=lambda **k:None, inner_text=lambda:'technical stats', count=lambda:3)
    locator.first = locator
    page = SimpleNamespace(locator=lambda s:locator, evaluate=lambda script:unsafe)
    with pytest.raises(runner.RealBrowserError, match='unsafe_real_workspace'):
        runner.teacher(page, None, 'http://127.0.0.1:8793', {}, tmp_path, 1, 'a' * 64)


def test_four_isolated_contexts_logout_even_on_failure(monkeypatch, tmp_path):
    contexts, calls = [], []

    class Context:
        def __init__(self):
            self.request = SimpleNamespace(post=self.post)
        def post(self, path, **kwargs):
            calls.append((path, kwargs))
            return SimpleNamespace(status=200)
        def route(self, *args): pass
        def new_page(self): return SimpleNamespace(set_default_timeout=lambda n:None)
        def close(self): self.closed = True

    def new_context(**kwargs):
        assert kwargs['service_workers'] == 'block'
        contexts.append(Context())
        return contexts[-1]

    def teacher(*args):
        if args[-2] == 2:
            raise RuntimeError('PRIVATE password /original/path.mp4')
        return {'ok':True}

    monkeypatch.setattr(runner, 'teacher', teacher)
    report = {'accounts':{}}
    runner.run(SimpleNamespace(new_context=new_context), 'http://127.0.0.1:8793',
        [{} for _ in range(4)], {f'Sample{i:02d}':str(i) * 64 for i in range(1, 5)}, tmp_path, report)
    assert len(contexts) == 4 and all(c.closed for c in contexts)
    assert len(calls) == 4 and all(p.endswith('/auth/logout') and k['max_redirects'] == 0 for p,k in calls)
    assert report['ok'] is False and report['accounts']['school-2']['error'] == 'browser_failed'
    assert 'PRIVATE' not in json.dumps(report)


def test_cli_launch_only_no_proxy_server_and_private_sanitized_json(monkeypatch, tmp_path, capsys):
    options = {}
    monkeypatch.setattr(runner.sys, 'platform', 'linux')
    monkeypatch.setattr(runner.shared, 'browser_executable', lambda p:'/opt/rehabaffect-browser/chrome')
    monkeypatch.setattr(runner, 'load_sample_hashes', lambda p:{})
    monkeypatch.setattr(runner.base, 'load_credentials', lambda *a:([{}] * 4, {}))
    monkeypatch.setattr(runner.shared, 'private_output', lambda p:tmp_path)
    monkeypatch.setattr(runner.os, 'umask', lambda n:0o077)
    monkeypatch.setattr(runner, 'run', lambda *a:a[-1].update(ok=True))
    closed = []
    browser = SimpleNamespace(close=lambda:closed.append(True))

    def launch(**kwargs):
        options.update(kwargs)
        return browser

    class Playwright:
        def __enter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        def __exit__(self, *args): pass

    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(sync_playwright=Playwright))
    assert runner.main(['--sample-manifest','PRIVATE.json','--school-credentials-file','schools',
        '--admin-credentials-file','admin','--executable-path','/opt/rehabaffect-browser/chrome']) == 0
    assert options == {'headless':True, 'args':['--no-proxy-server'],
        'executable_path':'/opt/rehabaffect-browser/chrome'}
    assert closed == [True]
    report = json.loads((tmp_path / 'acceptance.json').read_text())
    assert report['ok'] and 'PRIVATE' not in capsys.readouterr().out
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize('key,value', [('people',[{'name':'PRIVATE'}]),
    ('records',[{'evidence':'PRIVATE'}]), ('people',None), ('records',None),
    ('frame_revision',''), ('media_available',False), ('task_id','other')])
def test_workspace_rejects_people_records_or_wrong_scope(key, value):
    work = workspace()
    work[key] = value
    with pytest.raises(runner.RealBrowserError):
        runner.validate_workspace(work, task())


@pytest.mark.parametrize('section', ['technical_evidence', 'automatic_report'])
@pytest.mark.parametrize('key,value', [('source_bound',False), ('task_id','other'),
    ('frame_revision','stale'), ('source_sha256','b' * 64)])
def test_source_binding_required(section, key, value):
    work = workspace()
    work[section][key] = value
    with pytest.raises(runner.RealBrowserError):
        runner.validate_workspace(work, task())


@pytest.mark.parametrize('path,method,accepted', [
    ('/auth/login','POST',True), ('/auth/logout','POST',True),
    ('/course-analysis?task_id=x','GET',True), ('/upload/task?id=x','GET',True),
    ('/students','GET',False), ('/dossier/documents','GET',False),
    ('/identity/workspace','GET',False), ('/measurements','GET',False),
    ('/upload/tasks','POST',False), ('/school/context','POST',False),
    ('/auth/login?redirect=x','POST',False), ('/course-analysis','DELETE',False),
    ('/upload/../dossier','GET',False), ('/upload/%2e%2e/dossier','GET',False),
])
def test_request_policy(path, method, accepted):
    origin = 'http://127.0.0.1:8793'
    assert runner.allowed_request(origin + runner.API + path, method, origin) is accepted
    assert not runner.allowed_request('https://external.example' + runner.API + path, method, origin)


def test_masks_include_all_media_and_existing_private_regions(tmp_path):
    seen = {}

    class Page:
        def evaluate(self, script, values):
            assert 'data-acceptance-private' in script

        def locator(self, selector):
            seen['selector'] = selector
            return selector

        def screenshot(self, **kwargs):
            seen.update(kwargs)
            Path(kwargs['path']).touch()

    runner.capture(Page(), tmp_path, 'school-1-01-analysis-desktop.png', ['SECRET'])
    assert runner.shared.MASK_SELECTORS in seen['selector']
    assert all(s in seen['selector'].split(',') for s in ('video', 'img', 'canvas'))
    assert seen['full_page'] and seen['mask']


def test_download_receipt_deletes_raw_file_even_on_private_content(tmp_path):
    path = tmp_path / 'temporary-download'
    path.write_bytes(b'<!doctype html><article class="technical-report">SECRET</article>')
    deleted = []
    download = SimpleNamespace(failure=lambda:None, path=lambda:str(path), delete=lambda:deleted.append(True))

    class Event:
        value = download
        def __enter__(self): return self
        def __exit__(self, *args): pass

    page = SimpleNamespace(expect_download=lambda **k:Event(),
        locator=lambda s:SimpleNamespace(click=lambda:None))
    with pytest.raises(runner.RealBrowserError, match='download_failed'):
        runner.download_receipt(page, ['SECRET'])
    assert deleted == [True]
    receipt = runner.download_receipt(page, ['different-secret'])
    assert receipt['raw_download_retained'] is False
    assert 'SECRET' not in json.dumps(receipt) and str(path) not in json.dumps(receipt)


def test_errors_never_serialize_private_call_logs():
    assert runner.safe_code(RuntimeError('password=SECRET /original/file.mp4')) == 'browser_failed'
    assert runner.safe_code(runner.RealBrowserError('sample_hash_mismatch')) == 'sample_hash_mismatch'


def test_cli_rejects_windows_without_network(monkeypatch, capsys):
    monkeypatch.setattr(runner.sys, 'platform', 'win32')
    assert runner.main(['--sample-manifest','private.json','--school-credentials-file','schools',
        '--admin-credentials-file','admin','--executable-path','browser']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['error'] == 'linux_required' and report['accounts'] == {}
    assert 'private.json' not in json.dumps(report)
