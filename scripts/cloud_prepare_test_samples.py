"""Verify and copy authorized samples into the private cloud acceptance directory."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import shutil
import sqlite3

STAGING = Path('/home/ubuntu/rehab-deploy/real-samples')
DEST = Path('/var/lib/rehabaffect/acceptance-private/samples')
DB = Path('/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    os.umask(0o077)
    if os.getuid() != 0 or DEST.exists():
        raise RuntimeError('Fresh private sample destination required')
    from cloud_restore_preview import safe_tree, safe_path, require
    safe_tree(STAGING)
    safe_path(DEST)
    manifest = json.loads((STAGING / 'samples.private.json').read_text())
    require(len(manifest['samples']) == 4, 'four_samples_required')
    sources = []
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as conn:
        for item in manifest['samples']:
            require(item['sample_id'] in {'Sample01', 'Sample02', 'Sample03', 'Sample04'}, 'sample_id_invalid')
            source = STAGING / (item['sample_id'] + '.mp4')
            if not source.exists():
                row = conn.execute("SELECT file_path FROM video_analysis_tasks WHERE sha256=? AND upload_status='completed'", (item['sha256'],)).fetchone()
                require(row is not None, 'sample_source_missing')
                source = Path(row[0])
                require(source.is_relative_to(DB.parent / 'video_tasks/uploads'), 'source_outside_controlled_root')
            safe_path(source)
            require(source.is_file() and source.stat().st_size == item['size_bytes'], 'sample_size_mismatch')
            require(digest(source) == item['sha256'], 'sample_hash_mismatch')
            sources.append((source, item))
    DEST.mkdir(mode=0o700)
    for source, item in sources:
        target = DEST / (item['sample_id'] + '.mp4')
        shutil.copyfile(source, target)
        require(digest(target) == item['sha256'], 'copied_sample_hash_mismatch')
    config = DEST / 'samples.private.json'
    config.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    user = pwd.getpwnam('rehabaffect')
    for path in (DEST, *DEST.iterdir()):
        os.chown(path, user.pw_uid, user.pw_gid)
        path.chmod(0o700 if path.is_dir() else 0o600)
    print(json.dumps({'samples_staged': 4, 'source_and_copy_hashes_verified': True,
                      'third_party_inference_used': False}))


if __name__ == '__main__':
    main()
