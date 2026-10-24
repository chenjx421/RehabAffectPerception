# Mainland Cloud School Pilot

## Observation Update: 2026-10-21

Cloud-only V8 application changes and the V9 observation-worker refinement are
active. Windows source/runtime were not changed. The public origin, invitation,
five existing accounts, source task revisions and existing dossier permissions
remain unchanged.

- Retained functions include identity/manual-box confirmation, IEP/dossier forms,
  teacher review, dual-track evaluation, reports and company administration.
  Sampled AI observations are now shown first. Mobile "more classroom functions"
  exposes the previous sidebar links rather than dropping them.
- An independent observation queue uses the configured gateway's
  `glm-5.3-flash` model. Only the four explicitly selected sample-video SHA-256
  values are permitted; other school videos are NOT automatically approved for
  transmission. Names, IEP and diagnostic documents are not included.
- Eight-image requests timed out in real testing. The accepted worker uses two
  concurrent batches of at most four images with bounded deadlines. Both must
  pass source, timestamp and schema checks before any combined result is saved.
  No partial response is disguised as a completed analysis.
- The optional `reasoning_effort=low` setting was tested against this gateway.
  Its meaning is documented in the official API reference:
  https://docs.z.ai/api-reference/llm/chat-completion (checked 2026-10-20).
  Compatibility with this gateway was measured, not assumed from the model name.
- Two real tasks completed in 50.462 and 48.683 seconds of observation-worker
  time, excluding upload, preprocessing and queue wait. The user's course "111"
  has eight sampled frames and 20 unreviewed visible-behavior observations.
  Another permitted sample has 24 observations. These counts do not demonstrate
  educational accuracy, continuous tracking or automatic recognition of names.
- Live acceptance checked result/source agreement, teacher and administrator JSON
  downloads, browser-generated report downloads, three peer-account denials and
  anonymous rejection for each task. Ten masked desktop/mobile/report screenshots
  and two anonymous acceptance reports are retained locally under
  `output/cloud_observation_20261021/`.
- V8 regression: 750 passed, three existing string-escape warnings. V9 targeted
  adapter/worker/frame/store regression: 246 passed. These suites overlap and
  must not be added together or described as educational-accuracy validation.
- Same-frame confirmed identities and explicit per-observation links can project
  observations into student history. Withdrawal removes the projection. General
  observations without a localized person cannot establish a student's identity.
  Real name/face/IEP linkage has not been validated for the supplied real pupils.
- Existing teacher scoring is preserved. The AI layer does not generate a
  validated automatic ten-point teacher grade, infer emotions/diagnoses, perform
  ASR or claim whole-lesson participation percentages.

Processing acceleration was tested on the same 553,697,450-byte real sample:
360.424 to 220.844 seconds, a 38.727% reduction. All 67,726 decoded frames, 2,258
sampled frames, source/audio/image/evidence hashes matched. This is a processing
benchmark, not a school-network upload guarantee.

Rollback code/database snapshots are private under
`/var/lib/rehabaffect/cloud_backups/`. The new worker is
`rehabaffect-observations.service`; application and uploads remain independently
managed. Never restore a stale database over new school submissions.

## Live State: 2026-10-20

The accepted copy is now running under `rehabaffect-app.service` and
`rehabaffect-gateway.service`, behind nginx at `https://YOUR_SERVER_IP`.
The prior preview service is stopped/disabled. All application/SQLite ports remain
loopback-only; only HTTP ACME challenges and public HTTPS are exposed.

- All 45 original source database tables matched the saved Windows snapshot before
  activation: 5 accounts and 44 original tasks. The 41 completed original source
  videos passed SHA-256 checks before and after cloud restoration.
- Engineering acceptance tasks remain clearly named as tests. Original school
  contexts/metadata have been restored; three accounts must select their real
  school on first use. Test placeholders were not promoted as verified schools.
- Public HTTPS login passed for all four retained school accounts and the retained
  administrator, with administrator query access checked. Credentials are unchanged.
- A 553,697,450-byte source video uploaded over the public HTTPS chunk API in
  206.859 seconds (21.414 Mbps payload), with matching SHA-256. This is one
  operator-network measurement, not a guarantee of the school's upload speed.
  Its subsequent processing completed in 366.563 seconds; the public technical
  summary and administrator report/media retrieval checks passed.
- Four existing real samples passed report, full-media hash, Range, refresh,
  administrator and tenant-isolation rechecks. Browser evidence includes 22
  synthetic screenshots and 12 masked real-media screenshots. Current reports
  expose technical processing evidence; educational inference remains separate.
- Application/gateway/nginx startup is managed by systemd. IP certificates use
  `rehab-ip-cert-renew.timer` every six hours; issuance and renewal dry run passed.
- The retained invitation expires 2026-11-06 23:59:59 Asia/Shanghai. Its secret is
  only in the root-protected gateway config and local private invitation files.
  Never include complete invitation URLs or credentials in reports/source archives.
- The regular application retention lifecycle is enabled. Existing 60-day rules
  and 15-day expiry reminders remain; test-link lifetime does not extend data life.
- The Windows source was not patched, reset or restarted. Its old writer must not
  be restarted after cloud cutover without an explicit reconciliation plan.

Private rollback DB/env and the untouched migration preseed remain on the cloud
host. A local rollback copy also retains the Windows database and sealed vault
key material. These local backups do not constitute independent disaster recovery.

The configuration notes below record migration gates and the original preparation
design. Public IP testing is currently active; a commercial domain/ICP deployment,
managed database, object storage and validated automated classroom scoring remain
separate work. See `ip_https_maintenance/` for TLS installation and cutover evidence.

## Purchase and Access Prerequisites

- Purchased pilot (console verified 2026-10-20): Tencent Shanghai, 4 vCPU / 8 GiB,
  Ubuntu 24.04 LTS x86-64, 120 GB SSD, 200 Mbps peak bandwidth, one month.
  Checkout price was CNY 230. No GPU is required for the current evidence extractor.
- Peak bandwidth is not a throughput guarantee. Measure a synthetic 670 MiB
  upload from the actual school network. A five-minute transfer needs at least
  18.7 Mbps sustained payload throughput for one upload, excluding analysis.
- A one-month purchase is for preparation/testing, not proof of ICP eligibility.
  Tencent's published Lighthouse ICP criteria require at least 90 days purchased
  and at least 30 days remaining during filing. Domain, filing and public-access
  approval are still pending. Do not promise same-night formal public launch.
  Sources checked 2026-10-20: https://cloud.tencent.com/document/product/1207/45756
  and https://cloud.tencent.com/document/product/1207/50103 .
- Use one application process and one media worker. Four accounts do not mean
  four concurrent analysis workers. Capacity and processing latency need testing.
- Choose expandable SSD storage. Budget raw media + frames/audio + partial uploads
  + temporary processing + separate encrypted backups + free-space reserve.
  100 GiB is an initial planning option, not a promise that it covers 60 days.
- Complete cloud-account verification, payment/budget approval, least-privilege
  access and operator-controlled SSH first. Do not send passwords/keys in reports.
- Before a mainland public website: confirm domain ownership, DNS, required ICP
  filing/access-provider approval and any other applicable compliance obligations.
  Obtain a valid trusted TLS certificate. A raw IP or temporary tunnel does not
  replace these requirements. Browser capture and Secure cookies require HTTPS.
- Public firewall: SSH only from approved operator addresses; 80/443 only after
  public-access approval. NEVER expose application/gateway/SQLite ports.

## Minimal Runtime

- Approved Python 3.12 environment at `/opt/rehabaffect/.venv`; repository at
  `/opt/rehabaffect`. The project declares Python >=3.10 but the current Windows
  validation used 3.12. Linux/3.12 still needs its own acceptance run.
- `requirements.txt`: NumPy, headless OpenCV, cryptography, python-docx. These are minimum
  declarations, NOT a tested dependency lock. Resolve and lock after Linux QA.
  Do not co-install headless and GUI OpenCV in the same environment.
- Linux FFmpeg AND ffprobe; provision approved binaries and verify their versions.
  The decoder documents FFmpeg 7.1 timing validation; required showinfo duration
  fields exist from 6.0. Ubuntu 24.04's package must pass the synthetic smoke test
  before use; a version number alone is insufficient. Ubuntu 22.04's stock 4.4
  lacks the required fields. No Windows `.exe` binaries or automatic model downloads.
- Caddy, systemd, local POSIX filesystem with SQLite locking and atomic rename.
  GPU, PyTorch, MuJoCo, scikit-learn, sounddevice and cloud model APIs are not
  required for the school upload/evidence/review workflow with `--policy rule`.
- Preserve `models/face_detection_yunet_2023mar.onnx` and verify the source-defined
  size/hash for face-position candidates. Missing model must not be called a
  successful detection. Manual identity confirmation remains mandatory.

## Blocking Migration Gates

1. Obtain an approved write-stop window only AFTER active school work finishes.
   Make a private consistent SQLite backup (including committed WAL data), an
   inventory of all referenced media/artifacts, and an independently restorable
   backup. No simultaneous writes on Windows and Linux after cutover.
2. Preserve existing account IDs/hashes, scopes, task IDs, authorizations, revisions,
   deletion/expiry state and audit history. NEVER start against an empty database.
   The store constructor creates tables and seeds accounts, so bypassing the
   service preflight can silently create the wrong installation.
3. Windows absolute media/result paths cannot work unchanged on Linux. An audited
   migration must rewrite path references and verify hashes, playback and ownership.
   Do not use symlinks to defeat the stores' no-link/path containment checks.
4. DPAPI-wrapped keys cannot be decrypted on Linux. Determine the actual key mode
   privately. If DPAPI was used, authorized migration must decrypt under the
   original Windows user and re-encrypt without plaintext files/logs. Different
   vault roots may have different keys; do not blindly apply one new key to old blobs.
5. Dossier ownership includes database identity AND absolute database-path hash.
   A copied `.dossier-owner.json` is not automatically valid at the new location.
   Rebinding needs separately reviewed migration work, not marker deletion or
   bypassing checks. This preparation does NOT implement path/key/marker migration.
6. Run integrity/foreign-key checks; compare approved account/task baselines and
   file hashes; verify every vault can decrypt and authorization still gates reads.
   Test audio/no-audio/corrupt/over-limit media, retry, restart recovery, range
   playback, report/export, cross-school denial, expiry and automatic history.
7. Have rollback and external encrypted backups ready. Only then complete the
   environment's approval/minimum-count placeholders. The service checks an
   existing nonempty SQLite file in read-only mode before importing the app;
   those checks are an additional gate, not proof of a completed migration.

## Runtime Layout and Environment Inventory

The template uses `/var/lib/rehabaffect/seewo_demo2` on a persistent local disk.
No path in the data tree may be a symlink. All application state is private.

| Root | Source of location / purpose |
| --- | --- |
| SQLite DB plus its WAL/SHM | `REHAB_DEMO2_DB_PATH` |
| Legacy `student_documents` | `REHAB_DEMO2_UPLOAD_DIR`; retired routes stay retired |
| `video_tasks/uploads`, `analysis`, `results`, `.worker.lock` | DB parent / `video_tasks`; includes partial uploads |
| `scoped_dossier_v1`, `.dossier-owner.json` | upload-directory parent; encrypted original files and ownership marker |
| `student_summary_v1`, `safety_review_v1` | upload-directory parent; vault roots, content also stored encrypted in SQLite |
| `school_material_intake` | encrypted operator-imported school materials; inventory before migration |
| `.demo2_dossier_keys` | vault-root parent; Windows DPAPI files, not portable Linux keys |
| Repository `outputs/seewo_demo2/reports`, `teacher_reviews.json`, `analysis.json` and course directories | legacy fixed paths; DB env does not relocate them |
| Repository `outputs/seewo_xiaoyudi_demo`, `outputs/mujoco_frames` | legacy demo/simulation assets; not core cloud data roots |
| `.runtime` / logs / share config-state | Windows operational state; do not copy wholesale or serve publicly |
| `models`, `configs/scenarios`, `data/processed/seewo_demo2/session_config.json` | code/demo resources; inventory separately, no blanket real-data upload |

Application environment keys (names only):
`REHAB_DEMO2_DB_PATH`, `REHAB_DEMO2_UPLOAD_DIR`, `REHAB_DEMO2_DOSSIER_KEY`,
`REHAB_DEMO2_MEDIA_WORKER`, `REHAB_DEMO2_RETENTION_SCAN_SECONDS`,
`REHAB_DEMO2_COURSE_UPLOAD_LIMIT`, `REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX`,
`REHAB_FFMPEG`, `REHAB_FFPROBE`.
Optional external-model keys, deliberately not configured here:
`REHAB_REPORT_LLM_BASE_URL`, `REHAB_REPORT_LLM_MODEL`, `REHAB_REPORT_LLM_API_KEY`,
`REHAB_DEEPSEEK_API_KEY`, `REHAB_DEEPSEEK_MODEL`.
Template-only gates: `CLOUD_MIGRATION_APPROVED`, `CLOUD_MIN_ACCOUNT_COUNT`,
`CLOUD_MIN_TASK_COUNT`. `TZ` must match Shanghai authorization-date semantics.

## Service and Proxy Review

- Create dedicated unprivileged `rehabaffect` and `rehabaffect-gateway` users.
  Provision directories manually; app data owned by the app user, mode 0700.
  Code is read-only. Legacy demo/report writes into the code tree are intentionally
  not enabled by these units; do not promise legacy demo pages as accepted features.
- Reviewed environment file: `/etc/rehabaffect/cloud.env`, root-only mode 0600.
  Gateway JSON: `/etc/rehabaffect/gateway.json`, root owner / gateway group, 0640;
  permit directory traversal but no broad secret-file access.
  Required JSON keys: `invite_secret`, `cookie_secret`, `expires_at`,
  `upstream_port`, `listen_port`. Preserve approved identities/expiry privately;
  do not regenerate, publish or extend them as a side effect of deployment.
- Units stay blocked while approval/minimum-count placeholders are incomplete.
  App: `python -m src.rehab_affect.scenario_lab_server --host 127.0.0.1 --port 8793 --policy rule`.
  Gateway: `python -m src.rehab_affect.demo2_manager_gateway --config ...`;
  its code only permits IPv4 loopback. Review config ports against these units.
- `run_server` embeds media/retention/dossier/summary maintenance threads. Do not
  launch multiple app replicas or disable the worker without a separate worker
  implementation. These are not ASGI/WSGI apps: do not wrap them in Gunicorn/Uvicorn.
- Linux supervision uses systemd, NOT the Windows keeper/watchdog/deploy scripts.
  Their `ctypes.windll`, `pythonw.exe`, Windows process/ACL handling are not portable.
- Caddy example is intentionally loopback-only with a reserved `.invalid` host.
  It is NOT public-ready. After domain/ICP/TLS approval, review hostname and bind
  separately. Route all permitted public requests through the invitation gateway,
  never directly to the app and never via a file server over the data directories.
  Keep access logging disabled until reviewed for student IDs/query-string leakage.
- Verify proxy streaming, range responses and upload timeouts end-to-end. Current
  new uploads have a 1 GiB / 60-minute policy; legacy tasks can retain older limits.
  Chunk requests are bounded independently. Do not set a whole-file body limit
  or claim a fixed upload rate from a CPU/RAM specification.
- A started unit is not acceptance: confirm ports, app/gateway HTTP, authorized
  school/admin flows and an actual worker-produced synthetic result before DNS
  cutover. The current Windows tunnel remains untouched until a separate decision.
- Direct COS upload/storage is PENDING: the app expects local paths, seek/truncate,
  rename and local deletion. Mounting a bucket or replacing paths with URLs is
  not an implemented storage adapter. PostgreSQL/Redis migration is also not part
  of tonight's minimal single-host SQLite deployment.

## Audit Anchors (2026-10-20 Source Snapshot)

- `pyproject.toml:6`: Python floor; `:8` declares only NumPy as mandatory.
- `src/rehab_affect/demo2_media_analysis.py:71`: executable discovery;
  `:392` decoding contract; `:36` per-run artifact cap; stage timeouts are not a whole-job SLA.
- `src/rehab_affect/demo2_face_detection.py:29`: local YuNet model and integrity checks.
- `src/rehab_affect/student_record_store.py:271`: constructor/initialization;
  `:2904` DB/upload env; `:2095` controlled absolute source paths.
- `src/rehab_affect/demo2_dossier_store.py:199`: DB/path-bound storage ownership.
- `src/rehab_affect/demo2_dossier_vault.py:286`: explicit key vs Windows-only DPAPI.
- `src/rehab_affect/demo2_student_summary_store.py:78` and `demo2_safety.py:26`: vault roots.
- `src/rehab_affect/scenario_lab_server.py:2532`: HTTP server plus background workers;
  `src/rehab_affect/demo2_media_worker.py:163`: single-worker lock/startup recovery.
- `src/rehab_affect/demo2_manager_gateway.py:677`: loopback-only binding;
  `scripts/start_school_demo.ps1:35`: Windows local startup pattern.

## Operator Checks

- `scripts/cloud_migration_inventory.py --root ABSOLUTE_PROJECT_ROOT`: aggregate,
  read-only source inventory. It does not export keys or files and is not a backup.
- `scripts/cloud_runtime_preflight.py app` / `gateway`: tested systemd startup
  gates. Missing approvals, missing DB, inconsistent baselines and invalid runtime
  resources fail with fixed non-secret codes. No store initialization occurs.
- `scripts/cloud_media_smoke.py --ffmpeg /usr/bin/ffmpeg --ffprobe /usr/bin/ffprobe`:
  synthetic two-second audio/no-audio decode checks, no real students or API calls.
  This verifies decoding, not educational scoring or identity accuracy.

The application and gateway templates are now installed as Linux services for
the pilot described above. Purchase alone was not treated as acceptance; the
source comparison, media checks and explicit upload/browser tests preceded access.
