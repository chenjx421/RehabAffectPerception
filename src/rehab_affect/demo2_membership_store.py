"""Local membership persistence; SMS is injected and payment is deliberately disabled.

The HTTP layer must authenticate account_id/admin calls and supply a trusted
source_key. This module never sends SMS without an explicitly supplied sender,
creates a payment, or grants access to school/student data.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .student_record_store import (
    PASSWORD_HASH_ITERATIONS,
    PASSWORD_SALT_BYTES,
    _password_hash,
)


AGREEMENT_VERSION = "2026-09-09"
OTP_TTL_SECONDS = 300
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
RATE_WINDOW_SECONDS = 3600
PHONE_SEND_LIMIT = 5
SOURCE_SEND_LIMIT = 10
SOURCE_REGISTER_LIMIT = 30
DEFAULT_PLANS = (
    {"plan_id": "monthly", "name": "月度会员", "description": "拟定服务，权益与价格待配置，暂不可购买",
     "price_cents": None, "currency": "CNY", "duration_days": 30},
    {"plan_id": "yearly", "name": "年度会员", "description": "拟定服务，权益与价格待配置，暂不可购买",
     "price_cents": None, "currency": "CNY", "duration_days": 365},
)


class MembershipError(ValueError):
    """Stable, public-safe error consumed by the HTTP adapter."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _masked(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _phone(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"1[3-9][0-9]{9}", value.strip()):
        raise MembershipError(400, "invalid_phone", "请填写有效的大陆11位手机号码")
    return value.strip()


def _source(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 256:
        raise MembershipError(400, "invalid_source", "请求来源无效，请稍后重试")
    return _digest(value.strip())


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


class Demo2MembershipStore:
    def __init__(self, record_store, *, sms_sender=None, plans=None, now=None):
        if sms_sender is not None and not callable(sms_sender):
            raise ValueError("sms_sender must be callable or None")
        self.record_store = record_store
        self._sms_sender = sms_sender
        self._clock = now
        self._plans = self._normalize_plans(DEFAULT_PLANS if plans is None else plans)
        self._initialize()

    @staticmethod
    def _normalize_plans(plans) -> tuple[dict[str, Any], ...]:
        if not isinstance(plans, (list, tuple)):
            raise ValueError("plans must be a list of server-defined plans")
        normalized, seen = [], set()
        for plan in plans:
            if not isinstance(plan, dict):
                raise ValueError("invalid membership plan")
            plan_id = plan.get("plan_id")
            name, description = plan.get("name"), plan.get("description", "")
            price, days = plan.get("price_cents"), plan.get("duration_days")
            if (not isinstance(plan_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", plan_id)
                    or plan_id in seen or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
                    or not isinstance(description, str) or len(description) > 1000
                    or (price is not None and (type(price) is not int or not 1 <= price <= 100_000_000))
                    or type(days) is not int or not 1 <= days <= 3650 or plan.get("currency", "CNY") != "CNY"):
                raise ValueError("invalid membership plan")
            seen.add(plan_id)
            normalized.append({"plan_id": plan_id, "name": name.strip(), "description": description,
                               "price_cents": price, "currency": "CNY", "duration_days": days,
                               "available": False})
        return tuple(normalized)

    def _now(self) -> float:
        value = self._clock() if callable(self._clock) else self._clock
        if value is None:
            value = datetime.now(timezone.utc)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            value = value.timestamp()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("now must provide a finite timestamp or datetime")
        return float(value)

    def _initialize(self) -> None:
        # Keep the record-store schema version and all existing accounts intact.
        # executescript commits a previous transaction, so begin inside it.
        with self.record_store._connect() as connection:
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS demo2_memberships (
                    account_id TEXT PRIMARY KEY REFERENCES platform_accounts(account_id),
                    phone_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'inactive'
                        CHECK(status IN ('inactive', 'active', 'expired', 'suspended')),
                    expires_at TEXT,
                    agreement_version TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS demo2_membership_otps (
                    challenge_id TEXT PRIMARY KEY,
                    phone_hash TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    code_salt TEXT NOT NULL,
                    code_iterations INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed', 'superseded', 'consumed')),
                    consumed_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_demo2_membership_otps_phone
                    ON demo2_membership_otps(phone_hash, created_at DESC);
                CREATE TABLE IF NOT EXISTS demo2_membership_rate_limits (
                    scope TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    window_started_at REAL NOT NULL,
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    PRIMARY KEY(scope, key_hash)
                );
                CREATE TABLE IF NOT EXISTS demo2_membership_orders (
                    order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES demo2_memberships(account_id),
                    plan_id TEXT NOT NULL,
                    plan_name TEXT NOT NULL,
                    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
                    currency TEXT NOT NULL DEFAULT 'CNY' CHECK(currency = 'CNY'),
                    duration_days INTEGER NOT NULL CHECK(duration_days > 0),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'paid', 'cancelled', 'expired', 'refunded')),
                    provider_reference TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    paid_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_demo2_membership_orders_account
                    ON demo2_membership_orders(account_id, created_at DESC);
            """)

    def _audit(self, connection, action: str, object_id: str, detail: dict[str, Any]) -> None:
        self.record_store._audit(connection, "membership_service", action, "demo2_membership", object_id, detail)

    def _deny(self, connection, status: int, code: str, message: str, *, object_id: str = "") -> None:
        self._audit(connection, "membership_rejected", object_id, {"reason": code})
        # Wrong-code counters and abuse budgets must survive the public error.
        connection.commit()
        raise MembershipError(status, code, message)

    def _budget(self, connection, scope: str, key_hash: str, timestamp: float, limit: int) -> tuple:
        row = connection.execute(
            "SELECT window_started_at, attempts FROM demo2_membership_rate_limits WHERE scope = ? AND key_hash = ?",
            (scope, key_hash),
        ).fetchone()
        started, attempts = (row["window_started_at"], row["attempts"]) if row else (timestamp, 0)
        if timestamp - started >= RATE_WINDOW_SECONDS:
            started, attempts = timestamp, 0
        if attempts >= limit:
            self._deny(connection, 429, "rate_limited", "操作过于频繁，请稍后重试")
        return scope, key_hash, started, attempts + 1

    @staticmethod
    def _consume_budget(connection, budget: tuple) -> None:
        connection.execute("""
            INSERT INTO demo2_membership_rate_limits(scope, key_hash, window_started_at, attempts)
            VALUES (?, ?, ?, ?) ON CONFLICT(scope, key_hash) DO UPDATE SET
                window_started_at = excluded.window_started_at, attempts = excluded.attempts
        """, budget)

    def public_config(self) -> dict[str, Any]:
        return {"sms_available": self._sms_sender is not None, "payment_available": False,
                "plans": [dict(plan) for plan in self._plans], "agreement_version": AGREEMENT_VERSION}

    def request_code(self, phone, source_key) -> dict[str, int]:
        phone, source_hash = _phone(phone), _source(source_key)
        if self._sms_sender is None:
            raise MembershipError(503, "sms_not_configured", "短信服务尚未配置，暂时无法发送验证码")
        phone_hash = _digest(phone)
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            timestamp = self._now()
            previous = connection.execute(
                "SELECT created_at FROM demo2_membership_otps WHERE phone_hash = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (phone_hash,),
            ).fetchone()
            if previous and timestamp - previous["created_at"] < OTP_COOLDOWN_SECONDS:
                self._deny(connection, 429, "code_cooldown", "请间隔60秒后再获取验证码")
            budgets = [self._budget(connection, "sms_phone", phone_hash, timestamp, PHONE_SEND_LIMIT),
                       self._budget(connection, "sms_source", source_hash, timestamp, SOURCE_SEND_LIMIT)]
            for budget in budgets:
                self._consume_budget(connection, budget)
            challenge_id = uuid4().hex
            code = f"{secrets.randbelow(1_000_000):06d}"
            salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
            connection.execute("""
                UPDATE demo2_membership_otps SET status = 'superseded'
                WHERE phone_hash = ? AND status IN ('pending', 'sent')
            """, (phone_hash,))
            connection.execute("""
                INSERT INTO demo2_membership_otps
                (challenge_id, phone_hash, source_hash, code_hash, code_salt, code_iterations,
                 created_at, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (challenge_id, phone_hash, source_hash, _password_hash(code, salt), salt.hex(),
                  PASSWORD_HASH_ITERATIONS, timestamp, timestamp + OTP_TTL_SECONDS))
            self._audit(connection, "membership_code_requested", challenge_id, {"phone_masked": _masked(phone)})

        # No open database transaction while an injected provider is running.
        # Never include provider exceptions or the code in responses/audit logs.
        delivery_failed = False
        try:
            delivery_failed = self._sms_sender(phone, code) is False
        except Exception:
            delivery_failed = True
        finally:
            code = ""
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            delivered_at = self._now()
            if delivery_failed or delivered_at >= timestamp + OTP_TTL_SECONDS:
                connection.execute("UPDATE demo2_membership_otps SET status = 'failed' WHERE challenge_id = ? AND status = 'pending'",
                                   (challenge_id,))
                self._deny(connection, 503, "sms_send_failed", "短信发送未完成，请稍后重试", object_id=challenge_id)
            changed = connection.execute("""
                UPDATE demo2_membership_otps SET status = 'sent', expires_at = ?
                WHERE challenge_id = ? AND status = 'pending'
            """, (delivered_at + OTP_TTL_SECONDS, challenge_id)).rowcount
            if changed != 1:
                self._deny(connection, 503, "sms_send_failed", "短信发送未完成，请稍后重试", object_id=challenge_id)
            self._audit(connection, "membership_code_sent", challenge_id, {"phone_masked": _masked(phone)})
        return {"retry_after": OTP_COOLDOWN_SECONDS, "expires_in": OTP_TTL_SECONDS}

    def register(self, payload, source_key) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"phone", "code", "password", "agreement_version", "accepted"}:
            raise MembershipError(400, "invalid_registration", "注册信息格式无效")
        phone, source_hash = _phone(payload["phone"]), _source(source_key)
        code, password = payload["code"], payload["password"]
        if payload["accepted"] is not True or payload["agreement_version"] != AGREEMENT_VERSION:
            raise MembershipError(400, "agreement_required", "请阅读并同意当前版本的会员协议")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise MembershipError(400, "invalid_code", "请输入6位数字验证码")
        if (not isinstance(password, str) or not re.fullmatch(r"[A-Za-z0-9]{8,72}", password)
                or not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password)):
            raise MembershipError(400, "invalid_password", "密码须为8至72位字母和数字组合")
        phone_hash = _digest(phone)
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            timestamp = self._now()
            self._consume_budget(connection, self._budget(
                connection, "register_source", source_hash, timestamp, SOURCE_REGISTER_LIMIT))
            otp = connection.execute("""
                SELECT * FROM demo2_membership_otps WHERE phone_hash = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
            """, (phone_hash,)).fetchone()
            if otp is None or otp["status"] != "sent" or otp["consumed_at"] is not None:
                self._deny(connection, 400, "code_unavailable", "验证码无效或已使用，请重新获取")
            if timestamp >= otp["expires_at"]:
                self._deny(connection, 400, "code_expired", "验证码已过期，请重新获取", object_id=otp["challenge_id"])
            if otp["attempts"] >= OTP_MAX_ATTEMPTS:
                self._deny(connection, 429, "code_attempts_exceeded", "验证码尝试次数已用尽，请重新获取", object_id=otp["challenge_id"])
            attempts = otp["attempts"] + 1
            connection.execute("UPDATE demo2_membership_otps SET attempts = ? WHERE challenge_id = ?", (attempts, otp["challenge_id"]))
            candidate = _password_hash(code, bytes.fromhex(otp["code_salt"]), otp["code_iterations"])
            if not hmac.compare_digest(otp["code_hash"], candidate):
                if attempts >= OTP_MAX_ATTEMPTS:
                    self._deny(connection, 429, "code_attempts_exceeded", "验证码尝试次数已用尽，请重新获取", object_id=otp["challenge_id"])
                self._deny(connection, 400, "invalid_code", "验证码不正确", object_id=otp["challenge_id"])
            if connection.execute("SELECT 1 FROM platform_accounts WHERE username = ?", (phone,)).fetchone():
                self._deny(connection, 409, "phone_registered", "该手机号已注册，请直接登录", object_id=otp["challenge_id"])
            account_id, created_at = uuid4().hex, _iso(timestamp)
            salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
            connection.execute("""
                INSERT INTO platform_accounts
                (account_id, username, password_hash, password_salt, password_iterations, role,
                 bound_channel_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'registered_member', NULL, 'active', ?, ?)
            """, (account_id, phone, _password_hash(password, salt), salt.hex(), PASSWORD_HASH_ITERATIONS, created_at, created_at))
            connection.execute("""
                INSERT INTO demo2_memberships
                (account_id, phone_hash, status, agreement_version, accepted_at, created_at, updated_at)
                VALUES (?, ?, 'inactive', ?, ?, ?, ?)
            """, (account_id, phone_hash, AGREEMENT_VERSION, created_at, created_at, created_at))
            connection.execute("UPDATE demo2_membership_otps SET status = 'consumed', consumed_at = ? WHERE challenge_id = ?",
                               (timestamp, otp["challenge_id"]))
            self._audit(connection, "membership_registered", account_id,
                        {"phone_masked": _masked(phone), "agreement_version": AGREEMENT_VERSION, "school_access": False})
            account = dict(connection.execute("SELECT * FROM platform_accounts WHERE account_id = ?", (account_id,)).fetchone())
        return {**self.record_store._public_account(account), "phone_masked": _masked(phone)}

    @staticmethod
    def _member_row(connection, account_id):
        if not isinstance(account_id, str) or not account_id:
            raise MembershipError(404, "member_not_found", "未找到会员账号")
        row = connection.execute("""
            SELECT m.*, a.username, a.status AS account_status FROM demo2_memberships AS m
            JOIN platform_accounts AS a ON a.account_id = m.account_id
            WHERE m.account_id = ? AND a.role = 'registered_member'
        """, (account_id,)).fetchone()
        if row is None:
            raise MembershipError(404, "member_not_found", "未找到会员账号")
        return row

    @staticmethod
    def _public_member(row) -> dict[str, Any]:
        return {"account_id": row["account_id"], "phone_masked": _masked(row["username"]),
                "status": row["status"], "status_label": {"inactive": "未开通", "active": "已开通",
                    "expired": "已到期", "suspended": "已暂停"}[row["status"]],
                "expires_at": row["expires_at"], "school_access": False,
                "account_status": row["account_status"], "created_at": row["created_at"]}

    @staticmethod
    def _orders(connection, account_id=None) -> list[dict[str, Any]]:
        # Provider identifiers and any future payment secrets are never public.
        sql = """SELECT order_id, account_id, plan_id, plan_name, price_cents, currency,
                        duration_days, status, created_at, expires_at, paid_at
                 FROM demo2_membership_orders"""
        params = ()
        if account_id is not None:
            sql += " WHERE account_id = ?"
            params = (account_id,)
        return [dict(row) for row in connection.execute(sql + " ORDER BY created_at DESC, rowid DESC LIMIT 100", params)]

    def membership(self, account_id) -> dict[str, Any]:
        with self.record_store._connect() as connection:
            if not isinstance(account_id, str) or not account_id:
                raise MembershipError(404, "member_not_found", "未找到会员账号")
            account = connection.execute(
                "SELECT role, status FROM platform_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if account is not None and account["status"] == "active" and account["role"] in {"school_uploader", "company_admin"}:
                # Existing pilot roles remain separate from paid membership.
                # Admin retains its admin routes, not the school upload role.
                member = {"account_id": account_id, "phone_masked": "未绑定手机号", "status": "internal_trial",
                          "status_label": "内测账号", "expires_at": None,
                          "school_access": account["role"] == "school_uploader"}
                orders = []
            else:
                member = self._public_member(self._member_row(connection, account_id))
                orders = self._orders(connection, account_id)
        config = self.public_config()
        return {**member, "plans": config["plans"], "orders": orders,
                "sms_available": config["sms_available"], "payment_available": False}

    def create_order(self, account_id, payload) -> dict[str, Any]:
        # No provider/settlement integration exists. Do not persist fake orders
        # or trust any client price, paid flag, or plan availability.
        with self.record_store._connect() as connection:
            self._member_row(connection, account_id)
            self._deny(connection, 503, "payment_not_configured", "支付服务尚未配置，暂时无法创建订单", object_id=account_id)

    def admin_summary(self) -> dict[str, Any]:
        """Trusted server-only call: the HTTP adapter must enforce admin role."""
        with self.record_store._connect() as connection:
            members = [self._public_member(row) for row in connection.execute("""
                SELECT m.*, a.username, a.status AS account_status FROM demo2_memberships AS m
                JOIN platform_accounts AS a ON a.account_id = m.account_id
                WHERE a.role = 'registered_member' ORDER BY m.created_at DESC, m.rowid DESC
            """)]
            orders = self._orders(connection)
            self._audit(connection, "membership_admin_summary", "all_members", {"member_count": len(members)})
        return {"members": members, "orders": orders, "sms_available": self._sms_sender is not None,
                "payment_available": False}
