"""One bounded, private crop experiment; never installs or publishes anything.

Prepare preserves exact F input images and freezes human reference labels before
inference. Inspect its crops, then run with --approve-reference and the printed
--reference-sha256. Run is single-use: at most two HTTPS requests, two separate
single-target images per request, <=90 seconds each, no retries. A timeout ends
the experiment. Only the existing configured glm-5.3-flash is permitted.

Live paths must be under /var/lib/rehabaffect/acceptance-private. Original source
hash and F candidate digest are pinned below. There are no DB/service writes,
full-scene API images, mosaics, identity labels, default-model changes, or
endpoint/key arguments. Exact provider replies and unmasked images stay private.

Offline verification: python scripts/cloud_target_crop_probe.py --self-test
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

APP = Path('/opt/rehabaffect')
if (APP / 'scripts').is_dir():
    sys.path.insert(0, str(APP / 'scripts'))
    sys.path.insert(0, str(APP / 'src'))
import cloud_observation_effectiveness as private

PRIVATE_ROOT = Path('/var/lib/rehabaffect/acceptance-private')
SOURCE = '653edf349db570559d0d54594befb9025768e65ecef7a313f627dda24a9a6b21'
F_CANDIDATE = '0afa941539cf11fd9cf9c5a5c7166d93ee5493b2e5665433370127de5202999c'
MODEL = 'glm-5.3-flash'
PROMPT = (
    'Inspect each separate target BODY crop using pixels, not existing region numbers. '
    'The supplied head anchor identifies only the target in this crop, not an identity. '
    'If the target body cannot reliably be separated from another actor, or the target is unclear, suitable=false '
    'and both answers="unknown"; do not borrow a neighbor\'s body or hand. A distinguishable '
    'neighbor or clothing fragment alone does not make the target unsuitable. Otherwise '
    'posture is seated/standing/unknown. hand_above_shoulder is true only for a visible '
    'target hand above its own shoulder, false only when both target hands are visibly '
    'not above the shoulders, else "unknown". Return only a JSON object with '
    'one results array. Each result has exactly id, suitable, posture, '
    'hand_above_shoulder, with one result per input ID in order. '
    'No identity, attention, intention, or explanation.'
)
# Human reference fixed from the private F images before this experiment.
CASES = (
    {'id': 'C01', 'timestamp_sec': 307., 'label': 'O02', 'crop': [.31, .48, .39, .80],
     'subject': 'front-left light-jacket person', 'visible_posture': 'seated',
     'visible_hand_above_shoulder': False, 'suitable': True},
    {'id': 'C02', 'timestamp_sec': 307., 'label': None, 'crop': [.75, .40, .88, .69],
     'head': {'x': .81, 'y': .44, 'width': .027, 'height': .05},
     'subject': 'right-wall black-top person on yellow chair', 'visible_posture': 'seated',
     'visible_hand_above_shoulder': False, 'suitable': True},
    {'id': 'C03', 'timestamp_sec': 1539., 'label': 'O02', 'crop': [.41, .44, .50, .78],
     'subject': 'red-top child standing beside the front-left-center desk; requester-provided child role', 'visible_posture': 'standing',
     'visible_hand_above_shoulder': False, 'suitable': True},
    {'id': 'C04', 'timestamp_sec': 923., 'label': 'O01', 'crop': [.59, .47, .70, .86],
     'subject': 'foreground dark-jacket blue-jeans person', 'visible_posture': 'standing',
     'visible_hand_above_shoulder': False, 'suitable': True,
     'separation_note': 'Pink clothing behind the target does not obscure the distinct connected target head, torso, legs and low hands.'},
)


def check(value, code):
    private.require(value, code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_private(path, limit=1024 * 1024):
    path = Path(path)
    private.no_links(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        import stat
        info = os.fstat(handle.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_size <= limit and info.st_nlink == 1, 'unsafe_private_file')
        if os.name == 'posix':
            owners = {os.geteuid()}
            if os.geteuid() == 0:
                import pwd
                owners.add(pwd.getpwnam('rehabaffect').pw_uid)
            check(info.st_uid in owners and not info.st_mode & 0o077, 'unsafe_private_permissions')
        return handle.read(limit + 1)


def crop_image(data, box, head):
    image = private.decode_image(data)
    left, top, right, bottom = [round(v * size) for v, size in zip(box, (image.width, image.height) * 2)]
    check(0 <= left < right <= image.width and 0 <= top < bottom <= image.height, 'invalid_crop')
    x, y, w, h = (head[k] for k in ('x', 'y', 'width', 'height'))
    anchor = {'x': (x * image.width - left) / (right - left),
              'y': (y * image.height - top) / (bottom - top),
              'width': w * image.width / (right - left), 'height': h * image.height / (bottom - top)}
    check(private.bbox(anchor) is not None, 'head_outside_crop')
    crop = image.crop((left, top, right, bottom))
    stream = io.BytesIO()
    crop.save(stream, format='PNG')
    return stream.getvalue(), anchor, [left, top, right, bottom]


def prepare(review_dir, output_root):
    report_raw = read_private(review_dir / 'review.private.json')
    report = json.loads(report_raw)
    candidate_file = PRIVATE_ROOT / 'v10-effect-candidate-111-f' / 'candidate.private.json'
    check(digest(read_private(candidate_file)) == F_CANDIDATE, 'actual_candidate_file_hash_mismatch')
    check(report.get('source_sha256') == SOURCE and report.get('candidate_file_sha256') == F_CANDIDATE
          and report.get('actual_input_hashes_verified') is True and report.get('manifest_all_fields_equal') is True,
          'not_exact_authorized_f_inputs')
    output = private.private_run(output_root)
    references = []
    source_cache = {}
    for case in CASES:
        row = next(r for r in report['frames'] if r['timestamp_sec'] == case['timestamp_sec'])
        name = row['actual_model_input_file']
        check(isinstance(name, str) and Path(name).name == name, 'unsafe_image_name')
        if name not in source_cache:
            raw = read_private(review_dir / name)
            check(digest(raw) == row['model_image_sha256'], 'actual_f_input_hash_mismatch')
            source_cache[name] = raw
            private.write_private(output / name, raw)
        raw = source_cache[name]
        head = case.get('head') or next(o['bbox'] for o in row['observations'] if o['label'] == case['label'])
        crop, anchor, xyxy = crop_image(raw, case['crop'], head)
        file = case['id'] + '-crop.png'
        private.write_private(output / file, crop)
        references.append({**case, 'crop_file': file, 'crop_sha256': digest(crop),
            'actual_f_input_file': name, 'actual_f_input_sha256': digest(raw),
            'head_anchor_in_crop': anchor, 'crop_xyxy_pixels': xyxy,
            'expected_literal': {'id': case['id'], 'suitable': case['suitable'],
                'posture': case['visible_posture'] if case['suitable'] else 'unknown',
                'hand_above_shoulder': case['visible_hand_above_shoulder'] if case['suitable'] else 'unknown'}})
    reference = {'status': 'draft_pending_exact_crop_inspection', 'source_sha256': SOURCE,
        'candidate_file_sha256': F_CANDIDATE, 'source_review_file_sha256': digest(report_raw),
        'actual_candidate_file_hash_verified': True, 'candidate_file': str(candidate_file),
        'task_id': report['task_id'], 'created_unix': time.time(), 'max_api_calls': 2,
        'timeout_seconds_per_call': 90, 'model': MODEL, 'cases': references,
        'note': 'Draft labels require exact crop inspection and an explicit freeze before inference. Distinct neighbors are not automatically unsuitable. No cross-frame identity claim.'}
    private.write_json(output / 'reference.draft.private.json', reference)
    contact(output, reference['cases'], {}, 'REFERENCE BEFORE INFERENCE', 'reference-contact.private.png')
    return output, digest(read_private(output / 'reference.draft.private.json'))


def freeze(directory, draft_hash):
    raw = read_private(directory / 'reference.draft.private.json')
    check(digest(raw) == draft_hash, 'draft_reference_changed')
    value = json.loads(raw)
    check(value['status'] == 'draft_pending_exact_crop_inspection', 'invalid_reference_state')
    value.update(status='human_reference_pre_inference', inspected_and_frozen_unix=time.time(),
                 draft_file_sha256=draft_hash)
    private.write_json(directory / 'reference.private.json', value)
    return digest(read_private(directory / 'reference.private.json'))


def contact(output, cases, actual, title, name):
    Image, ImageDraw, ImageFont = private.image_tools()
    panel_w, panel_h = 340, 540
    canvas = Image.new('RGB', (panel_w * len(cases), panel_h), 'white')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for i, case in enumerate(cases):
        x = i * panel_w
        crop = private.decode_image(read_private(output / case['crop_file']))
        crop.thumbnail((panel_w - 24, 330))
        canvas.paste(crop, (x + 12, 60))
        lines = [case['id'] + ' | %.0fs' % case['timestamp_sec'], title,
                 'Human pose: ' + case['visible_posture'],
                 'Suitable: ' + str(case['suitable']),
                 'Expected: ' + case['expected_literal']['posture'],
                 'Hand above: ' + str(case['expected_literal']['hand_above_shoulder'])]
        if case['id'] in actual:
            lines += ['Model: ' + str(actual[case['id']].get('posture')),
                      'Model hand: ' + str(actual[case['id']].get('hand_above_shoulder')),
                      'Model suitable: ' + str(actual[case['id']].get('suitable'))]
        else:
            lines += ['Model: not available']
        draw.text((x + 12, 8), lines[0], fill='black', font=font)
        draw.text((x + 12, 30), lines[1], fill='black', font=font)
        for n, line in enumerate(lines[2:]):
            draw.text((x + 12, 400 + 18 * n), line, fill='black', font=font)
    stream = io.BytesIO()
    canvas.save(stream, format='PNG')
    private.write_private(output / name, stream.getvalue())


def payload(config, cases, directory):
    content = []
    for case in cases:
        raw = read_private(directory / case['crop_file'])
        check(digest(raw) == case['crop_sha256'], 'crop_changed')
        # Only ID, crop pixels and head anchor go upstream, never reference labels.
        content += [{'type': 'text', 'text': json.dumps({'id': case['id'], 'head_anchor': case['head_anchor_in_crop']})},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')}}]
    value = {'model': MODEL, 'temperature': 0, 'max_tokens': 2000,
             'response_format': {'type': 'json_object'},
             'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': content}]}
    if config.reasoning_effort:
        value['reasoning_effort'] = config.reasoning_effort
    return json.dumps(value, allow_nan=False).encode()


def parse_response(raw, ids):
    outer = json.loads(raw)
    content = outer['choices'][0]['message']['content']
    check(isinstance(content, str), 'invalid_literal_response')
    value = json.loads(content)
    check(isinstance(value, dict) and set(value) == {'results'} and isinstance(value['results'], list)
          and [r.get('id') for r in value['results']] == ids, 'invalid_literal_response')
    for row in value['results']:
        check(set(row) == {'id', 'suitable', 'posture', 'hand_above_shoulder'}
              and type(row['suitable']) is bool and row['posture'] in {'seated', 'standing', 'unknown'}
              and (type(row['hand_above_shoulder']) is bool or row['hand_above_shoulder'] == 'unknown'),
              'invalid_literal_response')
        check(row['suitable'] or (row['posture'] == 'unknown' and row['hand_above_shoulder'] == 'unknown'),
              'unsuitable_actor_not_abstained')
    return value['results']


def execute(directory, reference_hash, config, transport):
    raw = read_private(directory / 'reference.private.json')
    check(digest(raw) == reference_hash, 'reference_changed')
    reference = json.loads(raw)
    check(reference['source_sha256'] == SOURCE and reference['model'] == MODEL
          and reference.get('status') == 'human_reference_pre_inference'
          and config.enabled and config.model == MODEL, 'only_existing_glm_config_allowed')
    check(len(reference['cases']) <= 4, 'too_many_cases')
    private.write_json(directory / 'run-started.private.json', {'reference_sha256': reference_hash,
        'approved_unix': time.time(), 'model': MODEL, 'max_calls': 2, 'no_retries': True})
    config = replace(config, timeout_seconds=min(90., config.timeout_seconds))
    calls, actual = [], {}
    for index in range(0, len(reference['cases']), 2):
        group = reference['cases'][index:index + 2]
        number = len(calls) + 1
        check(number <= 2, 'call_budget_exceeded')
        body = payload(config, group, directory)
        private.write_json(directory / ('call-%02d-started.private.json' % number),
                           {'ids': [c['id'] for c in group], 'timeout_seconds': config.timeout_seconds,
                            'request_sha256': digest(body), 'reference_sha256': reference_hash})
        started = time.monotonic()
        record = {'call': number, 'ids': [c['id'] for c in group]}
        stop = False
        try:
            response = transport(config, body)
            private.write_private(directory / ('call-%02d-response.private.json' % number), response)
            parsed = parse_response(response, record['ids'])
            actual.update({row['id']: row for row in parsed})
            record['status'] = 'literal_response_parsed'
        except Exception as exc:
            code = str(exc) if isinstance(exc, private.DiagnosticError) else getattr(exc, 'code', None)
            safe = {'timeout', 'transport_error', 'upstream_status', 'invalid_response', 'response_too_large',
                    'redirect_blocked', 'invalid_literal_response', 'unsuitable_actor_not_abstained'}
            record.update(status='failed', code=code if code in safe else 'invalid_literal_response')
            stop = code in {'timeout', 'transport_error'} or isinstance(exc, TimeoutError)
            if isinstance(exc, TimeoutError):
                record['code'] = 'timeout'
        record['seconds'] = round(time.monotonic() - started, 3)
        calls.append(record)
        private.write_json(directory / ('call-%02d-result.private.json' % number), record)
        if stop:
            break
    comparisons = []
    for case in reference['cases']:
        result = actual.get(case['id'])
        mismatches = None if result is None else [k for k in ('suitable', 'posture', 'hand_above_shoulder')
                                                   if type(result[k]) is not type(case['expected_literal'][k])
                                                   or result[k] != case['expected_literal'][k]]
        comparisons.append({'id': case['id'], 'human_visible_posture': case['visible_posture'],
            'expected_literal': case['expected_literal'], 'actual_literal': result,
            'mismatched_fields': mismatches, 'posture_effect_assessable': case['suitable'],
            'literal_match': None if result is None else not mismatches})
    report = {'status': 'bounded_crop_probe_completed', 'model': MODEL, 'source_sha256': SOURCE,
        'reference_sha256': reference_hash, 'api_calls': len(calls), 'calls': calls, 'comparisons': comparisons,
        'published': False, 'default_model_changed': False, 'whole_lesson': False, 'accuracy': None,
        'effectiveness_passed': None, 'note': 'Small pre-referenced diagnostic only; no population accuracy or identity conclusion. No retry or continuation after timeout.'}
    private.write_json(directory / 'probe-result.private.json', report)
    contact(directory, reference['cases'], actual, 'BOUNDED CROP RESULT', 'result-contact.private.png')
    return report


def self_test():
    import tempfile
    import unittest
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Config:
        enabled: bool = True
        model: str = MODEL
        timeout_seconds: float = 120.
        reasoning_effort: str = 'low'

    class Checks(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.directory = private.private_run(Path(self.temp.name) / 'private')
            Image, _, _ = private.image_tools()
            stream = io.BytesIO()
            Image.new('RGB', (160, 320), 'green').save(stream, format='PNG')
            self.cases = []
            for c in CASES:
                private.write_private(self.directory / (c['id'] + '-crop.png'), stream.getvalue())
                self.cases.append({**c, 'crop_file': c['id'] + '-crop.png', 'crop_sha256': digest(stream.getvalue()),
                    'head_anchor_in_crop': {'x': .2, 'y': .1, 'width': .2, 'height': .2},
                    'expected_literal': {'id': c['id'], 'suitable': c['suitable'],
                        'posture': c['visible_posture'] if c['suitable'] else 'unknown',
                        'hand_above_shoulder': False if c['suitable'] else 'unknown'}})
            private.write_json(self.directory / 'reference.private.json', {'source_sha256': SOURCE,
                'model': MODEL, 'status': 'human_reference_pre_inference', 'cases': self.cases})
            self.sha = digest(read_private(self.directory / 'reference.private.json'))

        def test_two_calls_exact_comparison_no_gold_sent(self):
            seen = []
            def post(config, body):
                request = json.loads(body)
                self.assertLessEqual(config.timeout_seconds, 90)
                content = request['messages'][1]['content']
                texts = [json.loads(x['text']) for x in content if x['type'] == 'text']
                self.assertTrue(all(set(t) == {'id', 'head_anchor'} for t in texts))
                ids = [t['id'] for t in texts]
                seen.append(ids)
                rows = [c['expected_literal'] for c in self.cases if c['id'] in ids]
                return json.dumps({'choices': [{'message': {'content': json.dumps({'results': rows})}}]}).encode()
            report = execute(self.directory, self.sha, Config(), post)
            self.assertEqual(len(seen), 2)
            self.assertTrue(all(c['literal_match'] for c in report['comparisons']))
            with self.assertRaises(FileExistsError):
                execute(self.directory, self.sha, Config(), post)
            self.assertEqual(len(seen), 2)

        def test_timeout_stops_without_second_call(self):
            seen = []
            def post(*_args):
                seen.append(1)
                raise TimeoutError()
            report = execute(self.directory, self.sha, Config(), post)
            self.assertEqual(len(seen), 1)
            self.assertEqual(report['calls'][0]['code'], 'timeout')
            self.assertTrue(all(c['actual_literal'] is None for c in report['comparisons']))

        def test_changed_reference_no_call(self):
            with self.assertRaises(private.DiagnosticError):
                execute(self.directory, '0' * 64, Config(), lambda *_: self.fail('no API'))

        def test_other_model_refused(self):
            with self.assertRaises(private.DiagnosticError):
                execute(self.directory, self.sha, Config(model='other'), lambda *_: self.fail('no API'))

        def test_literal_bool_not_string(self):
            row = {'id': 'C01', 'suitable': True, 'posture': 'seated', 'hand_above_shoulder': 'false'}
            raw = json.dumps({'choices': [{'message': {'content': json.dumps({'results': [row]})}}]}).encode()
            with self.assertRaises(private.DiagnosticError):
                parse_response(raw, ['C01'])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--phase', choices=['prepare', 'freeze', 'run'])
    parser.add_argument('--review-dir')
    parser.add_argument('--output')
    parser.add_argument('--probe-dir')
    parser.add_argument('--reference-sha256')
    parser.add_argument('--approve-reference', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        check(os.name == 'posix', 'live_probe_requires_private_posix')
        paths = [Path(os.path.abspath(p)) for p in (args.review_dir, args.output, args.probe_dir) if p]
        for path in paths:
            private.no_links(path)
            check(path.is_relative_to(PRIVATE_ROOT) and path != PRIVATE_ROOT, 'private_root_required')
        if args.phase == 'prepare':
            check(args.review_dir and args.output, 'prepare_paths_required')
            output, sha = prepare(Path(args.review_dir), Path(args.output))
            print(json.dumps({'status': 'draft_prepared_no_api_calls', 'private_output': str(output), 'draft_reference_sha256': sha}))
        elif args.phase == 'freeze':
            check(args.probe_dir and args.approve_reference and private.sha256(args.reference_sha256),
                  'human_exact_crop_inspection_required')
            sha = freeze(Path(args.probe_dir), args.reference_sha256)
            print(json.dumps({'status': 'human_reference_frozen_no_api_calls', 'reference_sha256': sha,
                              'private_output': args.probe_dir}))
        else:
            check(args.phase == 'run' and args.probe_dir and args.approve_reference
                  and private.sha256(args.reference_sha256), 'human_reference_approval_required')
            from rehab_affect.demo2_observation_model import ObservationModelConfig, _https_post
            report = execute(Path(args.probe_dir), args.reference_sha256,
                             ObservationModelConfig.from_env(), _https_post)
            print(json.dumps({'status': report['status'], 'api_calls': report['api_calls'],
                'calls': report['calls'], 'comparisons': report['comparisons'], 'private_output': args.probe_dir}))
        return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, private.DiagnosticError) else 'crop_probe_failed'
        print(json.dumps({'status': 'failed', 'code': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
