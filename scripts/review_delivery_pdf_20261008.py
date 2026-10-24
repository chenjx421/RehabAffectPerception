"""Produce contact sheets and check the complete PDF's text/page count."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'output/playwright/delivery_20261008'
summary=json.loads((folder/'pdf_build_summary.json').read_text(encoding='utf8'))
reader=PdfReader(summary['pdf'])
assert len(reader.pages)==summary['pages']
images=sorted(folder.glob('review-*.jpg'))
assert len(images)==len(reader.pages),(len(images),len(reader.pages))
for page in reader.pages:
    assert len(page.extract_text().strip())>80
for start in range(0,len(images),9):
    sheet=Image.new('RGB',(1650,1260),'#e5eaf0');draw=ImageDraw.Draw(sheet)
    for index,file in enumerate(images[start:start+9]):
        im=Image.open(file);im.thumbnail((540,385))
        x=(index%3)*550+5;y=(index//3)*420+25
        sheet.paste(im,(x,y));draw.text((x,y-17),str(start+index+1),fill='black')
    sheet.save(folder/f'contact-{start//9+1}.jpg',quality=92)
print(f'Validated {len(reader.pages)} rendered pages; created contact sheets.')
