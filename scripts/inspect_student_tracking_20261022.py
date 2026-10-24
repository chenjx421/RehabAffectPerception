"""Private contact sheets for human identity continuity checks, not a model eval."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = json.loads((args.root/'derived.json').read_text(encoding='utf-8'))
    targets = [0, 300, 600, 840, 900, 960, 1020, 1200, 1500, 1800, 2100, 2280]
    for person in result['persons']:
        sheet = Image.new('RGB', (6*180, 2*210), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, start in enumerate(targets):
            window = next((w for w in person['windows'] if w['start_sec'] == start), None)
            if not window or not window['frame']:
                continue
            source = Image.open(args.root/'frames'/window['frame']).convert('RGB')
            b = window['bbox']
            x, y, w, h = b['x']*source.width, b['y']*source.height, b['width']*source.width, b['height']*source.height
            image = source.crop((max(0,x-w*1.1), max(0,y-h*.9), min(source.width,x+w*2.1), min(source.height,y+h*3.5)))
            image.thumbnail((170, 170))
            image = image.resize((max(1,int(image.width*min(170/image.width,170/image.height))),max(1,int(image.height*min(170/image.width,170/image.height)))))
            ox, oy = (i%6)*180, (i//6)*210
            sheet.paste(image, (ox+(180-image.width)//2, oy+25))
            draw.text((ox+5,oy+4), f"{start//60:02}:{start%60:02} / t={window['frame_time_sec']}", fill='black')
            draw.text((ox+5,oy+192), f"motion={window['movement']} n={window['observed_samples']}", fill='black')
        sheet.save(args.root/f"{person['person_id']}_contact.png")


if __name__ == '__main__':
    main()
