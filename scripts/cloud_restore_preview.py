"""Restore a pre-migration copy into a previously absent private cloud data root."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess

STAGE = Path('/var/lib/rehabaffect-migration/preseed-20261020')
TARGET = Path('/var/lib/rehabaffect/seewo_demo2')


def require(value, code):
    if not value:
        raise RuntimeError(code)


def safe_path(path):
    require(path.is_absolute() and '..' not in path.parts, 'invalid_path')
    for entry in (*reversed(path.parents), path):
        if not entry.exists() and not entry.is_symlink():
            continue
        info = entry.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'linked_path_refused')
        require(stat.S_ISDIR(info.st_mode) if entry != path else
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'special_path_refused')


def safe_tree(root):
    safe_path(root)
    for path in root.rglob('*'):
        safe_path(path)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def main():
    import pwd

    os.umask(0o077)
    safe_tree(STAGE)
    safe_path(TARGET)
    safe_path(Path('/etc/rehabaffect'))
    if os.getuid() != 0 or TARGET.exists() or not (STAGE / 'media-complete').is_file():
        raise RuntimeError('Incomplete stage or existing target; refused')
    source = STAGE / 'linux/var/lib/rehabaffect/seewo_demo2'
    db = source / 'rehab_affect_demo2.sqlite3'
    counts = {}
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        require(conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'database_integrity_failed')
        require(not conn.execute('PRAGMA foreign_key_check').fetchall(), 'foreign_keys_failed')
        for table in ('platform_accounts', 'video_analysis_tasks'):
            counts[table] = conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
        # Do not replay work already being processed on Windows.
        require(conn.execute("SELECT COUNT(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')").fetchone()[0] == 0, 'active_analysis_refused')
        source_checked = 0
        originals = []
        for row in conn.execute("SELECT file_path,sha256,byte_size FROM video_analysis_tasks WHERE upload_status='completed' AND (raw_media_deleted_at IS NULL OR raw_media_deleted_at='')"):
            safe_path(Path(row['file_path']))
            relative = Path(row['file_path']).relative_to(TARGET / 'video_tasks')
            path = STAGE / 'media' / relative
            require(path.is_file(), 'source_video_missing')
            require(path.stat().st_size == row['byte_size'], 'source_size_mismatch')
            require(digest(path) == row['sha256'], 'source_hash_mismatch')
            originals.append((relative, row['sha256']))
            source_checked += 1
        identity = conn.execute('SELECT database_id FROM demo2_dossier_storage_identity WHERE singleton=1').fetchone()
        require(identity is not None, 'storage_identity_missing')
        marker = (source / 'scoped_dossier_v1/.dossier-owner.json').read_bytes()
        expected_marker = {'version': 1, 'database_id': identity[0],
            'database_path_sha256': hashlib.sha256(str(TARGET / db.name).encode()).hexdigest()}
        expected_bytes = json.dumps(expected_marker, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')
        require(marker == expected_bytes, 'storage_identity_mismatch')
    shutil.copytree(source, TARGET)
    shutil.copytree(STAGE / 'media', TARGET / 'video_tasks', dirs_exist_ok=True)
    for name in ('student_documents', 'scoped_dossier_v1', 'student_summary_v1'):
        (TARGET / name).mkdir(exist_ok=True, mode=0o700)
    uid = pwd.getpwnam('rehabaffect').pw_uid
    gid = pwd.getpwnam('rehabaffect').pw_gid
    for path in (TARGET, *TARGET.rglob('*')):
        require(not path.is_symlink(), 'target_link_refused')
        os.chown(path, uid, gid)
        path.chmod(0o700 if path.is_dir() else 0o600)
    require(digest(TARGET / db.name) == digest(db), 'restored_database_mismatch')
    for relative, expected in originals:
        require(digest(TARGET / 'video_tasks' / relative) == expected, 'restored_video_mismatch')
    env = (STAGE / 'linux/etc/rehabaffect/runtime.env').read_text()
    env = env.replace('REHAB_DEMO2_MEDIA_WORKER=0', 'REHAB_DEMO2_MEDIA_WORKER=1')
    env += ('CLOUD_MIGRATION_APPROVED=yes\n'
            f'CLOUD_MIN_ACCOUNT_COUNT={counts["platform_accounts"]}\n'
            f'CLOUD_MIN_TASK_COUNT={counts["video_analysis_tasks"]}\n'
            'TZ=Asia/Shanghai\nREHAB_FFMPEG=/usr/bin/ffmpeg\nREHAB_FFPROBE=/usr/bin/ffprobe\n')
    config = Path('/etc/rehabaffect/preview.env')
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(env)
    shutil.copyfile('/opt/rehabaffect/deploy/cloud/rehabaffect-preview.service', '/etc/systemd/system/rehabaffect-preview.service')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'start', 'rehabaffect-preview.service'], check=True)
    print(json.dumps({'restored_private_copy': True, 'source_videos_hash_verified': source_checked,
                      'counts': counts, 'public_cutover': False, 'final_delta_required': True}))


if __name__ == '__main__':
    main()
