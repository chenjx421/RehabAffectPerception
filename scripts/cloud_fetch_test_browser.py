"""Fetch only official test-browser software; never handles application data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import stat
import urllib.request
import zipfile

URL = 'https://storage.googleapis.com/chrome-for-testing-public/156.0.8078.4/linux64/chrome-headless-shell-linux64.zip'
SIZE = 125797539
MD5 = '743dac7baf99eaa72e221335ea966f07'
ROOT = Path('/opt/rehabaffect-browser/official-cft-156')
PART = 2 * 1024 * 1024


def fetch(index):
    start, end = index * PART, min(SIZE, (index + 1) * PART) - 1
    target = ROOT / f'part-{index:03d}'
    for attempt in range(3):
        request = urllib.request.Request(URL, headers={'Range': f'bytes={start}-{end}'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{SIZE}':
                    raise RuntimeError('Unexpected official range response')
                data = response.read(PART + 1)
            if len(data) != end - start + 1:
                raise RuntimeError('Incomplete browser range')
            target.write_bytes(data)
            return target
        except Exception:
            if attempt == 2:
                raise


def main():
    if ROOT.exists():
        raise RuntimeError('Fresh software staging directory required')
    ROOT.mkdir(mode=0o755)
    paths = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for number, path in enumerate(pool.map(fetch, range((SIZE + PART - 1) // PART)), 1):
            paths.append(path)
            print('Official browser parts verified:', number, flush=True)
    archive = ROOT / 'official-browser.zip'
    with archive.open('wb') as output:
        for path in paths:
            output.write(path.read_bytes())
    if archive.stat().st_size != SIZE or hashlib.md5(archive.read_bytes()).hexdigest() != MD5:
        raise RuntimeError('Official browser checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            name = Path(entry.filename)
            if name.is_absolute() or '..' in name.parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise RuntimeError('Unsafe browser archive entry')
        source.extractall(ROOT)
        for entry in source.infolist():
            target = ROOT / entry.filename
            target.chmod(0o755 if entry.is_dir() or entry.external_attr >> 16 & 0o111 else 0o644)
    print(json.dumps({'official_download_verified': True, 'bytes': SIZE,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
