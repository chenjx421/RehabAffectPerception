"""Target selection contract; all data is synthetic and requests use loopback."""
import pytest

from test_demo2_observation_api import rig, PREFIX
from test_demo2_identity_api import request


@pytest.fixture
def target_rig(rig):
    value = {"task_id": "task-one", "selected_student_ids": [], "max_students": 3}
    def read(token, task_id):
        rig.observations._call("target_settings", token, task_id)
        rig.observations._task(task_id)
        return value.copy()
    def save(token, payload):
        rig.observations._call("save_targets", token, payload)
        rig.observations._task(payload["task_id"])
        value["selected_student_ids"] = payload["student_ids"]
        return value.copy()
    rig.observations.target_settings = read
    rig.observations.save_targets = save
    return rig


def test_save_and_read_targets(target_rig):
    payload = {"task_id": "task-one", "student_ids": ["student-one", "student-two", "student-three"]}
    status, headers, body = request(target_rig.httpd, PREFIX + "/targets", role="school", method="POST", payload=payload)
    assert status == 200
    assert body["settings"]["selected_student_ids"] == payload["student_ids"]
    assert "no-store" in headers["Cache-Control"]
    status, _, body = request(target_rig.httpd, PREFIX + "/targets?task_id=task-one", role="school")
    assert status == 200 and body["settings"]["max_students"] == 3
    assert len(body["settings"]["selected_student_ids"]) == 3


@pytest.mark.parametrize("ids", [["a", "b", "c", "d"], ["a", "a"], "a", [None], [True], [[]]])
def test_invalid_selection_rejected_before_store(target_rig, ids):
    status, _, _ = request(target_rig.httpd, PREFIX + "/targets", role="school", method="POST",
                            payload={"task_id": "task-one", "student_ids": ids})
    assert status == 400 and not target_rig.observations.calls


@pytest.mark.parametrize("role,status", [(None,401),("expired",401),("member",403),("admin",403),("other",404)])
def test_write_permissions(target_rig, role, status):
    actual, _, _ = request(target_rig.httpd, PREFIX + "/targets", role=role, method="POST",
                           payload={"task_id": "task-one", "student_ids": []})
    assert actual == status


def test_clear_targets(target_rig):
    status, _, body = request(target_rig.httpd, PREFIX + "/targets", role="school", method="POST",
                            payload={"task_id": "task-one", "student_ids": []})
    assert status == 200 and body["settings"]["selected_student_ids"] == []


@pytest.mark.parametrize("query", ["", "?task_id=task-one&task_id=task-two", "?task_id=task-one&extra=x"])
def test_bad_query_rejected(target_rig, query):
    status, _, _ = request(target_rig.httpd, PREFIX + "/targets" + query, role="school")
    assert status == 400


def test_foreign_origin_denied(target_rig):
    status, _, body = request(target_rig.httpd, PREFIX + "/targets", role="school", method="POST",
                            payload={"task_id": "task-one", "student_ids": []},
                            headers={"Origin": "https://foreign.invalid"})
    assert status == 403 and body["error"]["code"] == "origin_forbidden"
    assert not target_rig.observations.calls


@pytest.mark.parametrize("mime", ["text/plain", "application/x-www-form-urlencoded"])
def test_non_json_denied(target_rig, mime):
    status, _, _ = request(target_rig.httpd, PREFIX + "/targets", role="school", method="POST",
                           payload={"task_id": "task-one", "student_ids": []},
                           headers={"Content-Type": mime})
    assert status == 415 and not target_rig.observations.calls
