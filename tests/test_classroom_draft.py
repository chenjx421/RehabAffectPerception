"""Cloud classroom draft contracts using synthetic, source-bound manifests only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PHASES = ("\u524d\u6bb5", "\u4e2d\u6bb5", "\u540e\u6bb5")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloud = _load(
    "rehab_affect._classroom_draft_test_cloud",
    ROOT / ".runtime/cloud_release_overrides/demo2_course_analysis.py",
)
baseline = _load(
    "rehab_affect._classroom_draft_test_baseline",
    ROOT / "src/rehab_affect/demo2_course_analysis.py",
)


def _bind(identity, task, raw):
    text = json.dumps(raw, ensure_ascii=True)
    task["processing_result_json"] = text
    identity["frame_revision"] = hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(motions=(0.01, 0.03, 0.08, 0.02, 0.2, 0.04), *,
            has_audio=True, rms=None, coverage=None, lengths=None):
    count = len(motions)
    lengths = [20] * count if lengths is None else lengths
    rms = [0.01 * (index + 1) for index in range(count)] if rms is None else rms
    coverage = [1] * count if coverage is None else coverage
    assert count and len(lengths) == len(rms) == len(coverage) == count
    segments = []
    start = 0
    for motion, energy, ratio, length in zip(motions, rms, coverage, lengths):
        end = start + length
        audio = {"available": False}
        if has_audio:
            samples = round(length * 16000)
            observed = round(samples * ratio)
            audio = {
                "available": bool(observed), "sample_rate": 16000, "channels": 1,
                "sample_count": samples, "observed_sample_count": observed,
                "padded_sample_count": samples - observed,
                "coverage_ratio": observed / samples,
                "coverage_intervals": ([{"start_sec": start,
                                        "end_sec": start + observed / 16000}]
                                       if observed else []),
                "rms": energy if observed else None,
                "energy_activity_ratio": 0.25 if observed else None,
            }
        segments.append({
            "start_sec": start, "end_sec": end,
            "visual": {"sampled_frames": 2, "mean_motion": motion,
                       "mean_brightness": 80 + len(segments), "mean_sharpness": 20,
                       "samples": [{"timestamp_sec": start},
                                   {"timestamp_sec": start + min(1, length / 2)}]},
            "audio": audio,
        })
        start = end
    raw = {
        "task_id": "synthetic-classroom-task", "source_sha256": "a" * 64,
        "analysis_version": "demo2_media_evidence_v1.1", "analysis_status": "evidence_ready",
        "media": {"duration_sec": start, "duration_basis": "decoded_video_frame_end",
                  "width": 160, "height": 96, "fps": 10, "has_audio": has_audio,
                  "audio_status": "extracted" if has_audio else "absent"},
        "summary": {"decoded_frames": round(start * 10), "sampled_frames": count * 2,
                    "segment_count": count},
        "provenance": {"network_used": False, "models_downloaded": False},
        "segments": segments,
    }
    identity = {
        "task_id": raw["task_id"], "students": [], "bindings": [],
        "course_name": "Synthetic Course", "course_id": "synthetic-course",
        "school_context": {"school_name": "Synthetic School"},
        "media_available": True, "can_edit": True, "frames": [],
    }
    task = {"task_id": raw["task_id"], "sha256": raw["source_sha256"],
            "upload_status": "completed", "analysis_status": "evidence_ready",
            "expires_at": "2100-01-01T00:00:00+00:00"}
    _bind(identity, task, raw)
    return identity, task, raw


def _workspace(**kwargs):
    identity, task, _ = _source(**kwargs)
    work = cloud.build_workspace(identity, task, [])
    assert work["technical_evidence"]["source_bound"] is True
    assert work["classroom_draft"]["ready"] is True
    return work


def _record(record_id="synthetic-record", student_id="known", *,
            reviewed=True, status="current", score=None):
    return {
        "record_id": record_id, "version": 1, "student_id": student_id,
        "reviewed": reviewed, "evidence_status": status,
        "assessment": {"overall_score": score}, "start_sec": 0, "end_sec": 20,
        "goal_id": "synthetic-goal", "evidence": "Synthetic teacher observation",
        "teacher_prompt": "Synthetic prompt", "student_response": "Synthetic response",
        "support_level": "visual", "observed_state": "participating",
    }


def _binding(student_id="known", **changes):
    return {"student_id": student_id, "status": "confirmed", "current_revision": True,
            "role": "student", **changes}


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def _phases(draft):
    return [section for section in draft["sections"]
            if any(section["title"].startswith(label) for label in PHASES)]


def test_source_bound_draft_is_ready_without_teacher_records_and_does_not_mutate_inputs():
    identity, task, _ = _source()
    original = copy.deepcopy((identity, task))
    work = cloud.build_workspace(identity, task, [])
    draft = work["classroom_draft"]
    assert work["technical_evidence"]["source_bound"] is True
    assert draft["ready"] is True
    assert draft["kind"] == "automatic_classroom_draft"
    assert draft["task_id"] == task["task_id"]
    assert draft["frame_revision"] == identity["frame_revision"]
    assert draft["method"] and draft["scope"] and draft["limitations"]
    assert draft["summary"]["segment_count"] == len(draft["timeline"]) == 6
    assert draft["summary"]["linked_students"] == 0
    assert draft["students"] == work["people"] == work["records"] == []
    assert work["summary"]["scored"] == work["summary"]["records"] == 0
    assert work["report"]["ready"] is False
    assert work["automatic_report"]["ready"] is True
    assert draft["character_count"] == sum(len(s["text"]) for s in draft["sections"])
    assert json.loads(json.dumps(draft, allow_nan=False)) == draft
    assert cloud.build_workspace(identity, task, []) == work
    assert (identity, task) == original


@pytest.mark.parametrize("mutation,reason", [
    ("source", "source_mismatch"), ("task", "source_mismatch"),
    ("identity_task", "source_mismatch"), ("empty_hash", "source_mismatch"),
    ("revision", "stale_result_revision"), ("media", "source_unavailable"),
    ("deleted", "source_unavailable"), ("expired", "source_unavailable"),
    ("upload", "source_unavailable"), ("processing", "source_unavailable"),
    ("version", "unsupported_analysis_version"), ("coverage", "invalid_manifest"),
    ("interval", "invalid_manifest"), ("gap", "invalid_manifest"),
    ("tail", "invalid_manifest"), ("nan", "invalid_manifest"),
])
def test_real_upstream_gate_blocks_draft_for_invalid_source_or_evidence(mutation, reason):
    identity, task, raw = _source()
    if mutation == "source":
        raw["source_sha256"] = "b" * 64
    elif mutation == "task":
        raw["task_id"] = "other-synthetic-task"
    elif mutation == "identity_task":
        identity["task_id"] = "other-synthetic-task"
    elif mutation == "empty_hash":
        raw["source_sha256"] = task["sha256"] = ""
    elif mutation == "media":
        identity["media_available"] = False
    elif mutation == "deleted":
        task["raw_media_deleted_at"] = "2000-01-01T00:00:00+00:00"
    elif mutation == "expired":
        task["expires_at"] = "2000-01-01T00:00:00+00:00"
    elif mutation == "upload":
        task["upload_status"] = "uploading"
    elif mutation == "processing":
        task["analysis_status"] = "processing"
    elif mutation == "version":
        raw["analysis_version"] = "unsupported"
    elif mutation == "coverage":
        raw["segments"][0]["audio"]["coverage_ratio"] = 0.5
    elif mutation == "interval":
        raw["segments"][0]["audio"]["coverage_intervals"][0]["end_sec"] = 21
    elif mutation == "gap":
        raw["segments"][-1]["start_sec"] += 1
    elif mutation == "tail":
        raw["segments"][-1]["visual"]["mean_motion"] = -1
    elif mutation == "nan":
        raw["segments"][-1]["visual"]["mean_motion"] = float("nan")
    _bind(identity, task, raw)
    if mutation == "revision":
        identity["frame_revision"] = "stale-synthetic-revision"
    work = cloud.build_workspace(identity, task, [])
    assert work["technical_evidence"]["reason_code"] == reason
    assert work["technical_evidence"]["source_bound"] is False
    assert work["automatic_report"]["ready"] is False
    draft = work["classroom_draft"]
    assert draft["ready"] is False
    assert draft["timeline"] == draft["key_clips"] == draft["sections"] == draft["students"] == []
    assert draft["summary"] == {}
    assert draft["character_count"] == 0


@pytest.mark.parametrize("text", ["[]", "null", "{broken", '{"task_id":"a","task_id":"b"}'])
def test_malformed_manifest_cannot_produce_a_partial_draft(text):
    identity, task, _ = _source()
    task["processing_result_json"] = text
    identity["frame_revision"] = hashlib.sha256(text.encode()).hexdigest()
    work = cloud.build_workspace(identity, task, [])
    assert work["technical_evidence"]["reason_code"] == "invalid_manifest"
    assert work["classroom_draft"]["ready"] is False
    assert work["classroom_draft"]["timeline"] == []


def test_absent_audio_stays_null_in_summary_and_every_timeline_row():
    draft = _workspace(has_audio=False)["classroom_draft"]
    assert draft["summary"]["audio_coverage_ratio"] is None
    for row in draft["timeline"]:
        assert row["audio_status"] == "absent"
        assert row["audio_energy_index"] is row["raw_audio_rms"] is None


def test_uncovered_audio_stays_null_but_observed_silence_is_a_real_zero():
    draft = _workspace(motions=(0.1, 0.2, 0.3), rms=(0, 0, 0),
                       coverage=(1, 0, 0.5), lengths=(20, 20, 40))["classroom_draft"]
    assert draft["summary"]["audio_coverage_ratio"] == pytest.approx(0.5)
    assert [row["audio_status"] for row in draft["timeline"]] == ["covered", "uncovered", "partial"]
    assert [row["audio_energy_index"] for row in draft["timeline"]] == [0, None, 0]
    assert [row["raw_audio_rms"] for row in draft["timeline"]] == [0, None, 0]


@pytest.mark.parametrize("value,index", [(0, 0), (0.2, 50)])
@pytest.mark.parametrize("count", [1, 9])
def test_flat_signals_are_not_high_activity_or_behavior_events(value, index, count):
    draft = _workspace(motions=[value] * count, rms=[value] * count)["classroom_draft"]
    assert [row["motion_index"] for row in draft["timeline"]] == [index] * count
    assert [row["audio_energy_index"] for row in draft["timeline"]] == [index] * count
    label = "\u53d8\u5316\u63a5\u8fd1" if value else "\u672a\u6d4b\u5f97\u753b\u9762\u53d8\u5316"
    assert all(row["motion_level"] == label for row in draft["timeline"])
    assert all("\u4e0d\u6807\u4e3a\u884c\u4e3a\u4e8b\u4ef6" in row["description"]
               for row in draft["timeline"])
    assert draft["key_clips"]
    assert all(clip["title"] == "\u65f6\u95f4\u8f74\u4ee3\u8868\u7247\u6bb5"
               for clip in draft["key_clips"])
    assert [clip["segment_index"] for clip in draft["key_clips"]] == ([0] if count == 1 else [0, 4, 8])


def test_relative_indexes_use_p10_p90_range_and_retain_raw_measurements():
    values = [n / 16 for n in range(11)]
    draft = _workspace(motions=values, rms=list(reversed(values)))["classroom_draft"]
    expected = [0, 0, 12, 25, 38, 50, 62, 75, 88, 100, 100]
    assert [row["motion_index"] for row in draft["timeline"]] == expected
    assert [row["audio_energy_index"] for row in draft["timeline"]] == expected[::-1]
    assert [row["raw_motion"] for row in draft["timeline"]] == values
    assert [row["raw_audio_rms"] for row in draft["timeline"]] == values[::-1]
    assert draft["summary"]["average_motion"] == pytest.approx(sum(values) / len(values))
    assert draft["key_clips"][0]["segment_index"] == 10


def test_collapsed_percentile_range_keeps_a_real_outlier_without_dividing_by_zero():
    draft = _workspace(motions=[0] * 10 + [1], has_audio=False)["classroom_draft"]
    assert [row["motion_index"] for row in draft["timeline"]] == [0] * 10 + [100]
    assert draft["key_clips"][0]["segment_index"] == 10


def test_missing_motion_is_not_converted_to_zero_or_a_key_event():
    draft = _workspace(motions=(None, None, None), has_audio=False)["classroom_draft"]
    assert draft["summary"]["observed_motion_segments"] == 0
    assert draft["summary"]["average_motion"] is None
    assert draft["summary"]["peak_motion_time_sec"] is None
    assert draft["key_clips"] == []
    assert all(row["motion_index"] is row["raw_motion"] is None for row in draft["timeline"])


@pytest.mark.parametrize("motions", [(0.25,) * 15, tuple(n / 16 for n in range(15))])
def test_key_clips_are_unique_spaced_bounded_and_match_real_segments(motions):
    identity, task, raw = _source(motions=motions, lengths=[20] * 14 + [0.5])
    draft = cloud.build_workspace(identity, task, [])["classroom_draft"]
    assert draft["ready"] is True
    clips = draft["key_clips"]
    assert 1 <= len(clips) <= 6
    assert len({clip["segment_index"] for clip in clips}) == len(clips)
    for clip in clips:
        segment = raw["segments"][clip["segment_index"]]
        assert 0 <= clip["start_sec"] < clip["end_sec"] <= raw["media"]["duration_sec"]
        assert (clip["start_sec"], clip["end_sec"]) == (segment["start_sec"], segment["end_sec"])
        assert clip["title"] and clip["reason"]
    starts = sorted(clip["start_sec"] for clip in clips)
    assert all(right - left >= 40 for left, right in zip(starts, starts[1:]))
    assert any(clip["end_sec"] == 280.5 for clip in clips)


def test_phase_summaries_use_actual_local_peaks_and_audio_coverage():
    draft = _workspace(motions=(0.01, 0.03, 0.02, 0.08, 0.04, 0.06, 0.1, 0.2, 0.12),
                       coverage=(1, 1, 1, 0, 0, 0, 1, 0.5, 0))["classroom_draft"]
    phases = _phases(draft)
    assert len(phases) == 3
    expected = [
        ("00:00", "01:00", "0.03000", "00:20", "00:40", 3),
        ("01:00", "02:00", "0.08000", "01:00", "01:20", 0),
        ("02:00", "03:00", "0.20000", "02:20", "02:40", 2),
    ]
    for phase, (start, end, peak, peak_start, peak_end, covered) in zip(phases, expected):
        assert start in phase["title"] and end in phase["title"]
        assert all(value in phase["text"] for value in (peak, peak_start, peak_end))
        assert "3 \u4e2a\u65f6\u95f4\u7247" in phase["text"]
        assert f"\u97f3\u9891\u81f3\u5c11\u90e8\u5206\u8986\u76d6 {covered} \u4e2a" in phase["text"]


def test_single_segment_has_only_its_nonempty_phase_without_padding_to_a_word_target():
    draft = _workspace(motions=(0.125,), lengths=(2,), has_audio=False)["classroom_draft"]
    phases = _phases(draft)
    assert len(phases) == 1
    assert phases[0]["title"].startswith(PHASES[1])
    assert "0.12500" in phases[0]["text"]
    assert draft["character_count"] == sum(len(s["text"]) for s in draft["sections"])


def test_draft_content_and_revision_change_with_measured_source_not_just_template_text():
    identity, task, raw = _source()
    before = cloud.build_workspace(identity, task, [])["classroom_draft"]
    raw["segments"][0]["visual"]["mean_motion"] = 0.75
    _bind(identity, task, raw)
    after = cloud.build_workspace(identity, task, [])["classroom_draft"]
    assert before["task_id"] == after["task_id"]
    assert before["frame_revision"] != after["frame_revision"]
    assert before["timeline"] != after["timeline"]
    assert before["summary"] != after["summary"]
    assert before["key_clips"] != after["key_clips"]
    assert _phases(before) != _phases(after)


def test_student_summaries_only_include_known_workspace_people_and_current_reviews():
    identity, task, _ = _source()
    ids = ("known", "record-only", "roster-only", "revoked", "stale", "teacher")
    identity["students"] = [{"student_id": sid, "display_name": f"Synthetic {sid}",
                             "diagnosis": "SYNTHETIC_EXCLUDED_DIAGNOSIS",
                             "iep": "SYNTHETIC_EXCLUDED_IEP"} for sid in ids]
    identity["bindings"] = [
        _binding(), _binding(), _binding("unknown"),
        _binding("revoked", status="revoked"), _binding("stale", current_revision=False),
        _binding("teacher", role="teacher"),
    ]
    records = [_record(), _record("pending", reviewed=False),
               _record("stale", status="needs_reconfirmation"),
               _record("record-only", "record-only", reviewed=False),
               _record("unknown", "unknown", reviewed=False)]
    work = cloud.build_workspace(identity, task, records)
    draft = work["classroom_draft"]
    assert {p["student_id"] for p in work["people"]} == {"known", "record-only"}
    students = {p["student_id"]: p for p in draft["students"]}
    assert set(students) == {"known", "record-only"}
    assert draft["summary"]["linked_students"] == 2
    assert students["known"]["binding_count"] == 2
    assert students["known"]["record_count"] == 3
    assert students["known"]["reviewed_count"] == 1
    assert students["record-only"]["binding_count"] == students["record-only"]["reviewed_count"] == 0
    assert students["record-only"]["record_count"] == 1
    assert "SYNTHETIC_EXCLUDED_" not in json.dumps(draft)


def test_draft_schema_never_contains_educational_scores_or_unvalidated_metadata():
    identity, task, raw = _source()
    identity["students"] = [{"student_id": "known", "display_name": "Synthetic Student"}]
    raw.update(educational_score=9.9, transcript="SYNTHETIC_EXCLUDED_TRANSCRIPT",
               source_path="SYNTHETIC_EXCLUDED_PATH", token="SYNTHETIC_EXCLUDED_TOKEN")
    raw["segments"][0]["visual"].update(student_id="unconfirmed", attention_score=99)
    raw["segments"][0]["audio"]["transcript"] = "SYNTHETIC_EXCLUDED_SEGMENT"
    _bind(identity, task, raw)
    work = cloud.build_workspace(identity, task, [_record(score=7.5)])
    draft = work["classroom_draft"]
    assert draft["ready"] is True
    keys = set(_keys(draft))
    assert not {key for key in keys if "score" in key.lower()}
    assert not (keys & {"assessment", "grade", "diagnosis", "iep", "emotion", "attention",
                        "mastery", "accuracy", "independence", "consistency", "transfer"})
    assert "SYNTHETIC_EXCLUDED_" not in json.dumps(draft)
    assert work["records"][0]["assessment"]["overall_score"] == 7.5


@pytest.mark.parametrize("record_state,ready", [
    ("none", False), ("pending", False), ("stale", False), ("current", True),
])
def test_legacy_teacher_report_is_retained_without_changing_its_review_gate(record_state, ready):
    identity, task, _ = _source()
    identity["students"] = [{"student_id": "known", "display_name": "Synthetic Student"}]
    records = [] if record_state == "none" else [_record(
        reviewed=record_state != "pending",
        status="needs_reconfirmation" if record_state == "stale" else "current",
        score=7.5 if record_state == "current" else None,
    )]
    original = copy.deepcopy((identity, task, records))
    old = baseline.build_workspace(identity, task, records)
    work = cloud.build_workspace(identity, task, records)
    assert work["report"] == old["report"]
    assert work["summary"] == old["summary"]
    assert work["people"] == old["people"]
    assert work["records"] == old["records"]
    assert work["report"]["ready"] is ready
    assert work["classroom_draft"]["ready"] is True
    assert work["automatic_report"]["ready"] is True
    assert work["classroom_draft"] != work["report"] != work["automatic_report"]
    assert (identity, task, records) == original
