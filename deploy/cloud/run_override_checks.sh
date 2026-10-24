#!/usr/bin/env bash
set -euo pipefail
cd /opt/rehabaffect
export PYTHONPATH=/opt/rehabaffect:/opt/rehabaffect/src:/opt/rehabaffect/tests
export PYTHONDONTWRITEBYTECODE=1
export REHAB_FFMPEG=/usr/bin/ffmpeg
export REHAB_FFPROBE=/usr/bin/ffprobe
.venv/bin/python -m pytest -q -rs -p no:cacheprovider \
  .runtime/cloud_release_overrides/test_demo2_course_analysis_cloud.py \
  tests/test_demo2_face_detection.py::test_synthetic_blank_image_real_yunet_has_no_face_candidates \
  tests/test_cloud_e2e_acceptance.py \
  tests/test_cloud_restore_preview.py \
  --basetemp="$(mktemp -d /var/lib/rehabaffect/cloud-override-tests-XXXXXXXX)"
