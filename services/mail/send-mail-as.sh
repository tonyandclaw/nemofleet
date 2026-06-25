#!/usr/bin/env bash
# send-mail-as.sh — 寄一封信給 hermes@demo.local,可指定寄件者(資安 demo 用:未授權/自動寄件者)。
# 用法:send-mail-as.sh <from-addr> "<主旨>" "<內文>" [extra-header]
#   extra-header 可選,例:'Auto-Submitted: auto-generated'
set -euo pipefail
cd "$(dirname "$0")"
FROM="${1:?need from addr}"; SUBJ="${2:?need subject}"; BODY="${3:?need body}"; EXTRA="${4:-}"
.venv/bin/python - "$FROM" "$SUBJ" "$BODY" "$EXTRA" <<'PY'
import smtplib, ssl, sys
from email.message import EmailMessage
frm, subj, body, extra = sys.argv[1:5]
ctx = ssl.create_default_context(cafile='ca.pem')
m = EmailMessage()
m['From'] = frm; m['To'] = 'hermes@demo.local'; m['Subject'] = subj
if extra:
    k, _, v = extra.partition(':'); m[k.strip()] = v.strip()
m.set_content(body, charset='utf-8')
s = smtplib.SMTP('127.0.0.1', 3587, timeout=15)
s.starttls(context=ctx); s.login('demo', 'x')   # shim 接受任意 AUTH
s.send_message(m); s.quit()
print(f"✓ 已寄出:{frm} → hermes@demo.local  主旨「{subj}」" + (f"  [{extra}]" if extra else ""))
PY
