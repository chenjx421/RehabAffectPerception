# Isolated IP HTTPS Maintenance

Status update: the user explicitly authorized gateway cutover on 2026-10-20.
It completed at 22:00 Asia/Shanghai; see `gateway_cutover_result_20261020.md` and
`gateway_public_verification.json`. The maintenance-only verifier and activation
phases below are historical setup procedures, not current acceptance commands.

Runtime hold: PublicSample01 uploaded in 206.859 seconds; analysis is running.
Do not run deployment/cutover scripts,
edit ingress, restart nginx/gateway/app, or repeat gateway-denial probes. Latest
main-agent acceptance and exact 0600-to-0640 permission repair are recorded in
`gateway_cutover_result_20261020.md`; that latest revision is local-only.

Target: `YOUR_SERVER_IP`. This directory does not authorize gateway cutover.
Do not run an application, mount application data, or add an upstream here.
The existing SSH transport pins the console-verified host before authentication.
Never read or print private keys, cloud credentials, application env, or databases.

## Deployment Phases

Upload only these files with `scripts/cloud_ssh_operator.py` into a private remote
directory. Run `sudo -n bash /absolute/upload/path/deploy.sh PHASE` in order:

1. `prepare`: refuse occupied 80/443 or existing nginx; install a masked nginx,
   a dedicated Certbot 5.4.0 venv, access-log-free configuration, and HTTP ACME.
2. Verify the HTTP challenge probe from outside the cloud instance.
3. `staging`: obtain a staging shortlived IP certificate in its own private tree.
4. `production`: require successful staging; issue and verify a public certificate.
5. `activate`: install maintenance-only TLS and the six-hour renewal timer.
6. Verify HTTPS externally without any trust bypass; test blocked app/data routes.
7. `renewal-test`: staging dry run using production renewal settings and deploy
   hook; the hook reloads the current production certificate, never staging TLS.
8. `cleanup-probe`, then `verify` for public certificate metadata and unit states.

Only port 80 HTTP-01 challenge files are public over HTTP. All other HTTP paths
return 404, without redirect. HTTPS `/` returns 503, `Retry-After: 300`, and a
fixed maintenance document. Other HTTPS paths return 404. No nginx access logs
are enabled. ACME logs remain root-only; do not copy their raw contents to reports.

The runtime is `/opt/rehab-ip-certbot`, separate from the application venv.
Certbot and ACME are pinned to 5.4.0 and installed over verified HTTPS from the
Tencent package mirror; no trusted-host or TLS-verification bypass is used.
Certificate/account trees are `/etc/letsencrypt-rehab-ip/{staging,production}`;
private work/log trees have corresponding names under `/var/lib` and `/var/log`.
Certificate private keys stay on the server. No contact email is invented;
the ACME account is registered without one, and renewal needs operational monitoring.
The timer checks at 00/06/12/18 UTC with up to five minutes jitter, including missed
runs after reboot. Certbot's additional random sleep is disabled because the
systemd timer already provides jitter. Certbot chooses when renewal is due; do not force production
renewals every six hours. Reload runs only after successful issuance/renewal.

## Firewall and Boundaries

Never change port 22, enable/reset a firewall, or modify unrelated services.
If an existing host firewall is active, review it before adding only TCP 80/443.
If the Tencent public firewall/security group blocks traffic, request inbound
TCP 80 and TCP 443 from `0.0.0.0/0`. HTTP-01 validators cannot use a fixed source
allowlist. Do not add application ports, UDP rules, IPv6, or broad port ranges.
Do not claim public success from a loopback request or certificate issuance alone.

Future gateway switching needs explicit main-agent authorization and its own
review. `activate` refuses a second activation or an existing proxy configuration.
`gateway-standby.conf` is an unreferenced template, not an enabled site. It keeps
the external IP Host, targets only loopback 8796, permits 16 MiB request bodies,
uses 360-second proxy read/send timeouts and HTTP/1.1 upstream keepalive, disables
request/response buffering and cache, and forwards Range/If-Range unchanged.
Do not include it alongside the maintenance HTTPS server: a later approved
cutover must replace only the 443 server and retain the HTTP ACME server.
The static maintenance root is not the app checkout and contains no student data.
Windows sources, DB, tunnel, cloud preview, SSH, and existing firewall policy are
outside this deployment's write scope.

## Official References

- https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html
- https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates
- https://cloud.tencent.com/document/api/243/19630

The Tencent guidance allows temporary public-IP testing without domain filing;
this maintenance deployment is not an approval for formal application launch.
