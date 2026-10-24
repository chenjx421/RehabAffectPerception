"""Disposable dossier HTTP/browser acceptance. All authorization is fictional.

Run serially: python -B -m scripts.qa_demo2_dossier_20260911
No existing database, worker, port 8792, real authorization, or browser download.
The temporary env key exists only in this isolated Python process and is restored.
"""
from __future__ import annotations

import argparse
import base64
from http.client import HTTPConnection, HTTPResponse
import json
import os
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from scripts.qa_demo2_identity_20260910 import isolated_identity_server

REPO = Path(__file__).resolve().parents[1]
API = "/api/v1/demo2/dossier"
KEY_ENV = "REHAB_DEMO2_DOSSIER_KEY"
KEY_LOCK = threading.RLock()
SUMMARY_KEYS = ("learning_goals", "support_methods", "safety_notes", "professional_conclusion")
FAKE_AUTH = "FICTIONAL-AUTH-QA-ONLY-不得作为真实授权证明"
FAKE_TEXT = b"FICTIONAL-IEP-QA-ONLY: synthetic support information, no real pupil or diagnosis."
SCHOOL_B = {"city": "虚构乙市", "district": "虚构乙区", "school_name": "QA乙校（非真实学校）"}


def day(offset=0):
    return (date.today() + timedelta(days=offset)).isoformat()


def http(env, method, path, payload=None, *, user="t1", token=None, content_type="application/json"):
    """One socket write also handles early authorization denial on Windows."""
    token = token if token is not None else (env.tokens[user] if user else "")
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Host": f"127.0.0.1:{env.port}", "Connection": "close",
               "Content-Type": content_type, "Content-Length": str(len(body))}
    if token:
        headers["Cookie"] = "rehab_demo2_session=" + token
    wire = (f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode("ascii") + body
    conn = HTTPConnection("127.0.0.1", env.port, timeout=15)
    try:
        conn.connect()
        conn.sock.sendall(wire)
        response = HTTPResponse(conn.sock, method=method)
        response.begin()
        raw = response.read()
        outgoing = {k.lower(): v for k, v in response.getheaders()}
        data = json.loads(raw) if "application/json" in outgoing.get("content-type", "") else raw
        return response.status, outgoing, data
    finally:
        conn.close()


def authorization_payload(env, *, student="a", mode="original_and_summary", **changes):
    return {"student_id": env.students[student]["student_id"], "reference": FAKE_AUTH,
            "storage_mode": mode, "valid_until": day(30), "confirmed": True, **changes}


def document_payload(env, authorization, *, student="a", version=1, supersedes_id="", with_file=True, **changes):
    return {"student_id": env.students[student]["student_id"], "authorization_id": authorization["authorization_id"],
            "document_type": "iep", "document_date": day(), "source_ref": f"FICTIONAL-SOURCE-QA-V{version}",
            "retain_until": day(20), "summary": {key: f"FICTIONAL-{key}-V{version}" for key in SUMMARY_KEYS},
            "filename": f"FICTIONAL-IEP-V{version}.txt" if with_file else "",
            "content_base64": base64.b64encode(FAKE_TEXT + f" V{version}".encode()).decode() if with_file else "",
            "supersedes_id": supersedes_id, **changes}


@contextmanager
def isolated_dossier_server(root: Path):
    """Fresh SQLite, fresh key, real dossier store and private HTTP module."""
    with KEY_LOCK, patch.dict(os.environ, {KEY_ENV: Fernet.generate_key().decode()}):
        with isolated_identity_server(root) as env:
            # Import only after env injection; never initialize the live vault.
            from src.rehab_affect.demo2_dossier_store import Demo2DossierStore

            env.records.save_account_school_context(env.tokens["t2"], SCHOOL_B)
            with env.records._connect() as connection:
                connection.execute("UPDATE video_analysis_tasks SET school_context_json=? WHERE task_id=?",
                                   (json.dumps(SCHOOL_B, ensure_ascii=False), env.task_ids["t2"]))
            env.students = {}
            for label, alias, code in (("a", "t1", "QA-A"), ("b", "t1", "QA-B"), ("other", "t2", "QA-OTHER")):
                env.students[label] = env.identity.create_student(env.tokens[alias], {
                    "display_name": "虚构同名学生" if alias == "t1" else "虚构乙校学生",
                    "student_code": code, "class_name": "虚构测试班", "note": "QA夹具，无真实学生资料",
                })
            env.dossier = Demo2DossierStore(env.records, env.identity)
            env.vault_root = env.records.upload_dir.parent / "scoped_dossier_v1"
            env.vault_key = os.environ[KEY_ENV]
            current = env.identity.workspace(env.tokens["t1"], env.task_ids["t1"])
            assert current["media_available"] and current["frames"], "Real frame publication must work"
            env.binding_payload = {"task_id": env.task_ids["t1"], "frame_key": current["frames"][0]["frame_key"],
                                   "frame_revision": current["frame_revision"], "role": "student",
                                   "student_id": env.students["a"]["student_id"],
                                   "bbox": {"x": .15, "y": .2, "width": .2, "height": .6}}
            env.bind = lambda: env.identity.save_binding(env.tokens["t1"], env.binding_payload)
            yield env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="node")
    parser.add_argument("--output", type=Path, default=REPO / "output/playwright/demo2_dossier_20260911_isolated")
    args = parser.parse_args()
    output = args.output.resolve() / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    outcome = {"fixture_only": True, "isolated_server_closed": False}
    try:
        (REPO / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dqa-", dir=REPO / "tmp") as temporary:
            with isolated_dossier_server(Path(temporary)) as env:
                config = {"isolated": True, "base": f"http://127.0.0.1:{env.port}", "guard": env.guard,
                          "users": env.users, "usernames": env.usernames, "students": env.students,
                          "task_id": env.task_ids["t1"], "binding": env.binding_payload,
                          "output": str(output), "today": day(), "valid_until": day(30), "retain_until": day(20),
                          "fictional_authorization": FAKE_AUTH, "document_base64": base64.b64encode(FAKE_TEXT).decode()}
                child_env = dict(os.environ)
                child_env.pop(KEY_ENV, None)  # Browser has no access to the encryption key.
                child_env.setdefault("NODE_PATH", str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"))
                completed = subprocess.run([args.node, str(Path(__file__).with_suffix(".js"))],
                                           input=json.dumps(config, ensure_ascii=False), text=True, encoding="utf-8",
                                           cwd=REPO, env=child_env, timeout=240, check=False)
                outcome["exit_code"] = completed.returncode
        outcome["isolated_server_closed"] = True
    except Exception as exc:
        # No credentials, private content or local DB paths in exception output.
        outcome.update({"exit_code": 1, "error_type": type(exc).__name__, "cleanup_attempted": True})
    (output / "harness_report.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps({**outcome, "output": str(output)}, ensure_ascii=False))
    return outcome.get("exit_code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
