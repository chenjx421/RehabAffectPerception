"""Course-level provenance contracts. Media fixtures are synthetic, not real video.

Actual decoding acceptance lives in the isolated first-use verifier; these tests
focus on source authorization, version locking, historical records and page IO.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from test_demo2_evaluation_store import env, payload
from test_demo2_evaluation_api import http_env
from test_demo2_identity_store import make_task
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect import scenario_lab_server as server


@pytest.fixture
def source(env):
    account = env.records.account_from_session(env.tokens['t1'])
    fixture = SimpleNamespace(record=env.records, identity=env.store.identities,
        sessions={'school_uploader_01': (account, env.tokens['t1'])})
    return make_task(fixture, set_school=False)


def linked(source, **changes):
    return payload(task_id=source.task_id, frame_revision=source.revision, **changes)


def test_task_link_is_server_derived_course_level_and_survives_old_client(env, source):
    saved = env.store.save(env.tokens['t1'], linked(source))
    assert saved['task_id'] == source.task_id and saved['frame_revision'] == source.revision
    assert saved['source_sha256'] == source.result['source_sha256']
    assert saved['source_provenance']['scope'] == 'course'
    assert saved['source_provenance']['student_linkage'] == 'not_asserted'
    assert 'student_id' not in saved
    assert env.store.workspace(env.tokens['t1'])['records'] == [saved]
    updated = env.store.save(env.tokens['t1'], payload(expected_version=1))
    assert updated['source_provenance'] == saved['source_provenance']
    assert updated['task_id'] == source.task_id


def test_source_is_locked_including_legacy_unlinked_records(env, source):
    env.store.save(env.tokens['t1'], linked(source))
    for fields in ({'task_id':'another-task','frame_revision':source.revision},
                   {'task_id':'','frame_revision':''},
                   {'task_id':source.task_id,'frame_revision':'0'*64}):
        with pytest.raises(MeasurementError) as exc:
            env.store.save(env.tokens['t1'], payload(expected_version=1, **fields))
        assert exc.value.code == 'source_locked'
    env.store.save(env.tokens['t1'], payload(record_id='legacy',lesson_id='legacy-lesson'))
    with env.records._connect() as db:
        row=json.loads(db.execute('SELECT payload_json FROM demo2_classroom_evaluations WHERE record_id=?',('legacy',)).fetchone()[0])
        for key in ('task_id','frame_revision','source_sha256','source_provenance'):
            row.pop(key,None)
        raw=json.dumps(row,ensure_ascii=False)
        db.execute('UPDATE demo2_classroom_evaluations SET payload_json=? WHERE record_id=?',(raw,'legacy'))
    historical=next(r for r in env.store.workspace(env.tokens['t1'])['records'] if r['record_id']=='legacy')
    assert historical['source_provenance']['status']=='unlinked'
    with env.records._connect() as db:
        assert db.execute('SELECT payload_json FROM demo2_classroom_evaluations WHERE record_id=?',('legacy',)).fetchone()[0]==raw
    with pytest.raises(MeasurementError) as exc:
        env.store.save(env.tokens['t1'],linked(source,record_id='legacy',lesson_id='legacy-lesson',expected_version=1))
    assert exc.value.code=='source_locked'


def test_cross_account_cross_school_stale_source_and_forged_hash_fail(env, source):
    with pytest.raises(MeasurementError) as exc:
        env.store.preview(env.tokens['t2'],linked(source))
    assert exc.value.status==404
    with pytest.raises(MeasurementError) as exc:
        env.store.save(env.tokens['t1'],linked(source,source_sha256='0'*64))
    assert exc.value.code=='invalid_payload'
    with pytest.raises(MeasurementError) as exc:
        env.store.preview(env.tokens['t1'],payload(task_id=source.task_id,frame_revision='0'*64))
    assert exc.value.code=='source_version_changed'
    saved=env.store.save(env.tokens['t1'],linked(source))
    with env.records._connect() as db:
        raw=json.dumps({**source.result,'synthetic_revision_change':True})
        db.execute('UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?',(raw,source.task_id))
    view=env.store.workspace(env.tokens['t1'])['records'][0]
    assert view['source_provenance']['status']=='needs_reconfirmation'
    assert view['source_sha256']==saved['source_sha256']
    with pytest.raises(MeasurementError):
        env.store.save(env.tokens['t1'],payload(expected_version=1))
    with env.records._connect() as db:
        db.execute('UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?',(source.raw,source.task_id))
    env.records.save_account_school_context(env.tokens['t1'],dict(city='测试市',district='测试区',school_name='另一合成学校'))
    with pytest.raises(MeasurementError) as exc:
        env.store.preview(env.tokens['t1'],linked(source,record_id='new',lesson_id='new'))
    assert exc.value.code=='source_school_mismatch'


def test_http_link_preview_save_reload_without_student_ids(http_env, source):
    request=http_env; api='/api/v1/demo2/evaluations'
    assert request(api+'/preview','POST',linked(source))[0]==200
    status,_,body=request(api,'POST',linked(source))
    assert status==200,body
    saved=body['record']
    assert saved['source_sha256']==source.result['source_sha256']
    assert request(api)[2]['workspace']['records']==[saved]
    assert request(api+'/preview','POST',linked(source),user='t2')[0]==404
    assert request(api,'POST',payload(expected_version=1,task_id='',frame_revision=''))[0]==409


def test_page_source_url_validation_payload_and_json_export():
    html=render_evaluation({'role':'school_uploader','username':'synthetic'})
    for token in ('getAll("currenttask")','getAll("task_id")','identity/workspace?task_id=',
                  'task_id:source.task_id,frame_revision:source.frame_revision','SHA-256',
                  '未关联视频任务','JSON.stringify(renderedRecord,null,2)',
                  'workspace.records.filter(r=>r.task_id===requestedTask)'):
        assert token in html
    node=shutil.which('node')
    if not node:
        pytest.skip('Installed Node required')
    scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
    result=subprocess.run([node,'-e',"JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
        input=json.dumps(scripts),encoding='utf-8',capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_browser_currenttask_save_reload_export_and_invalid_url(env,source,monkeypatch,tmp_path):
    node=shutil.which('node')
    module=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
    if not node or not module.exists():
        pytest.skip('Installed Node/Playwright required; no downloads')
    env.store.save(env.tokens['t1'],linked(source))
    env.store.save(env.tokens['t1'],payload(record_id='legacy',lesson_id='legacy-lesson'))
    monkeypatch.setattr(server,'get_demo2_student_store',lambda:env.records)
    handler=server.create_handler(scenario_dir=tmp_path,model_path=tmp_path/'unused',policy_name='rule')
    http=ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=Thread(target=http.serve_forever,daemon=True);thread.start()
    cache=Path.home()/'AppData/Local/ms-playwright'
    candidates=sorted(cache.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'),reverse=True)
    executable=str(candidates[0]) if candidates else 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
    data=dict(module=str(module),executable=executable,origin=f'http://127.0.0.1:{http.server_port}',
              token=env.tokens['t1'],task=source.task_id,sha=source.result['source_sha256'],root=str(tmp_path))
    code=r"""
const fs=require('fs'),assert=require('assert/strict'),d=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const browser=await require(d.module).chromium.launch({headless:true,executablePath:d.executable});
try{const context=await browser.newContext(),page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
await context.route('**/*',r=>new URL(r.request().url()).origin===d.origin?r.continue():r.abort());
await context.addCookies([{name:'rehab_demo2_session',value:d.token,url:d.origin}]);
await page.goto(d.origin+'/demo2/evaluation?currenttask='+d.task);
await page.waitForFunction(()=>document.getElementById('resultContext').textContent.includes('SHA-256'));
assert.ok((await page.locator('#resultContext').textContent()).includes(d.sha));
assert.equal(await page.locator('.record-item').count(),1);
await page.locator('#editRecordBtn').click();await page.locator('#fCourseName').fill('SYNTHETIC browser source edit');
await page.locator('#saveBtn').click();
await page.waitForFunction(()=>document.getElementById('formMsg').textContent.includes('记录已保存'));
await page.reload();await page.waitForFunction(()=>document.getElementById('resultMeta').textContent.includes('已保存版本 2'));
const pending=page.waitForEvent('download');await page.locator('#exportJsonBtn').click();const download=await pending;
const path=d.root+'/SYNTHETIC-evaluation-export.json';await download.saveAs(path);const record=JSON.parse(fs.readFileSync(path,'utf8'));
assert.equal(record.task_id,d.task);assert.equal(record.source_sha256,d.sha);assert.equal(record.source_provenance.scope,'course');
assert.equal('student_id' in record,false);
await page.screenshot({path:d.root+'/SYNTHETIC-evaluation-linked.png',fullPage:true});
await page.goto(d.origin+'/demo2/evaluation');await page.locator('[data-id="legacy"]').click();
assert.ok((await page.locator('#resultContext').textContent()).includes('未关联视频任务'));
await page.goto(d.origin+'/demo2/evaluation?currenttask=../invalid');
await page.waitForFunction(()=>document.getElementById('evaluationSource').textContent.includes('链接无效'));
assert.equal(await page.locator('#saveBtn').isDisabled(),true);assert.deepEqual(errors,[]);
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
"""
    try:
        result=subprocess.run([node,'-e',code],input=json.dumps(data),text=True,encoding='utf-8',capture_output=True,timeout=70)
        assert result.returncode==0,result.stderr
    finally:
        http.shutdown();http.server_close();thread.join(5)
