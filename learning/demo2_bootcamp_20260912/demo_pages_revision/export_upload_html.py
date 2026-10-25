"""Export existing Demo2 HTML with a fictional account; no DB or server access."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from src.rehab_affect.demo2_portal import render_demo2_upload_html

account = {"account_id": "teaching-account", "username": "teaching-account", "login_alias": "教学演示账号", "role": "school_uploader", "bound_channel_id": "channel_1", "course_upload_limit": 5, "status": "active"}
target = Path(__file__).parent / "assets" / "upload.html"
target.write_text(render_demo2_upload_html(account), encoding="utf-8")
print("Exported unchanged upload HTML; fictional account only; no database access.")
