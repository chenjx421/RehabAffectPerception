"""Independent dossier acceptance using fictional data and temporary keys only."""
from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from cryptography.fernet import Fernet

from scripts.qa_demo2_dossier_20260911 import (
    API, FAKE_AUTH, FAKE_TEXT, KEY_ENV, SUMMARY_KEYS, authorization_payload,
    day, document_payload, http, isolated_dossier_server,
)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with isolated_dossier_server(tmp_path_factory.mktemp("dossier")) as isolated:
        yield isolated


@pytest.fixture()
def fresh(tmp_path):
    with isolated_dossier_server(tmp_path) as isolated:
        yield isolated


def get(env, route, **params):
    return http(env, "GET", API + route + ("?" + urlencode(params) if params else ""))


def create(env, route, payload, field):
    status, headers, body = http(env, "POST", API + route, payload)
    assert status == 200 and body.get("ok") is True, (status, body)
    assert_private(headers)
    return body[field]


def auth(env, **options):
    return create(env, "/authorization", authorization_payload(env, **options), "authorization")


def doc(env, authorization, **options):
    return create(env, "/documents", document_payload(env, authorization, **options), "document")


def reference(env, document, **changes):
    return create(env, "/references", {"task_id": env.task_ids["t1"],
                  "student_id": env.students["a"]["student_id"],
                  "frame_revision": env.binding_payload["frame_revision"],
                  "document_ids": [document["document_id"]], "confirmed": True, **changes}, "reference")


def assert_private(headers):
    assert "no-store" in headers.get("cache-control", "")
    assert "private" in headers.get("cache-control", "")


def serial(value):
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, bytes) else value.decode("utf-8", errors="replace")


def no_private_paths(env, value):
    encoded = serial(value).replace("\\\\", "\\")
    for secret in [str(env.root), str(env.records.db_path), env.vault_key, *env.tokens.values(), *env.users.values()]:
        assert secret not in encoded
    assert "password_hash" not in encoded and "file_path" not in encoded


def nested_dicts(value):
    if isinstance(value, dict):
        yield value
        for part in value.values():
            yield from nested_dicts(part)
    elif isinstance(value, list):
        for part in value:
            yield from nested_dicts(part)


@pytest.mark.parametrize("route", ["/student?student_id=unknown", "/task?task_id=unknown",
                                   "/document?document_id=unknown", "/reference?reference_id=unknown", "/admin"])
@pytest.mark.parametrize("user,expected", [(None, 401), ("member", 403)])
def test_dossier_get_auth_precedes_lookup(env, route, user, expected):
    status, headers, body = http(env, "GET", API + route, user=user)
    assert status == expected
    assert_private(headers)
    no_private_paths(env, body)


@pytest.mark.parametrize("route", ["/authorization", "/authorization/withdraw", "/documents", "/documents/delete", "/references"])
@pytest.mark.parametrize("user,expected", [(None, 401), ("member", 403), ("admin", 403)])
def test_dossier_write_auth_precedes_body(env, route, user, expected):
    status, headers, body = http(env, "POST", API + route, {"malformed": True}, user=user)
    assert status == expected
    assert_private(headers)
    no_private_paths(env, body)


@pytest.mark.parametrize("change", [{"confirmed": False}, {"confirmed": "true"}, {"valid_until": day(-1)},
                                   {"valid_until": day(61)}, {"storage_mode": "training"}, {"reference": ""},
                                   {"purpose": "model_training"}, {"owner_account_id": "forged"}])
def test_authorization_invalid_or_forged_has_no_live_record(env, change):
    status, _, _ = http(env, "POST", API + "/authorization", authorization_payload(env, **change))
    assert status == 400
    assert get(env, "/student", student_id=env.students["a"]["student_id"])[2]["workspace"]["authorization"] is None


def test_teacher_version_reference_withdraw_delete_lifecycle(fresh):
    env = fresh
    sid = env.students["a"]["student_id"]
    initial = get(env, "/student", student_id=sid)[2]["workspace"]
    assert initial["student"]["student_id"] == sid and initial["authorization"] is None
    assert initial["policy"] == {"max_retention_days": 60, "training_allowed": False}
    assert initial["legacy_notice"] and initial["vault"]["available"] is True
    authorization = auth(env)
    assert authorization["purpose"] == "education_support"
    assert http(env, "POST", API + "/authorization", authorization_payload(env))[0] == 409
    v1 = doc(env, authorization)
    status, headers, content = get(env, "/document", document_id=v1["document_id"])
    assert status == 200 and content == FAKE_TEXT + b" V1"
    assert_private(headers)
    assert "attachment" in headers.get("content-disposition", "").lower()
    assert "nosniff" == headers.get("x-content-type-options")
    assert get(env, "/task", task_id=env.task_ids["t1"])[2]["workspace"]["students"] == []
    unbound = {"task_id": env.task_ids["t1"], "student_id": sid,
               "frame_revision": env.binding_payload["frame_revision"], "document_ids": [v1["document_id"]], "confirmed": True}
    assert http(env, "POST", API + "/references", unbound)[0] in (403, 409)
    env.bind()
    old_ref = reference(env, v1)
    v2 = doc(env, authorization, version=2, supersedes_id=v1["document_id"])
    assert v2["family_id"] == v1["family_id"] and (v1["version"], v2["version"]) == (1, 2)
    assert http(env, "POST", API + "/documents", document_payload(env, authorization, version=3, supersedes_id=v1["document_id"]))[0] == 409
    exported = get(env, "/reference", reference_id=old_ref["reference_id"])[2]
    assert v1["document_id"] in serial(exported) and v2["document_id"] not in serial(exported)
    assert any(r.get("document_id") == v1["document_id"] and r.get("version") == 1 for r in nested_dicts(exported))
    assert "FICTIONAL-learning_goals-V2" not in serial(exported)
    no_private_paths(env, exported)
    result = create(env, "/documents/delete", {"student_id": sid, "document_id": v2["document_id"], "confirmed": True}, "result")
    assert isinstance(result, dict)
    assert get(env, "/document", document_id=v2["document_id"])[0] in (404, 410)
    assert get(env, "/document", document_id=v1["document_id"])[0] == 200
    withdrawal = {"student_id": sid, "authorization_id": authorization["authorization_id"], "confirmed": True}
    create(env, "/authorization/withdraw", withdrawal, "result")
    create(env, "/authorization/withdraw", withdrawal, "result")
    assert get(env, "/document", document_id=v1["document_id"])[0] in (404, 410)
    retained = get(env, "/student", student_id=sid)[2]
    for marker in (FAKE_AUTH, "FICTIONAL-SOURCE", "FICTIONAL-learning_goals", "FICTIONAL-IEP"):
        assert marker not in serial(retained)
        assert marker not in serial(get(env, "/reference", reference_id=old_ref["reference_id"])[2])
    env.dossier.cleanup_expired()
    env.dossier.cleanup_expired()
    assert not list(env.vault_root.rglob("*.enc")), "Deleted documents must be physically purged"


def test_scope_admin_and_cross_student_reference_are_rejected(fresh):
    env = fresh
    a = auth(env)
    document = doc(env, a)
    env.bind()
    ref = reference(env, document)
    routes = ["/student?" + urlencode({"student_id": env.students["a"]["student_id"]}),
              "/task?" + urlencode({"task_id": env.task_ids["t1"]}),
              "/document?" + urlencode({"document_id": document["document_id"]}),
              "/reference?" + urlencode({"reference_id": ref["reference_id"]})]
    for user in ("t2", "t3", "t4", "admin"):
        for route in routes:
            status, _, body = http(env, "GET", API + route, user=user)
            assert status == 403 if user == "admin" else status in (403, 404)
            assert FAKE_AUTH not in serial(body) and "FICTIONAL-learning_goals" not in serial(body)
    payload = {"task_id": env.task_ids["t1"], "student_id": env.students["b"]["student_id"],
               "frame_revision": env.binding_payload["frame_revision"], "document_ids": [document["document_id"]], "confirmed": True}
    assert http(env, "POST", API + "/references", payload)[0] in (403, 404, 409)
    assert http(env, "POST", API + "/authorization", authorization_payload(env), user="t2")[0] in (403, 404)
    assert get(env, "/admin")[0] == 403
    status, headers, data = http(env, "GET", API + "/admin", user="admin")
    assert status == 200
    assert_private(headers)
    summary = data["summary"]
    assert set(summary) == {"totals", "channels", "policy", "vault"}
    assert set(summary["totals"]) == {"authorization_count", "active_authorization_count", "document_count", "available_document_count",
                                      "expired_document_count", "deletion_pending_count", "reference_count", "encrypted_file_bytes"}
    assert summary["policy"] == {"max_retention_days": 60, "training_allowed": False, "raw_documents_visible": False}
    for channel in summary["channels"]:
        assert set(channel) == {"channel_no", "document_count", "available_document_count", "deletion_pending_count", "encrypted_file_bytes"}
    for forbidden in (FAKE_AUTH, "虚构同名学生", "FICTIONAL-IEP", "FICTIONAL-SOURCE", "FICTIONAL-learning_goals", document["document_id"]):
        assert forbidden not in serial(data)
    no_private_paths(env, data)


def test_encrypted_at_rest_and_audit_content_minimized(fresh):
    env = fresh
    a = auth(env)
    d = doc(env, a)
    env.bind()
    reference(env, d)
    markers = [FAKE_AUTH, "FICTIONAL-IEP-V1.txt", "FICTIONAL-SOURCE-QA-V1", "FICTIONAL-learning_goals-V1"]
    with sqlite3.connect(env.records.db_path) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%dossier%'")]
        assert tables
        for table in tables:
            assert table.replace("_", "").isalnum()
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            for row in rows:
                text = " ".join(str(value) for value in row)
                for marker in markers:
                    assert marker not in text
        audit = " ".join(str(row) for row in connection.execute("SELECT * FROM audit_logs WHERE action LIKE '%dossier%'"))
        for marker in [*markers, "虚构同名学生"]:
            assert marker not in audit
    files = [p for p in env.vault_root.rglob("*") if p.is_file()]
    assert files
    assert any(Fernet(env.vault_key.encode()).decrypt(p.read_bytes()) == FAKE_TEXT + b" V1" for p in files if p.suffix == ".enc")
    for p in files:
        raw = p.read_bytes()
        assert FAKE_TEXT not in raw and env.vault_key.encode() not in raw
    for p in env.records.db_path.parent.glob(env.records.db_path.name + "*"):
        if p.is_file():
            for marker in markers:
                assert marker.encode() not in p.read_bytes()


def test_summary_only_cannot_upload_original_and_invalid_files_are_rejected(fresh):
    env = fresh
    a = auth(env, mode="summary_only")
    assert http(env, "POST", API + "/documents", document_payload(env, a))[0] == 400
    d = doc(env, a, with_file=False)
    assert d["has_file"] is False and not d.get("filename")
    assert get(env, "/document", document_id=d["document_id"])[0] in (404, 409, 410)
    other = auth(env, student="b")
    for changes in ({"filename": "bad.html"}, {"filename": "../bad.txt"}, {"filename": "bad.pdf"},
                    {"content_base64": "%%%"}, {"document_date": day(1)}, {"retain_until": day(31)},
                    {"summary": {**{key: "" for key in SUMMARY_KEYS}, "diagnosis_by_ai": "forbidden"}}):
        status, _, _ = http(env, "POST", API + "/documents", document_payload(env, other, student="b", **changes))
        assert status == 400


def test_revoked_binding_and_old_revision_cannot_create_reference(fresh):
    env = fresh
    a = auth(env)
    d = doc(env, a)
    binding = env.bind()
    old = reference(env, d)
    env.identity.revoke_binding(env.tokens["t1"], {"task_id": env.task_ids["t1"], "binding_id": binding["binding_id"], "reason": "虚构QA撤销"})
    payload = {"task_id": env.task_ids["t1"], "student_id": env.students["a"]["student_id"],
               "frame_revision": env.binding_payload["frame_revision"], "document_ids": [d["document_id"]], "confirmed": True}
    assert http(env, "POST", API + "/references", payload)[0] in (403, 409)
    exported = get(env, "/reference", reference_id=old["reference_id"])[2]
    assert exported["evidence_status"] != "current"
    env.refresh_revision(env.task_ids["t1"])
    assert http(env, "POST", API + "/references", payload)[0] in (403, 409)


@pytest.mark.parametrize("query", ["student_id=a&student_id=b", "student_id=a&path=private", ""])
def test_exact_query_and_json_only_contract(env, query):
    assert http(env, "GET", API + "/student?" + query)[0] == 400
    assert http(env, "POST", API + "/authorization", authorization_payload(env), content_type="text/plain")[0] in (400, 415)


def test_old_sensitive_routes_do_not_bypass_scoped_authorization(fresh):
    env = fresh
    env.records.ensure_students([{"student_id": "QA_LEGACY", "display_name": "虚构旧档案"}])
    old = env.records.save_document({"student_id": "QA_LEGACY", "document_type": "iep", "filename": "LEGACY-PRIVATE.txt",
                                    "content_base64": base64.b64encode(FAKE_TEXT).decode()})
    paths = ["/api/seewo_demo2/document_download?id=" + old["document_id"],
             "/api/seewo_demo2/student_record?student_id=QA_LEGACY"]
    for user in ("t1", "t2", "admin"):
        for path in paths:
            status, _, body = http(env, "GET", path, user=user)
            assert status in (403, 410), (path, status)
            assert FAKE_TEXT.decode() not in serial(body) and "LEGACY-PRIVATE" not in serial(body)
        assert http(env, "POST", "/api/seewo_demo2/student_document", {}, user=user)[0] in (403, 410)
    with sqlite3.connect(env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM student_documents WHERE document_id=?", (old["document_id"],)).fetchone()[0] == 1


@pytest.mark.parametrize("mode", ["invalid_key", "missing_nonwindows_key", "different_valid_key"])
def test_key_unavailable_or_changed_never_falls_back_to_plaintext(fresh, mode):
    from src.rehab_affect import demo2_dossier_vault as vault

    env = fresh
    a = auth(env)
    document = doc(env, a)
    files = {p: p.read_bytes() for p in env.vault_root.glob("*.enc")}
    with patch.dict(os.environ):
        if mode == "missing_nonwindows_key":
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = "invalid-QA-key" if mode == "invalid_key" else Fernet.generate_key().decode()
        # Simulates the contract's unsupported-platform missing-key branch;
        # never creates a DPAPI key or changes the host's OS environment.
        with patch.object(vault, "_IS_WINDOWS", False):
            status, _, body = get(env, "/document", document_id=document["document_id"])
            assert status == 503
            assert FAKE_TEXT.decode() not in serial(body)
            no_private_paths(env, body)
    assert {p: p.read_bytes() for p in files} == files
    assert get(env, "/document", document_id=document["document_id"])[0] == 200


@pytest.mark.parametrize("deadline", ["authorization", "document"])
def test_expiry_read_cleanup_clears_sensitive_columns_and_old_exports(fresh, deadline):
    env = fresh
    a = auth(env)
    d = doc(env, a)
    env.bind()
    ref = reference(env, d)
    with sqlite3.connect(env.records.db_path) as connection:
        if deadline == "authorization":
            connection.execute("UPDATE demo2_dossier_authorizations SET valid_until=? WHERE authorization_id=?", (day(-1), a["authorization_id"]))
        else:
            connection.execute("UPDATE demo2_dossier_documents SET retain_until=? WHERE document_id=?", (day(-1), d["document_id"]))
    assert get(env, "/document", document_id=d["document_id"])[0] in (404, 410)
    exported = get(env, "/reference", reference_id=ref["reference_id"])[2]
    assert "FICTIONAL-learning_goals" not in serial(exported) and "FICTIONAL-SOURCE" not in serial(exported)
    assert exported["available"] is False
    with sqlite3.connect(env.records.db_path) as connection:
        assert connection.execute("SELECT metadata_ciphertext FROM demo2_dossier_documents WHERE document_id=?", (d["document_id"],)).fetchone()[0] is None
        if deadline == "authorization":
            assert connection.execute("SELECT metadata_ciphertext FROM demo2_dossier_authorizations WHERE authorization_id=?", (a["authorization_id"],)).fetchone()[0] is None
    assert not list(env.vault_root.glob("*.enc"))


def test_unlink_failure_keeps_deleted_content_inaccessible_and_retries(fresh):
    env = fresh
    a = auth(env)
    d = doc(env, a)
    original_unlink = Path.unlink

    def busy(path, *args, **kwargs):
        if path.parent == env.vault_root and path.suffix == ".enc":
            raise PermissionError("synthetic QA file-busy condition")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", busy):
        create(env, "/documents/delete", {"student_id": env.students["a"]["student_id"], "document_id": d["document_id"], "confirmed": True}, "result")
        assert get(env, "/document", document_id=d["document_id"])[0] in (404, 410)
        status, _, response = http(env, "GET", API + "/admin", user="admin")
        assert status == 200 and response["summary"]["totals"]["deletion_pending_count"] == 1
        with sqlite3.connect(env.records.db_path) as connection:
            state = connection.execute("SELECT status, metadata_ciphertext FROM demo2_dossier_documents WHERE document_id=?", (d["document_id"],)).fetchone()
            assert state == ("deletion_pending", None)
    env.dossier.cleanup_expired()
    env.dossier.cleanup_expired()
    assert not list(env.vault_root.glob("*.enc"))
    assert get(env, "/document", document_id=d["document_id"])[0] in (404, 410)


def test_independent_store_reopen_preserves_ciphertext_and_canonical_student(fresh):
    from src.rehab_affect.demo2_dossier_store import Demo2DossierStore, DossierError
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    env = fresh
    a = env.dossier.save_authorization(env.tokens["t1"], authorization_payload(env))
    document = env.dossier.create_document(env.tokens["t1"], document_payload(env, a))
    reopened_records = Demo2StudentRecordStore(env.records.db_path, env.records.upload_dir)
    reopened = Demo2DossierStore(reopened_records)
    workspace = reopened.student_workspace(env.tokens["t1"], env.students["a"]["student_id"])
    assert workspace["student"]["student_id"] == env.students["a"]["student_id"]
    assert workspace["documents"][0]["summary"]["learning_goals"] == "FICTIONAL-learning_goals-V1"
    assert reopened.document_download(env.tokens["t1"], document["document_id"])[0] == FAKE_TEXT + b" V1"
    with pytest.raises(DossierError) as error:
        reopened.document_download(env.tokens["t2"], document["document_id"])
    assert error.value.status in (403, 404)
    with patch.dict(os.environ, {KEY_ENV: "invalid-QA-key"}):
        with pytest.raises(DossierError) as error:
            reopened.document_download(env.tokens["t1"], document["document_id"])
        assert error.value.status == 503
    assert reopened.document_download(env.tokens["t1"], document["document_id"])[0] == FAKE_TEXT + b" V1"


def test_docx_metadata_and_eight_mib_limit_are_enforced(fresh):
    env = fresh
    a = auth(env)
    for name, entries in (
        ("macro.docx", {"[Content_Types].xml": b"macroEnabled", "word/document.xml": b"synthetic", "word/vbaProject.bin": b"synthetic"}),
        ("bomb.docx", {"[Content_Types].xml": b"synthetic", "word/document.xml": b"A" * 200000}),
        ("traversal.docx", {"[Content_Types].xml": b"synthetic", "word/document.xml": b"synthetic", "../outside.txt": b"synthetic"}),
    ):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry, content in entries.items():
                archive.writestr(entry, content)
        payload = document_payload(env, a, filename=name, content_base64=base64.b64encode(buffer.getvalue()).decode())
        assert http(env, "POST", API + "/documents", payload)[0] == 400
    oversized = base64.b64encode(b"A" * (8 * 1024 * 1024 + 1)).decode()
    assert http(env, "POST", API + "/documents", document_payload(env, a, content_base64=oversized))[0] == 400
    assert get(env, "/student", student_id=env.students["a"]["student_id"])[2]["workspace"]["documents"] == []
