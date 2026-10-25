"""Read-only Linux UI acceptance for four already-uploaded authorized samples.

Uses the real-sample manifest schema, but NEVER opens relative_path media or
calls load_samples (which hashes/probes original videos). Only login/logout
may mutate the server. No dossiers, student/identity APIs, traces or raw reports
are retained. Run on the cloud host; this script does not perform SSH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlencode, urlsplit

import cloud_browser_acceptance as shared
import cloud_e2e_acceptance as base


API = shared.API
COURSE = 'Authorized real sample acceptance'
MASK_SELECTORS = shared.MASK_SELECTORS + ',video,img,canvas,svg image'
CODES = shared.CODES | frozenset({'unsafe_manifest', 'manifest_invalid',
    'real_task_missing', 'sample_hash_mismatch', 'unsafe_real_workspace',
    'logout_failed', 'segments_missing'})


class RealBrowserError(Exception):
    def __init__(self, code):
        self.code = code if code in CODES else 'browser_failed'
        super().__init__(self.code)


def require(condition, code):
    if not condition:
        raise RealBrowserError(code)


def safe_code(exc):
    code = getattr(exc, 'code', '')
    return code if code in CODES else 'browser_failed'


def load_sample_hashes(path):
    """Read only one no-follow, owner-only 0600 manifest descriptor."""
    try:
        path = Path(path)
        require(all(not p.is_symlink() for p in (path, *path.parents)), 'unsafe_manifest')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 128 * 1024, 'unsafe_manifest')
            if os.name == 'posix':
                require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
                        'unsafe_manifest')
            value = json.loads(stream.read(128 * 1024 + 1).decode('utf-8-sig'))
        require(isinstance(value, dict) and type(value.get('schema_version')) is int
                and value['schema_version'] == 1, 'manifest_invalid')
        rows = value.get('samples')
        require(isinstance(rows, list) and len(rows) == 4
                and all(isinstance(row, dict) for row in rows), 'manifest_invalid')
        result = {}
        for row in rows:
            sample_id, digest = row.get('sample_id'), row.get('sha256')
            require(isinstance(sample_id, str) and sample_id in
                    {f'Sample{i:02d}' for i in range(1, 5)} and sample_id not in result
                    and isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest)
                    and type(row.get('size_bytes')) is int
                    and 0 < row['size_bytes'] <= 5 * 1024**3, 'manifest_invalid')
            # relative_path is deliberately neither resolved, stat'ed nor returned.
            require(row.get('relative_path') is None or isinstance(row['relative_path'], str),
                    'manifest_invalid')
            result[sample_id] = digest
        return result
    except (OSError, UnicodeError):
        raise RealBrowserError('unsafe_manifest') from None
    except (ValueError, TypeError):
        raise RealBrowserError('manifest_invalid') from None


def select_task(tasks, number, digest):
    require(isinstance(tasks, list) and number in range(1, 5), 'api_failed')
    candidates = [t for t in tasks if isinstance(t, dict)
        and t.get('course_name') == COURSE and t.get('filename') == f'Sample{number:02d}.mp4'
        and t.get('analysis_status') == 'evidence_ready']
    require(candidates, 'real_task_missing')
    candidates = [t for t in candidates if t.get('sha256') == digest]
    require(candidates, 'sample_hash_mismatch')
    task = candidates[0]
    require(isinstance(task.get('task_id'), str)
            and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task['task_id'])
            and isinstance(task.get('course_id'), str) and 0 < len(task['course_id']) <= 120,
            'unsafe_real_workspace')
    return task


def resolve_task(page, tasks, number, digest):
    """The list API omits SHA-256; obtain it from only exact-match task details."""
    require(isinstance(tasks, list), 'api_failed')
    details = []
    for row in tasks:
        if not (isinstance(row, dict) and row.get('course_name') == COURSE
                and row.get('filename') == f'Sample{number:02d}.mp4'
                and row.get('analysis_status') == 'evidence_ready'):
            continue
        task_id = row.get('task_id')
        require(isinstance(task_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task_id),
                'unsafe_real_workspace')
        detail = shared.api(page, '/upload/task?' + urlencode({'id':task_id})).get('task')
        require(isinstance(detail, dict) and all(detail.get(k) == row.get(k)
                for k in ('task_id', 'course_id', 'course_name', 'analysis_status')),
                'unsafe_real_workspace')
        name = detail.get('filename', detail.get('original_filename'))
        require(name == row['filename'], 'unsafe_real_workspace')
        require('sha256' not in row or row['sha256'] == detail.get('sha256'), 'sample_hash_mismatch')
        details.append({**detail, 'filename':name})
    return select_task(details, number, digest)


def validate_workspace(work, task):
    require(isinstance(work, dict)
            and all(work.get(k) == task[k] for k in ('task_id', 'course_id', 'course_name'))
            and work.get('people') == [] and work.get('records') == []
            and work.get('media_available') is True and bool(work.get('frame_revision')),
            'unsafe_real_workspace')
    technical, report = work.get('technical_evidence'), work.get('automatic_report')
    require(isinstance(technical, dict) and isinstance(report, dict)
            and technical.get('status') == 'available' and report.get('ready') is True
            and report.get('kind') == 'technical_summary', 'technical_result_missing')
    for evidence in (technical, report):
        require(evidence.get('source_bound') is True
                and evidence.get('task_id') == task['task_id']
                and evidence.get('frame_revision') == work['frame_revision'], 'technical_result_missing')
        # Some cloud revisions expose the digest here; reject conflicts if supplied.
        for key in ('source_sha256', 'sha256'):
            require(key not in evidence or evidence[key] == task['sha256'], 'sample_hash_mismatch')


def allowed_request(url, method, origin):
    """Narrow the existing same-origin guard; never read student/dossier APIs."""
    try:
        if not shared.allowed_request(url, method, origin):
            return False
        parsed = urlsplit(url)
        path = parsed.path
        if '%' in path or '\\' in path or any(p in {'.', '..'} for p in path.split('/')):
            return False
        if method == 'POST':
            return path in {API + '/auth/login', API + '/auth/logout'} and not parsed.query
        if path.startswith(API + '/'):
            return path in {API + p for p in ('/auth/me', '/course-analysis/tasks',
                '/course-analysis', '/upload/task', '/upload/media', '/school/context',
                '/upload/workspace', '/upload/courses', '/upload/quota')}
        return (path in {'/demo2/login', '/demo2/school', '/demo2/upload', '/demo2/analysis', '/favicon.ico'}
                or path.startswith('/static/'))
    except (ValueError, TypeError):
        return False


def capture(page, output, name, secrets):
    try:
        page.evaluate('''values => {
          const sensitive=/(?:password|passwd|cookie|invite|invitation|secret|token|密码|邀请码)/i;
          for (const e of document.querySelectorAll('body *')) {
            const text=[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('');
            const attr=[e.id,e.getAttribute('name'),e.getAttribute('href'),e.getAttribute('src')].join(' ');
            if (values.some(v=>v && text.includes(v)) || sensitive.test(attr)
                || (text.length<300 && sensitive.test(text))) e.setAttribute('data-acceptance-private','');
          }
        }''', secrets)
        page.screenshot(path=str(output / name), full_page=True, animations='disabled',
            mask=[page.locator(MASK_SELECTORS)], mask_color='#d4deeb', timeout=30000)
        (output / name).chmod(0o600)
        return name
    except Exception:
        raise RealBrowserError('screenshot_failed') from None


def login(page, context, origin, credentials):
    shared.goto(page, origin, '/demo2/login')
    page.locator('#username').fill(credentials['username'])
    page.locator('#password').fill(credentials['password'])
    page.locator('#loginButton').click()
    page.wait_for_url(lambda url: urlsplit(url).path != '/demo2/login', timeout=30000)
    account = shared.api(page, '/auth/me').get('account', {})
    require(account.get('role') == 'school_uploader' and credentials['username'] in
            {account.get('username'), account.get('login_alias')}, 'login_failed')
    return [credentials['username'], credentials['password'], account.get('username', ''),
            *[c['value'] for c in context.cookies()]]


def download_receipt(page, forbidden):
    with page.expect_download(timeout=45000) as event:
        page.locator('#downloadHtml').click()
    download = event.value
    try:
        require(download.failure() is None, 'download_failed')
        temporary = download.path()
        require(temporary is not None and 0 < Path(temporary).stat().st_size < 16 * 1024**2,
                'download_failed')
        body = Path(temporary).read_bytes()
        require(b'<!doctype html>' in body.lower()
                and b'technical-report' in body
                and all(v.encode() not in body for v in forbidden if v), 'download_failed')
        return {'bytes':len(body), 'sha256':hashlib.sha256(body).hexdigest(),
                'download_event':True, 'raw_download_retained':False}
    finally:
        download.delete()


def teacher(page, context, origin, credentials, output, number, digest):
    secrets = login(page, context, origin, credentials)
    task = resolve_task(page, shared.api(page, '/course-analysis/tasks').get('tasks'), number, digest)
    query = urlencode({'task_id':task['task_id']})
    validate_workspace(shared.api(page, '/course-analysis?' + query).get('workspace'), task)
    shared.goto(page, origin, '/demo2/analysis?' + query)
    page.locator('#technicalStats').wait_for(state='visible')
    require(bool(page.locator('#technicalStats').inner_text().strip()), 'technical_result_missing')
    page.locator('[data-segment]').first.wait_for(state='visible')
    segments = page.locator('[data-segment]').count()
    require(segments > 0, 'segments_missing')
    # Inspect the actual rendered page's lexical workspace, not only an earlier
    # preflight fetch: a refresh must not introduce people or stale evidence.
    validate_workspace(page.evaluate('() => typeof work === "undefined" ? null : work'), task)
    # Do not click play/segments: playback of real faces is outside this run.
    private = secrets + [task['filename']]
    prefix = f'school-{number}'
    images = [capture(page, output, prefix + '-01-analysis-desktop.png', private)]
    page.set_viewport_size({'width':390, 'height':844})
    validate_workspace(page.evaluate('() => typeof work === "undefined" ? null : work'), task)
    images.append(capture(page, output, prefix + '-02-analysis-mobile.png', private))
    page.set_viewport_size({'width':1440, 'height':1000})
    page.locator('#tab-report').click()
    page.locator('#reportBody .technical-report').wait_for(state='visible')
    receipt = download_receipt(page, secrets)
    # Export refreshes the workspace. Revalidate before the report screenshot.
    validate_workspace(page.evaluate('() => typeof work === "undefined" ? null : work'), task)
    images.append(capture(page, output, prefix + '-03-report.png', private))
    return {'ok':True, 'sample_id':f'Sample{number:02d}', 'source_sha256':digest,
        'task_fingerprint':hashlib.sha256(task['task_id'].encode()).hexdigest(),
        'source_bound':True, 'people_count':0, 'record_count':0,
        'technical_stats_visible':True, 'segment_count':segments, 'automatic_report_visible':True,
        'screenshots':images, 'download':receipt}


def run(browser, origin, schools, samples, output, report):
    for number, credentials in enumerate(schools, 1):
        key = f'school-{number}'
        context = browser.new_context(viewport={'width':1440, 'height':1000},
            accept_downloads=True, service_workers='block')
        try:
            context.route('**/*', lambda route: route.continue_() if allowed_request(
                route.request.url, route.request.method, origin) else route.abort())
            if hasattr(context, 'route_web_socket'):
                context.route_web_socket('**/*', lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(30000)
            report['accounts'][key] = teacher(page, context, origin, credentials, output,
                number, samples[f'Sample{number:02d}'])
        except Exception as exc:
            report['accounts'][key] = {'ok':False, 'error':safe_code(exc)}
        finally:
            try:
                # APIRequestContext bypasses routing, so use a fixed validated origin,
                # the sole logout path and no redirects.
                response = context.request.post(origin + API + '/auth/logout', data={},
                    timeout=10000, max_redirects=0)
                require(response.status == 200, 'logout_failed')
            except Exception:
                report['accounts'][key] = {'ok':False, 'error':'logout_failed'}
            context.close()
    report['ok'] = len(report['accounts']) == 4 and all(r['ok'] for r in report['accounts'].values())


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RealBrowserError('invalid_arguments')


def main(argv=None):
    report = {'ok':False, 'accounts':{}, 'actual_http':True, 'mocked_responses':False,
        'new_tasks_or_students_created':False, 'dossier_read':False, 'privacy_masks_applied':True,
        'not_verified':['public_https', 'new_upload', 'video_playback', 'student_assessment',
                        'face_identity', 'legal_authorization']}
    output = None
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--base-url', default='http://127.0.0.1:8793')
        parser.add_argument('--school-credentials-file', type=Path, required=True)
        parser.add_argument('--admin-credentials-file', type=Path, required=True,
            help='Local credential-set validation only; the administrator is never logged in.')
        parser.add_argument('--sample-manifest', type=Path, required=True)
        parser.add_argument('--executable-path', type=Path)
        parser.add_argument('--output-root', type=Path,
            default=Path.home() / '.local/state/rehab-affect/cloud-real-browser-screenshots')
        args = parser.parse_args(argv)
        require(sys.platform.startswith('linux'), 'linux_required')
        _, _, origin = base.endpoint(args.base_url)
        executable = shared.browser_executable(args.executable_path)
        os.umask(0o077)
        for key in ('DEBUG', 'PWDEBUG'):
            os.environ.pop(key, None)
        samples = load_sample_hashes(args.sample_manifest)
        schools, _ = base.load_credentials(args.school_credentials_file, args.admin_credentials_file)
        output = shared.private_output(args.output_root)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RealBrowserError('browser_unavailable') from None
        with sync_playwright() as playwright:
            options = {'executable_path':executable} if executable is not None else {}
            browser = playwright.chromium.launch(headless=True, args=['--no-proxy-server'], **options)
            try:
                run(browser, origin, schools, samples, output, report)
            finally:
                browser.close()
    except KeyboardInterrupt:
        report.update(ok=False, error='interrupted')
    except Exception as exc:
        report.update(ok=False, error=safe_code(exc))
    if output is not None:
        try:
            path = output / 'acceptance.json'
            with path.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=True, indent=2)
            path.chmod(0o600)
        except OSError:
            report.update(ok=False, error='unsafe_output')
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
