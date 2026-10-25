"""Read-only checks of real identity candidates; never writes student bindings."""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import cloud_e2e_acceptance as base

ORIGIN = 'http://127.0.0.1:8793'
PRIVATE = Path('/var/lib/rehabaffect/acceptance-private')
BROWSER = '/opt/rehabaffect-browser/official-cft-156/chrome-headless-shell-linux64/chrome-headless-shell'


def run(args):
    os.umask(0o077)
    if args.output.parent != PRIVATE or args.output.exists():
        raise ValueError('unsafe_output')
    args.output.mkdir(mode=0o700)
    schools, _ = base.load_credentials(PRIVATE/'schools.private.md', PRIVATE/'admin.private.json')
    client = base.Client(ORIGIN)
    result = {'passed': False, 'mode': 'candidate' if args.candidate else 'live'}
    try:
        client.login(schools[args.school_index-1], 'school_uploader')
        path = base.route('/identity/workspace', task_id=args.task_id)
        original = client.json(path)['workspace']
        frames = original['frames']
        result.update(frame_count=len(frames), binding_count=len(original['bindings']), detections=[])
        selected = None
        for frame in frames[:8]:
            detection = client.json(base.route('/identity/detect', task_id=args.task_id,
                frame_key=frame['frame_key'], frame_revision=original['frame_revision']))['detection']
            result['detections'].append({'time_sec': frame['time_sec'], 'count': len(detection.get('faces', [])),
                'available': detection.get('available'), 'reason': detection.get('reason')})
            if detection.get('faces') and selected is None:
                selected = frame
        if not selected:
            result['failure'] = 'no_clickable_candidates_in_sampled_frames'
            return
        html = None
        if args.candidate:
            sys.path.insert(0, '/opt/rehabaffect/src')
            spec = importlib.util.spec_from_file_location('rehab_affect._identity_candidate', args.candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            html = module.render_identity({'role':'school_uploader','username':'acceptance'})
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER, headless=True, args=['--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width':1440,'height':1000})
            cookies = SimpleCookie(); cookies.load(client.cookie)
            context.add_cookies([{'name':c.key,'value':c.value,'url':ORIGIN,'httpOnly':True,'sameSite':'Lax'} for c in cookies.values()])
            def guarded(route):
                if route.request.method not in ('GET','HEAD'):
                    route.abort(); return
                if html and urlsplit(route.request.url).path == '/demo2/identity':
                    route.fulfill(status=200, content_type='text/html', body=html); return
                route.continue_()
            context.route('**/*', guarded)
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.goto(ORIGIN+'/demo2/identity?task_id='+args.task_id, wait_until='networkidle', timeout=60000)
            page.locator('#frameSelect').select_option(str(frames.index(selected)))
            page.locator('[data-candidate="0"]').wait_for(state='visible', timeout=30000)
            candidate = page.locator('[data-candidate="0"]')
            result['portrait_count'] = page.locator('#candidateList .candidate-portrait').count()
            if args.require_portraits:
                assert result['portrait_count'] > 0
                assert not page.locator('#drawButton').is_visible()
            candidate.click()
            assert page.locator('.roi.selected').count() == 1
            assert page.locator('#drawButton').get_attribute('aria-pressed') == 'false'
            assert page.locator('#bboxWidth').input_value()
            result['click_selects_region_without_drawing'] = True
            result['test_profile_buttons'] = page.locator('[data-quick-test]').count()
            mask = [page.locator('#taskCourse,#taskSchool,#studentSelect,#bindingList,#studentSearch')]
            page.locator('#candidateList').scroll_into_view_if_needed()
            page.screenshot(path=str(args.output/'01-portrait-selection.png'), mask=mask)
            page.locator('#candidateList').screenshot(path=str(args.output/'02-portraits.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#candidateList').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(args.output/'03-mobile.png'), mask=mask)
            assert not errors
            result['browser_errors'] = 0
            context.close(); browser.close()
        assert client.json(path)['workspace'] == original
        result.update(passed=True, bindings_unchanged=True)
    finally:
        if client.cookie:
            client.request(base.API+'/auth/logout',payload={})
        (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--school-index', type=int, choices=range(1,5), default=1)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--require-portraits', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
