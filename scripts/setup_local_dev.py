#!/usr/bin/env python3
"""One-command local development environment for RehabAffect.

What this does
--------------
1. Creates ``.venv`` with Python >= 3.10 (3.12 preferred, via ``uv`` when present).
2. Installs ``requirements-local.txt`` into that environment.
3. Downloads static ffmpeg/ffprobe into ``.tools/`` (macOS arm64 has a pinned,
   checksum-verified build; other platforms are detected from PATH/.tools).
4. Downloads the YuNet face model into ``models/`` and verifies its SHA-256.
5. Runs a verification pass and prints what is ready and what is missing.

Usage
-----
    python3 scripts/setup_local_dev.py           # set up, then verify
    python3 scripts/setup_local_dev.py --check   # verify only, never writes
    python3 scripts/setup_local_dev.py --force   # recreate .venv from scratch

The script is idempotent: existing virtualenvs, tools and models are reused and
re-verified. It never downloads from a URL outside the constants below, never
touches ``.runtime/``, and never writes to a path outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-local.txt"
DEFAULT_VENV = ROOT / ".venv"
TOOLS_DIR = ROOT / ".tools"
MODELS_DIR = ROOT / "models"
UV_CACHE = ROOT / ".uv-cache"

MIN_PYTHON = (3, 10)

# ---------------------------------------------------------------------------
# Binary dependencies. Pin exact builds so a fresh machine reproduces the
# environment that was verified locally; hashes are of the extracted binaries.
# ---------------------------------------------------------------------------
FFMPEG_BUILDS = {
    ("darwin", "arm64"): {
        "version": "9.0.2",
        "base": "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2",
        "sha256": {
            "ffmpeg": "2e11c6f90993cdb79fff84d3f90044d28316b310e75b3e030cfc9a54f2c9d384",
            "ffprobe": "2738aa46a7f9acbc8ab09a6715554c90f7de603171ac403726765685df6a0059",
        },
    },
}

FFMPEG_HELP = {
    "darwin": "brew install ffmpeg, or place static binaries in .tools/",
    "linux": "sudo apt-get install -y ffmpeg, or place static binaries in .tools/",
    "win32": "install ffmpeg and set REHAB_FFMPEG/REHAB_FFPROBE, or place ffmpeg.exe/ffprobe.exe in .tools/",
}

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_BYTES = 232589

UV_FALLBACKS = ("/Users/chenjia/.local/bin/uv", str(Path.home() / ".local/bin/uv"))
PYTHON_CANDIDATES = ("python3.12", "python3.11", "python3.10", "python3")


def log(message: str) -> None:
    print(message, flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for candidate in UV_FALLBACKS:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def find_host_python() -> str | None:
    if sys.version_info >= MIN_PYTHON and shutil.which(sys.executable):
        return sys.executable
    for name in PYTHON_CANDIDATES:
        found = shutil.which(name)
        if not found:
            continue
        try:
            result = subprocess.run([found, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            major, minor = (int(part) for part in result.stdout.strip().split("."))
            if (major, minor) >= MIN_PYTHON:
                return found
    return None


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    log("  $ " + " ".join(command))
    subprocess.run(command, check=True, env=env)


def create_venv(venv: Path, *, force: bool) -> None:
    if venv.exists() and force:
        log(f"[venv] removing {venv.relative_to(ROOT)}")
        shutil.rmtree(venv)
    if venv_python(venv).exists():
        log(f"[venv] reuse {venv.relative_to(ROOT)}")
        return
    uv = find_uv()
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(UV_CACHE))
    if uv:
        log(f"[venv] uv venv --python 3.12 -> {venv.relative_to(ROOT)}")
        run([uv, "venv", "--python", "3.12", str(venv)], env=env)
        return
    python = find_host_python()
    if not python:
        raise SystemExit(
            "No Python >= 3.10 found. Install uv (recommended) or Python 3.12, then re-run."
        )
    log(f"[venv] {python} -m venv -> {venv.relative_to(ROOT)}")
    run([python, "-m", "venv", str(venv)])


def install_requirements(venv: Path) -> None:
    uv = find_uv()
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(UV_CACHE))
    python = str(venv_python(venv))
    if uv:
        run([uv, "pip", "install", "--python", python, "-r", str(REQUIREMENTS)], env=env)
    else:
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "rehabaffect-setup/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def resolve_ffmpeg() -> dict[str, str]:
    """Locate existing ffmpeg/ffprobe binaries without downloading anything."""
    found: dict[str, str] = {}
    for name in ("ffmpeg", "ffprobe"):
        configured = os.environ.get(f"REHAB_{name.upper()}", "").strip()
        candidates = [configured, shutil.which(name), str(TOOLS_DIR / name)]
        if os.name == "nt":
            candidates.insert(2, str(TOOLS_DIR / f"{name}.exe"))
        path = next((c for c in candidates if c and Path(c).is_file() and os.access(c, os.X_OK)), None)
        if path:
            found[name] = str(Path(path).resolve())
    return found


def install_ffmpeg() -> dict[str, str]:
    """Return the resolved ffmpeg/ffprobe paths, downloading a pinned build if needed."""
    found = resolve_ffmpeg()
    key = (sys.platform, platform.machine().lower())
    build = FFMPEG_BUILDS.get(key)
    if build and any(name not in found for name in ("ffmpeg", "ffprobe")):
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("ffmpeg", "ffprobe"):
            if name in found:
                continue
            log(f"[tools] downloading pinned {name} {build['version']} for {key[0]}/{key[1]}")
            with tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / f"{name}.zip"
                download(f"{build['base']}/{name}.zip", archive)
                with zipfile.ZipFile(archive) as bundle:
                    member = next((m for m in bundle.namelist() if Path(m).name == name), None)
                    if member is None:
                        raise SystemExit(f"pinned {name} archive does not contain {name}")
                    bundle.extract(member, temporary)
                    source = Path(temporary) / member
                    target = TOOLS_DIR / name
                    shutil.copy2(source, target)
            target.chmod(0o755)
            expected = build["sha256"].get(name)
            if expected and sha256_of(target) != expected:
                raise SystemExit(f"{name} checksum mismatch; refusing to use the download")
            found[name] = str(target.resolve())

    if not all(name in found for name in ("ffmpeg", "ffprobe")):
        log(f"[tools] WARNING: ffmpeg/ffprobe not available. {FFMPEG_HELP.get(sys.platform, '')}")
    return found


def install_model() -> Path:
    target = MODELS_DIR / YUNET_NAME
    if target.is_file() and target.stat().st_size == YUNET_BYTES and sha256_of(target) == YUNET_SHA256:
        log("[model] YuNet present and verified")
        return target
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    log("[model] downloading YuNet face detection model")
    with tempfile.TemporaryDirectory() as temporary:
        download(YUNET_URL, Path(temporary) / YUNET_NAME)
        candidate = Path(temporary) / YUNET_NAME
        if candidate.stat().st_size != YUNET_BYTES or sha256_of(candidate) != YUNET_SHA256:
            raise SystemExit("YuNet model checksum mismatch; refusing to use the download")
        shutil.copy2(candidate, target)
    log("[model] YuNet verified")
    return target


def display(path: Path) -> str:
    """Render a path relative to the repository when possible."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def verify(venv: Path, ffmpeg: dict[str, str], model: Path) -> bool:
    checks: list[tuple[str, bool, str]] = []
    python = venv_python(venv)
    checks.append(("venv", python.exists(), display(venv) if venv.exists() else "missing"))
    if python.exists():
        probe = (
            "import sys;"
            "import numpy, cv2, cryptography, PIL, pytest, requests, psutil, reportlab;"
            "print(f'{sys.version.split()[0]} numpy={numpy.__version__} cv2={cv2.__version__} "
            "cryptography={cryptography.__version__} PIL={PIL.__version__} pytest={pytest.__version__}')"
        )
        try:
            result = subprocess.run([str(python), "-c", probe], capture_output=True, text=True, timeout=120)
        except subprocess.SubprocessError as error:  # pragma: no cover - defensive
            checks.append(("python packages", False, str(error)))
            result = None
        if result is not None:
            if result.returncode == 0:
                checks.append(("python packages", True, result.stdout.strip()))
            else:
                last = (result.stderr.strip().splitlines() or ["import failed"])[-1]
                checks.append(("python packages", False, last))
            if result.returncode == 0:
                yunet = subprocess.run([str(python), "-c", "import cv2; print(hasattr(cv2, 'FaceDetectorYN'))"],
                                       capture_output=True, text=True, timeout=60)
                checks.append(("cv2.FaceDetectorYN", yunet.stdout.strip() == "True", yunet.stdout.strip()))
    for name in ("ffmpeg", "ffprobe"):
        path = ffmpeg.get(name)
        if not path:
            checks.append((name, False, "missing"))
            continue
        try:
            result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:  # pragma: no cover - defensive
            checks.append((name, False, str(error)))
            continue
        first = (result.stdout.splitlines() or [result.stderr.strip()])[0]
        checks.append((name, result.returncode == 0, first))
    ok_model = model.is_file() and model.stat().st_size == YUNET_BYTES and sha256_of(model) == YUNET_SHA256
    checks.append(("YuNet model", ok_model,
                   f"{display(model)} ({model.stat().st_size} bytes)" if model.is_file() else "missing"))

    log("")
    log("Verification")
    log("-" * 78)
    for name, passed, detail in checks:
        log(f"  {'PASS' if passed else 'FAIL':4}  {name:18} {detail[:120]}")
    log("-" * 78)
    media_ok = all(name in ffmpeg for name in ("ffmpeg", "ffprobe")) and ok_model
    return all(passed for _, passed, _ in checks) and media_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the current environment only; write nothing")
    parser.add_argument("--force", action="store_true", help="recreate the virtual environment")
    parser.add_argument("--venv-dir", type=Path, default=DEFAULT_VENV, help="virtual environment directory")
    parser.add_argument("--skip-ffmpeg", action="store_true", help="do not download ffmpeg/ffprobe")
    parser.add_argument("--skip-model", action="store_true", help="do not download the YuNet model")
    args = parser.parse_args(argv)

    venv = args.venv_dir if args.venv_dir.is_absolute() else (ROOT / args.venv_dir)
    log(f"RehabAffect local development setup ({sys.platform}/{platform.machine()})")
    log(f"repository: {ROOT}")
    log("")

    if not args.check:
        create_venv(venv, force=args.force)
        install_requirements(venv)
        ffmpeg = resolve_ffmpeg() if args.skip_ffmpeg else install_ffmpeg()
        model = MODELS_DIR / YUNET_NAME if args.skip_model else install_model()
    else:
        ffmpeg = resolve_ffmpeg()
        model = MODELS_DIR / YUNET_NAME

    ok = verify(venv, ffmpeg, model)
    log("")
    if ok:
        log("Environment ready.")
        log("  start the pilot platform:  ./scripts/run_local_demo.sh")
        log("  run the test suite:        PYTHONPATH=src .venv/bin/python -m pytest -q tests")
        return 0
    log("Environment incomplete; fix the FAIL lines above and re-run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
