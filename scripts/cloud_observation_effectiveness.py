"""Private, read-only source-image diagnostics, NOT an accuracy measurement.

Run on the authorized cloud host, as the owner of a private /var/lib directory:
  python scripts/cloud_observation_effectiveness.py --base-url http://127.0.0.1:8793 \
    --owner-credentials-file /var/lib/rehabaffect/acceptance-private/owner.json \
    --task-id TASK --source-sha256 SHA256 --allow-private-unmasked

For an unpublished canonical result, add --candidate-json /private/candidate.private.json.
Its task/source/revision/timestamps must match the owner's existing frame manifest.
Candidate file hashes identify the reviewed result; without its own image manifest,
matching the workspace image hash is not proof of the candidate's exact model input.

Credentials are a private {username,password} JSON file, never command arguments.
Only session login/logout POSTs and existing evidence GETs are permitted. There
are no uploads, inference requests, detection calls, DB imports, or deployment.
Login and evidence reads can create the server's normal session/audit records.
Source images and PNG sheets are UNMASKED, mode 0600 within a fresh mode 0700
directory outside the repository. Do not publish them or feed them to an external
model. Sharing requires a separately reviewed, sanitized copy.

Review the original AND overlay: a valid box/IoU is not proof of a person, action,
or identity. Boxes may be head/person anchors, not full-body detections. Every
action requires visible evidence; motion/interaction can need adjacent frames or
a clip. A same-frame teacher ROI is not cross-frame tracking. Sparse frames are
never a whole-lesson evaluation, action duration, or unique-person count.

Offline verification (synthetic images, temporary HTTP server, no credentials):
  python scripts/cloud_observation_effectiveness.py --self-test
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
import warnings
from urllib.parse import urlsplit

import cloud_e2e_acceptance as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = '/var/lib/rehabaffect/acceptance-private/observation-effectiveness'
BEHAVIORS = frozenset({
    'hand_raised', 'writing', 'manipulating_materials', 'handing_materials',
    'receiving_materials', 'head_toward_materials', 'head_toward_visible_person',
    'head_toward_camera', 'head_away_from_materials', 'seated', 'standing',
    'walking', 'out_of_seat',
})
COLORS = ('#d42135', '#136fc0', '#965400', '#7f35c1', '#087d42', '#a52f89')


class DiagnosticError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise DiagnosticError(code)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) is not None


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


class EvidenceClient(base.Client):
    """The inherited transport rejects non-loopback hosts, proxies and redirects."""

    def __init__(self, url):
        super().__init__(url)
        self.deadline = time.monotonic() + 180

    def request(self, path, *, payload=None, binary=None, headers=None, timeout=15):
        name = urlsplit(path).path.removeprefix(base.API)
        allowed = {'/upload/task', '/observations', '/identity/workspace', '/identity/frame'}
        require(binary is None and not headers, 'unsafe_request')
        require((payload is None and name in allowed) or
                (payload is not None and name in {'/auth/login', '/auth/logout'}), 'unsafe_request')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'deadline_exceeded')
        return super().request(path, payload=payload, timeout=min(timeout, remaining))


def no_links(path):
    require(all(not item.is_symlink() for item in (path, *path.parents)), 'unsafe_path')


def private_run(parent):
    parent = Path(os.path.abspath(Path(parent).expanduser()))
    require(not parent.is_relative_to(ROOT), 'output_inside_repository')
    no_links(parent)
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = parent.stat()
    require(stat.S_ISDIR(info.st_mode), 'unsafe_output')
    if os.name == 'posix':
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_output')
    run = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(5))
    run.mkdir(mode=0o700)
    return run


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def write_json(path, value):
    write_private(path, (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + '\n').encode())


def load_candidate(path):
    path = Path(os.path.abspath(path))
    no_links(path)
    raw = base.private_text(path)
    value = json.loads(raw)
    require(isinstance(value, dict), 'invalid_candidate')
    return {'result': value, 'json_text_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def image_tools():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise DiagnosticError('pillow_required') from None
    return Image, ImageDraw, ImageFont


def decode_image(data):
    Image, _, _ = image_tools()
    require(0 < len(data) <= base.MAX_RESPONSE, 'invalid_image')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as opened:
            require(opened.format in {'JPEG', 'PNG'} and getattr(opened, 'n_frames', 1) == 1,
                    'invalid_image')
            require(0 < opened.width <= 8192 and 0 < opened.height <= 8192 and
                    opened.width * opened.height <= 16_000_000, 'image_dimensions_exceeded')
            opened.verify()
        with Image.open(io.BytesIO(data)) as opened:
            return opened.convert('RGB')


def bbox(value):
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}:
        return None
    x, y, w, h = (value[k] for k in ('x', 'y', 'width', 'height'))
    if (not all(number(v) for v in (x, y, w, h)) or min(x, y) < 0 or min(w, h) <= 0
            or x + w > 1.000001 or y + h > 1.000001):
        return None
    return tuple(float(v) for v in (x, y, w, h))


def overlap(left, right):
    x, y, w, h = left
    a, b, c, d = right
    intersection = max(0., min(x + w, a + c) - max(x, a)) * max(0., min(y + h, b + d) - max(y, b))
    return {'iou': round(intersection / (w * h + c * d - intersection), 6),
            'intersection_over_smaller': round(intersection / min(w * h, c * d), 6)}


def snapshot(client, account, task_id, source_hash, targets=None, course_name=None, candidate=None):
    envelope = client.json(base.route('/upload/task', id=task_id))
    task = envelope['task']
    require(task.get('task_id') == task_id and task.get('sha256') == source_hash, 'source_mismatch')
    require(account.get('role') == 'school_uploader' and bool(account.get('account_id')) and
            task.get('account_id') == account['account_id'], 'not_task_owner')
    if course_name is not None:
        require(task.get('course_name') == course_name, 'course_mismatch')
    work = client.json(base.route('/observations', task_id=task_id))['workspace']
    require(work.get('status') == 'ready', 'observations_not_ready')
    require(work.get('owner_account_id') == account['account_id'], 'not_observation_owner')
    require(work.get('task_id') == task_id and work.get('source_sha256') == source_hash,
            'observation_source_mismatch')
    require(identifier(work.get('job_id')) and identifier(work.get('frame_revision')), 'invalid_provenance')
    identity = client.json(base.route('/identity/workspace', task_id=task_id))['workspace']
    require(identity.get('task_id') == task_id and identity.get('frame_revision') == work['frame_revision']
            and identity.get('media_available') is True and bool(identity.get('scope_key'))
            and identity['scope_key'] == work.get('scope_key'), 'identity_source_mismatch')
    result = candidate['result'] if candidate is not None else work.get('result')
    require(isinstance(result, dict) and result.get('schema_version') == 'visible_observation_v1',
            'unsupported_observation_schema')
    for key in ('task_id', 'source_sha256', 'frame_revision'):
        require(result.get(key) == work[key], 'result_provenance_mismatch')
    coverage = result['coverage']
    require(coverage.get('scope') == 'sampled_frames_only' and coverage.get('continuous_coverage') is False
            and coverage.get('full_lesson') is False and result.get('scoring_performed') is False
            and result.get('identity_recognition_performed') is False
            and result.get('requires_teacher_review') is True, 'unsafe_result_scope')
    raw_samples, frames = work['samples'], result['frames']
    require(isinstance(raw_samples, list) and isinstance(frames, list) and 1 <= len(raw_samples) <= 8
            and len(raw_samples) == len(frames) == coverage.get('sample_count'), 'invalid_samples')
    samples = []
    for sample in raw_samples:
        require(isinstance(sample, dict), 'invalid_samples')
        if 'time_sec' in sample and 'timestamp_sec' in sample:
            require(sample['time_sec'] == sample['timestamp_sec'], 'sample_timestamp_mismatch')
        samples.append({'frame_key': sample['frame_key'],
                        'timestamp_sec': sample.get('timestamp_sec', sample.get('time_sec')),
                        'image_sha256': sample.get('image_sha256')})
    keys = [sample['frame_key'] for sample in samples]
    times = [sample['timestamp_sec'] for sample in samples]
    require(all(identifier(key) for key in keys) and len(set(keys)) == len(keys)
            and all(number(t) and t >= 0 for t in times)
            and all(a < b for a, b in zip(times, times[1:])), 'invalid_samples')
    require(times == coverage.get('sample_timestamps_sec') == [f['timestamp_sec'] for f in frames],
            'sample_timestamp_mismatch')
    duration = coverage.get('media_duration_sec')
    require(duration is None or (number(duration) and duration > 0 and times[-1] <= duration),
            'invalid_duration')
    by_key = {frame['frame_key']: frame for frame in identity['frames']}
    require(all(key in by_key and by_key[key]['time_sec'] == timestamp
                for key, timestamp in zip(keys, times)), 'frame_manifest_mismatch')
    for frame in frames:
        observations = frame.get('observations')
        require(isinstance(observations, list) and len(observations) <= 9, 'invalid_observations')
        require(all(isinstance(o, dict) and o.get('behavior') in BEHAVIORS for o in observations),
                'invalid_behavior')
    chosen = targets if targets is not None else work.get('target_settings', {}).get('selected_student_ids', [])
    require(isinstance(chosen, list) and len(chosen) <= 3 and all(identifier(s) for s in chosen)
            and len(set(chosen)) == len(chosen), 'invalid_targets')
    roster = {s['student_id'] for s in identity['students'] if s.get('owner_account_id') == account['account_id']
              and s.get('scope_key') == work['scope_key']}
    require(set(chosen) <= roster, 'target_not_in_owner_roster')
    bindings = []
    for item in identity['bindings']:
        if (item.get('status') != 'confirmed' or item.get('current_revision') is not True
                or item.get('stale') is True or item.get('frame_key') not in keys):
            continue
        if (item.get('task_id') != task_id or item.get('source_sha256') != source_hash
                or item.get('frame_revision') != work['frame_revision']
                or item.get('owner_account_id') != account['account_id']
                or item.get('scope_key') != work['scope_key']):
            continue
        if item.get('time_sec') != by_key[item['frame_key']]['time_sec'] or bbox(item.get('bbox')) is None:
            continue
        bindings.append({k: item.get(k) for k in ('binding_id', 'student_id', 'role', 'frame_key', 'bbox')})
    # Discard roster names, profiles, teacher notes and all other API fields.
    return {'task_id': task_id, 'source_sha256': source_hash, 'job_id': work['job_id'],
            'frame_revision': work['frame_revision'], 'model': result.get('model', work.get('model')),
            'samples': samples, 'frames': frames, 'coverage': coverage,
            'result_origin': 'private_unpublished_candidate' if candidate is not None else 'current_workspace',
            'candidate_json_text_sha256': candidate['json_text_sha256'] if candidate is not None else None,
            'selected_student_ids': chosen, 'bindings': sorted(bindings, key=lambda b: b['binding_id'])}


def frame_diagnostics(frame, sample, image, bindings, targets):
    rows, boxes, review = [], [], []
    same_frame = [b for b in bindings if b['frame_key'] == sample['frame_key']]
    for index, observation in enumerate(frame['observations'], 1):
        label = 'O%02d' % index
        raw = observation.get('bbox')
        box = bbox(raw)
        state = 'null' if 'bbox' in observation and raw is None else 'valid' if box is not None else 'invalid'
        row = {'label': label, 'behavior': observation['behavior'], 'bbox_state': state,
               'bbox': dict(raw) if box is not None else None, 'same_frame_roi_geometry': []}
        if box is not None:
            x, y, w, h = box
            row.update(area_fraction=round(w * h, 6), pixel_width=round(w * image.width, 2),
                       pixel_height=round(h * image.height, 2),
                       touches_border=min(x, y, 1 - x - w, 1 - y - h) <= .001,
                       smaller_than_16px=min(w * image.width, h * image.height) < 16)
            boxes.append((label, box))
            for binding in same_frame:
                metrics = overlap(box, bbox(binding['bbox']))
                if metrics['intersection_over_smaller'] > 0:
                    row['same_frame_roi_geometry'].append({
                        'binding_id': binding['binding_id'], 'selected_target': binding['student_id'] in targets,
                        **metrics, 'iou_ge_0_5': metrics['iou'] >= .5})
            row['multiple_roi_candidates_iou_ge_0_5'] = sum(
                v['iou_ge_0_5'] for v in row['same_frame_roi_geometry']) > 1
        rows.append(row)
        review.append({'label': label, 'behavior': observation['behavior'],
                       'box_matches_one_visible_person': None, 'action_visibly_supported': None,
                       'same_frame_target_isolated': None, 'evidence_note_or_clip_time': '',
                       'verdict': 'pending'})
    overlaps = []
    for i, (left_label, left) in enumerate(boxes):
        for right_label, right in boxes[i + 1:]:
            metrics = overlap(left, right)
            if metrics['intersection_over_smaller'] > 0:
                overlaps.append({'left': left_label, 'right': right_label, **metrics})
    selected_rois = [b for b in same_frame if b['role'] == 'student' and b['student_id'] in targets]
    target_rows = []
    for binding in selected_rois:
        conflicts = [{'binding_id': other['binding_id'], **overlap(bbox(binding['bbox']), bbox(other['bbox']))}
                     for other in same_frame if other['binding_id'] != binding['binding_id']
                     and other['student_id'] != binding['student_id']]
        target_rows.append({'binding_id': binding['binding_id'],
                            'overlap_with_other_confirmed_rois': [c for c in conflicts if c['iou'] > 0],
                            'isolation_confirmed': None})
    return {'observations': rows, 'overlapping_observation_pairs': overlaps,
            'target_roi_geometry': target_rows,
            'target_review_status': 'pending_human_review' if selected_rois else 'not_evaluable_no_same_frame_target_roi',
            'overlap_note': 'Overlap can be multiple behaviors for one person; it is not an error rate.'}, review


def render_pair(image, diagnostics, bindings, frame_key, timestamp, output, index):
    Image, ImageDraw, ImageFont = image_tools()
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:
        font = ImageFont.load_default()
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)

    def rectangle(box, color, width):
        x, y, w, h = box
        draw.rectangle((int(x * (image.width - 1)), int(y * (image.height - 1)),
                        int((x + w) * (image.width - 1)), int((y + h) * (image.height - 1))),
                       outline=color, width=width)

    legend = []
    for n, row in enumerate(diagnostics['observations']):
        color = COLORS[n % len(COLORS)]
        if row['bbox_state'] == 'valid':
            rectangle(bbox(row['bbox']), color, 3)
            box = bbox(row['bbox'])
            draw.text((int(box[0] * image.width), int(box[1] * image.height)), row['label'], fill=color, font=font)
        legend.append((color, '%s %s [%s bbox]' % (row['label'], row['behavior'], row['bbox_state'])))
    for n, binding in enumerate(bindings, 1):
        rectangle(bbox(binding['bbox']), '#00b8b8', 2)
        x, y, _, h = bbox(binding['bbox'])
        draw.text((int(x * image.width), max(0, int((y + h) * image.height) - 20)),
                  'T%02d' % n, fill='#00b8b8', font=font)
        legend.append(('#007c7c', 'T%02d same-frame teacher ROI (not identity proof)' % n))
    stream = io.BytesIO()
    overlay.save(stream, format='PNG')
    write_private(output / ('effect-frame-%02d-overlay.png' % index), stream.getvalue())
    panel_width = min(960, max(320, image.width))
    panel_height = max(1, round(image.height * panel_width / image.width))
    require(panel_height <= 1600, 'contact_sheet_aspect_exceeded')
    sheet = Image.new('RGB', (panel_width * 2 + 36, panel_height + 90 + 24 * max(1, len(legend))), 'white')
    sheet.paste(image.resize((panel_width, panel_height)), (12, 64))
    sheet.paste(overlay.resize((panel_width, panel_height)), (24 + panel_width, 64))
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 8), 'PRIVATE UNMASKED | sampled frame only | %.3fs | %s' % (timestamp, frame_key),
              fill='black', font=font)
    draw.text((12, 36), 'Original source frame', fill='black', font=font)
    draw.text((24 + panel_width, 36), 'Predictions + selected teacher ROIs', fill='black', font=font)
    for n, (color, text) in enumerate(legend):
        draw.text((12, panel_height + 76 + n * 24), text, fill=color, font=font)
    stream = io.BytesIO()
    sheet.save(stream, format='PNG')
    name = 'effect-contact-%02d.png' % index
    write_private(output / name, stream.getvalue())
    return name


def collect(client, account, task_id, source_hash, output, *, targets=None, course_name=None, candidate=None):
    before = snapshot(client, account, task_id, source_hash, targets, course_name, candidate)
    report_frames, reviews = [], []
    for index, (sample, frame) in enumerate(zip(before['samples'], before['frames']), 1):
        status, headers, data = client.request(base.route('/identity/frame', task_id=task_id,
            frame_key=sample['frame_key'], frame_revision=before['frame_revision']))
        require(status == 200 and headers.get('content-type', '').split(';')[0] in {'image/png', 'image/jpeg'},
                'frame_download_failed')
        digest = hashlib.sha256(data).hexdigest()
        expected = sample.get('image_sha256')
        require(expected is None or (sha256(expected) and digest == expected), 'model_input_image_hash_mismatch')
        image = decode_image(data)
        suffix = 'png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg'
        source_file = 'effect-frame-%02d-source.%s' % (index, suffix)
        write_private(output / source_file, data)
        diagnostics, review = frame_diagnostics(frame, sample, image, before['bindings'], before['selected_student_ids'])
        selected = [b for b in before['bindings'] if b['frame_key'] == sample['frame_key']
                    and b['role'] == 'student' and b['student_id'] in before['selected_student_ids']]
        contact = render_pair(image, diagnostics, selected, sample['frame_key'], sample['timestamp_sec'], output, index)
        report_frames.append({'frame_key': sample['frame_key'], 'timestamp_sec': sample['timestamp_sec'],
            'width': image.width, 'height': image.height, 'source_image_sha256': digest,
            'workspace_source_image_hash_match': True if expected is not None else None,
            'model_input_image_hash_match': True if expected is not None and candidate is None else None,
            'model_input_hash_status': ('candidate_input_manifest_not_available' if candidate is not None else
                                        'verified' if expected is not None else 'not_available'),
            'source_file': source_file, 'contact_sheet': contact, **diagnostics})
        reviews.append({'frame_key': sample['frame_key'], 'timestamp_sec': sample['timestamp_sec'],
            'visible_person_count': None, 'missed_visible_people_count': None,
            'false_person_boxes_count': None, 'target_isolation_note': '', 'observations': review})
    after = snapshot(client, account, task_id, source_hash, targets, course_name, candidate)
    require(before == after, 'source_or_observations_changed_during_capture')
    times = [s['timestamp_sec'] for s in before['samples']]
    rows = [row for frame in report_frames for row in frame['observations']]
    scope = {**before['coverage'], 'max_sample_gap_sec': max((b - a for a, b in zip(times, times[1:])), default=None),
             'whole_lesson_metrics_permitted': False, 'temporal_coverage_fraction': None,
             'note': 'Point samples have no observed duration. Counts are observation records, not people or events.'}
    report = {'schema_version': 'observation_effect_diagnostic_v1',
        'status': 'artifacts_created_pending_human_review', 'effectiveness_passed': None,
        'accuracy': None, 'geometry_is_accuracy': False, 'unmasked_private': True,
        'task_id': task_id, 'source_sha256': source_hash, 'job_id': before['job_id'],
        'frame_revision': before['frame_revision'], 'model': before['model'], 'coverage': scope,
        'result_origin': before['result_origin'], 'candidate_json_text_sha256': before['candidate_json_text_sha256'],
        'candidate_published_by_this_tool': False,
        'observation_record_count': len(rows),
        'bbox_counts': {state: sum(row['bbox_state'] == state for row in rows) for state in ('valid', 'null', 'invalid')},
        'localized_record_fraction_not_accuracy': (round(sum(row['bbox_state'] == 'valid' for row in rows) / len(rows), 6)
                                                    if rows else None),
        'all_model_input_hashes_verified': all(f['model_input_image_hash_match'] is True for f in report_frames),
        'frames': report_frames,
        'acceptance_gates': [
            'Review every original frame: boxes enclose one real visible person/head; enumerate missed people and false boxes.',
            'Review every action against visible evidence; use adjacent frames/clip for temporal claims, otherwise mark not assessable.',
            'For target claims, verify one current teacher ROI in this exact frame, correct person and action; reject ambiguous/other-person attribution.',
            'Null/invalid boxes cannot support individual attribution; IoU candidates are geometry, never identity confirmation.',
            'No extrapolation from sampled frames to whole-lesson rates, durations, unique people, attention, mastery or diagnosis.',
        ]}
    write_json(output / 'diagnostics.json', report)
    write_json(output / 'review-template.json', {'task_id': task_id, 'source_sha256': source_hash,
        'job_id': before['job_id'], 'frame_revision': before['frame_revision'], 'effectiveness_passed': None,
        'result_origin': before['result_origin'], 'candidate_json_text_sha256': before['candidate_json_text_sha256'],
        'review_status': 'pending', 'allowed_verdicts': ['pending', 'supported', 'unsupported', 'not_assessable'],
        'frames': reviews})
    return report


def self_test():
    """Exercise real loopback transport with invented pixels; never load a DB/key."""
    import copy
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import unittest

    Image, ImageDraw, _ = image_tools()
    image = Image.new('RGB', (640, 360), '#cbd8cc')
    ImageDraw.Draw(image).rectangle((100, 70, 230, 320), fill='#5c307c')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    pixels = buffer.getvalue()
    digest = hashlib.sha256(pixels).hexdigest()
    box = {'x': .15, 'y': .15, 'width': .25, 'height': .7}
    account = {'account_id': 'synthetic-owner', 'role': 'school_uploader'}
    coverage = {'scope': 'sampled_frames_only', 'continuous_coverage': False, 'full_lesson': False,
                'sample_count': 1, 'sample_timestamps_sec': [10.], 'media_duration_sec': 1000.}
    provenance = {'task_id': 'synthetic-task', 'source_sha256': 'a' * 64, 'frame_revision': 'revision-1'}
    result = {**provenance, 'schema_version': 'visible_observation_v1', 'coverage': coverage,
              'scoring_performed': False, 'identity_recognition_performed': False, 'requires_teacher_review': True,
              'frames': [{'timestamp_sec': 10., 'observations': [{'behavior': 'standing', 'bbox': box},
                 {'behavior': 'hand_raised', 'bbox': box}, {'behavior': 'seated', 'bbox': None}]}]}
    binding = {**provenance, 'binding_id': 'binding-1', 'student_id': 'student-1', 'role': 'student',
               'owner_account_id': account['account_id'], 'scope_key': 'scope-1', 'status': 'confirmed',
               'current_revision': True, 'stale': False, 'frame_key': 's0_f0', 'time_sec': 10., 'bbox': box}
    fixture = {
        '/upload/task': {'ok': True, 'task': {'task_id': provenance['task_id'], 'sha256': provenance['source_sha256'],
                                            'account_id': account['account_id'], 'course_name': 'synthetic'}},
        '/observations': {'ok': True, 'workspace': {**provenance, 'job_id': 'job-1', 'status': 'ready',
            'owner_account_id': account['account_id'], 'scope_key': 'scope-1', 'model': 'synthetic-only',
            'target_settings': {'selected_student_ids': ['student-1']},
            'samples': [{'frame_key': 's0_f0', 'timestamp_sec': 10., 'image_sha256': digest}], 'result': result}},
        '/identity/workspace': {'ok': True, 'workspace': {'task_id': provenance['task_id'], 'scope_key': 'scope-1',
            'frame_revision': provenance['frame_revision'], 'media_available': True,
            'frames': [{'frame_key': 's0_f0', 'time_sec': 10., 'image_url': 'https://never-fetch.invalid/image'}],
            'students': [{'student_id': 'student-1', 'owner_account_id': account['account_id'],
                          'scope_key': 'scope-1', 'display_name': 'DO_NOT_EXPORT_PROFILE'}], 'bindings': [binding]}},
    }

    class Checks(unittest.TestCase):
        def setUp(self):
            self.fixture = copy.deepcopy(fixture)
            self.requests = []
            test = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def respond(self, status, body, mime='application/json', cookie=False):
                    self.send_response(status)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(body)))
                    if cookie:
                        self.send_header('Set-Cookie', 'rehab_demo2_session=synthetic-secret; HttpOnly')
                    self.end_headers()
                    self.wfile.write(body)

                def do_POST(self):
                    test.requests.append(('POST', self.path))
                    body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    if self.path == base.route('/auth/login'):
                        value = json.loads(body)
                        self.respond(200 if value.get('password') == 'synthetic-password' else 403,
                            json.dumps({'ok': True, 'account': account}).encode(), cookie=True)
                    elif self.path == base.route('/auth/logout'):
                        self.respond(200, b'{"ok":true}')
                    else:
                        self.respond(405, b'{}')

                def do_GET(self):
                    test.requests.append(('GET', self.path))
                    if self.headers.get('Cookie') != 'rehab_demo2_session=synthetic-secret':
                        self.respond(401, b'{}')
                        return
                    name = urlsplit(self.path).path.removeprefix(base.API)
                    if name == '/identity/frame':
                        self.respond(200, pixels, 'image/png')
                    else:
                        self.respond(200, json.dumps(test.fixture[name]).encode())

            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.addCleanup(self.close)
            self.client = EvidenceClient('http://127.0.0.1:%d' % self.server.server_port)
            self.owner = self.client.login({'username': 'synthetic', 'password': 'synthetic-password'}, 'school_uploader')
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.output = private_run(Path(self.temp.name) / 'private')

        def close(self):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)

        def collect(self):
            return collect(self.client, self.owner, provenance['task_id'], provenance['source_sha256'], self.output)

        def test_real_http_source_overlay_and_no_fake_accuracy(self):
            report = self.collect()
            self.assertEqual(report['bbox_counts'], {'valid': 2, 'null': 1, 'invalid': 0})
            self.assertTrue(report['all_model_input_hashes_verified'])
            self.assertEqual(report['frames'][0]['overlapping_observation_pairs'][0]['iou'], 1.)
            self.assertIsNone(report['effectiveness_passed'])
            self.assertIsNone(report['accuracy'])
            self.assertFalse(report['coverage']['whole_lesson_metrics_permitted'])
            self.assertEqual((self.output / 'effect-frame-01-source.png').read_bytes(), pixels)
            with Image.open(self.output / 'effect-frame-01-overlay.png') as rendered:
                self.assertNotEqual(rendered.getpixel((96, 54)), image.getpixel((96, 54)))
            with Image.open(self.output / 'effect-contact-01.png') as sheet:
                self.assertEqual(sheet.getpixel((20, 100)), image.getpixel((8, 36)))
            artifacts = (self.output / 'diagnostics.json').read_text()
            self.assertNotIn('DO_NOT_EXPORT_PROFILE', artifacts)
            self.assertNotIn('synthetic-secret', artifacts)
            self.assertEqual(sum('/identity/frame?' in path for _, path in self.requests), 1)
            self.assertFalse(any('never-fetch' in path for _, path in self.requests))
            self.assertEqual([p for method, p in self.requests if method == 'POST'], [base.route('/auth/login')])
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
                self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in self.output.iterdir()))

        def test_cross_owner_stops_before_images(self):
            self.fixture['/upload/task']['task']['account_id'] = 'other-owner'
            with self.assertRaisesRegex(DiagnosticError, 'not_task_owner'):
                self.collect()
            self.assertFalse(any('/identity/frame?' in p for _, p in self.requests))

        def test_model_input_hash_mismatch(self):
            self.fixture['/observations']['workspace']['samples'][0]['image_sha256'] = 'b' * 64
            with self.assertRaisesRegex(DiagnosticError, 'model_input_image_hash_mismatch'):
                self.collect()
            self.assertFalse((self.output / 'diagnostics.json').exists())

        def test_missing_hash_is_not_verified(self):
            del self.fixture['/observations']['workspace']['samples'][0]['image_sha256']
            report = self.collect()
            self.assertFalse(report['all_model_input_hashes_verified'])
            self.assertIsNone(report['frames'][0]['model_input_image_hash_match'])

        def test_actual_public_workspace_time_sec_without_worker_hash(self):
            sample = self.fixture['/observations']['workspace']['samples'][0]
            sample['time_sec'] = sample.pop('timestamp_sec')
            del sample['image_sha256']
            report = self.collect()
            self.assertEqual(report['frames'][0]['timestamp_sec'], 10.)
            self.assertEqual(report['frames'][0]['model_input_hash_status'], 'not_available')
            self.assertTrue((self.output / 'effect-contact-01.png').is_file())

        def test_reject_full_lesson_claim(self):
            self.fixture['/observations']['workspace']['result']['coverage']['full_lesson'] = True
            with self.assertRaisesRegex(DiagnosticError, 'unsafe_result_scope'):
                self.collect()

        def test_stale_binding_does_not_identify_target(self):
            self.fixture['/identity/workspace']['workspace']['bindings'][0]['current_revision'] = False
            frame = self.collect()['frames'][0]
            self.assertEqual(frame['target_review_status'], 'not_evaluable_no_same_frame_target_roi')
            self.assertEqual(frame['observations'][0]['same_frame_roi_geometry'], [])

        def test_invalid_box_is_reported_not_clamped(self):
            self.fixture['/observations']['workspace']['result']['frames'][0]['observations'][0]['bbox']['x'] = -1
            report = self.collect()
            self.assertEqual(report['bbox_counts']['invalid'], 2)

        def test_transport_blocks_writes_external_hosts(self):
            with self.assertRaises(DiagnosticError):
                self.client.request(base.route('/observations'), payload={'task_id': 'no'})
            with self.assertRaises(base.AcceptanceError):
                EvidenceClient('https://example.com')

        def test_no_overwrite(self):
            path = self.output / 'exclusive.json'
            write_private(path, b'original')
            with self.assertRaises(FileExistsError):
                write_private(path, b'replacement')
            self.assertEqual(path.read_bytes(), b'original')

        def test_source_revision_mismatch(self):
            self.fixture['/identity/workspace']['workspace']['frame_revision'] = 'wrong-revision'
            with self.assertRaisesRegex(DiagnosticError, 'identity_source_mismatch'):
                self.collect()

        def test_private_candidate_replaces_old_null_boxes_without_publishing(self):
            candidate_result = copy.deepcopy(result)
            candidate_result['model'] = 'candidate-model'
            candidate_path = self.output / 'candidate.private.json'
            write_json(candidate_path, candidate_result)
            candidate = load_candidate(candidate_path)
            for row in self.fixture['/observations']['workspace']['result']['frames'][0]['observations']:
                row['bbox'] = None
            report = collect(self.client, self.owner, provenance['task_id'], provenance['source_sha256'],
                             self.output, candidate=candidate)
            self.assertEqual(report['bbox_counts']['valid'], 2)
            self.assertEqual(report['result_origin'], 'private_unpublished_candidate')
            self.assertEqual(report['model'], 'candidate-model')
            self.assertFalse(report['all_model_input_hashes_verified'])
            self.assertTrue(report['frames'][0]['workspace_source_image_hash_match'])
            self.assertFalse(report['candidate_published_by_this_tool'])
            self.assertEqual([p for method, p in self.requests if method == 'POST'], [base.route('/auth/login')])

        def test_candidate_wrong_task_rejected_before_images(self):
            candidate = {'result': copy.deepcopy(result), 'json_text_sha256': 'd' * 64}
            candidate['result']['task_id'] = 'other-task'
            with self.assertRaisesRegex(DiagnosticError, 'result_provenance_mismatch'):
                collect(self.client, self.owner, provenance['task_id'], provenance['source_sha256'],
                        self.output, candidate=candidate)
            self.assertFalse(any('/identity/frame?' in p for _, p in self.requests))

        def test_candidate_wrong_timestamp_rejected(self):
            candidate = {'result': copy.deepcopy(result), 'json_text_sha256': 'd' * 64}
            candidate['result']['frames'][0]['timestamp_sec'] = 11.
            with self.assertRaisesRegex(DiagnosticError, 'sample_timestamp_mismatch'):
                collect(self.client, self.owner, provenance['task_id'], provenance['source_sha256'],
                        self.output, candidate=candidate)

    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    return 0 if outcome.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:8793')
    parser.add_argument('--owner-credentials-file')
    parser.add_argument('--retained-school-index', type=int, choices=range(4))
    parser.add_argument('--task-id')
    parser.add_argument('--source-sha256')
    parser.add_argument('--candidate-json', help='Private canonical candidate result; read only, never published.')
    parser.add_argument('--expected-course-name')
    parser.add_argument('--target-student-id', action='append', default=None,
                        help='Optional diagnostic target only; never changes server target settings.')
    parser.add_argument('--output-root', default=DEFAULT_OUTPUT)
    parser.add_argument('--allow-private-unmasked', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    client = None
    output = None
    try:
        require(os.name == 'posix', 'live_capture_requires_posix_private_permissions')
        require(args.allow_private_unmasked and bool(args.owner_credentials_file) != (args.retained_school_index is not None)
                and identifier(args.task_id)
                and sha256(args.source_sha256), 'explicit_source_owner_and_unmasked_consent_required')
        base.endpoint(args.base_url)
        if args.retained_school_index is not None:
            private = Path('/var/lib/rehabaffect/acceptance-private')
            schools, _ = base.load_credentials(private / 'schools.private.md', private / 'admin.private.json')
            credentials = schools[args.retained_school_index]
        else:
            credentials_path = Path(os.path.abspath(args.owner_credentials_file))
            no_links(credentials_path)
            credentials = base.credential(json.loads(base.private_text(credentials_path)))
        candidate = load_candidate(args.candidate_json) if args.candidate_json else None
        output = private_run(args.output_root)
        client = EvidenceClient(args.base_url)
        account = client.login(credentials, 'school_uploader')
        del credentials
        report = collect(client, account, args.task_id, args.source_sha256, output,
                         targets=args.target_student_id, course_name=args.expected_course_name, candidate=candidate)
        print(json.dumps({'status': report['status'], 'private_output': str(output),
                          'frames': len(report['frames']), 'bbox_counts': report['bbox_counts'],
                          'effectiveness_passed': None}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, DiagnosticError) else exc.code if isinstance(exc, base.AcceptanceError) else 'capture_failed'
        if output is not None:
            write_json(output / 'failure.json', {'status': 'failed', 'code': code, 'effectiveness_passed': None})
        print(json.dumps({'status': 'failed', 'code': code, 'private_output': str(output) if output else None}), file=sys.stderr)
        return 1
    finally:
        if client is not None and client.cookie:
            try:
                client.request(base.route('/auth/logout'), payload={})
            except Exception:
                pass
            client.cookie = ''


if __name__ == '__main__':
    raise SystemExit(main())
