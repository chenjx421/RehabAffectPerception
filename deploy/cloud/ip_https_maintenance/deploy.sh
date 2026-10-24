#!/usr/bin/env bash
set -euo pipefail
umask 077

IP=YOUR_SERVER_IP
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STATE=/var/lib/rehab-ip-maintenance
CERTBOT=/opt/rehab-ip-certbot/bin/certbot

fail() { printf '%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'Run with sudo -n bash.'
exec 9>/run/lock/rehab-ip-maintenance.lock
flock -n 9 || fail 'Another maintenance deployment is running.'

certbot_args() {
    local environment=$1
    CB_PATHS=(--config-dir "/etc/letsencrypt-rehab-ip/$environment"
        --work-dir "/var/lib/letsencrypt-rehab-ip/$environment"
        --logs-dir "/var/log/letsencrypt-rehab-ip/$environment")
}

check_local_http() {
    local status
    status=$(curl --noproxy '*' -sS --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1/)
    [ "$status" = 404 ] || fail 'Port 80 must not serve a homepage.'
    curl --noproxy '*' -fsS --max-time 10 http://127.0.0.1/.well-known/acme-challenge/deployment-probe |
        grep -Fx 'rehab-ip-acme-probe-v1' >/dev/null
}

case "${1:-}" in
    prepare)
        [ ! -e "$STATE/prepared" ] || fail 'Already prepared; use the later phases.'
        [ -z "$(ss -H -lnt '( sport = :80 or sport = :443 )')" ] || fail '80/443 already occupied; no changes made.'
        if dpkg-query -W -f='${db:Status-Status}' nginx 2>/dev/null | grep -qx installed; then
            fail 'Existing nginx requires separate review; no changes made.'
        fi
        [ ! -e /etc/nginx/nginx.conf ] || fail 'Existing nginx configuration requires review.'
        [ ! -e /etc/systemd/system/nginx.service ] || fail 'Custom nginx unit requires review.'
        systemctl mask --runtime nginx.service
        export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
        apt-get update -q
        apt-get install -y --no-install-recommends nginx python3-venv ca-certificates curl
        python3 -m venv /opt/rehab-ip-certbot
        "$CERTBOT" --version 2>/dev/null || true
        /opt/rehab-ip-certbot/bin/python -m pip --isolated install --disable-pip-version-check \
            --index-url https://mirrors.cloud.tencent.com/pypi/simple --no-cache-dir 'certbot==5.4.0' 'acme==5.4.0'
        /opt/rehab-ip-certbot/bin/python -c 'import importlib.metadata as m; assert tuple(map(int, m.version("certbot").split(".")[:2])) >= (5, 4)'
        install -d -m 0700 "$STATE" /etc/letsencrypt-rehab-ip /var/lib/letsencrypt-rehab-ip /var/log/letsencrypt-rehab-ip
        for environment in staging production; do
            install -d -m 0700 "/etc/letsencrypt-rehab-ip/$environment" "/var/lib/letsencrypt-rehab-ip/$environment" "/var/log/letsencrypt-rehab-ip/$environment"
        done
        install -d -m 0755 /etc/nginx/ip-maintenance /var/www/rehab-ip-acme/.well-known/acme-challenge /var/www/rehab-ip-maintenance
        install -m 0644 "$SOURCE/nginx.conf" /etc/nginx/nginx.conf
        install -m 0644 "$SOURCE/http.conf" /etc/nginx/ip-maintenance/active.conf
        install -m 0644 "$SOURCE/index.html" /var/www/rehab-ip-maintenance/index.html
        install -m 0755 "$SOURCE/reload.sh" /usr/local/sbin/rehab-ip-cert-reload
        printf '%s\n' 'rehab-ip-acme-probe-v1' >/var/www/rehab-ip-acme/.well-known/acme-challenge/deployment-probe
        chmod 0644 /var/www/rehab-ip-acme/.well-known/acme-challenge/deployment-probe
        /usr/sbin/nginx -t
        systemctl unmask --runtime nginx.service
        systemctl enable --now nginx.service
        check_local_http
        touch "$STATE/prepared"
        "$CERTBOT" --version
        printf '%s\n' 'PREPARED: HTTP ACME only. No TLS or upstream is enabled.'
        ;;
    staging)
        [ -f "$STATE/prepared" ] || fail 'Run prepare first.'
        check_local_http
        certbot_args staging
        "$CERTBOT" certonly --staging --non-interactive --agree-tos --register-unsafely-without-email \
            --preferred-profile shortlived --preferred-challenges http --webroot \
            --webroot-path /var/www/rehab-ip-acme --ip-address "$IP" --cert-name "$IP" \
            --no-directory-hooks "${CB_PATHS[@]}"
        openssl x509 -in "/etc/letsencrypt-rehab-ip/staging/live/$IP/cert.pem" -noout -checkip "$IP"
        touch "$STATE/staging-succeeded"
        printf '%s\n' 'STAGING_SUCCEEDED: staging certificate is not installed in nginx.'
        ;;
    production)
        [ -f "$STATE/staging-succeeded" ] || fail 'A successful staging issuance is required.'
        check_local_http
        certbot_args production
        "$CERTBOT" certonly --server https://acme-v02.api.letsencrypt.org/directory \
            --non-interactive --agree-tos --register-unsafely-without-email \
            --preferred-profile shortlived --preferred-challenges http --webroot \
            --webroot-path /var/www/rehab-ip-acme --ip-address "$IP" --cert-name "$IP" \
            --no-directory-hooks --deploy-hook /usr/local/sbin/rehab-ip-cert-reload "${CB_PATHS[@]}"
        openssl x509 -in "/etc/letsencrypt-rehab-ip/production/live/$IP/cert.pem" -noout -checkip "$IP"
        openssl verify -purpose sslserver -verify_ip "$IP" \
            -CAfile /etc/ssl/certs/ca-certificates.crt \
            -untrusted "/etc/letsencrypt-rehab-ip/production/live/$IP/chain.pem" \
            "/etc/letsencrypt-rehab-ip/production/live/$IP/cert.pem"
        touch "$STATE/production-succeeded"
        printf '%s\n' 'PRODUCTION_SUCCEEDED: trusted IP certificate verified against system roots.'
        ;;
    activate)
        [ -f "$STATE/production-succeeded" ] || fail 'A verified production certificate is required.'
        if grep -Eq 'proxy_pass|fastcgi_pass|uwsgi_pass|grpc_pass|scgi_pass' /etc/nginx/ip-maintenance/active.conf; then
            fail 'An upstream was added. Explicit gateway cutover review is required.'
        fi
        [ ! -f "$STATE/activated" ] || fail 'Already activated; do not overwrite a later gateway cutover.'
        [ -z "$(ss -H -lnt '( sport = :443 )')" ] || fail 'Port 443 became occupied; review before activation.'
        install -m 0644 /etc/nginx/ip-maintenance/active.conf "$STATE/http-before-tls.conf"
        combined=$(mktemp /etc/nginx/ip-maintenance/.active.XXXXXX)
        cat "$SOURCE/http.conf" "$SOURCE/https.conf" >"$combined"
        chmod 0644 "$combined"
        mv -f "$combined" /etc/nginx/ip-maintenance/active.conf
        if ! /usr/sbin/nginx -t || ! systemctl reload nginx.service; then
            install -m 0644 "$STATE/http-before-tls.conf" /etc/nginx/ip-maintenance/active.conf
            /usr/sbin/nginx -t && systemctl reload nginx.service
            fail 'TLS activation failed; HTTP-only configuration restored.'
        fi
        status=$(curl --noproxy '*' -sS --max-time 15 --resolve "$IP:443:127.0.0.1" -o /dev/null -w '%{http_code}' "https://$IP/")
        [ "$status" = 503 ] || fail 'TLS maintenance status was not 503.'
        install -m 0644 "$SOURCE/rehab-ip-cert-renew.service" /etc/systemd/system/rehab-ip-cert-renew.service
        install -m 0644 "$SOURCE/rehab-ip-cert-renew.timer" /etc/systemd/system/rehab-ip-cert-renew.timer
        systemd-analyze verify /etc/systemd/system/rehab-ip-cert-renew.service /etc/systemd/system/rehab-ip-cert-renew.timer
        systemctl daemon-reload
        systemctl enable --now rehab-ip-cert-renew.timer
        touch "$STATE/activated"
        printf '%s\n' 'ACTIVATED: maintenance TLS only. Six-hour renewal checks enabled; public reachability still requires external verification.'
        ;;
    renewal-test)
        [ -f "$STATE/activated" ] || fail 'Activate production TLS first.'
        certbot_args production
        "$CERTBOT" renew --cert-name "$IP" --dry-run --run-deploy-hooks --non-interactive --no-random-sleep-on-renew \
            --no-directory-hooks --deploy-hook /usr/local/sbin/rehab-ip-cert-reload "${CB_PATHS[@]}"
        systemctl start rehab-ip-cert-renew.service
        systemctl show rehab-ip-cert-renew.service -p Result -p ExecMainStatus --no-pager
        ;;
    cleanup-probe)
        rm -f -- /var/www/rehab-ip-acme/.well-known/acme-challenge/deployment-probe
        ;;
    verify)
        printf 'CHECKED_AT_UTC='; date -u +%FT%TZ
        "$CERTBOT" --version
        /usr/sbin/nginx -t
        printf '%s\n' 'LISTENERS'
        ss -H -lntp
        printf '%s\n' 'CERTIFICATE_PUBLIC_METADATA'
        openssl x509 -in "/etc/letsencrypt-rehab-ip/production/live/$IP/cert.pem" -noout -issuer -serial -dates -fingerprint -sha256 -ext subjectAltName
        printf '%s\n' 'RENEWAL_TIMER'
        systemctl show rehab-ip-cert-renew.timer -p ActiveState -p NextElapseUSecRealtime --no-pager
        systemctl show rehab-ip-cert-renew.service -p Result -p ExecMainStatus --no-pager
        printf '%s\n' 'PUBLIC_HTTPS_LOCAL_CHECK'
        curl --noproxy '*' -sS --max-time 15 --resolve "$IP:443:127.0.0.1" -D - "https://$IP/"
        ;;
    *) fail 'Usage: deploy.sh prepare|staging|production|activate|renewal-test|cleanup-probe|verify' ;;
esac
