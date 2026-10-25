"""Package only the three reviewed source overrides and acceptance scripts."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'.runtime/cloud_student_release'
NAMES = ('demo2_course_analysis.py','demo2_course_page.py','demo2_observation_store.py')


def main():
    files = [(SOURCE/name,'src/rehab_affect/'+name) for name in NAMES]
    files += [(ROOT/'scripts'/name,'scripts/'+name) for name in
        ('cloud_student_insights_acceptance.py','cloud_e2e_acceptance.py','cloud_update_v10.py')]
    with tarfile.open(SOURCE/'source.tar.gz','w:gz') as archive:
        for path,relative in files:
            raw = path.read_bytes()
            compile(raw,str(path),'exec')
            archive.add(path,arcname=relative,recursive=False)
    print(hashlib.sha256((SOURCE/'source.tar.gz').read_bytes()).hexdigest())


if __name__=='__main__':
    main()
