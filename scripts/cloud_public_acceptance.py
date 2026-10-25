"""Fixed-IP HTTPS pilot acceptance, with private invitation and anonymous output."""
from __future__ import annotations

import argparse
import hashlib
import http.client
from http.cookies import SimpleCookie
import json
import math
from pathlib import Path
import secrets
import ssl
import time

import cloud_e2e_acceptance as base

ORIGIN = 'https://YOUR_SERVER_IP'


class PublicClient(base.Client):
    def __init__(self, invitation):
        self.host, self.port, self.origin = 'YOUR_SERVER_IP', 443, ORIGIN
        self.cookie, self.invitation_cookie = '', ''
        status, headers, _ = self.request('/__manager/authorize', payload={'secret': invitation})
        base.require(status == 303, 'invitation_failed')
        cookies = SimpleCookie()
        cookies.load(headers.get('set-cookie', ''))
        token = cookies.get('rehab_manager_invite')
        base.require(token is not None and token['secure'], 'invitation_failed')
        self.invitation_cookie = token.OutputString(attrs=[])

    def request(self, path, *, payload=None, binary=None, headers=None, timeout=40):
        base.require(path.startswith(base.API + '/') or path == '/__manager/authorize', 'unsafe_endpoint')
        values = {'Origin': ORIGIN, 'Accept': 'application/json', 'Connection': 'close'}
        cookies = '; '.join(value for value in (self.invitation_cookie, self.cookie) if value)
        if cookies:
            values['Cookie'] = cookies
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            values['Content-Type'] = 'application/json'
        elif binary is not None:
            body = binary
            values['Content-Type'] = 'application/octet-stream'
        values.update(headers or {})
        connection = http.client.HTTPSConnection(self.host, 443, timeout=timeout,
                                                  context=ssl.create_default_context())
        try:
            connection.request('GET' if body is None else 'POST', path, body=body, headers=values)
            response = connection.getresponse()
            length = response.getheader('Content-Length')
            base.require(length is not None and length.isdecimal() and int(length) <= base.MAX_RESPONSE,
                         'invalid_response')
            content = response.read(int(length) + 1)
            base.require(len(content) == int(length), 'invalid_response')
            return response.status, {k.lower(): v for k, v in response.getheaders()}, content
        except (OSError, http.client.HTTPException):
            raise base.AcceptanceError('network_error') from None
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-config-file', type=Path, required=True)
    parser.add_argument('--school-credentials-file', type=Path, required=True)
    parser.add_argument('--admin-credentials-file', type=Path, required=True)
    parser.add_argument('--sample-source-manifest', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {'ok': False, 'origin': ORIGIN, 'tls_verified': False, 'school_network_test': False,
              'school_logins': 0, 'administrator_login': False}
    clients = []
    try:
        config = json.loads(base.private_text(args.gateway_config_file))
        schools, administrator = base.load_credentials(args.school_credentials_file, args.admin_credentials_file)
        for index, credentials in enumerate([*schools, administrator]):
            client = PublicClient(config['invite_secret'])
            report['tls_verified'] = True
            clients.append(client)
            account = client.login(credentials, 'school_uploader' if index < 4 else 'company_admin')
            if index < 4:
                report['school_logins'] += 1
                base.require(client.request(base.route('/admin/summary'))[0] == 403, 'role_isolation_failed')
            else:
                report['administrator_login'] = True
                base.require(isinstance(client.json(base.route('/admin/summary')).get('summary'), dict),
                             'admin_summary_failed')
        if args.sample_source_manifest:
            private = json.loads(base.private_text(args.sample_source_manifest))
            row = next(value for value in private['samples'] if value['sample_id'] == 'Sample01')
            root = Path(private['source_root']).resolve(strict=True)
            source = (root / row['relative_source_path']).resolve(strict=True)
            base.require(source.is_relative_to(root) and not source.is_symlink()
                         and source.stat().st_size == row['size_bytes'], 'sample_changed')
            course = 'public-wan-acceptance-' + secrets.token_hex(8)
            channel = clients[0].json(base.route('/upload/workspace', course_id=course))['workspace']['channel']
            started = time.monotonic()
            task = clients[0].json(base.route('/upload/tasks'), payload={
                'channel_id': channel['channel_id'], 'course_id': course,
                'course_name': 'Authorized public WAN acceptance', 'session_id': course,
                'uploader_name': 'Authorized acceptance', 'filename': 'PublicSample01.mp4',
                'mime_type': 'video/mp4', 'byte_size': row['size_bytes'],
                'total_chunks': math.ceil(row['size_bytes'] / base.CHUNK_SIZE),
                'security_confirmed': True, 'allow_company_archive': False})['task']
            digest, total, progress = hashlib.sha256(), 0, time.monotonic()
            with source.open('rb') as stream:
                for index in range(math.ceil(row['size_bytes'] / base.CHUNK_SIZE)):
                    chunk = stream.read(base.CHUNK_SIZE)
                    digest.update(chunk)
                    for attempt in range(3):
                        status, _, _ = clients[0].request(base.route('/upload/chunks', task_id=task['task_id'],
                            course_id=course, chunk_index=index), binary=chunk, timeout=330)
                        if status == 200:
                            break
                        current = clients[0].json(base.route('/upload/task', id=task['task_id']))['task']
                        if current['next_chunk_index'] == index + 1:
                            break
                        base.require(current['next_chunk_index'] == index and attempt < 2
                                     and status in {408, 429, 500, 502, 503, 504}, 'chunk_upload_failed')
                    total += len(chunk)
                    if time.monotonic() - progress >= 15:
                        print(json.dumps({'stage': 'public_upload', 'sent_mib': round(total / 1048576, 1)}), flush=True)
                        progress = time.monotonic()
            base.require(digest.hexdigest() == row['sha256'] and total == row['size_bytes'], 'sample_changed')
            current = clients[0].json(base.route('/upload/task', id=task['task_id']))['task']
            base.require(current['upload_status'] == 'completed' and current['sha256'] == row['sha256'],
                         'uploaded_hash_mismatch')
            elapsed = time.monotonic() - started
            report['large_upload'] = {'size_bytes': total, 'seconds': round(elapsed, 3),
                                      'payload_mbps': round(total * 8 / elapsed / 1e6, 3), 'sha256_verified': True}
            print(json.dumps({'stage': 'upload_complete', **report['large_upload']}), flush=True)
            started = time.monotonic()
            while current['analysis_status'] != 'evidence_ready':
                base.require(current['analysis_status'] not in {'failed', 'cancelled'}
                             and time.monotonic() - started < 1800, 'worker_failed_or_timeout')
                time.sleep(5)
                current = clients[0].json(base.route('/upload/task', id=task['task_id']))['task']
            base.automatic_report(clients[0], task['task_id'])
            status, _, body = clients[4].request(base.route('/upload/result', id=task['task_id']))
            base.require(status == 200 and json.loads(body)['source_sha256'] == row['sha256'], 'admin_download_failed')
            status, headers, body = clients[4].request(base.route('/upload/media', id=task['task_id']),
                headers={'Range': 'bytes=0-127'})
            base.require(status == 206 and len(body) == 128, 'admin_media_failed')
            report['analysis'] = {'seconds_including_queue': round(time.monotonic() - started, 3),
                'technical_report_available': True, 'admin_report_download': True, 'admin_media_range': True}
        report['ok'] = True
    except Exception as error:
        report['error'] = error.code if isinstance(error, base.AcceptanceError) else 'public_acceptance_failed'
    finally:
        for client in clients:
            if client.cookie:
                try:
                    client.request(base.route('/auth/logout'), payload={})
                except Exception:
                    pass
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
    print(json.dumps(report), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
