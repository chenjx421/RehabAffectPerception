"""Post-release V10 read-only checks for an explicitly selected existing task.

No target saves, identity links, uploads, processing requests or model calls.
Login/logout may create normal session/audit records. GET authorization is always
decided by the real API; missing context/identity is never filled in. Without
existing saved targets, individual mode must remain disabled. Existing confirmed
evidence is required only with --require-individual-evidence; otherwise missing
positive coverage is reported explicitly, never manufactured or called passed.

--screenshots adds browser checks, the original five masked screenshots and one
masked core-frame screenshot. There is intentionally no unmask option. Images
are decoded in memory; bbox checks assert geometry/source correspondence, NOT
identity, behavior or model accuracy. Report downloads are checked in memory,
with browser download storage disabled. No raw image/report is saved by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
from http.cookies import SimpleCookie
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

import cloud_e2e_acceptance as base


ORIGIN = 'http://127.0.0.1:8793'
PRIVATE = Path('/var/lib/rehabaffect/acceptance-private')
BROWSER = '/opt/rehabaffect-browser/official-cft-156/chrome-headless-shell-linux64/chrome-headless-shell'
MASK_SELECTORS = ','.join((
    'video', 'img', 'canvas', 'svg', 'input', 'textarea', 'select',
    '#school', '#title', '#scope', '#message', '#taskList', '#aiTargetList',
    '#groupTable', '#personTitle', '#personBars', '#personRecords', '#personAiObservations',
    '#recordTable', '#reportBody', '#coverage', '#teacherDetails', '#applicabilitySection',
    '.observation-link', '.observation-individual-heading',
    '.observation-source', '[data-acceptance-private]',
))
ERRORS = frozenset({
    'invalid_arguments', 'linux_cloud_only', 'unsafe_output', 'read_only_violation',
    'source_mismatch', 'observation_not_ready', 'invalid_observation', 'invalid_targets',
    'target_settings_changed', 'peer_data_leak', 'anonymous_data_leak', 'admin_result_mismatch',
    'admin_scope_leak', 'download_result_mismatch', 'identity_source_mismatch',
    'invalid_student_history', 'individual_evidence_unavailable', 'frame_download_failed',
    'rendered_samples_mismatch', 'rendered_observations_missing', 'image_not_loaded',
    'image_source_mismatch', 'bbox_render_mismatch', 'mode_switch_failed',
    'browser_report_download_mismatch', 'desktop_overflow', 'mobile_overflow',
    'browser_source_changed', 'observation_acceptance_failed', 'report_output_failed',
})


class CheckError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'observation_acceptance_failed'
        super().__init__(self.code)


def require(value, code):
    if not value:
        raise CheckError(code)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) is not None


def allowed_get(path, task_id, student_ids=()):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or '%' in parsed.path:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = parsed.path.removeprefix(base.API)
    if parsed.path != base.API + name:
        return False
    if name in {'/observations', '/observations/targets', '/observations/download',
                '/identity/workspace', '/course-analysis', '/applicability'}:
        return query == {'task_id': [task_id]}
    if name in {'/upload/task', '/upload/media'}:
        return query == {'id': [task_id]}
    if name == '/identity/frame':
        return (set(query) == {'task_id', 'frame_key', 'frame_revision'}
                and query['task_id'] == [task_id]
                and all(len(query[key]) == 1 and identifier(query[key][0])
                        for key in ('frame_key', 'frame_revision')))
    if name == '/observations/student':
        return (set(query) == {'student_id'} and len(query['student_id']) == 1
                and query['student_id'][0] in student_ids)
    return name == '/course-analysis/tasks' and not query


class ReadOnlyClient(base.Client):
    def __init__(self, task_id):
        super().__init__(ORIGIN)
        self.task_id = task_id
        self.student_ids = set()

    def request(self, path, *, payload=None, binary=None, **kwargs):
        session = path in {base.API + '/auth/login', base.API + '/auth/logout'}
        require(binary is None and (session and isinstance(payload, dict)
                or payload is None and allowed_get(path, self.task_id, self.student_ids)),
                'read_only_violation')
        return super().request(path, payload=payload, **kwargs)


def private_output(path):
    require(path.is_absolute() and path.parent == PRIVATE and '..' not in path.parts,
            'unsafe_output')
    for parent in (PRIVATE, *PRIVATE.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), 'unsafe_output')
    info = PRIVATE.stat()
    if os.name == 'posix':
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_output')
    path.mkdir(mode=0o700)
    return path


def valid_box(box):
    return (box is None or isinstance(box, dict) and set(box) == {'x', 'y', 'width', 'height'}
            and all(type(value) in (int, float) and math.isfinite(value) for value in box.values())
            and box['x'] >= 0 and box['y'] >= 0 and box['width'] > 0 and box['height'] > 0
            and box['x'] + box['width'] <= 1.000001 and box['y'] + box['height'] <= 1.000001)


def boxes(frame):
    result = []
    for row in frame['observations']:
        box = row.get('bbox')
        require(valid_box(box), 'invalid_observation')
        if box is not None and box not in result:
            result.append(box)
    return result


def validate_workspace(work, task_id, source_hash):
    require(isinstance(work, dict) and work.get('task_id') == task_id
            and work.get('status') == 'ready' and work.get('source_sha256') == source_hash,
            'observation_not_ready')
    result = work.get('result', {})
    require(result.get('schema_version') == 'visible_observation_v1'
            and result.get('task_id') == task_id and identifier(work.get('frame_revision'))
            and result.get('frame_revision') == work['frame_revision']
            and result.get('source_sha256') == source_hash
            and result.get('scoring_performed') is False
            and result.get('identity_recognition_performed') is False
            and result.get('requires_teacher_review') is True, 'invalid_observation')
    samples, frames = work.get('samples'), result.get('frames')
    require(isinstance(samples, list) and isinstance(frames, list) and 1 <= len(frames) <= 8
            and len(samples) == len(frames), 'invalid_observation')
    indexed = {}
    for sample in samples:
        require(identifier(sample.get('frame_key')) and type(sample.get('time_sec')) in (int, float)
                and math.isfinite(sample['time_sec']) and sample['time_sec'] >= 0
                and sample['time_sec'] not in indexed, 'invalid_observation')
        indexed[sample['time_sec']] = sample['frame_key']
    require(len(set(indexed.values())) == len(samples), 'invalid_observation')
    checked = []
    for frame in frames:
        timestamp = frame.get('timestamp_sec')
        require(type(timestamp) in (int, float) and timestamp in indexed
                and (not checked or timestamp > checked[-1]['timestamp_sec'])
                and isinstance(frame.get('observations'), list), 'invalid_observation')
        checked.append({**frame, 'frame_key': indexed[timestamp]})
        boxes(frame)
    coverage = result.get('coverage', {})
    require(coverage.get('sample_count') == len(checked)
            and coverage.get('sample_timestamps_sec') == [f['timestamp_sec'] for f in checked]
            and coverage.get('continuous_coverage') is False and coverage.get('full_lesson') is False,
            'invalid_observation')
    return checked


def validate_targets(settings, task_id, *, editable):
    require(isinstance(settings, dict) and settings.get('task_id') == task_id
            and type(settings.get('max_students')) is int and settings['max_students'] == 3
            and settings.get('can_edit') is editable
            and isinstance(settings.get('selected_student_ids'), list), 'invalid_targets')
    ids = settings['selected_student_ids']
    require(len(ids) <= 3 and all(identifier(value) for value in ids) and len(set(ids)) == len(ids),
            'invalid_targets')
    return ids


def confirmed_bindings(identity, work, frames):
    require(identity.get('task_id') == work['task_id']
            and identity.get('frame_revision') == work['frame_revision']
            and identity.get('media_available') is True and identity.get('scope_key') == work.get('scope_key')
            and isinstance(identity.get('students'), list) and isinstance(identity.get('bindings'), list),
            'identity_source_mismatch')
    students = [student['student_id'] for student in identity['students']]
    require(len(students) == len(set(students)) and all(identifier(s) for s in students),
            'identity_source_mismatch')
    binding_ids = [binding.get('binding_id') for binding in identity['bindings']]
    require(all(identifier(b) for b in binding_ids) and len(binding_ids) == len(set(binding_ids)),
            'identity_source_mismatch')
    times = {frame['frame_key']: frame['timestamp_sec'] for frame in frames}
    return [binding for binding in identity['bindings']
            if binding.get('status') == 'confirmed' and binding.get('role') == 'student'
            and binding.get('current_revision') is True and binding.get('stale') is not True
            and binding.get('task_id') == work['task_id']
            and binding.get('frame_revision') == work['frame_revision']
            and binding.get('source_sha256') == work['source_sha256']
            and binding.get('scope_key') == work['scope_key']
            and binding.get('owner_account_id') == work.get('owner_account_id')
            and binding.get('frame_key') in times
            and binding.get('time_sec') == times[binding['frame_key']]
            and binding.get('student_id') in students and identifier(binding.get('binding_id'))]


def individual_frames(history, student_id, work, frames, bindings):
    require(history.get('student_id') == student_id and history.get('reviewed') is False
            and history.get('teacher_review_status') == 'not_reviewed'
            and isinstance(history.get('observations'), list), 'invalid_student_history')
    projected = []
    normalized = work.get('observations', [])
    for row in history['observations']:
        require(row.get('student_id') == student_id and row.get('reviewed') is False
                and row.get('source_type') == 'machine_observation'
                and row.get('identity_basis') in {'confirmed_frame_bbox', 'explicit_person_link'},
                'invalid_student_history')
        if row.get('task_id') != work['task_id']:
            continue
        require(row.get('job_id') == work.get('job_id')
                and row.get('source_sha256') == work['source_sha256']
                and row.get('frame_revision') == work['frame_revision'] and row.get('bbox') is not None
                and valid_box(row['bbox']), 'invalid_student_history')
        matches = [o for o in normalized if all(o.get(key) == row.get(key) for key in
            ('observation_id', 'person_id', 'frame_key', 'time_sec', 'bbox'))]
        require(len(matches) == 1 and any(all(b.get(key) == row.get(key) for key in
                ('binding_id', 'student_id', 'frame_key', 'time_sec')) for b in bindings),
                'invalid_student_history')
        require(any(frame['frame_key'] == row['frame_key'] and any(
            model_row.get('bbox') == row['bbox'] and model_row.get('behavior') == row.get('behavior')
            for model_row in frame['observations']) for frame in frames), 'invalid_student_history')
        projected.append(row)
    require(len({row['observation_id'] for row in projected}) == len(projected), 'invalid_student_history')
    result = []
    for frame in frames:
        rows = [row for row in projected if row['frame_key'] == frame['frame_key']]
        if rows:
            result.append({**frame, 'observations': rows})
    return result


def denied(client, path, *, anonymous=False):
    require(client.request(path)[0] in ({401} if anonymous else {403, 404}),
            'anonymous_data_leak' if anonymous else 'peer_data_leak')


def api_checks(clients, anonymous, task_id, source_hash, school_index, report):
    owner, admin = clients[school_index - 1], clients[4]
    task = owner.json(base.route('/upload/task', id=task_id))['task']
    require(task.get('task_id') == task_id and task.get('sha256') == source_hash, 'source_mismatch')
    path = base.route('/observations', task_id=task_id)
    work = owner.json(path)['workspace']
    frames = validate_workspace(work, task_id, source_hash)
    targets_path = base.route('/observations/targets', task_id=task_id)
    settings = owner.json(targets_path)['settings']
    ids = validate_targets(settings, task_id, editable=True)
    admin_settings = admin.json(targets_path)['settings']
    require(validate_targets(admin_settings, task_id, editable=False) == ids, 'invalid_targets')
    require(admin.json(path)['workspace']['result'] == work['result'], 'admin_result_mismatch')
    download_path = base.route('/observations/download', task_id=task_id)
    for client in (owner, admin):
        status, headers, body = client.request(download_path)
        require(status == 200 and 'application/json' in headers.get('content-type', '')
                and 'attachment' in headers.get('content-disposition', '')
                and json.loads(body)['result'] == work['result'], 'download_result_mismatch')
    identity = owner.json(base.route('/identity/workspace', task_id=task_id))['workspace']
    bindings = confirmed_bindings(identity, work, frames)
    student_ids = {student['student_id'] for student in identity['students']}
    for client in [*clients, anonymous]:
        client.student_ids.update(student_ids)
    candidates, student_paths = {}, []
    for student_id in ids:
        require(student_id in student_ids, 'invalid_targets')
        student_path = base.route('/observations/student', student_id=student_id)
        history = owner.json(student_path)['workspace']
        candidates[student_id] = individual_frames(history, student_id, work, frames, bindings)
        student_paths.append(student_path)
        require(admin.request(student_path)[0] in {403, 404}, 'admin_scope_leak')
    protected = [path, targets_path, download_path, base.route('/course-analysis', task_id=task_id),
                 base.route('/identity/workspace', task_id=task_id), *student_paths]
    image_hashes = []
    for frame in frames:
        frame_path = base.route('/identity/frame', task_id=task_id, frame_key=frame['frame_key'],
                                frame_revision=work['frame_revision'])
        protected.append(frame_path)
        status, headers, data = owner.request(frame_path)
        require(status == 200 and headers.get('content-type', '').split(';')[0] in
                {'image/jpeg', 'image/png'} and (data.startswith(b'\xff\xd8\xff')
                or data.startswith(b'\x89PNG\r\n\x1a\n')), 'frame_download_failed')
        image_hashes.append(hashlib.sha256(data).hexdigest())
    for peer in (client for client in clients[:4] if client is not owner):
        for protected_path in protected:
            denied(peer, protected_path)
    for protected_path in protected:
        denied(anonymous, protected_path, anonymous=True)
    report.update(source_verified=True, target_get_verified=True, selected_target_count=len(ids),
                  peer_denials=3 * len(protected), anonymous_denied=True, admin_read=True,
                  teacher_and_admin_download_verified=True, frame_get_verified=len(frames),
                  frame_payload_hash=hashlib.sha256(''.join(image_hashes).encode()).hexdigest(),
                  sample_count=len(frames), observations=sum(len(f['observations']) for f in frames),
                  teacher_suggestions=len(work['result']['teacher_suggestions']),
                  existing_individual_evidence_available=any(candidates.values()),
                  individual_isolation_checks=len(student_paths),
                  individual_coverage=('existing_evidence' if any(candidates.values()) else
                                       'no_saved_targets' if not ids else 'no_confirmed_evidence'))
    return owner, work, settings, frames, bindings, candidates


def allowed_browser_request(url, method, task_id, student_ids):
    parsed = urlsplit(url)
    if method != 'GET' or parsed.scheme + '://' + parsed.netloc != ORIGIN or parsed.fragment:
        return False
    path = parsed.path + ('?' + parsed.query if parsed.query else '')
    return (path == '/demo2/analysis?' + urlencode({'task_id': task_id})
            or path == '/favicon.ico' or allowed_get(path, task_id, student_ids))


def capture(page, output, filename, *, full_page=False, locator=None):
    target = locator if locator is not None else page
    options = {'path': str(output / filename), 'mask': [page.locator(MASK_SELECTORS)],
               'mask_color': '#e6edf5', 'animations': 'disabled'}
    if locator is None:
        options['full_page'] = full_page
    target.screenshot(**options)
    (output / filename).chmod(0o600)


def browser_evidence(page, selector, frames, task_id, revision):
    items = page.locator(selector + ' .observation-item')
    require(items.count() == len(frames), 'rendered_samples_mismatch')
    count = 0
    for index, frame in enumerate(frames):
        item, expected_boxes = items.nth(index), boxes(frame)
        image = item.locator('img[data-ai-evidence]')
        require(image.count() == 1 and image.get_attribute('data-ai-evidence') == frame['frame_key'],
                'image_source_mismatch')
        url = urlsplit(image.get_attribute('src') or '')
        require(not url.scheme and not url.netloc and url.path == base.API + '/identity/frame'
                and parse_qs(url.query) == {'task_id': [task_id], 'frame_key': [frame['frame_key']],
                                           'frame_revision': [revision]}, 'image_source_mismatch')
        image.scroll_into_view_if_needed()
        page.wait_for_function('(img) => img.complete', arg=image.element_handle(), timeout=15000)
        require(image.evaluate('(img) => img.naturalWidth > 0 && img.naturalHeight > 0'), 'image_not_loaded')
        geometry = item.evaluate('''el => {
            const image=el.querySelector('img'), r=image.getBoundingClientRect();
            return {width:r.width,height:r.height,boxes:[...el.querySelectorAll('.observation-box')].map(b=>{
                const q=b.getBoundingClientRect();return {x:(q.x-r.x)/r.width,y:(q.y-r.y)/r.height,
                    width:q.width/r.width,height:q.height/r.height};})};
        }''')
        require(geometry['width'] > 0 and geometry['height'] > 0
                and len(geometry['boxes']) == len(expected_boxes), 'bbox_render_mismatch')
        for actual, expected in zip(geometry['boxes'], expected_boxes):
            require(all(abs(actual[key] - expected[key]) <= 2 / geometry[
                'width' if key in {'x', 'width'} else 'height'] for key in expected),
                'bbox_render_mismatch')
        count += len(expected_boxes)
    return count


def browser_export(page, task_id, source_hash, work, frames):
    # Observe the page's real JSON Blob and download event without accepting a
    # filesystem download. The payload may contain names; never return or save it.
    page.evaluate('''() => {
        window.__acceptanceBlob=null;
        window.__acceptanceCreateURL=URL.createObjectURL;
        URL.createObjectURL=function(blob){
            if(blob instanceof Blob && blob.type==='application/json')window.__acceptanceBlob=blob;
            return window.__acceptanceCreateURL.call(URL,blob);
        };
    }''')
    try:
        with page.expect_download(timeout=20000):
            page.locator('#downloadJson').click()
        raw = page.evaluate('''async limit => {
            const blob=window.__acceptanceBlob;
            if(!blob || blob.size>limit)return null;
            return await blob.text();
        }''', base.MAX_RESPONSE)
        require(isinstance(raw, str), 'browser_report_download_mismatch')
        exported = json.loads(raw)
        draft = exported.get('ai_observations', {})
        result = draft.get('result', {})
        require(exported.get('task_id') == task_id and draft.get('task_id') == task_id
                and draft.get('frame_revision') == work['frame_revision']
                and draft.get('reviewed') is False and draft.get('status') == 'ready'
                and result.get('task_id') == task_id and result.get('source_sha256') == source_hash
                and result.get('frame_revision') == work['frame_revision']
                and result.get('scoring_performed') is False
                and result.get('requires_teacher_review') is True
                and result.get('identity_recognition_performed') is False
                and len(result.get('frames', [])) == len(frames), 'browser_report_download_mismatch')
        for actual, expected in zip(result['frames'], frames):
            require(actual.get('timestamp_sec') == expected['timestamp_sec']
                    and [(r.get('behavior'), r.get('bbox')) for r in actual['observations']]
                    == [(r.get('behavior'), r.get('bbox')) for r in expected['observations']],
                    'browser_report_download_mismatch')
        return hashlib.sha256(raw.encode()).hexdigest()
    finally:
        page.evaluate('''() => {
            URL.createObjectURL=window.__acceptanceCreateURL;
            delete window.__acceptanceBlob;delete window.__acceptanceCreateURL;
        }''')


def browser_checks(browser, owner, task_id, source_hash, output, work, settings, frames,
                   bindings, candidates, report):
    cookie = SimpleCookie()
    cookie.load(owner.cookie)
    students = set(owner.student_ids)
    blocked = []
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN',
                                  service_workers='block', accept_downloads=False)
    try:
        def guard(route):
            request = route.request
            if allowed_browser_request(request.url, request.method, task_id, students):
                route.continue_()
            else:
                blocked.append(True)
                route.abort()
        context.route('**/*', guard)
        def no_websocket(socket):
            blocked.append(True)
            socket.close()
        context.route_web_socket('**/*', no_websocket)
        context.add_cookies([{'name': item.key, 'value': item.value, 'url': ORIGIN,
                             'httpOnly': True, 'sameSite': 'Lax'} for item in cookie.values()])
        page = context.new_page()
        page.goto(ORIGIN + '/demo2/analysis?' + urlencode({'task_id': task_id}), wait_until='networkidle')
        page.wait_for_function('''() => typeof observationWorkspace!=='undefined' &&
            !observationLoading && !observationIdentityLoading && !observationTargetsLoading''')
        rendered = page.evaluate('() => observationWorkspace')
        require(rendered.get('result') == work['result'] and rendered.get('job_id') == work.get('job_id'),
                'browser_source_changed')
        selected = page.locator('#aiTargetList input:checked').evaluate_all(
            '(inputs) => inputs.map(input => input.dataset.targetStudent).sort()')
        require(selected == sorted(settings['selected_student_ids'])
                and page.locator('#saveAiTargets').is_disabled(), 'invalid_targets')
        page.locator('#aiObservationContent .observation-summary').wait_for(timeout=20000)
        report['bbox_geometry_verified'] = browser_evidence(page, '#aiObservationContent', frames,
                                                           task_id, work['frame_revision'])
        require(page.locator('#aiObservationContent .observation-list li').count()
                >= report['observations'], 'rendered_observations_missing')
        require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'desktop_overflow')
        page.evaluate('window.scrollTo(0,0)')
        capture(page, output, 'classroom-observations-desktop.png', full_page=True)
        capture(page, output, 'classroom-observations-desktop-top.png')
        core = next((i for i, frame in enumerate(frames) if boxes(frame)), 0)
        capture(page, output, 'classroom-evidence-frame-masked.png',
                locator=page.locator('#aiObservationContent .observation-item').nth(core))
        individual = page.locator('[name=aiObservationMode][value=individual]')
        group = page.locator('[name=aiObservationMode][value=group]')
        if not settings['selected_student_ids']:
            require(individual.is_disabled() and group.is_checked(), 'mode_switch_failed')
            report['individual_mode_check'] = 'disabled_no_saved_targets'
        else:
            individual.check()
            require(page.locator('#aiIndividualContent').is_visible()
                    and page.locator('#aiObservationContent').is_hidden(), 'mode_switch_failed')
            eligible = {b['student_id'] for b in bindings} & set(settings['selected_student_ids'])
            if eligible:
                for student in sorted(eligible):
                    page.locator('#aiStudentSelect').select_option(student)
                    page.wait_for_function('''student => !observationStudentLoading &&
                        observationStudentId===student && !observationStudentError''', arg=student)
                    browser_evidence(page, '#aiIndividualContent', candidates[student], task_id, work['frame_revision'])
                    if not candidates[student]:
                        require(page.locator('#aiIndividualContent .observation-empty').is_visible(), 'mode_switch_failed')
                report['individual_mode_check'] = ('existing_evidence' if any(candidates[s] for s in eligible)
                                                   else 'confirmed_empty_state')
                report['individual_students_checked'] = len(eligible)
            else:
                require(page.locator('#aiIndividualContent .observation-empty').is_visible()
                        and page.locator('#aiIndividualContent .observation-item').count() == 0, 'mode_switch_failed')
                report['individual_mode_check'] = 'unconfirmed_empty_state'
            group.check()
            require(page.locator('#aiObservationContent').is_visible()
                    and page.locator('#aiIndividualContent').is_hidden(), 'mode_switch_failed')
        page.locator('#tab-report').click()
        report['browser_report_sha256'] = browser_export(page, task_id, source_hash, work, frames)
        report['browser_report_download_verified'] = True
        capture(page, output, 'classroom-report-desktop-top.png')
        page.locator('#tab-group').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        browser_evidence(page, '#aiObservationContent', frames, task_id, work['frame_revision'])
        require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'mobile_overflow')
        page.evaluate('window.scrollTo(0,0)')
        capture(page, output, 'classroom-observations-mobile.png', full_page=True)
        capture(page, output, 'classroom-observations-mobile-top.png')
        require(not blocked, 'read_only_violation')
        report.update(screenshots=6, browser_observations_rendered=True, image_decode_verified=len(frames),
                      screenshots_privacy_masked=True, browser_download_storage_disabled=True)
    finally:
        context.close()


def run(args, report):
    schools, admin = base.load_credentials(PRIVATE / 'schools.private.md', PRIVATE / 'admin.private.json')
    clients = []
    try:
        for credentials, role in [(item, 'school_uploader') for item in schools] + [(admin, 'company_admin')]:
            client = ReadOnlyClient(args.task_id)
            clients.append(client)
            client.login(credentials, role)
        anonymous = ReadOnlyClient(args.task_id)
        owner, work, settings, frames, bindings, candidates = api_checks(
            clients, anonymous, args.task_id, args.source_sha256, args.school_index, report)
        if args.require_individual_evidence:
            require(any(candidates.values()), 'individual_evidence_unavailable')
        if args.screenshots:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=args.executable_path,
                    args=['--no-sandbox', '--no-proxy-server'])
                try:
                    browser_checks(browser, owner, args.task_id, args.source_sha256, args.output,
                                   work, settings, frames, bindings, candidates, report)
                finally:
                    browser.close()
        current = owner.json(base.route('/observations/targets', task_id=args.task_id))['settings']
        require(current == settings, 'target_settings_changed')
        require(owner.json(base.route('/observations', task_id=args.task_id))['workspace']['result']
                == work['result'], 'browser_source_changed')
        report.update(ok=True, target_settings_unchanged=True)
    finally:
        for client in clients:
            if client.cookie:
                try:
                    client.request(base.route('/auth/logout'), payload={})
                except Exception:
                    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CheckError('invalid_arguments')


def main(argv=None):
    report = {'ok': False, 'read_only': True, 'student_data_written': False,
              'accuracy_assessed': False, 'identity_accuracy_assessed': False,
              'raw_download_retained': False, 'screenshots': 0, 'browser_observations_rendered': False}
    output = None
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--task-id', required=True)
        parser.add_argument('--source-sha256', required=True)
        parser.add_argument('--school-index', type=int, choices=range(1, 5), default=1)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--screenshots', action='store_true')
        parser.add_argument('--require-individual-evidence', action='store_true')
        parser.add_argument('--executable-path', default=BROWSER)
        args = parser.parse_args(argv)
        require(sys.platform.startswith('linux'), 'linux_cloud_only')
        require(identifier(args.task_id) and re.fullmatch('[0-9a-f]{64}', args.source_sha256), 'invalid_arguments')
        os.umask(0o077)
        output = private_output(args.output)
        run(args, report)
    except Exception as error:
        report['error'] = error.code if isinstance(error, CheckError) else (
            error.code if isinstance(error, base.AcceptanceError) else 'observation_acceptance_failed')
    if output is not None:
        try:
            with (output / 'acceptance.json').open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
        except OSError:
            report.update(ok=False, error='report_output_failed')
    print(json.dumps(report), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
