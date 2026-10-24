from pathlib import Path
from http.server import ThreadingHTTPServer
from threading import Thread
from http.client import HTTPConnection
import json
import pytest

from rehab_affect import scenario_lab_server as server
from rehab_affect import demo2_manager_gateway as gateway
from test_demo2_evaluation_store import env, payload


@pytest.fixture
def http_env(env,monkeypatch):
    monkeypatch.setattr(server,'get_demo2_student_store',lambda:env.records)
    handler=server.create_handler(scenario_dir=Path('configs/scenarios'),model_path=server.DEFAULT_LEARNED_POLICY_PATH,policy_name='rule')
    http=ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=Thread(target=http.serve_forever,daemon=True);thread.start()
    def request(path,method='GET',data=None,user='t1',headers=None):
        outgoing={'Content-Type':'application/json','Connection':'close'}
        if user:outgoing['Cookie']='rehab_demo2_session='+env.tokens[user]
        outgoing.update(headers or {})
        conn=HTTPConnection('127.0.0.1',http.server_port,timeout=10)
        try:
            conn.request(method,path,body=json.dumps(data).encode() if data is not None else None,headers=outgoing)
            response=conn.getresponse();raw=response.read()
            return response.status,dict(response.getheaders()),json.loads(raw) if 'json' in response.getheader('Content-Type','') else raw
        finally:conn.close()
    yield request
    http.shutdown();http.server_close();thread.join(3)


def test_live_api_save_preview_reload_and_access(http_env):
    request=http_env;api='/api/v1/demo2/evaluations'
    assert request(api,user=None)[0]==401
    assert request(api,user='admin')[0]==403
    status,headers,ws=request(api)
    assert status==200 and 'no-store' in headers['Cache-Control']
    assert len(ws['workspace']['templates'])==2
    assert request(api+'/preview','POST',payload())[2]['result']['comparison']['total_delta']==-1
    assert request(api)[2]['workspace']['records']==[]
    saved=request(api,'POST',payload())[2]['record']
    assert saved['version']==1
    assert request(api)[2]['workspace']['records'][0]['result']['school']['score_10']==8
    assert request(api,user='t2')[2]['workspace']['records']==[]
    assert request(api,'POST',payload())[0]==409
    assert request(api,'POST',payload(record_id='cross'),headers={'Origin':'https://external.invalid'})[0]==403
    assert request(api,'POST',payload(),headers={'Content-Type':'text/plain'})[0]==415
    assert request(api,'POST',payload(reviewed='true'))[0]==400
    assert request(api+'/withdraw','POST',dict(record_id='fixture-1',expected_version=1,reason='合成验收撤销'))[0]==200
    assert request(api)[2]['workspace']['records']==[]


def test_gateway_admits_only_intended_routes():
    assert '/demo2/evaluation' in gateway._PAGES
    assert '/api/v1/demo2/evaluations' in gateway._GET_API
    assert {'/api/v1/demo2/evaluations','/api/v1/demo2/evaluations/preview','/api/v1/demo2/evaluations/withdraw'} <= gateway._POST_API
    assert '/api/v1/demo2/evaluations/delete' not in gateway._POST_API
    assert '/api/v1/demo2/course-analysis/report' in gateway._GET_API
