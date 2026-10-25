"""Account-scoped rosters and manual identities for individual sampled frames.

No legacy student/IEP matching, face recognition, tracking, or assignment of
whole-scene motion/audio metrics to a student is performed here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import sqlite3
import unicodedata
from collections import OrderedDict
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from .student_record_store import MAX_PROCESSING_RESULT_BYTES, SCHOOL_CONTEXT_LIMITS, _iso


STUDENT_FIELDS = {"display_name": 80, "student_code": 64, "class_name": 120, "note": 1000}
IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_FRAMES = 20_000
MAX_FRAME_CACHE_MANIFESTS = 8
MAX_FRAME_CACHE_ENTRIES = 40_000
IDENTITY_SCOPE = "single_sample_frame"


class IdentityError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _has_controls(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)


def _field(value: Any, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or _has_controls(value):
        raise IdentityError(400, "invalid_field", "字段过长、格式无效或包含控制字符")
    normalized = value.strip()
    if required and not normalized:
        raise IdentityError(400, "invalid_field", "请填写必填字段")
    return normalized


def _number(value: Any) -> float:
    if type(value) not in {int, float}:
        raise IdentityError(400, "invalid_number", "数值必须为有限数字")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise IdentityError(400, "invalid_number", "数值必须为有限数字") from None
    if not math.isfinite(number):
        raise IdentityError(400, "invalid_number", "数值必须为有限数字")
    return number


def _bbox(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise IdentityError(400, "invalid_bbox", "请提供归一化的矩形坐标")
    try:
        box = {key: _number(value[key]) for key in ("x", "y", "width", "height")}
    except IdentityError:
        raise IdentityError(400, "invalid_bbox", "矩形坐标必须为有限数字") from None
    if (any(number < 0 or number > 1 for number in box.values()) or box["width"] <= 0 or box["height"] <= 0
            or box["width"] * box["height"] <= 0
            or box["width"] > 1 - box["x"] or box["height"] > 1 - box["y"]):
        raise IdentityError(400, "invalid_bbox", "矩形必须完整位于画面内，且面积大于零")
    return box


def _iou(first: dict[str, float], second: dict[str, float]) -> float:
    width = max(0.0, min(first["x"] + first["width"], second["x"] + second["width"]) - max(first["x"], second["x"]))
    height = max(0.0, min(first["y"] + first["height"], second["y"] + second["height"]) - max(first["y"], second["y"]))
    intersection = width * height
    union = first["width"] * first["height"] + second["width"] * second["height"] - intersection
    return intersection / union if union > 0 else 0.0


class Demo2IdentityStore:
    def __init__(self, record_store):
        self.record_store = record_store
        self._frame_cache = OrderedDict()
        self._frame_cache_entries = 0
        self._frame_cache_lock = Lock()
        with record_store._connect() as connection:
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS demo2_identity_students (
                    student_id TEXT PRIMARY KEY,
                    owner_account_id TEXT NOT NULL REFERENCES platform_accounts(account_id),
                    scope_key TEXT NOT NULL,
                    school_context_json TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    student_code TEXT NOT NULL DEFAULT '',
                    class_name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(student_id, owner_account_id, scope_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_demo2_identity_student_code
                    ON demo2_identity_students(owner_account_id, scope_key, class_name, student_code)
                    WHERE student_code <> '';
                CREATE INDEX IF NOT EXISTS idx_demo2_identity_student_scope
                    ON demo2_identity_students(owner_account_id, scope_key);
                CREATE TABLE IF NOT EXISTS demo2_identity_bindings (
                    binding_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES video_analysis_tasks(task_id),
                    owner_account_id TEXT NOT NULL REFERENCES platform_accounts(account_id),
                    scope_key TEXT NOT NULL,
                    student_id TEXT,
                    role TEXT NOT NULL CHECK(role IN ('student', 'teacher', 'unknown')),
                    frame_key TEXT NOT NULL,
                    frame_revision TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    time_sec REAL NOT NULL CHECK(time_sec >= 0),
                    bbox_json TEXT NOT NULL,
                    confirmed_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed' CHECK(status IN ('confirmed', 'revoked')),
                    revoked_by TEXT,
                    revoked_at TEXT,
                    revoked_reason TEXT NOT NULL DEFAULT '',
                    CHECK((role = 'student' AND student_id IS NOT NULL) OR (role <> 'student' AND student_id IS NULL)),
                    FOREIGN KEY(student_id, owner_account_id, scope_key)
                        REFERENCES demo2_identity_students(student_id, owner_account_id, scope_key)
                );
                CREATE INDEX IF NOT EXISTS idx_demo2_identity_bindings_task
                    ON demo2_identity_bindings(task_id, owner_account_id, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_demo2_identity_one_student_per_frame
                    ON demo2_identity_bindings(task_id, frame_revision, frame_key, student_id)
                    WHERE status = 'confirmed' AND role = 'student';
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(demo2_identity_bindings)")}
            if "overlap_confirmed" not in columns:
                connection.execute("ALTER TABLE demo2_identity_bindings ADD COLUMN overlap_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(overlap_confirmed IN (0, 1))")

    def _account(self, token, *, write=False):
        try:
            account = self.record_store.account_from_session(token)
        except ValueError:
            raise IdentityError(401, "authentication_required", "登录已失效，请重新登录") from None
        roles = {"school_uploader"} if write else {"school_uploader", "company_admin"}
        if account.get("role") not in roles:
            raise IdentityError(403, "identity_forbidden", "当前账号没有此身份名册操作权限")
        return account

    @staticmethod
    def _context(raw, *, required=True) -> dict[str, str]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(value, dict):
                raise ValueError
            context = {key: _field(value.get(key, ""), limit, required=True) for key, limit in SCHOOL_CONTEXT_LIMITS.items()}
            return context
        except (ValueError, TypeError):
            if required:
                raise IdentityError(409, "school_context_required", "请先填写完整学校信息；历史任务使用上传时的学校快照") from None
            return {key: "" for key in SCHOOL_CONTEXT_LIMITS}

    @staticmethod
    def _scope(owner: str, context: dict[str, str]) -> str:
        if not owner or not all(context.values()):
            return ""
        encoded = json.dumps({"owner_account_id": owner, "school_context": context}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _empty_school_snapshot(raw) -> bool:
        # Do not use _context(required=False): it intentionally hides invalid
        # or partial snapshots for display, which must never authorize a write.
        def unique_fields(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError("Duplicate school context fields")
            return value

        try:
            value = json.loads(raw, object_pairs_hook=unique_fields) if isinstance(raw, str) else raw
        except (ValueError, TypeError, RecursionError):
            return False
        if not isinstance(value, dict) or set(value) - set(SCHOOL_CONTEXT_LIMITS):
            return False
        # A legacy {} is empty; malformed/null/nonempty values are not. Even
        # whitespace must not erase an existing snapshot during confirmation.
        return all(isinstance(value.get(key, ""), str) and value.get(key, "") == ""
                   for key in SCHOOL_CONTEXT_LIMITS)

    @staticmethod
    def _task_has_bindings(connection, task_id) -> bool:
        return connection.execute(
            "SELECT 1 FROM demo2_identity_bindings WHERE task_id = ? LIMIT 1", (task_id,)
        ).fetchone() is not None

    @staticmethod
    def _task(connection, account, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise IdentityError(404, "task_unavailable", "任务不存在或当前账号无权访问")
        row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None or (account["role"] != "company_admin" and row["account_id"] != account["account_id"]):
            raise IdentityError(404, "task_unavailable", "任务不存在或当前账号无权访问")
        return dict(row)

    @staticmethod
    def _public_student(row):
        return {key: row[key] for key in ("student_id", "owner_account_id", "scope_key", "display_name", "student_code", "class_name", "note", "created_at")}

    def _students(self, connection, owner, scope):
        return [self._public_student(row) for row in connection.execute("""
            SELECT * FROM demo2_identity_students WHERE owner_account_id = ? AND scope_key = ?
            ORDER BY class_name, display_name, student_code, created_at, student_id
        """, (owner, scope))]

    def _audit(self, connection, account, action, object_id, detail):
        self.record_store._audit(connection, account["username"], action, "demo2_identity", object_id, detail)

    def roster(self, token) -> dict[str, Any]:
        account = self._account(token, write=True)
        with self.record_store._connect() as connection:
            context = self._context(
                self.record_store._school_context_for_account(connection, account["account_id"]), required=False
            )
            scope = self._scope(account["account_id"], context)
            students = self._students(connection, account["account_id"], scope) if scope else []
            self._audit(connection, account, "identity_roster_viewed", scope, {"student_count": len(students)})
        return {"school_context": context, "scope_key": scope, "students": students,
                "can_edit": bool(scope), "needs_school_context": not bool(scope)}

    def create_student(self, token, payload) -> dict[str, Any]:
        account = self._account(token, write=True)
        if not isinstance(payload, dict) or "display_name" not in payload or set(payload) - set(STUDENT_FIELDS):
            raise IdentityError(400, "invalid_student", "请仅提交学生姓名、校内编号、班级和备注")
        fields = {key: _field(payload.get(key, ""), limit, required=key == "display_name") for key, limit in STUDENT_FIELDS.items()}
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._context(self.record_store._school_context_for_account(connection, account["account_id"]))
            scope = self._scope(account["account_id"], context)
            row = {"student_id": str(uuid4()), "owner_account_id": account["account_id"], "scope_key": scope,
                   "school_context_json": json.dumps(context, ensure_ascii=False, sort_keys=True), "created_at": _iso(), **fields}
            try:
                connection.execute("""
                    INSERT INTO demo2_identity_students
                    (student_id, owner_account_id, scope_key, school_context_json, display_name, student_code, class_name, note, created_at)
                    VALUES (:student_id, :owner_account_id, :scope_key, :school_context_json, :display_name, :student_code, :class_name, :note, :created_at)
                """, row)
            except sqlite3.IntegrityError:
                raise IdentityError(409, "student_code_conflict", "当前名册的同一班级已存在此学生编号") from None
            self._audit(connection, account, "identity_student_created", row["student_id"], {"scope_key": scope})
        return self._public_student(row)

    @staticmethod
    def _revision(task):
        raw = task.get("processing_result_json")
        try:
            return hashlib.sha256(raw.encode("utf-8")).hexdigest() if isinstance(raw, str) else ""
        except UnicodeError:
            return ""

    @staticmethod
    def _sample_image(result, sample, segment_index, sample_index, time):
        if "image_path" in sample:
            return sample["image_path"]
        # The legacy publication filter removes *_path keys. Only this exact
        # engine contract supports recovery from its persisted frame directory
        # and integer sampling grid (demo2_media_analysis.py). Never scan disk,
        # take a client path, or fall back from an explicitly invalid path.
        sampling, artifacts = result.get("sampling"), result.get("artifacts")
        directory = artifacts.get("frames") if isinstance(artifacts, dict) else None
        if (result.get("analysis_version") != "demo2_media_evidence_v1.1"
                or not isinstance(sampling, dict) or type(sampling.get("fps")) not in {int, float}
                or sampling["fps"] != 1 or type(sampling.get("window_sec")) not in {int, float}
                or sampling["window_sec"] != 20
                or type(sample.get("timestamp_sec")) is not int
                or time != segment_index * 20 + sample_index or not 0 <= sample_index < 20
                or not isinstance(directory, str)
                or not re.fullmatch(r"media_[A-Za-z0-9_-]{1,80}/frames", directory)):
            raise IdentityError(409, "invalid_frame_manifest", "可信采样帧清单缺失或版本不受支持")
        return f"{directory}/frame_{int(time):06d}.jpg"

    @staticmethod
    def _image_parts(relative):
        if (not isinstance(relative, str) or not relative or len(relative) > 1024 or _has_controls(relative)
                or PureWindowsPath(relative).drive or ":" in relative):
            raise IdentityError(409, "invalid_frame_manifest", "采样帧路径未通过安全检查")
        parts = PurePosixPath(relative.replace("\\", "/"))
        if parts.is_absolute() or ".." in parts.parts or parts.suffix.lower() not in IMAGE_MIMES:
            raise IdentityError(409, "invalid_frame_manifest", "采样帧路径未通过安全检查")
        return parts

    def _image_path(self, task, relative, *, must_exist=False):
        parts = self._image_parts(relative)
        try:
            root = self.record_store._video_analysis_dir(task["task_id"])
            path = self.record_store._controlled_video_path(root.joinpath(*parts.parts), "analysis")
            if root not in path.parents:
                raise ValueError
            if must_exist and not path.is_file():
                raise IdentityError(404, "frame_unavailable", "采样帧文件不存在或不可读取")
        except (OSError, ValueError, RuntimeError) as exc:
            if isinstance(exc, IdentityError):
                raise
            raise IdentityError(409, "invalid_frame_manifest", "采样帧路径未通过安全检查") from None
        return path

    def _frames(self, task):
        raw = task.get("processing_result_json")
        task_id, base = task.get("task_id"), task.get("sha256")
        try:
            if not isinstance(raw, str) or not isinstance(task_id, str):
                raise ValueError
            encoded = raw.encode("utf-8")
            if len(encoded) > MAX_PROCESSING_RESULT_BYTES:
                raise ValueError
        except (ValueError, UnicodeError):
            raise IdentityError(409, "invalid_frame_manifest", "可信采样帧清单缺失或格式无效") from None
        manifest = {"task_id": task_id, "sha256": base, "processing_result_json": raw}
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", base):
            return self._parse_frames(manifest)
        # Cache only lexical frame metadata, never raw results, accounts,
        # rosters, permissions, live-media state, or resolved filesystem paths.
        key = (task_id, hashlib.sha256(encoded).hexdigest(), base.lower())
        with self._frame_cache_lock:
            frames = self._frame_cache.get(key)
            if frames is None:
                # Serialize cold parses as well as eviction to avoid a stampede.
                # Failed validation never publishes or falls back to an entry.
                frames = self._parse_frames(manifest)
                while self._frame_cache and (
                    len(self._frame_cache) >= MAX_FRAME_CACHE_MANIFESTS
                    or self._frame_cache_entries + len(frames) > MAX_FRAME_CACHE_ENTRIES
                ):
                    _, evicted = self._frame_cache.popitem(last=False)
                    self._frame_cache_entries -= len(evicted)
                self._frame_cache[key] = frames
                self._frame_cache_entries += len(frames)
            self._frame_cache.move_to_end(key)
        # Each frame contains only immutable scalars; copy both dict levels so
        # even an internal caller cannot modify a subsequent request's index.
        return {frame_key: dict(frame) for frame_key, frame in frames.items()}

    @classmethod
    def _parse_frames(cls, task):
        raw = task.get("processing_result_json")
        try:
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PROCESSING_RESULT_BYTES:
                raise ValueError
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("task_id") != task["task_id"]:
                raise ValueError
            base, source = task.get("sha256"), result.get("source_sha256")
            if (not isinstance(base, str) or not isinstance(source, str)
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", base) or not re.fullmatch(r"[0-9a-fA-F]{64}", source)
                    or not hmac.compare_digest(base.lower(), source.lower())):
                raise IdentityError(409, "source_hash_mismatch", "分析结果与上传视频的校验记录不一致")
            segments = result.get("segments")
            if not isinstance(segments, list):
                raise ValueError
            frames = {}
            for segment_index, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    raise ValueError
                start, end = _number(segment.get("start_sec")), _number(segment.get("end_sec"))
                if start < 0 or end <= start:
                    raise ValueError
                visual = segment.get("visual")
                if not isinstance(visual, dict) or not isinstance(visual.get("samples"), list):
                    raise ValueError
                for sample_index, sample in enumerate(visual["samples"]):
                    if not isinstance(sample, dict):
                        raise ValueError
                    time = _number(sample.get("timestamp_sec"))
                    if not start <= time < end or len(frames) >= MAX_FRAMES:
                        raise ValueError
                    relative = cls._sample_image(result, sample, segment_index, sample_index, time)
                    # Indexing is lexical only: resolving every path per GET is
                    # prohibitively costly for long videos. The selected frame
                    # is always resolved and link/existence checked by _frame.
                    cls._image_parts(relative)
                    key = f"s{segment_index}_f{sample_index}"
                    frames[key] = {"frame_key": key, "time_sec": time, "segment_start_sec": start,
                                   "segment_end_sec": end, "relative_image": relative}
            return frames
        except IdentityError as exc:
            if exc.code in {"source_hash_mismatch", "invalid_frame_manifest"}:
                raise
            raise IdentityError(409, "invalid_frame_manifest", "可信采样帧清单缺失或格式无效") from None
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            raise IdentityError(409, "invalid_frame_manifest", "可信采样帧清单缺失或格式无效") from None

    def _require_media(self, task) -> Path:
        if task["analysis_status"] != "evidence_ready":
            raise IdentityError(409, "evidence_not_ready", "视频证据尚未就绪，不能新增身份绑定或读取截图")
        try:
            self.record_store._require_live_video(task)
        except ValueError:
            raise IdentityError(410, "media_unavailable", "原视频已到期、删除或未完成上传") from None
        try:
            source = self.record_store._video_source_path(task)
            if not source.is_file():
                raise ValueError
        except (OSError, ValueError, RuntimeError):
            raise IdentityError(410, "media_unavailable", "原视频不存在或不可读取") from None
        return source

    def _frame(self, task, frame_key, revision):
        if not isinstance(revision, str) or revision != self._revision(task):
            raise IdentityError(409, "stale_frame_revision", "采样帧版本已变化，请刷新后重新确认")
        self._require_media(task)
        frames = self._frames(task)
        if not isinstance(frame_key, str) or frame_key not in frames:
            raise IdentityError(404, "frame_unavailable", "未找到指定采样帧")
        frame = frames[frame_key]
        path = self._image_path(task, frame["relative_image"], must_exist=True)
        return frame, path

    @staticmethod
    def _public_binding(row, revision, valid_keys):
        binding = {key: row[key] for key in ("binding_id", "task_id", "owner_account_id", "scope_key", "student_id", "role",
                   "frame_key", "frame_revision", "source_sha256", "time_sec", "confirmed_by", "created_at", "status",
                   "revoked_by", "revoked_at", "revoked_reason")}
        binding["bbox"] = json.loads(row["bbox_json"])
        binding["current_revision"] = row["frame_revision"] == revision and row["frame_key"] in valid_keys
        binding["stale"] = not binding["current_revision"]
        binding["identity_scope"] = IDENTITY_SCOPE
        binding["overlap_confirmed"] = bool(row["overlap_confirmed"]) if "overlap_confirmed" in row.keys() else False
        return binding

    def _bindings(self, connection, task, revision, valid_keys):
        return [self._public_binding(row, revision, valid_keys) for row in connection.execute("""
            SELECT * FROM demo2_identity_bindings WHERE task_id = ? AND owner_account_id = ?
            ORDER BY created_at, rowid
        """, (task["task_id"], task.get("account_id")))]

    def _workspace(self, token, task_id, *, export=False):
        account = self._account(token)
        with self.record_store._connect() as connection:
            task = self._task(connection, account, task_id)
            context = self._context(task.get("school_context_json"), required=False)
            scope = self._scope(task.get("account_id"), context)
            students = self._students(connection, task.get("account_id"), scope) if scope else []
            revision = self._revision(task)
            frames, reason = {}, ""
            try:
                frames = self._frames(task)
            except IdentityError as exc:
                reason = exc.code
            valid_keys = set(frames) if task["analysis_status"] == "evidence_ready" else set()
            bindings = self._bindings(connection, task, revision, valid_keys)
            live_evidence = True
            try:
                self._require_media(task)
            except IdentityError as exc:
                reason = exc.code
                live_evidence = False
            owner_teacher = account["role"] == "school_uploader" and task.get("account_id") == account["account_id"]
            needs_school_confirmation = owner_teacher and self._empty_school_snapshot(task.get("school_context_json"))
            can_confirm_school = False
            if needs_school_confirmation:
                current_context = self._context(
                    self.record_store._school_context_for_account(connection, account["account_id"]), required=False
                )
                can_confirm_school = (live_evidence and bool(self._scope(account["account_id"], current_context))
                                      and not self._task_has_bindings(connection, task_id))
            media_available = not reason and bool(frames)
            public_frames = [{**{key: value for key, value in frame.items() if key != "relative_image"},
                              "image_url": "/api/v1/demo2/identity/frame?" + urlencode(
                                  {"task_id": task_id, "frame_key": frame["frame_key"], "frame_revision": revision})
                              if media_available else ""} for frame in frames.values()]
            current = [item for item in bindings if item["status"] == "confirmed" and item["current_revision"]]
            summary = {"identity_scope": IDENTITY_SCOPE, "tracking_performed": False,
                       "global_motion_attributed_to_student": False, "global_audio_attributed_to_student": False,
                       "confirmed_count": sum(item["status"] == "confirmed" for item in bindings),
                       "current_confirmed_count": len(current), "revoked_count": sum(item["status"] == "revoked" for item in bindings),
                       "stale_count": sum(item["stale"] for item in bindings),
                       "bound_student_count": len({item["student_id"] for item in current if item["role"] == "student"}),
                       "frame_count": len(frames), "media_unavailable_reason": reason or ("no_sample_frames" if not frames else ""),
                       "frame_files_checked_on_access": True,
                       "note": "仅人工确认单张采样帧中的身份，不代表整段跟踪；全场景动作和音频指标不归属任何学生。"}
            self._audit(connection, account, "identity_exported" if export else "identity_workspace_viewed", task_id,
                        {"frame_revision": revision, "binding_count": len(bindings)})
        result = {"task_id": task_id, "course_id": task["course_id"], "course_name": task["course_name"],
                  "school_context": context, "scope_key": scope, "students": students, "bindings": bindings,
                  "frames": public_frames, "frame_revision": revision, "summary": summary,
                  "can_edit": account["role"] == "school_uploader" and bool(scope) and media_available,
                  "can_revoke": owner_teacher,
                  "needs_school_confirmation": needs_school_confirmation,
                  "can_confirm_school": can_confirm_school,
                  "media_available": media_available}
        if export:
            result.update({"schema_version": 1, "exported_at": _iso(), "identity_scope": IDENTITY_SCOPE})
        return result

    def workspace(self, token, task_id):
        return self._workspace(token, task_id)

    def confirm_task_school(self, token, payload):
        """Explicitly attribute an unbound legacy task to the owner's school.

        This is never an automatic migration or a way to change an existing
        school. The expected scope is the one the user saw in their roster.
        """
        account = self._account(token, write=True)
        if (not isinstance(payload, dict) or set(payload) != {"task_id", "expected_scope_key", "confirmed"}
                or payload["confirmed"] is not True
                or not isinstance(payload["expected_scope_key"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", payload["expected_scope_key"])):
            raise IdentityError(400, "invalid_school_confirmation", "请显式确认所展示学校，仅提交任务编号与当前学校范围")
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._task(connection, account, payload["task_id"])
            if not self._empty_school_snapshot(task.get("school_context_json")):
                raise IdentityError(409, "task_school_not_empty", "任务已有学校信息或快照无效，不允许覆盖；请刷新任务")
            if self._task_has_bindings(connection, task["task_id"]):
                raise IdentityError(409, "task_has_bindings", "任务已有身份绑定记录，不允许变更学校归属")
            context = self._context(self.record_store._school_context_for_account(connection, account["account_id"]))
            scope = self._scope(account["account_id"], context)
            if not hmac.compare_digest(payload["expected_scope_key"], scope):
                raise IdentityError(409, "school_scope_changed", "当前学校信息已变化，请重新查看学校信息后确认")
            self._require_media(task)
            connection.execute(
                "UPDATE video_analysis_tasks SET school_context_json = ?, updated_at = ? WHERE task_id = ?",
                (json.dumps(context, ensure_ascii=False, sort_keys=True), _iso(), task["task_id"]),
            )
            self._audit(connection, account, "identity_task_school_confirmed", task["task_id"],
                        {"old_scope_key": "", "new_scope_key": scope, "confirmed_by": account["username"]})
        # workspace authenticates on a separate connection; only read it after
        # committing the write transaction to avoid locking our own session.
        return self.workspace(token, task["task_id"])

    def save_binding(self, token, payload):
        account = self._account(token, write=True)
        required = {"task_id", "frame_key", "frame_revision", "role", "bbox"}
        if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {"student_id", "overlap_confirmed"}:
            raise IdentityError(400, "invalid_binding", "请仅提交任务、帧版本、身份角色、学生编号和矩形")
        if "overlap_confirmed" in payload and type(payload["overlap_confirmed"]) is not bool:
            raise IdentityError(400, "invalid_overlap_confirmation", "请明确确认重叠位置，而不是提交其他数值")
        role = payload["role"]
        if not isinstance(role, str) or role not in {"student", "teacher", "unknown"}:
            raise IdentityError(400, "invalid_role", "身份角色仅支持学生、教师或未知")
        student_id = payload.get("student_id")
        if role == "student":
            if not isinstance(student_id, str) or not student_id:
                raise IdentityError(400, "student_required", "请从任务所属名册选择学生")
            student_id = _field(student_id, 120, required=True)
        elif student_id is not None:
            raise IdentityError(400, "unexpected_student", "教师或未知身份不能指定学生编号")
        box = _bbox(payload["bbox"])
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._task(connection, account, payload["task_id"])
            context = self._context(task.get("school_context_json"))
            scope = self._scope(task["account_id"], context)
            frame, _ = self._frame(task, payload["frame_key"], payload["frame_revision"])
            if role == "student":
                if connection.execute("""SELECT 1 FROM demo2_identity_students
                    WHERE student_id = ? AND owner_account_id = ? AND scope_key = ?""",
                    (student_id, account["account_id"], scope)).fetchone() is None:
                    raise IdentityError(404, "student_unavailable", "学生不在该任务所属名册内")
                existing = connection.execute("""SELECT binding_id, student_id, bbox_json FROM demo2_identity_bindings
                    WHERE task_id = ? AND frame_key = ? AND frame_revision = ? AND role = 'student' AND status = 'confirmed'""",
                    (task["task_id"], frame["frame_key"], payload["frame_revision"])).fetchall()
                overlapping_ids = []
                for other in existing:
                    if other["student_id"] == student_id:
                        raise IdentityError(409, "duplicate_student_binding", "该学生在当前采样帧已有有效绑定，请先撤销旧绑定")
                    overlap = _iou(box, json.loads(other["bbox_json"]))
                    if overlap >= 0.98:
                        raise IdentityError(409, "indistinguishable_student_binding", "两个学生的框几乎完全相同。请框住可区分的可见部分，或换一个时刻核对")
                    if overlap > 0.7:
                        if payload.get("overlap_confirmed") is not True:
                            raise IdentityError(409, "overlapping_student_binding", "框内与另一名学生位置重叠。请核对确为不同学生；无法分辨时应换一个时刻，不要猜测姓名")
                        overlapping_ids.append(other["binding_id"])
            else:
                overlapping_ids = []
            binding = {"binding_id": str(uuid4()), "task_id": task["task_id"], "owner_account_id": account["account_id"],
                       "scope_key": scope, "student_id": student_id, "role": role, "frame_key": frame["frame_key"],
                       "frame_revision": payload["frame_revision"], "source_sha256": task["sha256"], "time_sec": frame["time_sec"],
                       "bbox_json": json.dumps(box, separators=(",", ":")), "confirmed_by": account["username"], "created_at": _iso(),
                       "status": "confirmed", "revoked_by": None, "revoked_at": None, "revoked_reason": "",
                       "overlap_confirmed": int(bool(overlapping_ids))}
            connection.execute("""INSERT INTO demo2_identity_bindings
                (binding_id, task_id, owner_account_id, scope_key, student_id, role, frame_key, frame_revision, source_sha256,
                 time_sec, bbox_json, confirmed_by, created_at, overlap_confirmed) VALUES
                (:binding_id, :task_id, :owner_account_id, :scope_key, :student_id, :role, :frame_key, :frame_revision,
                 :source_sha256, :time_sec, :bbox_json, :confirmed_by, :created_at, :overlap_confirmed)""", binding)
            self._audit(connection, account, "identity_binding_confirmed", binding["binding_id"],
                        {"task_id": task["task_id"], "frame_key": frame["frame_key"], "frame_revision": payload["frame_revision"], "role": role,
                         "overlap_confirmed": bool(overlapping_ids), "overlapping_binding_ids": overlapping_ids})
        return self._public_binding(binding, payload["frame_revision"], {frame["frame_key"]})

    def revoke_binding(self, token, payload):
        account = self._account(token, write=True)
        if not isinstance(payload, dict) or set(payload) != {"task_id", "binding_id", "reason"}:
            raise IdentityError(400, "invalid_revocation", "请提供任务、绑定编号和撤销原因")
        reason = _field(payload["reason"], 500, required=True)
        binding_id = _field(payload["binding_id"], 120, required=True)
        with self.record_store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._task(connection, account, payload["task_id"])
            row = connection.execute("""SELECT * FROM demo2_identity_bindings
                WHERE binding_id = ? AND task_id = ? AND owner_account_id = ?""",
                (binding_id, task["task_id"], account["account_id"])).fetchone()
            if row is None:
                raise IdentityError(404, "binding_unavailable", "未找到指定绑定")
            if row["status"] != "revoked":
                connection.execute("""UPDATE demo2_identity_bindings SET status = 'revoked', revoked_by = ?,
                    revoked_at = ?, revoked_reason = ? WHERE binding_id = ?""", (account["username"], _iso(), reason, binding_id))
                self._audit(connection, account, "identity_binding_revoked", binding_id, {"task_id": task["task_id"], "reason": reason})
            row = connection.execute("SELECT * FROM demo2_identity_bindings WHERE binding_id = ?", (binding_id,)).fetchone()
            try:
                keys = set(self._frames(task)) if task["analysis_status"] == "evidence_ready" else set()
            except IdentityError:
                keys = set()
            return self._public_binding(row, self._revision(task), keys)

    def frame_file(self, token, task_id, frame_key, frame_revision):
        account = self._account(token)
        with self.record_store._connect() as connection:
            task = self._task(connection, account, task_id)
            frame, path = self._frame(task, frame_key, frame_revision)
            self._audit(connection, account, "identity_frame_viewed", task_id,
                        {"frame_key": frame["frame_key"], "frame_revision": frame_revision})
        return path, IMAGE_MIMES[path.suffix.lower()]

    def preview_source(self, token, task_id, frame_key, frame_revision) -> dict[str, Any]:
        """Server-only source for a read-only preview; never serialize to clients."""
        account = self._account(token)
        with self.record_store._connect() as connection:
            task = self._task(connection, account, task_id)
            frame, _ = self._frame(task, frame_key, frame_revision)
            source = self._require_media(task)
            self._audit(connection, account, "identity_preview_viewed", task_id,
                        {"frame_key": frame["frame_key"], "frame_revision": frame_revision})
        return {"source_path": source, "time_sec": frame["time_sec"]}

    def export(self, token, task_id):
        return self._workspace(token, task_id, export=True)

    def tracking_seed(self, token, payload):
        """Authorize a short, unconfirmed position suggestion from a saved ROI."""
        account = self._account(token, write=True)
        if not isinstance(payload, dict) or set(payload) != {"task_id", "binding_id", "frame_revision"}:
            raise IdentityError(400, "invalid_tracking_request", "请从已确认的学生记录开始查看后续位置")
        binding_id = _field(payload["binding_id"], 120, required=True)
        with self.record_store._connect() as connection:
            task = self._task(connection, account, payload["task_id"])
            row = connection.execute("""SELECT * FROM demo2_identity_bindings
                WHERE task_id = ? AND binding_id = ? AND owner_account_id = ?""",
                (task["task_id"], binding_id, account["account_id"])).fetchone()
            if (row is None or row["status"] != "confirmed" or row["role"] != "student"
                    or row["frame_revision"] != payload["frame_revision"] or row["source_sha256"] != task["sha256"]):
                raise IdentityError(409, "tracking_seed_unavailable", "起始确认已变化或失效，请刷新后重新选择学生记录")
            scope = self._scope(task["account_id"], self._context(task["school_context_json"]))
            if scope != row["scope_key"]:
                raise IdentityError(409, "tracking_scope_changed", "任务学校归属已变化，请重新核对")
            student = connection.execute("""SELECT * FROM demo2_identity_students
                WHERE student_id = ? AND owner_account_id = ? AND scope_key = ?""",
                (row["student_id"], account["account_id"], scope)).fetchone()
            if student is None:
                raise IdentityError(409, "student_unavailable", "该学生已不在任务所属名册中")
            first, first_path = self._frame(task, row["frame_key"], payload["frame_revision"])
            frames = [{"frame_key": first["frame_key"], "time_sec": first["time_sec"], "path": first_path}]
            following = sorted((frame for frame in self._frames(task).values()
                                if first["time_sec"] < frame["time_sec"] <= first["time_sec"] + 5),
                               key=lambda frame: frame["time_sec"])
            for frame in following[:5]:
                frames.append({"frame_key": frame["frame_key"], "time_sec": frame["time_sec"],
                               "path": self._image_path(task, frame["relative_image"], must_exist=True)})
            self._audit(connection, account, "identity_tracking_requested", binding_id,
                        {"task_id": task["task_id"], "frame_revision": payload["frame_revision"], "frame_count": len(frames)})
            return {"binding_id": binding_id, "student_id": row["student_id"], "display_name": student["display_name"],
                    "frame_revision": payload["frame_revision"], "bbox": _bbox(json.loads(row["bbox_json"])), "frames": frames}
