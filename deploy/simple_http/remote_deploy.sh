#!/bin/bash
# 在目标服务器上以 root 运行：bash /root/rx/remote_deploy.sh
# 前置：/root/rx/src.tgz（代码包）、/root/rx/pilot_passwords.json（600 权限，测试账号密码）
set -euo pipefail

APP_DIR=/opt/rehabaffect
DATA_DIR=/var/lib/rehabaffect/data
ETC_DIR=/etc/rehabaffect
APP_PORT=9181
STAGE=/root/rx

echo "== 1. 系统依赖"
dnf install -y nginx ffmpeg python3.12 python3.12-pip >/tmp/rx_dnf.log 2>&1 || { tail -20 /tmp/rx_dnf.log; exit 1; }
command -v ffmpeg ffprobe nginx python3.12
ffmpeg -version | head -1
# Chinese font for Word/PDF report charts and embedded PDF text (optional: reports fall back to CID font / code labels).
dnf install -y wqy-zenhei-fonts >/tmp/rx_dnf_fonts.log 2>&1 || dnf install -y google-noto-sans-cjk-ttc-fonts >>/tmp/rx_dnf_fonts.log 2>&1 || echo "WARN 未安装中文字体，报告图表使用代码标签"
# Noto CJK is CFF (reportlab cannot embed it); Droid Sans Fallback is TrueType and gets embedded in PDF text.
dnf install -y google-droid-sans-fonts >>/tmp/rx_dnf_fonts.log 2>&1 || echo "WARN 未安装 TrueType 中文字体，PDF 正文使用内置 CID 字体"

echo "== 2. 运行用户与目录"
id rehabaffect >/dev/null 2>&1 || useradd --system --home-dir /var/lib/rehabaffect --shell /sbin/nologin rehabaffect
install -d -m 755 "$APP_DIR"
install -d -m 700 -o rehabaffect -g rehabaffect /var/lib/rehabaffect "$DATA_DIR"
install -d -m 750 -g rehabaffect "$ETC_DIR"

echo "== 3. 代码"
if [ -d "$APP_DIR/src" ]; then
  backup="/var/lib/rehabaffect-code-backup/$(date +%Y%m%d%H%M%S)"
  install -d -m 700 "$backup"
  cp -a "$APP_DIR/src" "$APP_DIR/scripts" "$backup/" 2>/dev/null || true
  echo "旧代码已备份到 $backup"
fi
tar xzf "$STAGE/src.tgz" -C "$APP_DIR" --no-same-owner
chown -R root:root "$APP_DIR"
chmod -R go-w "$APP_DIR"
# 模型文件需被运行用户读取
chmod 644 "$APP_DIR"/models/*

echo "== 4. Python 环境"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3.12 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q -i https://mirrors.tencentyun.com/pypi/simple --upgrade pip \
  || "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -i https://mirrors.tencentyun.com/pypi/simple -r "$APP_DIR/deploy/cloud/requirements.txt" \
  || "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/deploy/cloud/requirements.txt"
"$APP_DIR/.venv/bin/python" -c "import numpy, cv2, cryptography, docx; print('deps ok', cv2.__version__)"

echo "== 5. 环境变量（密钥只生成一次，之后保留）"
ENV_FILE="$ETC_DIR/app.env"
if [ ! -f "$ENV_FILE" ]; then
  key=$("$APP_DIR/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  prefix="rx-$("$APP_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_hex(6))")-"
  umask 077
  cat >"$ENV_FILE" <<EOF
PYTHONPATH=$APP_DIR/src
REHAB_DEMO2_DB_PATH=$DATA_DIR/demo2.sqlite3
REHAB_DEMO2_DOSSIER_KEY=$key
REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX=$prefix
REHAB_FFMPEG=/usr/bin/ffmpeg
REHAB_FFPROBE=/usr/bin/ffprobe
EOF
  chgrp rehabaffect "$ENV_FILE"; chmod 640 "$ENV_FILE"
fi

echo "== 6. systemd 服务（仅监听 127.0.0.1:$APP_PORT）"
cat >/etc/systemd/system/rehabaffect-web.service <<EOF
[Unit]
Description=RehabAffect classroom video analysis (behind nginx :80)
After=network.target

[Service]
Type=simple
User=rehabaffect
Group=rehabaffect
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
UMask=0077
ExecStart=$APP_DIR/.venv/bin/python -m rehab_affect.scenario_lab_server --host 127.0.0.1 --port $APP_PORT --policy rule
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=45
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/rehabaffect
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable rehabaffect-web.service >/dev/null
systemctl restart rehabaffect-web.service
for i in $(seq 1 30); do
  curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/demo2/login" && break
  sleep 2
done
curl -fsS -o /dev/null -w "app /demo2/login -> %{http_code}\n" "http://127.0.0.1:$APP_PORT/demo2/login"

echo "== 7. 测试账号密码"
if [ -f "$STAGE/pilot_passwords.json" ]; then
  systemctl stop rehabaffect-web.service
  install -m 600 -o rehabaffect -g rehabaffect "$STAGE/pilot_passwords.json" /var/lib/rehabaffect/.pilot_passwords.json
  sudo -u rehabaffect env $(grep -v '^#' "$ENV_FILE" | xargs) \
    "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/set_pilot_passwords.py" \
    --db "$DATA_DIR/demo2.sqlite3" --passwords-file /var/lib/rehabaffect/.pilot_passwords.json || { rm -f /var/lib/rehabaffect/.pilot_passwords.json; exit 1; }
  rm -f /var/lib/rehabaffect/.pilot_passwords.json
  shred -u "$STAGE/pilot_passwords.json" 2>/dev/null || rm -f "$STAGE/pilot_passwords.json"
  systemctl start rehabaffect-web.service
  for i in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/demo2/login" && break
    sleep 2
  done
fi

echo "== 8. nginx :80 反向代理"
# 发行版 nginx.conf 自带 listen 80 的默认 server，会与本站点冲突：备份后移除该块
if grep -q "listen       80;" /etc/nginx/nginx.conf; then
  cp -a /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%Y%m%d%H%M%S)"
  "$APP_DIR/.venv/bin/python" - <<'PY'
import re
from pathlib import Path
path = Path("/etc/nginx/nginx.conf")
text = path.read_text()
start = text.find("    server {")
if start != -1:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                text = text[:start] + text[index + 1:]
                break
path.write_text(text)
PY
fi
cat >/etc/nginx/conf.d/rehabaffect.conf <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # 上传分片 4 MiB，录制上传最大 256 MiB
    client_max_body_size 300m;
    client_body_buffer_size 8m;
    proxy_request_buffering off;
    proxy_buffering off;

    access_log /var/log/nginx/rehabaffect_access.log;

    location = / {
        return 302 /demo2/login;
    }

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
EOF
nginx -t
systemctl enable nginx >/dev/null
systemctl restart nginx

if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http && firewall-cmd --reload
fi

echo "== 9. 自检"
systemctl is-active rehabaffect-web.service nginx
ss -ltnp | grep -E ":80 |:$APP_PORT "
curl -sS -o /dev/null -w "nginx / -> %{http_code} %{redirect_url}\n" http://127.0.0.1/
curl -sS -o /dev/null -w "nginx /demo2/login -> %{http_code}\n" http://127.0.0.1/demo2/login
echo DEPLOY_DONE
