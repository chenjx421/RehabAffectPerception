"""Read-only real-course acceptance for the additive classroom draft release.

Candidate mode renders candidate code over the real authenticated course API.
Only the page document and its additive draft field are replaced; video, identity,
observations and permissions remain real. Live mode performs no interception.
No uploads, student changes, model calls or observation requests are made.
"""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import cloud_e2e_acceptance as base

ORIGIN = 'http://127.0.0.1:8793'
PRIVATE = Path('/var/lib/rehabaffect/acceptance-private')
BROWSER = '/opt/rehabaffect-browser/official-cft-156/chrome-headless-shell-linux64/chrome-headless-shell'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(args):
    os.umask(0o077)
    if args.output.parent != PRIVATE or args.output.exists() or args.output.is_symlink():
        raise ValueError('unsafe_output')
    args.output.mkdir(mode=0o700)
    schools, _ = base.load_credentials(PRIVATE/'schools.private.md', PRIVATE/'admin.private.json')
    clients = [base.Client(ORIGIN) for _ in schools]
    result = {'mode':'live' if args.live else 'candidate_on_real_api', 'passed':False}
    try:
        for client, credentials in zip(clients, schools):
            client.login(credentials, 'school_uploader')
        owner = clients[args.school_index-1]
        path = base.route('/course-analysis', task_id=args.task_id)
        began = time.monotonic()
        workspace = owner.json(path)['workspace']
        result['workspace_response_ms'] = round((time.monotonic()-began)*1000, 1)
        original = json.dumps(workspace, ensure_ascii=False, sort_keys=True)
        if not args.live:
            sys.path.insert(0, '/opt/rehabaffect/src')
            analysis = module(args.stage/'src/rehab_affect/demo2_course_analysis.py', 'rehab_affect._draft_candidate')
            html = module(args.stage/'src/rehab_affect/demo2_course_page.py', '_draft_page').HTML
            began = time.monotonic()
            workspace['classroom_draft'] = analysis._classroom_draft(workspace['technical_evidence'], workspace['people'])
            result['draft_generation_ms'] = round((time.monotonic()-began)*1000, 1)
        draft = workspace['classroom_draft']
        assert draft['ready'] and draft['task_id'] == args.task_id
        assert draft['frame_revision'] == workspace['frame_revision']
        assert len(draft['timeline']) == len(workspace['technical_evidence']['segments'])
        assert len(draft['timeline']) > 3 and len(draft['sections']) >= 7
        assert draft['character_count'] >= 1000
        for i, client in enumerate(clients):
            if i != args.school_index-1:
                assert client.request(path)[0] in (403, 404)
        assert base.Client(ORIGIN).request(path)[0] in (401, 403)
        result.update(segments=len(draft['timeline']), key_clips=len(draft['key_clips']),
                      narrative_characters=draft['character_count'], sections=len(draft['sections']),
                      linked_students=len(draft['students']), four_logins=True,
                      peer_denials=3, anonymous_denial=True,
                      teacher_record_count=workspace['summary']['records'])
        try:
            observations = owner.json(base.route('/observations', task_id=args.task_id))['workspace']
            result['existing_model_status'] = observations.get('status')
            frames = (observations.get('result') or {}).get('frames') or []
            result['existing_model_frames'] = len(frames)
            result['existing_model_observations'] = sum(len(f.get('observations') or []) for f in frames)
        except base.AcceptanceError:
            result['existing_model_status'] = 'unavailable'
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER, headless=True, args=['--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width':1440,'height':1000}, accept_downloads=True)
            cookies = SimpleCookie(); cookies.load(owner.cookie)
            context.add_cookies([{'name':c.key,'value':c.value,'url':ORIGIN,'httpOnly':True,'sameSite':'Lax'} for c in cookies.values()])
            def guarded(route):
                request = route.request
                if request.method not in ('GET', 'HEAD'):
                    route.abort(); return
                if not args.live and urlsplit(request.url).path == '/demo2/analysis':
                    route.fulfill(status=200,content_type='text/html',body=html); return
                if not args.live and request.url == ORIGIN+path:
                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'workspace':workspace},ensure_ascii=False)); return
                route.continue_()
            context.route('**/*', guarded)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error:errors.append(type(error).__name__))
            page.goto(ORIGIN+'/demo2/analysis?task_id='+args.task_id,wait_until='networkidle',timeout=60000)
            page.wait_for_function('typeof work !== "undefined" && work !== null')
            page.wait_for_selector('#classroomDraftSection',state='visible',timeout=20000)
            page.locator('#video').wait_for(state='visible')
            page.wait_for_function('document.getElementById("video").readyState >= 1',timeout=30000)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            mask = [page.locator('#school,#title,#scope,.observation-source,#aiTargetList,#groupTable')]
            page.screenshot(path=str(args.output/'01-classroom-desktop.png'),mask=mask,full_page=False)
            page.locator('#classroomDraftSection').screenshot(path=str(args.output/'02-draft-detail.png'),mask=mask)
            # Buttons carry validated segment bounds, not an invented event time.
            clips = page.locator('[data-draft-clip]')
            assert clips.count() > 0
            clips.first.click()
            page.wait_for_timeout(600)
            assert page.evaluate('document.getElementById("video").currentTime') >= draft['key_clips'][0]['start_sec']-1
            page.evaluate('document.getElementById("video").pause()')
            page.locator('#tab-report').click()
            page.locator('#reportBody .classroom-draft-report').wait_for(state='visible')
            assert draft['sections'][0]['text'] in page.locator('#reportBody').inner_text()
            page.screenshot(path=str(args.output/'03-report-desktop.png'),mask=mask,full_page=False)
            with page.expect_download() as download:
                page.locator('#downloadHtml').click()
            report_path = download.value.path()
            content = Path(report_path).read_text(encoding='utf-8')
            assert draft['title'] in content and draft['sections'][0]['text'] in content
            result['report_download_contains_draft'] = True
            page.locator('#tab-group').click()
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(args.output/'04-classroom-mobile.png'),mask=mask,full_page=False)
            assert not errors, 'browser_runtime_error'
            result.update(browser_errors=0, desktop_no_overflow=True, mobile_no_overflow=True,
                          actual_video_metadata_loaded=True, clip_seek_passed=True)
            context.close(); browser.close()
        after = owner.json(path)['workspace']
        assert json.dumps(after, ensure_ascii=False, sort_keys=True) == original, 'source_changed'
        result['source_workspace_unchanged'] = True
        result['passed'] = True
    finally:
        for client in clients:
            if client.cookie:
                client.request(base.API+'/auth/logout',payload={})
        (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--school-index', type=int, choices=range(1,5), default=1)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not args.live and args.stage is None:
        parser.error('candidate requires --stage')
    run(args)
