#!/usr/bin/env bash
set -euo pipefail
umask 077

SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ACTIVE=/etc/nginx/ip-maintenance/active.conf
STATE=/var/lib/rehab-ip-maintenance
fail() { printf '%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'Run with sudo -n bash.'
exec 9>/run/lock/rehab-ip-maintenance.lock
flock -n 9 || fail 'Another ingress deployment is running.'
systemctl is-active --quiet rehabaffect-app.service || fail 'Application is not active.'
systemctl is-active --quiet rehabaffect-gateway.service || fail 'Gateway is not active.'
[ "$(ss -H -lnt '( sport = :8796 )' | awk '{print $4}')" = 127.0.0.1:8796 ] || fail 'Gateway must listen only on 127.0.0.1:8796.'
status=$(curl --noproxy '*' -sS --max-time 10 -H 'Host: YOUR_SERVER_IP' -o /dev/null -w '%{http_code}' http://127.0.0.1:8796/invite)
[ "$status" = 200 ] || fail 'Gateway invite page is not ready.'
if grep -Eq 'proxy_pass|fastcgi_pass|uwsgi_pass|grpc_pass|scgi_pass' "$ACTIVE"; then
    fail 'An upstream is already active; do not overwrite it.'
fi
backup="$STATE/maintenance-before-gateway-$(date -u +%Y%m%dT%H%M%SZ).conf"
install -m 0600 "$ACTIVE" "$backup"
candidate=$(mktemp /etc/nginx/ip-maintenance/.gateway.XXXXXX)
trap 'rm -f -- "$candidate"' EXIT
cat "$SOURCE/http.conf" "$SOURCE/gateway-standby.conf" >"$candidate"
chmod 0644 "$candidate"
mv -f "$candidate" "$ACTIVE"

restore_maintenance() {
    install -m 0644 "$backup" "$ACTIVE"
    /usr/sbin/nginx -t
    systemctl reload nginx.service
}

if ! /usr/sbin/nginx -t || ! systemctl reload nginx.service; then
    restore_maintenance
    fail 'Cutover failed; maintenance configuration restored.'
fi
# Old workers may finish in-flight requests while new workers start accepting.
ready=false
for attempt in 1 2 3 4 5; do
    status=$(curl --noproxy '*' -sS --max-time 10 --resolve YOUR_SERVER_IP:443:127.0.0.1 -o /dev/null -w '%{http_code}' https://YOUR_SERVER_IP/invite) || status=000
    if [ "$status" = 200 ]; then ready=true; break; fi
    sleep 1
done
if [ "$ready" != true ]; then
    restore_maintenance
    fail 'Local trusted-TLS gateway verification failed; maintenance restored.'
fi
printf 'GATEWAY_CUTOVER_SUCCEEDED\nMAINTENANCE_BACKUP=%s\n' "$backup"
printf 'ACTIVE_CONFIG_SHA256='
sha256sum "$ACTIVE" | awk '{print $1}'
printf 'CHECKED_AT_UTC='
date -u +%FT%TZ
