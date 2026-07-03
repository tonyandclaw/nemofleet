#!/usr/bin/env python3
# send.py — send one email via the real SMTP relay (SMTP_* from .env). No mock.
# Usage: send.py <to> <subject> <body> [from]
import os, sys, ssl, smtplib
from email.message import EmailMessage

if len(sys.argv) < 4:
    sys.exit("usage: send.py <to> <subject> <body> [from]")
to, subj, body = sys.argv[1], sys.argv[2], sys.argv[3]
frm = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("SMTP_FROM", "")
host = os.environ.get("SMTP_HOST", "")
port = int(os.environ.get("SMTP_PORT", "587") or "587")
user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", "")
if not host or not frm:
    sys.exit("[send] SMTP_HOST / SMTP_FROM unset — configure the real SMTP relay in .env")

m = EmailMessage()
m["From"], m["To"], m["Subject"] = frm, to, subj
m.set_content(body, charset="utf-8")
s = smtplib.SMTP(host, port, timeout=20)
try:
    if os.environ.get("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no"):
        s.starttls(context=ssl.create_default_context())
    if user or pw:
        s.login(user, pw)
    s.send_message(m)
finally:
    s.quit()
print(f"✓ sent to {to}: {subj}")
