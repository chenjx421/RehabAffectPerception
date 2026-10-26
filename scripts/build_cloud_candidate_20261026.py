"""Build and verify the 2026-10-26 private cloud candidate package.

The selection mirrors ``cloud_build_release.py`` (application code, tests,
configs, deploy units, cloud helper scripts and the YuNet model) but adds an
explicit exclusion rule table, a content scan for key material, a post-build
extraction audit and a timestamped JSON-lines log.  Output is reproducible for a
given commit: tar entries use the HEAD commit time, root ownership and fixed
modes, and the gzip header carries no timestamp.
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".runtime/cloud_candidate_20261026/source.tar.gz"

SELECTION = (
    ("src", {".py"}),
    ("configs", {".json"}),
    ("tests", {".py"}),
    ("deploy/cloud", {".service", ".txt", ".sh"}),
)
# The SSH operator carries the operator-side key location and the snapshot
# helper reads private data; neither belongs on the server.
SCRIPT_EXCLUDES = {"cloud_ssh_operator.py", "cloud_prepare_snapshot.py"}
EXTRA_FILES = (
    "scripts/prepare_upload_video.py",
    "pyproject.toml",
    "models/face_detection_yunet_2023mar.onnx",
    "models/LICENSE.yunet",
)

# (rule id, description, glob patterns matched against the lower-cased
# basename or full relative path)
EXCLUSION_RULES = (
    ("database", "SQLite/DB files", ("*.db", "*.sqlite", "*.sqlite3", "*.db3")),
    ("wal_shm", "SQLite WAL/SHM/journal", ("*-wal", "*-shm", "*-journal", "*.wal", "*.shm")),
    ("video", "video media", ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm", "*.m4v",
                               "*.flv", "*.wmv", "*.mpg", "*.mpeg", "*.3gp")),
    ("audio", "audio media", ("*.wav", "*.mp3", "*.m4a", "*.aac", "*.flac")),
    ("key_material", "private keys and certificates",
     ("*.pem", "*.key", "*.p12", "*.pfx", "*.crt", "*.der", "id_rsa*", "id_ed25519*",
      "id_ecdsa*", "*_ed25519", "*_rsa", "*.ppk")),
    ("invitation_config", "invitation / gateway configs",
     ("invitations*.json", "invite_config*.json", "gateway.json")),
    ("credentials", "credential and secret files",
     ("*credential*", "*secret*", "*password*", "*token*.json", "schools.md", "admin.json",
      ".env", "*.env", "cloud.env", ".netrc")),
    ("runtime", "runtime/private trees", (".runtime/*", "*/.runtime/*", "data/*", "outputs/*")),
    ("bytecode", "compiled caches", ("*.pyc", "*/__pycache__/*", "__pycache__/*")),
)

KEY_CONTENT_PATTERNS = (
    ("private_key_block", re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("openssh_key_block", re.compile(rb"-----BEGIN OPENSSH PRIVATE KEY-----")),
    ("openai_style_api_key", re.compile(rb"\bsk-[A-Za-z0-9]{32,}\b")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
)


class BuildLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a", encoding="utf-8")

    def event(self, step: str, **fields):
        record = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                  "step": step, **fields}
        line = json.dumps(record, ensure_ascii=False)
        self.handle.write(line + "\n")
        self.handle.flush()
        print(line)

    def close(self):
        self.handle.close()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def match_exclusion(relative: str):
    lowered = relative.lower()
    basename = PurePosixPath(lowered).name
    for rule_id, _, patterns in EXCLUSION_RULES:
        for pattern in patterns:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(lowered, pattern):
                return rule_id, pattern
    return None


def scan_content(data: bytes):
    return [name for name, pattern in KEY_CONTENT_PATTERNS if pattern.search(data)]


def collect_candidates() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for folder, suffixes in SELECTION:
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files[path.relative_to(ROOT).as_posix()] = path
    for path in (ROOT / "scripts").glob("cloud_*.py"):
        if path.name not in SCRIPT_EXCLUDES:
            files[path.relative_to(ROOT).as_posix()] = path
    for name in EXTRA_FILES:
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError("Required package file missing: " + name)
        files[name] = path
    return files


def audit_archive(archive_path: Path, expected: dict[str, str], log: BuildLog) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="candidate_audit_") as scratch:
        scratch_root = Path(scratch).resolve()
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                target = (scratch_root / member.name).resolve()
                if not member.isfile():
                    problems.append("non_regular_member:" + member.name)
                elif scratch_root not in target.parents:
                    problems.append("path_escape:" + member.name)
            if problems:
                return problems
            archive.extractall(scratch_root, filter="data")
        extracted = {path.relative_to(scratch_root).as_posix(): path
                     for path in scratch_root.rglob("*") if path.is_file()}
        log.event("audit_extracted", member_count=len(members), extracted_files=len(extracted))
        rule_hits: dict[str, int] = {}
        for name, path in sorted(extracted.items()):
            hit = match_exclusion(name)
            if hit:
                rule_hits[hit[0]] = rule_hits.get(hit[0], 0) + 1
                problems.append(f"forbidden_after_extract:{hit[0]}:{name}")
            data = path.read_bytes()
            content_hits = scan_content(data)
            if content_hits:
                problems.append("key_material_after_extract:" + name + ":" + ",".join(content_hits))
            if data[:16] == b"SQLite format 3\x00":
                problems.append("sqlite_header_after_extract:" + name)
            digest = hashlib.sha256(data).hexdigest()
            if expected.get(name) != digest:
                problems.append("manifest_mismatch:" + name)
        missing = sorted(set(expected) - set(extracted))
        problems.extend("missing_after_extract:" + name for name in missing)
        log.event("audit_rules", forbidden_hits=rule_hits, missing=len(missing),
                  problems=len(problems))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Package even if tracked files differ from HEAD (recorded in the log).")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else (ROOT / args.output)
    output = output.resolve()
    log = BuildLog(output.parent / "build_log.jsonl")
    try:
        head = git("rev-parse", "HEAD")
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        dirty_tracked = [line for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line]
        commit_epoch = int(git("show", "-s", "--format=%ct", "HEAD"))
        log.event("start", output=output.relative_to(ROOT).as_posix(), branch=branch, head=head,
                  dirty_tracked_files=len(dirty_tracked))
        if dirty_tracked and not args.allow_dirty:
            log.event("result", status="FAILED", reason="tracked files differ from HEAD",
                      files=dirty_tracked[:20])
            return 2

        candidates = collect_candidates()
        log.event("collect", candidate_files=len(candidates))
        included: dict[str, Path] = {}
        excluded: list[dict] = []
        rule_hits = {rule_id: 0 for rule_id, _, _ in EXCLUSION_RULES}
        rule_hits["key_content_scan"] = 0
        rule_hits["symlink"] = 0
        for name, path in sorted(candidates.items()):
            if path.is_symlink():
                rule_hits["symlink"] += 1
                excluded.append({"path": name, "rule": "symlink"})
                continue
            hit = match_exclusion(name)
            if hit:
                rule_hits[hit[0]] += 1
                excluded.append({"path": name, "rule": hit[0], "pattern": hit[1]})
                continue
            content_hits = scan_content(path.read_bytes())
            if content_hits:
                rule_hits["key_content_scan"] += 1
                excluded.append({"path": name, "rule": "key_content_scan", "patterns": content_hits})
                continue
            included[name] = path
        for rule_id, description, patterns in EXCLUSION_RULES:
            log.event("exclusion_rule", rule=rule_id, description=description,
                      patterns=list(patterns), hits=rule_hits[rule_id])
        log.event("exclusion_rule", rule="key_content_scan",
                  description="private key / API key / token content", hits=rule_hits["key_content_scan"])
        log.event("exclusion_rule", rule="symlink", description="symbolic links refused",
                  hits=rule_hits["symlink"])
        for item in excluded:
            log.event("excluded", **item)

        output.parent.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, path in sorted(included.items()):
                data = path.read_bytes()
                hashes[name] = hashlib.sha256(data).hexdigest()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = commit_epoch
                info.mode = 0o755 if name.endswith(".sh") else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                archive.addfile(info, io.BytesIO(data))
        with output.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw,
                                                      mtime=0, compresslevel=9) as compressed:
            compressed.write(buffer.getvalue())
        payload = output.read_bytes()
        sha_lower = hashlib.sha256(payload).hexdigest()
        sha_upper = sha_lower.upper()
        log.event("package", files=len(included), excluded=len(excluded), bytes=len(payload),
                  uncompressed_bytes=len(buffer.getvalue()), sha256_lower=sha_lower,
                  sha256_upper=sha_upper)

        manifest_path = output.with_name(output.name + ".manifest.json")
        manifest_path.write_text(json.dumps({"branch": branch, "head": head, "files": hashes},
                                            indent=2) + "\n", encoding="utf-8")
        output.with_name(output.name + ".sha256").write_text(
            f"{sha_lower}  {output.name}\n", encoding="utf-8")
        output.with_name(output.name + ".sha256.upper.txt").write_text(sha_upper + "\n", encoding="utf-8")

        problems = audit_archive(output, hashes, log)
        if hashlib.sha256(output.read_bytes()).hexdigest() != sha_lower:
            problems.append("sha_changed_during_audit")
        summary = {"head": head, "branch": branch, "files": len(included), "excluded": len(excluded),
                   "bytes": len(payload), "sha256_lower": sha_lower, "sha256_upper": sha_upper,
                   "rule_hits": rule_hits, "problems": problems,
                   "status": "PASSED" if not problems else "FAILED"}
        output.with_name("build_summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                           encoding="utf-8")
        for problem in problems:
            log.event("audit_problem", detail=problem)
        log.event("result", status=summary["status"], files=len(included), bytes=len(payload),
                  sha256_lower=sha_lower, sha256_upper=sha_upper)
        return 0 if not problems else 1
    except Exception as error:  # noqa: BLE001 - recorded then re-raised as exit code
        log.event("result", status="FAILED", reason=type(error).__name__, detail=str(error))
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
