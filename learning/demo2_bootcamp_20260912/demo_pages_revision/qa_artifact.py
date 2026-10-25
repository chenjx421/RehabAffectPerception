"""Check screenshot revision coverage and preservation of unrelated source slides."""
import hashlib
import json
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).parent
manifest=json.loads((HERE/'SCREENSHOT_MANIFEST.json').read_text(encoding='utf-8'))
src=Path(manifest['sourceDeck'])
dst=Path(manifest['outputDeck'])
ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
def texts(z,n):
    root=ET.fromstring(z.read(f'ppt/slides/slide{n}.xml'))
    return [t.text or '' for t in root.findall('.//a:t',ns) if not re.fullmatch(r'\d{2}',t.text or '')]

assert hashlib.sha256(src.read_bytes()).hexdigest()==manifest['sourceSha256']
with zipfile.ZipFile(src) as a,zipfile.ZipFile(dst) as b:
    slides=[p for p in b.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',p)]
    assert len(slides)==42
    assert len(manifest['assets'])==10
    preserved=[]
    for row in manifest['pageMap']:
        if row['originalPage'] and row['originalPage'] not in (18,29,30,31):
            assert texts(a,row['originalPage'])==texts(b,row['page']),row
            preserved.append(row['page'])
    for page in manifest['screenshotPages']:
        root=ET.fromstring(b.read(f'ppt/slides/slide{page}.xml'))
        assert root.findall('.//p:pic',ns),page
        assert any('源码' in t for t in texts(b,page)),page
    count=sum(len(ET.fromstring(b.read(p)).findall('.//p:pic',ns)) for p in slides)
report={'slide_count':len(slides),'demo_screenshot_pages':manifest['screenshotPages'],'embedded_image_objects':count,'unrelated_slide_content_preserved':preserved,'source_deck_unchanged':True,'final_bytes':dst.stat().st_size,'final_sha256':hashlib.sha256(dst.read_bytes()).hexdigest()}
(HERE/'qa'/'content_preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
