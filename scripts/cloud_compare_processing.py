"""Read-only comparison of two anonymous cloud_benchmark_processing reports.

Usage: python cloud_compare_processing.py --baseline OLD/report.json --candidate NEW/report.json
       python cloud_compare_processing.py --self-test

Stdout is anonymous JSON. Exit 0 means evidence matches, not necessarily faster.
speed_gain_percent measures throughput gain; time_reduction_percent measures
elapsed-time savings. No media, credentials, database or network is accessed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat


MAX_REPORT_BYTES = 128 * 1024
MATCH_FIELDS = ('source_sha256', 'images_sha256', 'audio_sha256', 'evidence_sha256',
                'decoded_frames', 'sampled_frames')


class ComparisonError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise ComparisonError(code)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'invalid_report')
        result[key] = value
    return result


def reject_constant(_value):
    raise ComparisonError('invalid_report')


def read_report(path):
    try:
        require(not path.is_symlink(), 'report_unavailable')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_REPORT_BYTES, 'invalid_report')
            raw = stream.read(MAX_REPORT_BYTES + 1)
        require(len(raw) <= MAX_REPORT_BYTES, 'invalid_report')
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)
    except OSError:
        raise ComparisonError('report_unavailable') from None
    except (ValueError, UnicodeError, RecursionError):
        raise ComparisonError('invalid_report') from None


def validate(report):
    require(isinstance(report, dict), 'invalid_report')
    required = set(MATCH_FIELDS) | {'ok', 'sample', 'engine_sha256', 'processing_seconds',
        'progress_callbacks', 'database_progress_seconds', 'network_upload_measured',
        'production_database_modified'}
    require(required <= report.keys(), 'invalid_report')
    require(report['ok'] is True, 'benchmark_not_successful')
    require(report['network_upload_measured'] is False
            and report['production_database_modified'] is False, 'benchmark_scope_invalid')
    require(isinstance(report['sample'], str)
            and re.fullmatch(r'Sample0[1-4]', report['sample']), 'invalid_report')
    for key in ('source_sha256', 'engine_sha256', 'images_sha256', 'audio_sha256', 'evidence_sha256'):
        value = report[key]
        if key == 'audio_sha256' and value is None:
            continue
        require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'invalid_report')
    for key in ('decoded_frames', 'sampled_frames', 'progress_callbacks'):
        require(type(report[key]) is int and report[key] > 0, 'invalid_report')
    for key in ('processing_seconds', 'database_progress_seconds'):
        value = report[key]
        require(type(value) in (int, float) and math.isfinite(value)
                and value >= 0 and (key != 'processing_seconds' or value > 0), 'invalid_report')
    require(report['database_progress_seconds'] <= report['processing_seconds'], 'invalid_report')


def reduction(before, after):
    return round((1 - after / before) * 100, 6) if before else None


def compare(baseline, candidate):
    validate(baseline)
    validate(candidate)
    require(baseline['sample'] == candidate['sample'], 'sample_mismatch')
    for key in MATCH_FIELDS:
        require(baseline[key] == candidate[key], key + '_mismatch')
    before, after = baseline['processing_seconds'], candidate['processing_seconds']
    factor = before / after
    require(math.isfinite(factor), 'invalid_report')
    return {
        'ok': True, 'sample': baseline['sample'], 'evidence_identical': True,
        'checks': {key + '_identical': True for key in MATCH_FIELDS},
        'decoded_frames': baseline['decoded_frames'], 'sampled_frames': baseline['sampled_frames'],
        'audio_present': baseline['audio_sha256'] is not None,
        'baseline_seconds': before, 'candidate_seconds': after,
        'seconds_saved': round(before - after, 6),
        'speedup_factor': round(factor, 6),
        'speed_gain_percent': round((factor - 1) * 100, 6),
        'time_reduction_percent': reduction(before, after),
        'performance_improved': after < before,
        'progress_callbacks': {
            'baseline': baseline['progress_callbacks'], 'candidate': candidate['progress_callbacks'],
            'reduction_percent': reduction(baseline['progress_callbacks'], candidate['progress_callbacks'])},
        'database_progress_seconds': {
            'baseline': baseline['database_progress_seconds'], 'candidate': candidate['database_progress_seconds'],
            'reduction_percent': reduction(baseline['database_progress_seconds'],
                                           candidate['database_progress_seconds'])},
        'scope': 'single_sample_report_comparison_not_school_wan_or_general_capacity',
    }


def self_test():
    baseline = {'ok': True, 'sample': 'Sample01', 'source_sha256': 'a' * 64,
        'engine_sha256': 'b' * 64, 'images_sha256': 'c' * 64, 'audio_sha256': 'd' * 64,
        'evidence_sha256': 'e' * 64, 'decoded_frames': 67726, 'sampled_frames': 2258,
        'processing_seconds': 360.424, 'progress_callbacks': 5052, 'database_progress_seconds': 8.218,
        'network_upload_measured': False, 'production_database_modified': False}
    candidate = {**baseline, 'engine_sha256': 'f' * 64, 'processing_seconds': 220.844,
                 'progress_callbacks': 157, 'database_progress_seconds': 0.862}
    result = compare(baseline, candidate)
    require(result['seconds_saved'] == 139.58 and result['performance_improved'], 'self_test_failed')
    require(result['speedup_factor'] == round(360.424 / 220.844, 6), 'self_test_failed')
    cases = [(key, 'f' * 64 if key.endswith('sha256') else baseline[key] + 1, key + '_mismatch')
             for key in MATCH_FIELDS]
    cases += [('ok', False, 'benchmark_not_successful'),
              ('production_database_modified', True, 'benchmark_scope_invalid'),
              ('network_upload_measured', True, 'benchmark_scope_invalid'),
              ('sample', 'Sample02', 'sample_mismatch'),
              ('images_sha256', '', 'invalid_report'),
              ('processing_seconds', 0, 'invalid_report'),
              ('processing_seconds', float('nan'), 'invalid_report'),
              ('decoded_frames', True, 'invalid_report')]
    for key, value, code in cases:
        try:
            compare(baseline, {**candidate, key: value})
        except ComparisonError as error:
            require(str(error) == code, 'self_test_failed')
        else:
            raise ComparisonError('self_test_failed')
    missing = dict(candidate)
    del missing['audio_sha256']
    try:
        compare(baseline, missing)
    except ComparisonError as error:
        require(str(error) == 'invalid_report', 'self_test_failed')
    else:
        raise ComparisonError('self_test_failed')
    require(compare({**baseline, 'audio_sha256': None},
                    {**candidate, 'audio_sha256': None})['audio_present'] is False, 'self_test_failed')
    slower = compare(baseline, {**candidate, 'processing_seconds': 400})
    require(not slower['performance_improved'] and slower['speed_gain_percent'] < 0, 'self_test_failed')
    return {'ok': True, 'self_test': True, 'cases_passed': len(cases) + 4}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ComparisonError('invalid_arguments')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--baseline', type=Path)
        parser.add_argument('--candidate', type=Path)
        parser.add_argument('--self-test', action='store_true')
        args = parser.parse_args(argv)
        if args.self_test:
            require(args.baseline is None and args.candidate is None, 'invalid_arguments')
            result = self_test()
        else:
            require(args.baseline is not None and args.candidate is not None, 'invalid_arguments')
            result = compare(read_report(args.baseline), read_report(args.candidate))
    except ComparisonError as error:
        result = {'ok': False, 'error': str(error)}
    except Exception:
        result = {'ok': False, 'error': 'comparison_failed'}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
