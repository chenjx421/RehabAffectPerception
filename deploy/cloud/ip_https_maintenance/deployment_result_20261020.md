# IP HTTPS Maintenance Deployment Result

Historical maintenance-phase report. Superseded at 22:00 Asia/Shanghai by
`gateway_cutover_result_20261020.md`: public 443 was opened by the main agent,
the authorized gateway cutover completed, and external trusted-TLS checks passed.

Last external check started: 2026-10-20 13:44:25 UTC / 21:44:25 Asia/Shanghai.
Target: `YOUR_SERVER_IP`. Result: **server deployment ready; public HTTPS blocked**.
No public application/gateway cutover was performed by this task.

## Verified Results

| Check | Observed result |
| --- | --- |
| Initial 80/443 listeners | None; no existing web service replaced |
| Host firewall | UFW inactive; IPv4 iptables INPUT/FORWARD/OUTPUT policy ACCEPT |
| Public TCP/HTTP 80 | Reachable; synthetic ACME probe returned 200 with exact expected body |
| Public non-challenge HTTP | `/` and 10 synthetic restricted paths returned 404 |
| ACME staging | Successful IP certificate issuance before production |
| ACME production | Successful issuance; IP identity and system CA chain verified |
| Server listeners | nginx on IPv4 0.0.0.0:80 and 0.0.0.0:443 |
| Local HTTPS with real CA validation | `curl --resolve YOUR_SERVER_IP:443:127.0.0.1` returned 503 maintenance |
| Local HTTPS restricted routes | 10 synthetic app/data/config paths returned 404 |
| Public TCP/HTTPS 443 | Windows curl and independent Python direct connection timed out after nginx was listening |
| Public HTTPS trust/route acceptance | NOT completed: TLS handshake could not be reached externally |
| Access logs | Disabled globally and on both servers; access.log remained 0 bytes |
| Application upstream in active config | None; explicit no-upstream check passed |
| Gateway standby | Present, separate, not included; nginx syntax check passed |
| Renewal dry run | Successful simulated renewal with deploy hook; current production TLS retained |
| Renewal systemd service | Result=success, ExecMainStatus=0 |
| Renewal timer | Active; every 6 hours with up to 5 minutes systemd jitter; persistent across reboot |
| Temporary public probe | Removed after ACME/renewal verification |

The latest public verification JSON intentionally records `public_verified: false`
and `result: FAIL`. This is a network reachability failure, not evidence of a
publicly accepted certificate. No `-k`, custom trust exception, proxy environment,
or disabled TLS verification was used in public checks.

## Public Certificate Metadata

- Issuer: `C=US, O=Let's Encrypt, CN=YE1`.
- Critical SAN: `IP Address:YOUR_SERVER_IP`.
- Not before: `2026-10-20T12:41:03Z`.
- Not after: `2026-10-27T04:41:02Z` / `2026-10-27 12:41:02 Asia/Shanghai`.
- SHA-256: `0C:39:AD:4F:F5:1A:A8:15:5F:7C:4E:DF:19:79:C7:1E:AB:8A:40:AB:0A:AC:16:3D:4C:2D:8D:93:F3:54:B7:14`.
- Certbot and ACME versions: `5.4.0`; dedicated venv dependencies passed `pip check`.
- Saved renewal settings: production ACME directory, `preferred_profile=shortlived`,
  webroot authenticator, ECDSA, and the dedicated nginx reload hook.
- Next timer at last check: `2026-10-21 02:00:01 Asia/Shanghai`.

Certificates, account data and ACME logs stay root-only on the server. This report
contains no private keys, account secrets, environment values, tokens or student data.

## Required Public Firewall Action

Confirm/add an **inbound allow** rule on this instance's Tencent Lighthouse public
firewall or attached CVM security group, whichever applies:

| Protocol | Destination port | Source | Action |
| --- | --- | --- | --- |
| TCP | 443 | 0.0.0.0/0 | Allow |

Preserve the already-working TCP 80 rule and the existing SSH/22 policy exactly.
Do not expose 8793, 8796, SQLite, data storage, UDP, IPv6 or unrelated port ranges.
Check rule priority if a higher-priority deny exists. Cloud firewall state was not
read with cloud credentials; the upstream-block diagnosis is inferred from public
timeouts, working 80, local 443 success, and the permissive host firewall.

After the rule is effective, rerun `verify_public.py` with the same report path
from Windows, without a TLS bypass. Maintenance acceptance expects HTTPS `/` = 503,
all listed non-maintenance HTTPS paths = 404, and a valid exact-IP CA chain.
Do not run this maintenance-only verifier after an approved gateway cutover;
its route expectations intentionally reject an exposed application.

## Handoff Paths and Gateway Standby

- Active nginx main config: `/etc/nginx/nginx.conf`.
- Its only HTTP include: `/etc/nginx/ip-maintenance/active.conf`.
- Static public root: `/var/www/rehab-ip-maintenance`; no app/data tree is served.
- ACME webroot: `/var/www/rehab-ip-acme`.
- Production full chain: `/etc/letsencrypt-rehab-ip/production/live/YOUR_SERVER_IP/fullchain.pem`.
- Dedicated reload hook: `/usr/local/sbin/rehab-ip-cert-reload`.
- Timer/service: `rehab-ip-cert-renew.timer` / `rehab-ip-cert-renew.service`.
- Uploaded source: `/home/ubuntu/rehab-ip-https-20261020/`.
- Standby gateway config: `/home/ubuntu/rehab-ip-https-20261020/gateway-standby.conf`.

Standby targets loopback `127.0.0.1:8796` with external IP Host fixed to
`YOUR_SERVER_IP`, access logs off, 16 MiB per-request body limit, 360-second
read/send timeouts, request and response buffering off, HTTP/1.1 upstream
keepalive, and unchanged Range/If-Range forwarding. It was syntax-checked only;
no proxy traffic or application acceptance has been claimed.

An explicitly approved cutover must retain the existing port-80 ACME server and
replace only the maintenance port-443 server with the standby upstream/server.
Do not include both 443 default servers or rerun the maintenance activation phase.
Use `nginx -t` before any approved reload. The 553.7 MB sample must use the normal
chunk protocol with requests below 16 MiB; a whole-file request will be rejected.
The advertised 200 Mbps is peak bandwidth, not an achieved upload rate.

## Scope Preserved

Only this local deployment subdirectory and the isolated remote nginx/Certbot
resources were changed. No Windows source, original DB, tunnel, credentials,
application env, gateway secret/expiry, school context, cloud data or application
service was read or modified by this task. The pre-existing preview service was
confirmed to retain PID 46044 during nginx installation. Later promotion and
data restoration belong to the main agent, independently of this TLS work.
