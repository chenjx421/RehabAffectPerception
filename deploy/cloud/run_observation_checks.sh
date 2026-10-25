#!/usr/bin/env bash
set -euo pipefail
candidate="$1"
case "$candidate" in /opt/rehabaffect-candidate-*) ;; *) exit 2 ;; esac
cd "$candidate"
export PYTHONPATH="$candidate:$candidate/src:$candidate/tests"
export PYTHONDONTWRITEBYTECODE=1
export REHAB_FFMPEG=/usr/bin/ffmpeg
export REHAB_FFPROBE=/usr/bin/ffprobe
export PATH="/opt/rehabaffect/.venv/lib/python3.12/site-packages/playwright/driver:$PATH"
export REHAB_CLOUD_REFERENCE_SOURCE=/var/lib/rehabaffect/cloud-reference-before-acceleration
/opt/rehabaffect/.venv/bin/python -m pytest -q -rs -p no:cacheprovider \
  tests/test_cloud_observation_frames.py \
  tests/test_cloud_observation_worker.py \
  tests/test_demo2_observation_model.py \
  tests/test_demo2_observation_api.py \
  tests/test_cloud_processing_acceleration.py \
  .runtime/cloud_release_overrides/test_demo2_observation_store.py \
  .runtime/cloud_release_overrides/test_demo2_course_observation_page.py \
  .runtime/cloud_release_overrides/test_demo2_observation_ui_extensions.py \
  .runtime/cloud_release_overrides/test_demo2_course_analysis_cloud.py \
  tests/test_demo2_media_store.py tests/test_demo2_media_worker.py \
  tests/test_demo2_media_api.py tests/test_demo2_portal_api.py \
  tests/test_demo2_identity_api.py tests/test_demo2_course_analysis.py \
  tests/test_demo2_manager_gateway.py \
  --basetemp="$(mktemp -d /var/lib/rehabaffect/observation-checks-XXXXXXXX)"
