"""Reproduce and privately inspect an existing candidate's EXACT image inputs.

Run locally on the authorized cloud host; never invokes the observation model:
  python scripts/cloud_review_candidate_frames.py --candidate-dir /var/lib/rehabaffect/acceptance-private/CANDIDATE \
    --task-id TASK --source-sha256 SHA256 --output /var/lib/rehabaffect/acceptance-private/candidate-frame-review

REHAB_DEMO2_DB_PATH (or --db-path) must name an existing DB under
/var/lib/rehabaffect. SQLite is opened mode=ro, query_only, with write operations
denied. No store constructors, migrations, audit writes, login, upload, publish,
provider configuration, or network requests. The existing bounded frame loader
can perform local FFmpeg extraction and offline face proposals.

candidate.private.json and input-manifest.private.json must be private, complete,
and consistent with the current ready job. Both fresh loader manifests must
match EVERY saved field, list entry and JSON value type, including derived and
model image hashes, high_quality metadata, and normalized_to_evidence. A
different extraction result is refused, never substituted as the actual input.

Output is UNMASKED and private: exact evidence bytes, exact actual-model-input
bytes, available verified unannotated color bytes, and canonical prediction
contact sheets. Existing region numbers are already part of the model input;
the contact sheet adds Oxx prediction labels, not identity or accuracy claims.
Exit 0 certifies reproduction/export only, NOT observed-action effectiveness.

Offline verification: python scripts/cloud_review_candidate_frames.py --self-test
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Lock
import time

import cloud_observation_effectiveness as effect


DATA_ROOT = Path('/var/lib/rehabaffect')
PRIVATE_ROOT = DATA_ROOT / 'acceptance-private'
MAX_JSON_BYTES = 512 * 1024


def require(condition, code):
    effect.require(condition, code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate_json_field')
        value[key] = item
    return value


def load_json(path):
    path = Path(path)
    effect.no_links(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        import stat
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_JSON_BYTES,
                'unsafe_candidate_file')
        if os.name == 'posix':
            require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_candidate_permissions')
        raw = stream.read(MAX_JSON_BYTES + 1)
    require(len(raw) <= MAX_JSON_BYTES, 'candidate_file_too_large')
    value = json.loads(raw, object_pairs_hook=unique_object,
                       parse_constant=lambda _: effect.require(False, 'invalid_json_number'))
    return value, hashlib.sha256(raw).hexdigest()


@contextmanager
def readonly_connection(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        if hasattr(sqlite3, 'SQLITE_RECURSIVE'):
            allowed.add(sqlite3.SQLITE_RECURSIVE)
        connection.set_authorizer(lambda action, *_args: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        deadline = time.monotonic() + 15
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        yield connection
    finally:
        connection.close()


def readonly_records_type(parent):
    class ReadOnlyRecords(parent):
        def __init__(self, path):
            self.db_path = Path(path)
            self.video_task_dir = self.db_path.parent / 'video_tasks'
            self.upload_dir = self.db_path.parent / 'student_documents'

        def _connect(self):
            return readonly_connection(self.db_path)

    return ReadOnlyRecords


def backend(db_path):
    # Deliberately bypass constructors that create tables or update DB settings.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from rehab_affect.student_record_store import Demo2StudentRecordStore
    from rehab_affect.demo2_identity_store import Demo2IdentityStore
    from rehab_affect.demo2_observation_store import Demo2ObservationStore
    from cloud_observation_frames import load_job_frames, assert_current
    records = readonly_records_type(Demo2StudentRecordStore)(db_path)
    identities = object.__new__(Demo2IdentityStore)
    identities.record_store = records
    identities._frame_cache = OrderedDict()
    identities._frame_cache_entries = 0
    identities._frame_cache_lock = Lock()
    store = object.__new__(Demo2ObservationStore)
    store.records, store.identities = records, identities
    return records, identities, store, load_job_frames, assert_current


def current_job(records, store, task_id, source_hash, job_id=None):
    with records._connect() as db:
        rows = db.execute('SELECT * FROM demo2_observation_jobs WHERE task_id=? AND source_sha256=?',
                          (task_id, source_hash)).fetchall()
        require(len(rows) == 1 and rows[0]['status'] == 'ready', 'one_current_ready_job_required')
        expected = dict(rows[0])
        require(job_id is None or expected['job_id'] == job_id, 'job_id_mismatch')
        task = store._current(db, expected)
        selected = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_observation_targets'").fetchone():
            row = db.execute('SELECT student_ids_json FROM demo2_observation_targets WHERE task_id=? '
                'AND owner_account_id=? AND scope_key=? AND source_sha256=?',
                (task_id, expected['owner_account_id'], expected['scope_key'], source_hash)).fetchone()
            if row is not None:
                selected = json.loads(row[0])
    job = {**expected, 'frames': json.loads(expected['samples_json']), 'selected_student_ids': selected,
           'duration_sec': json.loads(task['processing_result_json'])['media']['duration_sec']}
    return expected, task, job


def validate_candidate(candidate, manifest, job):
    require(isinstance(candidate, dict) and candidate.get('schema_version') == 'visible_observation_v1',
            'unsupported_candidate_schema')
    for key in ('task_id', 'source_sha256', 'frame_revision'):
        require(candidate.get(key) == job[key], 'candidate_source_mismatch')
    require(candidate.get('identity_recognition_performed') is False
            and candidate.get('scoring_performed') is False
            and candidate.get('requires_teacher_review') is True, 'unsafe_candidate_scope')
    require(isinstance(manifest, list) and 1 <= len(manifest) <= 8, 'invalid_input_manifest')
    require(all(isinstance(row, dict) and effect.identifier(row.get('frame_key'))
                and effect.number(row.get('timestamp_sec')) and row['timestamp_sec'] >= 0 for row in manifest),
            'invalid_input_manifest')
    keys, times = [row['frame_key'] for row in manifest], [row['timestamp_sec'] for row in manifest]
    require(len(set(keys)) == len(keys) and all(a < b for a, b in zip(times, times[1:])), 'invalid_input_manifest')
    samples = sorted(job['frames'], key=lambda row: row.get('time_sec', row.get('timestamp_sec')))
    require(keys == [s['frame_key'] for s in samples]
            and times == [s.get('time_sec', s.get('timestamp_sec')) for s in samples], 'job_samples_mismatch')
    coverage, frames = candidate.get('coverage', {}), candidate.get('frames')
    require(coverage.get('scope') == 'sampled_frames_only' and coverage.get('continuous_coverage') is False
            and coverage.get('full_lesson') is False and coverage.get('sample_count') == len(manifest)
            and coverage.get('sample_timestamps_sec') == times, 'candidate_coverage_mismatch')
    require(isinstance(frames, list) and len(frames) == len(manifest)
            and [f.get('timestamp_sec') for f in frames] == times, 'candidate_timestamps_mismatch')
    for row, frame in zip(manifest, frames):
        require(row.get('source_sha256') == job['source_sha256'] and effect.sha256(row.get('image_sha256'))
                and effect.sha256(row.get('model_image_sha256')), 'manifest_provenance_missing')
        require(row.get('normalized_to_evidence') == {'scale_x': 1, 'scale_y': 1, 'offset_x': 0, 'offset_y': 0, 'crop': False},
                'unsupported_coordinate_transform')
        require(isinstance(row.get('high_quality'), dict), 'missing_high_quality_metadata')
        observations = frame.get('observations')
        require(isinstance(observations, list) and len(observations) <= 9, 'invalid_candidate_observations')
        require(all(isinstance(o, dict) and o.get('behavior') in effect.BEHAVIORS and 'bbox' in o
                    and (o['bbox'] is None or effect.bbox(o['bbox']) is not None) for o in observations),
                'invalid_candidate_observations')


def verify_frames(images, actual, expected, job):
    require(canonical(actual) == canonical(expected), 'input_manifest_mismatch')
    require(isinstance(images, list) and len(images) == len(expected), 'image_count_mismatch')
    for image, row in zip(images, expected):
        require(image.get('timestamp_sec') == row['timestamp_sec'], 'image_timestamp_mismatch')
        evidence = image.get('image_bytes')
        model = image.get('model_image_bytes', evidence)
        require(isinstance(evidence, bytes) and 0 < len(evidence) <= 1_500_000, 'invalid_evidence_bytes')
        require(isinstance(model, bytes) and 0 < len(model) <= 512 * 1024, 'invalid_model_input_bytes')
        require(hashlib.sha256(evidence).hexdigest() == row['image_sha256'], 'evidence_image_hash_mismatch')
        require(hashlib.sha256(model).hexdigest() == row['model_image_sha256'], 'model_image_hash_mismatch')
        effect.decode_image(evidence)
        effect.decode_image(model)
        cached = job.get('_observation_color_cache', {}).get('frames', {}).get(row['timestamp_sec'])
        if cached is not None and cached[0] is not None:
            require(hashlib.sha256(cached[0]).hexdigest() == row.get('derived_image_sha256'), 'derived_image_hash_mismatch')
            require(canonical(cached[1]) == canonical(row['high_quality']), 'derived_metadata_mismatch')


def render_pair(image, diagnostics, sample, output, index):
    Image, ImageDraw, ImageFont = effect.image_tools()
    # The shared renderer labels its left panel as a source frame; relabel the
    # fresh review canvas, never the exact exported model-input bytes.
    with tempfile.TemporaryDirectory(prefix='.render-', dir=output) as directory:
        directory = Path(directory)
        name = effect.render_pair(image, diagnostics, [], sample['frame_key'], sample['timestamp_sec'], directory, index)
        with Image.open(directory / name) as opened:
            sheet = opened.convert('RGB')
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((0, 30, sheet.width, 63), fill='white')
        try:
            font = ImageFont.load_default(size=16)
        except TypeError:
            font = ImageFont.load_default()
        draw.text((12, 36), 'ACTUAL MODEL INPUT (existing region IDs retained)', fill='black', font=font)
        draw.text((sheet.width // 2 + 6, 36), 'Canonical predictions on actual model input', fill='black', font=font)
        stream = io.BytesIO()
        sheet.save(stream, format='PNG')
        contact = 'actual-model-input-contact-%02d.png' % index
        effect.write_private(output / contact, stream.getvalue())
        effect.write_private(output / ('actual-model-input-overlay-%02d.png' % index),
                             (directory / ('effect-frame-%02d-overlay.png' % index)).read_bytes())
    return contact


def save_image(output, stem, data):
    suffix = '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg'
    name = stem + suffix
    effect.write_private(output / name, data)
    return name


def export_frames(output, candidate, manifest, images, job, candidate_hash, manifest_hash):
    rows = []
    for index, (sample, frame, image) in enumerate(zip(manifest, candidate['frames'], images), 1):
        evidence, model = image['image_bytes'], image.get('model_image_bytes', image['image_bytes'])
        evidence_file = save_image(output, 'original-evidence-%02d' % index, evidence)
        model_file = save_image(output, 'actual-model-input-%02d' % index, model)
        pixels = effect.decode_image(model)
        diagnostics, _ = effect.frame_diagnostics(frame, sample, pixels, [], [])
        contact = render_pair(pixels, diagnostics, sample, output, index)
        derived_file = None
        cached = job.get('_observation_color_cache', {}).get('frames', {}).get(sample['timestamp_sec'])
        if cached is not None and cached[0] is not None:
            derived_file = save_image(output, 'unannotated-derived-color-%02d' % index, cached[0])
        rows.append({'frame_key': sample['frame_key'], 'timestamp_sec': sample['timestamp_sec'],
            'evidence_file': evidence_file, 'actual_model_input_file': model_file, 'derived_color_file': derived_file,
            'actual_model_input_dimensions': [pixels.width, pixels.height],
            'image_sha256': sample['image_sha256'], 'model_image_sha256': sample['model_image_sha256'],
            'derived_image_sha256': sample.get('derived_image_sha256'), 'high_quality': sample['high_quality'],
            'contact_sheet': contact, **diagnostics})
    report = {'status': 'exact_candidate_inputs_reproduced_private_review_only',
              'task_id': job['task_id'], 'job_id': job['job_id'], 'source_sha256': job['source_sha256'],
              'frame_revision': job['frame_revision'], 'candidate_file_sha256': candidate_hash,
              'input_manifest_file_sha256': manifest_hash, 'manifest_all_fields_equal': True,
              'actual_input_hashes_verified': True, 'unmasked_private': True,
              'effectiveness_passed': None, 'accuracy': None, 'whole_lesson': False, 'published': False,
              'note': 'Original evidence may be grayscale. Actual model input may already contain region IDs; Oxx are candidate predictions. Geometry and input reproduction are not action or child-identity correctness.',
              'frames': rows}
    effect.write_json(output / 'input-manifest.private.json', manifest)
    effect.write_json(output / 'review.private.json', report)
    return report


def capture(records, identities, job, candidate, manifest, loader, assert_current):
    validate_candidate(candidate, manifest, job)
    images, actual = loader(records, identities, job)
    verify_frames(images, actual, manifest, job)
    assert_current(records, identities, job)
    again, after = loader(records, identities, job)
    verify_frames(again, after, manifest, job)
    return images


def live_paths(candidate_dir, db_path, output):
    require(os.name == 'posix', 'live_capture_requires_posix')
    paths = [Path(os.path.abspath(p)) for p in (candidate_dir, db_path, output)]
    candidate_dir, db_path, output = paths
    for path in paths:
        effect.no_links(path)
    require(candidate_dir.is_relative_to(PRIVATE_ROOT) and candidate_dir != PRIVATE_ROOT
            and output.is_relative_to(PRIVATE_ROOT) and output != PRIVATE_ROOT
            and not output.is_relative_to(candidate_dir), 'private_root_required')
    require(db_path.is_relative_to(DATA_ROOT) and db_path.is_file(), 'existing_cloud_db_required')
    require(candidate_dir.is_dir() and not candidate_dir.stat().st_mode & 0o077
            and candidate_dir.stat().st_uid == os.geteuid(), 'unsafe_candidate_directory')
    return candidate_dir, db_path, output


def self_test():
    import copy
    import unittest
    Image, ImageDraw, _ = effect.image_tools()

    def png(color):
        im = Image.new('RGB', (1280, 720), color)
        stream = io.BytesIO()
        im.save(stream, format='PNG')
        return stream.getvalue()

    evidence, color = png('#777777'), png('#157ea4')
    pixels = Image.open(io.BytesIO(color)).convert('RGB')
    ImageDraw.Draw(pixels).rectangle((256, 144, 512, 504), outline='yellow', width=3)
    stream = io.BytesIO()
    pixels.save(stream, format='PNG')
    model = stream.getvalue()
    digest = lambda data: hashlib.sha256(data).hexdigest()
    job = {'job_id': 'job-1', 'task_id': 'task-1', 'source_sha256': 'a' * 64, 'frame_revision': 'rev-1',
           'frames': [{'frame_key': 's0_f0', 'time_sec': 1.0}]}
    metadata = {'status': 'source_color', 'width': 1280, 'height': 720, 'requested_time_sec': 1.0}
    manifest = [{'frame_key': 's0_f0', 'timestamp_sec': 1.0, 'image_sha256': digest(evidence),
                 'model_image_sha256': digest(model), 'derived_image_sha256': digest(color),
                 'source_sha256': job['source_sha256'], 'high_quality': metadata,
                 'person_boxes': [], 'person_box_source': 'synthetic', 'identity_eligible': False,
                 'normalized_to_evidence': {'scale_x': 1, 'scale_y': 1, 'offset_x': 0, 'offset_y': 0, 'crop': False}}]
    candidate = {'schema_version': 'visible_observation_v1',
        **{k: job[k] for k in ('task_id', 'source_sha256', 'frame_revision')},
        'requires_teacher_review': True, 'identity_recognition_performed': False, 'scoring_performed': False,
        'coverage': {'scope': 'sampled_frames_only', 'sample_count': 1, 'sample_timestamps_sec': [1.0],
                     'continuous_coverage': False, 'full_lesson': False},
        'frames': [{'timestamp_sec': 1.0, 'observations': [{'behavior': 'standing',
            'bbox': {'x': .2, 'y': .2, 'width': .2, 'height': .5}}]}]}
    images = [{'timestamp_sec': 1.0, 'image_bytes': evidence, 'model_image_bytes': model}]

    class Checks(unittest.TestCase):
        def setUp(self):
            self.job = copy.deepcopy(job)
            self.job['_observation_color_cache'] = {'frames': {1.0: (color, copy.deepcopy(metadata))}}
            self.manifest, self.candidate, self.images = copy.deepcopy(manifest), copy.deepcopy(candidate), copy.deepcopy(images)
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)

        def capture(self, actual=None):
            loader = lambda *_args: (self.images, self.manifest if actual is None else actual)
            return capture(None, None, self.job, self.candidate, self.manifest, loader, lambda *_args: None)

        def test_exact_export_and_prediction_pixels(self):
            result = self.capture()
            output = effect.private_run(Path(self.temp.name) / 'private')
            report = export_frames(output, self.candidate, self.manifest, result, self.job, 'b' * 64, 'c' * 64)
            self.assertEqual((output / 'original-evidence-01.png').read_bytes(), evidence)
            self.assertEqual((output / 'actual-model-input-01.png').read_bytes(), model)
            self.assertEqual((output / 'unannotated-derived-color-01.png').read_bytes(), color)
            self.assertTrue(report['manifest_all_fields_equal'])
            self.assertIsNone(report['effectiveness_passed'])
            with Image.open(output / 'actual-model-input-overlay-01.png') as overlay:
                self.assertNotEqual(overlay.getpixel((255, 143)), pixels.getpixel((255, 143)))
            with Image.open(output / 'actual-model-input-contact-01.png') as contact:
                self.assertGreater(contact.width, 1280)
                self.assertEqual(contact.getpixel((20, 100)), pixels.getpixel((0, 0)))

        def test_every_manifest_field_matters(self):
            for key, replacement in [('derived_image_sha256', 'd' * 64), ('person_box_source', 'changed'),
                                     ('identity_eligible', True), ('high_quality', {'status': 'fallback'}),
                                     ('normalized_to_evidence', {'crop': True})]:
                actual = copy.deepcopy(self.manifest)
                actual[0][key] = replacement
                with self.subTest(field=key), self.assertRaisesRegex(effect.DiagnosticError, 'input_manifest_mismatch'):
                    self.capture(actual)

        def test_missing_or_extra_manifest_field_rejected(self):
            actual = copy.deepcopy(self.manifest)
            actual[0]['extra'] = True
            with self.assertRaisesRegex(effect.DiagnosticError, 'input_manifest_mismatch'):
                self.capture(actual)
            del actual[0]['extra']
            del actual[0]['derived_image_sha256']
            with self.assertRaisesRegex(effect.DiagnosticError, 'input_manifest_mismatch'):
                self.capture(actual)

        def test_actual_input_tamper_rejected(self):
            self.images[0]['model_image_bytes'] = color
            with self.assertRaisesRegex(effect.DiagnosticError, 'model_image_hash_mismatch'):
                self.capture()

        def test_evidence_tamper_rejected(self):
            self.images[0]['image_bytes'] = color
            with self.assertRaisesRegex(effect.DiagnosticError, 'evidence_image_hash_mismatch'):
                self.capture()

        def test_derived_color_tamper_rejected(self):
            self.job['_observation_color_cache']['frames'][1.0] = (evidence, metadata)
            with self.assertRaisesRegex(effect.DiagnosticError, 'derived_image_hash_mismatch'):
                self.capture()

        def test_wrong_task_rejected_before_loader(self):
            self.candidate['task_id'] = 'another-task'
            with self.assertRaisesRegex(effect.DiagnosticError, 'candidate_source_mismatch'):
                self.capture()

        def test_second_load_change_rejected(self):
            count = [0]
            def loader(*_args):
                count[0] += 1
                actual = copy.deepcopy(self.manifest)
                if count[0] == 2:
                    actual[0]['high_quality']['status'] = 'changed'
                return self.images, actual
            with self.assertRaisesRegex(effect.DiagnosticError, 'input_manifest_mismatch'):
                capture(None, None, self.job, self.candidate, self.manifest, loader, lambda *_args: None)

        def test_sqlite_no_writes_no_constructor(self):
            path = Path(self.temp.name) / 'synthetic.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE sample (value TEXT)')
                db.execute("INSERT INTO sample VALUES ('original')")
            db.close()
            before = path.read_bytes()
            class Parent:
                def __init__(self, *_args):
                    raise AssertionError('production constructor forbidden')
            records = readonly_records_type(Parent)(path)
            with records._connect() as db:
                self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0], 'original')
                for sql in ["UPDATE sample SET value='changed'", 'CREATE TABLE extra (id INT)', 'PRAGMA query_only=OFF']:
                    with self.assertRaises(sqlite3.DatabaseError):
                        db.execute(sql)
            self.assertEqual(path.read_bytes(), before)

        def test_manifest_json_value_type_mismatch(self):
            actual = copy.deepcopy(self.manifest)
            actual[0]['identity_eligible'] = 0
            with self.assertRaisesRegex(effect.DiagnosticError, 'input_manifest_mismatch'):
                self.capture(actual)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--candidate-dir')
    parser.add_argument('--task-id')
    parser.add_argument('--job-id')
    parser.add_argument('--source-sha256')
    parser.add_argument('--db-path', default=os.environ.get('REHAB_DEMO2_DB_PATH'))
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    output = None
    try:
        require(args.candidate_dir and args.db_path and args.output and effect.identifier(args.task_id)
                and effect.sha256(args.source_sha256), 'explicit_candidate_source_db_output_required')
        if args.job_id is not None:
            require(effect.identifier(args.job_id), 'invalid_job_id')
        candidate_dir, db_path, output_root = live_paths(args.candidate_dir, args.db_path, args.output)
        candidate, candidate_hash = load_json(candidate_dir / 'candidate.private.json')
        manifest, manifest_hash = load_json(candidate_dir / 'input-manifest.private.json')
        records, identities, store, loader, assert_current = backend(db_path)
        expected, task, job = current_job(records, store, args.task_id, args.source_sha256, args.job_id)
        validate_candidate(candidate, manifest, job)
        store._normalize(task, expected, candidate)
        images = capture(records, identities, job, candidate, manifest, loader, assert_current)
        require(current_job(records, store, args.task_id, args.source_sha256, expected['job_id'])[0] == expected,
                'job_changed_during_capture')
        require(load_json(candidate_dir / 'candidate.private.json')[1] == candidate_hash
                and load_json(candidate_dir / 'input-manifest.private.json')[1] == manifest_hash, 'candidate_files_changed')
        output = effect.private_run(output_root)
        report = export_frames(output, candidate, manifest, images, job, candidate_hash, manifest_hash)
        print(json.dumps({'status': report['status'], 'private_output': str(output),
                          'frames': len(report['frames']), 'manifest_all_fields_equal': True,
                          'effectiveness_passed': None}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, effect.DiagnosticError) else 'candidate_review_failed'
        if output is not None:
            effect.write_json(output / 'failure.private.json', {'status': 'failed', 'code': code})
        print(json.dumps({'status': 'failed', 'code': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
