"""Transfer explicitly provided sample media to the verified private cloud host."""
from pathlib import Path
import hashlib
import json
import time

from cloud_ssh_operator import connect, ROOT
import paramiko

MANIFEST = ROOT / '.runtime/cloud_deploy_20261020/real_sample_test/private_media_hash_matches.json'
ALLOWED = Path('C:/Path/To/Developer/Desktop/3\u540d\u4e0d\u540c\u969c\u788d\u7c7b\u578b\u5b66\u751f\u57fa\u7840\u6570\u636e').resolve()
REMOTE = '/home/ubuntu/rehab-deploy/real-samples'


def main():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    source_root = Path(data['source_root']).resolve(strict=True)
    if source_root != ALLOWED:
        raise RuntimeError('Authorized sample source mismatch')
    transport = connect()
    try:
        with paramiko.SFTPClient.from_transport(transport) as client:
            try:
                client.mkdir(REMOTE, 0o700)
            except OSError:
                if client.stat(REMOTE).st_mode & 0o077:
                    raise RuntimeError('Sample staging is not private')
            public_rows = []
            for row in data['samples']:
                sample = row['sample_id']
                if sample not in {'Sample01', 'Sample02', 'Sample03', 'Sample04'}:
                    raise RuntimeError('Unknown sample')
                source = (source_root / row['relative_source_path']).resolve(strict=True)
                if not source.is_relative_to(source_root) or source.is_symlink():
                    raise RuntimeError('Sample outside authorized source')
                hash_value = hashlib.sha256()
                with source.open('rb') as stream:
                    for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                        hash_value.update(block)
                if hash_value.hexdigest() != row['sha256'] or source.stat().st_size != row['size_bytes']:
                    raise RuntimeError('Sample changed')
                public_rows.append({key: row[key] for key in ('sample_id', 'size_bytes', 'sha256')} |
                                   {'relative_path': sample + '.mp4'})
                if row['completed_task_matches']:
                    print(sample, 'already present in migrated database; no duplicate WAN copy', flush=True)
                    continue
                before = (source.stat().st_size, source.stat().st_mtime_ns)
                previous = time.monotonic()
                def progress(done, total):
                    nonlocal previous
                    if time.monotonic() - previous >= 15:
                        print(sample, 'staged_MiB', round(done / 1048576, 1), flush=True)
                        previous = time.monotonic()
                client.put(str(source), REMOTE + '/' + sample + '.mp4', callback=progress)
                client.chmod(REMOTE + '/' + sample + '.mp4', 0o600)
                if before != (source.stat().st_size, source.stat().st_mtime_ns):
                    raise RuntimeError('Sample changed while transferring')
                print(sample, 'private transfer complete', flush=True)
            manifest = json.dumps({'schema_version': 1, 'samples': public_rows}, indent=2).encode()
            with client.open(REMOTE + '/samples.private.json', 'wb') as stream:
                stream.write(manifest)
            client.chmod(REMOTE + '/samples.private.json', 0o600)
    finally:
        transport.close()


if __name__ == '__main__':
    main()
