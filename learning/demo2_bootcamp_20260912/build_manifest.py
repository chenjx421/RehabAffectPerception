"""Capture code locations without importing business stores or loading data."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FILES = [
    'demo2_face_detection.py', 'demo2_roi_tracking.py', 'demo2_media_analysis.py',
    'demo2_media_worker.py', 'demo2_identity.py', 'demo2_identity_store.py',
    'demo2_dossier.py', 'demo2_dossier_store.py', 'demo2_dossier_vault.py',
    'demo2_frame_preview.py', 'demo2_media_cache.py', 'demo2_entry.py',
    'demo2_portal.py', 'demo2_channel_admin_store.py', 'student_record_store.py',
    'scenario_lab_server.py', 'seewo_student_demo.py', 'fusion.py', 'smoothing.py',
    'learned_policy.py', 'train_policy.py',
]
result = []
for name in FILES:
    path = ROOT / 'src/rehab_affect' / name
    data = path.read_bytes()
    tree = ast.parse(data.decode('utf-8-sig'))
    result.append({'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
                   'symbols': [{'name': node.name, 'line': node.lineno, 'kind': type(node).__name__}
                               for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))]})
(HERE / 'source_manifest.json').write_text(json.dumps({'date': '2026-09-12', 'files': result}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Captured {len(result)} source files; no database or model deserialization.')
