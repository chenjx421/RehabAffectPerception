"""Synthetic-only API/privacy tests; optional real Chromium against a temp server.

Never loads credentials, connects to cloud, or edits any deployed/source module.
"""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import cloud_observation_acceptance as qa
finally:
    sys.path.remove(str(ROOT / 'scripts'))

TASK, SHA, STUDENT = 'synthetic-task', 'a' * 64, 'synthetic-student'
BOX = {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.4}


def fixture_data(*, selected=True, confirmed=True, evidence=True):
    row = {'observation_id': 'observation-1', 'person_id': 'person-1', 'frame_key': 'frame-1',
           'time_sec': 1, 'bbox': BOX.copy(), 'behavior': 'seated', 'observation': 'seated',
           'reviewed': False, 'source_type': 'machine_observation'}
    result = {'schema_version': 'visible_observation_v1', 'task_id': TASK,
        'source_sha256': SHA, 'frame_revision': 'revision-1', 'scoring_performed': False,
        'identity_recognition_performed': False, 'requires_teacher_review': True,
        'model': 'synthetic-mixed-model', 'coverage': {'scope': 'sampled_frames_only', 'sample_count': 1,
            'sample_timestamps_sec': [1], 'continuous_coverage': False, 'full_lesson': False},
        'frames': [{'timestamp_sec': 1, 'observations': [{'behavior': 'seated', 'bbox': BOX.copy()},
            {'behavior': 'head_toward_materials', 'bbox': BOX.copy()}, {'behavior': 'standing', 'bbox': None}]}],
        'teacher_suggestions': []}
    work = {'task_id': TASK, 'status': 'ready', 'source_sha256': SHA, 'frame_revision': 'revision-1',
            'scope_key': 'synthetic-scope', 'owner_account_id': 'synthetic-owner', 'job_id': 'job-1',
            'result': result, 'samples': [{'frame_key': 'frame-1', 'time_sec': 1}], 'observations': [row]}
    binding = {'binding_id': 'binding-1', 'student_id': STUDENT, 'task_id': TASK,
        'frame_key': 'frame-1', 'time_sec': 1, 'frame_revision': 'revision-1', 'source_sha256': SHA,
        'scope_key': 'synthetic-scope', 'owner_account_id': 'synthetic-owner', 'role': 'student',
        'status': 'confirmed', 'current_revision': True, 'stale': False}
    identity = {'task_id': TASK, 'frame_revision': 'revision-1', 'scope_key': 'synthetic-scope',
        'media_available': True, 'can_edit': True, 'frames': work['samples'],
        'students': [{'student_id': STUDENT, 'display_name': 'SYNTHETIC PRIVATE NAME',
                      'student_code': 'PRIVATE-CODE', 'class_name': 'PRIVATE-CLASS'}],
        'bindings': [binding] if confirmed else []}
    history = {'student_id': STUDENT, 'reviewed': False, 'teacher_review_status': 'not_reviewed',
        'observations': [{**row, 'student_id': STUDENT, 'job_id': 'job-1', 'task_id': TASK,
            'binding_id': 'binding-1', 'source_sha256': SHA, 'frame_revision': 'revision-1',
            'identity_basis': 'confirmed_frame_bbox'}] if confirmed and evidence else []}
    settings = {'task_id': TASK, 'max_students': 3, 'can_edit': True,
                'selected_student_ids': [STUDENT] if selected else []}
    course = {'task_id': TASK, 'source_sha256': SHA, 'frame_revision': 'revision-1',
        'course_name': 'SYNTHETIC PRIVATE COURSE', 'school_context': {'school_name': 'PRIVATE SCHOOL'},
        'report_scope': 'PRIVATE SCOPE', 'can_edit': True, 'media_available': True,
        'media': {'duration_sec': 10, 'width': 160, 'height': 90},
        'frames': work['samples'], 'summary': {'records': 0, 'reviewed': 0}, 'people': [], 'records': [],
        'report': {'title': 'PRIVATE REPORT', 'character_count': 0, 'generation': 'synthetic',
                   'sections': [], 'record_versions': []}, 'rubric_version': 'synthetic',
        'dimensions': {}, 'states': {}, 'support_levels': {}}
    return SimpleNamespace(work=work, identity=identity, history=history, settings=settings,
                           course=course, task={'task_id': TASK, 'sha256': SHA}, calls=[], leaks=set())


def png():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (160, 90), '#ff0000').save(output, format='PNG')
    return output.getvalue()


class SyntheticClient:
    def __init__(self, data, role='owner'):
        self.data, self.role, self.student_ids, self.cookie = data, role, set(), ''

    def login(self, credentials, role):
        self.cookie = 'rehab_demo2_session=synthetic-only'
        return {'role': role}

    def request(self, path, *, payload=None, **kwargs):
        self.data.calls.append((self.role, 'POST' if payload is not None else 'GET', path))
        name = urlsplit(path).path.removeprefix(qa.base.API)
        if name == '/auth/logout':
            return 200, {}, b'{}'
        if self.role in {'peer', 'anonymous'} and name not in self.data.leaks:
            return (401 if self.role == 'anonymous' else 403), {}, b'{}'
        if self.role == 'admin' and name == '/observations/student':
            return 403, {}, b'{}'
        if name == '/identity/frame':
            return 200, {'content-type': 'image/png'}, png()
        if name == '/observations/download':
            return 200, {'content-type': 'application/json', 'content-disposition': 'attachment'}, json.dumps(self.data.work).encode()
        values = {'/observations': {'workspace': self.data.work},
                  '/observations/targets': {'settings': {**self.data.settings, 'can_edit': self.role != 'admin'}},
                  '/identity/workspace': {'workspace': self.data.identity},
                  '/observations/student': {'workspace': self.data.history},
                  '/upload/task': {'task': self.data.task}, '/course-analysis': {'workspace': self.data.course}}
        return 200, {'content-type': 'application/json'}, json.dumps(values.get(name, {'ok': True})).encode()

    def json(self, path):
        status, _, raw = self.request(path)
        assert status == 200
        return json.loads(raw)


def clients(data, school_index=1):
    group = [SyntheticClient(data, 'owner' if i == school_index - 1 else 'peer') for i in range(4)]
    return group + [SyntheticClient(data, 'admin')], SyntheticClient(data, 'anonymous')


@pytest.mark.parametrize('selected,confirmed,evidence,coverage', [
    (False, False, False, 'no_saved_targets'), (True, False, False, 'no_confirmed_evidence'),
    (True, True, False, 'no_confirmed_evidence'), (True, True, True, 'existing_evidence'),
])
def test_api_checks_only_get_existing_data_and_report_real_coverage(selected, confirmed, evidence, coverage):
    data = fixture_data(selected=selected, confirmed=confirmed, evidence=evidence)
    before = deepcopy((data.work, data.settings, data.identity, data.history))
    group, anonymous = clients(data, school_index=3)
    report = {}
    qa.api_checks(group, anonymous, TASK, SHA, 3, report)
    assert report['individual_coverage'] == coverage
    assert report['existing_individual_evidence_available'] is (selected and confirmed and evidence)
    assert report['teacher_and_admin_download_verified'] and report['target_get_verified']
    assert report['peer_denials'] >= 18 and report['anonymous_denied']
    assert all(method == 'GET' for _, method, _ in data.calls)
    assert before == (data.work, data.settings, data.identity, data.history)
    serialized = json.dumps(report)
    assert all(value not in serialized for value in (TASK, STUDENT, 'PRIVATE', 'synthetic-only'))


@pytest.mark.parametrize('name', ['/observations', '/observations/targets', '/observations/download',
                                  '/identity/frame', '/observations/student', '/course-analysis'])
def test_api_cross_school_or_anonymous_leaks_fail_closed(name):
    data = fixture_data()
    data.leaks.add(name)
    group, anonymous = clients(data)
    with pytest.raises(qa.CheckError, match='peer_data_leak'):
        qa.api_checks(group, anonymous, TASK, SHA, 1, {})


@pytest.mark.parametrize('change', [
    {'source_sha256': 'b' * 64}, {'frame_revision': 'old'}, {'student_id': 'foreign'},
    {'frame_key': 'other-frame'}, {'binding_id': 'other-binding'}, {'person_id': 'other-person'},
    {'bbox': None}, {'reviewed': True}, {'identity_basis': 'model_inferred'},
])
def test_individual_evidence_requires_existing_same_frame_source_binding(change):
    data = fixture_data()
    frames = qa.validate_workspace(data.work, TASK, SHA)
    bindings = qa.confirmed_bindings(data.identity, data.work, frames)
    data.history['observations'][0].update(change)
    with pytest.raises(qa.CheckError, match='invalid_student_history'):
        qa.individual_frames(data.history, STUDENT, data.work, frames, bindings)


@pytest.mark.parametrize('box', [{'x': 0, 'y': 0, 'width': -1, 'height': 1},
    {'x': True, 'y': 0, 'width': 1, 'height': 1}, {'x': 0.5, 'y': 0, 'width': 1, 'height': 1},
    {'x': float('nan'), 'y': 0, 'width': 1, 'height': 1}])
def test_invalid_boxes_are_not_accepted_as_evidence(box):
    data = fixture_data()
    data.work['result']['frames'][0]['observations'][0]['bbox'] = box
    with pytest.raises(qa.CheckError, match='invalid_observation'):
        qa.validate_workspace(data.work, TASK, SHA)


def test_duplicate_same_frame_person_box_is_rendered_once_and_null_is_group_only():
    frame = fixture_data().work['result']['frames'][0]
    assert len(frame['observations']) == 3 and qa.boxes(frame) == [BOX]


@pytest.mark.parametrize('ids', [[STUDENT, STUDENT], ['a', 'b', 'c', 'd'], ['../private']])
def test_invalid_saved_targets_fail_without_attempting_a_save(ids):
    data = fixture_data()
    data.settings['selected_student_ids'] = ids
    with pytest.raises(qa.CheckError, match='invalid_targets'):
        qa.validate_targets(data.settings, TASK, editable=True)


def test_duplicate_binding_cannot_count_as_confirmed_identity():
    data = fixture_data()
    data.identity['bindings'] *= 2
    with pytest.raises(qa.CheckError, match='identity_source_mismatch'):
        qa.confirmed_bindings(data.identity, data.work, qa.validate_workspace(data.work, TASK, SHA))


@pytest.mark.parametrize('name', ['/observations/targets', '/observations/link', '/observations',
    '/upload/tasks', '/upload/chunks', '/upload/retry', '/identity/students', '/measurements'])
def test_http_writes_are_rejected_before_network(monkeypatch, name):
    monkeypatch.setattr(qa.base.Client, 'request', lambda *a, **k: pytest.fail('network forbidden'))
    with pytest.raises(qa.CheckError, match='read_only_violation'):
        qa.ReadOnlyClient(TASK).request(qa.base.route(name), payload={})


@pytest.mark.parametrize('path,method,allowed', [
    ('/observations/targets?task_id=' + TASK, 'GET', True),
    ('/observations/targets?task_id=' + TASK, 'POST', False),
    ('/observations/targets?task_id=other', 'GET', False),
    ('/observations/targets?task_id=' + TASK + '&task_id=other', 'GET', False),
    ('/observations/student?student_id=' + STUDENT, 'GET', True),
    ('/observations/student?student_id=unknown', 'GET', False),
    ('/identity/frame?task_id=' + TASK + '&frame_key=frame-1&frame_revision=revision-1', 'GET', True),
    ('/upload/media?id=' + TASK, 'GET', True),
    ('/upload/media?id=other', 'GET', False),
    ('/identity/link', 'GET', False), ('/../observations', 'GET', False),
])
def test_browser_policy_is_origin_bound_get_only(path, method, allowed):
    url = qa.ORIGIN + qa.base.API + path
    assert qa.allowed_browser_request(url, method, TASK, {STUDENT}) is allowed
    assert not qa.allowed_browser_request(url.replace(qa.ORIGIN, 'https://external.test'), method, TASK, {STUDENT})


def test_private_output_is_exclusive_and_cannot_escape(tmp_path, monkeypatch):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    monkeypatch.setattr(qa, 'PRIVATE', private)
    output = qa.private_output(private / 'new')
    assert output.is_dir()
    with pytest.raises(FileExistsError):
        qa.private_output(output)
    with pytest.raises(qa.CheckError, match='unsafe_output'):
        qa.private_output(tmp_path / 'outside')


def args(output, **changes):
    return SimpleNamespace(task_id=TASK, source_sha256=SHA, school_index=1, screenshots=False,
                           require_individual_evidence=False, output=output, **changes)


def install_synthetic_clients(monkeypatch, data):
    group, anonymous = clients(data)
    pool = iter(group + [anonymous])
    monkeypatch.setattr(qa, 'ReadOnlyClient', lambda task_id: next(pool))
    monkeypatch.setattr(qa.base, 'load_credentials', lambda *a: ([{}] * 4, {}))
    return group


def test_strict_positive_individual_gate_never_writes_identity(monkeypatch, tmp_path):
    data = fixture_data(selected=False, confirmed=False)
    install_synthetic_clients(monkeypatch, data)
    options = args(tmp_path)
    options.require_individual_evidence = True
    report = {}
    with pytest.raises(qa.CheckError, match='individual_evidence_unavailable'):
        qa.run(options, report)
    assert report['individual_coverage'] == 'no_saved_targets'
    writes = [path for _, method, path in data.calls if method == 'POST']
    assert writes == [qa.base.route('/auth/logout')] * 5


def test_run_detects_saved_target_changes_and_cleans_up_sessions(monkeypatch, tmp_path):
    data = fixture_data()
    group = install_synthetic_clients(monkeypatch, data)
    original = group[0].json
    calls = [0]
    def changing(path):
        if path.startswith(qa.base.route('/observations/targets')):
            calls[0] += 1
            if calls[0] == 2:
                data.settings['selected_student_ids'] = []
        return original(path)
    monkeypatch.setattr(group[0], 'json', changing)
    with pytest.raises(qa.CheckError, match='target_settings_changed'):
        qa.run(args(tmp_path), {})
    assert sum(method == 'POST' for _, method, _ in data.calls) == 5


def test_cli_errors_are_sanitized_and_windows_never_loads_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'win32')
    monkeypatch.setattr(qa.base, 'load_credentials', lambda *a: pytest.fail('No Windows credentials'))
    command = ['--task-id', TASK, '--source-sha256', SHA, '--output', str(tmp_path / 'unused')]
    assert qa.main(command) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'linux_cloud_only'
    monkeypatch.setattr(qa.sys, 'platform', 'linux')
    monkeypatch.setattr(qa, 'private_output', lambda path: tmp_path)
    def fail(*a):
        raise RuntimeError('SYNTHETIC PRIVATE NAME password=PRIVATE-TOKEN /original/private.mp4')
    monkeypatch.setattr(qa, 'run', fail)
    assert qa.main(command) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['error'] == 'observation_acceptance_failed' and report['accuracy_assessed'] is False
    assert not any(value in json.dumps(report) for value in ('PRIVATE', TASK, str(tmp_path)))
    assert json.loads((tmp_path / 'acceptance.json').read_text()) == report


def test_invalid_cli_never_echoes_private_argument_values(capsys):
    assert qa.main(['--task-id', 'PRIVATE', '--unexpected=PRIVATE-TOKEN']) == 1
    output = capsys.readouterr()
    assert 'PRIVATE' not in output.out + output.err
    assert json.loads(output.out)['error'] == 'invalid_arguments'


@pytest.fixture(scope='module')
def chromium(tmp_path_factory):
    sync = pytest.importorskip('playwright.sync_api')
    temporary = tmp_path_factory.mktemp('browser-tmp').resolve()
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv('TEMP', str(temporary))
        environment.setenv('TMP', str(temporary))
        with sync.sync_playwright() as playwright:
            executable = Path(os.environ.get('REHAB_ACCEPTANCE_TEST_BROWSER', playwright.chromium.executable_path))
            if not executable.is_file():
                available = sorted((Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright').glob('chromium-*/chrome-win*/chrome.exe'))
                if not available:
                    pytest.skip('No local Chromium installed; no browser downloads in these tests')
                executable = available[-1]
            browser = playwright.chromium.launch(headless=True, executable_path=str(executable), args=['--no-proxy-server'])
            try:
                yield browser
            finally:
                browser.close()


@contextmanager
def synthetic_site(data):
    spec = importlib.util.spec_from_file_location('_synthetic_observation_page',
        ROOT / '.runtime/cloud_release_overrides/demo2_course_page.py')
    page_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(page_module)
    image = png()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            data.calls.append(('browser', 'GET', self.path))
            parsed = urlsplit(self.path)
            content_type = 'application/json'
            status = 200
            if parsed.path == '/demo2/analysis':
                content_type, body = 'text/html; charset=utf-8', page_module.HTML.encode()
            elif parsed.path == qa.base.API + '/identity/frame':
                content_type, body = 'image/png', image
            elif parsed.path == qa.base.API + '/upload/media':
                status, content_type, body = 404, 'text/plain', b'synthetic video not needed'
            elif parsed.path == '/favicon.ico':
                status, body = 204, b''
            else:
                _, _, body = SyntheticClient(data).request(self.path)
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            data.calls.append(('browser', 'POST', self.path))
            self.send_error(405)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('selected,confirmed,evidence,expected', [
    (False, False, False, 'disabled_no_saved_targets'),
    (True, False, False, 'unconfirmed_empty_state'),
    (True, True, False, 'confirmed_empty_state'),
    (True, True, True, 'existing_evidence'),
])
def test_real_browser_against_synthetic_v10_page_only(chromium, tmp_path, monkeypatch,
                                                     selected, confirmed, evidence, expected):
    data = fixture_data(selected=selected, confirmed=confirmed, evidence=evidence)
    group, anonymous = clients(data)
    report = {}
    owner, work, settings, frames, bindings, candidates = qa.api_checks(group, anonymous, TASK, SHA, 1, report)
    with synthetic_site(data) as origin:
        monkeypatch.setattr(qa, 'ORIGIN', origin)
        qa.browser_checks(chromium, owner, TASK, SHA, tmp_path, work, settings, frames, bindings, candidates, report)
    assert report['individual_mode_check'] == expected
    assert report['screenshots'] == 6 and report['bbox_geometry_verified'] == 1
    assert report['browser_report_download_verified'] and report['browser_download_storage_disabled']
    assert report['image_decode_verified'] == 1
    assert {p.name for p in tmp_path.iterdir()} == {
        'classroom-observations-desktop.png', 'classroom-observations-desktop-top.png',
        'classroom-report-desktop-top.png', 'classroom-observations-mobile.png',
        'classroom-observations-mobile-top.png', 'classroom-evidence-frame-masked.png'}
    assert all(method == 'GET' for _, method, _ in data.calls)
    assert 'PRIVATE' not in json.dumps(report)


def test_real_browser_masks_image_and_private_text_pixels(chromium, tmp_path):
    from PIL import Image
    context = chromium.new_context(viewport={'width': 300, 'height': 200})
    try:
        page = context.new_page()
        page.set_content('<div id="aiTargetList" style="position:absolute;left:0;top:0;width:100px;height:50px;background:red">PRIVATE NAME</div>'
                         '<img style="position:absolute;left:100px;top:0;width:100px;height:50px;background:red">')
        qa.capture(page, tmp_path, 'masked.png')
        with Image.open(tmp_path / 'masked.png') as image:
            assert image.getpixel((50, 25))[:3] == (230, 237, 245)
            assert image.getpixel((150, 25))[:3] == (230, 237, 245)
    finally:
        context.close()


@pytest.mark.parametrize('broken,box_width,error', [
    (True, 30, 'image_not_loaded'), (False, 80, 'bbox_render_mismatch'),
])
def test_real_browser_rejects_corrupt_image_or_wrong_bbox_geometry(chromium, broken, box_width, error):
    context = chromium.new_context(viewport={'width': 400, 'height': 300})
    try:
        context.route('**/*', lambda route: route.fulfill(status=200, content_type='image/png',
                                                         body=b'not an image' if broken else png()))
        page = context.new_page()
        src = qa.base.route('/identity/frame', task_id=TASK, frame_key='frame-1', frame_revision='revision-1')
        page.set_content(f'''<base href="{qa.ORIGIN}"><style>
            .observation-image{{position:relative;width:200px;height:112.5px}}
            img{{width:200px;height:112.5px;display:block}}
            .observation-box{{position:absolute;left:10%;top:20%;width:{box_width}%;height:40%}}
            </style><div id="evidence"><section class="observation-item"><div class="observation-image">
            <img src="{src}" data-ai-evidence="frame-1"><span class="observation-box"></span>
            </div></section></div>''')
        frames = qa.validate_workspace(fixture_data().work, TASK, SHA)
        with pytest.raises(qa.CheckError, match=error):
            qa.browser_evidence(page, '#evidence', frames, TASK, 'revision-1')
    finally:
        context.close()


@pytest.mark.parametrize('change', ['source', 'scoring', 'reviewed', 'bbox', 'none'])
def test_real_browser_download_memory_probe_rejects_tampering(chromium, tmp_path, change):
    data = fixture_data()
    frames = qa.validate_workspace(data.work, TASK, SHA)
    exported = {'task_id': TASK, 'ai_observations': {'task_id': TASK, 'frame_revision': 'revision-1',
                'status': 'ready', 'reviewed': False, 'result': deepcopy(data.work['result'])},
                'private_name': 'SYNTHETIC PRIVATE NAME'}
    draft = exported['ai_observations']
    if change == 'source':
        draft['result']['source_sha256'] = 'b' * 64
    elif change == 'scoring':
        draft['result']['scoring_performed'] = True
    elif change == 'reviewed':
        draft['reviewed'] = True
    elif change == 'bbox':
        draft['result']['frames'][0]['observations'][0]['bbox']['x'] = 0.2
    context = chromium.new_context(accept_downloads=False)
    try:
        page = context.new_page()
        page.set_content('<button id="downloadJson">Download</button><script>const payload='
                         + json.dumps(exported) + ''';document.querySelector('button').onclick=()=>{
            const a=document.createElement('a');a.download='synthetic.json';
            a.href=URL.createObjectURL(new Blob([JSON.stringify(payload)],{type:'application/json'}));
            document.body.append(a);a.click();a.remove();};</script>''')
        if change == 'none':
            digest = qa.browser_export(page, TASK, SHA, data.work, frames)
            assert len(digest) == 64 and 'PRIVATE' not in digest
        else:
            with pytest.raises(qa.CheckError, match='browser_report_download_mismatch'):
                qa.browser_export(page, TASK, SHA, data.work, frames)
        assert page.evaluate("typeof window.__acceptanceBlob === 'undefined'")
        assert list(tmp_path.iterdir()) == []
    finally:
        context.close()
