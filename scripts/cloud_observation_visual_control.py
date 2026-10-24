"""Image-grounding negative controls; generated pixels, no school data or writes."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def controls():
    from PIL import Image, ImageDraw
    result = []
    for index, color in enumerate(('#ffffff', '#192d44')):
        image = Image.new('RGB', (1280, 720), color)
        if index:
            draw = ImageDraw.Draw(image)
            for x in range(100, 1200, 200):
                draw.rectangle((x, 180, x + 90, 500), fill='#66bbaa')
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=90)
        result.append(buffer.getvalue())
    return result


def main():
    from rehab_affect.demo2_observation_model import ObservationModelClient, ObservationModelConfig, SampleFrame
    client = ObservationModelClient(ObservationModelConfig.from_env())
    # Decoy locators prevent a false pass from simply interpreting "no proposals" as "no people".
    decoys = [{'x': x, 'y': .25, 'width': .06, 'height': .1} for x in (.15, .45, .75)]
    samples = [SampleFrame(float(i), data, 'image/jpeg', person_boxes=decoys) for i, data in enumerate(controls())]
    result = client.analyze(samples, task_id='synthetic-no-people-control',
        source_sha256='0' * 64, frame_revision='1' * 64, media_duration_sec=2)
    counts = [len(frame['observations']) for frame in result['frames']]
    passed = len(counts) == 2 and counts == [0, 0]
    print(json.dumps({'control': 'generated_images_without_people_with_decoy_regions', 'passed': passed,
        'observation_counts': counts, 'positive_recognition_accuracy_verified': False}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({'control': 'generated_images_without_people', 'passed': False,
                          'error': 'control_request_failed'}), flush=True)
        raise SystemExit(2)
