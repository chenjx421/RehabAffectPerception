"""Scheduled safety retention against isolated SQLite and synthetic ciphertext."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

from rehab_affect import demo2_safety as module


NOW = '2026-10-16T12:00:00+00:00'
PAST = '2026-10-16T11:59:59+00:00'
FUTURE = '2026-10-16T12:00:01+00:00'


@pytest.fixture
def retention(tmp_path, monkeypatch):
    database = tmp_path / 'safety.sqlite3'

    @contextmanager
    def connect():
        db = sqlite3.connect(database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    records = SimpleNamespace(upload_dir=tmp_path / 'documents', _connect=connect)
    store = module.SafetyStore(records)
    monkeypatch.setattr(module, '_iso', lambda: NOW)

    def forbidden(*args, **kwargs):
        raise AssertionError('Maintenance must not authenticate or decrypt')

    monkeypatch.setattr(store, '_account', forbidden)
    monkeypatch.setattr(store.vault, 'open', forbidden)
    monkeypatch.setattr(store.vault, 'seal', forbidden)
    ciphertext = Fernet(Fernet.generate_key()).encrypt(b'SYNTHETIC SAFETY EVENT ONLY')
    return SimpleNamespace(store=store, connect=connect, ciphertext=ciphertext, root=tmp_path)


def insert(env, identifier, expires_at, status='pending'):
    with env.connect() as db:
        db.execute('INSERT INTO demo2_safety_events VALUES (?,?,?,?,?,?,?,?,?)',
                   (identifier, 'fictional-owner-' + identifier, '', 'synthetic-task',
                    '{}', status, 1, expires_at, env.ciphertext))


def rows(env):
    with env.connect() as db:
        return db.execute('SELECT * FROM demo2_safety_events ORDER BY id').fetchall()


def test_scheduled_cleanup_commits_without_visits_or_keys_and_preserves_other_data(retention):
    env = retention
    for index, status in enumerate(module.STATES):
        insert(env, str(index), PAST, status)
    insert(env, 'boundary', NOW)
    insert(env, 'future', FUTURE)
    future = [row for row in rows(env) if row[0] == 'future']
    media = env.root / 'synthetic-source.mp4'
    media.write_bytes(b'SYNTHETIC MEDIA SENTINEL')
    with env.connect() as db:
        db.execute('CREATE TABLE other_private_records (body BLOB NOT NULL)')
        db.execute('INSERT INTO other_private_records VALUES (?)', (env.ciphertext,))
    assert env.store.cleanup_expired() == {'deleted_count': 6, 'remaining_count': 1}
    assert rows(env) == future  # A separate connection sees the committed deletion.
    assert env.store.cleanup_expired() == {'deleted_count': 0, 'remaining_count': 1}
    assert media.read_bytes() == b'SYNTHETIC MEDIA SENTINEL'
    with env.connect() as db:
        assert db.execute('SELECT body FROM other_private_records').fetchone()[0] == env.ciphertext


@pytest.mark.parametrize('deadline,deleted', [
    ('2026-10-16T19:00:00+08:00', 1),
    ('2026-10-16T20:00:00+08:00', 1),
    ('2026-10-16T08:00:00-05:00', 0),
    ('2026-10-16T12:00:01Z', 0),
])
def test_expiry_compares_instants_not_timestamp_strings(retention, deadline, deleted):
    insert(retention, 'event', deadline)
    assert retention.store.cleanup_expired() == {'deleted_count': deleted, 'remaining_count': 1 - deleted}


def test_request_cleanup_and_scheduled_cleanup_share_the_same_boundary(retention):
    insert(retention, 'expired', NOW)
    insert(retention, 'future', FUTURE)
    with retention.connect() as db:
        assert retention.store._cleanup(db) == 1
    assert retention.store.cleanup_expired() == {'deleted_count': 0, 'remaining_count': 1}


def test_cleanup_failure_rolls_back_and_can_be_retried(retention):
    insert(retention, 'first', PAST)
    insert(retention, 'second', PAST)
    before = rows(retention)
    with retention.connect() as db:
        db.execute('''CREATE TRIGGER block_safety_delete BEFORE DELETE ON demo2_safety_events
                      WHEN OLD.id = 'second' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END''')
    with pytest.raises(sqlite3.IntegrityError):
        retention.store.cleanup_expired()
    assert rows(retention) == before
    with retention.connect() as db:
        db.execute('DROP TRIGGER block_safety_delete')
    assert retention.store.cleanup_expired() == {'deleted_count': 2, 'remaining_count': 0}


def test_concurrent_scheduled_sweeps_do_not_double_count_deletions(retention):
    for index in range(8):
        insert(retention, str(index), PAST)
    insert(retention, 'future', FUTURE)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: retention.store.cleanup_expired(), range(2)))
    assert sorted(result['deleted_count'] for result in results) == [0, 8]
    assert all(result['remaining_count'] == 1 for result in results)
    assert len(rows(retention)) == 1
