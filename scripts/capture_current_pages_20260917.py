"""Capture current UI in a disposable database, with explicitly synthetic data."""
import base64
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from scripts.qa_demo2_dossier_20260911 import isolated_dossier_server, authorization_payload, document_payload, day
from src.rehab_affect.demo2_media_analysis import _resolve_tool, process_video_task
from src.rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from src.rehab_affect.demo2_measurement_store import Demo2MeasurementStore

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/playwright/current_pages_20260917'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rehab-guide-') as temporary:
        with isolated_dossier_server(Path(temporary)) as env:
            env.membership._sms_sender = None
            # Use the real detector module; the guide never invokes fixture AI.
            env.server.importlib = SimpleNamespace(import_module=importlib.import_module)
            token = env.tokens['t1']
            frame = env.identity.workspace(token, env.task_ids['t1'])
            frame_path, _ = env.identity.frame_file(token, env.task_ids['t1'], frame['frames'][0]['frame_key'], frame['frame_revision'])
            video = Path(temporary) / 'synthetic_class.mp4'
            subprocess.run([str(_resolve_tool('ffmpeg')), '-y', '-loop', '1', '-i', str(frame_path),
                            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000', '-t', '6', '-r', '12',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(video)],
                           check=True, capture_output=True, timeout=45)
            raw = video.read_bytes()
            task = env.records.create_video_task(dict(account_session_token=token, account_id=env.accounts['t1']['account_id'],
                channel_id='channel_1',session_id='synthetic-guide', course_id='synthetic-guide',course_name='合成演示课堂 · 非真实教学',
                uploader_name='演示复核员',filename='synthetic_class.mp4',mime_type='video/mp4',byte_size=len(raw),total_chunks=1))
            tid = task['task_id']
            env.records.append_video_chunk(dict(account_session_token=token,task_id=tid,chunk_index=0,content_base64=base64.b64encode(raw).decode()))
            claim = env.records.claim_next_video_analysis()
            result = process_video_task(claim, Path(claim['analysis_dir']))
            env.records.finish_video_analysis(tid, result)
            ws = env.identity.workspace(token,tid)
            binding = dict(task_id=tid,frame_key=ws['frames'][0]['frame_key'],frame_revision=ws['frame_revision'],role='student',
                           student_id=env.students['a']['student_id'],bbox=dict(x=.15,y=.2,width=.2,height=.6))
            env.identity.save_binding(token,binding)
            auth = env.dossier.save_authorization(token,authorization_payload(env))
            dp = document_payload(env,auth)
            dp['summary'] = dict(learning_goals='合成示例：在三次机会中按约定支持完成物品分类。',
                                support_methods='合成示例：一步指令、实物与图卡选择、充分等待。',
                                safety_notes='合成示例：降低刺激，不强迫眼神接触。',professional_conclusion='无真实诊断，仅演示资料版本与权限。')
            doc = env.dossier.create_document(token,dp)
            env.dossier.create_reference(token,dict(task_id=tid,student_id=env.students['a']['student_id'],frame_revision=ws['frame_revision'],document_ids=[doc['document_id']],confirmed=True))
            measures = Demo2MeasurementStore(env.records)
            for n in range(3):
                measures.save(token,dict(record_id=f'guide-measure-{n}',expected_version=0,student_id=env.students['a']['student_id'],
                    lesson_date=day(-14+n*7),lesson_id=f'synthetic-{n}',course_name='合成生活数学课',goal_id='物品分类',
                    measurement_context='实物支持与一步指令',criterion='三次机会中至少两次按约定支持完成',
                    scores=dict(accuracy=6+n,independence=5+n,consistency=6,transfer=4+n),opportunities=3,observed=3,
                    reviewed=True,evidence='合成观察记录，用于演示趋势，不代表真实学生进步。',source_type='classroom_observation'))
            config = dict(base=f'http://127.0.0.1:{env.port}',tokens={'teacher':token,'admin':env.tokens['admin']},
                          task_id=tid,student_id=env.students['a']['student_id'],output=str(OUT))
            child = dict(os.environ)
            child.pop('REHAB_DEMO2_DOSSIER_KEY',None)
            child['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
            completed = subprocess.run(['node',str(Path(__file__).with_suffix('.js'))], input=json.dumps(config),
                                       text=True,encoding='utf8',cwd=ROOT,env=child,timeout=360)
            return completed.returncode


if __name__=='__main__':
    raise SystemExit(main())
