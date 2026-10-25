# Cloud Browser Screenshot Acceptance

Linux-only, headless Chromium, actual HTTP pages on `http://127.0.0.1:8793`.
This runner never starts a service, uses SSH, attaches to a desktop/cloud-console
browser, creates a task/student, uploads a file, or submits teacher/admin edits.
Only login/logout POST requests are permitted. Page/API GETs still produce normal
server access/audit activity and may invoke existing server-side read-time sync.

## Host Preparation (Main Agent / Operator)

Use the application's Linux virtual environment and provision Playwright Chromium
and its OS dependencies there. No install or service start happens automatically:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install --with-deps chromium
```

Alternatively, an operator can install the matching official Chromium build in
`/opt/rehabaffect-browser/` and add, for example:

```bash
--executable-path /opt/rehabaffect-browser/chrome-linux64/chrome
```

Use the actual extracted executable path; archive layouts vary. The option only
accepts an existing executable regular file strictly below that directory. Relative
paths, `..`, symlinks in the executable OR any parent directory, missing files and
non-executable files are rejected as `unsafe_executable`. No option means the
unchanged Playwright-managed Chromium default. The runner neither downloads nor
extracts archives, nor verifies their checksum/build compatibility. The operator
must verify the official HTTPS download and complete archive checksum, install
required libraries, and protect the browser directory from untrusted writes. A
matching MD5 checks transfer integrity, not an independent authenticity signature.
Only synthetic tasks are supported; there is no `--real-task` option.

Read-only reuse of the same private credential files as `cloud_e2e_acceptance.py`:
four school credentials in its supported Markdown/JSON format, plus separate admin
JSON. Files must be owned by the invoking Linux user, mode `0600` or `0400`, not
symlinks. Never put credentials in command arguments, shell environment, or logs.

```bash
.venv/bin/python scripts/cloud_browser_acceptance.py \
  --base-url http://127.0.0.1:8793 \
  --school-credentials-file /private/schools.md \
  --admin-credentials-file /private/admin.json
```

Optional `--output-root /private/cloud-screenshots`: directory must be owned by
the current user, private (`0700`), outside the repository and all web-served
directories, without symlink parents. The runner enforces repository exclusion,
owner/mode/symlink checks; the operator must ensure a custom directory is NOT
served by nginx or any other service. Default:
`~/.local/state/rehab-affect/cloud-browser-screenshots/<UTC timestamp>/`.

## Existing Synthetic Data Only

For each of the four teacher accounts, select the latest ready task from the
actual `/course-analysis/tasks` response whose title starts with `cloud e2e` or
`cloud-e2e`. Also support the existing E2E generator's exact title
`SYNTHETIC HTTP acceptance`, `cloud-e2e-<16 hex>` batch and `synthetic.mp4` filename.
The selected task must have no linked people or teacher records, and the batch
must contain only ready synthetic tasks. Technical evidence/report must match
the task and source revision. No real-classroom fallback and no quota use.

If synthetic tasks are missing, run the separately authorized E2E uploader first;
this screenshot runner reports `synthetic_task_missing` and does NOT create them.
It does not inspect or capture student archives, dossier plaintext, or raw DBs.

## Preserved Artifacts

Each account gets its own fresh, nonpersistent browser context; admin never shares
teacher cookies. For each teacher, preserve blank login, populated synthetic upload
list, desktop synthetic technical result, mobile result, and teacher report after
a successful real UI HTML-download event. The player must actually load and advance.
Admin gets blank admin login and dashboard screenshots. Account fields, credentials,
invite/token-related elements, and administrator detail tables are masked; totals,
layout, technical results and action controls remain visible. Masking is deliberate
privacy redaction, not an unmodified screenshot claim.

Outputs are private PNGs plus `acceptance.json` (pass/fail, artifact filenames,
download byte length/SHA-256, opaque synthetic task fingerprint). Raw downloaded
HTML is checked in the browser's private temporary directory then deleted. No
cookies, passwords, invitation values, browser profiles, HAR, tracing, console
logs, response dumps, or raw exception call logs are saved. Redirects/external
origins cannot receive browser requests. Only sessions created by the runner are
logged out; existing user sessions are not touched.

Exit 0 requires all four teacher flows and admin capture to pass. Exit 1 preserves
partial images and machine-readable failures; do not treat it as acceptance.
The download screenshot shows the real report page, not fabricated browser download
chrome; the JSON receipt separately proves a download event completed.

These screenshots verify existing synthetic evidence playback and report UI only,
not new upload creation, 670 MiB transfer speed, public HTTPS/ICP readiness, student
assessment, actual student tracking, or cloud-account ownership. No screenshot is
sent externally by this script. Share only operator-reviewed redacted copies.

Pure local safety tests (no service/browser startup):

```bash
.venv/bin/python -m pytest tests/test_cloud_browser_acceptance.py -q
```
