"""Verify the existing invitation and admin summary entry without student writes."""
import http.cookiejar
import json
from pathlib import Path
import urllib.request
import urllib.error


ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / '.runtime/manager_share_config.json').read_text(encoding='utf-8-sig'))
    state = json.loads((ROOT / '.runtime/manager_share_state.json').read_text(encoding='utf-8-sig'))
    credentials = json.loads((ROOT / '.runtime/admin_credentials_20261016.json').read_text(encoding='utf-8-sig'))
    base = state['origin'].rstrip('/')
    assert base == 'https://example.invalid'
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(base + path, data=body, headers={
            'Content-Type': 'application/json', 'Origin': base})
        with opener.open(req, timeout=30) as response:
            return response.read(), response.headers

    request('/__manager/authorize', {'secret': config['invite_secret']})
    raw, _ = request('/api/v1/demo2/auth/login', {
        **credentials, 'role': 'company_admin'})
    assert json.loads(raw)['ok']
    raw, headers = request('/demo2/admin/student-summaries')
    assert '授权学生摘要归档' in raw.decode('utf-8')
    assert '课程历史' in raw.decode('utf-8')
    assert 'no-store' in headers['Cache-Control']
    raw, _ = request('/api/v1/demo2/student-summaries/admin')
    workspace = json.loads(raw)['workspace']
    assert workspace['policy']['purpose'] == 'educational_followup'
    assert workspace['policy']['research'] is False and workspace['policy']['training'] is False
    raw, _ = request('/demo2/admin')
    assert '/demo2/admin/student-summaries' in raw.decode('utf-8')
    try:
        request('/api/v1/demo2/student-summaries/automatic', {})
        raise AssertionError('Administrator cannot configure school authorization')
    except urllib.error.HTTPError as error:
        assert error.code == 403
    report = {'original_public_origin': base, 'existing_invitation_accepted': True,
              'admin_login': True, 'admin_summary_page': True, 'admin_summary_api': True,
              'admin_navigation': True, 'student_archive_entries': workspace['pagination']['total'],
              'automatic_route_role_guard': True,
              'student_writes': False, 'expires_at': config['expires_at']}
    (ROOT / '.runtime/student_summary_live_20261016.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Responses, request details and credentials are deliberately not logged.
        raise SystemExit('Live summary acceptance failed; no student data was written.') from None
