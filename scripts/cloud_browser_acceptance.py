"""Private Linux browser screenshots of actual loopback pages, without mutations.

Reads credentials using cloud_e2e_acceptance.load_credentials. Creates only login
sessions/audit events and private screenshot artifacts; never uploads or binds a
student. No browser profile, storage state, trace, HAR, or console is persisted.
See cloud_browser_acceptance.md before running on the cloud host.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlencode, urlsplit

from cloud_e2e_acceptance import AcceptanceError, endpoint, load_credentials


API = '/api/v1/demo2'
ROOT = Path(__file__).resolve().parents[1]
BROWSER_ROOT = Path('/opt/rehabaffect-browser')
CODES = frozenset({'invalid_arguments', 'unsafe_endpoint', 'unsafe_credentials',
    'invalid_credentials', 'unsafe_output', 'linux_required', 'browser_unavailable',
    'page_failed', 'login_failed', 'api_failed', 'synthetic_task_missing',
    'unsafe_synthetic_workspace', 'technical_result_missing', 'download_failed',
    'screenshot_failed', 'browser_failed', 'unsafe_executable', 'interrupted'})
MASK_SELECTORS = ','.join([
    'input:visible', 'textarea:visible', 'select:visible',
    '#accountName', '#accountGreeting', '#schoolLocation', '#school',
    '#accountList', '#channelList', '#schoolContexts', '#membershipAccounts',
    '#membershipOrdersSummary', '#registrationRequests', '#recentSecurityAcceptances',
    '#courseUsage', '#recentUploads', '#personSelect', '#studentSelect',
    '[data-acceptance-private]',
    'a[href*="invite" i]', 'a[href*="token=" i]', 'a[href*="secret=" i]',
])


class BrowserAcceptanceError(Exception):
    def __init__(self, code):
        self.code = code if code in CODES else 'browser_failed'
        super().__init__(self.code)


def require(value, code):
    if not value:
        raise BrowserAcceptanceError(code)


def safe_code(exc):
    """Never serialize Playwright exceptions: their call logs can contain values."""
    code = getattr(exc, 'code', '')
    return code if code in CODES else 'browser_failed'


def browser_executable(value):
    """Validate an operator-installed browser; never resolve through symlinks."""
    if value is None:
        return None
    try:
        path = Path(value)
        require(path.is_absolute() and '..' not in path.parts
                and path.is_relative_to(BROWSER_ROOT) and path != BROWSER_ROOT,
                'unsafe_executable')
        require(all(not item.is_symlink() for item in (path, *path.parents)), 'unsafe_executable')
        resolved = path.resolve(strict=True)
        require(resolved.is_relative_to(BROWSER_ROOT) and resolved.is_file()
                and os.access(resolved, os.X_OK), 'unsafe_executable')
        return str(resolved)
    except (OSError, ValueError, RuntimeError):
        raise BrowserAcceptanceError('unsafe_executable') from None


def synthetic_task(task):
    if not isinstance(task, dict) or task.get('analysis_status') != 'evidence_ready':
        return False
    title, course = task.get('course_name'), task.get('course_id')
    if not isinstance(title, str) or not isinstance(course, str):
        return False
    named = re.match(r'^cloud[ -]e2e(?:[ -]|$)', title, re.I) is not None
    legacy = (title == 'SYNTHETIC HTTP acceptance'
              and re.fullmatch(r'cloud-e2e-[a-f0-9]{16}', course) is not None
              and task.get('filename', task.get('original_filename')) == 'synthetic.mp4')
    return bool((named or legacy) and isinstance(task.get('task_id'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', task['task_id'])
                and 0 < len(course) <= 120)


def validate_workspace(work, task):
    require(isinstance(work, dict) and work.get('task_id') == task['task_id']
            and work.get('course_id') == task['course_id']
            and work.get('course_name') == task['course_name']
            and work.get('people') == [] and work.get('records') == [],
            'unsafe_synthetic_workspace')
    technical, report = work.get('technical_evidence', {}), work.get('automatic_report', {})
    require(isinstance(technical, dict) and technical.get('status') == 'available'
            and technical.get('source_bound') is True
            and technical.get('task_id') == task['task_id']
            and technical.get('frame_revision') == work.get('frame_revision')
            and isinstance(report, dict) and report.get('ready') is True
            and report.get('kind') == 'technical_summary'
            and report.get('source_bound') is True
            and report.get('task_id') == task['task_id']
            and report.get('frame_revision') == work.get('frame_revision'),
            'technical_result_missing')


def private_output(parent):
    """Fail closed on symlinks/shared modes; keep artifacts outside web/repo roots."""
    parent = Path(os.path.abspath(parent.expanduser()))
    require(not parent.is_relative_to(ROOT), 'unsafe_output')
    require(all(not p.is_symlink() for p in (parent, *parent.parents)), 'unsafe_output')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = parent.stat()
    if os.name == 'posix':
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_output')
    require(stat.S_ISDIR(info.st_mode), 'unsafe_output')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = parent / stamp
    output.mkdir(mode=0o700)
    return output


def allowed_request(url, method, origin):
    parsed = urlsplit(url)
    if (parsed.scheme + '://' + parsed.netloc != origin or parsed.username
            or parsed.password or any(ord(c) < 32 for c in url)):
        return False
    if method == 'POST':
        return parsed.path in {API + '/auth/login', API + '/auth/logout'} and not parsed.query
    return method in {'GET', 'HEAD'} and (
        parsed.path.startswith('/demo2/') or parsed.path.startswith(API + '/')
        or parsed.path.startswith('/static/') or parsed.path == '/favicon.ico')


def api(page, path):
    result = page.evaluate('''async path => {
      const r = await fetch(path, {cache:'no-store', credentials:'same-origin',
        redirect:'error', signal:AbortSignal.timeout(30000)});
      if (!r.ok) return {accepted:false};
      const body=await r.json(); return {accepted:body.ok!==false, body};
    }''', API + path)
    require(result.get('accepted') is True and isinstance(result.get('body'), dict), 'api_failed')
    return result['body']


def goto(page, origin, path):
    response = page.goto(origin + path, wait_until='domcontentloaded')
    require(response is not None and response.status == 200
            and urlsplit(page.url).path == urlsplit(path).path, 'page_failed')


def capture(page, output, name, secrets):
    """Mask real DOM regions, not fabricated replacement content or screenshots."""
    try:
        page.evaluate('''values => {
          const sensitive=/(?:password|passwd|cookie|invite|invitation|secret|token|密码|邀请码|邀请密钥)/i;
          for (const e of document.querySelectorAll('body *')) {
            const text=[...e.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('');
            const attr=[e.id,e.getAttribute('name'),e.getAttribute('href'),e.getAttribute('src')].join(' ');
            if (values.some(v=>v && text.includes(v)) || sensitive.test(attr)
                || (text.length<300 && sensitive.test(text))) e.setAttribute('data-acceptance-private','');
          }
        }''', secrets)
        page.screenshot(path=str(output / name), full_page=True, animations='disabled',
                        mask=[page.locator(MASK_SELECTORS)], mask_color='#d4deeb', timeout=30000)
        os.chmod(output / name, 0o600)
        return name
    except Exception:
        raise BrowserAcceptanceError('screenshot_failed') from None


def login(page, context, origin, credentials, role, output, prefix):
    goto(page, origin, '/demo2/login')
    page.locator('#username').wait_for()
    if role == 'company_admin':
        page.locator('#adminRole').click()
    # Blank login form only. Never take a screenshot while credentials are filled.
    capture(page, output, prefix + '-01-login.png', [])
    page.locator('#username').fill(credentials['username'])
    page.locator('#password').fill(credentials['password'])
    page.locator('#loginButton').click()
    page.wait_for_url(lambda url: urlsplit(url).path != '/demo2/login', timeout=30000)
    account = api(page, '/auth/me').get('account', {})
    require(account.get('role') == role and credentials['username'] in
            {account.get('username'), account.get('login_alias')}, 'login_failed')
    cookies = context.cookies()
    return [credentials['username'], credentials['password'], account.get('username', ''),
            *[c['value'] for c in cookies]]


def teacher(page, context, origin, credentials, output, number):
    prefix = f'school-{number}'
    sensitive = login(page, context, origin, credentials, 'school_uploader', output, prefix)
    tasks = api(page, '/course-analysis/tasks').get('tasks', [])
    require(isinstance(tasks, list), 'api_failed')
    candidates = [task for task in tasks if synthetic_task(task)]
    require(candidates, 'synthetic_task_missing')
    # Prefer the latest list entry; never substitute a real classroom if unsuitable.
    task = candidates[0]
    query = urlencode({'task_id': task['task_id']})
    validate_workspace(api(page, '/course-analysis?' + query).get('workspace'), task)
    upload_query = urlencode({'course_id': task['course_id']})
    upload = api(page, '/upload/workspace?' + upload_query).get('workspace', {})
    require(isinstance(upload.get('tasks'), list) and upload['tasks']
            and all(synthetic_task(t) and t.get('course_id') == task['course_id'] for t in upload['tasks']),
            'unsafe_synthetic_workspace')
    goto(page, origin, '/demo2/upload?' + upload_query)
    page.locator('#taskList .task-row').first.wait_for()
    page.wait_for_function("document.getElementById('accountName').textContent !== '读取中'")
    images = [prefix + '-01-login.png', capture(page, output, prefix + '-02-upload-list.png', sensitive)]
    goto(page, origin, '/demo2/analysis?' + query)
    page.locator('#technicalStats').wait_for(state='visible')
    require('技术处理记录已生成' in page.locator('#technicalStatus').inner_text(), 'technical_result_missing')
    images.append(capture(page, output, prefix + '-03-synthetic-result.png', sensitive))
    page.evaluate("window.__acceptanceStage='segment_playback'")
    page.locator('[data-segment]').first.wait_for()
    page.locator('[data-segment]').first.click()
    page.wait_for_function("document.getElementById('video').currentTime > 0.1", timeout=30000)
    page.locator('#video').evaluate('(v) => v.pause()')
    require(page.locator('#video').evaluate('(v) => v.videoWidth > 0'), 'technical_result_missing')
    page.set_viewport_size({'width':390, 'height':844})
    images.append(capture(page, output, prefix + '-04-result-mobile.png', sensitive))
    page.set_viewport_size({'width':1440, 'height':1000})
    page.locator('#tab-report').click()
    page.locator('#reportBody .technical-report').wait_for()
    # Real UI download event from actual HTTP workspace; no invented receipt UI.
    with page.expect_download(timeout=45000) as event:
        page.locator('#downloadHtml').click()
    download = event.value
    require(download.failure() is None, 'download_failed')
    temporary = download.path()
    require(temporary is not None and Path(temporary).stat().st_size < 16 * 1024 * 1024, 'download_failed')
    body = Path(temporary).read_bytes()
    require(body and b'<!doctype html>' in body.lower()
            and all(value.encode() not in body for value in sensitive if value), 'download_failed')
    receipt = {'bytes':len(body), 'sha256':hashlib.sha256(body).hexdigest(), 'download_event':True,
               'raw_download_retained':False}
    download.delete()
    images.append(capture(page, output, prefix + '-05-teacher-download.png', sensitive))
    return {'ok':True, 'screenshots':images, 'download':receipt,
            'synthetic_task_fingerprint':hashlib.sha256(task['task_id'].encode()).hexdigest()}


def admin(page, context, origin, credentials, output):
    sensitive = login(page, context, origin, credentials, 'company_admin', output, 'admin')
    goto(page, origin, '/demo2/admin')
    page.wait_for_function("document.getElementById('taskCount').textContent !== '--'")
    require(isinstance(api(page, '/admin/summary').get('summary'), dict), 'api_failed')
    return {'ok':True, 'screenshots':['admin-01-login.png',
            capture(page, output, 'admin-02-dashboard.png', sensitive)]}


def run(browser, origin, schools, administrator, output, report):
    for number, credentials in enumerate([*schools, administrator], 1):
        key = f'school-{number}' if number <= 4 else 'admin'
        context = browser.new_context(viewport={'width':1440, 'height':1000},
            accept_downloads=True, service_workers='block')
        try:
            context.route('**/*', lambda route: route.continue_() if allowed_request(
                route.request.url, route.request.method, origin) else route.abort())
            if hasattr(context, 'route_web_socket'):
                context.route_web_socket('**/*', lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(30000)
            # Browser console/errors/requests deliberately have no logging callbacks.
            report['accounts'][key] = teacher(page, context, origin, credentials, output, number) if number <= 4 else admin(
                page, context, origin, credentials, output)
        except Exception as exc:
            report['accounts'][key] = {'ok':False, 'error':safe_code(exc)}
            try:
                report['accounts'][key]['diagnostic'] = page.evaluate('''() => ({
                    stage: window.__acceptanceStage || 'before_playback',
                    ready_state: document.getElementById('video')?.readyState ?? null,
                    media_error: document.getElementById('video')?.error?.code ?? null,
                    video_width: document.getElementById('video')?.videoWidth ?? null
                })''')
            except Exception:
                pass
        finally:
            try:
                context.request.post(origin + API + '/auth/logout', data={}, timeout=10000,
                                     max_redirects=0)
            except Exception:
                pass
            context.close()
    report['ok'] = len(report['accounts']) == 5 and all(v['ok'] for v in report['accounts'].values())


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BrowserAcceptanceError('invalid_arguments')


def main(argv=None):
    report = {'ok':False, 'accounts':{}, 'actual_http':True, 'mocked_responses':False,
        'new_tasks_or_students_created':False, 'privacy_masks_applied':True,
        'not_verified':['public_https', 'large_upload_speed', 'new_upload', 'student_assessment']}
    output = None
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--base-url', default='http://127.0.0.1:8793')
        parser.add_argument('--school-credentials-file', type=Path, required=True)
        parser.add_argument('--admin-credentials-file', type=Path, required=True)
        parser.add_argument('--executable-path', type=Path,
            help='Existing executable under /opt/rehabaffect-browser/; no symlink components.')
        parser.add_argument('--output-root', type=Path,
            default=Path.home() / '.local/state/rehab-affect/cloud-browser-screenshots')
        args = parser.parse_args(argv)
        require(sys.platform.startswith('linux'), 'linux_required')
        _, _, origin = endpoint(args.base_url)
        browser_executable(args.executable_path)
        # Prevent permissive defaults or debugging env from persisting secret call logs.
        os.umask(0o077)
        for key in ('DEBUG', 'PWDEBUG'):
            os.environ.pop(key, None)
        schools, administrator = load_credentials(args.school_credentials_file, args.admin_credentials_file)
        output = private_output(args.output_root)
        report['output_directory'] = str(output)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserAcceptanceError('browser_unavailable') from None
        with sync_playwright() as playwright:
            executable = browser_executable(args.executable_path)
            launch_options = {'executable_path':executable} if executable is not None else {}
            browser = playwright.chromium.launch(headless=True,
                args=['--disable-background-networking', '--disable-component-update',
                      '--no-proxy-server'], **launch_options)
            try:
                run(browser, origin, schools, administrator, output, report)
            finally:
                browser.close()
    except KeyboardInterrupt:
        report['error'] = 'interrupted'
    except Exception as exc:
        report['error'] = safe_code(exc)
    if output is not None:
        try:
            report['screenshot_files'] = sorted(p.name for p in output.glob('*.png')
                if re.fullmatch(r'(school-[1-4]|admin)-[0-9]{2}-[a-z-]+\.png', p.name))
            path = output / 'acceptance.json'
            path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding='utf-8')
            path.chmod(0o600)
        except OSError:
            report.update(ok=False, error='unsafe_output')
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
