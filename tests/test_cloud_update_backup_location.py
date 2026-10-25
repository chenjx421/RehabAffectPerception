"""Deployment backups must not inherit the app data directory's ownership."""
from pathlib import Path
import importlib.util


def test_backup_root_has_no_application_owned_ancestor():
    source = Path(__file__).resolve().parents[1] / 'scripts/cloud_update_v10.py'
    spec = importlib.util.spec_from_file_location('_backup_location', source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    assert helper.BACKUPS == Path('/var/lib/rehabaffect-cloud-backups')
    assert Path('/var/lib/rehabaffect') not in helper.BACKUPS.parents
    assert helper.DB == Path('/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3')
