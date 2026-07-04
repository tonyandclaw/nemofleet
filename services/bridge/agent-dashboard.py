#!/usr/bin/env python3
# agent-dashboard.py — NemoClaw Multi-Agent 即時狀態儀表板(host web server, Apple/enterprise-grade)。
# http://127.0.0.1:8899 → 整個 agent stack 活狀態 + 可操作控制 + 即時事件流/趨勢/告警/巡檢歷史。
# 渲染:側欄 menu + hash 路由分頁;分區 memo(內容沒變不重繪→無閃爍)。唯讀為主、每 call timeout、整體快取 ~8s、單項失敗降級。
# X-Bridge-Token 只 server 端用,不入 HTML/JSON。POST /api/action?do=cve|source|refresh(localhost only)。
import json, os, re, shlex, subprocess, threading, time, hashlib, secrets
from http.cookies import SimpleCookie
try:
    import ipaddress
except Exception:
    ipaddress = None
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    import yaml  # 解析 openshell policy get 的 YAML(唯讀政策檢視)
except Exception:
    yaml = None
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("DASHBOARD_PORT", "8899"))
import glob as _glob
DIR = os.environ.get("NEMOFLEET_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (services/bridge/<file> → up 3)
BRIDGE = f"{DIR}/services/bridge"
MAIL = f"{DIR}/services/mail"
WEB_DIR = f"{BRIDGE}/web"   # React + Chart.js SPA (served at /app; talks to the same /api/* endpoints)
_WEB_CT = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
           ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
           ".map": "application/json"}
TOKEN = ""
try:
    TOKEN = open(f"{BRIDGE}/.bridge-token").read().strip()
except Exception:
    pass
# 只有明確宣告前面有可信 reverse proxy 時才信 X-Forwarded-For(否則任何客戶端可偽造繞過 IP 白名單/登入鎖)
TRUST_XFF = os.environ.get("DASH_TRUST_XFF", "").lower() in ("1", "true", "yes")
# TLS 是否啟用在啟動時即確定(cookie 的 Secure flag 與 __main__ 共用同一判定)
DASH_TLS_ON = bool(os.environ.get("DASH_TLS") and os.path.exists(f"{BRIDGE}/dash-cert.pem") and os.path.exists(f"{BRIDGE}/dash-key.pem"))
NVM = os.environ.get("NEMOFLEET_NODE_BIN") or next(iter(sorted(_glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")), reverse=True)), "")
ENV = dict(os.environ, PATH=(NVM + ":" if NVM else "") + os.environ.get("PATH", ""))
WD = "/sandbox/.hermes/workspace/it-task"
_CACHE = {"ts": 0, "data": None}
_COLLECT_TTL = int(os.environ.get("DASH_COLLECT_TTL", "5"))   # SWR 背景刷新間隔(秒);搭配 streamer 5s + 前端 5s 輪詢
HISTORY = []
try:                                                  # 真 NemoClaw/worker 家族品牌圖(🦞 Claw logo)
    BRAND_SVG = open(f"{BRIDGE}/assets/brand.svg").read()
except Exception:
    BRAND_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0066ff"/></svg>'

# ===== 存取控制:帳號 / session / RBAC / timeout / IP 白名單 =====
USERS_FILE = os.environ.get("DASH_USERS_FILE") or f"{BRIDGE}/dash-users.json"
AUTH_FILE = os.environ.get("DASH_AUTH_FILE") or f"{BRIDGE}/dash-auth.json"
SEED_FILE = os.environ.get("DASH_SEED_FILE") or f"{DIR}/config/bridge/dash-seed.json"   # 首次啟動的種子帳密;git-ignored,見 config/bridge/README.md
SESSIONS = {}   # sid -> {email, role, created, last, ip}
_LOGINF = {}    # ip -> {count, until}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def _login_locked(key):
    lf = _LOGINF.get(key); return bool(lf and lf.get("until", 0) > time.time())
def _login_fail(key):
    lf = _LOGINF.get(key) or {"count": 0, "until": 0}
    lf["count"] = lf.get("count", 0) + 1
    if lf["count"] >= 5: lf["until"] = time.time() + 300; lf["count"] = 0
    _LOGINF[key] = lf
def _pwhash(pw, salt): return hashlib.pbkdf2_hmac("sha256", (pw or "").encode(), bytes.fromhex(salt), 120000).hex()
def _mkuser(pw, role):
    salt = secrets.token_hex(16)
    return {"salt": salt, "pwhash": _pwhash(pw, salt), "role": role, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
_USERS_LOCK = threading.RLock()   # 帳號/授權檔 load→改→存 保護(server 是多執行緒)
def _json_write(path, obj, **kw):
    # 原子寫:tmp + os.replace;程序中途死掉不會留半寫壞檔(dash-users.json 毀損 = 全帳號消失)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)
    os.replace(tmp, path)
def save_users(u):
    _json_write(USERS_FILE, u, indent=2)
def load_users():
    try: u = json.load(open(USERS_FILE, encoding="utf-8"))
    except Exception: u = {}
    if not u:   # 首次啟動:從 config/bridge/dash-seed.json 種一個 admin(該檔 git-ignored,自填帳密)
        try:
            s = json.load(open(SEED_FILE, encoding="utf-8"))
            u = {s["email"]: dict(_mkuser(s["password"], s.get("role", "admin")),
                                  must_change=bool(s.get("must_change", True)))}
            save_users(u)
        except Exception:
            pass    # 無 seed 檔 → 不種帳號;請先建立 dash-seed.json(見 config/bridge/README.md)
    return u
def save_auth(d): _json_write(AUTH_FILE, d, indent=2)
def load_auth():
    d = {"max_sessions": 3, "timeout_min": 30, "ip_whitelist": []}
    try: d.update(json.load(open(AUTH_FILE, encoding="utf-8")))
    except Exception: pass
    return d
def _ip_ok(ip):
    wl = load_auth().get("ip_whitelist") or []
    if not wl: return True
    if ip in ("127.0.0.1", "::1"): return True   # 直連 loopback 一律放行,避免自鎖
    for w in wl:
        w = w.strip()
        if not w: continue
        if "/" in w and ipaddress:
            try:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(w, strict=False): return True
            except Exception: pass
        elif ip == w: return True
    return False
def _verify(email, pw):
    u = load_users().get((email or "").strip().lower())
    return u if (u and _pwhash(pw, u["salt"]) == u["pwhash"]) else None
def _gc_sessions():
    to = load_auth().get("timeout_min", 30) * 60; now = time.time()
    if to <= 0: return   # 0 = 無限制(不逾時)
    for sid in [s for s, v in list(SESSIONS.items()) if now - v["last"] > to]: SESSIONS.pop(sid, None)
def new_session(email, role, ip):
    _gc_sessions()
    mx = load_auth().get("max_sessions", 3)
    mine = sorted([(v["last"], s) for s, v in SESSIONS.items() if v["email"] == email])
    while mx > 0 and len(mine) >= mx: SESSIONS.pop(mine.pop(0)[1], None)
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"email": email, "role": role, "created": time.time(), "last": time.time(), "ip": ip}
    return sid
def get_session(sid):
    _gc_sessions(); v = SESSIONS.get(sid)
    if v: v["last"] = time.time()
    return v
def do_user_op(body, actor):
    with _USERS_LOCK:   # 兩個 admin 同時操作不會互蓋(load→改→save 非原子)
        return _do_user_op(body, actor)
def _do_user_op(body, actor):
    op = body.get("op"); email = (body.get("email") or "").strip().lower(); u = load_users()
    if op == "add":
        if not _EMAIL_RE.match(email): return {"ok": False, "msg": "Email 格式不正確"}
        if email in u: return {"ok": False, "msg": "帳號已存在"}
        if not (body.get("password") or ""): return {"ok": False, "msg": "需密碼"}
        role = body.get("role") if body.get("role") in ("admin", "viewer") else "viewer"
        u[email] = _mkuser(body["password"], role); save_users(u); return {"ok": True, "msg": f"已新增 {email}"}
    if op == "del":
        if email == actor: return {"ok": False, "msg": "不能刪除自己"}
        if u.pop(email, None) is None: return {"ok": False, "msg": "查無此帳號"}
        save_users(u)
        for sid in [sd for sd, v in list(SESSIONS.items()) if v["email"] == email]: SESSIONS.pop(sid, None)
        return {"ok": True, "msg": f"已刪除 {email}"}
    if op == "role":
        r = body.get("role")
        if email not in u: return {"ok": False, "msg": "查無此帳號"}
        if r not in ("admin", "viewer"): return {"ok": False, "msg": "角色不正確"}
        if email == actor and r != "admin": return {"ok": False, "msg": "不能取消自己的管理員"}
        u[email]["role"] = r; save_users(u)
        for v in SESSIONS.values():
            if v["email"] == email: v["role"] = r
        return {"ok": True, "msg": f"{email} → {r}"}
    if op == "pw":
        if email not in u: return {"ok": False, "msg": "查無此帳號"}
        if not (body.get("password") or ""): return {"ok": False, "msg": "需密碼"}
        salt = secrets.token_hex(16); u[email]["salt"] = salt; u[email]["pwhash"] = _pwhash(body["password"], salt); u[email]["must_change"] = False
        save_users(u); return {"ok": True, "msg": f"{email} 密碼已重設"}
    return {"ok": False, "msg": "未知操作"}
def do_auth_config(body):
    with _USERS_LOCK:
        return _do_auth_config(body)
def _do_auth_config(body):
    a = load_auth()
    if "max_sessions" in body:
        try: a["max_sessions"] = max(0, int(body["max_sessions"]))
        except Exception: pass
    if "timeout_min" in body:
        try: a["timeout_min"] = max(0, int(body["timeout_min"]))
        except Exception: pass
    if "ip_whitelist" in body:
        a["ip_whitelist"] = [x.strip() for x in str(body["ip_whitelist"]).split(",") if x.strip()]
    save_auth(a); return {"ok": True, "msg": "存取設定已更新", "auth": a}
LOGIN_HTML = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NemoFleet 登入</title><link rel="icon" type="image/svg+xml" href="/brand.svg"><style>
*{box-sizing:border-box;margin:0;padding:0}body{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 50% 28%,#171922,#0b0b0d);color:#f2f2f4;font:15px/1.5 -apple-system,BlinkMacSystemFont,"PingFang TC","Microsoft JhengHei",system-ui,sans-serif}
.box{width:344px;background:#161618;border:1px solid #2a2a31;border-radius:18px;padding:30px 28px;box-shadow:0 24px 70px rgba(0,0,0,.55)}
.bd{display:flex;align-items:center;gap:11px;margin-bottom:20px}.mk{width:40px;height:40px;border-radius:11px;background:radial-gradient(circle at 50% 38%,#10131c,#05070d);display:grid;place-items:center}.mk img{width:30px;height:30px}
h1{font-size:18px;font-weight:680;letter-spacing:-.02em}.sub{font-size:11.5px;color:#a0a3ab;margin-top:1px}
label{display:block;font-size:12px;color:#a0a3ab;margin:15px 0 5px}
input{width:100%;background:#0e0e11;border:1px solid #2a2a31;border-radius:10px;padding:11px 13px;color:#f2f2f4;font:inherit;font-size:14px}input:focus{outline:2px solid #4d8dff;border-color:transparent}
button{width:100%;margin-top:22px;background:#4d8dff;color:#fff;border:0;border-radius:10px;padding:12px;font:inherit;font-weight:600;font-size:15px;cursor:pointer}button:hover{opacity:.92}button:disabled{opacity:.5;cursor:default}
.err{color:#ff5a66;font-size:12.5px;margin-top:13px;min-height:16px;text-align:center}</style></head><body>
<form class="box" id="f"><div class="bd"><span class="mk"><img src="/brand.svg" width="30" height="30"></span><div><h1>NemoFleet</h1><div class="sub">Agent Control Plane</div></div></div>
<label>帳號 Email</label><input id="em" type="email" autocomplete="username" autofocus placeholder="you@asus.com">
<label>密碼</label><input id="pw" type="password" autocomplete="current-password" placeholder="********">
<button id="b" type="submit">登入</button><div class="err" id="er"></div></form>
<script>const f=document.getElementById('f'),er=document.getElementById('er'),b=document.getElementById('b');
f.addEventListener('submit',async e=>{e.preventDefault();er.textContent='';b.disabled=true;b.textContent='登入中…';
try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:em.value,password:pw.value})});const j=await r.json();
if(j.ok){location.href='/'}else{er.textContent=j.msg||'登入失敗';b.disabled=false;b.textContent='登入'}}catch(_){er.textContent='連線失敗';b.disabled=false;b.textContent='登入'}});</script></body></html>"""


def sh(cmd, timeout=6):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV).stdout
    except Exception:
        return ""

def ct(frag):
    return sh(f"docker ps --format '{{{{.Names}}}}' | grep -m1 {frag}", 4).strip()

def ep(container, path, timeout=6):
    out = sh(f"docker exec {container} sh -c \"curl -s -m5 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099{path}\"", timeout)
    try:
        return json.loads(out)
    except Exception:
        return {}

def read_json_in(container, fname, timeout=5):
    out = sh(f"docker exec {container} sh -c 'cat {WD}/{fname} 2>/dev/null'", timeout)
    try:
        return json.loads(out)
    except Exception:
        return {}

def read_conf_in(container, fname, timeout=5):
    out = sh(f"docker exec {container} sh -c 'cat {WD}/{fname} 2>/dev/null'", timeout)
    d = {}
    for line in out.splitlines():
        m = re.match(r"\s*([a-z0-9_.]+)\s*=\s*(.*?)\s*$", line)
        if m:
            d[m.group(1)] = m.group(2)
    return d

def short(name):
    return re.sub(r"-[0-9a-f]{8}.*$", "", name.replace("openshell-", ""))

def parse_policy(out, sandbox="team-lead"):
    # 解析 `openshell policy get <sb> --full` → 唯讀摘要(版本/雜湊/egress 白名單/可寫路徑)
    p = {"sandbox": sandbox, "version": None, "hash": None, "networks": [], "fs_rw": []}
    if not out:
        return p
    vm = re.search(r"Version:\s*(\d+)", out); hm = re.search(r"Hash:\s*([0-9a-f]+)", out)
    p["version"] = vm.group(1) if vm else None
    p["hash"] = hm.group(1)[:10] if hm else None
    if yaml is None:
        return p
    parts = re.split(r"\n-{3,}\n", out, maxsplit=1)
    body = parts[1] if len(parts) > 1 else out
    try:
        y = yaml.safe_load(body) or {}
    except Exception:
        return p
    fp = y.get("filesystem_policy") or {}
    p["fs_rw"] = [x for x in (fp.get("read_write") or []) if isinstance(x, str)]
    nets = y.get("network_policies") or {}
    pri = {"mail_egress": 0, "telegram": 1, "telegram_bot": 2, "worker_bridge": 3, "nvidia": 4}
    items = []
    for name, pp in nets.items():
        if not isinstance(pp, dict):
            continue
        eps = []
        for e in (pp.get("endpoints") or []):
            if isinstance(e, dict) and e.get("host"):
                eps.append(f"{e['host']}:{e['port']}" if e.get("port") else str(e["host"]))
        bins = [str(b.get("path", "")).split("/")[-1] for b in (pp.get("binaries") or []) if isinstance(b, dict)]
        l7 = any(e.get("rules") for e in (pp.get("endpoints") or []) if isinstance(e, dict))
        items.append({"name": name, "eps": eps, "nbin": len(pp.get("binaries") or []),
                      "bins": sorted(set(b for b in bins if b)), "l7": l7})
    items.sort(key=lambda x: (pri.get(x["name"], 9), x["name"]))
    p["networks"] = items
    return p

_CLOCK = threading.Lock()
def collect():
    # stale-while-revalidate:有資料就立刻回(過期則背景刷新),請求永不被冷收集阻塞
    if _CACHE["data"] is not None:
        if time.time() - _CACHE["ts"] >= _COLLECT_TTL and _CLOCK.acquire(blocking=False):
            def _bg():
                try:
                    _collect_impl()
                finally:
                    _CLOCK.release()
            threading.Thread(target=_bg, daemon=True).start()
        return _CACHE["data"]
    with _CLOCK:                      # 首次(全無資料)才同步收集
        if _CACHE["data"] is None:
            _collect_impl()
    return _CACHE["data"]
def _collect_impl():
    now = time.time()
    d = {"now": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "mttr": "44 秒"}

    rows = sh("docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}|{{.RunningFor}}|{{.ID}}'", 5).splitlines()
    d["containers"] = []
    for r in rows:
        p = r.split("|")
        if len(p) >= 6:
            d["containers"].append({"name": short(p[0]), "full": p[0], "status": p[1],
                                    "image": p[2], "ports": p[3] or "—", "uptime": p[4], "id": p[5][:12]})

    d["gateway"] = sh("curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:%s/ 2>/dev/null" % os.environ.get("NEMOCLAW_GATEWAY_PORT", "8080"), 4).strip() not in ("", "000")
    d["hermes_api"] = sh("curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8642/v1/models 2>/dev/null", 4).strip() not in ("", "000")
    cth = ct("team-lead")
    d["telegram_recent"] = 0
    if cth:
        try:
            d["telegram_recent"] = int(sh(f"docker logs --since 6m {cth} 2>&1 | grep -ac getUpdates", 6).strip() or 0)
        except Exception:
            pass

    cto = ct("worker-a"); ct2 = ct("worker-b")
    nodes = []
    for label, c in (("A", cto), ("B", ct2)):
        if not c:
            continue
        h = ep(c, "/health"); m = ep(c, "/monitor")
        node = {"label": label, "name": short(c), "zone": h.get("zone"), "role": h.get("role"),
                "caps": h.get("caps", []), "alive": bool(h), "alerts": m.get("alerts", 0),
                "monitor": [{"asset": x["asset"].replace("lab-", ""), "status": x.get("status"),
                             "regressions": x.get("regressions", []), "pending": x.get("pending_review", []),
                             "offline": x.get("offline", False), "health": x.get("health")}
                            for x in m.get("devices", [])]}
        if "fix" in (h.get("caps") or []):
            node["scenarios"] = h.get("scenarios", [])
            asn = ep(c, "/assets")  # EBG19P 資產盤點(運維節點)
            if asn.get("available"):
                node["assets"] = {"count": asn.get("count", 0), "unknown": asn.get("unknown", 0),
                                  "list": asn.get("assets", [])[:12]}
            tr = ep(c, "/traffic")  # EBG19P WAN 流量基線(運維節點)
            if tr.get("available") and tr.get("samples"):
                node["traffic"] = {"latest": tr.get("latest_mbps", 0), "avg": tr.get("avg_mbps", 0),
                                   "peak": tr.get("peak_mbps", 0), "anomaly": tr.get("anomaly", False),
                                   "series": tr.get("series", [])}
            dl = ep(c, "/device-log")  # EBG19P syslog 匯集(運維節點 A — 設備日誌歸這台的管理者)
            if dl.get("available"):
                node["devlog"] = {"total": dl.get("total", 0), "by_category": dl.get("by_category", {}),
                                  "by_severity": dl.get("by_severity", {}), "security_events": dl.get("security_events", [])}
            la = read_json_in(c, "syslog-analysis.json")  # worker-a syslog 進階分析(異常/根因/融合/日報;排程寫檔)
            if la and la.get("available"):
                node["loganalysis"] = {"findings": la.get("findings", []), "root_causes": (la.get("root_causes") or [])[:5],
                                       "fusion": la.get("fusion", []), "summary": la.get("summary", ""),
                                       "summary_en": la.get("summary_en", ""), "ts": la.get("ts")}
        if "cert" in (h.get("caps") or []):  # 憑證 / 弱加密與協定盤點(運維節點 A 主動提醒;讀快取,掃描走排程)
            ce = read_json_in(c, "cert-report.json")
            if ce and ce.get("findings") is not None:
                node["cert"] = {"counts": ce.get("counts", {}), "severity": ce.get("severity", {}),
                                "device_count": ce.get("device_count", 0),
                                "findings": [{"asset": (f.get("asset") or "").replace("lab-", ""),
                                              "service": f.get("service"), "issue": f.get("issue"),
                                              "severity": f.get("severity"), "detail": f.get("detail"), "fix": f.get("fix"), "state": f.get("state")}
                                             for f in ce.get("findings", [])[:16]]}
        if "cve" in (h.get("caps") or []):
            cve = read_json_in(c, "cve-report.json")
            aff = [{"cve": f.get("cve"), "asset": f.get("asset", "").replace("lab-", ""),
                    "component": f.get("component"), "ver": f.get("our_version"), "sev": f.get("severity")}
                   for f in cve.get("findings", []) if f.get("verdict") == "affected"]
            node["cve"] = {"fleet": cve.get("fleet_size"), "counts": cve.get("counts", {}), "affected_list": aff}
            src = read_json_in(c, "source-cve-report.json")
            if src:
                node["source"] = {"sbom": src.get("sbom_packages"), "sbom_source": src.get("sbom_source"),
                                  "sast_source": src.get("sast_source"), "analysis_by": src.get("analysis_by"),
                                  "upstream_repo": src.get("upstream_repo"),
                                  "advisories_source": src.get("advisories_source"), "cve_feed": src.get("cve_feed"),
                                  "advisories_fixed": src.get("advisories_fixed"), "cve_reconciled": src.get("cve_reconciled"),
                                  "sast": len(src.get("sast_findings", [])),
                                  "patches": src.get("patches"), "design_violated": src.get("design_violated"),
                                  "design": [{"req": x.get("req"), "kind": x.get("kind"), "desc": x.get("desc"),
                                              "desc_en": x.get("desc_en"), "evidence_en": x.get("evidence_en"),
                                              "status": x.get("status"), "evidence": x.get("evidence")}
                                             for x in src.get("design_conformance", [])],
                                  "sast_list": [{"cwe": s.get("cwe"), "file": s.get("file"), "line": s.get("line"),
                                                 "code": s.get("code"), "patch": s.get("patch"),
                                                 "patch_verified": s.get("patch_verified"), "violates_design": s.get("violates_design"),
                                                 "upstream_path": s.get("upstream_path"), "url": s.get("url"),
                                                 "remediation": s.get("remediation"), "patch_kind": s.get("patch_kind")}
                                                for s in src.get("sast_findings", [])[:6]]}
        if "nuclei" in (h.get("caps") or []):
            try:
                nz = json.loads(_worker_get("worker-b", "/nuclei", timeout=8) or "{}")
            except Exception:
                nz = {}
            if nz:
                node["nuclei"] = {"available": nz.get("available"), "target": nz.get("target"),
                                  "tags": nz.get("tags"), "count": nz.get("count", 0),
                                  "counts": nz.get("counts", {}), "note": nz.get("note"), "ts": nz.get("ts"),
                                  "escalated": nz.get("escalated", []),
                                  "findings": [{"template": fd.get("template"), "name": fd.get("name"),
                                                "severity": fd.get("severity"), "matched_at": fd.get("matched_at"),
                                                "cve": fd.get("cve", []), "reference": fd.get("reference", [])}
                                               for fd in (nz.get("findings") or [])[:30]]}
        nodes.append(node)
    d["nodes"] = nodes
    d["settings"] = (ep(cto, "/settings") if cto else {}) or {}   # 管理設定(讀 node A;兩台同步)
    d["mttr_n"] = 0   # 動態 MTTR:讀 node A 的 fix-history 近 N 次成功修復取平均(無紀錄→保留 44 秒基準)
    try:
        oks = []
        for l in (sh(f"docker exec {cto} sh -c 'cat {WD}/fix-history.jsonl 2>/dev/null'", 5).splitlines() if cto else []):
            try:
                j = json.loads(l)
                if j.get("ok") and isinstance(j.get("secs"), (int, float)):
                    oks.append(j)
            except Exception:
                pass
        if oks:
            recent = oks[-10:]
            d["mttr"] = f"{round(sum(x['secs'] for x in recent) / len(recent))} 秒"
            d["mttr_n"] = len(oks); d["mttr_last"] = oks[-1]["secs"]
    except Exception:
        pass
    if cto:  # EBG19P 身分(設備詳情抽屜用;讀 node A 同步來的真機設定快照)
        cf = read_conf_in(cto, "ebg19p-current.conf")
        if cf:
            d["ebg19p_info"] = {k: cf.get(k) for k in ("device.model", "device.firmware", "device.mac",
                                "wan.proto", "wifi.ssid", "webui.wan_access", "ssh.enabled",
                                "firewall.dos_protection", "upnp.enabled", "wps.enabled")}
    try:  # EBG19P 處置稽核(最近 8 筆;host executor 寫的 jsonl)
        au = [json.loads(l) for l in open(os.path.expanduser("~/.config/nemoclaw/ebg19p-audit.jsonl"), encoding="utf-8") if l.strip()]
        d["ebg19p_audit"] = au[-8:][::-1]
    except Exception:
        d["ebg19p_audit"] = []

    gov = {"allowed": {}, "denied": 0, "denied_benign": 0}
    _bn = lambda L: ("inference.local" in L) and ("handshake" in L.lower() or "eof" in L.lower())
    events = []
    for c in [x for x in (cth, cto, ct2) if x]:
        lines = sh(f"docker logs --since 2h {c} 2>&1 | grep -aE 'ALLOWED|DENIED'", 7).splitlines()
        for ln in lines:
            mm = re.search(r"policy:([a-z_-]+)", ln)
            if "ALLOWED" in ln and mm and mm.group(1) != "-":
                gov["allowed"][mm.group(1)] = gov["allowed"].get(mm.group(1), 0) + 1
            elif "DENIED" in ln:
                if _bn(ln):
                    gov["denied_benign"] += 1
                else:
                    gov["denied"] += 1
        for ln in [x for x in lines if "getUpdates" not in x][-40:]:
            dtm = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", ln)  # log 是 UTC(…Z)
            disp, sortk = "", ""
            if dtm:
                try:
                    u = datetime(*map(int, dtm.groups())) + timedelta(hours=8)  # UTC→CST(+8),與面板時鐘一致
                    disp = u.strftime("%m-%d %H:%M:%S"); sortk = u.strftime("%Y%m%d%H%M%S")
                except Exception:
                    disp = dtm.group(0)[5:].replace("T", " "); sortk = dtm.group(0)
            pol = re.search(r"policy:([a-z_-]+)", ln)
            cls = re.search(r"OCSF (\S+)", ln)             # OCSF 類別,如 NET:OPEN / PROC:EXEC
            sev = re.search(r"OCSF \S+ \[([A-Z]+)\]", ln)  # 嚴重度 INFO/MED/HIGH
            eng = re.search(r"engine:([a-z0-9]+)", ln)     # 判定引擎 opa / l7
            rsn = re.search(r"\[reason:([^\]]+)\]", ln)    # DENIED 沒有 policy,但有 reason
            binm = re.search(r"(?:ALLOWED|DENIED) (/\S+?)\(", ln)  # 發起此動作的 binary/程式
            tgt = re.search(r"(host\.openshell\.internal:\d+|api\.[\w.]+(?::\d+)?|\d+\.\d+\.\d+\.\d+:\d+|https?://[^\s\]]+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?::\d+)?)", ln)
            events.append({"t": disp, "ts": sortk, "benign": _bn(ln), "verb": "DENIED" if "DENIED" in ln else "ALLOWED",
                           "policy": pol.group(1) if pol else "-", "cls": cls.group(1) if cls else "",
                           "sev": sev.group(1) if sev else "", "engine": eng.group(1) if eng else "",
                           "reason": (rsn.group(1) if rsn else "")[:150], "binary": binm.group(1) if binm else "",
                           "target": (tgt.group(1) if tgt else "")[:46]})
    alln = sorted([e for e in events if e["ts"]], key=lambda e: e["ts"], reverse=True)
    denied = [e for e in alln if e["verb"] == "DENIED"][:14]      # 保證最近 DENIED 進得了事件流(否則被頻繁 ALLOWED 擠掉→「擋下」篩選空白)
    allowed = [e for e in alln if e["verb"] == "ALLOWED"][:34]
    d["events"] = sorted(denied + allowed, key=lambda e: e["ts"], reverse=True)
    d["governance"] = gov

    HISTORY.append({"ts": time.strftime("%H:%M:%S"), "allowed": sum(gov["allowed"].values()), "telegram": d["telegram_recent"], "denied": gov["denied"]})
    del HISTORY[:-40]
    d["history"] = {"allowed": [x["allowed"] for x in HISTORY], "telegram": [x["telegram"] for x in HISTORY], "denied": [x["denied"] for x in HISTORY], "ts": [x["ts"] for x in HISTORY]}

    kinds = {}; tickets = []
    for cc in [x for x in (cto, ct2) if x]:
        for ln in sh(f"docker exec {cc} sh -c 'cat {WD}/jira-queue.jsonl 2>/dev/null'", 5).splitlines():
            try:
                j = json.loads(ln)
            except Exception:
                continue
            k = j.get("kind", "?"); kinds[k] = kinds.get(k, 0) + 1
            tickets.append({"id": j.get("id"), "summary": j.get("summary", ""), "kind": k,
                            "asset": (j.get("asset") or "").replace("lab-", ""), "priority": j.get("priority"),
                            "status": j.get("status"), "created": j.get("created", "")})
    d["jira"] = kinds
    tickets.sort(key=lambda x: x.get("created", ""), reverse=True)
    d["jira_tickets"] = tickets[:12]

    guard = []
    try:
        for ln in open(f"{DIR}/eval/ledgers/LOOP-LEDGER.md", encoding="utf-8").read().splitlines():
            fm = re.search(r"fails=(\d+)", ln); tm = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d)", ln)
            if fm and tm:
                guard.append({"ts": tm.group(1), "fails": int(fm.group(1)), "bridge": "bridge=PASS" in ln})
    except Exception:
        pass
    d["guard"] = guard[-14:]

    polout = sh("openshell policy get team-lead --full 2>/dev/null", 12)
    d["bridge_ips"] = sorted(set(re.findall(r"172\.18\.0\.\d+/32", polout)))
    d["policy"] = parse_policy(polout)
    d["policy"]["sandboxes"] = _list_agent_sandboxes()   # 供唯讀卡 agent 選單
    # 快照是每個 sandbox 各自一份(Hermes / worker-a / worker-b)→ 逐台收集
    by_agent = []; all_names = []
    for label, sb in (("Hermes", "team-lead"), ("worker-a", "worker-a"), ("worker-b", "worker-b")):
        items = []
        for ln in sh(f"nemoclaw {sb} snapshot list 2>/dev/null", 10).splitlines():
            vm = re.search(r"\b(v\d+)\b", ln)
            tm = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z", ln)  # 抓真時間戳;Name 欄位可為空,不能靠位置
            if not vm or not tm:
                continue
            nm = ln[vm.end():tm.start()].strip()
            items.append({"ver": vm.group(1), "name": nm or "—", "ts": tm.group(0)})
        items = items[:6][::-1]   # CLI 新→舊;取最新 6 筆轉時間序(舊→新,最新在最後)
        by_agent.append({"label": label, "sb": sb, "items": items})
        all_names += [it["name"] for it in items]
    d["snapshots_by_agent"] = by_agent
    d["snapshots"] = all_names   # 全 stack 合計(KPI 計數用)
    d["snapshots_meta"] = next((a["items"] for a in by_agent if a["sb"] == "worker-a"), [])

    al = []   # 雙語:{msg(zh), msg_en};前端用 L() 挑語言
    if not d["gateway"]: al.append({"msg": "OpenShell gateway 離線", "msg_en": "OpenShell gateway offline"})
    if not d["hermes_api"]: al.append({"msg": "Hermes API :8642 離線", "msg_en": "Hermes API :8642 offline"})
    for n in nodes:
        if not n["alive"]: al.append({"msg": f"節點 {n['label']} 離線", "msg_en": f"Node {n['label']} offline"})
        for x in n["monitor"]:
            if x["status"] and "ALERT" in str(x["status"]):
                _m = re.search(r"ALERT\((\d+)", str(x["status"]))
                _n = _m.group(1) if _m else "?"
                al.append({"msg": f"{x['asset']} {x['status']}", "msg_en": f"{x['asset']} ALERT({_n} security drift(s))"})
    for n in nodes:  # 憑證已過期 = 急迫提醒,進總告警
        ex = ((n.get("cert") or {}).get("counts") or {}).get("expired", 0)
        if ex:
            al.append({"msg": f"{ex} 張憑證已過期", "msg_en": f"{ex} certificate(s) expired"})
    d["alerts_list"] = al

    def _sk(s):  # 任意時間字串 → 可排序 14 位數字鍵
        x = re.sub(r"\D", "", s or "")[:14]
        return x.ljust(14, "0")
    tl = []
    for e in d["events"][:34]:  # 治理事件(ALLOWED/DENIED)
        tl.append({"sk": e["ts"] or _sk(e["t"]), "tm": e["t"], "type": "gov",
                   "tone": "bad" if e["verb"] == "DENIED" else "",
                   "a": e["verb"], "b": ((e["binary"].split("/")[-1] + " → ") if e.get("binary") else "")
                   + (e.get("target") or e.get("policy") or e.get("cls") or "")})
    for j in d.get("jira_tickets", []):  # Jira 升級工單
        tl.append({"sk": _sk(j.get("created")), "tm": (j.get("created") or "")[5:16], "type": "jira",
                   "tone": "warn", "a": j.get("id") or "Jira", "b": (j.get("summary") or "")[:96]})
    for a in d.get("ebg19p_audit", []):  # EBG19P 處置稽核
        tl.append({"sk": _sk(a.get("ts")), "tm": (a.get("ts") or "")[5:16], "type": "audit",
                   "tone": "bad" if a.get("result") == "failed" else "ok",
                   "a": a.get("action", ""), "b": (a.get("detail") or a.get("result") or "")})
    for g in guard[-14:]:  # 巡檢歷史(LOOP-LEDGER;取最近,避免自我檢查淹掉其他類別)
        tl.append({"sk": _sk(g["ts"]), "tm": (g["ts"] or "")[5:16], "type": "guard",
                   "tone": "bad" if g["fails"] > 0 else "ok",
                   "a": "fails=" + str(g["fails"]), "b": ("bridge PASS" if g.get("bridge") else "self-check")})
    for n in d.get("nodes", []):  # EBG19P syslog 進階分析(worker-a):異常 / 融合洞察 → device 類別
        la = n.get("loganalysis")
        if not la:
            continue
        lts = la.get("ts") or ""
        for f in (la.get("findings") or []):
            tl.append({"sk": _sk(lts), "tm": (lts or "")[5:16], "type": "device",
                       "tone": "bad" if f.get("sev") == "high" else "warn",
                       "a": "syslog", "b": (f.get("title") or "")[:110], "b_en": (f.get("title_en") or f.get("title") or "")[:110]})
        for x in (la.get("fusion") or []):
            tl.append({"sk": _sk(lts), "tm": (lts or "")[5:16], "type": "device", "tone": "warn",
                       "a": "fusion", "b": ((x.get("title") or "") + " — " + (x.get("detail") or ""))[:110],
                       "b_en": ((x.get("title_en") or x.get("title") or "") + " — " + (x.get("detail_en") or x.get("detail") or ""))[:110]})
    tl.sort(key=lambda x: x["sk"], reverse=True)
    d["timeline"] = tl[:80]

    try:
        d["sysinfo"] = _sysinfo()   # 高價值系統資訊(60s 快取,不增加輪詢負擔)
    except Exception:
        d["sysinfo"] = {}
    try:
        d["proactive"] = json.load(open(f"{DIR}/data/proactive-status.json", encoding="utf-8"))
        d["proactive"]["log"] = [json.loads(l) for l in open(f"{DIR}/data/proactive-log.jsonl", encoding="utf-8") if l.strip()][-20:][::-1]
    except Exception:
        d["proactive"] = {}
    # cross-node work flow: worker /flow events + host-side team-lead events (proactive patrol/report)
    _flow = []
    for _frag in ("worker-a", "worker-b", "worker-c"):
        try:
            _flow += (json.loads(_worker_get(_frag, "/flow", timeout=6) or "{}").get("flow") or [])
        except Exception:
            pass
    try:
        _flow += [json.loads(l) for l in open(FLOW_LOG, encoding="utf-8") if l.strip()][-30:]
    except Exception:
        pass
    _ps = d.get("proactive") or {}
    if _ps.get("last_patrol"):
        _t = _ps["last_patrol"].split(" ")[-1] if " " in _ps["last_patrol"] else _ps["last_patrol"]
        _flow.append({"ts": _t, "node": "team-lead", "peer": "human", "task": "patrol",
                      "status": "done", "detail": "%s crit / %s routine" % (_ps.get("last_critical", 0), _ps.get("last_routine", 0))})
    d["flow"] = sorted(_flow, key=lambda e: e.get("ts", ""), reverse=True)[:30]
    _gc = {"up": False, "reviews": [], "backups": [], "backup_count": 0, "firmware": {}, "skills_count": 0, "curations": []}
    try:
        _rv = json.loads(_worker_get("worker-c", "/reviews", timeout=6) or "{}")
        _bk = json.loads(_worker_get("worker-c", "/backup", timeout=6) or "{}")
        _fw = json.loads(_worker_get("worker-c", "/firmware", timeout=6) or "{}")
        _sk = json.loads(_worker_get("worker-c", "/skills", timeout=6) or "{}")
        _cu = json.loads(_worker_get("worker-c", "/curations", timeout=6) or "{}")
        _gc = {"up": bool(_rv or _bk or _fw or _sk), "reviews": _rv.get("reviews", []),
               "backups": _bk.get("backups", []), "backup_count": _bk.get("count", 0), "firmware": _fw,
               "skills_count": _sk.get("count", 0), "curations": _cu.get("curations", [])}
    except Exception:
        pass
    d["governance_c"] = _gc
    _CACHE["ts"] = now; _CACHE["data"] = d
    return d

ALLOWED_CFG = {"cve_interval_sec", "cert_interval_sec", "cert_expire_warn_days", "cert_rsa_min",
               "auto_escalate", "quiet_enabled", "quiet_start", "quiet_end", "quiet_days", "notify_channels", "cert_sig_min", "cert_cipher_policy", "cert_ec_min",
               "dev_cpu_hi", "dev_ram_hi", "dev_temp_hi",
               "proactive_enabled", "patrol_interval_sec", "digest_interval_sec", "proactive_safety_net",
               "nuclei_interval_sec", "nuclei_tags", "proactive_snooze_until", "backup_interval_sec"}
def _worker_post(path, payload, timeout=10):
    """POST JSON to each worker's IT-ops endpoint. The JSON is piped via stdin to an in-container
    curl (docker exec -i … --data-binary @-): no nested shell quoting, no base64 smuggling, and the
    token/body are argv rather than interpolated into a shell string. Returns (any_ok, last_text)."""
    body = json.dumps(payload, ensure_ascii=False)
    any_ok, last = False, ""
    for frag in ("worker-a", "worker-b"):
        c = ct(frag)
        if not c:
            continue
        try:
            r = subprocess.run(
                ["docker", "exec", "-i", c, "curl", "-s", "-m", "6",
                 "-H", f"X-Bridge-Token: {TOKEN}", "-H", "Content-Type: application/json",
                 "-X", "POST", "--data-binary", "@-", f"http://127.0.0.1:9099{path}"],
                input=body, capture_output=True, text=True, timeout=timeout, env=ENV)
            last = r.stdout or r.stderr or ""
            if '"ok":true' in last.replace(" ", ""):
                any_ok = True
        except Exception:
            pass
    return any_ok, last

def _worker_get(frag, path, timeout=16):
    """GET an in-container worker endpoint (e.g. re-trigger a scan). No body → no quoting hazard."""
    c = ct(frag)
    if not c:
        return ""
    try:
        r = subprocess.run(
            ["docker", "exec", c, "curl", "-s", "-m", "12", "-H", f"X-Bridge-Token: {TOKEN}",
             f"http://127.0.0.1:9099{path}"],
            capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.stdout or ""
    except Exception:
        return ""

def do_config(k, v):
    # 管理設定:推到兩台 worker endpoint 的 /settings(各容器持久化;掃描迴圈讀取)
    if k not in ALLOWED_CFG:
        return {"ok": False, "msg": "不允許的設定"}
    ok, _ = _worker_post("/settings", {k: v})
    if ok and k in ("cert_rsa_min", "cert_expire_warn_days", "cert_sig_min", "cert_cipher_policy", "cert_ec_min"):
        _worker_get("worker-a", "/cert-scan")   # 改門檻 → 立刻重掃刷新報表(避免時間差)
    _CACHE["ts"] = 0
    return {"ok": ok, "msg": f"{k} 已更新" if ok else "更新失敗(端點未回 ok)"}

def do_cert_policy(params):
    # 憑證政策:每設備覆寫 / 自訂 cipher 家族 → 推兩台 + 觸發重掃
    ok, _ = _worker_post("/cert-policy", params)
    if ok:
        _worker_get("worker-a", "/cert-scan")
    _CACHE["ts"] = 0
    return {"ok": ok, "msg": "憑證政策已更新" if ok else "更新失敗"}

def do_recipient(op, name, telegram, email):
    # 通知對象增刪:推到兩台 endpoint /recipients;新增且有 email → 寄歡迎信(真實 SMTP,可驗證)
    if op == "test":   # 一鍵試送:對該對象現有通道送測試通知(不受 notify_channels gate)
        msgs = []
        try:
            if email:
                _alert_email(email, "NemoClaw 測試通知",
                             f"{name or ''} 您好,這是一封測試通知,確認您的 Email 告警通道正常。— NemoClaw")
                msgs.append("Email")
            if telegram:
                _alert_telegram(telegram, f"NemoClaw 測試通知:{name or ''} 的 Telegram 告警通道正常")
                msgs.append("Telegram")
        except Exception as e:
            return {"ok": False, "msg": f"測試送出失敗:{e}"}
        return {"ok": bool(msgs), "msg": ("已送出測試(" + " + ".join(msgs) + ")") if msgs else "此對象未設任何通道"}
    ok, last_text = _worker_post("/recipients", {"op": op, "name": name, "telegram": telegram, "email": email})
    try:
        last = json.loads(last_text)
    except Exception:
        last = {"ok": ok, "msg": "更新成功" if ok else "更新失敗"}
    if op == "add" and last.get("ok") and email:
        try:
            subj = "NemoClaw 通知對象啟用"
            text = f"{name} 您好,您已被加入 NemoClaw 告警 / 工單通知對象。此信用於確認 Email 通道可達。"
            sh(f"bash {MAIL}/send-to.sh {shlex.quote(email)} {shlex.quote(subj)} {shlex.quote(text)}", 25)
            last["msg"] = (last.get("msg", "") + " · 已寄歡迎信")
        except Exception:
            pass
    _CACHE["ts"] = 0
    return last

NOTIFIED_FILE = f"{BRIDGE}/notified.json"
NOTIFY_SENDER = os.environ.get("NOTIFY_SENDER", "tony@demo.local")   # Hermes email 白名單授權寄件者(觸發 Telegram 推播)
def _load_notified():
    try:
        return set(json.load(open(NOTIFIED_FILE, encoding="utf-8")))
    except Exception:
        return set()
def _save_notified(x):
    try:
        _json_write(NOTIFIED_FILE, sorted(x))
    except Exception:
        pass
_DLP_RULES = [
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|bearer|authorization)\b\s*[:=]\s*\S+"), "CREDENTIAL"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "LONG-SECRET"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "CARD"),
]
def _dlp(text, ctx=""):
    # 出站 DLP:送出前遮蔽憑證/長密鑰/卡號;命中寫稽核。L7 內容檢查的應用層補強。
    t = text or ""; hits = []
    for rx, lbl in _DLP_RULES:
        if rx.search(t):
            hits.append(lbl); t = rx.sub(f"[REDACTED:{lbl}]", t)
    if hits:
        try: audit("system", "dlp-redact", f"{ctx}: {','.join(sorted(set(hits)))}", "", True)
        except Exception: pass
    return t
def _alert_email(to, subject, body):
    body = _dlp(body, f"email→{to}")
    sh(f"bash {MAIL}/send-to.sh {shlex.quote(to)} {shlex.quote(subject)} {shlex.quote(body)}", 25)
def _alert_telegram(chat_id, text):
    text = _dlp(text, f"telegram→{chat_id}")
    body = (f"Hermes,請務必實際呼叫你的 send_message 工具,發 Telegram 訊息到 chat id {chat_id},"
            f"內容為「{text}」。不要只在回信說明,要真的呼叫工具發送。")
    sh(f"bash {MAIL}/send-mail-as.sh {shlex.quote(NOTIFY_SENDER)} {shlex.quote('NemoClaw 告警轉發')} {shlex.quote(body)}", 25)
def notify_loop():
    """新工單 → 通知每位收件人(Email 直送真實 SMTP;Telegram 經 Hermes)。首啟以現有工單為基線、不補發歷史。"""
    time.sleep(10)
    notified = _load_notified()
    seeded = os.path.exists(NOTIFIED_FILE)
    while True:
        try:
            d = collect()
            _track_ports(d)
            anoms = detect_anomalies(d)
            cur_ids = {a.get("id") or a.get("msg") for a in anoms if a.get("sev") in ("high", "warn")}
            tickets = d.get("jira_tickets", []) or []
            ids = [t.get("id") for t in tickets if t.get("id")]
            _la = next((n.get("loganalysis") for n in d.get("nodes", []) if n.get("loganalysis")), None)
            _la_ids = {"log:" + (f.get("id") or f.get("title", "")) for f in ((_la.get("findings", []) + _la.get("fusion", [])) if _la else [])}
            if not seeded:
                notified.update(ids); _ANOM_ACTIVE.update(cur_ids)
                _LOG_ACTIVE.update(_la_ids); _LOG_SUMMARY_DAY["d"] = time.strftime("%Y-%m-%d")
                _save_notified(notified); seeded = True
            else:
                recips = (d.get("settings") or {}).get("recipients", []) or []
                chans = set(x.strip() for x in ((d.get("settings") or {}).get("notify_channels", "") or "").split(",") if x.strip())
                for t in tickets:
                    tid = t.get("id")
                    if not tid or tid in notified:
                        continue
                    subj = f"\u26a0\ufe0f NemoFleet 告警 \u00b7 {t.get('priority','')} \u00b7 {t.get('asset','')}"
                    body = f"{t.get('summary','')}\n\n工單 {tid}({t.get('kind','')})。請至 Jira 處理。"
                    sent = 0
                    for r in recips:
                        try:
                            if "email" in chans and r.get("email"):
                                _alert_email(r["email"], subj, body); sent += 1
                            if "telegram" in chans and r.get("telegram"):
                                _alert_telegram(r["telegram"], f"NemoFleet 告警:{t.get('summary','')[:80]}"); sent += 1
                        except Exception as e:
                            print("[notify send]", e, flush=True)
                    notified.add(tid); _save_notified(notified)
                    print(f"[notify] ticket {tid} -> {len(recips)} recipient(s), {sent} message(s)", flush=True)
                for a in anoms:
                    if a.get("sev") not in ("high", "warn"):
                        continue
                    aid = a.get("id") or a.get("msg")
                    if aid in _ANOM_ACTIVE:
                        continue
                    for r in recips:
                        try:
                            if "email" in chans and r.get("email"):
                                _alert_email(r["email"], "\u26a0\ufe0f NemoFleet 異常告警", a["msg"])
                            if "telegram" in chans and r.get("telegram"):
                                _alert_telegram(r["telegram"], f"NemoFleet 異常:{a['msg']}")
                        except Exception as e:
                            print("[anom send]", e, flush=True)
                    print(f"[anom] {aid} -> {len(recips)} recipient(s)", flush=True)
                _ANOM_ACTIVE.clear(); _ANOM_ACTIVE.update(cur_ids)
                # EBG19P syslog 進階分析:新發現告警 + 每日日報(item 8)
                if _la:
                    for f in (_la.get("findings", []) + _la.get("fusion", [])):
                        fid = "log:" + (f.get("id") or f.get("title", ""))
                        if f.get("sev") not in ("high", "warn") or fid in _LOG_ACTIVE:
                            continue
                        _LOG_ACTIVE.add(fid)
                        for r in recips:
                            try:
                                if "email" in chans and r.get("email"):
                                    _alert_email(r["email"], "\U0001f5a7 EBG19P syslog 分析", f.get("title", ""))
                                if "telegram" in chans and r.get("telegram"):
                                    _alert_telegram(r["telegram"], f"EBG19P syslog:{f.get('title','')[:90]}")
                            except Exception as e:
                                print("[log send]", e, flush=True)
                        print(f"[loganom] {fid} -> {len(recips)} recipient(s)", flush=True)
                    today = time.strftime("%Y-%m-%d")
                    if _la.get("summary") and _LOG_SUMMARY_DAY["d"] != today:
                        _LOG_SUMMARY_DAY["d"] = today
                        for r in recips:
                            try:
                                if "email" in chans and r.get("email"):
                                    _alert_email(r["email"], "\U0001f4cb EBG19P 每日 syslog 日報", _la["summary"])
                                if "telegram" in chans and r.get("telegram"):
                                    _alert_telegram(r["telegram"], "\U0001f4cb " + _la["summary"][:220])
                            except Exception as e:
                                print("[log daily]", e, flush=True)
                        print(f"[log daily] summary -> {len(recips)} recipient(s)", flush=True)
        except Exception as e:
            print("[notify loop]", e, flush=True)
        time.sleep(20)

FLOW_LOG = f"{DIR}/data/flow-log.jsonl"
def _flow_append(node, peer, task, status, detail=""):
    try:
        os.makedirs(os.path.dirname(FLOW_LOG), exist_ok=True)
        ev = {"ts": time.strftime("%H:%M:%S"), "node": str(node)[:20], "peer": str(peer)[:20],
              "task": str(task)[:40], "status": str(status)[:16], "detail": str(detail)[:100]}
        try:
            lines = [l for l in open(FLOW_LOG, encoding="utf-8") if l.strip()][-59:]
        except Exception:
            lines = []
        lines.append(json.dumps(ev, ensure_ascii=False))
        with open(FLOW_LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
def do_action(do):
    ct2 = ct("worker-b")
    if do == "patrol":
        try:
            open(f"{DIR}/data/proactive-trigger", "w").close()
        except Exception:
            pass
        _flow_append("team-lead", "human", "patrol (GUI)", "working")
        return {"ok": True, "msg": "已請求立即巡邏(≤20s 生效)"}
    if do in ("snooze30", "snooze120", "snooze_off"):
        until = 0 if do == "snooze_off" else int(time.time()) + (1800 if do == "snooze30" else 7200)
        do_config("proactive_snooze_until", until)
        _CACHE["ts"] = 0
        return {"ok": True, "msg": ("已靜音 critical 主動告警至 " + time.strftime("%H:%M", time.localtime(until))) if until else "已取消靜音"}
    if do == "refresh":
        _CACHE["ts"] = 0; return {"ok": True, "msg": "已重新整理"}
    if do == "cve" and ct2:
        sh(f"docker exec {ct2} sh -c \"curl -s -m20 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/cve\"", 25)
        _flow_append("worker-b", "human", "CVE rescan (GUI)", "working")
        _CACHE["ts"] = 0; return {"ok": True, "msg": "節點 B 已重掃設備 CVE"}
    if do == "source" and ct2:
        sh(f"docker exec {ct2} sh -c \"curl -s -m25 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/source-cve\"", 30)
        _flow_append("worker-b", "human", "source scan (GUI)", "working")
        _CACHE["ts"] = 0; return {"ok": True, "msg": "節點 B 已重跑原始碼分析(SBOM/SAST)"}
    if do == "nuclei" and ct2:
        sh(f"docker exec {ct2} sh -c \"curl -s -m20 -X POST -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/nuclei-scan\"", 25)
        _flow_append("worker-b", "human", "nuclei scan (GUI)", "working")
        _CACHE["ts"] = 0; return {"ok": True, "msg": "worker-b 已觸發 nuclei 主動掃描(背景執行,稍後刷新)"}
    if do == "backup":
        ct3 = ct("worker-c")
        if ct3:
            sh(f"docker exec {ct3} sh -c \"curl -s -m20 -X POST -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/backup\"", 25)
            _flow_append("worker-c", "human", "backup (GUI)", "working")
            _CACHE["ts"] = 0; return {"ok": True, "msg": "worker-c 已觸發設定備份"}
        return {"ok": False, "msg": "worker-c 未部署"}
    return {"ok": False, "msg": "未知動作"}

AUDIT_FILE = os.path.expanduser("~/.config/nemoclaw/ebg19p-audit.jsonl")
DEV_MSG = {"sync": "EBG19P 已強制同步", "harden": "EBG19P 已套用安全基準(關 UPnP/WPS、開 DoS)",
           "restart": "EBG19P 防火牆/無線服務已重啟", "block": "已送出未授權設備封鎖"}

def do_snapshot(op, sel, sb="worker-a"):
    # NemoClaw 快照 create / restore(逐沙箱)。localhost only · admin-gated · 白名單 + shlex.quote
    # 注意:restore CLI 即使「Restore failed」也回 rc=0,故成功要看輸出文字,不能只看退出碼。
    sel = (sel or "").strip()
    if sb not in ("team-lead", "worker-a", "worker-b"):
        return {"ok": False, "msg": "sandbox 不合法"}
    if op == "delete":
        # 無 CLI delete;快照即 rebuild-backups/<sb>/<timestamp> 目錄 → 嚴格驗 timestamp 後 rmtree(防路徑穿越)
        ts = sel
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z$", ts):
            return {"ok": False, "msg": "timestamp 格式不合法"}
        base = os.path.realpath(os.path.expanduser(f"~/.nemoclaw/rebuild-backups/{sb}"))
        target = os.path.realpath(os.path.join(base, ts))
        if target != os.path.join(base, ts) or not target.startswith(base + os.sep) or not os.path.isdir(target):
            return {"ok": False, "msg": "找不到該快照目錄"}
        try:
            import shutil; shutil.rmtree(target)
        except Exception as e:
            return {"ok": False, "msg": f"刪除失敗:{e}"}
        return {"ok": True, "msg": f"已刪除 {sb} 快照 {ts}"}
    if op == "create":
        nm = re.sub(r"[^A-Za-z0-9._-]", "-", sel)[:40] or ("ui-" + time.strftime("%Y%m%d-%H%M%S"))
        cmd = f"nemoclaw {sb} snapshot create --name {shlex.quote(nm)} 2>&1"; tmo = 90
    elif op == "restore":
        if not re.match(r"^[A-Za-z0-9._:-]+$", sel):
            return {"ok": False, "msg": "selector 不合法"}
        cmd = f"nemoclaw {sb} snapshot restore {shlex.quote(sel)} 2>&1"; tmo = 150
    else:
        return {"ok": False, "msg": "未知操作"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=tmo, env=ENV)
    except Exception as e:
        return {"ok": False, "msg": f"執行失敗:{e}"}
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if op == "create":
        ok = r.returncode == 0 and "created" in out.lower()
        mv = re.search(r"(v\d+)", out); msg = (f"已於 {sb} 建立快照 {mv.group(1) if mv else nm}" if ok else "建立快照失敗")
    else:
        ok = "restored" in out.lower() and "restore failed" not in out.lower()
        msg = (f"已從 {sel} 復原 {sb}" if ok else "復原失敗(運行中沙箱無法 in-place 還原,請走重建流程)")
    return {"ok": ok, "msg": msg, "out": out[-400:]}

def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s or "")

POLICY_PROVE_DIR = "/tmp/.nclaw-prove"
def _prove(raw_yaml):
    # 形式化證明:回 (gaps:int, rc0:bool, out:str)。gaps = critical/high 缺口數(-1=無法解析);rc0 = 退出碼 0
    os.makedirs(POLICY_PROVE_DIR, exist_ok=True)
    pf = f"{POLICY_PROVE_DIR}/policy.yaml"; cf = f"{POLICY_PROVE_DIR}/cred.yaml"
    with open(pf, "w") as fh: fh.write(raw_yaml or "")
    with open(cf, "w") as fh: fh.write("version: 1\ncredentials: []\n")
    try:
        r = subprocess.run(f"openshell policy prove --policy {shlex.quote(pf)} --credentials {shlex.quote(cf)} --compact",
                           shell=True, capture_output=True, text=True, timeout=60, env=ENV)
    except Exception as e:
        return (-1, False, f"prove 執行失敗:{e}")
    out = _strip_ansi((r.stdout or "") + (r.stderr or ""))
    m = re.search(r"(\d+)\s+critical/high gaps", out)
    gaps = int(m.group(1)) if m else (0 if r.returncode == 0 else -1)
    return (gaps, r.returncode == 0, out.strip())

def _policy_sb_ok(sb):
    return bool(re.match(r"^[A-Za-z0-9._-]+$", sb or ""))

def _policy_raw(sb):
    out = sh(f"openshell policy get {shlex.quote(sb)} --full 2>/dev/null", 12)
    parts = re.split(r"\n---\n", out, 1)          # 標頭(版本/雜湊)與政策 YAML 以 --- 分隔
    return (parts[1] if len(parts) > 1 else out).strip()

def _policy_presets(sb):
    res = []
    for ln in sh(f"nemoclaw {shlex.quote(sb)} policy-list 2>/dev/null", 12).splitlines():
        m = re.search(r"([●○])\s+(\S+)\s+—\s+(.+)", ln)
        if m:
            desc = m.group(3).strip()
            # nemoclaw 裂腦標記:gateway 有但本地 registry 沒有 → policy-remove 的 guard 會誤判「not applied」
            desync = "missing from local state" in desc
            res.append({"name": m.group(2), "desc": desc, "active": m.group(1) == "●", "desync": desync})
    return res

def _osh_settings(sb):
    res = []
    for ln in sh(f"openshell settings get {shlex.quote(sb)} 2>/dev/null", 12).splitlines():
        m = re.match(r"\s+([a-z0-9_]+)\s*=\s*(\S+)(?:\s+\(([^)]*)\))?", ln)
        if m:
            res.append({"key": m.group(1), "value": m.group(2), "source": (m.group(3) or "")})
    return res

_SB_LABELS = {"team-lead": "Hermes · 對人前台", "worker-a": "worker-a · IT 運維",
              "worker-b": "worker-b · 資安分析"}
def _list_agent_sandboxes():
    """枚舉實際存在的 agent 沙箱(供 GUI 政策編輯器切換)。讀 openshell sandbox list,附友善標籤。"""
    out, names = sh("openshell sandbox list 2>/dev/null", 12), []
    for ln in out.splitlines():
        m = re.match(r"\s*([a-z0-9][a-z0-9-]*)\s+\d{4}-\d{2}-\d{2}", _strip_ansi(ln))
        if m:
            names.append(m.group(1))
    # 維持 Hermes→A→B 的順序;只回已知 agent 沙箱
    order = ["team-lead", "worker-a", "worker-b"]
    ordered = [n for n in order if n in names] + [n for n in names if n not in order]
    return [{"name": n, "label": _SB_LABELS.get(n, n)} for n in ordered]

def do_policy_get(sb):
    if not _policy_sb_ok(sb): sb = "team-lead"
    full = sh(f"openshell policy get {shlex.quote(sb)} --full 2>/dev/null", 12)
    parts = re.split(r"\n-{3,}\n", full, maxsplit=1)
    raw = (parts[1] if len(parts) > 1 else full).strip()
    pol = parse_policy(full, sb)
    gaps, _ok, pout = _prove(raw)
    hist = _strip_ansi(sh(f"openshell policy list {shlex.quote(sb)} 2>/dev/null", 12))
    return {"ok": True, "sb": sb, "raw": raw, "presets": _policy_presets(sb), "settings": _osh_settings(sb),
            "sandboxes": _list_agent_sandboxes(), "rules": pol["networks"], "fs_rw": pol["fs_rw"],
            "baseline_gaps": gaps, "prove_out": pout[-1200:], "history": hist[-1500:]}

def do_policy_ro(sb):
    # 唯讀:解析任一 agent 的 live 政策(供治理頁唯讀卡的 agent 選單即時切換)
    if not _policy_sb_ok(sb): sb = "team-lead"
    full = sh(f"openshell policy get {shlex.quote(sb)} --full 2>/dev/null", 12)
    return {"ok": True, "policy": parse_policy(full, sb), "sandboxes": _list_agent_sandboxes()}

# ── 系統資訊(高價值唯讀;60s 快取,避免每 5s 輪詢狂打 CLI)──
_SYSINFO = {"ts": 0, "data": None}
def _sysinfo():
    if _SYSINFO["data"] is not None and time.time() - _SYSINFO["ts"] < 60:
        return _SYSINFO["data"]
    info = {}
    # 推理路由(provider/model)+ 從 Hermes 容器探 inference.local 可達性(就是 Telegram 503 的根因指標)
    try:
        j = json.loads(sh("nemoclaw inference get --json 2>/dev/null", 15) or "{}")
    except Exception:
        j = {}
    cth = ct("hermes"); code = ""
    if cth:
        code = sh(f"docker exec {cth} sh -c \"curl -s -k -m4 -o /dev/null -w '%{{http_code}}' https://inference.local/v1/models\" 2>/dev/null", 10).strip()
    info["inference"] = {"provider": j.get("provider"), "model": j.get("model"),
                         "reachable": code not in ("", "000"), "http": code or "—"}
    # OpenShell gateway 狀態
    st = _strip_ansi(sh("openshell status 2>/dev/null", 12))
    pick = lambda k: (re.search(k + r":\s*(\S+)", st) or (0, None))[1]
    info["gateway"] = {"status": pick("Status"), "version": pick("Version"), "server": pick("Server")}
    # 埠轉發(各 agent 對外埠)
    fwd = []
    for ln in _strip_ansi(sh("openshell forward list 2>/dev/null", 12)).splitlines():
        m = re.match(r"\s*([A-Za-z0-9][\w-]*)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)", ln)
        if m and m.group(1).lower() != "sandbox":
            fwd.append({"sb": m.group(1), "bind": m.group(2), "port": m.group(3), "status": m.group(5)})
    info["forwards"] = fwd
    # 已註冊憑證供應商(只名稱,不含密鑰)
    creds = []
    for ln in _strip_ansi(sh("nemoclaw credentials list 2>/dev/null", 12)).splitlines():
        m = re.match(r"\s{2,}([a-z][a-z0-9-]+)\s*$", ln)
        if m and m.group(1) not in ("with",):
            creds.append(m.group(1))
    info["credentials"] = creds
    # 支援的 messaging 通道(查一次)
    chans = []
    for ln in _strip_ansi(sh("nemoclaw team-lead channels list 2>/dev/null", 12)).splitlines():
        m = re.match(r"\s{2,}([a-z]+)\s+—", ln)
        if m: chans.append(m.group(1))
    info["channels"] = chans
    _SYSINFO["ts"] = time.time(); _SYSINFO["data"] = info
    return info

def do_sys(do, sb="", tail="200", provider="", model="", chan="", a1="", a2=""):
    # 中價值:較重的診斷 + 管理動作,改 on-demand(按鈕觸發,不進 5s 輪詢)
    if do == "doctor":
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} doctor 2>&1", 45))
        return {"ok": True, "title": f"{sb} · doctor", "out": out[-5000:] or "(無輸出 / 逾時)"}
    if do == "logs":
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        n = str(tail) if re.match(r"^\d{1,4}$", str(tail)) else "200"
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} logs --tail {n} 2>&1", 30))
        return {"ok": True, "title": f"{sb} · logs (tail {n})", "out": out[-9000:] or "(無輸出 / 逾時)"}
    if do == "stale":
        out = _strip_ansi(sh("nemoclaw upgrade-sandboxes --check 2>&1", 45))
        return {"ok": True, "title": "過期沙箱檢查", "out": out[-5000:] or "(無輸出 / 逾時)"}
    if do == "gsettings":
        out = _strip_ansi(sh("openshell settings get --global 2>&1", 15))
        return {"ok": True, "title": "全域 OpenShell 設定(--global)", "out": out[-5000:] or "(無輸出)"}
    if do == "recover":   # nemoclaw <sb> recover:重啟 gateway + dashboard port-forward(冪等自癒)
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} recover 2>&1", 90))
        return {"ok": True, "title": f"{sb} · recover", "out": out[-6000:] or "(無輸出 / 逾時)"}
    if do == "gwhealth":  # openshell status + doctor:強制層 gateway 健康
        out = (_strip_ansi(sh("openshell status 2>&1", 20)) + "\n\n===== openshell doctor =====\n"
               + _strip_ansi(sh("openshell doctor 2>&1", 45)))
        return {"ok": True, "title": "OpenShell Gateway 健康(status + doctor)", "out": out[-9000:] or "(無輸出 / 逾時)"}
    if do == "infset":    # nemoclaw inference set --provider --model [--sandbox];切換推理路由
        if not re.match(r"^[A-Za-z0-9._-]{1,64}$", provider) or not re.match(r"^[A-Za-z0-9._:/-]{1,96}$", model):
            return {"ok": False, "out": "provider / model 格式不正確(限英數與 . _ - : /)"}
        cmd = f"nemoclaw inference set --provider {shlex.quote(provider)} --model {shlex.quote(model)}"
        if sb and _policy_sb_ok(sb): cmd += f" --sandbox {shlex.quote(sb)}"
        out = _strip_ansi(sh(cmd + " 2>&1", 90))
        return {"ok": True, "title": f"inference set → {provider} / {model}", "out": out[-6000:] or "(無輸出 / 逾時)"}
    if do == "gc":        # nemoclaw gc --dry-run:預覽要刪的孤兒 docker 映像(只看不刪)
        out = _strip_ansi(sh("nemoclaw gc --dry-run 2>&1", 60))
        return {"ok": True, "title": "GC 預覽(--dry-run · 不刪)", "out": out[-6000:] or "(無輸出 / 逾時)"}
    if do == "gcrun":     # nemoclaw gc --yes:真的清除孤兒 docker 映像
        out = _strip_ansi(sh("nemoclaw gc --yes 2>&1", 120))
        return {"ok": True, "title": "GC 執行(已清孤兒映像)", "out": out[-6000:] or "(無輸出 / 逾時)"}
    if do in ("chanstart", "chanstop"):   # nemoclaw <sb> channels start|stop <channel>(保留憑證,重建沙箱)
        sbn = sb or "team-lead"
        if not _policy_sb_ok(sbn): return {"ok": False, "out": "sandbox 不合法"}
        if not re.match(r"^[a-z]{2,20}$", chan): return {"ok": False, "out": "channel 名稱不正確"}
        verb = "start" if do == "chanstart" else "stop"
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sbn)} channels {verb} {shlex.quote(chan)} 2>&1", 120))
        return {"ok": True, "title": f"{sbn} · channels {verb} {chan}", "out": out[-6000:] or "(無輸出 / 逾時)"}
    if do == "upgrade":   # nemoclaw upgrade-sandboxes --auto --yes:重建「過時且運行中」沙箱
        out = _strip_ansi(sh("nemoclaw upgrade-sandboxes --auto --yes 2>&1", 240))
        return {"ok": True, "title": "升級過時沙箱(--auto)", "out": out[-9000:] or "(無輸出 / 逾時)"}
    if do == "backupall": # nemoclaw backup-all:升級前備份所有沙箱狀態
        out = _strip_ansi(sh("nemoclaw backup-all 2>&1", 240))
        return {"ok": True, "title": "全量備份(backup-all)", "out": out[-8000:] or "(無輸出 / 逾時)"}
    if do == "debug":     # nemoclaw debug --quick --output <tarball>:診斷包(寫到 host /tmp)
        path = f"/tmp/nemoclaw-debug-{int(time.time())}.tgz"
        out = _strip_ansi(sh(f"nemoclaw debug --quick --output {shlex.quote(path)} 2>&1", 120))
        return {"ok": True, "title": "診斷包(debug --quick)", "out": (f"bundle: {path}\n(在 host 上取用)\n\n" + out)[-8000:]}
    if do == "rebuild":   # nemoclaw <sb> rebuild --yes:升級單一沙箱到當前 agent 版(會重建)
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} rebuild --yes 2>&1", 300))
        return {"ok": True, "title": f"{sb} · rebuild", "out": out[-9000:] or "(無輸出 / 逾時)"}
    if do == "hostslist": # nemoclaw <sb> hosts-list
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} hosts-list 2>&1", 20))
        return {"ok": True, "title": f"{sb} · hosts", "out": out[-5000:] or "(無 host 別名)"}
    if do == "hostsadd":  # nemoclaw <sb> hosts-add <hostname> <ip>
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        if not re.match(r"^[A-Za-z0-9._-]{1,64}$", a1): return {"ok": False, "out": "hostname 不正確"}
        if not re.match(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$", a2): return {"ok": False, "out": "IP 不正確(限 IPv4)"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} hosts-add {shlex.quote(a1)} {shlex.quote(a2)} 2>&1", 30))
        return {"ok": True, "title": f"{sb} · hosts-add {a1} → {a2}", "out": out[-5000:] or "(無輸出)"}
    if do == "hostsrm":   # nemoclaw <sb> hosts-remove <hostname>
        if not _policy_sb_ok(sb): return {"ok": False, "out": "sandbox 不合法"}
        if not re.match(r"^[A-Za-z0-9._-]{1,64}$", a1): return {"ok": False, "out": "hostname 不正確"}
        out = _strip_ansi(sh(f"nemoclaw {shlex.quote(sb)} hosts-remove {shlex.quote(a1)} 2>&1", 30))
        return {"ok": True, "title": f"{sb} · hosts-remove {a1}", "out": out[-5000:] or "(無輸出)"}
    if do in ("fwdstart", "fwdstop"):   # openshell forward start|stop <port> [sandbox]
        if not re.match(r"^[0-9][0-9.:]{0,39}$", a1): return {"ok": False, "out": "port 不正確"}
        tail2 = ""
        if a2:
            if not _policy_sb_ok(a2): return {"ok": False, "out": "sandbox 不合法"}
            tail2 = " " + shlex.quote(a2)
        if do == "fwdstart":
            out = _strip_ansi(sh(f"openshell forward start {shlex.quote(a1)}{tail2} -d 2>&1", 30))
            return {"ok": True, "title": f"forward start {a1}" + (f" · {a2}" if a2 else ""), "out": out[-5000:] or "(無輸出)"}
        out = _strip_ansi(sh(f"openshell forward stop {shlex.quote(a1)}{tail2} 2>&1", 30))
        return {"ok": True, "title": f"forward stop {a1}" + (f" · {a2}" if a2 else ""), "out": out[-5000:] or "(無輸出)"}
    return {"ok": False, "out": "unknown op"}

def do_policy(op, body):
    # OpenShell policy 編輯:preset 開關 / prove / prove-gated apply。localhost · admin · 差異式證明把關
    sb = body.get("sb") or "team-lead"
    if not _policy_sb_ok(sb): return {"ok": False, "msg": "sandbox 不合法"}
    if op == "setting":
        key = body.get("key", ""); val = str(body.get("value", ""))
        if not re.match(r"^[a-z0-9_]+$", key): return {"ok": False, "msg": "key 不合法"}
        if val == "unset":
            cmd = f"openshell settings delete {shlex.quote(sb)} --key {shlex.quote(key)}"
        elif val in ("true", "false"):
            cmd = f"openshell settings set {shlex.quote(sb)} --key {shlex.quote(key)} --value {val}"
        else:
            return {"ok": False, "msg": "value 須為 true/false/unset"}
        try:
            r = subprocess.run(cmd + " 2>&1", shell=True, capture_output=True, text=True, timeout=30, env=ENV)
        except Exception as e:
            return {"ok": False, "msg": f"執行失敗:{e}"}
        out = _strip_ansi((r.stdout or "") + (r.stderr or "")); ok = r.returncode == 0
        return {"ok": ok, "msg": (f"已設定 {key} = {val}" if ok else "設定失敗"), "out": out[-400:]}
    if op == "preset":
        name = body.get("name", ""); on = bool(body.get("on")); dry = bool(body.get("dry"))
        if not re.match(r"^[A-Za-z0-9._-]+$", name): return {"ok": False, "msg": "preset 不合法"}
        # 裂腦修正:收回一個「gateway 有但本地 registry 沒有」的 preset 時,nemoclaw policy-remove 的 guard
        # 只看本地 registry → 誤判 not applied 而拒收。先 policy-add 納管進 registry,再 policy-remove 真的從 gateway 移除。
        desync = False
        if not on:
            desync = any(p["name"] == name and p.get("desync") for p in _policy_presets(sb))
        if desync and not on:
            if dry:
                return {"ok": True, "dry": True, "nochange": False,
                        "msg": "預覽(未套用):此 preset 在 gateway 啟用但本地 state 缺失;將先納管再移除以真正收回",
                        "out": f"{name}: active on gateway, missing from local state → 修正後移除"}
            try:
                ra = subprocess.run(f"nemoclaw {shlex.quote(sb)} policy-add {shlex.quote(name)} --yes",
                                    shell=True, capture_output=True, text=True, timeout=90, env=ENV)
                rr = subprocess.run(f"nemoclaw {shlex.quote(sb)} policy-remove {shlex.quote(name)} --yes",
                                    shell=True, capture_output=True, text=True, timeout=90, env=ENV)
            except Exception as e:
                return {"ok": False, "msg": f"執行失敗:{e}"}
            out = _strip_ansi((ra.stdout or "") + (ra.stderr or "") + "\n" + (rr.stdout or "") + (rr.stderr or ""))
            still = any(p["name"] == name and p["active"] for p in _policy_presets(sb))
            ok = (rr.returncode == 0) and not still
            return {"ok": ok, "dry": False, "nochange": False,
                    "msg": ("已收回 " + name + "(已修正 gateway 與本地狀態不同步)") if ok else ("收回失敗:" + name),
                    "out": out[-800:]}
        verb = "policy-add" if on else "policy-remove"; flag = "--dry-run" if dry else "--yes"
        try:
            r = subprocess.run(f"nemoclaw {shlex.quote(sb)} {verb} {shlex.quote(name)} {flag}",
                               shell=True, capture_output=True, text=True, timeout=90, env=ENV)
        except Exception as e:
            return {"ok": False, "msg": f"執行失敗:{e}"}
        out = _strip_ansi((r.stdout or "") + (r.stderr or "")); ok = r.returncode == 0
        low = out.lower(); first = ((out.strip().split("\n") or [""])[0]).strip()
        nochange = any(k in low for k in ("not applied", "already", "no changes"))
        if dry:
            msg = "預覽(未套用)"
        elif nochange:
            msg = "未變更:" + first; ok = True
        elif ok:
            msg = "已" + ("開放" if on else "收回") + " " + name
        else:
            msg = "失敗:" + (first or "見輸出")
        return {"ok": ok, "dry": dry, "nochange": nochange, "msg": msg, "out": out[-800:]}
    if op == "rule_remove":   # 細粒度:移除單一網路規則(openshell policy update --remove-rule)
        name = body.get("name", ""); dry = bool(body.get("dry"))
        if not re.match(r"^[A-Za-z0-9._-]+$", name): return {"ok": False, "msg": "rule 名稱不合法"}
        flag = "--dry-run" if dry else "--wait --timeout 60"
        try:
            r = subprocess.run(f"openshell policy update {shlex.quote(sb)} --remove-rule {shlex.quote(name)} {flag}",
                               shell=True, capture_output=True, text=True, timeout=90, env=ENV)
        except Exception as e:
            return {"ok": False, "msg": f"執行失敗:{e}"}
        out = _strip_ansi((r.stdout or "") + (r.stderr or "")); ok = r.returncode == 0
        return {"ok": ok, "dry": dry, "msg": ("預覽(未套用)" if dry else (("已移除規則 " + name) if ok else "移除失敗")), "out": out[-800:]}
    if op == "endpoint_add":  # 細粒度:新增 host:port:access(+可選 binary)
        host = (body.get("host") or "").strip(); port = str(body.get("port") or "443").strip()
        access = (body.get("access") or "full").strip(); bins = body.get("binaries") or []
        dry = bool(body.get("dry"))
        if not re.match(r"^[A-Za-z0-9.*_-]+$", host): return {"ok": False, "msg": "host 不合法"}
        if not re.match(r"^\d{1,5}$", port): return {"ok": False, "msg": "port 不合法"}
        if access not in ("full", "rest", "websocket"): access = "full"
        binflags = " ".join(f"--binary {shlex.quote(b)}" for b in bins if re.match(r"^[/A-Za-z0-9._-]+$", b))
        flag = "--dry-run" if dry else "--wait --timeout 60"
        try:
            r = subprocess.run(f"openshell policy update {shlex.quote(sb)} --add-endpoint {shlex.quote(host + ':' + port + ':' + access)} {binflags} {flag}",
                               shell=True, capture_output=True, text=True, timeout=90, env=ENV)
        except Exception as e:
            return {"ok": False, "msg": f"執行失敗:{e}"}
        out = _strip_ansi((r.stdout or "") + (r.stderr or "")); ok = r.returncode == 0
        return {"ok": ok, "dry": dry, "msg": ("預覽(未套用)" if dry else (("已新增 " + host + ":" + port) if ok else "新增失敗")), "out": out[-800:]}
    if op == "prove":
        gaps, rc0, out = _prove(body.get("raw", ""))
        base = body.get("baseline")
        worse = (base is not None and gaps >= 0 and gaps > int(base))
        return {"ok": True, "gaps": gaps, "pass": rc0, "worse": worse,
                "msg": (f"critical/high 缺口 = {gaps}" + (" ⚠ 比現行更差" if worse else " · 未變差")), "out": out[-1500:]}
    if op == "apply":
        raw = body.get("raw", "")
        cand, _rc, cout = _prove(raw)
        if cand < 0:
            return {"ok": False, "msg": "prove 無法解析(政策可能語法錯誤),已拒絕套用", "out": cout[-1500:]}
        base, _b, _bo = _prove(_policy_raw(sb))   # 現行 live 政策基線
        if base >= 0 and cand > base:
            return {"ok": False, "blocked": True, "gaps": cand, "baseline_gaps": base,
                    "msg": f"❌ 已拒絕:此改動讓 critical/high 缺口由 {base} 增為 {cand}", "out": cout[-1500:]}
        os.makedirs(POLICY_PROVE_DIR, exist_ok=True)
        pf = f"{POLICY_PROVE_DIR}/apply.yaml"
        with open(pf, "w") as fh: fh.write(raw)
        try:
            r = subprocess.run(f"openshell policy set --policy {shlex.quote(pf)} {shlex.quote(sb)} --wait --timeout 40",
                               shell=True, capture_output=True, text=True, timeout=75, env=ENV)
        except Exception as e:
            return {"ok": False, "msg": f"套用失敗:{e}"}
        sout = _strip_ansi((r.stdout or "") + (r.stderr or "")); sok = r.returncode == 0
        return {"ok": sok, "gaps": cand, "baseline_gaps": base,
                "msg": (f"✅ prove 通過(缺口 {cand} ≤ 現行 {base})並已套用" if sok else "prove 通過但 set 失敗"), "out": sout[-1000:]}
    return {"ok": False, "msg": "未知操作"}

def do_device_action(do):
    # EBG19P 運維快速處置(寫入經 host executor;localhost only;二次確認在前端;每筆稽核)
    if do not in ("sync", "harden", "restart", "block"):
        return {"ok": False, "msg": "不允許的設備動作"}
    arg = ""
    if do == "block":  # 取目前未授權 MAC(node A /assets);無對象則略過
        cto = ct("worker-a")
        if cto:
            try:
                a = json.loads(sh(f"docker exec {cto} sh -c \"curl -s -m6 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/assets\"", 8))
                arg = next((x["mac"] for x in a.get("assets", []) if not x.get("known")), "")
            except Exception:
                arg = ""
        if not arg:
            return {"ok": True, "msg": "目前無未授權設備,無需封鎖"}
    out = sh(f"bash {DIR}/scripts/ebg19p-action.sh {shlex.quote(do)} {shlex.quote(arg)}", 60)
    _CACHE["ts"] = 0
    ok = "RESULT=ok" in out or "RESULT=skipped" in out
    msg = DEV_MSG.get(do, "完成") + (f"({arg})" if arg else "")
    return {"ok": ok, "msg": msg if ok else (DEV_MSG.get(do, "動作") + " 失敗(設備不可達或登入失敗,見稽核)")}


ADMIN_AUDIT = os.environ.get("DASH_AUDIT_FILE") or os.path.expanduser("~/.config/nemoclaw/admin-audit.jsonl")
_AUDIT_LOCK = threading.Lock()
def _audit_canon(e):
    return json.dumps([e["seq"], e["ts"], e["actor"], e["action"], e["detail"], e["ip"], e["ok"]], ensure_ascii=False)
def audit(actor, action, detail, ip, ok=True):
    # 防竄改:每筆 hash = sha256(prev_hash + canonical(entry)),串成鏈,改任一筆都會斷鏈。
    try:
        with _AUDIT_LOCK:
            os.makedirs(os.path.dirname(ADMIN_AUDIT), exist_ok=True)
            prev = "0" * 64; seq = 1
            if os.path.exists(ADMIN_AUDIT):
                last = None
                for l in open(ADMIN_AUDIT, encoding="utf-8"):
                    if l.strip(): last = l
                if last:
                    j = json.loads(last); prev = j.get("hash", "0" * 64); seq = int(j.get("seq", 0)) + 1
            e = {"seq": seq, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "actor": actor or "?",
                 "action": action, "detail": (detail or "")[:300], "ip": ip or "", "ok": bool(ok)}
            e["prev_hash"] = prev
            e["hash"] = hashlib.sha256((prev + _audit_canon(e)).encode()).hexdigest()
            with open(ADMIN_AUDIT, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception as ex:
        print("[audit] fail:", ex, flush=True)
def load_audit(n=40):
    try:
        rows = [json.loads(l) for l in open(ADMIN_AUDIT, encoding="utf-8") if l.strip()]
    except Exception:
        rows = []
    return rows[-n:][::-1]
def verify_audit():
    try:
        rows = [json.loads(l) for l in open(ADMIN_AUDIT, encoding="utf-8") if l.strip()]
    except Exception:
        return {"ok": True, "count": 0, "broken": None}
    prev = "0" * 64
    for e in rows:
        h = hashlib.sha256((prev + _audit_canon(e)).encode()).hexdigest()
        if e.get("prev_hash") != prev or e.get("hash") != h:
            return {"ok": False, "count": len(rows), "broken": e.get("seq")}
        prev = e["hash"]
    return {"ok": True, "count": len(rows), "broken": None}

_PORT_PREV = {}      # asset -> set(目前 up 的網口)(只由 notify_loop 維護)
_PORT_EVENTS = []    # 近期網口 up→down 事件(供 GUI 卡 + 告警)
_ANOM_ACTIVE = set() # 已告警的異常 id(消失再出現才重發)
_LOG_ACTIVE = set()  # 已告警的 syslog 分析發現 id
_LOG_SUMMARY_DAY = {"d": ""}  # 最近推播日報的日期(每日一次)
DEV_CPU_HI, DEV_RAM_HI, DEV_TEMP_HI = 85, 85, 80
def detect_anomalies(d):
    # 確定性資安/維運異常偵測:離線 / 越權突增 / 登入暴力 / 非工時管理 / 設備 CPU·RAM·溫度過高 / 網口斷線。
    out = []; now = time.time()
    _S = d.get("settings") or {}
    cpu_g = int(_S.get("dev_cpu_hi") or DEV_CPU_HI); ram_g = int(_S.get("dev_ram_hi") or DEV_RAM_HI); temp_g = int(_S.get("dev_temp_hi") or DEV_TEMP_HI)
    _dov = _S.get("dev_overrides") or {}
    def _thr(a, k, gd):
        o = _dov.get("lab-" + a) or _dov.get(a) or {}
        try:
            return int(o[k]) if k in o else gd
        except Exception:
            return gd
    for n in d.get("nodes", []):
        for m in (n.get("monitor") or []):
            asset = m.get("asset", "?")
            if m.get("offline") or m.get("status") == "offline":
                # 真實實機(ebg19p)離線屬環境常態 → info(中性 offline,不發紅色告警/Telegram);其餘維持 warn
                _real_off = "ebg19p" in asset
                out.append({"id": f"offline:{asset}", "sev": ("info" if _real_off else "warn"),
                            "kind": "device_offline", "msg": f"設備離線:{asset}(節點 {n.get('label')})",
                            "msg_en": f"Device offline: {asset} (node {n.get('label')})"})
                continue
            h = m.get("health") or {}
            cpu, ram, temp = h.get("cpu_pct"), h.get("ram_pct"), h.get("temp_c")
            cpu_hi, ram_hi, temp_hi = _thr(asset, "dev_cpu_hi", cpu_g), _thr(asset, "dev_ram_hi", ram_g), _thr(asset, "dev_temp_hi", temp_g)
            if isinstance(cpu, (int, float)) and cpu >= cpu_hi:
                out.append({"id": f"cpu:{asset}", "sev": ("high" if cpu >= 95 else "warn"), "kind": "device_cpu", "msg": f"{asset} CPU 高負載 {cpu}%(門檻 {cpu_hi}%)", "msg_en": f"{asset} high CPU load {cpu}% (threshold {cpu_hi}%)"})
            if isinstance(ram, (int, float)) and ram >= ram_hi:
                out.append({"id": f"ram:{asset}", "sev": "warn", "kind": "device_ram", "msg": f"{asset} 記憶體高用量 {ram}%(門檻 {ram_hi}%)", "msg_en": f"{asset} high memory usage {ram}% (threshold {ram_hi}%)"})
            if isinstance(temp, (int, float)) and temp >= temp_hi:
                out.append({"id": f"temp:{asset}", "sev": ("high" if temp >= 90 else "warn"), "kind": "device_temp", "msg": f"{asset} 溫度偏高 {temp}°C(門檻 {temp_hi}°C)", "msg_en": f"{asset} high temperature {temp}°C (threshold {temp_hi}°C)"})
    for ev in _PORT_EVENTS:
        if now - ev["t"] < 600:
            out.append({"id": ev["id"], "sev": "warn", "kind": "port_down", "msg": ev["msg"], "msg_en": ev.get("msg_en", ev["msg"])})
    g = d.get("governance", {}) or {}; den = g.get("denied", 0); hist = (d.get("history", {}) or {}).get("denied", []) or []
    if den >= 3 and hist:
        avg = sum(hist) / len(hist)
        if den > max(3, avg * 2):
            out.append({"id": "denied_spike", "sev": "high", "kind": "denied_spike", "msg": f"越權擋下突增:本期 {den} vs 均值 {avg:.0f}", "msg_en": f"Blocked-egress spike: {den} this period vs avg {avg:.0f}"})
    for ipk, lf in list(_LOGINF.items()):
        if lf.get("until", 0) > time.time():
            out.append({"id": f"loginlock:{ipk}", "sev": "high", "kind": "login_lock", "msg": f"登入暴力嘗試已鎖定:{ipk}", "msg_en": f"Login brute-force locked out: {ipk}"})
        elif lf.get("count", 0) >= 3:
            out.append({"id": f"loginfail:{ipk}", "sev": "warn", "kind": "login_fail", "msg": f"連續登入失敗 {lf.get('count')} 次:{ipk}", "msg_en": f"Repeated login failures ({lf.get('count')}): {ipk}"})
    for e in load_audit(20):
        if str(e.get("action", "")).startswith("/api/") and e.get("ok"):
            ts = e.get("ts", "")
            try:
                hh = int(ts[11:13])
            except Exception:
                hh = 12
            if hh < 7 or hh >= 21:
                out.append({"id": f"offhours:{ts}", "sev": "info", "kind": "offhours_admin", "msg": f"非工時管理動作:{e.get('action')} by {e.get('actor')} @ {ts[11:16]}", "msg_en": f"Off-hours admin action: {e.get('action')} by {e.get('actor')} @ {ts[11:16]}"})
                break
    return out
# 刻意未接的上行埠(無 cable / 無 WAN):其 link 會被 WAN 看門狗反覆 up→down,屬預期,不當 port_down 事件。
_PORT_IGNORE = {"lab-asus-ebg19p-01": {"WAN 1"}}   # WAN 1 flapping 屬環境問題,不發紅色 port_down 警告
_PORT_LAST = {}   # (asset,port) -> 上次發 port_down 的時間;去抖:同埠 600s 內只記一次,避免 flapping 洗版
def _track_ports(d):
    # 只在 notify_loop 呼叫:維護 up→down 狀態,產生 port_down 事件
    now = time.time()
    for n in d.get("nodes", []):
        for m in (n.get("monitor") or []):
            h = m.get("health") or {}
            if not h: continue
            asset = m.get("asset", "?")
            ign = _PORT_IGNORE.get(asset, set())
            up = {p.get("port") for p in (h.get("ports") or []) if p.get("state") == "up" and p.get("port") not in ign}
            prev = _PORT_PREV.get(asset)
            if prev is not None:
                for p in sorted(prev - up):
                    if p in ign:
                        continue
                    if now - _PORT_LAST.get((asset, p), 0) < 600:   # 去抖:同埠 10 分內已記過 → 不重複(flapping 不洗版)
                        continue
                    _PORT_LAST[(asset, p)] = now
                    _PORT_EVENTS.append({"t": now, "id": f"portdown:{asset}:{p}:{int(now)}", "msg": f"{asset} 網口 {p} 斷線(原為連線中)", "msg_en": f"{asset} port {p} went down (was up)"})
            _PORT_PREV[asset] = up
    if len(_PORT_EVENTS) > 50:
        del _PORT_EVENTS[:-50]

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _sid(self):
        try:
            c = SimpleCookie(self.headers.get("Cookie", "")); return c["sid"].value if "sid" in c else ""
        except Exception:
            return ""
    def _cip(self):
        # X-Forwarded-For 任何直連客戶端都能偽造(填 127.0.0.1 即繞過 IP 白名單與登入鎖),
        # 僅 DASH_TRUST_XFF=1(前面確有可信 reverse proxy)才採用,且取最右值=可信 proxy 記錄的直連端。
        if TRUST_XFF:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[-1].strip()
        return self.client_address[0]
    def _sess(self):
        v = get_session(self._sid())
        return v if (v and _ip_ok(self._cip())) else None
    def _send_cookie(self, code, obj, sid=None):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        if sid is not None:
            self.send_header("Set-Cookie", f"sid={sid}; HttpOnly; Path=/; SameSite=Strict" + ("; Secure" if DASH_TLS_ON else ""))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _serve_web(self, p):
        # static file server for the /app SPA under WEB_DIR (path-traversal guarded).
        # ETag/304 + caching: vendored libs are immutable (long cache → browser never re-fetches
        # React/Chart.js); app files revalidate cheaply. Keeps the dashboard light as the fleet grows.
        rel = "index.html" if p in ("/app", "/app/") else p[len("/app/"):]
        base = os.path.realpath(WEB_DIR)
        target = os.path.realpath(os.path.join(base, rel))
        if not (target == base or target.startswith(base + os.sep)) or not os.path.isfile(target):
            return self._send(404, "not found", "text/plain")
        st = os.stat(target)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304); self.send_header("ETag", etag); self.end_headers(); return
        with open(target, "rb") as f:
            body = f.read()
        cache = "public, max-age=31536000, immutable" if "/vendor/" in p else "no-cache, must-revalidate"
        self.send_response(200)
        self.send_header("Content-Type", _WEB_CT.get(os.path.splitext(target)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/brand.svg":
            return self._send(200, BRAND_SVG, "image/svg+xml; charset=utf-8")
        if p == "/app" or p.startswith("/app/"):   # React console (authed); coexists with the classic UI at /
            if not self._sess():
                if p in ("/app", "/app/"):
                    self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return
                return self._send(401, "auth required", "text/plain")
            return self._serve_web(p)
        if p == "/login":
            return self._send(200, LOGIN_HTML, "text/html; charset=utf-8")
        sess = self._sess()
        if p in ("/", "/index.html"):
            if not sess:
                self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return
            self.send_response(302); self.send_header("Location", "/app"); self.end_headers(); return   # SPA is the default UI now
        if not sess:
            return self._send(401, json.dumps({"error": "auth required"}), "application/json; charset=utf-8")
        if p == "/api/whoami":
            return self._send(200, json.dumps({"email": sess["email"], "role": sess["role"]}), "application/json; charset=utf-8")
        if p == "/api/audit":
            if sess["role"] != "admin":
                return self._send(403, json.dumps({"ok": False, "msg": "需要管理員權限"}), "application/json; charset=utf-8")
            return self._send(200, json.dumps({"recent": load_audit(80), "chain": verify_audit()}, ensure_ascii=False), "application/json; charset=utf-8")
        if p == "/api/policy-get":
            if sess["role"] != "admin":
                return self._send(403, json.dumps({"ok": False, "msg": "需要管理員權限"}), "application/json; charset=utf-8")
            sb = parse_qs(urlparse(self.path).query).get("sb", ["team-lead"])[0]
            try:
                return self._send(200, json.dumps(do_policy_get(sb), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        if p == "/api/policy-ro":   # 唯讀:任一 agent 的 live 政策(治理頁唯讀卡 agent 選單)
            sb = parse_qs(urlparse(self.path).query).get("sb", ["team-lead"])[0]
            try:
                return self._send(200, json.dumps(do_policy_ro(sb), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        if p == "/api/sys":   # on-demand;admin:doctor / logs / stale / gsettings / recover / gwhealth / infset
            if sess["role"] != "admin":
                return self._send(403, json.dumps({"ok": False, "out": "需要管理員權限"}), "application/json; charset=utf-8")
            q = parse_qs(urlparse(self.path).query)
            do = q.get("do", [""])[0]; sb = q.get("sb", [""])[0]; tail = q.get("tail", ["200"])[0]
            provider = q.get("provider", [""])[0]; model = q.get("model", [""])[0]; chan = q.get("chan", [""])[0]
            a1 = q.get("a1", [""])[0]; a2 = q.get("a2", [""])[0]
            try:
                return self._send(200, json.dumps(do_sys(do, sb, tail, provider, model, chan, a1, a2), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "out": str(e)}), "application/json")
        if p == "/api/status":
            try:
                data = dict(collect())
                _mc = load_users().get(sess["email"], {}).get("must_change", False)
                data["_me"] = {"email": sess["email"], "role": sess["role"], "must_change": _mc}
                data["anomalies"] = detect_anomalies(data)
                data["alerts_list"] = (data.get("alerts_list") or []) + [{"msg": a["msg"], "msg_en": a.get("msg_en", a["msg"])} for a in data["anomalies"] if a["sev"] in ("high", "warn")]
                if sess["role"] == "admin":
                    a = load_auth(); a["sessions"] = len(SESSIONS)
                    data["_acl"] = {"users": [{"email": e, "role": v.get("role"), "created": v.get("created")} for e, v in load_users().items()], "auth": a}
                    data["_audit"] = {"recent": load_audit(20), "chain": verify_audit()}
                self._send(200, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}), "application/json")
        else:
            self._send(404, "not found", "text/plain")
    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}
    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/login":
            body = self._body(); ip = self._cip()
            if not _ip_ok(ip):
                return self._send(403, json.dumps({"ok": False, "msg": "IP 不在白名單"}), "application/json; charset=utf-8")
            if _login_locked(ip):
                left = int(_LOGINF[ip]["until"] - time.time())
                audit(body.get("email") or "?", "login", "rate-locked", ip, False)
                return self._send(429, json.dumps({"ok": False, "msg": f"嘗試過多,請 {left} 秒後再試"}), "application/json; charset=utf-8")
            email = (body.get("email") or "").strip().lower(); u = _verify(email, body.get("password") or "")
            if not u:
                _login_fail(ip)
                audit(body.get("email") or "?", "login", "bad-credentials", ip, False)
                return self._send(200, json.dumps({"ok": False, "msg": "帳號或密碼錯誤"}), "application/json; charset=utf-8")
            _LOGINF.pop(ip, None)
            audit(email, "login", "ok", ip, True)
            return self._send_cookie(200, {"ok": True, "role": u.get("role")}, sid=new_session(email, u.get("role", "viewer"), ip))
        sess = self._sess()
        if not sess:
            return self._send(401, json.dumps({"ok": False, "msg": "auth required"}), "application/json; charset=utf-8")
        if p == "/api/logout":
            audit(sess["email"], "logout", "", self._cip()); SESSIONS.pop(self._sid(), None); return self._send_cookie(200, {"ok": True}, sid="")
        if sess["role"] != "admin":
            return self._send(403, json.dumps({"ok": False, "msg": "需要管理員權限"}), "application/json; charset=utf-8")
        audit(sess["email"], p, urlparse(self.path).query, self._cip())
        if p == "/api/users":
            return self._send(200, json.dumps(do_user_op(self._body(), sess["email"]), ensure_ascii=False), "application/json; charset=utf-8")
        if p == "/api/auth-config":
            return self._send(200, json.dumps(do_auth_config(self._body()), ensure_ascii=False), "application/json; charset=utf-8")
        if self.path.startswith("/api/action"):
            do = parse_qs(urlparse(self.path).query).get("do", [""])[0]
            if do not in ("cve", "source", "refresh", "patrol", "nuclei", "snooze30", "snooze120", "snooze_off", "backup"):
                return self._send(400, json.dumps({"ok": False, "msg": "不允許的動作"}), "application/json; charset=utf-8")
            try:
                self._send(200, json.dumps(do_action(do), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/config"):  # 管理設定(localhost only;推到兩台 endpoint)
            q = parse_qs(urlparse(self.path).query)
            k = q.get("k", [""])[0]; v = q.get("v", [""])[0]
            try:
                self._send(200, json.dumps(do_config(k, v), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/cert-policy"):  # 憑證政策覆寫 / 自訂 cipher
            q = parse_qs(urlparse(self.path).query)
            if "fam" in q:
                params = {"cipher_family": q.get("fam", [""])[0], "on": q.get("on", ["0"])[0] in ("1", "true")}
            else:
                params = {"scope": q.get("scope", [""])[0], "key": q.get("key", [""])[0], "value": q.get("value", [""])[0]}
            try:
                self._send(200, json.dumps(do_cert_policy(params), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/recipient"):  # 通知對象 / 管理者增刪(localhost only)
            q = parse_qs(urlparse(self.path).query)
            op = q.get("op", [""])[0]; nm = q.get("name", [""])[0]
            tg = q.get("telegram", [""])[0]; em = q.get("email", [""])[0]
            try:
                self._send(200, json.dumps(do_recipient(op, nm, tg, em), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/policy"):  # OpenShell policy 編輯(localhost only;admin;preset/prove/prove-gated apply)
            body = self._body()
            try:
                self._send(200, json.dumps(do_policy(body.get("op", ""), body), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/snapshot"):  # NemoClaw 快照 create/restore(localhost only;admin;前端二次確認)
            q = parse_qs(urlparse(self.path).query)
            op = q.get("op", [""])[0]; sel = q.get("sel", [""])[0]; sb = q.get("sb", ["worker-a"])[0]
            try:
                self._send(200, json.dumps(do_snapshot(op, sel, sb), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        elif self.path.startswith("/api/device-action"):  # EBG19P 運維快速處置(localhost only;前端二次確認)
            do = parse_qs(urlparse(self.path).query).get("do", [""])[0]
            try:
                self._send(200, json.dumps(do_device_action(do), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        else:
            self._send(404, "not found", "text/plain")
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print(f"[agent-dashboard] http://127.0.0.1:{PORT}  (token auth: {'on' if TOKEN else 'off'})", flush=True)
    def warm_loop():
        while True:
            if _CLOCK.acquire(blocking=False):
                try:
                    _collect_impl()
                except Exception:
                    pass
                finally:
                    _CLOCK.release()
            time.sleep(6)
    load_users()   # 確保種子帳號(Tony / admin)存在
    threading.Thread(target=warm_loop, daemon=True).start()   # 預熱快取,隱藏冷收集延遲
    threading.Thread(target=notify_loop, daemon=True).start()
    H.timeout = 30   # 單一連線閒置逾時,緩解 slowloris
    BIND = os.environ.get("DASH_BIND", "127.0.0.1")   # 預設只本機;設 0.0.0.0 或某 IP 即對網路開放
    class _DashServer(ThreadingHTTPServer):
        daemon_threads = True          # worker 為 daemon,異常不堆積、不擋關閉
        request_queue_size = 128       # 加大 accept backlog(對外曝露易有突發連線/掃描)
        def get_request(self):
            s, a = super().get_request()
            s.settimeout(30)           # 限制每連線(含 TLS 握手)時間,壞/慢連線不會卡住 worker
            return s, a
        def handle_error(self, request, client_address):
            pass                       # 吞掉單一連線錯誤(如 TLS 握手失敗),不影響其他連線
    srv = _DashServer((BIND, PORT), H)
    _cert, _key = f"{BRIDGE}/dash-cert.pem", f"{BRIDGE}/dash-key.pem"
    _tls = DASH_TLS_ON
    if _tls:
        import ssl
        _ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); _ctx.load_cert_chain(_cert, _key)
        # 關鍵:do_handshake_on_connect=False → TLS 握手延後到各自 worker 執行緒,
        # 不在主 accept 迴圈做;否則一個壞/慢握手就會卡死整台(本次「一陣子後連不到」的真因)。
        srv.socket = _ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    print(f"[agent-dashboard] {'https' if _tls else 'http'}://{BIND}:{PORT}", flush=True)
    if BIND not in ("127.0.0.1", "::1") and not _tls:
        print("[agent-dashboard] ⚠ 已對網路開放但未啟用 TLS:憑證將以明文傳輸。建議 gen-dash-tls.sh + DASH_TLS=1,並於設定頁設 IP 白名單。", flush=True)
    srv.serve_forever()
