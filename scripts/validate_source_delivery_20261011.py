"""Exercise the delivered code in an isolated new installation, not the live DB."""
import json, os, shutil, socket, subprocess, tempfile, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'outputs/delivery_20261011/RehabAffect_Demo2_Source_20261011'
PYTHON='D:/anaconda3/python.exe'
report={'date':'2026-10-11','scope':'isolated delivered source; no production data','checks':{}}
with tempfile.TemporaryDirectory(prefix='demo2-source-') as tmp:
    work=Path(tmp)/'source';shutil.copytree(STAGE/'source',work)
    env=dict(os.environ)
    for key in list(env):
        if key.startswith('REHAB_'):env.pop(key)
    env['PYTHONPATH']=str(work)+os.pathsep+str(work/'src');env['PYTHONIOENCODING']='utf-8'
    init=subprocess.run([PYTHON,'initialize_local.py'],cwd=work,env=env,capture_output=True,text=True,encoding='utf8',timeout=50)
    if init.returncode:raise RuntimeError(init.stderr)
    passwords={line.split()[0]:line.split()[1] for line in init.stdout.splitlines() if line.split() and line.split()[0] in ['t1','t2','t3','t4','admin']}
    assert len(passwords)==5;report['checks']['fresh_database_and_random_accounts']=True
    repeat=subprocess.run([PYTHON,'initialize_local.py'],cwd=work,env=env,capture_output=True,timeout=30)
    assert repeat.returncode!=0;report['checks']['refuses_existing_database']=True
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (Path(tmp)/'server.log').open('wb') as log:
        process=subprocess.Popen([PYTHON,'-m','src.rehab_affect.scenario_lab_server','--host','127.0.0.1','--port',str(port),'--policy','rule'],cwd=work,env=env,stdout=log,stderr=log)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(50):
                try:
                    with urllib.request.urlopen(base+'/demo2/login',timeout=2) as r:assert r.status==200
                    break
                except Exception:time.sleep(.4)
            else:raise RuntimeError('Packaged server did not start')
            report['checks']['clean_server_login_page']=True
            for user,password in passwords.items():
                data=json.dumps({'username':user,'password':password,'role':'company_admin' if user=='admin' else 'school_uploader'}).encode()
                request=urllib.request.Request(base+'/api/v1/demo2/auth/login',data=data,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=15) as response:
                    assert response.status==200
                    cookie=response.headers['Set-Cookie'].split(';')[0]
                request=urllib.request.Request(base+('/demo2/admin' if user=='admin' else '/demo2/upload'),headers={'Cookie':cookie})
                with urllib.request.urlopen(request,timeout=15) as response:assert response.status==200
            report['checks']['five_new_accounts_and_workspaces']=True
        finally:process.terminate();process.wait(timeout=20)
    result=subprocess.run([PYTHON,'-m','pytest','tests/test_classroom_rubric.py','tests/test_evaluation_reference_context.py','-q','-p','no:cacheprovider'],cwd=work,env=env,capture_output=True,text=True,encoding='utf8',timeout=180)
    report['tests']={'command':'python -m pytest tests/test_classroom_rubric.py tests/test_evaluation_reference_context.py -q -p no:cacheprovider','exit_code':result.returncode,'output':result.stdout[-3000:]}
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
report['passed']=True
(STAGE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
