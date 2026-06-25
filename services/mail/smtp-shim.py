#!/usr/bin/env python3
# smtp-shim.py — STARTTLS-capable SMTP front for GreenMail.
# Hermes 的 email adapter 寫死 smtplib.SMTP + starttls()+login()(驗證憑證、無開關),
# 但 GreenMail 的 plain SMTP(3025)不支援 STARTTLS → 本 shim 在 :3587 提供
# STARTTLS(用 mail.pem/mail.key,SAN=host.openshell.internal)+ 任意帳密 AUTH,
# 收到的信原封轉投 GreenMail 127.0.0.1:3025,落進 IMAP inbox。
import asyncio
import smtplib
import ssl
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult

HERE = Path(__file__).resolve().parent
GREENMAIL = ("127.0.0.1", 3025)
LISTEN = ("0.0.0.0", 3587)


class RelayHandler:
    async def handle_DATA(self, server, session, envelope):
        try:
            with smtplib.SMTP(*GREENMAIL, timeout=15) as s:
                s.sendmail(envelope.mail_from, envelope.rcpt_tos, envelope.original_content)
        except Exception as e:  # noqa: BLE001 — 回 SMTP 4xx 讓寄件端知道
            return f"451 relay to greenmail failed: {e}"
        print(f"[shim] relayed {envelope.mail_from} -> {envelope.rcpt_tos}", flush=True)
        return "250 OK relayed"


def allow_any(server, session, envelope, mechanism, auth_data):
    return AuthResult(success=True)


tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain(HERE / "mail.pem", HERE / "mail.key")

controller = Controller(
    RelayHandler(),
    hostname=LISTEN[0],
    port=LISTEN[1],
    tls_context=tls,           # 廣告 STARTTLS
    authenticator=allow_any,   # 廣告 AUTH,接受任何帳密(demo)
    auth_require_tls=True,
)
controller.start()
print(f"[shim] SMTP STARTTLS shim on {LISTEN[0]}:{LISTEN[1]} -> greenmail {GREENMAIL[0]}:{GREENMAIL[1]}", flush=True)
asyncio.new_event_loop().run_forever()
