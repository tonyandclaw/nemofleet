#!/usr/bin/env bash
# read-inbox.sh — 讀 tony@demo.local 信箱(demo 時投影這個,看 Hermes 的回信)。
# 用法:read-inbox.sh [數量,預設 3]
set -euo pipefail
cd "$(dirname "$0")"
.venv/bin/python - "${1:-3}" <<'PY'
import imaplib, ssl, email, sys
from email import policy
from email.header import decode_header
n = int(sys.argv[1])
ctx = ssl.create_default_context(cafile='ca.pem')
im = imaplib.IMAP4_SSL('127.0.0.1', 3993, ssl_context=ctx, timeout=10)
im.login('tony@demo.local', 'x'); im.select('INBOX')
typ, d = im.uid('search', None, 'ALL')
allu = d[0].split()
def dh(s): return ''.join(p.decode(e or 'utf-8') if isinstance(p, bytes) else p for p, e in decode_header(s or ''))
def is_onboarding(txt):  # Hermes 的 /sethome onboarding 系統提示,非真正回覆,demo 不顯示
    return 'No home channel is set' in txt or 'Type /sethome' in txt
# 由新到舊掃,跳過 onboarding 提示,收滿 n 封真正回覆;再依時間正序印出
picked = []
for u in reversed(allu):
    t, md = im.uid('fetch', u, '(RFC822)')
    m = email.message_from_bytes(md[0][1], policy=policy.default)
    b = m.get_body(preferencelist=('plain', 'html'))
    if b and is_onboarding(b.get_content()):
        continue
    picked.append((m, b))
    if len(picked) >= n:
        break
for m, b in reversed(picked):
    print("="*56)
    print("From   :", dh(m['From']))
    print("Subject:", dh(m['Subject']))
    print("-"*56)
    print((b.get_content() if b else "(無內文)").strip())
im.logout()
PY
