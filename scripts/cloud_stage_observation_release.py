"""Stage a verified source archive for acceptance without touching the live service."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    if (args.archive.parent != Path("/home/ubuntu/rehab-deploy") or args.archive.is_symlink()
            or args.stage.parent != Path("/opt") or not args.stage.name.startswith("rehabaffect-candidate-")
            or args.stage.exists()):
        raise ValueError("Unexpected staging path")
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != args.sha256:
        raise ValueError("Release checksum mismatch")
    with tarfile.open(args.archive, "r:gz") as archive:
        members = archive.getmembers()
        for item in members:
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts or not item.isfile():
                raise ValueError("Unexpected release entry")
            if item.size > 10 * 1024 * 1024:
                raise ValueError("Release entry too large")
        args.stage.mkdir(mode=0o755)
        archive.extractall(args.stage, filter="data")
    for path in args.stage.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    print("Source staged; live service unchanged.")


if __name__ == "__main__":
    main()
