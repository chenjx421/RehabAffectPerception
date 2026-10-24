"""Directory provenance and pure scope guards; no network or real student data."""

from copy import deepcopy
from datetime import date

import pytest

from rehab_affect.school_directory import (
    CONTEXT_LIMITS, SOURCE_URL, SPECIAL_SOURCE_URL, SchoolSelectionError, normalize_school_selection,
    prepare_school_selection, school_directory,
)


EMPTY = {"city": "", "district": "", "school_name": ""}
OTHER = {"selection_source": "other", "province": "测试省", "city": "测试市",
         "district": "测试区", "school_name": "测试学校", "street": "测试街道", "address": "测试路1号"}


def wire(selection=None, expected=None):
    return {**(OTHER if selection is None else selection),
            "expected_context": deepcopy(EMPTY if expected is None else expected), "confirmed": True}


def test_directory_is_explicitly_limited_and_each_name_has_dated_public_evidence():
    directory = school_directory()
    assert directory["coverage"]["complete"] is False
    assert directory["coverage"]["entry_count"] == len(directory["entries"]) == 5
    assert directory["coverage"]["special_education_complete"] is False
    assert directory["regions"] == [{"province": "上海市", "city": "上海市", "district": "青浦区"}]
    assert len({row["directory_id"] for row in directory["entries"]}) == 5
    assert {row["school_name"] for row in directory["entries"]} == {
        "青浦区辅读学校", "上海市青浦区东方中学", "上海市青浦区豫才中学", "上海市青浦区实验中学", "上海市青浦区徐泾中学"
    }
    for row in directory["entries"]:
        assert (row["city"], row["district"]) == ("上海市", "青浦区")
        assert row["source_status"] == "public_source"
        assert row["source_url"] in {SOURCE_URL, SPECIAL_SOURCE_URL}
        if row["directory_id"] == "sh-qp-fudu":
            assert row["source_published_on"] == "2022-10-27"
            assert row["source_title"] == "青浦区教育机构一览表"
            assert row["address"] == "上海市青浦区朱家角镇西井街77号"
            assert row["street"] == "朱家角镇"
            assert "现状待复核" in row["source_note"]
        else:
            assert row["source_title"] == "2026年青浦区初中学区划分一览表"
            assert row["address"] is None and row["street"] is None
            assert row["address_status"] == "pending"
        assert date.fromisoformat(row["source_published_on"]) <= date.fromisoformat(row["source_checked_on"])
        assert not {"tenant_id", "school_id", "teacher_verified"} & row.keys()
    directory["entries"][0]["school_name"] = "tampered"
    directory["regions"].clear()
    assert school_directory()["entries"][0]["school_name"] != "tampered"
    assert school_directory()["regions"]


def test_directory_normalization_uses_server_names_and_keeps_metadata_separate():
    entry = school_directory()["entries"][0]
    result = normalize_school_selection({"selection_source": "directory", "directory_id": entry["directory_id"]})
    assert result["context"] == {key: entry[key] for key in CONTEXT_LIMITS}
    assert result["details"]["source_status"] == "public_source"
    assert result["details"]["source_url"] == entry["source_url"]
    assert result["details"]["address"] == entry["address"]
    assert result["details"]["selection_source"] == "directory"
    assert result["details"]["directory_id"] == entry["directory_id"]


def test_other_is_structured_pending_and_never_auto_matches_directory():
    entry = school_directory()["entries"][0]
    payload = {"selection_source": "other", **{key: entry[key] for key in ("province", "street", "address", *CONTEXT_LIMITS)}}
    result = normalize_school_selection(payload)
    assert result["details"]["source_status"] == "pending"
    assert result["details"]["directory_id"] is None
    assert result["details"]["source_url"] is None
    assert result["details"]["source_checked_on"] is None
    assert len(school_directory()["entries"]) == 5
    result = normalize_school_selection({**OTHER, "school_name": "  测试学校  "})
    assert result["context"]["school_name"] == "测试学校"
    assert result["details"]["province"] == "测试省"
    assert result["details"]["street"] == "测试街道"
    assert result["details"]["address"] == "测试路1号"
    assert result["details"]["address_status"] == "pending"


@pytest.mark.parametrize("field", ["province", "street", "address", *CONTEXT_LIMITS])
@pytest.mark.parametrize("value", ["", "   ", None, 123, [], "a\nb", "a\x00b", "a\u202eb", "x" * 301])
def test_other_rejects_invalid_values(field, value):
    with pytest.raises(SchoolSelectionError):
        normalize_school_selection({**OTHER, field: value})


@pytest.mark.parametrize("field", ["province", "city", "district", "street"])
def test_region_limit_is_eighty_characters(field):
    with pytest.raises(SchoolSelectionError):
        normalize_school_selection({**OTHER, field: "a" * 81})


def test_address_is_required_bounded_and_metadata_only():
    assert len(normalize_school_selection({**OTHER, "address": "a" * 300})["details"]["address"]) == 300
    for field in ("address", "street"):
        with pytest.raises(SchoolSelectionError):
            normalize_school_selection({key: value for key, value in OTHER.items() if key != field})
    result = normalize_school_selection(OTHER)
    assert "address" not in result["context"] and "street" not in result["context"]


@pytest.mark.parametrize("payload", [None, [], {}, {"selection_source": []},
    {"selection_source": "directory", "directory_id": "not-listed"},
    {"selection_source": "directory", "directory_id": None},
    {**OTHER, "teacher_verified": True}, {**OTHER, "tenant_id": "scope"},
    {**OTHER, "source_url": SOURCE_URL}, {**OTHER, "source_status": "verified"},
    {"selection_source": "existing", **EMPTY},
])
def test_unknown_ids_fields_and_claims_are_rejected(payload):
    with pytest.raises(SchoolSelectionError):
        normalize_school_selection(payload)


def test_initial_selection_preserves_input_objects_and_returns_three_field_context():
    payload = wire()
    before = deepcopy(payload)
    current = dict(EMPTY)
    result = prepare_school_selection(payload, current_context=current, has_existing_students=False)
    assert result["context_changed"] is True
    assert set(result["context"]) == set(CONTEXT_LIMITS)
    assert result["details"]["selection_source"] == "other"
    assert current == EMPTY and payload == before


def test_existing_students_block_changes_even_if_current_school_is_empty():
    for current in [EMPTY, {"city": "旧市", "district": "旧区", "school_name": "旧学校"}]:
        with pytest.raises(SchoolSelectionError) as exc:
            prepare_school_selection(wire(expected=current), current_context=current, has_existing_students=True)
        assert exc.value.code == "school_migration_required"
        assert exc.value.status == 409
        assert "管理员迁移" in str(exc.value)


def test_owner_without_students_can_change_context_without_any_snapshot_rewrite():
    current = {"city": "旧市", "district": "旧区", "school_name": "旧学校"}
    result = prepare_school_selection(wire(expected=current), current_context=current, has_existing_students=False)
    assert result["context_changed"] is True
    assert set(result) == {"context", "details", "context_changed"}
    assert current["school_name"] == "旧学校"


def test_existing_selection_preserves_exact_context_and_allows_roster_owner():
    current = {"city": " 上海 ", "district": "青浦", "school_name": "旧校名"}
    result = prepare_school_selection(wire({"selection_source": "existing", **current}, current),
                                      current_context=current, has_existing_students=True)
    assert result["context"] == current
    assert result["context_changed"] is False
    assert result["details"]["source_status"] == "pending"


def test_directory_canonicalization_cannot_silently_rename_an_existing_scope():
    current = {"city": "上海", "district": "青浦", "school_name": "东方中学"}
    entry = school_directory()["entries"][0]
    with pytest.raises(SchoolSelectionError) as exc:
        prepare_school_selection(wire({"selection_source": "directory", "directory_id": entry["directory_id"]}, current),
                                 current_context=current, has_existing_students=True)
    assert exc.value.code == "school_migration_required"


@pytest.mark.parametrize("confirmed", [False, None, 1, "true"])
def test_confirmation_is_explicit_boolean(confirmed):
    with pytest.raises(SchoolSelectionError) as exc:
        prepare_school_selection({**wire(), "confirmed": confirmed}, current_context=EMPTY, has_existing_students=False)
    assert exc.value.code == "school_confirmation_required"


def test_expected_context_and_trusted_roster_state_fail_closed():
    with pytest.raises(SchoolSelectionError) as exc:
        prepare_school_selection(wire(expected={**EMPTY, "city": "stale"}), current_context=EMPTY, has_existing_students=False)
    assert exc.value.code == "school_context_changed" and exc.value.status == 409
    with pytest.raises(SchoolSelectionError):
        prepare_school_selection({**OTHER, "confirmed": True}, current_context=EMPTY, has_existing_students=False)
    for unknown in [None, 0, "false"]:
        with pytest.raises(SchoolSelectionError) as exc:
            prepare_school_selection(wire(), current_context=EMPTY, has_existing_students=unknown)
        assert exc.value.code == "school_scope_unavailable"
    with pytest.raises(SchoolSelectionError):
        prepare_school_selection(wire(), current_context=None, has_existing_students=False)


def test_existing_source_is_not_a_backdoor_to_a_different_school():
    with pytest.raises(SchoolSelectionError) as exc:
        prepare_school_selection(wire({"selection_source": "existing", **{key: OTHER[key] for key in CONTEXT_LIMITS}}),
                                 current_context=EMPTY, has_existing_students=False)
    assert exc.value.code == "school_context_changed"
