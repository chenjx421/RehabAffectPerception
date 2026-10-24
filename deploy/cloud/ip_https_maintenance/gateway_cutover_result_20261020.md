# Gateway Cutover Result

Authorized by the user; switched at `2026-10-20T14:00:10Z` / `22:00:10 Asia/Shanghai`.
External acceptance started at `2026-10-20T14:00:27Z`. Result: **PASS**.
This supersedes the earlier maintenance-phase public-443 timeout result.

Final authenticated acceptance: PublicSample01 uploaded in 206.859 seconds and
finished processing in a further 366.563 seconds. The technical summary,
administrator report download and administrator media Range request all passed.
Four school logins and the administrator login also passed over public HTTPS.
The report is stored privately as `public-large-upload-2202.json`; it contains
no invitation secret or credentials. No school-network speed guarantee is implied.

## Active Ingress

- `/etc/nginx/ip-maintenance/active.conf` now contains ACME-only HTTP 80 and HTTPS
  to the invitation gateway at `127.0.0.1:8796`, not directly to the application.
- `nginx -t` passed, reload succeeded, and local trusted-TLS `/invite` returned 200.
- Maintenance backup retained as root-only 0600 at
  `/var/lib/rehab-ip-maintenance/maintenance-before-gateway-20261020T140008Z.conf`.
- Active config SHA-256:
  `30f2739e3f297b68fa1dbfe8591fdeb8014027a088a8d8c8edaab8ca3ae93356`.
- External IP Host fixed to `YOUR_SERVER_IP`; access logs off; 16 MiB per request;
  proxy read/send 360s; request/response buffering off; HTTP/1.1 upstream keepalive;
  Range and If-Range headers forwarded unchanged.

## Public Acceptance Without Credentials

| Request | Observed result |
| --- | --- |
| HTTPS `/invite` | 200 HTML; no authorization cookie issued |
| HTTPS `/demo2/login`, no invite | 401 `invitation_required` |
| HTTPS `/api/v1/demo2/auth/me`, no invite | 401 `invitation_required` |
| HTTPS `/api/v1/demo2/upload/workspace`, no invite | 401 `invitation_required` |
| HTTP `/` and `/invite` | 404 |
| HTTP nonexistent ACME challenge | 404 |
| Python default CA store and exact IP SAN | Verified, no TLS bypass |
| Independent Windows curl `/invite` | 200, `ssl_verify_result=0` |

The live certificate SHA-256 remains
`0c39ad4ff51aa8155f7c4edf1979c71eab8a40ab0aac163d4c2d8d93f354b714`.
Machine-readable evidence: `gateway_public_verification.json`.
No cookie jar, authorization secret, login credentials, forged invitation or
authenticated request was used. Only three unauthorized gateway checks were made
to stay below its failure-rate threshold. Do not repeatedly run this check during
the main agent's real-credential acceptance.

## Gateway Readiness Repair

Initial cutover preflight found gateway failed with no 8796 listener, despite the
earlier transient service-start result. File metadata showed `gateway.json` was
0600 root:rehabaffect-gateway and unreadable by the intended service user.
Only its mode was corrected to the already-documented 0640; contents were never
read or rewritten. The failed gateway state was reset and the gateway started.
No application restart, environment edit, secret/expiry change or DB operation
was performed by this task.

### Exact Permission Change

| Item | Before | After |
| --- | --- | --- |
| `/etc/rehabaffect/gateway.json` mode | 0600 | 0640 |
| File owner and group | root:rehabaffect-gateway | Unchanged |
| Intended service user's `test -r` | Failed | Passed |
| File content, secret and expiry | Not read | Not read or rewritten |
| Parent `/etc/rehabaffect` | 0710 root:rehabaffect-gateway | Unchanged |
| `/etc/rehabaffect/cloud.env` | 0600 root:root | Unchanged; contents not read |

The correction added only group-read permission to the configuration; it added
no group-write or other-user access and did not change ownership. The following
operations are a historical record, **not instructions to rerun during upload**:

```sh
sudo -n chmod 0640 /etc/rehabaffect/gateway.json
sudo -n -u rehabaffect-gateway test -r /etc/rehabaffect/gateway.json
sudo -n systemctl reset-failed rehabaffect-gateway.service
sudo -n systemctl start rehabaffect-gateway.service
```

The app remained running with PID 71192 across this repair; gateway became active
with loopback PID 74319 at the subsequent ingress acceptance. No ProtectSystem or
other systemd hardening setting was relaxed. The promotion script was not edited
by this side task; future provisioning must retain the intended 0640 file mode.

### Reproducible Provisioning Cause

No parent directory permission was changed during the gateway readiness repair.
`/etc/rehabaffect` was already 0710 root:rehabaffect-gateway when inspected.

Inspection before the main agent's correction confirmed `scripts/cloud_promote_pilot.py` sets
`os.umask(0o077)`, while `private_write` at lines 32-37 passes its requested mode
only to `os.open` and never reapplies it. Therefore its `mode=0o640` gateway call
at line 99 creates a 0600 file: `0o640 & ~0o077 == 0o600`. The later `os.chown`
changes ownership but cannot restore the masked group-read bit. The directory
mode at lines 97-98 is already correct and does not need to be broadened.

The main agent's minimal source fix is to set the final file mode explicitly,
after setting ownership and before starting the gateway:

```python
os.chown(CONFIG / 'gateway.json', 0, identity.pw_gid)
(CONFIG / 'gateway.json').chmod(0o640)
```

An alternative reusable-helper fix is `os.fchmod(output.fileno(), mode)` in
`private_write`, after writing/flushing and before the final fsync. Preserve the
default 0600 mode for cloud.env and the process-wide 0077 umask; do not loosen
parent directories or globally change the umask to solve this one file's access.
No source fix was applied by this TLS side task because the main agent owns it.

This also explains the reported preflight code without requiring a parent-mode
change: the configuration read raises PermissionError, an OSError, which
`scripts/cloud_runtime_preflight.py:152-153` maps to
`required_runtime_resource_unavailable`. This mapping alone is generic, but the
observed failed/successful service-user read checks isolated this concrete defect.

At final acceptance, nginx, regular app, regular gateway and the six-hour renewal
timer were all active. Ports 8793 and 8796 were loopback-only. Nginx access.log
remained 0 bytes. The user's subsequent instruction was to keep the completed
cutover in place; no rollback was performed.

## Main-Agent Acceptance Update

The user reports successful real public-HTTPS logins for four school accounts and
one administrator, plus a successful administrator summary request. These are
main-agent observations, not authenticated tests repeated by this TLS side task.
No credentials, invitation cookies or account responses were collected here.

PublicSample01 is approximately 554 MB (previously described as 553.7 MB). The
latest user update reports upload **completed in 206.859 seconds**; analysis is
in progress. The earlier 160 MiB progress and approximately 20 Mbps observation
are superseded by that completion report, not a sustained-rate guarantee or proof
of 200 Mbps throughput. Media processing, authorized Range playback and final
outcomes remain with the main agent. No new monitoring, probing, configuration changes,
service operations or DB access were performed after the user's upload hold.

## Change Inventory

All local files for this side task are in `deploy/cloud/ip_https_maintenance/`:

- `nginx.conf`, `http.conf`, `https.conf`, `index.html`: isolated maintenance setup.
- `deploy.sh`, `reload.sh`, renewal service and timer: staging-first production
  issuance, separate Certbot environment, six-hour renewal and validated reload.
- `gateway-standby.conf`, `nginx-standby-check.conf`, `cutover_gateway.sh`: candidate
  proxy syntax checks, maintenance backup, guarded authorized cutover and rollback.
- `verify_public.py`, `public_verification.json`: historical maintenance acceptance.
- `verify_gateway_public.py`, `gateway_public_verification.json`: successful
  unauthenticated public gateway acceptance with default CA validation.
- `README.md`, `deployment_result_20261020.md`, this file: setup/history/handoff.

Remote changes were limited to the dedicated nginx/ACME/static-page/Certbot files,
renewal units and reload hook, followed by the authorized ingress switch and the
single gateway configuration permission repair above. No Windows source file,
original DB, tunnel, cloud application source, school context or application data
was modified by this side task. No Git commit or staging of unrelated work was
performed. This latest local handoff revision was intentionally not uploaded to
the server while the sample transfer was active.
