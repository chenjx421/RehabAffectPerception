"""Pure student insight projections; synthetic inputs, no stores or services."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rehab_affect._student_insights_test_cloud",
    ROOT / ".runtime/cloud_student_release/demo2_course_analysis.py",
)
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)

BOX = {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}
OTHER_BOX = {"x": 0.65, "y": 0.1, "width": 0.2, "height": 0.3}


def _observation(oid="o0000", *, frame="f0", time=0, behavior="hand_raised",
                 box=None, person="same-model-person", **changes):
    return {
        "observation_id": oid, "frame_key": frame, "time_sec": time,
        "person_id": person, "bbox": dict(BOX if box is None else box),
        "behavior": behavior, "observation": behavior,
        "confidence": None, "reviewed": False, "source_type": "machine_observation",
        **changes,
    }


def _binding(bid="binding-a", sid="student-a", *, frame="f0", time=0,
             box=None, **changes):
    return {
        "binding_id": bid, "student_id": sid, "task_id": "synthetic-task",
        "owner_account_id": "synthetic-owner", "scope_key": "synthetic-scope",
        "frame_key": frame, "time_sec": time, "bbox": dict(BOX if box is None else box),
        "source_sha256": "a" * 64, "frame_revision": "b" * 64,
        "status": "confirmed", "current_revision": True, "role": "student",
        **changes,
    }


@pytest.fixture
def source():
    task = {"task_id": "synthetic-task", "account_id": "synthetic-owner", "sha256": "a" * 64}
    frames = [{"frame_key": "f0", "time_sec": 0}, {"frame_key": "f1", "time_sec": 20}]
    identity = {
        "task_id": task["task_id"], "frame_revision": "b" * 64,
        "scope_key": "synthetic-scope", "media_available": True,
        "frames": frames, "bindings": [_binding()],
        "students": [
            {"student_id": "student-a", "display_name": "Synthetic A"},
            {"student_id": "student-b", "display_name": "Synthetic B"},
        ],
    }
    public = {
        "job_id": "synthetic-job", "task_id": task["task_id"],
        "source_sha256": task["sha256"], "frame_revision": identity["frame_revision"],
        "owner_account_id": task["account_id"], "scope_key": identity["scope_key"],
        "status": "ready", "samples": copy.deepcopy(frames),
        "observations": [_observation()], "reviewed": False,
        "teacher_review_status": "not_reviewed", "source_type": "machine_observation",
        "result": {
            "schema_version": "visible_observation_v1", "model": "synthetic-model",
            "coverage": {"scope": "sampled_frames_only", "sample_timestamps_sec": [0, 20],
                         "sample_count": 2, "media_duration_sec": 40,
                         "continuous_coverage": False, "full_lesson": False},
            "frames": [
                {"timestamp_sec": 0, "observations": [{"behavior": "hand_raised", "bbox": dict(BOX)}]},
                {"timestamp_sec": 20, "observations": []},
            ],
            "teacher_suggestions": [{"timestamp_sec": 0,
                                     "code": "review_visible_turn_opportunity",
                                     "evidence_behaviors": ["hand_raised"]}],
            "requires_teacher_review": True, "identity_recognition_performed": False,
            "scoring_performed": False,
        },
    }
    return public, identity, task


def _project(source, links=None):
    return cloud.build_student_insights(*source, links)


def _student(result, sid="student-a"):
    return next(person for person in result["students"] if person["student_id"] == sid)


def _dimensions(person):
    return {dimension["key"]: dimension for dimension in person["dimensions"]}


def _all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_source_bound_projection_preserves_canonical_input_and_all_nested_inputs(source):
    links = {("same-model-person", "f0"): "binding-a"}
    before = copy.deepcopy((source, links))
    result = _project(source, links)
    public, identity, task = source
    assert result["ready"] is True
    assert result["task_id"] == task["task_id"]
    assert result["job_id"] == public["job_id"]
    assert result["source_sha256"] == task["sha256"]
    assert result["frame_revision"] == identity["frame_revision"]
    assert _student(result)["display_name"] == "Synthetic A"
    assert _student(result)["identity_status"] == "confirmed"
    assert result["anonymous_people"] == []
    assert result["summary"]["named_students"] == 1
    assert result["summary"]["sample_count"] == result["summary"]["observation_count"] == 1
    assert result["group"]["scope"] == "confirmed_students"
    assert (source, links) == before
    assert _project(source, links) == result
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("target,key,value", [
    (0, "status", "pending"), (0, "status", "failed"),
    (0, "task_id", "other-task"), (1, "task_id", "other-task"),
    (0, "source_sha256", "c" * 64), (0, "frame_revision", "c" * 64),
    (0, "owner_account_id", "other-owner"), (0, "scope_key", "other-scope"),
    (1, "media_available", False), (0, "source_sha256", None),
    (0, "frame_revision", None),
])
def test_source_gate_rejects_mismatched_unavailable_or_unready_inputs(source, target, key, value):
    source[target][key] = value
    result = _project(source)
    assert result["ready"] is False
    assert result["students"] == result["anonymous_people"] == []
    assert result["summary"]["observation_count"] == 0


@pytest.mark.parametrize("key,value", [
    ("status", "revoked"), ("current_revision", False),
    ("source_sha256", "c" * 64), ("frame_revision", "c" * 64),
    ("time_sec", 1), ("frame_key", "missing-frame"), ("role", "unknown"),
    ("student_id", "outside-roster"),
    ("task_id", "other-task"), ("owner_account_id", "other-owner"),
    ("scope_key", "other-school-scope"),
])
def test_identity_binding_must_be_current_same_source_and_same_scope(source, key, value):
    source[1]["bindings"][0][key] = value
    result = _project(source)
    assert result["students"] == [], f"Invalid binding {key}={value!r} was attributed"
    assert result["summary"]["named_students"] == 0
    assert len(result["anonymous_people"]) == 1


@pytest.mark.parametrize("mutation", ["no_frame", "no_sample", "row_time", "sample_time", "frame_time"])
def test_observation_must_match_both_exact_frame_and_claimed_sample(source, mutation):
    public, identity, _ = source
    if mutation == "no_frame":
        identity["frames"] = identity["frames"][1:]
    elif mutation == "no_sample":
        public["samples"] = public["samples"][1:]
    elif mutation == "row_time":
        public["observations"][0]["time_sec"] = 0.00001
    elif mutation == "sample_time":
        public["samples"][0]["time_sec"] = 0.00001
    else:
        identity["frames"][0]["time_sec"] = 0.00001
    result = _project(source)
    assert result["ready"] is False
    assert result["students"] == result["anonymous_people"] == []


def test_repeated_person_id_and_same_coordinates_do_not_propagate_identity_across_frames(source):
    source[0]["observations"].append(_observation("o0001", frame="f1", time=20, behavior="standing"))
    result = _project(source)
    named = _student(result)
    assert named["sample_count"] == named["observation_count"] == 1
    assert [e["frame_key"] for e in named["evidence"]] == ["f0"]
    assert len(result["anonymous_people"]) == 1
    unknown = result["anonymous_people"][0]
    assert unknown["identity_status"] == "unconfirmed"
    assert unknown["evidence"][0]["frame_key"] == "f1"
    assert result["group"]["evidence_count"] == 1
    assert _dimensions(named)["activity"]["status"] != "observed"


def test_explicit_person_link_to_other_frame_is_not_identity_confirmation(source):
    source[0]["observations"] = [_observation(frame="f1", time=20)]
    result = _project(source, {("same-model-person", "f1"): "binding-a"})
    assert result["students"] == []
    assert result["anonymous_people"][0]["identity_status"] == "unconfirmed"


def test_same_person_id_can_belong_to_different_confirmed_students_in_different_frames(source):
    source[0]["observations"].append(_observation("o0001", frame="f1", time=20, behavior="standing"))
    source[1]["bindings"].append(_binding("binding-b", "student-b", frame="f1", time=20))
    result = _project(source)
    assert {p["student_id"] for p in result["students"]} == {"student-a", "student-b"}
    assert _student(result, "student-a")["evidence"][0]["behaviors"] == ["hand_raised"]
    assert _student(result, "student-b")["evidence"][0]["behaviors"] == ["standing"]


def test_ambiguous_student_boxes_require_explicit_same_frame_link(source):
    source[1]["bindings"].append(_binding("binding-b", "student-b"))
    assert _project(source)["students"] == []
    result = _project(source, {("same-model-person", "f0"): "binding-b"})
    assert [p["student_id"] for p in result["students"]] == ["student-b"]


@pytest.mark.parametrize("explicit_binding", ["missing-binding", "binding-b", "revoked-binding"])
def test_invalid_explicit_link_never_falls_back_to_another_students_geometry(source, explicit_binding):
    source[1]["bindings"].extend([
        _binding("binding-b", "student-b", box=OTHER_BOX),
        _binding("revoked-binding", "student-b", status="revoked"),
    ])
    result = _project(source, {("same-model-person", "f0"): explicit_binding})
    assert result["students"] == []
    assert len(result["anonymous_people"]) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_confirmed_teacher_box_vetoes_both_geometric_and_explicit_student_attribution(source, explicit):
    source[1]["bindings"].append(_binding("teacher-binding", "", role="teacher"))
    links = {("same-model-person", "f0"): "binding-a"} if explicit else None
    result = _project(source, links)
    assert result["students"] == result["anonymous_people"] == []
    assert result["summary"]["observation_count"] == 0


@pytest.mark.parametrize("teacher_is_smaller", [True, False])
def test_contained_teacher_box_cannot_escape_exclusion_due_to_small_iou(source, teacher_is_smaller):
    large = {"x": 0.1, "y": 0.1, "width": 0.6, "height": 0.6}
    small = {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.1}
    observed, teacher = (large, small) if teacher_is_smaller else (small, large)
    source[0]["observations"][0]["bbox"] = observed
    source[1]["bindings"] = [_binding(box=observed),
                             _binding("teacher-binding", "", box=teacher, role="teacher")]
    result = _project(source)
    assert result["students"] == [], "A confirmed teacher region was attributed to a student"
    assert result["anonymous_people"] == [], "A confirmed teacher region became an anonymous pupil candidate"


def test_teacher_on_another_frame_does_not_suppress_a_valid_student(source):
    source[1]["bindings"].append(_binding("teacher-binding", "", frame="f1", time=20, role="teacher"))
    assert _student(_project(source))["observation_count"] == 1


def test_unconfirmed_same_coordinates_stay_separate_frame_local_candidates(source):
    source[1]["bindings"] = []
    source[0]["observations"] += [
        _observation("o0001", behavior="seated", person="another-model-id"),
        _observation("o0002", frame="f1", time=20),
    ]
    result = _project(source)
    candidates = result["anonymous_people"]
    assert result["students"] == []
    assert len(candidates) == len({p["candidate_id"] for p in candidates}) == 2
    assert [p["sample_count"] for p in candidates] == [1, 1]
    assert [p["observation_count"] for p in candidates] == [2, 1]
    assert all("student_id" not in p for p in candidates)
    assert result["group"]["scope"] == "unconfirmed_people"
    assert result["group"]["dimensions"] == result["group"]["suggestions"] == []


def test_nearby_anonymous_boxes_are_not_clustered_into_one_person(source):
    source[1]["bindings"] = []
    other_box = {**BOX, "x": BOX["x"] + 0.01}
    source[0]["observations"].append(_observation("o0001", box=other_box))
    result = _project(source)
    assert len(result["anonymous_people"]) == 2


@pytest.mark.parametrize("bad_box", [
    None, {}, {**BOX, "x": -0.1}, {**BOX, "width": 0}, {**BOX, "height": True},
    {**BOX, "x": float("nan")}, {**BOX, "width": float("inf")}, {**BOX, "x": 0.99},
])
def test_unlocalized_or_invalid_boxes_never_become_individual_insights(source, bad_box):
    source[0]["observations"][0]["bbox"] = bad_box
    result = _project(source)
    if bad_box is None:
        assert result["ready"] is True
        assert result["students"] == []
        assert result["anonymous_people"]
        assert result["anonymous_people"][0]["evidence"][0]["bbox"] is None
    else:
        assert result["ready"] is False
        assert result["students"] == result["anonymous_people"] == []


def test_zero_observations_means_no_evidence_not_zero_score_or_no_support(source):
    source[0]["observations"] = []
    result = _project(source)
    assert result["ready"] is False
    assert result["students"] == result["anonymous_people"] == []
    assert result["group"]["dimensions"] == result["group"]["suggestions"] == []
    assert not {key for key in _all_keys(result) if "score" in key.lower()}


def test_missing_dimension_is_unknown_not_a_numeric_rating(source):
    source[0]["observations"] = [_observation(behavior="seated")]
    student = _student(_project(source))
    dimensions = _dimensions(student)
    assert dimensions["activity"]["status"] == "observed"
    for key in ("participation", "orientation", "interaction"):
        assert dimensions[key]["status"] in {"not_observed", "unknown", "insufficient_evidence"}
        assert dimensions[key]["evidence_count"] == 0
        assert dimensions[key]["text"]
        assert not ({"score", "rating", "value", "passed"} & dimensions[key].keys())


def test_named_student_exposes_state_timeline_but_archive_is_summary_only(source):
    result = _project(source)
    student = _student(result)

    assert len(student["state_timeline"]) == student["sample_count"]
    assert student["state_timeline"][0]["time_sec"] == 0
    estimate = student["state_timeline"][0]["state_estimate"]
    assert estimate["participation"] == "出现参与线索"
    assert estimate["emotion_stress"] == "当前采样无法可靠判断"

    archive = student["archive_summary"]
    assert archive["sample_count"] == student["sample_count"]
    assert "逐时刻状态估计留在本课分析页" in archive["archive_scope"]
    assert "evidence" not in archive


def test_each_students_profile_and_support_follow_only_their_own_behavior_evidence(source):
    source[1]["bindings"].append(_binding("binding-b", "student-b", box=OTHER_BOX))
    source[0]["observations"] = [
        _observation(), _observation("o0001", behavior="writing"),
        _observation("o0002", behavior="seated"),
        _observation("o0003", behavior="head_away_from_materials", box=OTHER_BOX),
        _observation("o0004", behavior="standing", box=OTHER_BOX),
    ]
    result = _project(source)
    first, second = _student(result), _student(result, "student-b")
    assert set(first["evidence"][0]["behaviors"]) == {"hand_raised", "writing", "seated"}
    assert set(second["evidence"][0]["behaviors"]) == {"head_away_from_materials", "standing"}
    assert _dimensions(first)["participation"]["status"] == "observed"
    assert _dimensions(second)["participation"]["status"] != "observed"
    assert _dimensions(first)["orientation"]["status"] != "observed"
    assert _dimensions(second)["orientation"]["status"] == "observed"
    assert first["headline"] != second["headline"]
    assert first["suggestions"] and second["suggestions"]
    assert set(first["suggestions"]).isdisjoint(second["suggestions"])
    for person in (first, second):
        for evidence in person["evidence"]:
            assert all(cloud.VISIBLE_ACTIONS[code] in evidence["observations"]
                       for code in evidence["behaviors"])


def test_scene_suggestions_and_unattributed_behavior_do_not_become_a_named_childs_support(source):
    before = _student(_project(source))
    source[0]["result"]["teacher_suggestions"].append({
        "timestamp_sec": 0, "code": "review_visible_movement_and_seating_context",
        "evidence_behaviors": ["out_of_seat"],
    })
    source[0]["observations"].append(_observation("o0001", behavior="out_of_seat", box=OTHER_BOX))
    after = _project(source)
    assert _student(after) == before
    assert after["group"]["evidence_count"] == 1
    assert len(after["anonymous_people"]) == 1


def test_duplicate_observation_ids_are_not_double_counted(source):
    source[0]["observations"].append(copy.deepcopy(source[0]["observations"][0]))
    result = _project(source)
    assert result["summary"]["observation_count"] == 1
    assert _student(result)["evidence"][0]["observation_ids"] == ["o0000"]


@pytest.mark.parametrize("explicit,basis", [(False, "confirmed_frame_bbox"), (True, "explicit_person_link")])
def test_named_evidence_retains_the_exact_binding_and_attribution_basis(source, explicit, basis):
    links = {("same-model-person", "f0"): "binding-a"} if explicit else None
    evidence = _student(_project(source, links))["evidence"][0]
    assert evidence.get("binding_id") == "binding-a", "Named evidence lost its identity binding"
    assert evidence.get("identity_basis") == basis, "Named evidence lost its attribution method"
    assert evidence["frame_key"] == "f0" and evidence["time_sec"] == 0


def test_projection_does_not_forward_private_fields_or_model_supplied_identity_and_scores(source):
    public, identity, task = source
    marker = "SYNTHETIC_EXCLUDED_"
    identity["students"][0].update(diagnosis=marker + "DIAGNOSIS", iep=marker + "IEP",
                                   note=marker + "NOTE", student_code=marker + "CODE")
    identity["bindings"][0]["confirmed_by"] = marker + "ACCOUNT"
    task.update(file_path=marker + "PATH", token=marker + "TOKEN")
    public["result"].update(transcript=marker + "TRANSCRIPT", private_text=marker + "DETAIL")
    public["observations"][0].update(student_id=marker + "FAKE_STUDENT", display_name=marker + "FAKE_NAME",
                                      role="teacher", educational_score=9.9, diagnosis=marker + "MODEL_DIAGNOSIS")
    result = _project(source)
    assert _student(result)["display_name"] == "Synthetic A"
    assert marker not in json.dumps(result)
    keys = set(_all_keys(result))
    assert not {key for key in keys if "score" in key.lower()}
    assert not keys.intersection({"diagnosis", "iep", "transcript", "file_path", "token", "confirmed_by"})


def test_legacy_free_text_is_not_reinterpreted_as_canonical_behavior(source):
    row = source[0]["observations"][0]
    row.pop("behavior")
    row["observation"] = "SYNTHETIC_EXCLUDED_FREE_TEXT"
    result = _project(source)
    assert result["ready"] is False
    assert result["students"] == result["anonymous_people"] == []
    assert "SYNTHETIC_EXCLUDED_" not in json.dumps(result)


@pytest.fixture
def workspace_case(source, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "rehab_affect._student_insights_test_observation_store",
        ROOT / ".runtime/cloud_student_release/demo2_observation_store.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    public, identity, task = source
    identity["bindings"].append(_binding("binding-b", "student-b"))
    job = {
        key: public[key] for key in ("job_id", "task_id", "owner_account_id", "scope_key",
                                    "source_sha256", "frame_revision", "status")
    }
    job.update(model="synthetic-model", error_code=None,
               created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
               samples_json=json.dumps(public["samples"]), result_json=json.dumps(public["result"]),
               normalized_json=json.dumps({"schema_version": 1, "observations": public["observations"]}))
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE demo2_observation_jobs (
            job_id TEXT PRIMARY KEY, task_id TEXT, owner_account_id TEXT, scope_key TEXT,
            source_sha256 TEXT, frame_revision TEXT, status TEXT, model TEXT, error_code TEXT,
            created_at TEXT, updated_at TEXT, samples_json TEXT, result_json TEXT, normalized_json TEXT
        );
        CREATE TABLE demo2_observation_person_links (
            job_id TEXT, person_id TEXT, frame_key TEXT, binding_id TEXT,
            owner_account_id TEXT, scope_key TEXT, source_sha256 TEXT, frame_revision TEXT
        );
    """)
    fields = tuple(job)
    db.execute("INSERT INTO demo2_observation_jobs (" + ",".join(fields) + ") VALUES ("
               + ",".join("?" for _ in fields) + ")", tuple(job[key] for key in fields))
    link = {"job_id": job["job_id"], "person_id": "same-model-person", "frame_key": "f0",
            "binding_id": "binding-a", "owner_account_id": job["owner_account_id"],
            "scope_key": job["scope_key"], "source_sha256": job["source_sha256"],
            "frame_revision": job["frame_revision"]}
    db.execute("INSERT INTO demo2_observation_person_links VALUES(?,?,?,?,?,?,?,?)", tuple(link.values()))
    db.commit()

    @contextmanager
    def connect():
        yield db

    # Exercise real workspace SQL/public projection without constructing a store
    # or pretending this wiring test verifies authentication or media on disk.
    store = object.__new__(module.Demo2ObservationStore)
    store.records = SimpleNamespace(_connect=connect)
    account = {"account_id": task["account_id"], "role": "school_uploader"}
    calls = []

    def authorized(token, task_id, *, teacher_only=True):
        assert token == "synthetic-token" and task_id == task["task_id"]
        assert teacher_only is False
        calls.append("authorized")
        return account, identity, task

    def current(connection, selected):
        assert connection is db and selected == job
        calls.append("current")
        return task

    monkeypatch.setattr(store, "_authorized", authorized)
    monkeypatch.setattr(store, "_current", current)
    monkeypatch.setattr(module, "_allowed_hashes", lambda: {task["sha256"]})
    monkeypatch.setattr(module, "_provider_ready", lambda: True)
    monkeypatch.setitem(sys.modules, "rehab_affect.demo2_course_analysis", cloud)
    try:
        yield SimpleNamespace(store=store, module=module, db=db, job=job, link=link,
                              source=source, calls=calls)
    finally:
        db.close()


def test_workspace_adds_projection_without_mutating_canonical_payload_or_database(workspace_case):
    case = workspace_case
    before = copy.deepcopy(case.source)
    writes = case.db.total_changes
    case.db.execute("PRAGMA query_only=ON")
    work = case.store.workspace("synthetic-token", case.job["task_id"])
    assert case.calls == ["authorized", "current"]
    assert work["result"] == case.source[0]["result"]
    assert work["observations"] == case.source[0]["observations"]
    assert work["samples"] == case.source[0]["samples"]
    assert work["reviewed"] is False and work["teacher_review_status"] == "not_reviewed"
    assert work["can_request"] is True
    insights = work["student_insights"]
    assert [student["student_id"] for student in insights["students"]] == ["student-a"]
    evidence = _student(insights)["evidence"][0]
    assert evidence["binding_id"] == "binding-a" and evidence["identity_basis"] == "explicit_person_link"
    assert case.source == before
    assert case.db.total_changes == writes
    stored = dict(case.db.execute("SELECT * FROM demo2_observation_jobs").fetchone())
    assert stored == case.job


@pytest.mark.parametrize("field", ["job_id", "owner_account_id", "scope_key", "source_sha256", "frame_revision"])
def test_workspace_ignores_explicit_links_outside_current_job_and_source(workspace_case, field):
    case = workspace_case
    foreign = {**case.link, "binding_id": "binding-b", field: "other-synthetic-value"}
    case.db.execute("INSERT INTO demo2_observation_person_links VALUES(?,?,?,?,?,?,?,?)", tuple(foreign.values()))
    case.db.commit()
    case.db.execute("PRAGMA query_only=ON")
    work = case.store.workspace("synthetic-token", case.job["task_id"])
    assert case.calls == ["authorized", "current"]
    assert [student["student_id"] for student in work["student_insights"]["students"]] == ["student-a"]
    assert _student(work["student_insights"])["evidence"][0]["binding_id"] == "binding-a"


def test_workspace_current_source_failure_prevents_running_projection(workspace_case, monkeypatch):
    case = workspace_case

    def reject_current(connection, job):
        raise case.module.ObservationError(409, "source_changed", "Synthetic source changed")

    def forbidden_projection(*args, **kwargs):
        pytest.fail("Projection ran after the current-source gate failed")

    monkeypatch.setattr(case.store, "_current", reject_current)
    monkeypatch.setattr(cloud, "build_student_insights", forbidden_projection)
    with pytest.raises(case.module.ObservationError) as caught:
        case.store.workspace("synthetic-token", case.job["task_id"])
    assert caught.value.code == "source_changed"


@pytest.mark.parametrize("gate,status", [("allowlist", "not_authorized"), ("provider", "not_configured")])
def test_workspace_unavailable_gate_does_not_project_cached_observations(workspace_case, monkeypatch, gate, status):
    case = workspace_case
    if gate == "allowlist":
        monkeypatch.setattr(case.module, "_allowed_hashes", lambda: set())
    else:
        monkeypatch.setattr(case.module, "_provider_ready", lambda: False)
    work = case.store.workspace("synthetic-token", case.job["task_id"])
    assert work["status"] == status
    assert work["observations"] == [] and work["result"] is None
    assert "student_insights" not in work or work["student_insights"]["ready"] is False
    assert case.calls == ["authorized"]
