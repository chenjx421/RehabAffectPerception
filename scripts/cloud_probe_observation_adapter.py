"""Check the configured cloud transport with synthetic images only."""
from __future__ import annotations

import importlib.util
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np


def main():
    path = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("cloud_observation_probe_model", path)
    model = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = model
    spec.loader.exec_module(model)
    images = []
    for timestamp in (0, 10):
        image = np.full((320, 480, 3), 245, dtype=np.uint8)
        cv2.circle(image, (200, 65), 22, (0, 0, 0), 3)
        cv2.line(image, (200, 88), (200, 200), (0, 0, 0), 5)
        cv2.line(image, (200, 115), (270, 35 if timestamp else 150), (0, 0, 0), 5)
        cv2.line(image, (200, 115), (145, 150), (0, 0, 0), 5)
        cv2.line(image, (200, 200), (165, 290), (0, 0, 0), 5)
        cv2.line(image, (200, 200), (235, 290), (0, 0, 0), 5)
        encoded, buffer = cv2.imencode(".jpg", image)
        if not encoded:
            raise RuntimeError("fixture_encoding_failed")
        images.append(model.SampleFrame(timestamp, buffer.tobytes()))
    started = time.monotonic()
    try:
        config = model.ObservationModelConfig.from_env()
        if len(sys.argv) > 2:
            config = replace(config, model=sys.argv[2])
        result = model.ObservationModelClient(config).analyze(images)
        report = {"ok": True, "synthetic_only": True, "seconds": round(time.monotonic() - started, 3),
                  "model": config.model,
                  "frames": len(result["frames"]), "school_data_sent": False,
                  "actions": [[item["behavior"] for item in frame["observations"]] for frame in result["frames"]]}
    except model.ObservationModelError as error:
        report = {"ok": False, "synthetic_only": True, "error": error.code, "school_data_sent": False}
    print(json.dumps(report), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
