#!/usr/bin/env python3
# wi_approval.py — real per-action human-approval tokens. Replaces the old flat shared-secret
# check (any non-empty string "approved" a rollback) with a token that is single-use, expires,
# and is cryptographically bound to the exact action+params it was approved for — so a leaked or
# replayed token can't be used to approve a different rollback than the one a human actually saw.
#
# issue() runs on team-lead's side, only after a human has actually approved a specific action
# over Telegram (see skills/hermes/firmware-approval/SKILL.md) — issuer identifies that human, not
# the node. verify() runs on worker-c's side. Both share one HMAC key (services/bridge/.approval-key,
# zone C + team-lead only). Pure functions, no I/O — the caller supplies the key and the
# already-used-nonce check (see worker-itops.py's _approval_verify_and_record for how worker-c
# persists nonces + an approval-history audit trail for traceability).
import base64, hashlib, hmac, json, secrets, time


def _canon(params):
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s):
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _key_bytes(key):
    return key.encode() if isinstance(key, str) else key


def issue(action, params, issuer, key, ttl_s=300):
    """呼叫端須自行確保:已經拿到一個真人對「這個 action + 這組 params」的明確核准,issuer 是
    可辨識該真人身分的字串(例如 Telegram user id/username),不是節點名稱 —— 這樣 worker-c 端的
    稽核紀錄才查得到「誰」核准的,而不是只知道「team-lead 核准了」。"""
    payload = {
        "act": action,
        "params_hash": hashlib.sha256(_canon(params).encode()).hexdigest(),
        "iss": issuer,
        "iat": int(time.time()),
        "exp": int(time.time()) + int(ttl_s),
        "nonce": secrets.token_hex(16),
    }
    body = _b64u(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = hmac.new(_key_bytes(key), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify(token, action, params, key, seen_nonce):
    """seen_nonce(nonce) -> bool:呼叫端提供的判斷式,回報這個 nonce 是否已經核准使用過(單次
    核准)。這支函式本身不寫入任何狀態 —— 通過驗證後,呼叫端仍必須自己把 claims['nonce'] 記下來
    (見 worker-itops.py),否則同一個 token 可以被重放。"""
    try:
        body, sig = (token or "").rsplit(".", 1)
        if not body or not sig:
            raise ValueError
    except ValueError:
        return {"ok": False, "error": "approval_token 格式不正確"}
    want = hmac.new(_key_bytes(key), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, want):
        return {"ok": False, "error": "approval_token 簽章不符(密鑰不對或內容被竄改)"}
    try:
        payload = json.loads(_b64u_decode(body))
    except Exception:
        return {"ok": False, "error": "approval_token payload 無法解析"}
    if payload.get("act") != action:
        return {"ok": False, "error": "approval_token 綁定的動作(%s)跟這次要做的(%s)不符" % (payload.get("act"), action)}
    if payload.get("params_hash") != hashlib.sha256(_canon(params).encode()).hexdigest():
        return {"ok": False, "error": "approval_token 綁定的參數跟這次呼叫的參數不符(這個核准是核給別的動作內容的)"}
    if time.time() > payload.get("exp", 0):
        return {"ok": False, "error": "approval_token 已過期(核准有時效)"}
    if seen_nonce(payload.get("nonce", "")):
        return {"ok": False, "error": "approval_token 已被使用過(單次核准,不可重放)"}
    return {"ok": True, "claims": payload}
