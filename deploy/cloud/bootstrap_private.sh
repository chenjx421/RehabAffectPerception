#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" != 0 ]; then
    echo "Run as root" >&2
    exit 1
fi
apt-get update -q
apt-get install -y --no-install-recommends python3-venv python3-pip ffmpeg ca-certificates curl rsync
if ! id rehabaffect >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/rehabaffect --shell /usr/sbin/nologin rehabaffect
fi
if ! id rehabaffect-gateway >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin rehabaffect-gateway
fi
install -d -m 0755 /opt/rehabaffect
install -d -m 0700 -o rehabaffect -g rehabaffect /var/lib/rehabaffect
install -d -m 0750 -o root -g rehabaffect-gateway /etc/rehabaffect
install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/rehab-deploy
python3 -m venv /opt/rehabaffect/.venv
echo "Private runtime prerequisites installed. No public listener or application started."
