"""Deployment transport pinned to the host verified in Tencent's console."""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
from pathlib import Path
import socket
import shlex
import sys
import tarfile
import time

import paramiko

HOST = "YOUR_SERVER_IP"
HOST_KEY = "SHA256:bmsTXtCIUMC+E09eymKVsTdxMXld4Nj0YwI+JtMjP90"
ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / ".runtime/cloud_deploy_20261020/rehab_cloud_ed25519"


def connect():
    sock = socket.create_connection((HOST, 22), timeout=20)
    transport = paramiko.Transport(sock)
    transport.start_client(timeout=20)
    key = transport.get_remote_server_key()
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    if key.get_name() != "ssh-ed25519" or fingerprint != HOST_KEY:
        transport.close()
        raise RuntimeError("Trusted host identity mismatch; no authentication sent")
    transport.auth_publickey("ubuntu", paramiko.Ed25519Key.from_private_key_file(str(KEY)))
    transport.set_keepalive(20)
    return transport


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--command")
    group.add_argument("--upload", nargs=2, metavar=("LOCAL", "REMOTE"))
    group.add_argument("--download", nargs=2, metavar=("REMOTE", "LOCAL"))
    group.add_argument("--stream-tree", nargs=2, metavar=("LOCAL_DIRECTORY", "REMOTE_DIRECTORY"))
    args = parser.parse_args()
    transport = connect()
    try:
        if args.command:
            channel = transport.open_session(timeout=20)
            channel.exec_command(args.command)
            while True:
                if channel.recv_ready():
                    sys.stdout.buffer.write(channel.recv(65536))
                    sys.stdout.buffer.flush()
                if channel.recv_stderr_ready():
                    sys.stderr.buffer.write(channel.recv_stderr(65536))
                    sys.stderr.buffer.flush()
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    return channel.recv_exit_status()
                time.sleep(0.05)
        if args.stream_tree:
            source = Path(args.stream_tree[0]).resolve(strict=True)
            destination = args.stream_tree[1]
            if not source.is_dir() or not destination.startswith("/var/lib/rehabaffect-migration/") or ".." in destination.split("/"):
                raise ValueError("Private migration staging directory required")
            channel = transport.open_session(window_size=8 * 1024 * 1024, timeout=30)
            channel.exec_command("sudo -n tar -xf - --no-same-owner -C " + shlex.quote(destination))
            class Sink:
                def write(self, data):
                    channel.sendall(data)
                    return len(data)
            count = total = 0
            start = last = time.monotonic()
            with tarfile.open(fileobj=Sink(), mode="w|", bufsize=1024 * 1024) as archive:
                for path in source.rglob("*"):
                    info = path.lstat()
                    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise ValueError("Link refused during private migration")
                    if path.name == ".worker.lock":
                        continue
                    if path.is_dir():
                        continue
                    before = (info.st_size, info.st_mtime_ns)
                    member = archive.gettarinfo(str(path), path.relative_to(source).as_posix())
                    member.mode = 0o600
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(member, stream)
                    after = path.stat()
                    if before != (after.st_size, after.st_mtime_ns):
                        raise RuntimeError("Source changed while streaming; staging is incomplete")
                    count += 1
                    total += info.st_size
                    if time.monotonic() - last >= 10:
                        print("Private staged files:", count, "MiB:", round(total / 1048576, 1), flush=True)
                        last = time.monotonic()
            channel.shutdown_write()
            code = channel.recv_exit_status()
            if code:
                raise RuntimeError("Remote staging extraction failed")
            print("Private staging complete:", count, "files", total, "bytes", round(time.monotonic() - start, 1), "seconds")
            return 0
        with paramiko.SFTPClient.from_transport(transport) as sftp:
            if args.upload:
                local, remote = args.upload
                sftp.put(local, remote)
                print("Uploaded bytes:", os.path.getsize(local))
            else:
                remote, local = args.download
                sftp.get(remote, local)
                print("Downloaded bytes:", os.path.getsize(local))
        return 0
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
