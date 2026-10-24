from pathlib import Path
import cloud_e2e_acceptance as base

origin='http://127.0.0.1:8793'
task='ff08fa906e044259a1fe10dc49aaf5a2'
schools,_=base.load_credentials(Path('/var/lib/rehabaffect/acceptance-private/schools.private.md'),Path('/var/lib/rehabaffect/acceptance-private/admin.private.json'))
c=base.Client(origin);c.login(schools[0],'school_uploader')
p=c.json(base.route('/observations',task_id=task))['workspace']
i=c.json(base.route('/identity/workspace',task_id=task))['workspace']
import sqlite3, importlib.util
with sqlite3.connect('file:/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    t=dict(db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?',(task,)).fetchone())
spec=importlib.util.spec_from_file_location('rehab_affect._debug_analysis','/opt/rehabaffect-candidate-students-20261021/src/rehab_affect/demo2_course_analysis.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ins=m.build_student_insights(p,i,t,{})
from rehab_affect.student_record_store import Demo2StudentRecordStore
from rehab_affect.demo2_identity_store import Demo2IdentityStore
records=Demo2StudentRecordStore(db_path=Path('/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3'), upload_dir=Path('/var/lib/rehabaffect/seewo_demo2/uploads')); ids=Demo2IdentityStore(records)
indexed=ids._frames(t)
from rehab_affect.demo2_face_detection import detect_faces
face_counts=[]; face_errors=[]
for f in list(indexed.values())[:8]:
    try: face_counts.append(len(detect_faces(f.get('path') or f.get('relative_image')).get('faces',[])))
    except Exception as e: face_counts.append(-1);face_errors.append(type(e).__name__+':'+str(e)[:80])
def summary(v):
    return {k:(len(x) if isinstance(x,(list,dict)) else x) for k,x in v.items() if k in ('status','task_id','job_id','source_sha256','frame_revision','owner_account_id','scope_key','media_available','ready','samples','observations','frames','bindings','students','result')}
print({'public':summary(p),'identity':summary(i),'task':{k:t.get(k) for k in ('task_id','account_id','sha256')},'frame_keys':list(next(iter(indexed.values())).keys()),'face_counts':face_counts,'face_errors':face_errors,'first_sample':p.get('samples',[{}])[0],'first_observation':p.get('observations',[{}])[0],'first_frame':i.get('frames',[{}])[0],'insight':{k:(len(v) if isinstance(v,(list,dict)) else v) for k,v in ins.items() if k in ('ready','task_id','source_sha256','frame_revision','job_id','summary','students','anonymous_people')}})
