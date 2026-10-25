# Data Directory

This directory is intentionally kept lightweight in Git.

Recommended local layout:

```text
data/
  raw/
    session_0001/
      front_rgb.mp4
      microphone.wav
      robot_events.jsonl
      labels.json
  processed/
    clips.jsonl
    features.jsonl
```

Do not commit raw videos, audio, or private user data to GitHub.

