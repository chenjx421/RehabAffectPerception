import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location("refresh", Path(__file__).resolve().parents[1] / "scripts/cloud_refresh_observation.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "state.sqlite"
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db
    with connect() as db:
        db.executescript("""
        CREATE TABLE demo2_observation_jobs(job_id TEXT PRIMARY KEY,status TEXT,result_json TEXT,
          normalized_json TEXT,error_code TEXT,updated_at REAL,model TEXT);
        CREATE TABLE demo2_observation_person_links(job_id TEXT);
        INSERT INTO demo2_observation_jobs VALUES('job','ready','{"old":true}','{}','',1,'old-model');
        """)
        expected = dict(db.execute("SELECT * FROM demo2_observation_jobs").fetchone())
    store = SimpleNamespace(records=SimpleNamespace(_connect=connect),
                            _current=lambda db, row: {},
                            _normalize=lambda task, job, result: {"normalized": result})
    return store, expected, tmp_path / "archive.json"


def test_replace_preserves_previous_in_private_archive(state):
    store, expected, archive = state
    MODULE.publish(store, expected, {"new": True}, archive)
    assert json.loads(archive.read_text())["previous_job"] == expected
    with store.records._connect() as db:
        assert json.loads(db.execute("SELECT result_json FROM demo2_observation_jobs").fetchone()[0]) == {"new": True}


@pytest.mark.parametrize("mutation", ["UPDATE demo2_observation_jobs SET updated_at=2",
    "UPDATE demo2_observation_jobs SET status='running'",
    "INSERT INTO demo2_observation_person_links VALUES('job')"])
def test_concurrent_change_or_existing_link_blocks_replacement(state, mutation):
    store, expected, archive = state
    with store.records._connect() as db:
        db.execute(mutation)
    with pytest.raises(ValueError):
        MODULE.publish(store, expected, {"new": True}, archive)
    assert not archive.exists()
    with store.records._connect() as db:
        assert json.loads(db.execute("SELECT result_json FROM demo2_observation_jobs").fetchone()[0]) == {"old": True}


def test_invalid_result_does_not_discard_old(state):
    store, expected, archive = state
    def reject(*args):
        raise ValueError("invalid")
    store._normalize = reject
    with pytest.raises(ValueError):
        MODULE.publish(store, expected, {}, archive)
    assert not archive.exists()


def test_archive_collision_prevents_write(state):
    store, expected, archive = state
    archive.write_text("prior")
    with pytest.raises(FileExistsError):
        MODULE.publish(store, expected, {}, archive)
    with store.records._connect() as db:
        assert db.execute("SELECT updated_at FROM demo2_observation_jobs").fetchone()[0] == 1


def test_reviewed_candidate_matches_exact_evidence_and_bytes(tmp_path):
    folder = tmp_path / 'reviewed'
    folder.mkdir()
    candidate = folder / 'candidate.private.json'
    raw = b'{"frames":[]}'
    candidate.write_bytes(raw)
    (folder / 'input-manifest.private.json').write_text('[{"image_sha256":"a"}]')
    digest = hashlib.sha256(raw).hexdigest()
    manifest = [{'image_sha256': 'a'}]
    assert MODULE.load_reviewed_candidate(candidate, digest, manifest, tmp_path) == {'frames': []}
    for wrong_digest, wrong_manifest in [('f' * 64, manifest), (digest, [])]:
        with pytest.raises(ValueError):
            MODULE.load_reviewed_candidate(candidate, wrong_digest, wrong_manifest, tmp_path)
    with pytest.raises(ValueError):
        MODULE.load_reviewed_candidate(candidate, digest, manifest, tmp_path / 'other')


def test_reviewed_candidate_rejects_linked_manifest(tmp_path):
    folder = tmp_path / 'reviewed'
    folder.mkdir()
    candidate = folder / 'candidate.private.json'
    candidate.write_bytes(b'{}')
    source = tmp_path / 'manifest.json'
    source.write_text('[]')
    import os
    os.link(source, folder / 'input-manifest.private.json')
    with pytest.raises(ValueError, match='invalid_reviewed_candidate'):
        MODULE.load_reviewed_candidate(candidate, hashlib.sha256(b'{}').hexdigest(), [], tmp_path)


def test_publish_audited_model_input_is_atomic_with_result(state):
    store, expected, archive = state
    with store.records._connect() as db:
        db.execute('CREATE TABLE demo2_observation_inputs(job_id TEXT PRIMARY KEY,result_sha256 TEXT,input_manifest_json TEXT,created_at REAL)')
    manifest = [{'frame_key': 'f1', 'image_sha256': 'a' * 64}]
    store._input_manifest = lambda task, job, value: json.dumps(value)
    MODULE.publish(store, expected, {'new': True}, archive, input_manifest=manifest)
    with store.records._connect() as db:
        raw = db.execute('SELECT result_json FROM demo2_observation_jobs').fetchone()[0]
        audited = db.execute('SELECT * FROM demo2_observation_inputs').fetchone()
        assert audited['result_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
        assert json.loads(audited['input_manifest_json']) == manifest
