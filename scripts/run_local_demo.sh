#!/usr/bin/env bash
# Start the Demo2 classroom platform locally with a disposable dev database.
#
# Usage:
#   ./scripts/run_local_demo.sh            # port 8791
#   PORT=8800 ./scripts/run_local_demo.sh
#
# State lives under .runtime/local_dev/ (gitignored) so a local experiment never
# mixes with outputs/seewo_demo2/ or with any deployment data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8791}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "No virtualenv found. Run: python3 scripts/setup_local_dev.py" >&2
  exit 1
fi

export PATH="$ROOT/.tools:$PATH"
export REHAB_DEMO2_DB_PATH="${REHAB_DEMO2_DB_PATH:-$ROOT/.runtime/local_dev/db.sqlite3}"
export REHAB_DEMO2_UPLOAD_DIR="${REHAB_DEMO2_UPLOAD_DIR:-$ROOT/.runtime/local_dev/student_documents}"
export REHAB_DEMO2_MEDIA_WORKER="${REHAB_DEMO2_MEDIA_WORKER:-1}"

mkdir -p "$(dirname "$REHAB_DEMO2_DB_PATH")" "$REHAB_DEMO2_UPLOAD_DIR"

# IEP/dossier storage needs an explicit Fernet key outside Windows (the DPAPI
# auto-key path is Windows-only). Generate one dev key and keep it local.
KEY_FILE="$ROOT/.runtime/local_dev/dossier.key"
if [[ -z "${REHAB_DEMO2_DOSSIER_KEY:-}" ]]; then
  if [[ ! -s "$KEY_FILE" ]]; then
    (umask 077; "$PYTHON" -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())' > "$KEY_FILE")
  fi
  export REHAB_DEMO2_DOSSIER_KEY="$(cat "$KEY_FILE")"
fi

echo "RehabAffect local platform"
echo "  url:  http://127.0.0.1:$PORT/demo2/login"
echo "  db:   $REHAB_DEMO2_DB_PATH"
echo "  docs: $REHAB_DEMO2_UPLOAD_DIR"
echo "  key:  $KEY_FILE"
echo

exec "$PYTHON" -m src.rehab_affect.scenario_lab_server --host 127.0.0.1 --port "$PORT" --policy rule
