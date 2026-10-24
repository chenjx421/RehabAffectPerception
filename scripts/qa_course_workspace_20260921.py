"""Real media and browser flow in a disposable DB, without child data or API mocks."""
import base64
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from types import SimpleNamespace

from scripts.qa_demo2_dossier_20260911 import isolated_dossier_server
from src.rehab_affect.demo2_media_analysis import _resolve_tool, process_video_task

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='course-workspace-') as tmp:
        with isolated_dossier_server(Path(tmp)) as env:
            env.server.importlib=SimpleNamespace(import_module=importlib.import_module)
            token=env.tokens['t1']
            work=env.identity.workspace(token,env.task_ids['t1'])
            image,_=env.identity.frame_file(token,env.task_ids['t1'],work['frames'][0]['frame_key'],work['frame_revision'])
            video=Path(tmp)/'synthetic.mp4'
            subprocess.run([str(_resolve_tool('ffmpeg')),'-y','-loop','1','-i',str(image),'-f','lavfi',
                '-i','sine=frequency=440:sample_rate=16000','-t','6','-r','12','-c:v','libx264',
                '-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True,capture_output=True,timeout=40)
            data=video.read_bytes()
            task=env.records.create_video_task(dict(account_session_token=token,channel_id='channel_1',
                session_id='review-qa',course_id='review-qa',course_name='合成课堂 · 物品分类（验收数据）',
                uploader_name='合成复核员',filename=video.name,byte_size=len(data),total_chunks=1))
            tid=task['task_id']
            env.records.append_video_chunk(dict(account_session_token=token,task_id=tid,chunk_index=0,
                content_base64=base64.b64encode(data).decode()))
            claim=env.records.claim_next_video_analysis()
            env.records.finish_video_analysis(tid,process_video_task(claim,Path(claim['analysis_dir'])))
            ws=env.identity.workspace(token,tid)
            if '--applicability' not in sys.argv:
                from src.rehab_affect.video_applicability import ApplicabilityStore
                gate=ApplicabilityStore(env.records)
                state=gate.workspace(token,tid)
                gate.save(token,dict(task_id=tid,version=state['version'],revision=state['revision'],category='special',
                    goal='合成验收目标',reason='仅用于合成课堂工作流测试，不代表真实课堂分类',confirmed=True))
            for key,x in [('a',.1),('b',.5)]:
                env.identity.save_binding(token,dict(task_id=tid,frame_key=ws['frames'][0]['frame_key'],
                    frame_revision=ws['frame_revision'],role='student',student_id=env.students[key]['student_id'],
                    bbox=dict(x=x,y=.2,width=.2,height=.6)))
            config=dict(base=f'http://127.0.0.1:{env.port}',task_id=tid,student_id=env.students['a']['student_id'],
                other_student_id=env.students['b']['student_id'],teacher=token,other=env.tokens['t2'],admin=env.tokens['admin'],
                output=str(ROOT/'output/playwright/course_workspace_20260921'))
            if '--batch' in sys.argv:
                second=env.records.create_video_task(dict(account_session_token=token,channel_id='channel_1',
                    session_id='review-qa',course_id='review-qa',course_name='合成课堂 · 第二机位（验收数据）',
                    uploader_name='合成复核员',filename='second.mp4',byte_size=len(data),total_chunks=1))
                second_id=second['task_id']
                env.records.append_video_chunk(dict(account_session_token=token,task_id=second_id,chunk_index=0,
                    content_base64=base64.b64encode(data).decode()))
                claim=env.records.claim_next_video_analysis()
                env.records.finish_video_analysis(second_id,process_video_task(claim,Path(claim['analysis_dir'])))
                second_ws=env.identity.workspace(token,second_id)
                from src.rehab_affect.video_applicability import ApplicabilityStore
                gate=ApplicabilityStore(env.records);state=gate.workspace(token,second_id)
                gate.save(token,dict(task_id=second_id,version=state['version'],revision=state['revision'],category='special',
                    goal='合成第二机位目标',reason='合成验收资料已由测试流程明确确认',confirmed=True))
                env.identity.save_binding(token,dict(task_id=second_id,frame_key=second_ws['frames'][0]['frame_key'],
                    frame_revision=second_ws['frame_revision'],role='student',student_id=env.students['a']['student_id'],
                    bbox=dict(x=.1,y=.2,width=.2,height=.6)))
                config.update(second_task_id=second_id,output=str(ROOT/'output/playwright/batch_review_20260921'))
            child=dict(os.environ)
            child.pop('REHAB_DEMO2_DOSSIER_KEY',None)
            child['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
            script=Path(__file__).with_name('qa_batch_review_20260921.js') if '--batch' in sys.argv else Path(__file__).with_suffix('.js')
            if '--support' in sys.argv:
                script=Path(__file__).with_name('qa_support_20260928.js')
                config['output']=str(ROOT/'output/playwright/support_20260928')
            if '--safety' in sys.argv:
                owner_context=env.records.account_school_context(token)['context']
                env.records.save_account_school_context(env.tokens['t2'],owner_context)
                config['reviewer_id']=env.records.account_from_session(env.tokens['t2'])['account_id']
                script=Path(__file__).with_name('qa_safety_20260929.js')
                config['output']=str(ROOT/'output/playwright/safety_20260929')
            if '--applicability' in sys.argv:
                script=Path(__file__).with_name('qa_applicability_20260929.js')
                config['output']=str(ROOT/'output/playwright/applicability_20260929')
            result=subprocess.run(['node',str(script)],input=json.dumps(config),
                text=True,encoding='utf8',cwd=ROOT,env=child,timeout=180)
            return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
