#!/usr/bin/env bash
set -euo pipefail
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx.service
/usr/bin/logger -t rehab-ip-cert-renew -- 'Validated nginx configuration and reloaded the active certificate.'
