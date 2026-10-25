"""Opt-in synthetic-only gateway probe. Never reads school media or dossiers."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
from pathlib import Path
import secrets
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rehab_affect.demo2_dossier_vault import DossierVault

BASE = "https://model.kimitk.top/v1"
PRIVATE = ROOT / ".runtime" / "demo3_gateway"


def inline(data: bytes, mime: str) -> str:
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def card(code: str, color: str) -> bytes:
    im = Image.new("RGB", (480, 240), "white")
    draw = ImageDraw.Draw(im)
    draw.rectangle((12, 12, 140, 225), fill=color)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 64)
    draw.text((170, 80), code, fill="black", font=font)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def call(key: str, model: str, content: object) -> dict:
    start = time.monotonic()
    try:
        response = requests.post(
            BASE + "/chat/completions",
            headers={"Authorization": "Bearer " + key},
            json={"model": model, "messages": [{"role": "user", "content": content}],
                  "max_tokens": 768, "stream": False},
            timeout=(15, 70), allow_redirects=False,
        )
        result = {"http_status": response.status_code, "seconds": round(time.monotonic() - start, 2)}
        if response.status_code == 200:
            body = response.json()
            choices = body.get("choices") or [{}]
            result.update(reply=choices[0].get("message", {}).get("content"),
                          finish_reason=choices[0].get("finish_reason"),
                          reported_model=body.get("model"), usage=body.get("usage"))
        else:
            # Do not echo vendor error bodies: they can contain credentials/payloads.
            result["error"] = "provider_http_error"
            detail = response.text.lower()
            if isinstance(detail, str):
                result["error_hints"] = [label for label, words in {
                    "audio_field_mentioned": ("input_audio", "audio"),
                    "unsupported_input": ("unsupported", "not support", "not allowed", "不支持"),
                    "invalid_parameter": ("invalid", "parameter", "validation"),
                    "model_unavailable": ("model not found", "no available", "no channel"),
                }.items() if any(word in detail for word in words)]
        return result
    except requests.exceptions.SSLError:
        return {"error": "tls_verification_failed"}
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError):
        return {"error": "connection_or_response_error"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3.8-max")
    parser.add_argument("--fixture-seed", type=int)
    parser.add_argument("--cases", nargs="+", choices=["text", "image", "audio", "video", "frames"],
                        default=["text", "image", "audio", "video"])
    args = parser.parse_args()
    rng = random.Random(args.fixture_seed) if args.fixture_seed is not None else secrets.SystemRandom()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    vault = DossierVault(PRIVATE.resolve())
    secret_path = PRIVATE / "api_key.enc"
    provided = os.environ.get("REHAB_DEMO3_PROBE_KEY", "").strip()
    if provided:
        secret_path.write_bytes(vault.seal(provided.encode()))
    if not secret_path.exists():
        raise SystemExit("Missing local encrypted credential; set REHAB_DEMO3_PROBE_KEY once.")
    key = vault.open(secret_path.read_bytes()).decode()
    cases = {}
    if "text" in args.cases:
        cases["text"] = ("Return only the sum of 17 and 26.", "43")
    if "image" in args.cases:
        code = str(rng.randrange(1000, 10000))
        png = card(code, "red")
        (PRIVATE / "synthetic_card.png").write_bytes(png)
        cases["image"] = ([{"type": "text", "text": "Read the four digit number in this image. Return only the number."},
                           {"type": "image_url", "image_url": {"url": inline(png, "image/png")}}], code)
    if "audio" in args.cases:
        audio = PRIVATE / "synthetic_speech.wav"
        if audio.exists():
            cases["audio"] = ([{"type": "text", "text": "Transcribe the spoken words in this audio. Do not guess if audio is unavailable."},
                               {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "wav"}}],
                              "The green door is number seven.")
    if "video" in args.cases or "frames" in args.cases:
        import cv2
        import numpy as np
        video = PRIVATE / "synthetic_sequence.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 4, (480, 240))
        if not writer.isOpened():
            raise SystemExit("Synthetic video encoder unavailable")
        sequence = [str(number) for number in rng.sample(range(1000, 10000), 3)]
        for code, color in zip(sequence, ["red", "blue", "green"]):
            frame = cv2.cvtColor(np.array(Image.open(io.BytesIO(card(code, color)))), cv2.COLOR_RGB2BGR)
            for _ in range(8):
                writer.write(frame)
        writer.release()
        if "video" in args.cases:
            cases["video"] = ([{"type": "text", "text": "List the numbers shown in this video in chronological order. Do not guess if video is unavailable."},
                               {"type": "video_url", "video_url": {"url": inline(video.read_bytes(), "video/mp4")}}], sequence)
        if "frames" in args.cases:
            content = [{"type": "text", "text": "These are chronological frames from a synthetic video. Return only the three numbers in chronological order, separated by commas."}]
            capture = cv2.VideoCapture(str(video))
            for seconds in (1, 3, 5):
                capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
                ok, frame = capture.read()
                if not ok:
                    raise SystemExit("Synthetic frame extraction failed")
                ok, encoded = cv2.imencode(".png", frame)
                if not ok:
                    raise SystemExit("Synthetic frame encoding failed")
                content.extend([{"type": "text", "text": f"Timestamp: {seconds} seconds"},
                                {"type": "image_url", "image_url": {"url": inline(encoded.tobytes(), "image/png")}}])
            capture.release()
            cases["frames"] = (content, sequence)
    report = {"model_requested": args.model, "endpoint": BASE, "synthetic_only": True,
              "school_data_sent": False, "production_enabled": False, "results": {}}
    for name, (content, expected) in cases.items():
        result = call(key, args.model, content)
        result["expected"] = expected
        reply = result.get("reply") or ""
        if name in ("text", "image"):
            result["exact_match"] = isinstance(reply, str) and reply.strip() == expected
        elif name in ("video", "frames"):
            result["sequence_match"] = isinstance(reply, str) and all(x in reply for x in expected) and [reply.find(x) for x in expected] == sorted(reply.find(x) for x in expected)
        else:
            result["requires_transcript_review"] = True
        report["results"][name] = result
        destination = PRIVATE / ("probe_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": name, **result}, ensure_ascii=True), flush=True)
    print("Report: " + str(destination), flush=True)


if __name__ == "__main__":
    main()
