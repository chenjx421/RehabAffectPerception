# Person Portrait Fix, 2026-10-22 (China Standard Time)

Scope: complete heads in the three person portraits on the existing cloud result
page, without replacing tasks, accounts, source videos, bindings or scores.

## Changes

- Compact head-and-shoulders crops include additional space above each face.
- Portrait tabs, main portrait and timeline thumbnails use `object-fit: contain`.
- Crop cache keys include the crop version and source image; old crop files are
  retained but are no longer selected by the changed calculation.
- No frame/box means a text placeholder, never an empty image URL or a full-scene
  image pretending to be an individual portrait. Failed image loads are explicit.
- Tabs have stable dimensions; the main label describes the displayed sample,
  not the predominant availability state across the lesson.
- Main portraits and tabs can use a higher-resolution source preview at the
  persisted sample time. Extraction uses the existing bounded local decoder,
  a shared per-frame cache, aspect-ratio checks and whole/local image-difference
  checks. A mismatch or extraction error retains the sampled image. This is a
  viewing aid, not pixel-identical evidence or an identity-recognition upgrade.
- Original evidence, frame revisions and identity-write coordinates are unchanged.
- Timeline thumbnails load lazily; they retain the original sampled evidence.

## Verification

- `test_simple_person_portraits.py` plus the two simple analysis tests: 15 passed.
- `test_demo2_frame_preview.py` plus portrait tests: 81 passed, 2 skipped.
- Real public HTTPS verification: three distinct colored portrait URLs, three
  person switches, differing timeline content, no empty/failed images after
  scrolling through the available thumbnails, no page script errors, no page
  overflow at 390px. The verification only reads an existing user-designated task.
- All three rendered heads visually inspected. Source preview crop sizes were
  32x36, 38x44 and 37x42 pixels: resolution remains limited; no claim of HD faces.
- Browser evidence: `output/playwright/portraits-20261022/acceptance.json` and PNGs.
- Release stage: `.runtime/cloud_candidate_20261022_portraits_v5`.
- Root-owned cloud backup: `v10-20261021T182949Z-d7f581f2` (UTC in backup name).
- Deployment helper verified the site was idle, backed up code/database, resumed
  services and verified protected account/task rows and existing schemas unchanged.

## Boundaries And Follow-Up

This release verifies portrait rendering, not educational scoring accuracy. The
existing heuristic scoring and the 12-point legacy-result refresh were not changed.
The legacy refresh cannot provide dense per-person observations for a whole lesson;
do not treat unsampled intervals as proven absence. Shared audio is not evidence
of an individual child's confusion. These require a separate analysis revision,
not artificial differences between student scores.

An earlier wider run found 14 failures in the acceleration baseline-comparison
tests, alongside 44 passes and 1 skip. Those media-engine files were not modified
in this portrait release. The full project suite is not claimed to pass.
