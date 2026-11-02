#!/bin/zsh
# 本机执行：打包当前代码 → 上传 → 远端 remote_deploy.sh（nginx :80 → 127.0.0.1:9181）
# 用法：SSHPASS='<root 密码>' deploy/simple_http/push_and_deploy.sh <服务器IP> [密码 JSON 文件]
set -euo pipefail
HOST="${1:?服务器 IP}"
PASSWORDS="${2:-.runtime/local_run/pilot_passwords.json}"
cd "${0:A:h}/../.."
STAGE="$(mktemp -d /private/tmp/rxdeploy.XXXXXX)"
git -c core.quotepath=off ls-files -co --exclude-standard -- src scripts configs data deploy pyproject.toml > "$STAGE/files.txt"
printf 'models/face_detection_yunet_2023mar.onnx\nmodels/LICENSE.yunet\n' >> "$STAGE/files.txt"
COPYFILE_DISABLE=1 tar czf "$STAGE/src.tgz" --no-xattrs -T "$STAGE/files.txt"
shasum -a 256 "$STAGE/src.tgz"
MUX=(-o ControlMaster=auto -o ControlPath=/private/tmp/rxmux-%C -o ControlPersist=900)
SSH=(sshpass -e ssh "${MUX[@]}" -o ConnectTimeout=20 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new "root@$HOST")
SCP=(sshpass -e scp "${MUX[@]}" -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
"${SSH[@]}" 'install -d -m 700 /root/rx'
"${SCP[@]}" "$STAGE/src.tgz" deploy/simple_http/remote_deploy.sh "root@$HOST:/root/rx/"
[ -f "$PASSWORDS" ] && "${SCP[@]}" "$PASSWORDS" "root@$HOST:/root/rx/pilot_passwords.json"
"${SSH[@]}" 'chmod 600 /root/rx/* && bash /root/rx/remote_deploy.sh'
curl -sS -o /dev/null -w "外网 http://$HOST/demo2/login -> %{http_code}\n" --noproxy '*' "http://$HOST/demo2/login"
rm -rf "$STAGE"
