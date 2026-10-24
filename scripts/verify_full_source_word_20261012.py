"""Verify source fidelity after Word pagination; remove unused template payloads."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import pdfplumber
from docx import Document
from pypdf import PdfReader
from scripts.build_full_source_word_20261012 import OUT, TARGET, SOURCE

def main():
    document=Document(TARGET)
    removed=[]
    for key,relationship in list(document.part.rels.items()):
        if relationship.reltype.rsplit('/',1)[-1] in {'image','customXml','hyperlink'}:
            document.part.drop_rel(key);removed.append(key)
    document.save(TARGET)
    manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf8'))
    expected=[]
    for item in manifest['inventory']:
        expected.extend(f'{i+1:05d}  {line.expandtabs(4)}' for i,line in enumerate((SOURCE/item['file']).read_text(encoding='utf-8-sig').splitlines()))
    actual=[]
    for paragraph in document.paragraphs:
        if paragraph.style.name=='Source Code':actual.extend(paragraph.text.split('\n'))
    assert actual==expected
    pdf=OUT/'review.pdf'
    reader=PdfReader(pdf)
    outside=[];counts=[]
    with pdfplumber.open(pdf) as rendered:
        for page_number,page in enumerate(rendered.pages,1):
            counts.append(len(page.chars))
            for char in page.chars:
                if char['x0'] < -1 or char['x1']>page.width+1 or char['top'] < -1 or char['bottom']>page.height+1:
                    outside.append({'page':page_number,'box':[char['x0'],char['top'],char['x1'],char['bottom']]})
            page.close()
            if page_number%100==0:print('Checked pages:',page_number,flush=True)
    report={'pages':len(reader.pages),'all_source_lines_verified_after_word':len(actual),'unused_template_relationships_removed':len(removed),'page_boundary_violations':outside,'low_content_pages':[i+1 for i,n in enumerate(counts) if n<8]}
    (OUT/'layout_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='page_boundary_violations'}))
    print('boundary violations:',len(outside))

if __name__=='__main__':main()
