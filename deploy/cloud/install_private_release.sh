#!/usr/bin/env bash
set -euo pipefail
archive="$1"
expected="$2"
actual="$(sha256sum "$archive" | cut -d ' ' -f 1)"
test "$actual" = "$expected"
test -d /opt/rehabaffect/.venv
tar -xzf "$archive" --no-same-owner -C /opt/rehabaffect
chmod -R go-w /opt/rehabaffect/src /opt/rehabaffect/scripts /opt/rehabaffect/tests
/opt/rehabaffect/.venv/bin/pip install --disable-pip-version-check -r /opt/rehabaffect/deploy/cloud/requirements.txt pytest
echo "Release installed privately; data and service activation are separate gates."
