"""Compare two reviewed failure images using an existing authorized provider only.

Private probe; never changes a job, account, environment file or published result.
"""
from dataclasses import replace
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cloud_observation_effectiveness as effect


def context_sheet(data, boxes):
    from PIL import Image, ImageDraw, ImageFont
    original = effect.decode_image(data)
    width = 1600
    header_height = round(original.height * width / original.width)
    columns, side = 4, 400
    sheet = Image.new('RGB', (width, header_height + ((len(boxes) + columns - 1) // columns) * side), 'white')
    sheet.paste(original.resize((width, header_height)), (0, 0))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=22)
    for index, box in enumerate(boxes):
        x, y, w, h = [box[key] for key in ('x', 'y', 'width', 'height')]
        left, top = max(0, x - 2 * w), max(0, y - .25 * h)
        right, bottom = min(1, x + 3 * w), min(1, y + 9 * h)
        crop = original.crop((round(left * original.width), round(top * original.height),
                              round(right * original.width), round(bottom * original.height)))
        crop.thumbnail((side - 12, side - 40))
        ox, oy = (index % columns) * side, header_height + (index // columns) * side
        draw.text((ox + 6, oy + 5), 'REGION %d: indexed head + context' % (index + 1), fill='black', font=font)
        sheet.paste(crop, (ox + (side - crop.width) // 2, oy + 36))
    for quality in (82, 70, 58, 45):
        buffer = io.BytesIO()
        sheet.save(buffer, 'JPEG', quality=quality)
        if buffer.tell() <= 524288:
            return buffer.getvalue()
    raise ValueError('context_sheet_too_large')


def read_private(path, limit):
    effect.no_links(path)
    info = path.stat()
    if not path.is_file() or info.st_size > limit or info.st_nlink != 1 or info.st_mode & 0o077:
        raise ValueError('private_file_required')
    return path.read_bytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-review-dir', type=Path, required=True)
    parser.add_argument('--model', choices=['qwen3.8-max', 'glm-5.3', 'kimi-k3', 'glm-5.3-flash'], required=True)
    parser.add_argument('--context-crops', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path('/var/lib/rehabaffect/acceptance-private')
    if (not args.input_review_dir.is_relative_to(root) or args.output.parent != root or args.output.exists()):
        raise ValueError('private_root_required')
    effect.no_links(args.input_review_dir)
    effect.no_links(args.output)
    os.umask(0o077)
    from rehab_affect.demo2_observation_model import ObservationModelClient, ObservationModelConfig, SampleFrame
    from rehab_affect.demo2_observation_store import _allowed_hashes
    report = json.loads(read_private(args.input_review_dir / 'review.private.json', 524288))
    manifest = json.loads(read_private(args.input_review_dir / 'input-manifest.private.json', 524288))
    if report['source_sha256'] not in _allowed_hashes() or report['actual_input_hashes_verified'] is not True:
        raise ValueError('sample_not_authorized')
    config = replace(ObservationModelConfig.from_env(), model=args.model, timeout_seconds=90)
    selected, samples, images, model_images = [], [], [], []
    for index in (1, 3):
        item, row = manifest[index], report['frames'][index]
        name = row['actual_model_input_file']
        if Path(name).name != name:
            raise ValueError('invalid_image_path')
        data = read_private(args.input_review_dir / name, 524288)
        if hashlib.sha256(data).hexdigest() != item['model_image_sha256']:
            raise ValueError('input_changed')
        original_input = data
        if args.context_crops:
            data = context_sheet(data, item['person_boxes'])
            item = {**item, 'context_sheet_sha256': hashlib.sha256(data).hexdigest(),
                    'view': 'source_with_numbered_context_crops'}
        samples.append(SampleFrame(item['timestamp_sec'], data, 'image/jpeg', person_boxes=item['person_boxes']))
        selected.append(item)
        images.append(original_input)
        model_images.append(data)
    args.output.mkdir(mode=0o700)
    for index, data in enumerate(model_images, 1):
        effect.write_private(args.output / ('actual-input-%02d.jpg' % index), data)
    started = time.monotonic()
    result = ObservationModelClient(config).analyze(samples, task_id=report['task_id'],
        source_sha256=report['source_sha256'], frame_revision=report['frame_revision'], media_duration_sec=None)
    effect.write_json(args.output / 'result.private.json', result)
    effect.write_json(args.output / 'inputs.private.json', selected)
    for index, (sample, row, data) in enumerate(zip(selected, result['frames'], images), 1):
        image = effect.decode_image(data)
        diagnostics, _ = effect.frame_diagnostics(row, sample, image, [], [])
        effect.render_pair(image, diagnostics, [], sample['frame_key'], sample['timestamp_sec'], args.output, index)
    summary = {'ok': True, 'model': args.model, 'seconds': round(time.monotonic() - started, 3),
               'sample_count': len(samples), 'observations': sum(len(row['observations']) for row in result['frames']),
               'published': False, 'effectiveness_passed': None}
    effect.write_json(args.output / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        code = getattr(error, 'code', '')
        print(json.dumps({'ok': False, 'error': code if code in {
            'timeout', 'invalid_response', 'transport_error', 'upstream_status', 'model_refused'} else 'probe_failed'}), flush=True)
        raise SystemExit(1)
