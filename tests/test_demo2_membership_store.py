from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Barrier

import pytest

from rehab_affect import demo2_membership_store as membership_module
from rehab_affect.demo2_membership_store import Demo2MembershipStore, MembershipError
from rehab_affect.student_record_store import Demo2StudentRecordStore


PHONE = "13800000001"
PASSWORD = "MemberTest123"
SOURCE = "fixture-source"


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 9, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class SimulatedSmsCapture(list):
    def __repr__(self):
        return "<simulated SMS capture: redacted>"


@pytest.fixture()
def record_store(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "MembershipFixture-")
    return Demo2StudentRecordStore(tmp_path / "membership.sqlite3", tmp_path / "documents")


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def sent():
    # In-memory capture only: no SMS/network provider is involved in these tests.
    return SimulatedSmsCapture()


@pytest.fixture()
def store(record_store, clock, sent):
    return Demo2MembershipStore(record_store, sms_sender=lambda phone, code: sent.append((phone, code)), now=clock)


def payload(otp_code, phone=PHONE, **changes):
    return {"phone": phone, "code": otp_code, "password": PASSWORD,
            "agreement_version": "2026-09-09", "accepted": True, **changes}


def register_member(store, sent, phone=PHONE):
    store.request_code(phone, SOURCE)
    return store.register(payload(sent[-1][1], phone), SOURCE)


def scalar(record_store, sql, parameters=()):
    with record_store._connect() as connection:
        return connection.execute(sql, parameters).fetchone()[0]


def last_otp(record_store):
    with record_store._connect() as connection:
        return dict(connection.execute("SELECT * FROM demo2_membership_otps ORDER BY rowid DESC LIMIT 1").fetchone())


def test_unconfigured_services_are_explicit_and_do_not_create_codes(record_store):
    store = Demo2MembershipStore(record_store)
    config = store.public_config()
    assert config["sms_available"] is False and config["payment_available"] is False
    assert config["agreement_version"] == "2026-09-09"
    assert config["plans"]
    assert all(plan["price_cents"] is None and plan["currency"] == "CNY" and plan["available"] is False
               for plan in config["plans"])
    with pytest.raises(MembershipError) as error:
        store.request_code(PHONE, SOURCE)
    assert (error.value.status, error.value.code) == (503, "sms_not_configured")
    assert str(error.value) == error.value.message
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_membership_otps") == 0


def test_initialization_is_idempotent_and_old_accounts_and_schema_are_unchanged(record_store):
    with record_store._connect() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM platform_accounts ORDER BY account_id")]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    for _ in range(2):
        Demo2MembershipStore(record_store)
    reopened = Demo2StudentRecordStore(record_store.db_path, record_store.upload_dir)
    Demo2MembershipStore(reopened)
    with reopened._connect() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM platform_accounts ORDER BY account_id")] == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        assert connection.execute("SELECT COUNT(*) FROM demo2_memberships").fetchone()[0] == 0


@pytest.mark.parametrize("username,school_access", [("school_uploader_01", True), ("company_admin", False)])
def test_existing_active_pilot_accounts_get_read_only_trial_membership(record_store, username, school_access):
    store = Demo2MembershipStore(record_store)
    with record_store._connect() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM platform_accounts ORDER BY account_id")]
        account_id = connection.execute("SELECT account_id FROM platform_accounts WHERE username = ?", (username,)).fetchone()[0]
    result = store.membership(account_id)
    assert result["status"] == "internal_trial" and result["status_label"] == "内测账号"
    assert result["phone_masked"] == "未绑定手机号" and result["expires_at"] is None
    assert result["orders"] == [] and result["school_access"] is school_access
    assert result["plans"] == store.public_config()["plans"]
    assert result["sms_available"] is False and result["payment_available"] is False
    with pytest.raises(MembershipError) as denied:
        store.create_order(account_id, {"plan_id": "monthly"})
    assert denied.value.code == "member_not_found"
    with record_store._connect() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM platform_accounts ORDER BY account_id")] == before
        assert connection.execute("SELECT COUNT(*) FROM demo2_memberships").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM demo2_membership_orders").fetchone()[0] == 0
        connection.execute("UPDATE platform_accounts SET status = 'inactive' WHERE account_id = ?", (account_id,))
    with pytest.raises(MembershipError) as inactive:
        store.membership(account_id)
    assert inactive.value.status == 404
    with pytest.raises(MembershipError) as unknown:
        store.membership("unknown-account")
    assert unknown.value.status == 404


def test_register_uses_salted_hashes_and_existing_login_but_no_school_access(store, record_store, sent, monkeypatch, caplog):
    monkeypatch.setattr(membership_module.secrets, "randbelow", lambda _: 37291)
    assert store.request_code(PHONE, SOURCE) == {"retry_after": 60, "expires_in": 300}
    code = sent[-1][1]
    assert len(code) == 6 and code.startswith("0")
    otp = last_otp(record_store)
    assert otp["code_hash"] == hashlib.pbkdf2_hmac(
        "sha256", code.encode(), bytes.fromhex(otp["code_salt"]), otp["code_iterations"]).hex()
    account = store.register(payload(code), SOURCE)
    assert account["username"] == PHONE and account["role"] == "registered_member"
    assert account["bound_channel_id"] is None and account["course_upload_limit"] == 5
    assert "password_hash" not in account and "password_salt" not in account
    authenticated = record_store.authenticate_account(PHONE, PASSWORD)
    assert authenticated["account_id"] == account["account_id"]
    session = record_store.create_account_session(authenticated)
    assert record_store.account_from_session(session["token"])["role"] == "registered_member"
    with pytest.raises(ValueError, match="没有学校视频上传权限"):
        record_store.account_upload_workspace(session["token"], "school-course")
    record_store.revoke_account_session(session["token"])
    with record_store._connect() as connection:
        member = dict(connection.execute("SELECT * FROM demo2_memberships").fetchone())
        stored = dict(connection.execute("SELECT * FROM platform_accounts WHERE account_id = ?", (account["account_id"],)).fetchone())
        audit = [dict(row) for row in connection.execute("SELECT * FROM audit_logs WHERE actor = 'membership_service'")]
    assert member["status"] == "inactive" and member["expires_at"] is None
    assert member["agreement_version"] == "2026-09-09" and member["accepted_at"]
    assert stored["password_hash"] == hashlib.pbkdf2_hmac(
        "sha256", PASSWORD.encode(), bytes.fromhex(stored["password_salt"]), stored["password_iterations"]).hex()
    assert stored["password_salt"] != otp["code_salt"]
    serialized = json.dumps([last_otp(record_store), member, stored, audit])
    assert code not in serialized and PASSWORD not in serialized
    assert code not in caplog.text and PASSWORD not in caplog.text
    assert PHONE not in json.dumps(audit)
    assert last_otp(record_store)["status"] == "consumed"


def test_membership_and_admin_summary_mask_phones_and_keep_payment_unavailable(store, sent):
    first = register_member(store, sent)
    second = register_member(store, sent, "13900000002")
    membership = store.membership(first["account_id"])
    assert membership["account_id"] == first["account_id"]
    assert membership["phone_masked"] == "138****0001"
    assert membership["status"] == "inactive" and membership["status_label"] == "未开通"
    assert membership["expires_at"] is None and membership["orders"] == []
    assert membership["school_access"] is False and membership["sms_available"] is True
    assert membership["payment_available"] is False
    summary = store.admin_summary()
    assert len(summary["members"]) == 2 and summary["orders"] == []
    assert summary["sms_available"] is True and summary["payment_available"] is False
    serialized = json.dumps([membership, summary])
    assert PHONE not in serialized and second["username"] not in serialized
    assert "password_hash" not in serialized and "phone_hash" not in serialized


def test_orders_never_trust_client_prices_or_payment_status(store, record_store, sent):
    account = register_member(store, sent)
    for supplied in ({"plan_id": "monthly"}, {"price_cents": 1, "paid": True},
                     {"plan_id": "yearly", "status": "paid", "available": True}, None):
        with pytest.raises(MembershipError) as error:
            store.create_order(account["account_id"], supplied)
        assert (error.value.status, error.value.code) == (503, "payment_not_configured")
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_membership_orders") == 0
    assert store.membership(account["account_id"])["status"] == "inactive"
    assert store.membership(account["account_id"])["school_access"] is False
    for method in (store.membership, lambda value: store.create_order(value, {})):
        with pytest.raises(MembershipError) as error:
            method("not-a-member")
        assert error.value.status == 404


def test_server_plans_are_copied_and_cannot_enable_payment(record_store):
    plans = [{"plan_id": "semester", "name": "学期会员", "description": "测试方案",
              "price_cents": 12000, "currency": "CNY", "duration_days": 180, "available": True}]
    store = Demo2MembershipStore(record_store, plans=plans)
    plans[0]["price_cents"] = 1
    first = store.public_config()
    assert first["plans"][0]["price_cents"] == 12000 and first["plans"][0]["available"] is False
    first["plans"][0]["price_cents"] = 2
    assert store.public_config()["plans"][0]["price_cents"] == 12000
    for changes in ({"price_cents": 0}, {"price_cents": True}, {"price_cents": -1},
                    {"duration_days": 0}, {"currency": "USD"}):
        with pytest.raises(ValueError):
            Demo2MembershipStore(record_store, plans=[{**plans[0], **changes}])


@pytest.mark.parametrize("phone", ["", "12345678901", "1380000000", "138000000001", "+8613800000001", "１３８０００００００１", 13800000001])
def test_phone_validation_rejects_non_mainland_or_non_ascii_values(store, sent, phone):
    with pytest.raises(MembershipError) as error:
        store.request_code(phone, SOURCE)
    assert error.value.code == "invalid_phone" and sent == []


@pytest.mark.parametrize("changes", [
    {"password": "Short12"}, {"password": "a1" * 37}, {"password": "12345678"},
    {"password": "abcdefgh"}, {"password": "Example!123"}, {"password": "中文密码12345"},
    {"code": "12345"}, {"code": "１２３４５６"}, {"code": 123456},
    {"accepted": False}, {"accepted": "true"}, {"accepted": 1},
    {"agreement_version": "old"}, {"role": "company_admin"},
])
def test_invalid_registration_does_not_consume_code(store, record_store, sent, changes):
    store.request_code(PHONE, SOURCE)
    with pytest.raises(MembershipError) as error:
        store.register(payload(sent[-1][1], **changes), SOURCE)
    assert error.value.status == 400
    assert last_otp(record_store)["attempts"] == 0 and last_otp(record_store)["status"] == "sent"
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_memberships") == 0


@pytest.mark.parametrize("password", ["a1234567", "a" * 71 + "1"])
def test_password_length_boundaries_are_accepted(store, sent, password):
    store.request_code(PHONE, SOURCE)
    assert store.register(payload(sent[-1][1], password=password), SOURCE)["role"] == "registered_member"


def test_wrong_attempts_survive_reopen_and_fifth_failure_blocks_correct_code(store, record_store, clock, sent):
    store.request_code(PHONE, SOURCE)
    code = sent[-1][1]
    wrong = "999999" if code != "999999" else "000000"
    for number in range(1, 6):
        with pytest.raises(MembershipError) as error:
            store.register(payload(wrong), SOURCE)
        assert error.value.code == ("code_attempts_exceeded" if number == 5 else "invalid_code")
        assert last_otp(record_store)["attempts"] == number
        store = Demo2MembershipStore(record_store, now=clock)
    with pytest.raises(MembershipError) as error:
        store.register(payload(code), "different-source")
    assert error.value.code == "code_attempts_exceeded"
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_memberships") == 0


def test_fifth_attempt_can_succeed_after_four_wrong_codes(store, sent):
    store.request_code(PHONE, SOURCE)
    code = sent[-1][1]
    wrong = "999999" if code != "999999" else "000000"
    for _ in range(4):
        with pytest.raises(MembershipError):
            store.register(payload(wrong), SOURCE)
    assert store.register(payload(code), SOURCE)["role"] == "registered_member"


@pytest.mark.parametrize("elapsed,valid", [(299, True), (300, False)])
def test_otp_expiry_exact_boundary(store, clock, sent, elapsed, valid):
    store.request_code(PHONE, SOURCE)
    clock.advance(elapsed)
    if valid:
        assert store.register(payload(sent[-1][1]), SOURCE)["role"] == "registered_member"
    else:
        with pytest.raises(MembershipError) as error:
            store.register(payload(sent[-1][1]), SOURCE)
        assert error.value.code == "code_expired"


def test_clock_is_checked_after_obtaining_database_transaction(store, record_store, clock, sent, monkeypatch):
    store.request_code(PHONE, SOURCE)
    clock.advance(299)
    original = record_store._connect

    @contextmanager
    def delayed_connection():
        with original() as connection:
            clock.advance(2)
            yield connection

    monkeypatch.setattr(record_store, "_connect", delayed_connection)
    with pytest.raises(MembershipError) as error:
        store.register(payload(sent[-1][1]), SOURCE)
    assert error.value.code == "code_expired"


def test_cooldown_and_resend_invalidate_previous_code(store, record_store, clock, sent, monkeypatch):
    values = iter((1111, 2222))
    monkeypatch.setattr(membership_module.secrets, "randbelow", lambda _: next(values))
    store.request_code(PHONE, SOURCE)
    first_code = sent[-1][1]
    clock.advance(59)
    with pytest.raises(MembershipError) as error:
        store.request_code(PHONE, "another-source")
    assert error.value.code == "code_cooldown" and len(sent) == 1
    clock.advance(1)
    store.request_code(PHONE, "another-source")
    assert len(sent) == 2
    with pytest.raises(MembershipError) as error:
        store.register(payload(first_code), SOURCE)
    assert error.value.code == "invalid_code"
    assert store.register(payload(sent[-1][1]), SOURCE)["role"] == "registered_member"
    with record_store._connect() as connection:
        assert [row[0] for row in connection.execute("SELECT status FROM demo2_membership_otps ORDER BY rowid")] == ["superseded", "consumed"]


def test_phone_send_budget_cannot_be_bypassed_by_rotating_sources(store, clock, sent):
    for index in range(membership_module.PHONE_SEND_LIMIT):
        store.request_code(PHONE, f"source-{index}")
        clock.advance(60)
    with pytest.raises(MembershipError) as error:
        store.request_code(PHONE, "yet-another-source")
    assert error.value.code == "rate_limited" and len(sent) == membership_module.PHONE_SEND_LIMIT
    clock.advance(3600)
    store.request_code(PHONE, SOURCE)


def test_source_send_budget_survives_reopen_and_phone_rotation(record_store, clock, sent):
    for index in range(membership_module.SOURCE_SEND_LIMIT):
        store = Demo2MembershipStore(record_store, sms_sender=lambda phone, code: sent.append((phone, code)), now=clock)
        store.request_code(f"138{index:08d}", SOURCE)
    with pytest.raises(MembershipError) as error:
        store.request_code("13999999999", SOURCE)
    assert error.value.code == "rate_limited"
    assert len(sent) == membership_module.SOURCE_SEND_LIMIT


def test_register_source_budget_applies_even_without_an_issued_otp(store):
    for _ in range(membership_module.SOURCE_REGISTER_LIMIT):
        with pytest.raises(MembershipError) as error:
            store.register(payload("123456"), SOURCE)
        assert error.value.code == "code_unavailable"
    with pytest.raises(MembershipError) as error:
        store.register(payload("123456", phone="13900000002"), SOURCE)
    assert error.value.code == "rate_limited"


@pytest.mark.parametrize("returns_false", [False, True])
def test_failed_sender_never_leaks_or_activates_code(record_store, clock, sent, caplog, returns_false):
    def failed_sender(phone, code):
        sent.append((phone, code))
        if returns_false:
            return False
        raise RuntimeError(f"provider secret for {phone}: {code} at D:/private/provider.key")

    store = Demo2MembershipStore(record_store, sms_sender=failed_sender, now=clock)
    with pytest.raises(MembershipError) as error:
        store.request_code(PHONE, SOURCE)
    assert (error.value.status, error.value.code) == (503, "sms_send_failed")
    assert last_otp(record_store)["status"] == "failed"
    with pytest.raises(MembershipError) as denied:
        store.register(payload(sent[-1][1]), SOURCE)
    assert denied.value.code == "code_unavailable"
    with pytest.raises(MembershipError) as cooldown:
        store.request_code(PHONE, "other-source")
    assert cooldown.value.code == "code_cooldown"
    with record_store._connect() as connection:
        audit = json.dumps([dict(row) for row in connection.execute("SELECT * FROM audit_logs")])
    exposed = str(error.value) + audit + caplog.text
    assert PHONE not in exposed and sent[-1][1] not in exposed and "provider.key" not in exposed


def test_pending_code_cannot_register_before_sender_returns(record_store, clock):
    outcomes = []
    store = None

    def sender(phone, code):
        try:
            store.register(payload(code, phone), SOURCE)
        except MembershipError as error:
            outcomes.append(error.code)

    store = Demo2MembershipStore(record_store, sms_sender=sender, now=clock)
    assert store.request_code(PHONE, SOURCE)["expires_in"] == 300
    assert outcomes == ["code_unavailable"] and last_otp(record_store)["status"] == "sent"


def test_late_sender_cannot_replace_a_newer_challenge(record_store, clock, sent):
    store = None

    def sender(phone, code):
        sent.append((phone, code))
        if len(sent) == 1:
            clock.advance(60)
            store.request_code(phone, SOURCE)

    store = Demo2MembershipStore(record_store, sms_sender=sender, now=clock)
    with pytest.raises(MembershipError) as error:
        store.request_code(PHONE, SOURCE)
    assert error.value.code == "sms_send_failed" and len(sent) == 2
    assert last_otp(record_store)["status"] == "sent"
    assert store.register(payload(sent[-1][1]), SOURCE)["role"] == "registered_member"


def test_simultaneous_requests_send_only_once(record_store, clock, sent):
    stores = [Demo2MembershipStore(record_store, sms_sender=lambda phone, code: sent.append((phone, code)), now=clock)
              for _ in range(2)]
    barrier = Barrier(2)

    def request(store):
        barrier.wait(timeout=5)
        try:
            return store.request_code(PHONE, SOURCE)
        except MembershipError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(request, stores))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert outcomes.count("code_cooldown") == 1 and len(sent) == 1


def test_concurrent_register_consumes_otp_and_creates_member_exactly_once(store, record_store, clock, sent):
    store.request_code(PHONE, SOURCE)
    other = Demo2MembershipStore(record_store, now=clock)
    barrier = Barrier(2)

    def register(current):
        barrier.wait(timeout=5)
        try:
            return current.register(payload(sent[-1][1]), SOURCE)
        except MembershipError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(register, (store, other)))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert outcomes.count("code_unavailable") == 1
    assert scalar(record_store, "SELECT COUNT(*) FROM platform_accounts") == 6
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_memberships") == 1
    assert last_otp(record_store)["status"] == "consumed"


def test_registration_rolls_back_account_and_consumption_if_member_insert_fails(store, record_store, sent):
    store.request_code(PHONE, SOURCE)
    with record_store._connect() as connection:
        connection.execute("""CREATE TRIGGER fixture_member_failure BEFORE INSERT ON demo2_memberships
                            BEGIN SELECT RAISE(ABORT, 'fixture insert failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="fixture insert failure"):
        store.register(payload(sent[-1][1]), SOURCE)
    assert scalar(record_store, "SELECT COUNT(*) FROM platform_accounts") == 5
    assert last_otp(record_store)["status"] == "sent" and last_otp(record_store)["attempts"] == 0
    with record_store._connect() as connection:
        connection.execute("DROP TRIGGER fixture_member_failure")
    assert store.register(payload(sent[-1][1]), SOURCE)["role"] == "registered_member"


def test_replay_or_duplicate_registration_never_changes_existing_password(store, record_store, clock, sent):
    account = register_member(store, sent)
    with pytest.raises(MembershipError) as replay:
        store.register(payload(sent[-1][1]), SOURCE)
    assert replay.value.code == "code_unavailable"
    clock.advance(60)
    store.request_code(PHONE, SOURCE)
    with pytest.raises(MembershipError) as duplicate:
        store.register(payload(sent[-1][1], password="Changed123"), SOURCE)
    assert duplicate.value.code == "phone_registered"
    assert record_store.authenticate_account(PHONE, PASSWORD)["account_id"] == account["account_id"]
    assert scalar(record_store, "SELECT COUNT(*) FROM demo2_memberships") == 1


def test_member_orders_are_account_scoped_and_hide_provider_metadata(store, record_store, sent):
    first = register_member(store, sent)
    second = register_member(store, sent, "13900000002")
    with record_store._connect() as connection:
        for index, account in enumerate((first, second)):
            connection.execute("""
                INSERT INTO demo2_membership_orders
                (order_id, account_id, plan_id, plan_name, price_cents, duration_days, created_at, provider_reference)
                VALUES (?, ?, 'monthly', '测试方案', 100, 30, '2026-09-09T00:00:00+00:00', ?)
            """, (f"fixture-order-{index}", account["account_id"], f"private-provider-{index}"))
    assert [order["order_id"] for order in store.membership(first["account_id"])["orders"]] == ["fixture-order-0"]
    summary = store.admin_summary()
    assert len(summary["orders"]) == 2
    assert "private-provider" not in json.dumps(summary)
    assert PHONE not in json.dumps(summary) and second["username"] not in json.dumps(summary)
