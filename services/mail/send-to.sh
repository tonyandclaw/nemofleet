#!/usr/bin/env bash
# send-to.sh — 寄一封信給「任意收件者」(經 STARTTLS shim :3587 → GreenMail)。
# 用途:GUI 新增通知對象時,寄歡迎/測試信給該管理者,證明 Email 通道可達(收件匣可驗證)。
# 用法:send-to.sh <to-addr> "<主旨>" "<內文>" [from-addr]
set -euo pipefail
cd "$(dirname "$0")"
TO="${1:?need to}"; SUBJ="${2:?need subject}"; BODY="${3:?need body}"; FROM="${4:-nemoclaw@demo.local}"
.venv/bin/python - "$TO" "$SUBJ" "$BODY" "$FROM" <<'PY'
import smtplib, ssl, sys
from email.message import EmailMessage
to, subj, body, frm = sys.argv[1:5]
ctx = ssl.create_default_context(cafile='ca.pem')
m = EmailMessage()
m['From'] = frm; m['To'] = to; m['Subject'] = subj
m.set_content(body, charset='utf-8')
s = smtplib.SMTP('127.0.0.1', 3587, timeout=15)
s.starttls(context=ctx); s.login('demo', 'x')   # shim 接受任意 AUTH
s.send_message(m); s.quit()
print(f"✓ sent to {to}: {subj}")
PY
