import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location('pdf_acceptance',
    Path(__file__).resolve().parents[1] / 'scripts/build_cloud_acceptance_pdf_20261020.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.mark.parametrize('value', [None, {}, {'ok':True}, {'status':'passed'},
    {'ok':True,'large_upload':{'sha256_verified':True},'analysis':{}},
    {'status':'passed','checks':[{'name':'worker_ready','passed':True}]}])
def test_upload_success_never_implies_worker_completion(value):
    assert builder.worker_verdict(value)[0] == '待验收'


def test_actual_public_report_schema_requires_every_final_check():
    value = {'ok':True,'large_upload':{'sha256_verified':True},'analysis':{
        'seconds_including_queue':366.563,'technical_report_available':True,
        'admin_report_download':True,'admin_media_range':True}}
    assert builder.worker_verdict(value)[0] == '已通过'
    assert '视频处理摘要可用、后台报告下载与视频读取检查通过' in builder.worker_verdict(value)[1]
    assert 'frame' not in builder.worker_verdict(value)[1]
    for field in ('technical_report_available','admin_report_download','admin_media_range'):
        changed = {**value,'analysis':{**value['analysis'],field:False}}
        assert builder.worker_verdict(changed)[0] == '待验收'


def test_partial_final_json_is_pending(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text('{"ok":true,"analysis":')
    assert builder.read_json(path) is None
    assert builder.worker_verdict(builder.read_json(path))[0] == '待验收'


def test_explicit_failure_overrides_positive_upload():
    assert builder.worker_verdict({'ok':False,'large_upload':{'sha256_verified':True}})[0] == '未通过 / 待复验'
