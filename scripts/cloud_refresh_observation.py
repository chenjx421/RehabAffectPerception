"""Recompute an approved sample without discarding its last usable result.

Private maintenance only. A successful compare-and-swap publishes the new
result; failures leave the old result available. Existing explicit person links
block replacement because observation addresses can change between model runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
PHASE = "arguments"


def load_reviewed_candidate(candidate, digest, manifest, private_root):
    candidate = Path(candidate)
    if (candidate.name != 'candidate.private.json'
            or candidate.parent.parent != private_root
            or not re.fullmatch('[a-f0-9]{64}', digest or '')):
        raise ValueError('invalid_reviewed_candidate')
    manifest_path = candidate.parent / 'input-manifest.private.json'
    for path in (candidate, manifest_path):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('invalid_reviewed_candidate')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 524288:
            raise ValueError('invalid_reviewed_candidate')
    raw = candidate.read_bytes()
    if len(raw) > 524288 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('reviewed_candidate_changed')
    raw_manifest = manifest_path.read_bytes()
    if len(raw_manifest) > 524288 or json.loads(raw_manifest) != manifest:
        raise ValueError('candidate_input_changed')
    return json.loads(raw)


def save_private(path, value):
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        json.dump(value, handle, ensure_ascii=True, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def publish(store, expected, result, archive, input_manifest=None):
    with store.records._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT * FROM demo2_observation_jobs WHERE job_id=?",
                             (expected["job_id"],)).fetchone()
        if current is None or dict(current) != expected or current["status"] != "ready":
            raise ValueError("result_changed")
        if db.execute("SELECT count(*) FROM demo2_observation_person_links WHERE job_id=?",
                      (expected["job_id"],)).fetchone()[0]:
            raise ValueError("explicit_identity_links_present")
        task = store._current(db, dict(current))
        normalized = store._normalize(task, dict(current), result)
        raw = json.dumps(result, ensure_ascii=True, allow_nan=False)
        manifest_raw = store._input_manifest(task, dict(current), input_manifest) if input_manifest is not None else None
        previous_input = None
        if manifest_raw is not None:
            row = db.execute('SELECT * FROM demo2_observation_inputs WHERE job_id=?',
                             (expected['job_id'],)).fetchone()
            previous_input = dict(row) if row is not None else None
        save_private(archive, {"previous_job": expected, "replacement": result,
                               "previous_input": previous_input})
        now = time.time()
        db.execute("""UPDATE demo2_observation_jobs SET result_json=?,normalized_json=?,
                   model=COALESCE(?,model),error_code='',updated_at=? WHERE job_id=?""",
                   (raw,
                    json.dumps(normalized, ensure_ascii=True, allow_nan=False),
                    result.get('model'), now, expected["job_id"]))
        if manifest_raw is not None:
            db.execute('''INSERT INTO demo2_observation_inputs(job_id,result_sha256,input_manifest_json,created_at)
                VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET result_sha256=excluded.result_sha256,
                input_manifest_json=excluded.input_manifest_json,created_at=excluded.created_at''',
                (expected['job_id'], hashlib.sha256(raw.encode('utf-8')).hexdigest(), manifest_raw, now))


def main():
    global PHASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--capture-response", action="store_true")
    parser.add_argument('--model', choices=['glm-5.3-flash', 'glm-5.3', 'qwen3.8-max'])
    parser.add_argument("--accepted-candidate", type=Path)
    parser.add_argument("--accepted-candidate-sha256")
    args = parser.parse_args()
    os.umask(0o077)
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", args.task_id)
            or not re.fullmatch(r"[a-f0-9]{64}", args.source_sha256)
            or args.output.parent != Path("/var/lib/rehabaffect/acceptance-private")
            or args.output.exists() or args.output.parent.is_symlink()):
        raise ValueError("private_new_output_required")
    from rehab_affect.demo2_observation_store import Demo2ObservationStore, _allowed_hashes, _provider_ready
    from rehab_affect.student_record_store import get_demo2_student_store
    from rehab_affect.demo2_observation_model import ObservationModelClient, ObservationModelConfig
    from cloud_observation_frames import load_job_frames, assert_current
    from cloud_observation_worker import _analyze_job

    if args.source_sha256 not in _allowed_hashes() or not _provider_ready():
        raise ValueError("sample_not_authorized")
    PHASE = "load_current_job"
    records = get_demo2_student_store()
    store = Demo2ObservationStore(records)
    with records._connect() as db:
        candidates = db.execute("SELECT * FROM demo2_observation_jobs WHERE task_id=? AND source_sha256=?",
                                (args.task_id, args.source_sha256)).fetchall()
        if len(candidates) != 1 or candidates[0]["status"] != "ready":
            raise ValueError("current_ready_job_required")
        expected = dict(candidates[0])
        task = store._current(db, expected)
        if db.execute("SELECT count(*) FROM demo2_observation_person_links WHERE job_id=?",
                      (expected["job_id"],)).fetchone()[0]:
            raise ValueError("explicit_identity_links_present")
    args.output.mkdir(mode=0o700)
    job = {**expected, "frames": json.loads(expected["samples_json"]),
           "duration_sec": json.loads(task["processing_result_json"])["media"]["duration_sec"]}
    with records._connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_observation_targets'").fetchone()
        if exists:
            # The worker normally supplies this field; maintenance reads the same scope.
            selected = db.execute("SELECT student_ids_json FROM demo2_observation_targets WHERE task_id=? AND owner_account_id=? AND scope_key=? AND source_sha256=?",
                                  (job["task_id"], job["owner_account_id"], job["scope_key"], job["source_sha256"])).fetchone()
            if selected:
                job['selected_student_ids'] = json.loads(selected[0])
    PHASE = "load_frames"
    frames, manifest = load_job_frames(records, store.identities, job)
    save_private(args.output / "input-manifest.private.json", manifest)
    started = time.monotonic()
    PHASE = "model_call"
    if args.capture_response:
        import rehab_affect.demo2_observation_model as adapter
        transport = adapter._https_post
        lock = threading.Lock()
        sequence = [0]
        def captured(config, body):
            response = transport(config, body)
            with lock:
                sequence[0] += 1
                path = args.output / ("provider-response-%02d.private.json" % sequence[0])
                with path.open("xb") as handle:
                    os.chmod(path, 0o600)
                    handle.write(response)
            return response
        adapter._https_post = captured
    if args.accepted_candidate:
        result = load_reviewed_candidate(args.accepted_candidate,
            args.accepted_candidate_sha256, manifest, args.output.parent)
    else:
        if args.accepted_candidate_sha256:
            raise ValueError('candidate_required')
        from dataclasses import replace
        config = ObservationModelConfig.from_env()
        if args.model:
            config = replace(config, model=args.model)
            job = {**job, 'model': args.model}
        result = _analyze_job(ObservationModelClient(config), frames, job)
    PHASE = "validate_result"
    assert_current(records, store.identities, job)
    if load_job_frames(records, store.identities, job)[1] != manifest:
        raise ValueError("evidence_changed")
    store._normalize(task, expected, result)
    save_private(args.output / "candidate.private.json", result)
    observations = [item for frame in result["frames"] for item in frame["observations"]]
    report = {"task_id": args.task_id, "source_verified": True,
              "sample_count": len(frames), "observations": len(observations),
              "localized_observations": sum(item["bbox"] is not None for item in observations),
              "seconds": round(time.monotonic() - started, 3), "published": False,
              "continuous_tracking": False, "real_identity_validated": False}
    if args.publish:
        PHASE = "publish"
        publish(store, expected, result, args.output / "replacement.private.json", input_manifest=manifest)
        report["published"] = True
    save_private(args.output / "summary.json", report)
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        code = getattr(error, "code", None)
        allowed = {"timeout", "transport_error", "invalid_response", "upstream_status", "invalid_input",
                   "invalid_config", "model_refused", "source_unavailable", "source_changed", "invalid_result"}
        print(json.dumps({"ok": False, "error": code if code in allowed else "refresh_failed",
                          "phase": PHASE,
                          "diagnostic": getattr(error, 'diagnostic_code', None)
                              if getattr(error, 'diagnostic_code', None) in {
                                  'response_json','response_envelope','response_schema','bbox_not_proposed',
                                  'person_index_not_proposed','completion_truncated','batch_result_invalid'} else None}), flush=True)
        raise SystemExit(1)
