"""Package reviewed application files, excluding all credentials and school data."""
from pathlib import Path
import argparse
import hashlib
import json
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    args = parser.parse_args()
    files = {}
    for folder, suffixes in (("src", {".py"}), ("configs", {".json"}),
                             ("tests", {".py"}), ("deploy/cloud", {".service", ".txt", ".sh"})):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files[path.relative_to(ROOT).as_posix()] = path
    for path in (ROOT / "scripts").glob("cloud_*.py"):
        if path.name not in {"cloud_ssh_operator.py", "cloud_prepare_snapshot.py"}:
            files[path.relative_to(ROOT).as_posix()] = path
    files["scripts/prepare_upload_video.py"] = ROOT / "scripts/prepare_upload_video.py"
    for name in ("pyproject.toml", "models/face_detection_yunet_2023mar.onnx", "models/LICENSE.yunet"):
        files[name] = ROOT / name
    if args.overrides:
        for name in ("demo2_course_analysis.py", "demo2_course_page.py"):
            path = args.overrides / name
            if not path.is_file():
                raise ValueError("Both reviewed cloud-only overrides are required")
            files["src/rehab_affect/" + name] = path
            files[".runtime/cloud_release_overrides/" + name] = path
        for name in ("student_record_store.py", "scenario_lab_server.py", "demo2_portal.py",
                     "demo2_media_analysis.py", "demo2_observation_model.py",
                     "demo2_observation_store.py", "demo2_dossier.py", "demo2_identity.py"):
            path = args.overrides / name
            if path.is_file():
                files["src/rehab_affect/" + name] = path
                files[".runtime/cloud_release_overrides/" + name] = path
        for test in args.overrides.glob("test_*.py"):
            files[".runtime/cloud_release_overrides/" + test.name] = test
    args.output.parent.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with tarfile.open(args.output, "w:gz") as archive:
        for name, path in sorted(files.items()):
            if path.is_symlink():
                raise ValueError("Symlink refused")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            archive.add(path, arcname=name, recursive=False)
    manifest = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(files), "bytes": args.output.stat().st_size,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
