"""Independent, bounded observation queue; media processing stays responsive."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloud_observation_frames import assert_current, load_job_frames
from rehab_affect.demo2_identity_store import Demo2IdentityStore, IdentityError
from rehab_affect.demo2_media_worker import WorkerLock
from rehab_affect.demo2_observation_model import (
    ObservationModelClient, ObservationModelConfig, ObservationModelError, SampleFrame,
    SCHEMA_VERSION, ERROR_DIAGNOSTICS, _suggestions, _validate_frames,
)
from rehab_affect.demo2_observation_store import Demo2ObservationStore, ObservationError
from rehab_affect.student_record_store import get_demo2_student_store


ADAPTER_ERROR_CODES = frozenset({
    "disabled", "invalid_config", "invalid_input", "request_too_large", "timeout",
    "transport_error", "upstream_status", "redirect_blocked", "response_too_large",
    "invalid_response", "model_refused",
})
MODEL_JOB_BUDGET_SECONDS = 210.0


def _analyze_batch(client, samples, arguments, deadline):
    # Retry a transient timeout once, inside the job deadline. Invalid evidence is never retried.
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 0.1:
            raise ObservationModelError('timeout')
        bounded = client
        if isinstance(client, ObservationModelClient) and remaining < client.config.timeout_seconds:
            bounded = ObservationModelClient(replace(client.config, timeout_seconds=min(90, remaining)))
        try:
            return bounded.analyze(samples, **arguments)
        except ObservationModelError as error:
            if error.code != 'timeout' or attempt == 1:
                raise


def _analyze_job(client, frames, job):
    if not 1 <= len(frames) <= 8:
        raise ObservationModelError("invalid_input")
    samples = [SampleFrame(**frame) for frame in frames]
    if any(right.timestamp_sec <= left.timestamp_sec for left, right in zip(samples, samples[1:])):
        raise ObservationModelError("invalid_input")
    if isinstance(client, ObservationModelClient) and client.config.timeout_seconds > 90:
        client = ObservationModelClient(replace(client.config, timeout_seconds=90))
    config = getattr(client, "config", None)
    if isinstance(config, ObservationModelConfig) and job.get("model") and job["model"] != config.model:
        raise ObservationModelError("invalid_input")
    provenance = {key: job[key] for key in ("task_id", "source_sha256", "frame_revision")}
    arguments = {**provenance, "media_duration_sec": job["duration_sec"]}
    deadline = time.monotonic() + MODEL_JOB_BUDGET_SECONDS
    if len(samples) <= 4:
        return _analyze_batch(client, samples, arguments, deadline)
    if not isinstance(config, ObservationModelConfig):
        raise ObservationModelError("invalid_config")
    batches = [samples[index:index + 2] for index in range(0, len(samples), 2)]
    # A shared deadline bounds all calls; no partial batch is published as a complete result.
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(_analyze_batch, client, batch, arguments, deadline) for batch in batches]
        results = [future.result() for future in pending]
    metadata = {
        "schema_version": SCHEMA_VERSION, **provenance, "model": config.model,
        "requires_teacher_review": True, "identity_recognition_performed": False,
        "scoring_performed": False,
    }
    try:
        for batch, result in zip(batches, results):
            timestamps = [float(sample.timestamp_sec) for sample in batch]
            coverage = {
                "scope": "sampled_frames_only", "sample_timestamps_sec": timestamps,
                "sample_count": len(batch), "media_duration_sec": job["duration_sec"],
                "continuous_coverage": False, "full_lesson": False,
            }
            if (not isinstance(result, dict) or set(result) != set(metadata) | {"coverage", "frames", "teacher_suggestions"}
                    or any(result[key] != value for key, value in metadata.items())
                    or any(type(result[key]) is not bool for key in (
                        "requires_teacher_review", "identity_recognition_performed", "scoring_performed"))
                    or result["coverage"] != coverage):
                raise ValueError
            reported = result["coverage"]
            if (type(reported["sample_count"]) is not int
                    or reported["continuous_coverage"] is not False or reported["full_lesson"] is not False
                    or any(type(t) not in (int, float) for t in reported["sample_timestamps_sec"])
                    or (reported["media_duration_sec"] is not None
                        and type(reported["media_duration_sec"]) not in (int, float))):
                raise ValueError
            _validate_frames({"frames": result["frames"]}, timestamps)
            if result["teacher_suggestions"] != _suggestions(result["frames"]):
                raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ObservationModelError("invalid_response", diagnostic_code="batch_result_invalid") from None
    rows = sorted((row for result in results for row in result["frames"]), key=lambda row: row["timestamp_sec"])
    suggestions = sorted((row for result in results for row in result["teacher_suggestions"]),
                         key=lambda row: row["timestamp_sec"])
    return {**metadata, "coverage": {
        **results[0]["coverage"], "sample_timestamps_sec": [row["timestamp_sec"] for row in rows],
        "sample_count": len(samples),
    }, "frames": rows, "teacher_suggestions": suggestions}


def process_one(records, store, client):
    job = store.claim_next(lease_seconds=300)
    if job is None:
        return False
    started = time.monotonic()
    try:
        identities = store.identities
        frames, manifest = load_job_frames(records, identities, job)
        assert_current(records, identities, job)
        result = _analyze_job(client, frames, job)
        assert_current(records, identities, job)
        _, current_manifest = load_job_frames(records, identities, job)
        if current_manifest != manifest:
            raise ValueError("evidence_changed")
        store.finish(job, result, input_manifest=manifest)
        localized = sum(observation["bbox"] is not None
                        for frame in result["frames"] for observation in frame["observations"])
        group_only = sum(observation["bbox"] is None
                         for frame in result["frames"] for observation in frame["observations"])
        print(json.dumps({
            "event": "observation_ready", "task_id": job["task_id"],
            "samples": len(manifest), "seconds": round(time.monotonic() - started, 3),
            "localized_observations": localized, "group_only_observations": group_only,
        }), flush=True)
    except Exception as error:
        adapter_code, adapter_detail = None, None
        if isinstance(error, ObservationModelError):
            adapter_code = error.code if isinstance(error.code, str) and error.code in ADAPTER_ERROR_CODES else "unknown_error"
            detail = getattr(error, "diagnostic_code", None)
            adapter_detail = detail if isinstance(detail, str) and detail in ERROR_DIAGNOSTICS else adapter_code
            # Persist the bounded cause as well as logging it, so a failed job
            # remains diagnosable through the authorized workspace after restart.
            code = adapter_code if adapter_code in ADAPTER_ERROR_CODES else "invalid_result"
        elif isinstance(error, (IdentityError, ObservationError, ValueError, OSError)):
            code = "source_unavailable"
        else:
            code = "model_failed"
        store.fail(job, code)
        print(json.dumps({"event": "observation_failed", "task_id": job["task_id"],
                          "code": code, "adapter_error_code": adapter_code,
                          "adapter_error_detail": adapter_detail}), flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--enqueue", action="append", default=[])
    args = parser.parse_args()
    os.umask(0o077)
    database = Path(os.environ.get("REHAB_DEMO2_DB_PATH", ""))
    if not database.is_absolute() or not database.is_file():
        print(json.dumps({"ok": False, "reason": "existing_database_required"}))
        return 2
    records = get_demo2_student_store()
    store = Demo2ObservationStore(records)
    store.cleanup_expired()
    config = ObservationModelConfig.from_env()
    lock = WorkerLock(records.db_path.parent / ".observations.lock")
    if not lock.acquire():
        print(json.dumps({"ok": False, "reason": "observation_worker_busy"}))
        return 2
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    client = ObservationModelClient(config)
    try:
        for task_id in args.enqueue:
            if not config.enabled:
                return 2
            store.enqueue(task_id, model=config.model)
        if args.once:
            if not config.enabled:
                return 2
            return 0 if process_one(records, store, client) else 3
        next_discovery = 0
        next_cleanup = 0
        while not stop.is_set():
            if time.monotonic() >= next_cleanup:
                store.cleanup_expired()
                next_cleanup = time.monotonic() + 60
            if not config.enabled:
                stop.wait(2)
                continue
            if time.monotonic() >= next_discovery:
                store.enqueue_authorized_ready()
                next_discovery = time.monotonic() + 30
            if not process_one(records, store, client):
                stop.wait(2)
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
