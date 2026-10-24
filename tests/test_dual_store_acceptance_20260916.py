from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore
from rehab_affect.demo2_measurement_store import MeasurementError
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "DualAcceptance-")
    records = Demo2StudentRecordStore(tmp_path / "synthetic.sqlite3", tmp_path / "documents")
    tokens = {}
    for key, username in (("teacher_a", "school_uploader_01"), ("teacher_b", "school_uploader_02")):
        account = records.authenticate_account(username, "DualAcceptance-" + username)
        tokens[key] = records.create_account_session(account)["token"]
        records.save_account_school_context(
            tokens[key], {"city": "合成市", "district": "合成区", "school_name": "合成学校一"}
        )
    return SimpleNamespace(records=records, store=Demo2EvaluationStore(records), tokens=tokens)


def evaluation_payload(record_id=None, **changes):
    payload = {
        "record_id": record_id or str(uuid4()),
        "expected_version": 0,
        "lesson_id": "synthetic-lesson-20260916",
        "lesson_date": date.today().isoformat(),
        "course_name": "合成生活数学课",
        "subject_id": "math",
        "template_id": "basic_100",
        "goal_context": "合成目标：在视觉支持下完成数量配对；不含真实学生资料。",
        "school_source": "teacher_recorded",
        "school_rater": "合成评分人",
        "reviewed": True,
        "items": [
            {
                "id": f"i{index}",
                "school_score": 8,
                "enhanced_score": 7,
                "evidence": "合成课堂观察 00:20",
                "reason": "合成复核原因",
                "suggestion": "合成下一课建议",
            }
            for index in range(1, 11)
        ],
    }
    payload.update(changes)
    return payload


def test_account_and_school_scopes_are_isolated_and_reversible(env):
    saved = env.store.save(env.tokens["teacher_a"], evaluation_payload())
    assert env.store.workspace(env.tokens["teacher_b"])["records"] == []

    env.records.save_account_school_context(
        env.tokens["teacher_a"], {"city": "合成市", "district": "合成区", "school_name": "合成学校二"}
    )
    changed_workspace = env.store.workspace(env.tokens["teacher_a"])
    assert changed_workspace["records"] == []
    assert changed_workspace["school_context"]["school_name"] == "合成学校二"
    with pytest.raises(MeasurementError) as exc:
        env.store.save(env.tokens["teacher_a"], evaluation_payload(record_id=saved["record_id"], expected_version=1))
    assert exc.value.status == 404

    env.records.save_account_school_context(
        env.tokens["teacher_a"], {"city": "合成市", "district": "合成区", "school_name": "合成学校一"}
    )
    assert env.store.workspace(env.tokens["teacher_a"])["records"] == [saved]


def test_rule_snapshot_and_version_history_remain_stable_after_edit(env):
    first = env.store.save(env.tokens["teacher_a"], evaluation_payload())
    original_snapshot = deepcopy(first["rule_snapshot"])
    original_result = deepcopy(first["result"])

    edited = evaluation_payload(
        record_id=first["record_id"],
        expected_version=1,
        course_name="合成生活数学课（修订）",
        items=[
            {**item, "school_score": 9, "enhanced_score": 8, "reason": "合成修订原因"}
            for item in first["items"]
        ],
    )
    second = env.store.save(env.tokens["teacher_a"], edited)
    assert second["version"] == 2
    assert second["rule_snapshot"] == original_snapshot
    assert second["result"] != original_result

    with env.records._connect() as db:
        rows = db.execute(
            "SELECT version, payload_json FROM demo2_classroom_evaluation_versions "
            "WHERE record_id=? ORDER BY version",
            (first["record_id"],),
        ).fetchall()
    assert [row["version"] for row in rows] == [1, 2]
    assert __import__("json").loads(rows[0]["payload_json"]) == first


def test_withdrawn_record_cannot_be_reused_or_withdrawn_twice(env):
    saved = env.store.save(env.tokens["teacher_a"], evaluation_payload())
    withdrawn = env.store.withdraw(
        env.tokens["teacher_a"],
        {"record_id": saved["record_id"], "expected_version": 1, "reason": "合成撤销"},
    )
    assert withdrawn["status"] == "withdrawn"
    with pytest.raises(MeasurementError) as exc:
        env.store.withdraw(
            env.tokens["teacher_a"],
            {"record_id": saved["record_id"], "expected_version": 2, "reason": "再次撤销"},
        )
    assert exc.value.code == "version_conflict"
    with pytest.raises(MeasurementError) as exc:
        env.store.save(env.tokens["teacher_a"], evaluation_payload(record_id=saved["record_id"], expected_version=2))
    assert exc.value.code == "version_conflict"


def test_uuid_and_date_contract_validation_is_strict_and_transactional(env):
    invalid_payloads = [
        evaluation_payload(record_id="fixture-1"),
        evaluation_payload(record_id=str(uuid4()), lesson_date="2026-1-1"),
        evaluation_payload(record_id=str(uuid4()), lesson_date="2026-02-30"),
        evaluation_payload(record_id=str(uuid4()), lesson_date=(date.today() + timedelta(days=1)).isoformat()),
    ]
    for payload in invalid_payloads:
        with pytest.raises(MeasurementError):
            env.store.save(env.tokens["teacher_a"], payload)
    assert env.store.workspace(env.tokens["teacher_a"])["records"] == []


def test_sqlite_concurrent_first_save_has_one_winner_and_one_conflict(env):
    record_id = str(uuid4())

    def save_once():
        try:
            result = env.store.save(env.tokens["teacher_a"], evaluation_payload(record_id=record_id))
            return ("saved", result["version"])
        except MeasurementError as exc:
            return ("error", exc.status, exc.code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: save_once(), range(2)))
    assert outcomes.count(("saved", 1)) == 1
    assert sum(outcome[0] == "error" and outcome[2] == "version_conflict" for outcome in outcomes) == 1
    assert len(env.store.workspace(env.tokens["teacher_a"])["records"]) == 1
