"""Read-only student-facing browser acceptance on the real authorized course.

Candidate mode projects existing observations, never calls a model or writes
student records. Live mode uses the deployed page and API without interception.
"""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

import cloud_e2e_acceptance as base

ORIGIN = 'http://127.0.0.1:8793'
PRIVATE = Path('/var/lib/rehabaffect/acceptance-private')
DB = Path('/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3')
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
    schools, _ = base.load_credentials(PRIVATE/'schools.private.md',PRIVATE/'admin.private.json')
    clients = [base.Client(ORIGIN) for _ in schools]
    result = {'mode':'live' if args.live else 'candidate_on_real_api','passed':False}
    try:
        for client, credentials in zip(clients,schools):
            client.login(credentials,'school_uploader')
        owner = clients[args.school_index-1]
        path = base.route('/observations',task_id=args.task_id)
        original = owner.json(path)['workspace']
        public = json.loads(json.dumps(original))
        identity = owner.json(base.route('/identity/workspace',task_id=args.task_id))['workspace']
        if not args.live:
            sys.path.insert(0,'/opt/rehabaffect/src')
            analysis = module(args.stage/'src/rehab_affect/demo2_course_analysis.py','rehab_affect._student_candidate')
            html = module(args.stage/'src/rehab_affect/demo2_course_page.py','_student_page').HTML
            with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:
                db.row_factory = sqlite3.Row
                task = dict(db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?',(args.task_id,)).fetchone())
                links = {(r['person_id'],r['frame_key']):r['binding_id'] for r in db.execute(
                    'SELECT * FROM demo2_observation_person_links WHERE job_id=?',(public['job_id'],))}
            public['student_insights'] = analysis.build_student_insights(public,identity,task,links)
        insights = public['student_insights']
        assert insights['ready'] and insights['task_id']==args.task_id
        assert insights['source_sha256']==public['source_sha256']
        assert insights['frame_revision']==public['frame_revision']
        profiles = insights['students']+insights['anonymous_people']
        assert profiles and all(p['evidence'] and p['dimensions'] and p['suggestions'] for p in profiles)
        for client in clients:
            if client is not owner:
                assert client.request(path)[0] in (403,404)
        assert base.Client(ORIGIN).request(path)[0] in (401,403)
        result.update(four_logins=True,peer_denials=3,anonymous_denial=True,
            observation_count=insights['summary']['observation_count'],
            confirmed_students=len(insights['students']),frame_local_profiles=len(insights['anonymous_people']),
            observation_samples=insights['summary']['sample_count'],
            canonical_result_unchanged=public['result']==original['result'])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER,headless=True,args=['--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            cookies = SimpleCookie(); cookies.load(owner.cookie)
            context.add_cookies([{'name':c.key,'value':c.value,'url':ORIGIN,'httpOnly':True,'sameSite':'Lax'} for c in cookies.values()])
            def guarded(route):
                request = route.request
                if request.method not in ('GET','HEAD'):
                    route.abort(); return
                if not args.live and urlsplit(request.url).path=='/demo2/analysis':
                    route.fulfill(status=200,content_type='text/html',body=html); return
                if not args.live and request.url==ORIGIN+path:
                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'workspace':public},ensure_ascii=False)); return
                route.continue_()
            context.route('**/*',guarded)
            page = context.new_page(); errors = []
            page.on('pageerror',lambda error:errors.append(type(error).__name__))
            page.goto(ORIGIN+'/demo2/analysis?task_id='+args.task_id,wait_until='networkidle',timeout=60000)
            try:
                page.wait_for_selector('#studentInsightsCards .insight-card',state='visible',timeout=30000)
            except Exception:
                print(page.evaluate('''() => { const e=document.querySelector('#studentInsightsCards .insight-card'); return {errors:window.__errors||[], hidden:e?.closest('#group')?.hidden, group:e?.closest('#group')?.outerHTML.slice(0,300), pane:e?.closest('.student-insight-pane')?.hidden, section:e?.closest('#studentInsightsSection')?.hidden, display:e?getComputedStyle(e).display:''}; }'''))
                raise
            page.locator('#studentInsightsSection').scroll_into_view_if_needed()
            page.wait_for_function('Array.from(document.querySelectorAll("#studentInsightsCards img")).every(i=>i.complete&&i.naturalWidth>0)')
            cards = page.locator('#studentInsightsCards .insight-card')
            assert 1 <= cards.count() <= 3
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            # All visible labels come from current model rows, not scene energy.
            body = page.locator('#studentInsightsCards').inner_text()
            assert '参与状态' in body and '支持建议' in body
            assert '音频能量' not in body and '亮度' not in body
            mask = [page.locator('#school,#title,#scope,#groupTable')]
            page.screenshot(path=str(args.output/'01-students-desktop.png'),mask=mask)
            page.locator('#studentInsightsSection').screenshot(path=str(args.output/'02-student-cards.png'))
            first_key = cards.first.get_attribute('data-insight-profile')
            page.locator('#studentInsightsLimit').select_option('1')
            assert page.locator('#studentInsightsCards .insight-card').count()==1
            if len(profiles)>1:
                page.locator('#studentInsightsNext').click()
                assert page.locator('#studentInsightsCards .insight-card').first.get_attribute('data-insight-profile')!=first_key
                page.locator('#studentInsightsPrev').click()
            page.locator('#studentInsightsLimit').select_option('3')
            page.locator('#studentInsightsCards [data-insight-evidence]').first.click()
            page.wait_for_function('document.getElementById("video").readyState >= 1',timeout=30000)
            page.wait_for_timeout(500)
            expected = profiles[0]['evidence'][0]['time_sec']
            assert abs(page.evaluate('document.getElementById("video").currentTime')-expected)<3
            page.evaluate('document.getElementById("video").pause()')
            if insights['anonymous_people']:
                href = page.locator('#studentInsightsCards [data-insight-identity]').first.get_attribute('href')
                assert args.task_id in href and 'frame_key=' in href
                page.goto(ORIGIN+href,wait_until='domcontentloaded',timeout=30000)
                assert page.url.startswith(ORIGIN+'/demo2/identity')
                page.go_back(wait_until='domcontentloaded')
                page.wait_for_selector('#studentInsightsCards .insight-card',state='visible',timeout=30000)
            page.locator('#tab-report').click()
            page.locator('.student-insights-report').wait_for(state='visible')
            assert profiles[0]['headline'] in page.locator('#reportBody').inner_text()
            page.screenshot(path=str(args.output/'03-student-report.png'),mask=mask)
            with page.expect_download() as downloaded:
                page.locator('#downloadHtml').click()
            content = Path(downloaded.value.path()).read_text(encoding='utf-8')
            assert '学生课堂' in content and profiles[0]['headline'] in content
            page.locator('#tab-group').click()
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#studentInsightsSection').scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(args.output/'04-students-mobile.png'),mask=mask)
            assert not errors
            result.update(browser_errors=0,desktop_no_overflow=True,mobile_no_overflow=True,
                evidence_images_loaded=True,clip_seek_passed=True,identity_entry_opened=True,
                report_download_contains_student_insights=True,pagination_passed=True)
            context.close(); browser.close()
        after = owner.json(path)['workspace']
        assert after==original,'observation_workspace_changed'
        result['existing_observations_unchanged']=True
        result['passed']=True
    finally:
        for client in clients:
            if client.cookie:
                client.request(base.API+'/auth/logout',payload={})
        (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage',type=Path)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--school-index',type=int,choices=range(1,5),default=1)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not args.live and args.stage is None:
        parser.error('candidate requires --stage')
    run(args)
