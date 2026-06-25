#!/usr/bin/env bash
# up.sh — email-channel demo 的 HOST 端零件,冪等可重跑。
# 負責:GreenMail 容器 + SMTP STARTTLS shim。沙箱內的 CONNECT 橋與 gateway
# 重啟由 boot-stack.sh 處理(因為要在巢狀 netns + 合併 CA bundle 下做)。
#
# 為何需要 shim:Hermes 的 email adapter 寫死 IMAP4_SSL(隱式 TLS)+ SMTP STARTTLS,
# 無關閉開關;GreenMail 的 plain SMTP(3025)不廣告 STARTTLS,故 :3587 shim 補上
# STARTTLS 後原封轉投 3025。IMAPS(3993)Hermes 直連即可。
set -uo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
ok(){ printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$1"; }

# 1) 憑證(SAN=host.openshell.internal/172.18.0.1)— 不存在才產
if [ ! -f "$DIR/greenmail.p12" ]; then
  openssl genrsa -out ca.key 2048 2>/dev/null
  openssl req -x509 -new -key ca.key -days 825 -subj "/CN=NemoClaw Demo Mail CA" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.pem
  openssl genrsa -out mail.key 2048 2>/dev/null
  openssl req -new -key mail.key -subj "/CN=host.openshell.internal" -out mail.csr
  printf "subjectAltName=DNS:host.openshell.internal,DNS:localhost,IP:172.18.0.1,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n" > san.cnf
  openssl x509 -req -in mail.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 825 -extfile san.cnf -out mail.pem 2>/dev/null
  openssl pkcs12 -export -in mail.pem -inkey mail.key -certfile ca.pem -name greenmail -out greenmail.p12 -password pass:changeit
  chmod 644 greenmail.p12
  ok "憑證已產(CA + host.openshell.internal SAN)"
else ok "憑證已存在"; fi

# 2) GreenMail 容器(--restart unless-stopped 已能跨重開機;這裡只在缺席時建)
if ! docker ps --format '{{.Names}}' | grep -q '^greenmail-demo$'; then
  docker rm -f greenmail-demo >/dev/null 2>&1 || true
  docker run -d --name greenmail-demo --restart unless-stopped \
    -p 172.18.0.1:3025:3025 -p 127.0.0.1:3025:3025 \
    -p 172.18.0.1:3993:3993 -p 127.0.0.1:3993:3993 \
    -p 127.0.0.1:3143:3143 -p 127.0.0.1:8081:8080 \
    -v "$DIR/greenmail.p12:/home/greenmail/greenmail.p12:ro" \
    -e GREENMAIL_OPTS='-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.tls.keystore.file=/home/greenmail/greenmail.p12 -Dgreenmail.tls.keystore.password=changeit -Dgreenmail.auth.disabled -Dgreenmail.verbose' \
    greenmail/standalone:latest >/dev/null
  ok "GreenMail 容器已啟動"
else ok "GreenMail 容器已在跑"; fi

# 3) venv(aiosmtpd)
if [ ! -x "$DIR/.venv/bin/python" ]; then
  uv venv .venv -q && uv pip install -q --python .venv/bin/python aiosmtpd
  ok "venv + aiosmtpd 已建"
else ok "venv 已存在"; fi

# 4) SMTP STARTTLS shim(:3587)
if ! ss -tln 2>/dev/null | grep -q ':3587 '; then
  pkill -f 'smtp-shim.py' 2>/dev/null || true
  nohup "$DIR/.venv/bin/python" "$DIR/smtp-shim.py" >"$DIR/shim.log" 2>&1 & disown
  for i in 1 2 3 4 5; do ss -tln 2>/dev/null | grep -q ':3587 ' && break; sleep 1; done
  ss -tln 2>/dev/null | grep -q ':3587 ' && ok "SMTP STARTTLS shim :3587" || bad "shim 沒起來(看 shim.log)"
else ok "SMTP STARTTLS shim :3587 已在跑"; fi

echo "  host 端就緒。沙箱內的 CONNECT 橋 + gateway(含 mail CA)請跑 boot-stack.sh,或見 README。"
