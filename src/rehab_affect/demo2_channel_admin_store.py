"""Company-admin configuration of existing upload channels and course quotas."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from .student_record_store import MAX_COURSE_UPLOAD_LIMIT, MIN_COURSE_UPLOAD_LIMIT, _iso, _now, _token_hash


UPDATE_FIELDS = {"channel_id", "expected_version", "channel_name", "owner_label", "status", "course_upload_limit"}
CHANNEL_FIELDS = ("channel_id", "channel_no", "channel_name", "owner_label", "status", "created_at", "updated_at",
                  "account_id", "username", "account_status", "course_upload_limit")
CHANNEL_QUERY = """
    SELECT c.*, a.account_id, a.username, a.role AS account_role, a.status AS account_status,
           a.course_upload_limit, a.updated_at AS account_updated_at
    FROM video_upload_channels AS c
    LEFT JOIN platform_accounts AS a ON a.bound_channel_id = c.channel_id
"""


class ChannelAdminError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _text(value: Any, limit: int, *, required: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > limit
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)):
        raise ChannelAdminError(400, "invalid_channel_update", "通道文字过长、格式无效或包含控制字符")
    value = value.strip()
    if required and not value:
        raise ChannelAdminError(400, "invalid_channel_update", "通道名称不能为空")
    return value


class Demo2ChannelAdminStore:
    def __init__(self, records):
        self.records = records

    def _admin(self, token):
        try:
            account = self.records.account_from_session(token)
        except (TypeError, ValueError):
            raise ChannelAdminError(401, "authentication_required", "登录已失效，请重新登录") from None
        if account["role"] != "company_admin":
            raise ChannelAdminError(403, "channel_admin_forbidden", "仅公司管理员可以管理上传通道")
        return account

    @staticmethod
    def _recheck_admin(connection, account, token):
        # Recheck on the transaction's connection: a second account_from_session
        # would open a writer connection and contend with our BEGIN IMMEDIATE.
        row = connection.execute("""
            SELECT a.account_id, a.username, a.role, a.status, s.expires_at, s.revoked_at
            FROM account_sessions AS s JOIN platform_accounts AS a ON a.account_id = s.account_id
            WHERE s.session_id = ? AND s.account_id = ? AND s.token_hash = ?
        """, (account["session_id"], account["account_id"], _token_hash(str(token or "")))).fetchone()
        if row is None or row["status"] != "active" or row["revoked_at"]:
            raise ChannelAdminError(401, "authentication_required", "登录已失效，请重新登录")
        try:
            expired = datetime.fromisoformat(row["expires_at"]) <= _now()
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise ChannelAdminError(401, "authentication_required", "登录已失效，请重新登录")
        if row["role"] != "company_admin":
            raise ChannelAdminError(403, "channel_admin_forbidden", "仅公司管理员可以管理上传通道")
        return dict(row)

    @staticmethod
    def _channel(connection, channel_id):
        row = connection.execute(CHANNEL_QUERY + " WHERE c.channel_id = ?", (channel_id,)).fetchone()
        if row is None:
            raise ChannelAdminError(404, "channel_unavailable", "上传通道不存在")
        return dict(row)

    @staticmethod
    def _version(row):
        # Task counts and school context are live information, not channel
        # configuration. Include both channel state and the bound account quota.
        state = {key: row[key] for key in (*CHANNEL_FIELDS, "account_role", "account_updated_at")}
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _public_channel(self, connection, row):
        result = {key: row[key] for key in CHANNEL_FIELDS}
        result["version"] = self._version(row)
        result["school_context"] = self.records._school_context_for_account(connection, row["account_id"])
        counts = connection.execute("""
            SELECT COUNT(*) AS task_count,
                   COALESCE(SUM(CASE WHEN upload_status NOT IN ('cancelled', 'expired') THEN 1 ELSE 0 END), 0)
                       AS active_task_count
            FROM video_analysis_tasks WHERE channel_id = ?
        """, (row["channel_id"],)).fetchone()
        result.update(dict(counts))
        # Match create_video_task exactly: reservations and failures still use
        # slots; only cancelled/expired uploads are excluded, per account/course.
        result["course_usage"] = [dict(usage) for usage in connection.execute("""
            SELECT course_id, COUNT(*) AS used_slots FROM video_analysis_tasks
            WHERE account_id = ? AND upload_status NOT IN ('cancelled', 'expired')
            GROUP BY course_id ORDER BY course_id
        """, (row["account_id"],))]
        result["max_course_used_slots"] = max((usage["used_slots"] for usage in result["course_usage"]), default=0)
        return result

    def list_channels(self, token) -> dict[str, Any]:
        account = self._admin(token)
        with self.records._connect() as connection:
            connection.execute("BEGIN")
            self._recheck_admin(connection, account, token)
            rows = connection.execute(CHANNEL_QUERY + " ORDER BY c.channel_no").fetchall()
            return {"channels": [self._public_channel(connection, dict(row)) for row in rows]}

    def update_channel(self, token, payload) -> dict[str, Any]:
        account = self._admin(token)
        if not isinstance(payload, dict) or set(payload) != UPDATE_FIELDS:
            raise ChannelAdminError(400, "invalid_channel_update", "请仅提交通道编号、当前版本、名称、负责人、状态和课程名额")
        channel_id, expected_version = payload["channel_id"], payload["expected_version"]
        if (not isinstance(channel_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", channel_id)
                or not isinstance(expected_version, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_version)):
            raise ChannelAdminError(400, "invalid_channel_update", "通道编号或版本格式无效，请刷新后重试")
        name = _text(payload["channel_name"], 120, required=True)
        owner = _text(payload["owner_label"], 120)
        status, limit = payload["status"], payload["course_upload_limit"]
        if not isinstance(status, str) or status not in {"active", "paused"}:
            raise ChannelAdminError(400, "invalid_channel_update", "通道状态仅支持 active 或 paused")
        if type(limit) is not int or not MIN_COURSE_UPLOAD_LIMIT <= limit <= MAX_COURSE_UPLOAD_LIMIT:
            raise ChannelAdminError(400, "invalid_course_upload_limit", "每课程上传名额必须是 3 至 5 的整数")
        with self.records._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            account = self._recheck_admin(connection, account, token)
            row = self._channel(connection, channel_id)
            if not hmac.compare_digest(expected_version, self._version(row)):
                raise ChannelAdminError(409, "channel_version_conflict", "通道配置已变化，请刷新后重新确认")
            if row["account_id"] is None or row["account_role"] != "school_uploader":
                raise ChannelAdminError(409, "channel_account_unavailable", "通道没有有效的既有上传账号，不允许自动分配账号")
            before = self._public_channel(connection, row)
            if limit < row["course_upload_limit"] and limit < before["max_course_used_slots"]:
                raise ChannelAdminError(409, "channel_quota_in_use",
                                        f"已有课程占用 {before['max_course_used_slots']} 个有效上传名额，不能降至 {limit}；历史任务不会删除")
            now = _iso()
            connection.execute("""
                UPDATE video_upload_channels SET channel_name = ?, owner_label = ?, status = ?, updated_at = ?
                WHERE channel_id = ?
            """, (name, owner, status, now, channel_id))
            if limit != row["course_upload_limit"]:
                connection.execute("UPDATE platform_accounts SET course_upload_limit = ?, updated_at = ? WHERE account_id = ?",
                                   (limit, now, row["account_id"]))
            after = self._public_channel(connection, self._channel(connection, channel_id))
            self.records._audit(connection, account["username"], "channel_admin_updated", "video_upload_channel", channel_id,
                                {"before": before, "after": after})
        return after
