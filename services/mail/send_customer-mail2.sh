#!/usr/bin/env bash
# send-customer-mail.sh — demo 觸發:以「客戶」身分寄一封信給 Hermes,觀察它收信反應。
# 用法:send-customer-mail.sh ["主旨"] ["內文"]
# 重點:用正規 MIME(charset=utf-8),否則 Hermes 解析器會 "unknown encoding: unknown-8bit"。
set -euo pipefail
cd "$(dirname "$0")"
SUBJ="${1:-IT詢問：IT 報修RT-AX89X 設定怪怪的}"
BODY="${2:-Hermes 你好，我是IT Tony2。
RT-AX89X 設定怪怪的,SSH 好像被打開了密碼登入,syslog 也收不到 log,請比對核准基準處理
麻煩你回覆，謝謝。}"

.venv/bin/python - "$SUBJ" "$BODY" <<'PY'
import smtplib, ssl, sys
from email.message import EmailMessage
subj, body = sys.argv[1], sys.argv[2]
ctx = ssl.create_default_context(cafile='ca.pem')
m = EmailMessage()
m['From'] = 'tony@demo.local'; m['To'] = 'hermes@demo.local'; m['Subject'] = subj
m.set_content(body, charset='utf-8')
s = smtplib.SMTP('127.0.0.1', 3587, timeout=15)
s.starttls(context=ctx); s.login('tony@demo.local', 'x'); s.send_message(m); s.quit()
print(f"✓ 已寄出:tony@demo.local → hermes@demo.local  主旨「{subj}」")
print("  Hermes 會在 ≤20s 內輪詢抓信,經 Azure Kimi 生成後回信到 tony 信箱。")
print("  讀回信:bash mail-demo/read-inbox.sh")
PY
