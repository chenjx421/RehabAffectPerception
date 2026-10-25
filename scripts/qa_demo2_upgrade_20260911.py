"""Opt-in, read-only live measurements. No workers, browsers or live DB access.

Passwords are read only from QA_DEMO2_TEACHER_PASSWORD and
QA_DEMO2_ADMIN_PASSWORD. Reports contain timings/lengths, never response bodies,
cookies, credentials or student information. Authentication creates a session;
all subsequent live operations are GETs. Baseline does not probe new routes.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import statistics
import tempfile
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode


API = "/api/v1/demo2/identity"
LOGIN = "/api/v1/demo2/auth/login"
TASK_ID = "a5ded3bc97c54d949961b130e6f18ca2"
MIN_INTERVAL = 2.2
PASSWORD_ENV = {"t1": "QA_DEMO2_TEACHER_PASSWORD", "admin": "QA_DEMO2_ADMIN_PASSWORD"}


class SafeQAError(RuntimeError):
    """Only locally authored, non-sensitive error messages reach stdout."""


class ReadOnlyLiveClient:
    def __init__(self):
        self.last_started = None
        self.cookies = {}
        self.samples = []

    def request(self, role, endpoint, *, query=None, password=None, sample=None):
        if role not in PASSWORD_ENV:
            raise SafeQAError("Unexpected account role")
        if endpoint == "login":
            if query is not None or not password:
                raise SafeQAError("Login requires an environment password")
            path, method = LOGIN, "POST"
            payload = json.dumps({"username": role, "password": password}).encode("utf-8")
        else:
            if password is not None or endpoint not in {"workspace", "frame", "detect", "preview"}:
                raise SafeQAError("Endpoint is outside the read-only allowlist")
            fields = {"task_id"} if endpoint == "workspace" else {"task_id", "frame_key", "frame_revision"}
            if not isinstance(query, dict) or set(query) != fields or query.get("task_id") != TASK_ID:
                raise SafeQAError("Query is outside the authorized task/field allowlist")
            if role not in self.cookies:
                raise SafeQAError("Authentication is required before measurement")
            path, method, payload = API + "/" + endpoint + "?" + urlencode(query), "GET", None
        if self.last_started is not None:
            time.sleep(max(0.0, MIN_INTERVAL - (time.perf_counter() - self.last_started)))
        started = time.perf_counter()
        interval = None if self.last_started is None else started - self.last_started
        self.last_started = started
        connection = http.client.HTTPConnection("127.0.0.1", 8792, timeout=90)
        headers = {"Connection": "close", "Accept-Encoding": "identity"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if role in self.cookies:
            headers["Cookie"] = self.cookies[role]
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            body = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            content_type = response.getheader("Content-Type", "").split(";", 1)[0]
            row = {"role": role, "endpoint": endpoint, "sample": sample,
                   "status": response.status, "response_bytes": len(body),
                   "elapsed_ms": round(elapsed_ms, 3), "content_type": content_type,
                   "cache_control": response.getheader("Cache-Control", ""),
                   "request_interval_sec": None if interval is None else round(interval, 6),
                   "interval_at_least_2_2_sec": interval is None or interval >= MIN_INTERVAL}
            parsed = None
            if response.status == 200 and content_type == "application/json":
                try:
                    parsed = json.loads(body)
                except (ValueError, UnicodeError) as from_error:
                    raise SafeQAError("Invalid JSON response; body was not logged") from from_error
            if endpoint == "login":
                if response.status != 200:
                    raise SafeQAError(f"Login failed for {role}: HTTP {response.status}")
                cookie = SimpleCookie()
                cookie.load(response.getheader("Set-Cookie", ""))
                session = cookie.get("rehab_demo2_session")
                if session is None:
                    raise SafeQAError("Login did not return the required session cookie")
                self.cookies[role] = "rehab_demo2_session=" + session.value
            else:
                if endpoint == "detect" and isinstance(parsed, dict):
                    detection = parsed.get("detection", {})
                    cached = parsed.get("cached", detection.get("cached") if isinstance(detection, dict) else None)
                    row["cached"] = cached if isinstance(cached, bool) else None
                    row["detector_available"] = detection.get("available") if isinstance(detection, dict) else None
                if content_type == "image/jpeg":
                    row["jpeg_signature_valid"] = body.startswith(b"\xff\xd8") and body.endswith(b"\xff\xd9")
                if endpoint == "preview":
                    cache = response.getheader("X-Preview-Cache")
                    row["preview_cache"] = cache if cache in {"hit", "miss"} else None
                self.samples.append(row)
            return row, parsed
        except (OSError, http.client.HTTPException) as from_error:
            raise SafeQAError("Live 127.0.0.1:8792 unavailable or request interrupted; no service changes made") from from_error
        finally:
            connection.close()


def summarize(rows):
    result = []
    for role in PASSWORD_ENV:
        for endpoint in ("workspace", "frame", "detect", "preview"):
            group = [row for row in rows if row["role"] == role and row["endpoint"] == endpoint]
            if group:
                result.append({"role": role, "endpoint": endpoint, "count": len(group),
                               "statuses": [row["status"] for row in group],
                               "bytes": [row["response_bytes"] for row in group],
                               "elapsed_ms": [row["elapsed_ms"] for row in group],
                               "median_ms": round(statistics.median(row["elapsed_ms"] for row in group), 3)})
    return result


def collect(phase):
    missing = [name for name in PASSWORD_ENV.values() if not os.environ.get(name)]
    if missing:
        raise SafeQAError("Missing password environment variables: " + ", ".join(missing))
    client = ReadOnlyLiveClient()
    report = {"phase": phase, "started_utc": datetime.now(timezone.utc).isoformat(),
              "host": "127.0.0.1:8792", "task_id": TASK_ID,
              "business_writes": 0, "browser_processes": 0, "external_requests": 0,
              "authentication_session_creation": True, "min_interval_sec": MIN_INTERVAL,
              "samples": client.samples}
    try:
        for role, variable in PASSWORD_ENV.items():
            client.request(role, "login", password=os.environ[variable])
            if phase == "after" and role == "t1":
                row, body = client.request(role, "workspace", query={"task_id": TASK_ID}, sample=0)
                if row["status"] != 200 or not isinstance(body, dict):
                    raise SafeQAError("Upgrade preflight could not read the authorized workspace")
                current = body.get("workspace", {})
                frames = current.get("frames", [])
                if not frames or not current.get("media_available"):
                    raise SafeQAError("Upgrade preflight has no authorized available frame")
                probe = {"task_id": TASK_ID, "frame_key": frames[0]["frame_key"],
                         "frame_revision": current["frame_revision"]}
                row, _ = client.request(role, "preview", query=probe, sample=0)
                if (row["status"] != 200 or row["content_type"] != "image/jpeg"
                        or not row.get("jpeg_signature_valid") or "no-store" not in row["cache_control"]):
                    raise SafeQAError("Upgrade preflight failed: preview must return a no-store JPEG with HTTP 200")
                row, _ = client.request(role, "detect", query=probe, sample=0)
                if row["status"] != 200 or not isinstance(row.get("cached"), bool):
                    raise SafeQAError("Upgrade preflight failed: detect must return a boolean cached field")
                report["version_preflight"] = {"passed": True, "samples": list(client.samples),
                                               "warms_teacher_preview_and_detect": True}
                client.samples.clear()
            identifiers = None
            for index in range(1, 4):
                row, body = client.request(role, "workspace", query={"task_id": TASK_ID}, sample=index)
                if row["status"] != 200 or not isinstance(body, dict):
                    raise SafeQAError(f"Workspace unavailable for {role}: HTTP {row['status']}")
                workspace = body.get("workspace", {})
                frames = workspace.get("frames", [])
                if not frames or not workspace.get("media_available"):
                    raise SafeQAError("Authorized task has no available frame; no repairs attempted")
                current = {"task_id": TASK_ID, "frame_key": frames[0]["frame_key"],
                           "frame_revision": workspace["frame_revision"]}
                if identifiers is not None and current != identifiers:
                    raise SafeQAError("Frame manifest changed during sampling; compare only stable runs")
                identifiers = current
            for endpoint in (("frame", "detect") if phase == "before" else ("frame", "detect", "preview")):
                for index in range(1, 4):
                    row, _ = client.request(role, endpoint, query=identifiers, sample=index)
                    if row["status"] != 200:
                        raise SafeQAError(f"{endpoint} failed for {role}: HTTP {row['status']}")
        report["complete"] = True
    except SafeQAError as error:
        report.update(complete=False, error=str(error))
    report["summary"] = summarize(client.samples)
    return report


def compare_reports(before, after):
    if not before.get("complete") or not after.get("complete"):
        raise SafeQAError("Before/after comparison requires two complete runs")
    if (before.get("phase"), after.get("phase")) != ("before", "after"):
        raise SafeQAError("Comparison requires a before report followed by an after report")
    if before.get("task_id") != after.get("task_id") or before.get("host") != after.get("host"):
        raise SafeQAError("Before/after host and task must match")
    indexed = {(item["role"], item["endpoint"]): item for item in before["summary"]}
    rows = []
    for new in after["summary"]:
        old = indexed.get((new["role"], new["endpoint"]))
        if old:
            rows.append({"role": new["role"], "endpoint": new["endpoint"],
                         "before_median_ms": old["median_ms"], "after_median_ms": new["median_ms"],
                         "delta_median_ms": round(new["median_ms"] - old["median_ms"], 3),
                         "before_bytes": old["bytes"], "after_bytes": new["bytes"]})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--service-updated", action="store_true", help="Required only after explicit update notice")
    parser.add_argument("--before-report", type=Path)
    args = parser.parse_args()
    if args.phase == "after" and not args.service_updated:
        parser.error("after is gated until the main task confirms the live service update")
    try:
        report = collect(args.phase)
        if args.before_report and report["complete"]:
            report["comparison"] = compare_reports(json.loads(args.before_report.read_text(encoding="utf-8")), report)
        destination = Path(tempfile.mkdtemp(prefix="qa_demo2_upgrade_20260911_")) / (args.phase + ".json")
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(destination), **report}, indent=2, ensure_ascii=True))
        return 0 if report["complete"] else 1
    except SafeQAError as error:
        print(json.dumps({"complete": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
