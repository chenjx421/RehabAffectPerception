"""Provision the existing approved credential without writing a plaintext local key."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from cloud_ssh_operator import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rehab_affect.demo2_dossier_vault import DossierVault


def main():
    vault_dir = ROOT / ".runtime/demo3_gateway"
    key = DossierVault(vault_dir.resolve()).open((vault_dir / "api_key.enc").read_bytes()).decode()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,4096}", key):
        raise ValueError("Unexpected credential format")
    # Only hashes are used here; the worker independently checks the live source.
    manifest = json.loads((ROOT / ".runtime/cloud_deploy_20261020/real_sample_test/cloud_samples.private.json").read_text(encoding="utf-8"))
    hashes = [sample["sha256"] for sample in manifest["samples"]]
    if len(hashes) != 4 or any(not re.fullmatch("[a-f0-9]{64}", value) for value in hashes):
        raise ValueError("Four authorized sample hashes required")
    content = (
        "REHAB_OBSERVATION_API_BASE=https://model.kimitk.top/v1\n"
        "REHAB_OBSERVATION_MODEL=glm-5.3-flash\n"
        "REHAB_OBSERVATION_API_KEY=" + key + "\n"
        "REHAB_OBSERVATION_ALLOWED_SHA256=" + ",".join(hashes) + "\n"
        "REHAB_OBSERVATION_AUTO_AFTER=" + str(int(datetime.now(timezone.utc).timestamp())) + "\n"
        "REHAB_DEMO2_DECODER_THREADS=2\n"
    ).encode()
    transport = connect()
    try:
        channel = transport.open_session(timeout=20)
        # O_EXCL leaves any pre-existing deployment configuration untouched.
        command = """sudo -n /opt/rehabaffect/.venv/bin/python -c 'import os,sys; p="/etc/rehabaffect/observations.env"; data=sys.stdin.buffer.read(16385); assert 0<len(data)<=16384; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); f=os.fdopen(fd,"wb"); f.write(data); f.flush(); os.fsync(f.fileno()); f.close()'"""
        channel.exec_command(command)
        channel.sendall(content)
        channel.shutdown_write()
        if channel.recv_exit_status() != 0:
            raise RuntimeError("Private configuration not installed")
        print(json.dumps({"installed": True, "authorized_sample_count": 4, "credential_printed": False}))
    finally:
        transport.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"installed": False, "error": "private_provisioning_failed"}))
        raise SystemExit(1)
