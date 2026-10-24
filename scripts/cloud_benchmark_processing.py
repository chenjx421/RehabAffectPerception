"""Compare processing implementations in a private, independent test database."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample", default="Sample01")
    args = parser.parse_args()
    os.umask(0o077)
    parent = Path("/var/lib/rehabaffect/acceptance-private").resolve()
    if args.output.exists() or args.output.resolve().parent != parent:
        raise ValueError("New private output directory required")
    live = sqlite3.connect("file:/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3?mode=ro", uri=True)
    try:
        busy = live.execute("SELECT count(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')").fetchone()[0]
    finally:
        live.close()
    if busy:
        print(json.dumps({"ok": False, "reason": "live_worker_busy"}))
        return 2
    samples = parent / "samples"
    manifest = json.loads((samples / "samples.private.json").read_text())
    row = next(item for item in manifest["samples"] if item["sample_id"] == args.sample)
    source = (samples / row["relative_path"]).resolve(strict=True)
    if not source.is_relative_to(samples) or source.is_symlink():
        raise ValueError("Invalid sample")
    args.output.mkdir(mode=0o700)
    prefix = secrets.token_urlsafe(24)
    os.environ["REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX"] = prefix
    from rehab_affect.student_record_store import Demo2StudentRecordStore
    records = Demo2StudentRecordStore(args.output / "benchmark.sqlite3", args.output / "documents")
    account = records.authenticate_account("school_uploader_01", prefix + "school_uploader_01")
    token = records.create_account_session(account)["token"]
    records.save_account_school_context(token, {
        "city": "Engineering benchmark", "district": "Private test",
        "school_name": "Private processing benchmark",
    })
    size, chunk_size = source.stat().st_size, 4 * 1024 * 1024
    task = records.create_video_task({
        "account_id": account["account_id"], "account_session_token": token,
        "channel_id": "channel_1", "session_id": "processing-benchmark",
        "course_id": "processing-benchmark", "course_name": "Processing benchmark",
        "uploader_name": "Engineering test", "filename": "Sample.mp4",
        "byte_size": size, "total_chunks": (size + chunk_size - 1) // chunk_size,
    })
    with source.open("rb") as handle:
        index = 0
        while block := handle.read(chunk_size):
            records.append_video_chunk({
                "task_id": task["task_id"], "account_id": account["account_id"],
                "chunk_index": index, "content_base64": base64.b64encode(block).decode("ascii"),
            })
            index += 1
    claim = records.claim_next_video_analysis()
    if claim["sha256"] != row["sha256"]:
        raise ValueError("Source checksum mismatch")
    spec = importlib.util.spec_from_file_location("benchmark_engine", args.engine)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    calls = 0
    database_seconds = 0.0
    stages = {}
    current_stage = None
    stage_started = started = last_print = time.monotonic()

    def progress(percent, stage):
        nonlocal calls, database_seconds, current_stage, stage_started, last_print
        now = time.monotonic()
        if stage != current_stage:
            if current_stage:
                stages[current_stage] = stages.get(current_stage, 0) + now - stage_started
            current_stage, stage_started = stage, now
        before = time.monotonic()
        records.update_video_analysis_progress(claim["task_id"], stage, percent)
        database_seconds += time.monotonic() - before
        calls += 1
        if now - last_print >= 20:
            print(json.dumps({"stage": stage, "percent": percent, "elapsed": round(now - started, 2)}), flush=True)
            last_print = now

    result = engine.process_video_task(claim, Path(claim["analysis_dir"]), progress=progress)
    records.finish_video_analysis(claim["task_id"], result)
    elapsed = time.monotonic() - started
    stages[current_stage] = stages.get(current_stage, 0) + time.monotonic() - stage_started
    # Normalize run-specific paths only; preserve every measured value and image byte.
    normalized = json.loads(json.dumps(result))
    normalized.pop("task_id", None)
    normalized.pop("performance", None)
    normalized.pop("processing_timings", None)
    frame_digests = []
    for segment in normalized["segments"]:
        for sample in segment["visual"]["samples"]:
            image = Path(claim["analysis_dir"]) / sample["image_path"]
            frame_digests.append(hashlib.sha256(image.read_bytes()).hexdigest())
            sample["image_path"] = image.name
    audio = result["artifacts"].get("audio")
    audio_hash = hashlib.sha256((Path(claim["analysis_dir"]) / audio).read_bytes()).hexdigest() if audio else None
    normalized.pop("artifacts", None)
    report = {
        "ok": True, "sample": args.sample, "source_sha256": claim["sha256"],
        "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
        "processing_seconds": round(elapsed, 3), "progress_callbacks": calls,
        "database_progress_seconds": round(database_seconds, 3),
        "stages": {key: round(value, 3) for key, value in stages.items()},
        "decoded_frames": result["summary"]["decoded_frames"],
        "sampled_frames": result["summary"]["sampled_frames"],
        "audio_sha256": audio_hash,
        "images_sha256": hashlib.sha256("".join(frame_digests).encode()).hexdigest(),
        "evidence_sha256": hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
        "network_upload_measured": False, "production_database_modified": False,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
