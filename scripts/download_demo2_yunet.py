"""Explicit, pinned YuNet dependency installation; never called by inference.

Uses only Python's standard library. No images or other project data are sent.
Existing files must match the pinned release and are never overwritten.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request


COMMIT = "47534e27c9851bb1128ccc0102f1145e27f23f98"
MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_SIZE = 232589
LICENSE_SHA256 = "c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
UPSTREAM_DIR = "opencv/opencv_zoo/contents/models/face_detection_yunet"
MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    f"{COMMIT}/models/face_detection_yunet/{MODEL_NAME}"
)
ALLOWED_HOSTS = frozenset({"api.github.com", "media.githubusercontent.com"})
NETWORK_BUDGET_SECONDS = 45.0
SOCKET_TIMEOUT_SECONDS = 10.0
CHUNK_BYTES = 65536


def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in ALLOWED_HOSTS
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("Refusing a non-official or non-HTTPS download URL")


class _OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, *, byte_limit: int, deadline: float) -> bytes:
    _check_url(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("YuNet download time budget exceeded")
    request = urllib.request.Request(
        url, headers={"User-Agent": "RehabAffectPerception-YuNet-installer/1"}
    )
    opener = urllib.request.build_opener(_OfficialRedirects())
    with opener.open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, remaining)) as response:
        _check_url(response.geturl())
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > byte_limit:
            raise ValueError("Official response exceeds the expected byte limit")
        result = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("YuNet download time budget exceeded")
            # read1 makes at most one underlying read, so a slow stream cannot
            # conceal elapsed time while filling a large read() request.
            chunk = response.read1(min(CHUNK_BYTES, byte_limit + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > byte_limit:
                raise ValueError("Official response exceeds the expected byte limit")
    return bytes(result)


def _upstream_file(name: str, *, deadline: float) -> bytes:
    url = f"https://api.github.com/repos/{UPSTREAM_DIR}/{name}?ref={COMMIT}"
    metadata = json.loads(_download(url, byte_limit=16384, deadline=deadline))
    if metadata.get("encoding") != "base64":
        raise ValueError("Unexpected official file metadata encoding")
    encoded = "".join(metadata["content"].split())
    return base64.b64decode(encoded, validate=True)


def _verify_model(data: bytes) -> None:
    if len(data) != MODEL_SIZE or hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("YuNet model size or SHA-256 does not match the pinned LFS pointer")


def _verify_license(data: bytes) -> None:
    # Preserve official text while tolerating a checkout's line endings and
    # final newline; the upstream LICENSE itself has no final newline.
    normalized = data.replace(b"\r\n", b"\n").rstrip(b"\n")
    if hashlib.sha256(normalized).hexdigest() != LICENSE_SHA256:
        raise ValueError("YuNet MIT license differs from the pinned upstream license")


def _read_existing(path: Path, *, byte_limit: int, verify) -> bool:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink destination: {path}")
    if not path.exists():
        return False
    if not path.is_file() or path.stat().st_size > byte_limit:
        raise ValueError(f"Refusing incompatible existing destination: {path}")
    with path.open("rb") as stream:
        verify(stream.read(byte_limit + 1))
    return True


def _install_without_overwrite(path: Path, data: bytes, verify) -> None:
    verify(data)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".yunet_download_", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish atomically without replacing any pre-existing destination.
        # A concurrent installer winning the race is accepted only if verified.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _read_existing(path, byte_limit=max(MODEL_SIZE, 4096), verify=verify):
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install(*, verify_only: bool = False) -> None:
    if MODEL_DIR.is_symlink():
        raise ValueError("Refusing a symlink model directory")
    model_path = MODEL_DIR / MODEL_NAME
    license_path = MODEL_DIR / "LICENSE.yunet"
    has_model = _read_existing(model_path, byte_limit=MODEL_SIZE, verify=_verify_model)
    has_license = _read_existing(license_path, byte_limit=4096, verify=_verify_license)
    if has_model and has_license:
        print(f"Verified existing YuNet: {model_path} ({MODEL_SIZE} bytes; {MODEL_SHA256})")
        return
    if verify_only:
        raise FileNotFoundError("Pinned YuNet model or MIT license is not installed; no network used")

    deadline = time.monotonic() + NETWORK_BUDGET_SECONDS
    pointer = _upstream_file(MODEL_NAME, deadline=deadline).decode("ascii")
    match = re.fullmatch(
        r"version https://git-lfs.github.com/spec/v1\n"
        r"oid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?",
        pointer.replace("\r\n", "\n"),
    )
    if match is None or match.groups() != (MODEL_SHA256, str(MODEL_SIZE)):
        raise ValueError("Official LFS pointer does not match the pinned model manifest")
    license_data = _upstream_file("LICENSE", deadline=deadline)
    _verify_license(license_data)
    model_data = None
    if not has_model:
        model_data = _download(MODEL_URL, byte_limit=MODEL_SIZE, deadline=deadline)
        _verify_model(model_data)
    # No destination is created until every downloaded artifact is validated.
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not has_license:
        _install_without_overwrite(license_path, license_data, _verify_license)
    if model_data is not None:
        _install_without_overwrite(model_path, model_data, _verify_model)
    print(f"Installed verified YuNet: {model_path} ({MODEL_SIZE} bytes; {MODEL_SHA256})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Verify local files without network access")
    args = parser.parse_args()
    try:
        install(verify_only=args.verify_only)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"YuNet installation refused/failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
