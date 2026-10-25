#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends fonts-noto-cjk
/opt/rehabaffect/.venv/bin/python -m playwright install-deps chromium
install -d -m 0755 /opt/rehabaffect-browser
PLAYWRIGHT_BROWSERS_PATH=/opt/rehabaffect-browser /opt/rehabaffect/.venv/bin/python -m playwright install chromium --only-shell
chmod -R a+rX,go-w /opt/rehabaffect-browser
