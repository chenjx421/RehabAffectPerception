#!/usr/bin/env bash
set -euo pipefail
candidate="$1"
case "$candidate" in /opt/rehabaffect-candidate-*) ;; *) exit 2 ;; esac
cd "$candidate"
export PYTHONPATH="$candidate:$candidate/src:$candidate/tests"
export PYTHONDONTWRITEBYTECODE=1
/opt/rehabaffect/.venv/bin/python -m pytest -q -rs -p no:cacheprovider \
  tests/test_demo2_observation_model.py \
  tests/test_cloud_observation_worker.py \
  tests/test_cloud_observation_frames.py \
  .runtime/cloud_release_overrides/test_demo2_observation_store.py \
  --basetemp="$(mktemp -d /var/lib/rehabaffect/observation-batch-checks-XXXXXXXX)"
