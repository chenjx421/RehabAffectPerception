"""Package only masked screenshots and anonymous acceptance counts."""
import argparse
import os
from pathlib import Path
import pwd
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unmasked-internal", action="store_true")
    args = parser.parse_args()
    root = Path("/var/lib/rehabaffect/acceptance-private")
    if args.unmasked_internal:
        root = root / 'observation-effectiveness'
    if args.output.parent != Path("/home/ubuntu/rehab-deploy") or args.output.exists():
        raise ValueError("New private deployment artifact required")
    entries = []
    for directory in args.directory:
        if directory.parent != root or directory.is_symlink() or not directory.is_dir():
            raise ValueError("Unexpected evidence directory")
        for path in directory.iterdir():
            allowed = (path.name.startswith('effect-contact-') and path.suffix == '.png') if args.unmasked_internal else (
                path.name == "acceptance.json" or (path.name.startswith("classroom-") and path.suffix == ".png"))
            if allowed:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("Unexpected evidence file")
                entries.append((path, directory.name + "/" + path.name))
    if not entries:
        raise ValueError("No accepted artifacts")
    os.umask(0o077)
    with tarfile.open(args.output, "x:gz") as archive:
        for path, name in entries:
            archive.add(path, arcname=name, recursive=False)
    owner = pwd.getpwnam("ubuntu")
    os.chown(args.output, owner.pw_uid, owner.pw_gid)
    print("Private internal review images prepared; not for public distribution." if args.unmasked_internal else "Masked screenshot artifact prepared.")


if __name__ == "__main__":
    main()
