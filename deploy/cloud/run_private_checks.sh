#!/usr/bin/env bash
set -euo pipefail
cd /opt/rehabaffect
export PYTHONPATH=/opt/rehabaffect:/opt/rehabaffect/src
export PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_demo2_media_store.py tests/test_demo2_media_worker.py \
  tests/test_demo2_media_api.py tests/test_demo2_portal_api.py \
  tests/test_demo2_identity_api.py tests/test_demo2_course_analysis.py \
  tests/test_demo2_manager_gateway.py \
  --basetemp="$(mktemp -d /var/lib/rehabaffect/cloud-tests-XXXXXXXX)"
