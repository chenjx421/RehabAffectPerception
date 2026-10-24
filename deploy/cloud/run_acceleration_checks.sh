#!/usr/bin/env bash
set -euo pipefail
cd /opt/rehabaffect
export PYTHONPATH=/opt/rehabaffect:/opt/rehabaffect/src:/opt/rehabaffect/tests
export PYTHONDONTWRITEBYTECODE=1
export REHAB_FFMPEG=/usr/bin/ffmpeg
export REHAB_FFPROBE=/usr/bin/ffprobe
export REHAB_CLOUD_REFERENCE_SOURCE=/var/lib/rehabaffect/cloud-reference-before-acceleration
.venv/bin/python -m pytest -q -rs -p no:cacheprovider \
  tests/test_cloud_upload_acceleration.py \
  .runtime/cloud_release_overrides/test_demo2_course_analysis_cloud.py \
  tests/test_cloud_browser_acceptance.py \
  tests/test_cloud_real_browser_acceptance.py \
  tests/test_cloud_e2e_acceptance.py \
  --basetemp="$(mktemp -d /var/lib/rehabaffect/acceleration-tests-XXXXXXXX)"
