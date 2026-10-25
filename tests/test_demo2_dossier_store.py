"""Real isolated SQLite, real Fernet, synthetic inputs; no live services/data."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sqlite3
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from rehab_affect import demo2_dossier_store as module
from rehab_affect.demo2_dossier_store import Demo2DossierStore, DossierError, MAX_FILE_BYTES, SUMMARY_FIELDS
from rehab_affect.demo2_identity_store import Demo2IdentityStore
from rehab_affect.student_record_store import Demo2StudentRecordStore


SCHOOL = {"city": "虚构测试市", "district": "虚构测试区", "school_name": "虚构同名学校"}
SECRET = "SENSITIVE-DOSSIER-CONTENT-765431"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("dossier_seed")
    with pytest.MonkeyPatch.context() as monkey:
        monkey.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "DossierTest-")
        records = Demo2StudentRecordStore(root / "template.sqlite3", root / "documents")
        identities = Demo2IdentityStore(records)
        with records._connect() as connection:
            accounts = {row["username"]: dict(row) for row in connection.execute("SELECT * FROM platform_accounts")}
        aliases = {"a": "school_uploader_01", "b": "school_uploader_02", "admin": "company_admin", "member": "school_uploader_03"}
        tokens = {alias: records.create_account_session(accounts[name]["account_id"])["token"] for alias, name in aliases.items()}
        for alias in ("a", "b"):
            records.save_account_school_context(tokens[alias], SCHOOL)
        pupils = {}
        for key, owner in (("a1", "a"), ("a2", "a"), ("b1", "b")):
            pupils[key] = identities.create_student(tokens[owner], {"display_name": "虚构同名学生", "student_code": key, "class_name": "测试班"})
        with records._connect() as connection:
            connection.execute("UPDATE platform_accounts SET role = 'registered_member', bound_channel_id = NULL WHERE username = 'school_uploader_03'")
    return SimpleNamespace(path=records.db_path, tokens=tokens, pupils=pupils,
                           accounts={alias: accounts[name] for alias, name in aliases.items()})


@pytest.fixture()
def env(template, tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("REHAB_DEMO2_DOSSIER_KEY", key)
    database = tmp_path / "isolated.sqlite3"
    with sqlite3.connect(template.path) as source, sqlite3.connect(database) as target:
        source.backup(target)
    records = Demo2StudentRecordStore(database, tmp_path / "documents")
    identities = Demo2IdentityStore(records)
    return SimpleNamespace(records=records, identities=identities, store=Demo2DossierStore(records, identities),
                           tokens=dict(template.tokens), pupils=template.pupils, accounts=template.accounts, tmp=tmp_path, key=key)


def day(offset=0):
    return (module._today() + timedelta(days=offset)).isoformat()


def auth_payload(env, pupil="a1", **changes):
    return {"student_id": env.pupils[pupil]["student_id"], "reference": SECRET + "-authorization",
            "storage_mode": "original_and_summary", "valid_until": day(30), "confirmed": True, **changes}


def authorize(env, pupil="a1", **changes):
    return env.store.save_authorization(env.tokens[pupil[0]], auth_payload(env, pupil, **changes))


def document_payload(auth, **changes):
    return {"student_id": auth["student_id"], "authorization_id": auth["authorization_id"], "document_type": "iep",
            "document_date": day(-1), "source_ref": SECRET + "-source", "retain_until": day(20),
            "summary": {key: SECRET + "-" + key for key in SUMMARY_FIELDS}, "filename": SECRET + ".txt",
            "content_base64": base64.b64encode((SECRET + "-original").encode()).decode(), "supersedes_id": "", **changes}


def document(env, pupil="a1", authorization=None, **changes):
    authorization = authorization or authorize(env, pupil)
    return env.store.create_document(env.tokens[pupil[0]], document_payload(authorization, **changes))


def assert_error(status, code, function, *args):
    with pytest.raises(DossierError) as error:
        function(*args)
    assert error.value.status == status and error.value.code == code
    assert SECRET not in str(error.value)
    return error.value


def task(env, pupil="a1", *, bind=True):
    owner = pupil[0]
    content = b"synthetic source bytes"
    created = env.records.create_video_task({"account_session_token": env.tokens[owner], "channel_id": env.accounts[owner]["bound_channel_id"],
        "session_id": "dossier-session", "course_id": "dossier-course", "course_name": "虚构课堂",
        "uploader_name": "测试", "filename": "synthetic.mp4", "byte_size": len(content), "total_chunks": 1})
    task_id = created["task_id"]
    env.records.append_video_chunk({"account_session_token": env.tokens[owner], "task_id": task_id, "chunk_index": 0,
                                   "content_base64": base64.b64encode(content).decode()})
    claim = env.records.claim_next_video_analysis()
    path = Path(claim["analysis_dir"]) / "media_fixture/frames/frame_000000.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic frame; never decoded")
    env.records.finish_video_analysis(task_id, {"task_id": task_id, "analysis_version": "demo2_media_evidence_v1.1",
        "source_sha256": claim["sha256"], "media": {"duration_sec": 1}, "sampling": {"fps": 1, "window_sec": 20},
        "artifacts": {"frames": "media_fixture/frames"}, "segments": [{"start_sec": 0, "end_sec": 1,
            "visual": {"samples": [{"timestamp_sec": 0, "image_path": "media_fixture/frames/frame_000000.jpg"}]}}]})
    workspace = env.identities.workspace(env.tokens[owner], task_id)
    binding = None
    if bind:
        binding = env.identities.save_binding(env.tokens[owner], {"task_id": task_id, "frame_key": "s0_f0",
            "frame_revision": workspace["frame_revision"], "role": "student", "student_id": env.pupils[pupil]["student_id"],
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}})
    return SimpleNamespace(task_id=task_id, revision=workspace["frame_revision"], binding=binding, source=Path(claim["file_path"]))


def reference_payload(env, video, documents, pupil="a1", **changes):
    return {"task_id": video.task_id, "student_id": env.pupils[pupil]["student_id"], "frame_revision": video.revision,
            "document_ids": [doc["document_id"] for doc in documents], "confirmed": True, **changes}


def reference(env, video, documents, pupil="a1"):
    return env.store.create_reference(env.tokens[pupil[0]], reference_payload(env, video, documents, pupil))


def query(env, sql, parameters=()):
    with env.records._connect() as connection:
        return [dict(row) for row in connection.execute(sql, parameters)]


def test_empty_student_workspace_and_isolated_additive_schema(env):
    before = query(env, "SELECT * FROM students")
    version = query(env, "PRAGMA user_version")
    Demo2DossierStore(env.records)
    workspace = env.store.student_workspace(env.tokens["a"], env.pupils["a1"]["student_id"])
    assert workspace["student"] == {key: env.pupils["a1"][key] for key in ("student_id", "display_name", "student_code", "class_name")}
    assert workspace["authorization"] is None and workspace["documents"] == [] and workspace["references"] == []
    assert workspace["policy"] == {"max_retention_days": 60, "training_allowed": False}
    assert workspace["vault"] == {"available": True, "mode": "env_fernet"}
    assert "未自动迁移" in workspace["legacy_notice"]
    assert query(env, "SELECT * FROM students") == before and query(env, "PRAGMA user_version") == version
    assert query(env, "PRAGMA foreign_key_check") == []


def test_real_encryption_roundtrip_reopen_and_no_sensitive_plaintext_at_rest(env):
    auth = authorize(env)
    doc = document(env, authorization=auth)
    path = env.store._file(doc["document_id"])
    assert path.name == doc["document_id"] + ".enc" and SECRET.encode() not in path.read_bytes()
    assert env.store.document_download(env.tokens["a"], doc["document_id"]) == ((SECRET + "-original").encode(), SECRET + ".txt", "text/plain; charset=utf-8")
    reopened = Demo2DossierStore(Demo2StudentRecordStore(env.records.db_path, env.records.upload_dir))
    assert reopened.student_workspace(env.tokens["a"], auth["student_id"])["documents"] == [doc]
    for filename in (env.records.db_path, Path(str(env.records.db_path) + "-wal"), Path(str(env.records.db_path) + "-shm")):
        if filename.exists():
            assert SECRET.encode() not in filename.read_bytes() and env.key.encode() not in filename.read_bytes()
    audits = query(env, "SELECT * FROM audit_logs WHERE object_type = 'demo2_dossier'")
    encoded = json.dumps(audits, ensure_ascii=False)
    assert SECRET not in encoded and "虚构同名学生" not in encoded and str(env.tmp) not in encoded
    assert all(row["actor"] == env.accounts["a"]["account_id"] for row in audits)


@pytest.mark.parametrize("identity", ["b", "admin", "member", "anonymous"])
def test_sensitive_operations_reject_other_owners_admin_and_members(env, identity):
    doc = document(env)
    video = task(env)
    ref = reference(env, video, [doc])
    token = env.tokens.get(identity, "")
    expected = 404 if identity == "b" else 401 if identity == "anonymous" else 403
    calls = [(env.store.student_workspace, (doc["student_id"],)), (env.store.document_download, (doc["document_id"],)),
             (env.store.task_workspace, (video.task_id,)), (env.store.reference_export, (ref["reference_id"],)),
             (env.store.save_authorization, (auth_payload(env),)),
             (env.store.create_document, (document_payload({"student_id": doc["student_id"], "authorization_id": doc["authorization_id"]}),)),
             (env.store.delete_document, ({"student_id": doc["student_id"], "document_id": doc["document_id"], "confirmed": True},)),
             (env.store.withdraw_authorization, ({"student_id": doc["student_id"], "authorization_id": doc["authorization_id"], "confirmed": True},)),
             (env.store.create_reference, (reference_payload(env, video, [doc]),))]
    for function, args in calls:
        with pytest.raises(DossierError) as error:
            function(token, *args)
        assert error.value.status == expected
        assert SECRET not in str(error.value) and str(env.tmp) not in str(error.value)


def test_same_name_and_school_do_not_merge_students_or_authorizations(env):
    first = authorize(env, "a1")
    second = authorize(env, "a2")
    third = authorize(env, "b1")
    assert len({first["student_id"], second["student_id"], third["student_id"]}) == 3
    assert_error(404, "authorization_unavailable", env.store.create_document, env.tokens["a"],
                 document_payload(first, student_id=second["student_id"]))
    assert_error(404, "authorization_unavailable", env.store.withdraw_authorization, env.tokens["a"],
                 {"student_id": second["student_id"], "authorization_id": first["authorization_id"], "confirmed": True})
    assert env.store.student_workspace(env.tokens["a"], second["student_id"])["documents"] == []


def test_current_school_scope_change_blocks_previous_school_dossier(env):
    doc = document(env)
    with pytest.raises(ValueError, match="管理员迁移"):
        env.records.save_account_school_context(env.tokens["a"], {**SCHOOL, "school_name": "另一虚构学校"})
    # Independently verify access checks after an operator-side scope migration.
    with env.records._connect() as db:
        db.execute("UPDATE school_contexts SET school_name=? WHERE school_name=?", ("另一虚构学校", SCHOOL['school_name']))
    assert_error(404, "student_unavailable", env.store.student_workspace, env.tokens["a"], doc["student_id"])
    assert_error(404, "document_unavailable", env.store.document_download, env.tokens["a"], doc["document_id"])
    with env.records._connect() as db:
        db.execute("UPDATE school_contexts SET school_name=? WHERE school_name=?", (SCHOOL['school_name'], "另一虚构学校"))
    assert env.store.student_workspace(env.tokens["a"], doc["student_id"])["documents"][0]["available"] is True


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"confirmed": "true"}, {"reference": ""},
                                      {"reference": "x" * 501}, {"purpose": "training"}, {"storage_mode": "cloud"},
                                      {"valid_until": "2026-13-01"}, {"valid_until": "2026-9-15"}])
def test_authorization_requires_exact_fields_literal_consent_and_valid_values(env, changes):
    with pytest.raises(DossierError) as error:
        env.store.save_authorization(env.tokens["a"], auth_payload(env, **changes))
    assert error.value.status == 400
    assert query(env, "SELECT * FROM demo2_dossier_authorizations") == []


@pytest.mark.parametrize("days", [-1, 0, 61])
def test_authorization_enforces_exclusive_future_sixty_day_cap(env, days):
    assert_error(400, "invalid_retention", env.store.save_authorization, env.tokens["a"], auth_payload(env, valid_until=day(days)))


def test_live_authorization_cannot_be_replaced_and_withdrawal_allows_new_one(env):
    auth = authorize(env, valid_until=day(60))
    assert_error(409, "authorization_exists", env.store.save_authorization, env.tokens["a"], auth_payload(env))
    payload = {"student_id": auth["student_id"], "authorization_id": auth["authorization_id"], "confirmed": True}
    env.store.withdraw_authorization(env.tokens["a"], payload)
    env.store.withdraw_authorization(env.tokens["a"], payload)
    newer = authorize(env)
    assert newer["authorization_id"] != auth["authorization_id"]
    old = query(env, "SELECT * FROM demo2_dossier_authorizations WHERE authorization_id = ?", (auth["authorization_id"],))[0]
    assert old["metadata_ciphertext"] is None and old["status"] == "withdrawn"


def test_summary_only_rejects_original_and_allows_approved_summary(env):
    auth = authorize(env, storage_mode="summary_only")
    assert_error(400, "original_not_authorized", env.store.create_document, env.tokens["a"], document_payload(auth))
    doc = document(env, authorization=auth, filename="", content_base64="")
    assert not doc["has_file"] and doc["filename"] == "" and doc["summary"]["learning_goals"].startswith(SECRET)
    assert_error(404, "original_unavailable", env.store.document_download, env.tokens["a"], doc["document_id"])
    assert not list(env.store.root.glob("*.enc"))


@pytest.mark.parametrize("changes", [
    {"document_type": "diagnosis"}, {"source_ref": ""}, {"source_ref": "x" * 201},
    {"summary": {}}, {"summary": {key: "x" * 2001 for key in SUMMARY_FIELDS}},
    {"summary": {key: {"nested": "not text"} for key in SUMMARY_FIELDS}},
    {"summary": {key: "" for key in SUMMARY_FIELDS}, "filename": "", "content_base64": ""},
    {"document_date": "2099-01-01"}, {"retain_until": "2099-01-01"},
    {"owner_account_id": "fake"}, {"scope_key": "fake"}, {"created_at": "fake"},
])
def test_document_exact_fields_dates_summary_and_bounds(env, changes):
    auth = authorize(env)
    with pytest.raises(DossierError) as error:
        env.store.create_document(env.tokens["a"], document_payload(auth, **changes))
    assert error.value.status == 400
    assert query(env, "SELECT * FROM demo2_dossier_documents") == []


@pytest.mark.parametrize("filename,data", [
    ("../escape.txt", b"hello"), ("C:\\secret.txt", b"hello"), ("foo.txt:stream", b"hello"),
    ("file\x00.txt", b"hello"), ("file.svg", b"<svg/>"), ("file.html", b"<html/>"),
    ("file.exe", b"MZhello"), ("fake.pdf", b"not a PDF"), ("fake.png", b"not PNG"),
    ("fake.jpg", b"not JPEG"), ("active.txt", b"<html><script>bad</script>"),
    ("binary.txt", b"MZbinary"), ("binary.txt", b"\x00secret"), ("script.txt", b"#!/bin/sh\necho hi"),
])
def test_untrusted_file_names_and_magic_are_rejected(env, filename, data):
    auth = authorize(env)
    with pytest.raises(DossierError) as error:
        env.store.create_document(env.tokens["a"], document_payload(auth, filename=filename, content_base64=base64.b64encode(data).decode()))
    assert error.value.status == 400 and SECRET not in str(error.value)


@pytest.mark.parametrize("encoded", ["%%%", "data:text/plain;base64,eA==", "eA", "é", ""])
def test_bad_base64_is_rejected(env, encoded):
    auth = authorize(env)
    assert_error(400, "invalid_file", env.store.create_document, env.tokens["a"], document_payload(auth, content_base64=encoded))


def zip_data(extra=None, compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        archive.writestr("[Content_Types].xml", "<Types>wordprocessingml.document.main+xml</Types>")
        archive.writestr("word/document.xml", "<document><text>synthetic</text></document>")
        for name, data in extra or []:
            archive.writestr(name, data)
    return stream.getvalue()


@pytest.mark.parametrize("kind", ["macro", "bomb", "traversal", "duplicate", "embedded"])
def test_docx_rejects_macros_zip_bombs_and_unsafe_metadata(env, kind):
    extras = {"macro": [("word/vbaProject.bin", b"macro")], "bomb": [("word/large.xml", b"x" * 1024 * 1024)],
              "traversal": [("../outside.txt", "bad")], "duplicate": [("word/document.xml", "duplicate")],
              "embedded": [("word/embeddings/file.exe", b"MZhello")]}
    auth = authorize(env)
    with pytest.warns(UserWarning) if kind == "duplicate" else __import__("contextlib").nullcontext():
        data = zip_data(extras[kind])
    assert_error(400, "invalid_file", env.store.create_document, env.tokens["a"],
                 document_payload(auth, filename="safe-looking.docx", content_base64=base64.b64encode(data).decode()))


@pytest.mark.parametrize("filename,data,mime", [
    ("fixture.pdf", b"%PDF-1.4\nsynthetic\n%%EOF", "application/pdf"),
    ("fixture.jpg", b"\xff\xd8\xffsynthetic\xff\xd9", "image/jpeg"),
    ("fixture.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 8, "image/png"),
    ("fixture.docx", zip_data(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
])
def test_allowed_magic_and_mime_roundtrip_without_ocr_or_execution(env, filename, data, mime):
    doc = document(env, filename=filename, content_base64=base64.b64encode(data).decode())
    assert env.store.document_download(env.tokens["a"], doc["document_id"]) == (data, filename, mime)


def test_exact_eight_mib_file_roundtrips_without_vault_envelope_overflow(env):
    content = b"x" * MAX_FILE_BYTES
    auth = authorize(env)
    doc = document(env, authorization=auth, filename="maximum.txt", content_base64=base64.b64encode(content).decode())
    assert len(env.store.document_download(env.tokens["a"], doc["document_id"])[0]) == MAX_FILE_BYTES
    assert_error(400, "invalid_file", env.store.create_document, env.tokens["a"],
                 document_payload(auth, filename="oversized.txt", content_base64=base64.b64encode(content + b"x").decode()))


@pytest.mark.parametrize("failure", ["invalid_key", "missing_key", "wrong_key", "corrupt_metadata", "corrupt_file", "other_student_file"])
def test_vault_failures_and_cross_student_ciphertext_substitution_fail_closed(env, monkeypatch, failure):
    doc = document(env)
    if failure == "invalid_key":
        monkeypatch.setenv("REHAB_DEMO2_DOSSIER_KEY", "invalid")
    elif failure == "missing_key":
        from rehab_affect import demo2_dossier_vault as vault_module
        monkeypatch.delenv("REHAB_DEMO2_DOSSIER_KEY")
        monkeypatch.setattr(vault_module, "_IS_WINDOWS", False)
    elif failure == "wrong_key":
        monkeypatch.setenv("REHAB_DEMO2_DOSSIER_KEY", Fernet.generate_key().decode())
    elif failure == "corrupt_metadata":
        with env.records._connect() as connection:
            connection.execute("UPDATE demo2_dossier_documents SET metadata_ciphertext = ? WHERE document_id = ?", (b"invalid", doc["document_id"]))
    elif failure == "corrupt_file":
        env.store._file(doc["document_id"]).write_bytes(b"invalid")
    else:
        other = document(env, "a2", content_base64=base64.b64encode(b"different student original").decode())
        env.store._file(doc["document_id"]).write_bytes(env.store._file(other["document_id"]).read_bytes())
    reopened = Demo2DossierStore(env.records)
    with pytest.raises(DossierError) as error:
        reopened.document_download(env.tokens["a"], doc["document_id"])
    assert error.value.status == 503
    assert SECRET not in str(error.value) and str(env.tmp) not in str(error.value)


def test_missing_key_cannot_save_authorization_or_any_plaintext(env, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_DOSSIER_KEY", "")
    assert_error(503, "vault_unavailable", env.store.save_authorization, env.tokens["a"], auth_payload(env))
    assert not query(env, "SELECT * FROM demo2_dossier_authorizations")
    assert env.store.admin_summary(env.tokens["admin"])["vault"] == {"available": False, "mode": "unavailable"}


def test_immutable_version_families_and_historical_reference_do_not_follow_new_summary(env):
    auth = authorize(env)
    original = document(env, authorization=auth)
    video = task(env)
    recorded = reference(env, video, [original])
    newer = document(env, authorization=auth, supersedes_id=original["document_id"], summary={key: "new approved version" for key in SUMMARY_FIELDS})
    assert newer["version"] == 2 and newer["family_id"] == original["family_id"]
    exported = env.store.reference_export(env.tokens["a"], recorded["reference_id"])
    assert exported["document_versions"] == [{"document_id": original["document_id"], "version": 1}]
    assert exported["documents"][0]["summary"] == original["summary"]
    assert "new approved version" not in json.dumps(exported)
    assert_error(409, "successor_exists", env.store.create_document, env.tokens["a"], document_payload(auth, supersedes_id=original["document_id"]))
    assert_error(409, "version_type_mismatch", env.store.create_document, env.tokens["a"],
                 document_payload(auth, supersedes_id=newer["document_id"], document_type="safety_support"))
    other_auth = authorize(env, "a2")
    assert_error(404, "document_unavailable", env.store.create_document, env.tokens["a"], document_payload(other_auth, supersedes_id=newer["document_id"]))


@pytest.mark.parametrize("reason", ["delete", "withdraw", "document_expired", "authorization_expired"])
def test_lifecycle_clears_sensitive_columns_deletes_files_and_cannot_resurrect_exports(env, reason, monkeypatch):
    auth = authorize(env)
    doc = document(env, authorization=auth)
    video = task(env)
    ref = reference(env, video, [doc])
    if reason == "delete":
        env.store.delete_document(env.tokens["a"], {"student_id": doc["student_id"], "document_id": doc["document_id"], "confirmed": True})
    elif reason == "withdraw":
        env.store.withdraw_authorization(env.tokens["a"], {"student_id": doc["student_id"], "authorization_id": auth["authorization_id"], "confirmed": True})
    else:
        deadline = module._today() + timedelta(days=20 if reason == "document_expired" else 30)
        monkeypatch.setattr(module, "_today", lambda: deadline)
        env.store.cleanup_expired()
    assert not env.store._file(doc["document_id"]).exists()
    row = query(env, "SELECT * FROM demo2_dossier_documents WHERE document_id = ?", (doc["document_id"],))[0]
    assert row["metadata_ciphertext"] is None and row["has_file"] == 0
    assert_error(410, "document_unavailable", env.store.document_download, env.tokens["a"], doc["document_id"])
    exported = env.store.reference_export(env.tokens["a"], ref["reference_id"])
    assert exported["available"] is False and exported["status"] == "sources_unavailable"
    assert exported["documents"][0]["summary"] == {} and exported["documents"][0]["filename"] == ""
    assert SECRET not in json.dumps(exported)
    assert query(env, "SELECT metadata_ciphertext FROM demo2_dossier_references")[0]["metadata_ciphertext"] is None
    assert env.store.cleanup_expired()["purged_count"] == 0


@pytest.mark.parametrize("reason", ["revoked_binding", "reprocessed", "source_missing", "raw_expired"])
def test_old_references_label_invalid_identity_and_cannot_create_new_ones(env, reason):
    doc = document(env)
    video = task(env)
    ref = reference(env, video, [doc])
    if reason == "revoked_binding":
        env.identities.revoke_binding(env.tokens["a"], {"task_id": video.task_id, "binding_id": video.binding["binding_id"], "reason": "测试撤销"})
    elif reason == "source_missing":
        video.source.unlink()
    else:
        with env.records._connect() as connection:
            if reason == "reprocessed":
                connection.execute("UPDATE video_analysis_tasks SET processing_result_json = processing_result_json || ' ' WHERE task_id = ?", (video.task_id,))
            else:
                connection.execute("UPDATE video_analysis_tasks SET expires_at = '2000-01-01T00:00:00+00:00' WHERE task_id = ?", (video.task_id,))
    exported = env.store.reference_export(env.tokens["a"], ref["reference_id"])
    assert exported["available"] is False and exported["status"] != "available" and exported["evidence_status"] != "current"
    assert exported["documents"][0]["available"] is True
    assert env.store.task_workspace(env.tokens["a"], video.task_id)["students"] == []
    with pytest.raises(DossierError) as error:
        reference(env, video, [doc])
    assert error.value.status == 409


def test_references_require_canonical_student_current_binding_and_same_student_versions(env):
    first = document(env)
    other = document(env, "a2")
    video = task(env)
    assert_error(404, "document_unavailable", env.store.create_reference, env.tokens["a"], reference_payload(env, video, [other]))
    assert_error(409, "identity_unavailable", env.store.create_reference, env.tokens["a"], reference_payload(env, video, [other], "a2"))
    for ids in ([], [first["document_id"]] * 2, [str(index) for index in range(11)], "not-list"):
        assert_error(400, "invalid_document_ids", env.store.create_reference, env.tokens["a"], reference_payload(env, video, [first], document_ids=ids))
    workspace = env.store.task_workspace(env.tokens["a"], video.task_id)
    assert len(workspace["students"]) == 1 and workspace["students"][0]["student_id"] == first["student_id"]


def test_unlink_failure_immediately_blocks_access_and_retries_after_reopen(env, monkeypatch):
    doc = document(env)
    path = env.store._file(doc["document_id"])
    original = Path.unlink

    def denied(value, *args, **kwargs):
        if value == path:
            raise PermissionError("private path must not leak: " + str(path))
        return original(value, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", denied)
        outcome = env.store.delete_document(env.tokens["a"], {"student_id": doc["student_id"], "document_id": doc["document_id"], "confirmed": True})
        assert outcome["status"] == "deletion_pending" and path.exists()
        row = query(env, "SELECT * FROM demo2_dossier_documents")[0]
        assert row["metadata_ciphertext"] is None
        assert_error(410, "document_unavailable", env.store.document_download, env.tokens["a"], doc["document_id"])
        assert env.store.admin_summary(env.tokens["admin"])["totals"]["deletion_pending_count"] == 1
        assert str(path) not in json.dumps(query(env, "SELECT * FROM audit_logs WHERE object_type = 'demo2_dossier'"))
    reopened = Demo2DossierStore(env.records)
    assert reopened.cleanup_expired()["purged_count"] == 1 and not path.exists()
    assert reopened.cleanup_expired()["purged_count"] == 0


def test_failed_write_leaves_inaccessible_tombstone_and_removes_partial_ciphertext(env, monkeypatch):
    auth = authorize(env)

    def partial_failure(object_id, ciphertext):
        env.store.root.mkdir(exist_ok=True)
        env.store._file(object_id, temporary=True).write_bytes(ciphertext[:100])
        raise OSError("sensitive provider error " + SECRET)

    monkeypatch.setattr(env.store, "_write_file", partial_failure)
    assert_error(503, "storage_unavailable", env.store.create_document, env.tokens["a"], document_payload(auth))
    row = query(env, "SELECT * FROM demo2_dossier_documents")[0]
    assert row["status"] == "deleted" and row["metadata_ciphertext"] is None
    assert not list(env.store.root.glob("*.tmp")) and not list(env.store.root.glob("*.enc"))


def test_unknown_ciphertext_orphan_cleanup_retries_without_touching_unmanaged_files(env, monkeypatch):
    env.store.cleanup_expired()  # Establish ownership before simulating a crashed write.
    orphan_id = uuid4().hex
    orphan = env.store.root / (orphan_id + ".tmp")
    orphan.write_bytes(Fernet(env.key.encode()).encrypt(b"synthetic orphan"))
    sentinel = env.store.root / "unmanaged.txt"
    sentinel.write_bytes(b"leave untouched")
    unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path == orphan:
            raise PermissionError("test")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail)
        assert env.store.cleanup_expired()["deletion_pending_count"] == 1
        assert query(env, "SELECT status FROM demo2_dossier_file_cleanup")[0]["status"] == "deletion_pending"
    assert env.store.cleanup_expired()["purged_count"] == 1
    assert not orphan.exists() and sentinel.read_bytes() == b"leave untouched"


def test_storage_marker_binds_canonical_path_and_persistent_database_identity(env):
    env.store.cleanup_expired()
    marker = env.store.root / module.STORAGE_OWNER_FILE
    saved = marker.read_bytes()
    value = json.loads(saved)
    canonical = os.path.normcase(str(env.records.db_path.resolve()))
    assert value["database_path_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert value["database_id"] == query(env, "SELECT database_id FROM demo2_dossier_storage_identity")[0]["database_id"]
    assert canonical.encode() not in saved
    alternate = env.records.db_path.parent / "unused" / ".." / env.records.db_path.name
    alternate.parent.mkdir(exist_ok=True)
    reopened = Demo2DossierStore(Demo2StudentRecordStore(alternate, env.records.upload_dir))
    with reopened.records._connect() as connection:
        assert reopened._storage_owned(connection)
    assert marker.read_bytes() == saved
    doc = document(env)
    assert reopened.document_download(env.tokens["a"], doc["document_id"])[0] == (SECRET + "-original").encode()


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("copied", [False, True])
def test_other_database_cannot_purge_shared_root_or_replay_pending_deletions(env, template, marked, copied):
    doc = document(env)
    marker = env.store.root / module.STORAGE_OWNER_FILE
    if not marked:
        marker.unlink()  # Simulate a populated pre-marker installation, in tmp_path only.
    orphan_id = uuid4().hex
    (env.store.root / (orphan_id + ".tmp")).write_bytes(b"preserve crash artifact")
    before = {path.name: path.read_bytes() for path in env.store.root.iterdir()}
    database = env.tmp / "other.sqlite3"
    with sqlite3.connect(env.records.db_path if copied else template.path) as source, sqlite3.connect(database) as target:
        source.backup(target)
    other_records = Demo2StudentRecordStore(database, env.records.upload_dir)
    other = Demo2DossierStore(other_records)
    with other_records._connect() as connection:
        connection.execute("UPDATE demo2_dossier_documents SET status = 'deletion_pending'")
        connection.execute("INSERT INTO demo2_dossier_file_cleanup VALUES (?, 'deletion_pending', 0, '', '')", (orphan_id,))
    for _ in range(2):
        outcome = other.cleanup_expired()
        assert outcome["purged_count"] == 0
        assert outcome["deletion_pending_count"] == 1 + int(copied)
    assert {path.name: path.read_bytes() for path in env.store.root.iterdir()} == before
    assert env.store.document_download(env.tokens["a"], doc["document_id"])[0] == (SECRET + "-original").encode()
    if copied:
        with other_records._connect() as connection:
            identity = connection.execute("SELECT database_id FROM demo2_dossier_storage_identity").fetchone()[0]
        assert identity == query(env, "SELECT database_id FROM demo2_dossier_storage_identity")[0]["database_id"]


def test_unmarked_populated_root_preserves_existing_reads_and_blocks_original_writes(env):
    doc = document(env)
    (env.store.root / module.STORAGE_OWNER_FILE).unlink()
    original = env.store._file(doc["document_id"])
    saved = original.read_bytes()
    reopened = Demo2DossierStore(env.records)
    assert reopened.document_download(env.tokens["a"], doc["document_id"])[0] == (SECRET + "-original").encode()
    assert_error(503, "storage_unavailable", reopened.create_document, env.tokens["a"],
                 document_payload(doc, supersedes_id=doc["document_id"]))
    with env.records._connect() as connection:
        connection.execute("UPDATE demo2_dossier_documents SET retain_until = ?", (day(-1),))
    assert reopened.cleanup_expired()["purged_count"] == 0
    assert original.read_bytes() == saved
    assert not (env.store.root / module.STORAGE_OWNER_FILE).exists()
    assert len(query(env, "SELECT * FROM demo2_dossier_documents")) == 1
    assert_error(410, "document_unavailable", reopened.document_download, env.tokens["a"], doc["document_id"])


def test_competing_databases_only_one_can_claim_an_empty_root(env, template):
    database = env.tmp / "competitor.sqlite3"
    with sqlite3.connect(template.path) as source, sqlite3.connect(database) as target:
        source.backup(target)
    other = Demo2DossierStore(Demo2StudentRecordStore(database, env.records.upload_dir))
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda store: store.cleanup_expired(), (env.store, other)))
    owners = []
    for store in (env.store, other):
        with store.records._connect() as connection:
            owners.append(store._storage_owned(connection))
    assert owners.count(True) == 1
    owner, stranger = (env.store, other) if owners[0] else (other, env.store)
    orphan = owner.root / (uuid4().hex + ".tmp")
    orphan.write_bytes(b"synthetic orphan")
    assert stranger.cleanup_expired()["purged_count"] == 0 and orphan.exists()
    assert owner.cleanup_expired()["purged_count"] == 1 and not orphan.exists()


@pytest.mark.parametrize("damage", ["malformed", "oversized", "identity", "reparse"])
def test_invalid_owner_marker_or_replaced_database_fails_closed(env, monkeypatch, damage):
    env.store.cleanup_expired()
    marker = env.store.root / module.STORAGE_OWNER_FILE
    orphan = env.store.root / (uuid4().hex + ".enc")
    orphan.write_bytes(b"do not delete")
    if damage == "identity":
        with env.records._connect() as connection:
            connection.execute("UPDATE demo2_dossier_storage_identity SET database_id = ?", (uuid4().hex,))
    elif damage == "reparse":
        original = Path.lstat

        def linked(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=1024) if path == marker else info

        monkeypatch.setattr(Path, "lstat", linked)
    else:
        marker.write_bytes(b"{" if damage == "malformed" else b"x" * 4097)
    saved = marker.read_bytes()
    assert env.store.cleanup_expired()["purged_count"] == 0
    assert orphan.read_bytes() == b"do not delete" and marker.read_bytes() == saved
    assert not query(env, "SELECT * FROM demo2_dossier_file_cleanup")


def test_nonredirecting_reparse_ciphertext_is_never_read_or_purged(env, monkeypatch):
    doc = document(env)
    path = env.store._file(doc["document_id"])
    original = Path.lstat

    def linked(value, *args, **kwargs):
        result = original(value, *args, **kwargs)
        if value == path:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=1024)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", linked)
        assert_error(503, "storage_unavailable", env.store.document_download, env.tokens["a"], doc["document_id"])
        assert env.store.delete_document(env.tokens["a"], {"student_id": doc["student_id"], "document_id": doc["document_id"], "confirmed": True})["status"] == "deletion_pending"
    assert path.exists()
    assert env.store.cleanup_expired()["purged_count"] == 1


def test_admin_exact_statistics_never_expose_student_or_dossier_content(env):
    first = document(env)
    second = document(env, "b1")
    summary = env.store.admin_summary(env.tokens["admin"])
    assert set(summary) == {"totals", "channels", "policy", "vault"}
    assert set(summary["totals"]) == {"authorization_count", "active_authorization_count", "document_count", "available_document_count",
                                     "expired_document_count", "deletion_pending_count", "reference_count", "encrypted_file_bytes"}
    assert summary["totals"]["document_count"] == summary["totals"]["available_document_count"] == 2
    assert summary["totals"]["encrypted_file_bytes"] == sum(env.store._file(doc["document_id"]).stat().st_size for doc in (first, second))
    assert len(summary["channels"]) == 4
    assert [item["document_count"] for item in summary["channels"]] == [1, 1, 0, 0]
    assert all(set(item) == {"channel_no", "document_count", "available_document_count", "deletion_pending_count", "encrypted_file_bytes"} for item in summary["channels"])
    assert summary["policy"] == {"max_retention_days": 60, "training_allowed": False, "raw_documents_visible": False}
    encoded = json.dumps(summary, ensure_ascii=False)
    for value in (SECRET, "虚构同名学生", first["student_id"], first["document_id"], env.key, str(env.tmp), "filename", "source_ref", "reference"):
        if value == "reference":
            continue  # reference_count is an explicitly required safe count.
        assert value not in encoded
    assert_error(403, "dossier_forbidden", env.store.admin_summary, env.tokens["a"])


def test_concurrent_authorization_and_successor_are_serialized(env):
    stores = [Demo2DossierStore(env.records) for _ in range(3)]

    def authorize_one(store):
        try:
            return store.save_authorization(env.tokens["a"], auth_payload(env))
        except DossierError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as executor:
        outcomes = list(executor.map(authorize_one, stores))
    assert outcomes.count("authorization_exists") == 2
    auth = next(item for item in outcomes if isinstance(item, dict))
    original = document(env, authorization=auth)

    def successor(store):
        try:
            return store.create_document(env.tokens["a"], document_payload(auth, supersedes_id=original["document_id"]))["version"]
        except DossierError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as executor:
        versions = list(executor.map(successor, stores))
    assert versions.count(2) == 1 and versions.count("successor_exists") == 2
