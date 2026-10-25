"""Server maintenance wiring without opening sockets or touching live stores."""
from types import SimpleNamespace

import pytest

from src.rehab_affect import demo2_media_worker, demo2_safety
from src.rehab_affect import scenario_lab_server as server
from test_demo2_dossier_api import rig


class TwoSweeps:
    def __init__(self):
        self.waits = []

    def is_set(self):
        return len(self.waits) == 2

    def wait(self, timeout):
        self.waits.append(timeout)


@pytest.mark.parametrize('failure', [None, 'Dossier', 'Safety', 'both'])
def test_sweeps_fail_independently_and_retry_without_sensitive_logs(failure, capsys):
    calls = []

    def callback(name):
        def cleanup():
            calls.append(name)
            if calls.count(name) == 1 and failure in (name, 'both'):
                raise RuntimeError('private-ciphertext-path-and-key')
        return cleanup

    worker = server._DossierMaintenance(callback('Dossier'), safety_cleanup=callback('Safety'))
    worker.stopped = TwoSweeps()
    worker._run()  # Exercise the real loop synchronously; no thread or service starts.
    assert calls == ['Dossier', 'Safety', 'Dossier', 'Safety']
    assert all(0 <= timeout <= 30 for timeout in worker.stopped.waits)
    error = capsys.readouterr().err
    assert 'private-ciphertext-path-and-key' not in error
    for name in ('Dossier', 'Safety'):
        assert (f'{name} cleanup unavailable' in error) == (failure in (name, 'both'))


def test_safety_cleanup_can_run_without_dossier_callback():
    calls = []
    worker = server._DossierMaintenance(None, safety_cleanup=lambda: calls.append('safety'))
    worker.stopped = TwoSweeps()
    worker._run()
    assert calls == ['safety', 'safety']


def test_handler_safety_callback_uses_captured_records_and_recovers_from_initialization_failure(monkeypatch, tmp_path):
    records, calls = object(), []
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: records)
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / 'unused', policy_name='rule')

    def make_safety(actual):
        assert actual is records
        calls.append(actual)
        if len(calls) == 1:
            raise RuntimeError('synthetic unavailable store')
        return SimpleNamespace(cleanup_expired=lambda: {'deleted_count': 2, 'remaining_count': 3})

    monkeypatch.setattr(demo2_safety, 'SafetyStore', make_safety)
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: pytest.fail('must not look up another store'))
    with pytest.raises(RuntimeError):
        handler.cleanup_expired_safety()
    assert handler.cleanup_expired_safety() == {'deleted_count': 2, 'remaining_count': 3}
    assert len(calls) == 2


def test_server_registers_both_callbacks_in_existing_maintenance_lifecycle(monkeypatch):
    events = []
    dossier, safety = object(), object()

    def dossier_cleanup():
        return dossier

    def safety_cleanup():
        return safety

    class Retention:
        ident = None

        def __init__(self, **kwargs):
            pass

        def start(self):
            events.append('retention_start')
            self.ident = 1

        def join(self, **kwargs):
            events.append('retention_join')

    class Maintenance:
        def __init__(self, cleanup, *, safety_cleanup):
            assert cleanup() is dossier and safety_cleanup() is safety

        def start(self):
            events.append('maintenance_start')

        def stop(self):
            events.append('maintenance_stop')

    class Listener:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            events.append('serve')

        def server_close(self):
            events.append('close')

    monkeypatch.setattr(server, 'create_handler', lambda **kwargs: SimpleNamespace(
        cleanup_expired_dossiers=dossier_cleanup, cleanup_expired_safety=safety_cleanup))
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: object())
    monkeypatch.setattr(server, 'Thread', Retention)
    monkeypatch.setattr(server, '_DossierMaintenance', Maintenance)
    monkeypatch.setattr(server, 'ThreadingHTTPServer', Listener)
    monkeypatch.setattr(demo2_media_worker, 'VideoAnalysisWorker', lambda records: SimpleNamespace(
        start=lambda: events.append('worker_start'), stop=lambda: events.append('worker_stop')))
    monkeypatch.setenv('REHAB_DEMO2_MEDIA_WORKER', '1')
    server.run_server(port=0)
    assert events == ['retention_start', 'maintenance_start', 'worker_start', 'serve',
                      'worker_stop', 'maintenance_stop', 'retention_join', 'close']


@pytest.mark.parametrize('user,expected', [('teacher', 410), ('admin', 410), ('member', 403), (None, 401)])
def test_exact_legacy_aggregator_is_blocked_before_loading(rig, monkeypatch, user, expected):
    def forbidden(**kwargs):
        pytest.fail('retired aggregator must never load legacy data')

    monkeypatch.setattr(server, 'load_seewo_demo2', forbidden)
    assert server._is_retired_legacy_data_path('/api/seewo_student_demo2')
    status, _, body = rig.request('/api/seewo_student_demo2?force=1', user=user)
    assert status == expected
    if expected == 410:
        assert body['error']['code'] == 'legacy_data_reimport_required'
