"""Durable teacher drafts for long-term → short-term goal decomposition.

Drafts are explicitly not IEPs. They are scoped to the owning uploader account
and are never used to generate a formal report without teacher confirmation.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4


class GoalPlanError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: Any, limit: int, required: bool = False, field: str = "") -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise GoalPlanError(400, "invalid_goal_plan", f"{field or '文本'}格式无效")
    value = value.strip()
    if required and not value:
        raise GoalPlanError(400, "invalid_goal_plan", f"请填写{field or '内容'}")
    if len(value) > limit:
        raise GoalPlanError(400, "invalid_goal_plan", f"{field or '文本'}不能超过 {limit} 字")
    return value


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    if value < low or value > high:
        raise GoalPlanError(400, "invalid_goal_plan", f"周期必须在 {low}–{high} 周之间")
    return value


class Demo2GoalPlanStore:
    def __init__(self, record_store: Any):
        self.records = record_store

    def _ensure(self, db: sqlite3.Connection) -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_goal_plans (
            plan_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            long_term TEXT NOT NULL DEFAULT '',
            baseline TEXT NOT NULL DEFAULT '',
            weeks INTEGER NOT NULL DEFAULT 4,
            goals_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            confirmed_at TEXT NOT NULL DEFAULT '',
            UNIQUE(account_id, student_id, subject)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_demo2_goal_plans_owner ON demo2_goal_plans(account_id, student_id)")
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_goal_plan_owner_acceptance (
            plan_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            accepted_at TEXT NOT NULL
        )""")

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        try:
            goals = json.loads(row["goals_json"] or "[]")
        except (TypeError, ValueError):
            goals = []
        return {
            "plan_id": row["plan_id"], "student_id": row["student_id"], "subject": row["subject"],
            "long_term": row["long_term"], "baseline": row["baseline"], "weeks": int(row["weeks"]),
            "goals": goals if isinstance(goals, list) else [], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "confirmed_at": row["confirmed_at"],
        }

    def owner_accept(self, account_id: str, plan_id: str) -> dict[str, Any]:
        with self.records._connect() as db:
            self._ensure(db)
            row = db.execute("SELECT plan_id FROM demo2_goal_plans WHERE plan_id=? AND account_id=?",
                             (plan_id, account_id)).fetchone()
            if row is None:
                raise GoalPlanError(404, "goal_plan_not_found", "目标草案不存在")
            accepted = _now()
            db.execute("""INSERT INTO demo2_goal_plan_owner_acceptance(plan_id, account_id, accepted_at)
                VALUES(?,?,?) ON CONFLICT(plan_id) DO UPDATE SET accepted_at=excluded.accepted_at,
                account_id=excluded.account_id""", (plan_id, account_id, accepted))
            db.commit()
        return {"plan_id": plan_id, "owner_accepted_at": accepted}

    def owner_accepted(self, plan_id: str) -> str:
        with self.records._connect() as db:
            self._ensure(db)
            row = db.execute("SELECT accepted_at FROM demo2_goal_plan_owner_acceptance WHERE plan_id=?",
                             (plan_id,)).fetchone()
            return str(row["accepted_at"]) if row else ""

    def get(self, account_id: str, student_id: str, subject: str) -> dict[str, Any] | None:
        with self.records._connect() as db:
            self._ensure(db)
            row = db.execute("SELECT * FROM demo2_goal_plans WHERE account_id=? AND student_id=? AND subject=?",
                             (account_id, student_id, subject)).fetchone()
            return self._public(row) if row else None

    def list_for_student(self, account_id: str, student_id: str) -> list[dict[str, Any]]:
        with self.records._connect() as db:
            self._ensure(db)
            rows = db.execute("SELECT * FROM demo2_goal_plans WHERE account_id=? AND student_id=? ORDER BY updated_at DESC",
                              (account_id, student_id)).fetchall()
            return [self._public(row) for row in rows]

    def list_all(self, account_id: str) -> list[dict[str, Any]]:
        with self.records._connect() as db:
            self._ensure(db)
            rows = db.execute("SELECT * FROM demo2_goal_plans WHERE account_id=? ORDER BY updated_at DESC",
                              (account_id,)).fetchall()
            return [self._public(row) for row in rows]

    def due_stages(self, account_id: str, today: str) -> list[dict[str, Any]]:
        """Stages whose date is on/before today; no hidden notification is invented."""
        from datetime import date, timedelta
        try:
            current = date.fromisoformat(today)
        except ValueError:
            current = date.today()
        due = []
        for plan in self.list_all(account_id):
            base = str(plan.get("confirmed_at") or plan.get("updated_at") or "")
            try:
                start = date.fromisoformat(base[:10])
            except ValueError:
                continue
            for week in (1, 2, 4, 8):
                when = start + timedelta(weeks=week)
                if when <= current:
                    due.append({"plan_id": plan["plan_id"], "student_id": plan["student_id"],
                                "subject": plan["subject"], "week": week, "due_date": when.isoformat(),
                                "days_overdue": (current - when).days, "status": plan.get("status") or "draft"})
        due.sort(key=lambda item: (item["due_date"], item["student_id"], item["week"]))
        return due

    def save(self, account_id: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise GoalPlanError(400, "invalid_goal_plan", "请求格式无效")
        allowed = {"student_id", "subject", "long_term", "baseline", "weeks", "goals", "status"}
        if set(payload) - allowed:
            raise GoalPlanError(400, "invalid_goal_plan", "包含不支持的字段")
        student_id = _text(payload.get("student_id"), 120, True, "学生")
        subject = _text(payload.get("subject"), 40, True, "学科")
        long_term = _text(payload.get("long_term"), 1000, True, "长期目标")
        baseline = _text(payload.get("baseline"), 1000, False, "当前基线")
        weeks = _int(payload.get("weeks"), 4, 1, 36)
        status = payload.get("status") or "draft"
        if status not in {"draft", "confirmed"}:
            raise GoalPlanError(400, "invalid_goal_plan", "草案状态无效")
        raw_goals = payload.get("goals")
        if not isinstance(raw_goals, list) or len(raw_goals) > 10:
            raise GoalPlanError(400, "invalid_goal_plan", "短期目标必须是 0–10 条")
        goals = []
        for index, item in enumerate(raw_goals, start=1):
            if not isinstance(item, dict):
                raise GoalPlanError(400, "invalid_goal_plan", f"第 {index} 条短期目标格式无效")
            goals.append({
                "goal": _text(item.get("goal"), 500, False, f"第 {index} 条短期目标"),
                "criterion": _text(item.get("criterion"), 500, False, f"第 {index} 条通过标准"),
                "evidence": _text(item.get("evidence"), 500, False, f"第 {index} 条视频/课堂证据"),
                "support": _text(item.get("support"), 500, False, f"第 {index} 条支持方式"),
                "lesson_goal_id": _text(item.get("lesson_goal_id"), 120, False, f"第 {index} 条本课目标"),
            })
        if not any(g["goal"] for g in goals):
            raise GoalPlanError(400, "invalid_goal_plan", "请至少填写一条短期目标")
        if status == "confirmed" and len([g for g in goals if g["goal"]]) < 1:
            raise GoalPlanError(400, "invalid_goal_plan", "教师确认前至少需要一条短期目标")
        now = _now()
        with self.records._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._ensure(db)
            existing = db.execute("SELECT * FROM demo2_goal_plans WHERE account_id=? AND student_id=? AND subject=?",
                                  (account_id, student_id, subject)).fetchone()
            if existing:
                plan_id = existing["plan_id"]
                db.execute("""UPDATE demo2_goal_plans SET long_term=?, baseline=?, weeks=?, goals_json=?,
                              status=?, updated_at=?, confirmed_at=? WHERE plan_id=?""",
                           (long_term, baseline, weeks, json.dumps(goals, ensure_ascii=False), status, now,
                            now if status == "confirmed" else "", plan_id))
            else:
                plan_id = "gp-" + uuid4().hex
                db.execute("""INSERT INTO demo2_goal_plans
                    (plan_id, account_id, student_id, subject, long_term, baseline, weeks, goals_json, status,
                     created_at, updated_at, confirmed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (plan_id, account_id, student_id, subject, long_term, baseline, weeks,
                            json.dumps(goals, ensure_ascii=False), status, now, now,
                            now if status == "confirmed" else ""))
            db.commit()
            row = db.execute("SELECT * FROM demo2_goal_plans WHERE plan_id=?", (plan_id,)).fetchone()
            return self._public(row)
