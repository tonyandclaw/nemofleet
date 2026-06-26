#!/usr/bin/env python3
# agent-dashboard.py — NemoClaw Multi-Agent 即時狀態儀表板(host web server, Apple/enterprise-grade)。
# http://127.0.0.1:8899 → 整個 agent stack 活狀態 + 可操作控制 + 即時事件流/趨勢/告警/巡檢歷史。
# 渲染:側欄 menu + hash 路由分頁;分區 memo(內容沒變不重繪→無閃爍)。唯讀為主、每 call timeout、整體快取 ~8s、單項失敗降級。
# X-Bridge-Token 只 server 端用,不入 HTML/JSON。POST /api/action?do=cve|source|jira_reset|refresh(localhost only)。
import json, os, re, shlex, subprocess, threading, time, hashlib, secrets, base64
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
TOKEN = ""
try:
    TOKEN = open(f"{BRIDGE}/.bridge-token").read().strip()
except Exception:
    pass
NVM = os.environ.get("NEMOFLEET_NODE_BIN") or next(iter(sorted(_glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")), reverse=True)), "")
ENV = dict(os.environ, PATH=(NVM + ":" if NVM else "") + os.environ.get("PATH", ""))
WD = "/sandbox/.openclaw/workspace/it-task"
_CACHE = {"ts": 0, "data": None}
_COLLECT_TTL = int(os.environ.get("DASH_COLLECT_TTL", "5"))   # SWR 背景刷新間隔(秒);搭配 streamer 5s + 前端 5s 輪詢
HISTORY = []
try:                                                  # 真 NemoClaw/OpenClaw 家族品牌圖(🦞 Claw logo)
    BRAND_SVG = open(f"{BRIDGE}/assets/brand.svg").read()
except Exception:
    BRAND_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0066ff"/></svg>'

# ===== 存取控制:帳號 / session / RBAC / timeout / IP 白名單 =====
USERS_FILE = f"{BRIDGE}/dash-users.json"
AUTH_FILE = f"{BRIDGE}/dash-auth.json"
SEED_FILE = f"{DIR}/config/bridge/dash-seed.json"   # 首次啟動的種子帳密;git-ignored,見 config/bridge/README.md
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
def save_users(u):
    json.dump(u, open(USERS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
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
def save_auth(d): json.dump(d, open(AUTH_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
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

def parse_policy(out, sandbox="hermes-demo"):
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
    pri = {"greenmail_mail": 0, "telegram": 1, "telegram_bot": 2, "openclaw_bridge": 3, "nvidia": 4}
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

    d["gateway"] = sh("curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ 2>/dev/null", 4).strip() not in ("", "000")
    d["hermes_api"] = sh("curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8642/v1/models 2>/dev/null", 4).strip() not in ("", "000")
    cth = ct("hermes-demo")
    d["telegram_recent"] = 0
    if cth:
        try:
            d["telegram_recent"] = int(sh(f"docker logs --since 6m {cth} 2>&1 | grep -ac getUpdates", 6).strip() or 0)
        except Exception:
            pass

    cto = ct("my-assistant"); ct2 = ct("openclaw-2")
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
            la = read_json_in(c, "syslog-analysis.json")  # OpenClaw A syslog 進階分析(異常/根因/融合/日報;排程寫檔)
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

    polout = sh("openshell policy get hermes-demo --full 2>/dev/null", 12)
    d["bridge_ips"] = sorted(set(re.findall(r"172\.18\.0\.\d+/32", polout)))
    d["policy"] = parse_policy(polout)
    d["policy"]["sandboxes"] = _list_agent_sandboxes()   # 供唯讀卡 agent 選單
    # 快照是每個 sandbox 各自一份(Hermes / OpenClaw A / OpenClaw B)→ 逐台收集
    by_agent = []; all_names = []
    for label, sb in (("Hermes", "hermes-demo"), ("OpenClaw A", "my-assistant"), ("OpenClaw B", "openclaw-2")):
        items = []
        for ln in sh(f"nemoclaw {sb} snapshot list 2>/dev/null", 10).splitlines():
            mm = re.search(r"(v\d+)\s+(\S+)\s+(\S+)", ln)
            if mm and mm.group(2) not in ("name=", "Version"):
                items.append({"ver": mm.group(1), "name": mm.group(2), "ts": mm.group(3)})
        items = items[:6][::-1]   # CLI 新→舊;取最新 6 筆轉時間序(舊→新,最新在最後)
        by_agent.append({"label": label, "sb": sb, "items": items})
        all_names += [it["name"] for it in items]
    d["snapshots_by_agent"] = by_agent
    d["snapshots"] = all_names   # 全 stack 合計(KPI 計數用)
    d["snapshots_meta"] = next((a["items"] for a in by_agent if a["sb"] == "my-assistant"), [])

    al = []   # 雙語:{msg(zh), msg_en};前端用 L() 挑語言
    if not d["gateway"]: al.append({"msg": "OpenShell gateway :18080 離線", "msg_en": "OpenShell gateway :18080 offline"})
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
    for n in d.get("nodes", []):  # EBG19P syslog 進階分析(OpenClaw A):異常 / 融合洞察 → device 類別
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
    _CACHE["ts"] = now; _CACHE["data"] = d
    return d

ALLOWED_CFG = {"cve_interval_sec", "cert_interval_sec", "cert_expire_warn_days", "cert_rsa_min",
               "auto_escalate", "quiet_enabled", "quiet_start", "quiet_end", "quiet_days", "notify_channels", "cert_sig_min", "cert_cipher_policy", "cert_ec_min",
               "dev_cpu_hi", "dev_ram_hi", "dev_temp_hi"}
def do_config(k, v):
    # 管理設定:推到兩台 OpenClaw endpoint 的 /settings(各容器持久化;掃描迴圈讀取)
    if k not in ALLOWED_CFG:
        return {"ok": False, "msg": "不允許的設定"}
    b64 = base64.b64encode(json.dumps({k: v}).encode()).decode()  # ('"', '\\"')   # 巢狀 docker exec sh -c "..." 內的雙引號要逸出
    ok = False
    for frag in ("my-assistant", "openclaw-2"):
        c = ct(frag)
        if not c:
            continue
        out = sh(f"docker exec {c} sh -c \"echo {b64} | base64 -d | curl -s -m6 -H 'X-Bridge-Token: {TOKEN}' "
                 f"-H 'Content-Type: application/json' -X POST --data-binary @- http://127.0.0.1:9099/settings\"", 10)
        if '"ok":true' in out.replace(" ", ""):
            ok = True
    if ok and k in ("cert_rsa_min", "cert_expire_warn_days", "cert_sig_min", "cert_cipher_policy", "cert_ec_min"):  # 改門檻 → 立刻重掃刷新報表(避免時間差)
        cta = ct("my-assistant")
        if cta:
            sh(f"docker exec {cta} sh -c \"curl -s -m12 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/cert-scan\"", 16)
    _CACHE["ts"] = 0
    return {"ok": ok, "msg": f"{k} 已更新" if ok else "更新失敗(端點未回 ok)"}

def do_cert_policy(params):
    # 憑證政策:每設備覆寫 / 自訂 cipher 家族 → 推兩台 + 觸發重掃
    b64 = base64.b64encode(json.dumps(params).encode()).decode()  # ('"', '\\"')
    ok = False
    for frag in ("my-assistant", "openclaw-2"):
        c = ct(frag)
        if not c:
            continue
        out = sh(f"docker exec {c} sh -c \"echo {b64} | base64 -d | curl -s -m6 -H 'X-Bridge-Token: {TOKEN}' "
                 f"-H 'Content-Type: application/json' -X POST --data-binary @- http://127.0.0.1:9099/cert-policy\"", 10)
        if '"ok":true' in out.replace(" ", ""):
            ok = True
    if ok:
        cta = ct("my-assistant")
        if cta:
            sh(f"docker exec {cta} sh -c \"curl -s -m12 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/cert-scan\"", 16)
    _CACHE["ts"] = 0
    return {"ok": ok, "msg": "憑證政策已更新" if ok else "更新失敗"}

def do_recipient(op, name, telegram, email):
    # 通知對象增刪:推到兩台 endpoint /recipients;新增且有 email → 寄歡迎信進 GreenMail(可驗證)
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
    b64 = base64.b64encode(json.dumps({"op": op, "name": name, "telegram": telegram, "email": email}).encode()).decode()  # ('"', '\\"')
    last = {"ok": False, "msg": "更新失敗"}
    for frag in ("my-assistant", "openclaw-2"):
        c = ct(frag)
        if not c:
            continue
        out = sh(f"docker exec {c} sh -c \"echo {b64} | base64 -d | curl -s -m6 -H 'X-Bridge-Token: {TOKEN}' "
                 f"-H 'Content-Type: application/json' -X POST --data-binary @- http://127.0.0.1:9099/recipients\"", 10)
        try:
            last = json.loads(out)
        except Exception:
            pass
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
NOTIFY_SENDER = "tony@demo.local"   # Hermes email 白名單授權寄件者(觸發 Telegram 推播)
def _load_notified():
    try:
        return set(json.load(open(NOTIFIED_FILE, encoding="utf-8")))
    except Exception:
        return set()
def _save_notified(x):
    try:
        json.dump(sorted(x), open(NOTIFIED_FILE, "w", encoding="utf-8"))
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
    """新工單 → 通知每位收件人(Email 直送 GreenMail;Telegram 經 Hermes)。首啟以現有工單為基線、不補發歷史。"""
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

def do_action(do):
    ct2 = ct("openclaw-2")
    if do == "refresh":
        _CACHE["ts"] = 0; return {"ok": True, "msg": "已重新整理"}
    if do == "cve" and ct2:
        sh(f"docker exec {ct2} sh -c \"curl -s -m20 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/cve\"", 25)
        _CACHE["ts"] = 0; return {"ok": True, "msg": "節點 B 已重掃設備 CVE"}
    if do == "source" and ct2:
        sh(f"docker exec {ct2} sh -c \"curl -s -m25 -H 'X-Bridge-Token: {TOKEN}' http://127.0.0.1:9099/source-cve\"", 30)
        _CACHE["ts"] = 0; return {"ok": True, "msg": "節點 B 已重跑原始碼分析(SBOM/SAST)"}
    if do == "jira_reset":
        sh(f"bash {DIR}/demo/jira-reset.sh", 30); _CACHE["ts"] = 0
        return {"ok": True, "msg": "工單佇列已重置"}
    return {"ok": False, "msg": "未知動作"}

AUDIT_FILE = os.path.expanduser("~/.config/nemoclaw/ebg19p-audit.jsonl")
DEV_MSG = {"sync": "EBG19P 已強制同步", "harden": "EBG19P 已套用安全基準(關 UPnP/WPS、開 DoS)",
           "restart": "EBG19P 防火牆/無線服務已重啟", "block": "已送出未授權設備封鎖"}

def do_snapshot(op, sel, sb="my-assistant"):
    # NemoClaw 快照 create / restore(逐沙箱)。localhost only · admin-gated · 白名單 + shlex.quote
    # 注意:restore CLI 即使「Restore failed」也回 rc=0,故成功要看輸出文字,不能只看退出碼。
    sel = (sel or "").strip()
    if sb not in ("hermes-demo", "my-assistant", "openclaw-2"):
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

_SB_LABELS = {"hermes-demo": "Hermes · 對人前台", "my-assistant": "OpenClaw A · IT 運維",
              "openclaw-2": "OpenClaw B · 資安分析"}
def _list_agent_sandboxes():
    """枚舉實際存在的 agent 沙箱(供 GUI 政策編輯器切換)。讀 openshell sandbox list,附友善標籤。"""
    out, names = sh("openshell sandbox list 2>/dev/null", 12), []
    for ln in out.splitlines():
        m = re.match(r"\s*([a-z0-9][a-z0-9-]*)\s+\d{4}-\d{2}-\d{2}", _strip_ansi(ln))
        if m:
            names.append(m.group(1))
    # 維持 Hermes→A→B 的順序;只回已知 agent 沙箱
    order = ["hermes-demo", "my-assistant", "openclaw-2"]
    ordered = [n for n in order if n in names] + [n for n in names if n not in order]
    return [{"name": n, "label": _SB_LABELS.get(n, n)} for n in ordered]

def do_policy_get(sb):
    if not _policy_sb_ok(sb): sb = "hermes-demo"
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
    if not _policy_sb_ok(sb): sb = "hermes-demo"
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
    for ln in _strip_ansi(sh("nemoclaw hermes-demo channels list 2>/dev/null", 12)).splitlines():
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
        sbn = sb or "hermes-demo"
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
    sb = body.get("sb") or "hermes-demo"
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
        cto = ct("my-assistant")
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

HTML = r"""<!doctype html><html lang="zh-Hant" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NemoFleet · Agent Status</title>
<link rel="icon" type="image/svg+xml" href="/brand.svg">
<style>
:root{
 --bg:#fafafc;--card:#ffffff;--card2:#f3f4f7;--seg:#ececf0;--tx:#111114;--tx2:#5f636b;--tx3:#9398a1;--line:#e7e8ee;
 --accent:#0066ff;--ok:#0a875a;--okbg:#e6f5ee;--warn:#946200;--warnbg:#fbf0d9;--danger:#d11a2a;--dangerbg:#fbe9ea;--purple:#6e56cf;--purplebg:#efeafc;--accentbg:#e9f1ff;
 --sh1:0 0 0 1px rgba(20,20,40,.04);--sh2:0 2px 8px rgba(20,20,45,.05),0 14px 34px rgba(20,20,45,.05);
 --r:18px;--rs:10px;
}
html[data-theme="dark"]{
 --bg:#0b0b0d;--card:#161618;--card2:#202024;--seg:#26262b;--tx:#f2f2f4;--tx2:#a0a3ab;--tx3:#70737b;--line:#2a2a31;
 --accent:#4d8dff;--ok:#2ecc8f;--okbg:#0f3023;--warn:#e0a030;--warnbg:#2e2410;--danger:#ff5a66;--dangerbg:#331417;--purple:#a18aff;--purplebg:#1f1a36;--accentbg:#12233f;
 --sh1:0 0 0 1px rgba(255,255,255,.05);--sh2:0 2px 10px rgba(0,0,0,.35),0 16px 40px rgba(0,0,0,.45);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-variant-numeric:tabular-nums;
 font:14.5px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Inter","Helvetica Neue","PingFang TC","Microsoft JhengHei","Noto Sans TC",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;transition:background .35s,color .35s}
button:focus-visible,[tabindex]:focus-visible,a:focus-visible{outline:2.5px solid var(--accent);outline-offset:2px;border-radius:8px}
::selection{background:rgba(0,102,255,.18)}
a{color:inherit}
/* layout */
#app{display:flex;min-height:100vh}
.side{width:236px;flex:0 0 236px;position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:var(--card);padding:20px 14px;display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:11px;padding:6px 8px 16px}
.mk{width:34px;height:34px;border-radius:10px;background:radial-gradient(circle at 50% 38%,#10131c,#05070d);display:grid;place-items:center;box-shadow:0 4px 12px rgba(0,0,0,.28),inset 0 0 0 1px rgba(255,255,255,.06);flex:0 0 auto}
.mk img{width:26px;height:26px;display:block}
.brand h1{font-size:17px;font-weight:680;letter-spacing:-.02em}
.brand .bsub{font-size:11px;color:var(--tx3);margin-top:1px}
.nav{display:flex;flex-direction:column;gap:3px;margin-top:4px}
.nav a{display:flex;align-items:center;gap:11px;padding:9px 12px;border-radius:11px;color:var(--tx2);text-decoration:none;font-size:14px;font-weight:560;transition:background .15s,color .15s}
.nav a:hover{background:var(--card2);color:var(--tx)}
.nav a.on{background:var(--accent);color:#fff;box-shadow:0 5px 14px rgba(0,102,255,.32)}
.nav .ni{width:20px;text-align:center;font-size:15px;flex:0 0 auto}
.nb{margin-left:auto;font-size:10.5px;font-weight:800;padding:1px 7px;border-radius:980px;letter-spacing:.02em}
.nb.bad{background:var(--dangerbg);color:var(--danger)}
.nb.warn{background:var(--warnbg);color:var(--warn)}
.nav a.on .nb{background:rgba(255,255,255,.24);color:#fff}
.nb.off{display:none}
.side-ft{margin-top:auto;padding:13px 10px 4px;border-top:1px solid var(--line);font-size:12px;color:var(--tx2)}
.live{display:flex;align-items:center;gap:7px;font-weight:600}.live .d{width:8px;height:8px;border-radius:50%;background:var(--ok)}
@keyframes bp{0%,100%{opacity:1}50%{opacity:.25}}.live .d{animation:bp 2.4s ease-in-out infinite}
.main{flex:1;min-width:0;padding:26px 34px 64px}
.topbar{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.topbar h2{font-size:22px;font-weight:660;letter-spacing:-.02em}
.topbar .tsub{color:var(--tx2);font-size:13px;margin-top:2px}
.topbar .right{margin-left:auto;display:flex;align-items:center;gap:12px;color:var(--tx2);font-size:13px}
.tbuser{font-size:12.5px;color:var(--tx2);white-space:nowrap;max-width:210px;overflow:hidden;text-overflow:ellipsis}
.tbsep{width:1px;height:24px;background:var(--line);flex:0 0 auto}
.tbupd{font-size:12.5px;color:var(--tx2);white-space:nowrap;font-variant-numeric:tabular-nums}
.tbbtns{display:flex;gap:6px}
.btn.icon{padding:7px 11px}
.nav a.dragging{opacity:.45}
.nav a[draggable="true"]{cursor:grab}
.navreset{font-size:11px!important;color:var(--tx3)!important;font-weight:500!important;opacity:.85;margin-top:6px}
.tbuser:empty+.tbsep{display:none}
/* controls */
.seg{display:inline-flex;background:var(--seg);border-radius:11px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--tx2);font:inherit;font-size:12.5px;font-weight:560;padding:5px 13px;border-radius:8px;cursor:pointer;transition:.18s;white-space:nowrap}
.seg button:hover{color:var(--tx)}
.seg button.on{background:var(--card);color:var(--tx);box-shadow:0 1px 3px rgba(0,0,0,.14)}
.tlabel{color:var(--tx3);font-size:12px;font-weight:560}
.btn{border:1px solid var(--line);background:var(--card);color:var(--tx);font:inherit;font-size:12.5px;font-weight:560;padding:7px 15px;border-radius:980px;cursor:pointer;transition:.16s;box-shadow:var(--sh1)}
.btn:hover{background:var(--card2);transform:translateY(-1px)}.btn:active{transform:translateY(0) scale(.98)}
.btn[disabled]{opacity:.5;cursor:default;transform:none}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(10px);background:var(--tx);color:var(--bg);padding:11px 20px;border-radius:12px;font-size:14px;font-weight:560;box-shadow:var(--sh2);opacity:0;transition:.28s cubic-bezier(.2,.8,.2,1);pointer-events:none;z-index:20}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
/* banner */
.bn{display:flex;align-items:center;gap:10px;border-radius:14px;padding:13px 18px;font-weight:600;font-size:13.5px;border:1px solid;margin-bottom:20px}
.bn.ok{background:var(--okbg);color:var(--ok);border-color:transparent}
.bn.bad{background:var(--dangerbg);color:var(--danger);border-color:var(--danger);animation:alertpulse 2.4s ease-in-out infinite}
@keyframes alertpulse{0%,100%{box-shadow:0 0 0 0 rgba(209,26,42,0)}50%{box-shadow:0 0 0 5px rgba(209,26,42,.13)}}
body.stale #view{opacity:.5;filter:saturate(.55);transition:opacity .3s,filter .3s}
/* kpi */
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:14px}
@media(max-width:1180px){.kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:560px){.kpis{grid-template-columns:repeat(2,1fr)}}
a.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:17px 18px;box-shadow:var(--sh2);transition:transform .16s,box-shadow .16s,border-color .16s;text-decoration:none;color:inherit;display:block;position:relative}
a.kpi:hover{transform:translateY(-2px);border-color:var(--accent)}
a.kpi::after{content:'→';position:absolute;top:15px;right:16px;color:var(--tx3);opacity:0;transition:.16s;font-size:14px}
a.kpi:hover::after{opacity:1;transform:translateX(2px)}
.kpi .n{font-size:33px;font-weight:600;letter-spacing:-.035em;line-height:1.04}
.kpi .n small{font-size:14px;color:var(--tx3);font-weight:560;letter-spacing:0}
.kpi .l{color:var(--tx2);font-size:12.5px;margin-top:7px;font-weight:500}
.red{color:var(--danger)}.ok{color:var(--ok)}.mut{color:var(--tx2)}
/* sections + cards */
.sec{font-size:12px;color:var(--tx3);margin:28px 4px 13px;font-weight:680;letter-spacing:.05em;text-transform:uppercase}
.grid{display:grid;gap:16px}
.g4{grid-template-columns:repeat(4,1fr)}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:1.4fr 1fr 1fr}
@media(max-width:1180px){.g4{grid-template-columns:1fr 1fr}.g3{grid-template-columns:1fr}}
@media(max-width:720px){.g4,.g2,.g3{grid-template-columns:1fr!important}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:19px 20px;box-shadow:var(--sh2)}
.cardlink{text-decoration:none;color:inherit;display:block;transition:transform .16s,border-color .16s}
.cardlink:hover{border-color:var(--accent);transform:translateY(-2px)}
.ct{font-size:12.5px;color:var(--tx2);font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:9px}
.ct b{color:var(--tx);font-size:14.5px;font-weight:660}
.ico{width:25px;height:25px;border-radius:8px;display:grid;place-items:center;font-size:13px;flex:0 0 auto}
.kv{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--line);font-size:14px}
.kv:first-of-type{border-top:0}.kv .k{color:var(--tx2)}.kv .v{font-weight:600}
.pill{padding:3px 11px;border-radius:980px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.ok{color:var(--ok);background:var(--okbg)}.pill.bad{color:var(--danger);background:var(--dangerbg)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:9px;vertical-align:middle}
.dot.g{background:var(--ok)}.dot.r{background:var(--danger)}.dot.a{background:var(--warn)}
.mono{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;letter-spacing:-.01em}
.tags{margin:0 0 12px}.tag{display:inline-block;background:var(--card2);border-radius:7px;padding:3px 10px;margin:0 6px 6px 0;font-size:11.5px;color:var(--tx2);font-weight:560}
/* device rows (fleet) */
.dev{padding:11px 0;border-top:1px solid var(--line)}.dev:first-of-type{border-top:0}
.devh{display:flex;align-items:center;justify-content:space-between;font-size:14px}
.devd{margin-top:7px;padding-left:16px;font-size:12.5px}
.dl{font-weight:600;margin-right:7px}.dl.red{color:var(--danger)}.dl.warn{color:var(--warn)}
.chip{display:inline-block;background:var(--card2);border-radius:6px;padding:2px 8px;margin:2px 5px 2px 0;font-size:11.5px;font-family:"SF Mono",ui-monospace,monospace;color:var(--tx2)}
.ast{display:flex;align-items:center;gap:9px;padding:7px 0;border-top:1px solid var(--line);font-size:12.5px}.ast:first-of-type{border-top:0}
.ast .am{font-family:"SF Mono",ui-monospace,monospace;color:var(--tx2);font-size:11.5px}
.ast .ai{margin-left:auto;font-family:"SF Mono",ui-monospace,monospace;color:var(--tx3);font-size:11.5px}
.ast .ab{font-size:10px;font-weight:700;padding:1px 7px;border-radius:980px}.ast .ab.k{color:var(--ok);background:var(--okbg)}.ast .ab.u{color:var(--danger);background:var(--dangerbg)}
/* tables */
table.tb{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.tb th{text-align:left;color:var(--tx3);font-size:11px;font-weight:680;text-transform:uppercase;letter-spacing:.03em;padding:7px 10px;border-bottom:1px solid var(--line)}
.tb td{padding:9px 10px;border-bottom:1px solid var(--line)}
.tb tr:last-child td{border-bottom:0}
.tb tbody tr{transition:background .14s}.tb tbody tr:hover{background:var(--card2)}
.sev{font-weight:800;font-size:11px;text-transform:uppercase;letter-spacing:.02em}.sev.high{color:var(--danger)}.sev.med{color:var(--warn)}
/* viz */
.split{display:flex;gap:20px;align-items:center;margin-top:4px}
.legend{font-size:12.5px;color:var(--tx2);line-height:2}.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:7px}
.stat{display:flex;gap:10px;margin-top:14px}.stat .s{background:var(--card2);border-radius:12px;padding:12px;flex:1;text-align:center}
.stat .s b{display:block;font-size:22px;font-weight:600;letter-spacing:-.02em}.stat .s span{font-size:11.5px;color:var(--tx2)}
.bar{display:flex;align-items:center;gap:11px;margin:11px 0;font-size:13px}
.bar .bl{width:172px;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .bt{flex:1;height:8px;background:var(--card2);border-radius:6px;overflow:hidden}
.bar .bf{height:100%;border-radius:6px;background:var(--accent)}
.bar .bv{width:48px;text-align:right;font-weight:600}
.evrow{border-top:1px solid var(--line)}.evrow:first-child{border-top:0}
.ev{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:13px;cursor:pointer;border-radius:8px;transition:background .12s}
.ev:hover{background:var(--card2)}
.ev .t{color:var(--tx3);font-size:11.5px;width:96px;flex:0 0 auto;font-variant-numeric:tabular-nums}
.evx{margin-left:8px;color:var(--tx3);font-size:10px;flex:0 0 auto}
.evd{padding:2px 10px 13px 106px;display:grid;grid-template-columns:1fr 1fr;gap:8px 22px}
@media(max-width:700px){.evd{grid-template-columns:1fr;padding-left:14px}}
.evdk{display:flex;flex-direction:column;gap:2px;font-size:12.5px;min-width:0}
.evdk span{color:var(--tx3);font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}.evdk b{color:var(--tx);font-weight:600;word-break:break-word;font-family:"SF Mono",ui-monospace,monospace}
.ev .vb{font-size:10.5px;font-weight:800;width:54px;flex:0 0 auto;letter-spacing:.02em}.ev .vb.a{color:var(--ok)}.ev .vb.d{color:var(--danger)}.ev .vb.n{color:var(--tx3)}
.bnt{font-size:9.5px;font-weight:700;color:var(--tx2);background:var(--card2);border-radius:5px;padding:1px 6px}
.evbn{grid-column:1/-1;background:var(--card2);border-radius:8px;padding:9px 12px;font-size:12px;color:var(--tx2);line-height:1.6}
.codeblk{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.5;overflow-x:auto}
.codeblk .pl{white-space:pre-wrap;word-break:break-word;padding:0 4px;border-radius:3px}
.pl-a{background:var(--okbg);color:var(--ok)}
.pl-d{background:var(--dangerbg);color:var(--danger)}
.pl-h{color:var(--accent)}
.ev .pol{font-size:12px;color:var(--accent);font-weight:600;font-family:"SF Mono",ui-monospace,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40%}.ev .pol.d{color:var(--danger)}.ev .pol.n{color:var(--tx2)}.ev .tg{color:var(--tx3);font-size:12px;margin-left:auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:42%;font-family:"SF Mono",ui-monospace,monospace}
.snap{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line);font-size:13px}.snap:first-of-type{border-top:0}.snap .sd{width:6px;height:6px;border-radius:50%;background:var(--purple);flex:0 0 auto}
.gh{display:flex;gap:5px;align-items:flex-end;flex-wrap:wrap}
.gb{width:15px;height:26px;border-radius:4px;background:var(--ok)}.gb.f{background:var(--danger)}.gb.br{box-shadow:inset 0 0 0 2px var(--accent)}
.donut{animation:pop .5s cubic-bezier(.2,.8,.2,1)}@keyframes pop{from{opacity:.2;transform:scale(.92)}to{opacity:1;transform:scale(1)}}
.filtrow{display:flex;align-items:center;gap:11px;margin-bottom:16px}
.acts{display:flex;gap:9px;flex-wrap:wrap;margin-top:15px}
/* live architecture tab — dark-dashboard inspired (deep stage · glow · flow lines) */
.arch{position:relative;max-width:720px;margin:0 auto;padding:24px 22px 26px;border-radius:22px;border:1px solid var(--line);background:var(--card);overflow:hidden}
.arch::before{content:"";position:absolute;inset:0;background:radial-gradient(85% 46% at 50% -8%,var(--accentbg),transparent 60%);opacity:.8;pointer-events:none}
html[data-theme="dark"] .arch{background:linear-gradient(180deg,#121319,#0c0d11);border-color:#23242c}
html[data-theme="dark"] .arch::before{opacity:1;background:radial-gradient(80% 46% at 50% -10%,rgba(77,141,255,.16),transparent 62%)}
.arch>*{position:relative;z-index:1}
.aband{position:relative;display:block;border-radius:16px;padding:14px 18px 14px 22px;border:1px solid var(--line);background:var(--card);box-shadow:var(--sh2);overflow:hidden;transition:transform .16s,box-shadow .16s}
.aband::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px}
.aband:hover{transform:translateY(-2px)}
.aband.nemo{background:linear-gradient(105deg,var(--purplebg),var(--card) 62%);box-shadow:var(--sh2),0 8px 30px -10px var(--purple)}.aband.nemo::before{background:var(--purple);box-shadow:0 0 12px var(--purple)}
.aband.shell{background:linear-gradient(105deg,var(--accentbg),var(--card) 62%);box-shadow:var(--sh2),0 8px 30px -10px var(--accent)}.aband.shell::before{background:var(--accent);box-shadow:0 0 12px var(--accent)}
.aptag{font-size:9px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--tx3);margin-bottom:4px}
.aband .bt,.abox .bt{display:flex;align-items:center;gap:10px;font-weight:660;font-size:14px}
.aband .bd,.abox .bd{color:var(--tx2);font-size:11.5px;margin-top:5px;line-height:1.55;word-break:break-word}
.aico{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;font-size:14px;flex:0 0 auto}
.aico.p{background:var(--purplebg);color:var(--purple)}.aico.a{background:var(--accentbg);color:var(--accent)}.aico.g{background:var(--okbg);color:var(--ok)}.aico.w{background:var(--warnbg);color:var(--warn)}
.atier{display:flex;gap:16px;justify-content:center;align-items:stretch}
.abox{position:relative;flex:1 1 0;min-width:0;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:15px;padding:13px 15px;box-shadow:var(--sh2);text-decoration:none;color:inherit;transition:transform .16s,box-shadow .16s,border-color .16s}
.abox:hover{transform:translateY(-3px);border-color:var(--accent);box-shadow:var(--sh2),0 10px 28px -12px var(--accent)}
.abox .bt{font-size:13px;font-weight:640}
.conn{display:flex;flex-direction:column;align-items:center;gap:0;padding:4px 0}
.conn .ln{width:2px;height:18px;border-radius:2px;background:linear-gradient(to bottom,transparent 8%,var(--accent));background-size:100% 220%;animation:aflow 1.5s linear infinite;opacity:.55}
@keyframes aflow{0%{background-position:0 100%}100%{background-position:0 -120%}}
.conn .pill{font-size:10.5px;color:var(--tx2);background:var(--card2);border:1px solid var(--line);border-radius:980px;padding:3px 12px;font-weight:560;white-space:nowrap;max-width:96%;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.conn .tip{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid var(--accent);opacity:.6;margin-top:1px}
.asplit{display:flex;gap:16px}.asplit>.conn{flex:1 1 0;min-width:0}.asplit .pill{font-family:"SF Mono",ui-monospace,monospace;font-size:10px}
.adot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.adot.g{background:var(--ok);box-shadow:0 0 8px var(--ok),0 0 0 3px var(--okbg)}.adot.r{background:var(--danger);box-shadow:0 0 9px var(--danger),0 0 0 3px var(--dangerbg)}
.aleg{text-align:center;color:var(--tx3);font-size:11px;margin-top:18px}
.encl{position:relative;border:1.5px solid var(--accent);border-radius:18px;padding:14px 16px 18px;margin:4px 0;background:linear-gradient(180deg,var(--accentbg),transparent 46%)}
html[data-theme="dark"] .encl{background:linear-gradient(180deg,rgba(77,141,255,.10),transparent 48%)}
.enclh{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:12.5px;font-weight:700;color:var(--accent)}
.enclh .encltag{font-size:9px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--tx3)}
.encld{font-size:11px;color:var(--tx2);margin:5px 0 14px}
a.enclh{cursor:pointer;text-decoration:none;border-radius:8px;transition:opacity .15s}a.enclh:hover{opacity:.78}
.recadd{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px;align-items:center}
.rcin{flex:1;min-width:110px;background:var(--card2);border:1px solid var(--line);border-radius:9px;padding:8px 11px;color:var(--tx);font:inherit;font-size:13px}
.rcin::placeholder{color:var(--tx3)}
.rcin:focus{outline:2px solid var(--accent);outline-offset:1px}
.famrow{display:flex;flex-wrap:wrap;gap:6px}
.fam{border:1px solid var(--line);background:var(--card);color:var(--tx2);font:inherit;font-size:11.5px;font-weight:600;padding:4px 10px;border-radius:8px;cursor:pointer;font-family:"SF Mono",ui-monospace,monospace;transition:.14s}
.fam:hover{border-color:var(--danger)}
.fam.on{background:var(--danger);color:#fff;border-color:transparent}
.hsel{background:var(--card2);border:1px solid var(--line);border-radius:9px;padding:6px 10px;color:var(--tx);font:inherit;font-size:13px;cursor:pointer}
.qcfg{display:flex;align-items:center;gap:9px;margin-top:11px;flex-wrap:wrap}
.qlb{font-size:12.5px;color:var(--tx2);font-weight:560}
.qdays{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}
.dchip{border:1px solid var(--line);background:var(--card);color:var(--tx2);font:inherit;font-size:12px;font-weight:600;padding:5px 12px;border-radius:8px;cursor:pointer;transition:.14s}
.dchip:hover{border-color:var(--accent)}.dchip.on{background:var(--accent);color:#fff;border-color:transparent}
.cfind{padding:10px 0;border-top:1px solid var(--line)}
.cfind:first-child{border-top:0}
.cfh{display:flex;align-items:center;gap:9px}
.cfsev{font-size:10px;font-weight:800;letter-spacing:.03em}
.cfsev.r{color:var(--danger)}.cfsev.w{color:var(--warn)}
.cfd{color:var(--tx);font-size:13px;margin-top:5px;line-height:1.5}
.cffix{color:var(--tx2);font-size:12px;margin-top:5px;background:var(--card2);border-radius:8px;padding:7px 10px}
.cfst{margin-top:7px;border:1px solid var(--line);border-radius:8px;padding:7px 10px}
.cfsth{font-size:10px;font-weight:800;letter-spacing:.04em;color:var(--tx3);text-transform:uppercase;margin-bottom:4px}
.cfstr{display:flex;justify-content:space-between;gap:12px;font-size:12px;padding:2px 0}
.cfstr span{color:var(--tx2)}.cfstr b{color:var(--tx);word-break:break-all;text-align:right}
@keyframes flash{0%{box-shadow:0 0 0 0 rgba(0,102,255,.0)}25%{box-shadow:0 0 0 3px var(--accent)}100%{box-shadow:0 0 0 0 rgba(0,102,255,.0)}}
.flash{animation:flash 1.25s ease-out}
.dbarwrap{display:flex;align-items:center;gap:11px}
.dbar{flex:1;max-width:230px;accent-color:var(--accent);cursor:pointer;height:5px}
.dbe{font-size:11px;color:var(--tx3);white-space:nowrap}
.dbv{font-size:13px;font-weight:700;color:var(--accent);min-width:14px;text-align:center;font-variant-numeric:tabular-nums}
.sbpol{margin-top:8px;display:flex;flex-wrap:wrap;gap:4px}
.sbpol .pc{font-size:9.5px;font-weight:600;font-family:"SF Mono",ui-monospace,monospace;background:var(--accentbg);color:var(--accent);border-radius:6px;padding:1px 7px}
.sbpol .pc.sb{background:var(--purplebg);color:var(--purple)}
.sbpol .pc.deny{background:var(--card2);color:var(--tx2)}
.topo{max-width:760px;margin:0 auto}
.tlayer{font-size:11px;color:var(--tx3);font-weight:800;letter-spacing:.06em;text-transform:uppercase;margin:18px 2px 8px}
.tlayer:first-child{margin-top:0}
.tlink{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:11px 14px;margin-bottom:9px;box-shadow:var(--sh1)}
.tends{display:flex;align-items:center;gap:10px;font-weight:640;font-size:13.5px}
.tnode{color:var(--tx);white-space:nowrap}
.tarw{flex:1;height:2px;border-radius:2px;background:linear-gradient(90deg,var(--accent),transparent 90%);background-size:200% 100%;animation:aflow 1.5s linear infinite;min-width:22px;opacity:.6}
.tmeta{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-top:8px}
.tproto{font-family:"SF Mono",ui-monospace,monospace;font-size:10.5px;color:var(--accent);background:var(--accentbg);border-radius:6px;padding:2px 8px}
.tst{font-size:10.5px;font-weight:700;border-radius:980px;padding:2px 9px;white-space:nowrap}
.tst.g{color:var(--ok);background:var(--okbg)}.tst.r{color:var(--danger);background:var(--dangerbg)}.tst.a{color:var(--warn);background:var(--warnbg)}
.ttraf{font-size:11px;color:var(--tx2);font-variant-numeric:tabular-nums}
.tevt{font-size:10.5px;font-weight:700;color:var(--danger);background:var(--dangerbg);border-radius:6px;padding:2px 8px}
.aflow{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;align-items:center}
.archev{display:flex;flex-wrap:wrap;gap:7px;align-items:center;max-width:720px;margin:0 auto 14px;background:var(--card);border:1px solid var(--line);border-radius:13px;padding:10px 14px;box-shadow:var(--sh1)}
.archevh{font-size:11px;font-weight:800;color:var(--tx2);text-transform:uppercase;letter-spacing:.05em;margin-right:4px}
.sank{padding:4px 0}
.skl{font-family:-apple-system,system-ui,sans-serif;font-size:11px;fill:var(--tx2)}
.skl.b{fill:var(--tx);font-weight:700}
.skl.r{fill:var(--danger);font-weight:700}
.skl.g{fill:var(--ok);font-weight:700}
.skl.b{fill:var(--tx);font-weight:700;font-size:12.5px}
.skl.h{fill:var(--tx3);font-size:10px;font-weight:800;letter-spacing:.04em}
.sksub{max-width:760px;margin:0 auto;color:var(--tx2);font-size:12.5px;text-align:center;line-height:1.5}
.sklgrow{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin:9px auto 0;max-width:760px}
.sklg{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--tx2);font-weight:600}
.sklg i{width:12px;height:12px;border-radius:3px;display:inline-block}
.explain{max-width:620px;margin:0 auto}
.xpintro{text-align:center;color:var(--tx2);font-size:13px;margin-bottom:16px}
.xstep{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:15px 18px;box-shadow:var(--sh2)}
.xnum{flex:0 0 auto;width:32px;height:32px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;font-size:16px;font-weight:700}
.xbody{flex:1;min-width:0}
.xhead{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.xhead b{font-size:15.5px;font-weight:680}
.xico{font-size:16px}
.xstwrap{margin-left:auto}
.xst{font-size:12px;font-weight:700;border-radius:980px;padding:3px 11px;white-space:nowrap}
.xst.g{color:var(--ok);background:var(--okbg)}.xst.a{color:var(--warn);background:var(--warnbg)}.xst.r{color:var(--danger);background:var(--dangerbg)}
.xdesc{color:var(--tx2);font-size:13px;margin-top:6px;line-height:1.55}
.xarrow{text-align:center;color:var(--tx3);font-size:17px;line-height:1;margin:4px 0}
@media(max-width:640px){.atier,.asplit{flex-direction:column}}
/* device detail slide-over(點龍蝦受管設備看細節)*/
.ovl{position:fixed;inset:0;background:rgba(10,12,20,.42);opacity:0;pointer-events:none;transition:opacity .25s;z-index:30;backdrop-filter:blur(2px)}
.ovl.on{opacity:1;pointer-events:auto}
.drw{position:fixed;top:0;right:0;height:100vh;width:min(580px,94vw);background:var(--bg);border-left:1px solid var(--line);box-shadow:-24px 0 60px rgba(0,0,0,.28);transform:translateX(101%);transition:transform .32s cubic-bezier(.2,.85,.25,1);z-index:31;overflow-y:auto;padding:22px 24px 44px}
.drw.on{transform:translateX(0)}
.drwh{display:flex;align-items:center;gap:12px;margin-bottom:4px}
.drwh .mk{width:38px;height:38px;border-radius:11px;background:radial-gradient(circle at 50% 38%,#10131c,#05070d);display:grid;place-items:center;box-shadow:0 4px 12px rgba(0,0,0,.28),inset 0 0 0 1px rgba(255,255,255,.06);flex:0 0 auto}
.drwh .mk img{width:28px;height:28px}
.drwh h2{font-size:19px;font-weight:680;letter-spacing:-.02em}.drwh .ds{font-size:11.5px;color:var(--tx2);margin-top:1px}
.drwx{margin-left:auto;width:32px;height:32px;border-radius:9px;border:1px solid var(--line);background:var(--card);display:grid;place-items:center;cursor:pointer;color:var(--tx2);font-size:16px;transition:.15s}.drwx:hover{background:var(--card2);color:var(--tx)}
.dsec{font-size:11px;color:var(--tx3);font-weight:680;letter-spacing:.05em;text-transform:uppercase;margin:20px 2px 9px}
.clickable{cursor:pointer}.clickable:hover{background:var(--card2)}
.mgd{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;color:var(--accent);background:var(--accentbg);border-radius:980px;padding:1px 8px 1px 5px;margin-left:7px;vertical-align:middle}
.mgd img{width:12px;height:12px}
.skgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}
@media(max-width:1180px){.skgrid{grid-template-columns:repeat(2,1fr)}}
.skel{height:92px;border-radius:18px;border:1px solid var(--line);background:linear-gradient(90deg,var(--card),var(--card2),var(--card));background-size:400px 100%;animation:shimmer 1.25s linear infinite}
@keyframes shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}
/* settings */
.setrow{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 0;border-top:1px solid var(--line)}.setrow>:first-child{min-width:0}.thsub{color:var(--tx3);font-size:11.5px;font-weight:600;letter-spacing:.02em;margin:2px 0 3px}.threshcard .setrow{display:block;padding:11px 0}.threshcard .setrow>:first-child{margin-bottom:8px}.threshcard .seg{flex-wrap:wrap;max-width:100%}
.setrow:first-of-type{border-top:0}
.sk{font-weight:600;font-size:14px}.sd2{color:var(--tx2);font-size:12px;margin-top:2px}
/* density:compact */
body[data-density="compact"]{font-size:13.5px}
body[data-density="compact"] .main{padding:18px 22px 40px}
body[data-density="compact"] .card{padding:14px 15px;border-radius:14px}
body[data-density="compact"] a.kpi{padding:13px 14px;border-radius:14px}
body[data-density="compact"] .kpi .n{font-size:27px}
body[data-density="compact"] .sec{margin:18px 4px 9px}
body[data-density="compact"] .nav a{padding:7px 12px}
body[data-density="compact"] .kv,body[data-density="compact"] .ev,body[data-density="compact"] .dev{padding-top:6px;padding-bottom:6px}
body[data-density="compact"] .grid{gap:11px}body[data-density="compact"] .kpis{gap:11px}
/* 分頁切換特效:整頁淡入上浮 + 卡片依序浮現(線上架構不套,保留其流動線動畫)*/
@keyframes viewin{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes riseIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
.viewin{animation:viewin .34s cubic-bezier(.2,.8,.2,1)}
.viewin>*{animation:riseIn .46s both cubic-bezier(.2,.8,.2,1)}
.viewin>*:nth-child(2){animation-delay:.05s}
.viewin>*:nth-child(3){animation-delay:.1s}
.viewin>*:nth-child(4){animation-delay:.15s}
.viewin>*:nth-child(n+5){animation-delay:.19s}
@media(prefers-reduced-motion:reduce){.viewin,.viewin>*{animation:none}}
/* responsive */
@media(max-width:820px){
 #app{flex-direction:column}
 .side{width:auto;flex:none;position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:12px}
 .brand{padding:2px 6px 10px}
 .nav{flex-direction:row;flex-wrap:wrap;gap:5px}.nav a{padding:7px 11px}
 .side-ft{display:none}
 .main{padding:18px}
}
.tlrow{display:flex;align-items:center;gap:13px;padding:9px 0;border-top:1px solid var(--line);font-size:13px}
.tlrow:first-child{border-top:0}
.tlt{color:var(--tx2);flex:0 0 90px;font-size:12px;font-variant-numeric:tabular-nums}
.tlty{flex:0 0 78px;font-size:11.5px;font-weight:600;color:var(--tx2)}
.tlty.gov{color:var(--accent)}.tlty.jira{color:var(--warn)}.tlty.audit{color:var(--purple)}.tlty.guard{color:var(--ok)}
.tla{flex:0 0 auto;font-weight:600;color:var(--tx)}
.tla.d{color:var(--danger)}.tla.a{color:var(--ok)}.tla.w{color:var(--warn)}
.tlb{flex:1;min-width:0;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tclg{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--tx2);margin:4px 0 8px}
.tclg i{display:inline-block;width:12px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.tserh{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--tx2);margin-bottom:2px}
.tserh i{display:inline-block;width:12px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.tserh b{color:var(--tx);font-size:14px;font-variant-numeric:tabular-nums}
.tchart{position:relative}
.tcx{fill:var(--tx3);font-size:9px;font-family:-apple-system,system-ui,sans-serif}
.tctip{position:absolute;top:-4px;background:var(--tx);color:var(--bg);font-size:11px;line-height:1.45;padding:5px 9px;border-radius:8px;pointer-events:none;white-space:nowrap;transform:translateX(-50%);display:none;z-index:6;box-shadow:var(--sh2)}
@media(max-width:560px){.tlty{display:none}.tlb{flex-basis:100%}}
</style></head>
<script>(function(){try{var q=new URLSearchParams(location.search),u=q.get('theme'),lg=q.get('lang');if(u==='dark'||u==='light')localStorage.setItem('nclaw-theme',u);if(lg==='en'||lg==='zh')localStorage.setItem('nclaw-lang',lg);document.documentElement.setAttribute('data-theme',localStorage.getItem('nclaw-theme')||'light')}catch(e){}})();</script>
<body>
<div id="app">
 <aside class="side">
  <div class="brand"><span class="mk"><img src="/brand.svg" alt="NemoFleet" width="26" height="26"></span><div><h1>NemoFleet</h1><div class="bsub">Agent Control Plane</div></div></div>
  <nav class="nav" id="nav"></nav>
  <div class="side-ft"><span class="live"><span class="d" id="liveDot"></span><span id="liveTxt">即時連線</span></span><div id="sft" style="margin-top:7px">—</div></div>
 </aside>
 <main class="main">
  <div class="topbar">
   <div><h2 id="ttitle">總覽</h2><div class="tsub" id="tsub"></div></div>
   <div class="right"><span id="meuser" class="tbuser"></span><span class="tbsep"></span><span id="upd" class="tbupd"></span><span class="tbsep"></span><div class="tbbtns"><button class="btn icon" id="refreshBtn" data-act="do" data-v="refresh">↻</button><button class="btn" id="logoutBtn" data-act="logout">⎋ 登出</button></div></div>
  </div>
  <div id="view"></div>
 </main>
</div>
<div class="toast" id="toast"></div>
<div class="ovl" id="ovl"></div>
<aside class="drw" id="drw" aria-label="device detail">
  <div class="drwh"><span class="mk"><img src="/brand.svg" alt="NemoClaw" width="28" height="28"></span>
    <div><h2 id="drwTitle">EBG19P</h2><div class="ds" id="drwSub"></div></div>
    <span class="drwx" id="drwClose" title="關閉 (Esc)">✕</span></div>
  <div id="drwBody"></div>
</aside>
<script>
const el=id=>document.getElementById(id);
const TABS=[{id:'overview',ni:'◉'},{id:'arch',ni:'◈'},{id:'fleet',ni:'⬡'},{id:'cve',ni:'🛡'},{id:'gov',ni:'⚡'},{id:'timeline',ni:'◷'},{id:'ops',ni:'🎫'},{id:'stack',ni:'▦'},{id:'settings',ni:'⚙'}];
let CFG={theme:localStorage.getItem('nclaw-theme')||'light',refresh:+(localStorage.getItem('nclaw-refresh')||5),
 node:localStorage.getItem('nclaw-node')||'all',density:(function(){var x=localStorage.getItem('nclaw-density');if(x==='compact')return 7;if(x==='comfortable')return 5;var n=parseInt(x,10);return(n>=1&&n<=10)?n:5})(),lang:localStorage.getItem('nclaw-lang')||'zh'};
let timer=null,LAST=null,DRW='ebg',EVF='all',TLF='all',ARCHVIEW=(localStorage.getItem('nclaw-archview')==='explain'?'explain':'detail'),CERTSCOPE='',lastOk=Date.now(),OPEN_EV=new Set(),POLICY_DATA=null,SNAPSEL=new Set(),TABORDER=JSON.parse(localStorage.getItem('nclaw-taborder')||'null'),DRAGTAB=null;const C={};let CV={};
const I18N={
zh:{refresh:'↻ 重新整理',kiosk:'⛶ 全螢幕',logout:'登出',logout_c:'確定要登出嗎?',nav_reset:'還原預設順序',running:'執行中…',live_ok:'即時連線',live_lag:'資料延遲',live_down:'連線中斷 ',live_manual:'手動更新',updated:'更新 ',upd_fail:'更新失敗,重試…',loading:'載入即時狀態…',
t_overview:'總覽',t_fleet:'設備監控',t_cve:'資安 / CVE',t_gov:'治理事件',t_ops:'工單 / 巡檢',t_stack:'系統堆疊',t_timeline:'活動時間軸',t_settings:'設定',
s_overview:'四大元件 · 關鍵指標 · 一頁綜覽',s_fleet:'設備狀態 · 安全偏離 · 待審變更 · 修復場景',s_cve:'設備弱點分級 · SBOM · SAST · 設計符合性',s_gov:'OCSF 事件流 · ALLOWED / DENIED · 趨勢',s_ops:'Jira 人在迴路 · 巡檢歷史 · 快照 · 跨 agent 通道',s_stack:'容器健康 · 服務端點 · 主機服務',s_timeline:'治理 · 工單 · 處置 · 巡檢 · 全棧事件合一',s_settings:'主題 · 語言 · 自動刷新 · 顯示密度 · 節點篩選',
t_arch:'線上架構',s_arch:'即時拓撲 · 資料流 · 兩大治理面',a_tg:'Telegram',a_email:'Email · GreenMail',a_report:'一句話報修 · 僅授權寄件者',a_bridge:'scoped /32 + X-Bridge-Token · 唯一互通面',a_nemo:'NemoClaw · 管理層',a_nemo_d:'生命週期 · 快照 · 復原 · 管理節點 A / B',a_shell:'OpenShell · 強制層',a_shell_d:'OPA(host/path/binary 三層)+ L7 MITM · 所有 egress 必經',a_mon:'監控 / 報修(/monitor · /fix)',a_sec:'資安(/cve · /source)· egress 受治理',a_fleet:'受管設備',a_egress:'受治理 egress',a_egress_d:'Jira :3690 · mail :3993 · 推理',a_legend:'● 在線　● 離線　· 點任一方塊跳對應分頁',a_manages:'治理 / 管理下方整個 agent stack',a_t_mgmt:'管理面',a_t_enf:'強制面 · 所有 egress 必經',a_denydef:'deny-by-default',a_encl_d:'每個 agent 各自沙箱 · 各自 OPA 政策 · 僅能經 openclaw_bridge 互通 · 所有 egress 必經此層',arch_view:'視圖',arch_flow:'精簡',arch_topo:'詳細',arch_events:'重大事件',arch_noevt:'無重大事件 · 全部正常',arch_sankey:'流量圖',sk_title:'治理流量總覽(近 2 小時)',sk_sub:'每一筆網路動作都先經 OpenShell 逐筆審核;下面看「哪種動作、各幾次、放行還是擋下」。',sk_h_src:'來源 · 全部動作',sk_h_gate:'OpenShell 逐筆把關',sk_h_out:'動作類型 · 結果',sk_times:'次',sk_allow:'綠 = 放行',sk_deny:'紅 = 越權擋下',sk_via:'藍 = 全部先過 OpenShell',sk_width:'帶子越粗代表次數越多',sk_allow2:'放行',sk_deny2:'擋下',sk_denied:'越權擋下',sk_n_mail:'郵件 Email',sk_n_bridge:'Agent 互通',sk_n_ai:'AI 推理',arch_explain:'解說',xp_intro:'這個系統怎麼運作 · 一步一步看',x1_t:'使用者提需求',x1_d:'用 Telegram 或 Email 跟系統說「幫我看設備 / 修問題」',x2_t:'Hermes 前台接收',x2_d:'聽懂需求、轉給後台處理,但它本身碰不到任何設備',x3_t:'OpenShell 安全審核',x3_d:'每一個動作都逐筆檢查,沒被授權的一律擋下(預設全擋)',x4_t:'OpenClaw 維運執行',x4_d:'實際去巡檢、修設備,只能做被政策允許的事',x5_t:'結果回報 / 開工單',x5_d:'修好就回報;修不了或需人核准 → 自動開 Jira 工單通知管理者',x_ok:'正常',x_online:'線上',x_offline:'離線',x_guard:'把關中',x_gate_off:'閘道離線',x_blocked:'今天擋下',x_times:'次',x_hosts:'台在線',x_pending:'張待辦工單',x_clear:'無待辦',tl_entry:'入口通道 · Entry',tl_inter:'互通面 · scoped',tl_enf:'強制面 · 所有 egress',tl_egress:'受治理 egress',tl_fleet:'受管設備',governed:'受治理',pol_title:'OpenShell 政策',pol_ro:'唯讀',pol_allowlist:'egress 白名單 · deny-by-default(僅列允許的出站目的地)',pol_fsrw:'可寫路徑',pol_edit:'唯讀檢視。改設定請用 openshell policy / nemoclaw policy-* CLI(認證 + 可稽核 + 可形式化證明)。',pol_more:'其他出站 preset',pol_edit_btn:'⚙ 編輯(prove 把關)',pol_edit_title:'政策編輯',pol_loading:'載入政策 + 形式化證明中…',pol_load_fail:'載入失敗',pol_sb:'沙箱',pol_pick_agent:'選擇 agent(設定該 agent 的 OpenShell 權限)',pol_rules:'egress 規則明細(逐條)',pol_rules_d:'每條 = 一個網路規則(host:port + 可用 binary)。可單獨移除,或在下方新增 endpoint。改動先 dry-run 預覽再確認。',pol_rule_rm:'移除',pol_add_ep:'＋ 新增',pol_pick_agent_d:'每個 agent 各自獨立沙箱政策(deny-by-default)。選了之後,下面的 Presets / 設定 / 原始 YAML 都套用到該 agent。',pol_gaps:'critical/high 缺口(現行)',pol_gate_d:'套用前一律跑 openshell policy prove;只要改動讓缺口數增加就拒絕套用(差異式把關)。',pol_presets:'出站白名單 Presets',pol_presets_d:'每個 preset = 對某服務的「出站允許清單」。🟢 已開放(允許 agent 連線到它);⚪ 未開放(deny-by-default 擋著)。按「開放」=加白名單放行,「收回」=移除擋回。改動會先 dry-run 預覽再確認。',osh_settings:'OpenShell 設定',osh_settings_d:'沙箱層級的 OpenShell 開關(true / false / 預設=unset 繼承全域)。即時生效、可稽核。',osh_unset:'預設',pol_on:'開放',pol_off:'收回',pol_raw:'原始政策 YAML(進階)',pol_prove_btn:'驗證 prove',pol_apply_btn:'套用(prove 通過才送)',pol_revert:'還原編輯',pol_history:'政策版本歷史',pol_confirm_apply:'確定套用此變更?',pol_apply_c:'確定把編輯後的原始政策套用到 live 沙箱?\nprove 通過(未變差)才會真的送出。',
banner_ok:'✓ 全系統正常 · 兩節點各司其職 · 無告警',sec_kpi:'關鍵指標 · 點擊深入',sec_comp:'四大元件',sec_nodes:'兩 OpenClaw 節點 · 職責分工(點看詳情)',
kpi_nodes:'OpenClaw 節點在線',managed_dev:'受管設備',dev_allok:'全 ok',kpi_denied:'越權擋下 DENIED',kpi_cve:'CVE affected',kpi_mttr:'修復 MTTR',kpi_snap:'NemoClaw 快照',kpi_containers:'容器運行',
comp_nemo:'管理層',comp_shell:'強制層',comp_hermes:'對人前台',comp_oc:'IT 設備群',herm_role:'對人前台 Human front desk',herm_about:'使用者唯一的對話入口:接 Telegram / Email 需求,用 OpenAI 相容 API 理解後委派給 OpenClaw 執行。本身不直接碰任何設備——所有動作都要過 OpenShell 治理。',herm_status:'即時狀態',herm_tg:'Telegram 輪詢',herm_mail:'Email 入口',herm_sandbox:'沙箱 / 治理',herm_flow:'在架構中的角色',herm_flow_d:'使用者 → Hermes(前台,聽懂並轉派)→ OpenShell(逐筆審核 · deny-by-default)→ OpenClaw(實際巡檢 / 修復)→ 回報 / 自動開 Jira。Hermes 僅經 scoped /32 + X-Bridge-Token 與 OpenClaw 互通。',nemo_role:'管理層 Management plane',nemo_about:'整個 agent stack 的生命週期管理:建立 / 快照 / 復原沙箱,管理 OpenClaw A、B 與 Hermes。出事可重建回已知良好狀態。',nemo_snaps:'快照 / 還原點',a_total:'合計',nemo_manages:'管理的沙箱',nemo_recovery:'復原能力',nemo_recovery_d:'每個 agent 各自快照鏈;boot-stack 用 snapshot restore --to 重建沙箱(如 openclaw-2 即由 A 的快照建出)。重開機由 cron @reboot 自癒拉起。',osh_role:'強制層 Enforcement plane',osh_about:'所有 agent 的網路 / 檔案動作都先經此逐筆審核:OPA(host/path/binary 三層)+ L7 MITM,deny-by-default,所有 egress 必經。',osh_endpoints:'個端點',osh_enf:'強制機制',osh_enf_d:'政策即 code、可形式化證明(openshell policy prove)。非白名單目的地一律 DENIED;白名單內可見可管。政策可在「治理事件 → ⚙ 編輯」以 prove 把關後修改。',c_lifecycle:'生命週期 / 復原',snap_unit:'快照',c_restore:'最新還原點',c_deny:'越權擋下',c_tg:'Telegram 輪詢',alive:'存活',stopped:'停',online:'在線',offline:'離線',c_nodes_online:'節點在線',unit_host:'台',fleet_unit:'台',c_bridge:'跨 agent 通道',
node_word:'節點',node_net_health:'網路設備健康',node_cve_health:'設備弱點',node_detail:'查看完整詳情 →',dev_ok:'設備 ok',dev_drift:'安全偏離',benign:'良性',pol_ph_host:'host(例 api.example.com)',pol_ph_bin:'binary(選填,逗號分隔)',scanned:'掃',
filter_node:'節點篩選',f_all:'全部',f_a:'運維 A',f_b:'資安 B',
assets_title:'已連線資產',assets_unit:'台',assets_unknown:'未授權',assets_none:'無連線資產',asset_known:'已核准',
tr_title:'LAN 流量(WIRED)',tr_now:'目前',tr_avg:'基線均值',tr_peak:'峰值',h_temp:'溫度',h_ports:'網口',h_health:'即時健康',tr_anom:'流量突增異常',tr_norm:'流量正常 · 在基線範圍內',
drw_managed:'NemoClaw 受管',drw_identity:'設備身分',drw_compliance:'安全合規基準',drw_clean:'與基準一致 · 無偏離',di_model:'型號',di_fw:'韌體',di_mac:'MAC',di_wan:'WAN',di_ssid:'SSID',di_remote:'遠端管理',drw_hint:'點看設備細節 →',
act_title:'快速處置',act_sync:'強制同步',act_harden:'套用安全基準',act_restart:'重啟服務',act_block:'封鎖未授權',audit_title:'處置稽核',audit_none:'尚無處置紀錄',act_done:'處置已送出',act_warn_harden:'將套用安全基準到 EBG19P 實機(關 UPnP/WPS、開 DoS)並重啟防火牆/無線。確定執行?',act_warn_restart:'將重啟 EBG19P 防火牆/無線服務,WiFi 會短暫斷線。確定執行?',act_warn_block:'將封鎖未授權設備的無線連線。確定執行?',nodrift:'無變更 · 與核准基準一致',reg:'安全偏離',pend:'待審變更',nomon:'無監控資料',scen:'修復場景待命',scen_unit:'種',nonode:'此篩選下無節點',
cve_grade:'設備 CVE 分級',aff_title:'Affected 弱點',aff_jira:'已開 Jira 工單',th_cve:'CVE',th_asset:'資產',th_comp:'元件',th_ver:'版本',th_sev:'嚴重度',noaff:'無 affected',src_title:'原始碼 · 設計符合性',src_feed:'即時 CVE 情資',src_adv:'上游 advisory 校正',src_fixed:'已修',src_recon:'校正 backport 假陽性',src_sbom:'SBOM 套件',src_prov:'基準:RT-AX89X 韌體線(非 EBG19P)',src_sast:'SAST 命中',sast_code:'漏洞程式碼',sast_patch:'建議修補(diff)',sast_verified:'patch 驗證',sast_ok:'已驗證:套用後樣式消失',src_design:'設計違反',src_reqs:'設計符合性 · 機器可驗條款',st_violated:'違反',st_compliant:'符合',st_na:'未評估',src_view:'上游原始碼',src_evid:'現況證據',sast_fix:'修補建議',fix_risk:'風險',fix_how:'建議修法',patch_sugg:'逐行建議(需依資料流確認)',th_cwe:'CWE',th_file:'檔案',th_line:'行',btn_rescan:'↻ 重掃 CVE',btn_source:'↻ 原始碼分析',sec_source:'原始碼 / SBOM / SAST · 設計文件符合性',cve_off:'節點 B(資安)離線或尚無 CVE 報告。',
dl_title:'EBG19P 設備日誌',dl_sub:'真機 syslog 集中 · OCSF 分類',dl_total:'行',dl_sec:'安全關注',dl_none:'無安全關注事件(設備日誌正常)',dl_cats:'分類',
ev_title:'即時治理事件流',ev_sub:'OCSF · 濾心跳',e_all:'全部',e_allow:'放行',e_deny:'擋下',ev_none:'無符合事件',ev_hint:'點任一列看完整資訊',ev_action:'動作',ev_process:'發起程式',ev_target:'目標',ev_engine:'判定引擎',ev_sev:'嚴重度',ev_policy:'套用政策',ev_reason:'原因',act_net:'嘗試開啟網路連線',act_proc:'嘗試執行程式',act_file:'嘗試存取檔案',act_other:'受治理動作',deny_nopol:'(無放行政策 → 拒絕)',gov_title:'治理覆蓋',gov_2h:'近2h',gov_denytot:'越權擋下 DENIED(實質)',gov_benign:'推理心跳握手失敗(良性 · 不計)',gov_benign_t:'良性',gov_benign_why:'良性事件:這是 OpenClaw 定期對推理後端 inference.local:443(LLM 大腦)的心跳連線。TLS 握手是被「上游 Azure 限流(429)」中斷,不是被本地政策擋下,也不是外部攻擊或越權 egress——因此不計入「越權擋下」。要消除這類雜訊,可設 NEMOCLAW_AGENT_HEARTBEAT_EVERY=0 關閉心跳。',collecting:'收集中…',trend:'趨勢',tr_actions:'治理動作量',tr_recent:'最近取樣 · 確切時間點',tr_act_u:'動作',tr_deny_u:'擋下',tr_hb_u:'心跳',tr_tg:'Telegram 心跳',tr_samples:'取樣點',accruing:'累積中…',sec_gov_trend:'治理覆蓋 · 趨勢',
jira_title:'Jira 工單',jira_hil:'人在迴路',jira_reset:'重置工單佇列',jira_empty:'佇列空',guard_title:'巡檢歷史',guard_legend:'綠pass · 紅fail · 框主鏈',guard_recent:'最近巡檢',mttr_row:'修復 MTTR',mttr_base:'基準值',sec_snap_bridge:'快照 · 跨 agent 通道',snap_title:'NemoClaw 快照',snap_restore:'還原點',snap_create_btn:'＋ 建立快照',snap_restore_btn:'復原',snap_name_p:'快照名稱(留空自動命名):',snap_per_agent_d:'每個 agent 沙箱各自一份快照鏈;在各區塊按「＋ 建立快照」為該 agent 留還原點。還原(in-place)需走重建流程,不在此即時操作。',snap_del_btn:'刪除快照',snap_del_c1:'確定刪除快照 %s?此操作不可復原。',snap_del_c2:'再次確認:此操作不可復原。請輸入版本「%s」以確認刪除:',snap_del_cancel:'已取消(輸入不符)',snap_del_sel:'刪除選取',snap_del_sel_c:'確定刪除選取的 %s 個快照?此操作不可復原。',snap_del_sel_done:'已刪除 %s 個快照',snap_restore_c:'確定把 my-assistant 沙箱「復原」到 %s?\n這會回滾目前 agent 的工作狀態(具破壞性)。',bridge_title:'跨 agent 通道 · scoped /32',bridge_auth:'授權',bridge_note:'每節點各一條 /32 + X-Bridge-Token,唯一互通面',
set_appearance:'外觀',set_theme:'主題',set_theme_d:'淺色商務 / 純黑深色',th_light:'淺色',th_dark:'深色',set_lang:'語言 Language',set_lang_d:'介面顯示語言',set_density:'顯示密度',set_density_d:'10 級:1 最寬鬆 ↔ 10 最緊湊',acl_section:'存取控制(管理員)',aud_title:'管理稽核(防竄改)',aud_d:'每筆管理動作以 hash 串鏈記錄;改動任一筆都會斷鏈被偵測。',aud_intact:'鏈完整',aud_broken:'鏈遭竄改 斷於',aud_verify:'重新驗證',anom_sec:'資安異常偵測',anom_title:'異常偵測',anom_found:'項異常',anom_clear:'正常',anom_none:'目前無異常',mc_prompt:'偵測到使用預設密碼,請設定新密碼(至少 6 碼):',mc_skip:'未變更;下次登入仍會提醒',acl_accounts:'帳號管理',acl_policy:'Session / 安全政策',acl_you:'你',acl_pw:'改密碼',acl_online:'在線 session',acl_maxs:'每帳號 session 上限',acl_maxs_d:'超過上限自動踢最舊;∞=不限',acl_timeout:'閒置逾時',acl_timeout_d:'閒置超過此時間需重新登入;∞=不限',acl_ipwl:'IP 白名單',acl_ipwl_d:'留空=不限;逗號分隔,支援 CIDR(loopback 一律放行防自鎖)',acl_del_c:'確定刪除此帳號?',acl_pw_p:'輸入新密碼:',den_comfort:'舒適',den_compact:'緊湊',den_loose:'寬鬆',den_tight:'緊湊',apply:'套用',set_data:'資料',set_refresh:'自動刷新',set_refresh_d:'背景輪詢 /api/status 間隔',rf_off:'關',set_defnode:'預設節點篩選',set_defnode_d:'設備監控預設顯示',set_manual:'手動重新整理',set_manual_d:'立即清快取重取',btn_now:'↻ 立即重整',set_about:'關於',ab_fmt:'事件格式',ab_cred:'憑證安全',ab_cred_v:'Token 僅 server 端',ab_nature:'資料性質',ab_nature_v:'唯讀彙整 · 快取 8s',ab_keys:'鍵盤快捷',ab_k_tabs:'切換分頁',ab_k_r:'重整',ab_k_d:'深淺主題',ab_k_f:'全螢幕',
toast_refresh:'已重新整理',toast_cve:'節點 B 已重掃設備 CVE',toast_source:'節點 B 已重跑原始碼分析(SBOM/SAST)',toast_jira:'工單佇列已重置',toast_done:'完成',toast_fail:'動作失敗',role_a:'IT 運維 / 網路管理',role_b:'資安 / 原始碼分析',stk_services:'主機服務',sys_section:'系統資訊 · nemoclaw / openshell',sys_inf:'推理路由',sys_inf_model:'模型',sys_reach:'可達',sys_unreach:'不可達',sys_gw:'OpenShell Gateway',sys_gw_status:'狀態',sys_fwd:'埠轉發(各 agent)',sys_meta:'供應商 / 通道',sys_creds:'憑證供應商',sys_chan:'支援通道',sys_tools:'診斷工具(即時執行)',sys_tools_d:'按下即時跑 nemoclaw/openshell 診斷,結果顯示於抽屜(較重,不進自動輪詢)。',sys_doctor:'健康診斷',sys_logs:'日誌',sys_global:'全域',sys_stale:'檢查過期沙箱',sys_gsettings:'全域設定',sys_recover:'復原',sys_recover_c:'確定要對此 sandbox 執行 recover?會重啟其 gateway 與 dashboard 轉發(短暫中斷、冪等)。',sys_gwhealth:'Gateway 健康',sys_inf_set:'切換推理模型',sys_inf_set_btn:'切換…',sys_inf_prov_p:'OpenShell provider 名稱(例:compatible-endpoint):',sys_inf_model_p:'模型 id(例:Kimi-K2.5):',sys_gc:'GC 預覽',sys_gcrun:'GC 清除',sys_gc_c:'nemoclaw gc 會刪除孤兒 docker 映像(已停用的舊 sandbox image),確定執行?',sys_chan_stop:'停用',sys_chan_start:'啟用',sys_chan_stop_c:'停用此通道?會重建 sandbox(短暫中斷),但保留憑證。',sys_chan_start_c:'重新啟用此通道?會重建 sandbox。',sys_maint:'維護 / 升級(admin)',sys_maint_d:'較重的生命週期動作:備份、升級、重建、診斷包、host 別名、埠轉發。',sys_backup:'全量備份',sys_backup_c:'執行 nemoclaw backup-all 備份所有沙箱狀態?可能要數十秒。',sys_upgrade:'升級過時沙箱',sys_upgrade_c:'對所有「過時且運行中」的沙箱跑 rebuild 升級?較耗時、會短暫中斷。',sys_debug:'診斷包',sys_rebuild:'重建',sys_rebuild_p:'重建會把沙箱升到當前 agent 版(較久、會中斷)。請輸入 sandbox 名稱以確認:',sys_rebuild_mismatch:'名稱不符,已取消',sys_hosts_list:'hosts',sys_hosts_add:'＋別名',sys_hosts_rm:'－別名',sys_hosts_name_p:'host 別名(hostname):',sys_hosts_ip_p:'IP 位址(IPv4):',sys_hosts_rm_c:'移除此 host 別名?',sys_fwd_start:'開埠轉發',sys_fwd_stop:'停埠轉發',sys_fwd_port_p:'本機 port(例:8080 或 0.0.0.0:8080):',sys_fwd_sb_p:'sandbox 名稱(留空=last-used):',sys_fwd_stop_c:'停止此埠轉發?',stk_containers:'容器',stk_running:'運行',stk_stopped:'已停止',stk_svc_gateway:'OpenShell 閘道 :18080',stk_svc_hermes:'Hermes API :8642',stk_svc_tg:'Telegram 輪詢',stk_healthy:'全部容器運行中',stk_none:'無容器資料',stk_grp_core:'核心治理',stk_grp_agent:'Agent 節點',stk_grp_infra:'周邊服務',stk_uptime:'狀態',ctr_detail:'容器詳情',ctr_name:'名稱',ctr_state:'狀態',ctr_status:'完整狀態',ctr_group:'分組',ctr_image:'映像',ctr_ports:'埠',ctr_uptime:'運行時間',svc_detail:'服務詳情',svc_endpoint:'端點',svc_about:'說明',svc_gateway_d:'OpenShell 強制層閘道:所有 sandbox 經此抓政策、所有受治理 egress 必經(deny-by-default + L7 MITM)。',svc_hermes_d:'Hermes 對人前台的 OpenAI 相容 API:接 Telegram / Email 需求,經 scoped bridge 委派 OpenClaw。',svc_tg_d:'Hermes 對 Telegram Bot API 的輪詢(getUpdates);近期有次數代表存活。',tl_all:'全部',tl_gov:'治理',tl_jira:'工單',tl_audit:'處置',tl_guard:'巡檢',tl_dev:'設備日誌',la_title:'syslog 智慧分析',la_sub:'異常 · 根因收斂 · 跨訊號融合',la_root:'重複事件根因',la_clean:'無異常發現',tl_none:'無活動事件',jira_id:'工單',jira_pri:'優先',jira_asset:'資產',jira_sum:'摘要',jira_tickets:'工單明細',kpi_cert:'憑證/弱加密告警',cert_title:'憑證 / 弱加密與協定',cert_sub:'主動提醒 · 不受信任 / 弱演算法 / 將過期 / 弱協定',cert_high:'高風險',cert_med:'中風險',cert_service:'服務',cert_issue:'問題',cert_detail:'說明',cert_clean:'無憑證/加密問題',ce_untrusted:'不受信任',ce_weakalg:'弱演算法',ce_expired:'已過期',ce_expiring:'即將過期',ce_weakproto:'弱協定',ce_weakcipher:'弱加密套件',ce_weakssh:'弱 SSH 演算法',set_mgmt_scan:'管理 · 掃描排程',set_mgmt_thresh:'管理 · 告警門檻',set_mgmt_notify:'管理 · 通知 / 開單',set_cve_iv:'CVE 掃描間隔',set_cve_iv_d:'資安節點 B 定期掃設備 CVE 的頻率',set_cert_iv:'憑證掃描間隔',set_cert_iv_d:'運維節點 A 定期盤點憑證/弱加密的頻率',set_warn_days:'憑證過期提前提醒',set_warn_days_d:'剩餘天數低於此值就提醒(將過期)',set_rsa_min:'RSA 金鑰最低位元',set_rsa_min_d:'低於此值判定弱演算法',set_cert_thr:'憑證 / 加密門檻',set_dev_thr:'設備健康告警門檻(跟隨上方 scope:全域或各設備)',set_cpu_hi:'CPU 高負載門檻',set_cpu_hi_d:'設備 CPU 超過此值即告警(≥95% 高risk)',set_ram_hi:'記憶體高用量門檻',set_ram_hi_d:'設備 RAM 超過此值即告警',set_temp_hi:'溫度告警門檻',set_temp_hi_d:'設備溫度超過此值即告警',set_sig:'簽章演算法門檻',set_sig_d:'低於此強度的簽章判為弱(建議 SHA-256)',set_ec_min:'ECDSA 曲線最低強度',set_ec_min_d:'EC 金鑰曲線低於此值判定弱演算法(P-256<P-384<P-521)',set_cipher:'加密套件政策',set_cipher_d:'要標出哪些弱加密套件(寬鬆→嚴格)',ci_lax:'寬鬆',ci_std:'標準',ci_strict:'嚴格',ci_custom:'自訂',cp_global:'全域預設',cp_inherit:'繼承',cp_custom_fams:'自訂:要標為弱的套件',cp_custom_d:'點亮(紅)= 會被標為弱',cur_state:'目前狀態 · openssl 解析',set_escalate:'自動開 Jira 工單',set_escalate_d:'掃到高風險是否自動開單(關=只在儀表板提醒)',set_quiet:'靜音時段',set_quiet_d:'選定的星期 + 時段內不自動開單',q_from:'從',q_to:'到',d_mon:'一',d_tue:'二',d_wed:'三',d_thu:'四',d_fri:'五',d_sat:'六',d_sun:'日',set_channels:'通知管道',set_channels_d:'告警/工單去向(Jira 一律保留)',on_:'開',off_:'關',ch_base:'Jira+儀表板',ch_email:'+Email',ch_tg:'+Telegram',ch_dash:'僅儀表板',set_mgmt_rec:'管理 · 通知對象',rec_hint:'告警/工單會通知這些管理者',rec_none:'尚無通知對象',rec_name:'姓名',rec_tg:'Telegram chat id',rec_email:'Email',rec_add:'＋ 新增',rec_del:'刪除',rec_need_name:'請先填姓名',ch_all:'+Email+TG',rec_test:'測試',rec_del_confirm:'確定刪除此通知對象?'},
en:{refresh:'↻ Refresh',kiosk:'⛶ Fullscreen',logout:'Log out',logout_c:'Log out?',nav_reset:'Reset order',running:'Running…',live_ok:'Live',live_lag:'Data delayed',live_down:'Disconnected ',live_manual:'Manual',updated:'Updated ',upd_fail:'Update failed, retrying…',loading:'Loading live status…',
t_overview:'Overview',t_fleet:'Fleet Monitor',t_cve:'Security / CVE',t_gov:'Governance',t_ops:'Escalation / Guard',t_stack:'Stack',t_timeline:'Activity Timeline',t_settings:'Settings',
s_overview:'Four components · key metrics · one-page summary',s_fleet:'Device status · regressions · pending drift · remediation',s_cve:'Fleet CVE triage · SBOM · SAST · design compliance',s_gov:'OCSF event stream · ALLOWED / DENIED · trend',s_ops:'Jira human-in-the-loop · guard history · snapshots · cross-agent',s_stack:'Container health · service endpoints · host services',s_timeline:'Governance · tickets · actions · guard · unified stack feed',s_settings:'Theme · language · auto refresh · density · node filter',
t_arch:'Live Architecture',s_arch:'Live topology · data flow · two governance planes',a_tg:'Telegram',a_email:'Email · GreenMail',a_report:'one-line ticket · authorized senders only',a_bridge:'scoped /32 + X-Bridge-Token · sole interconnect',a_nemo:'NemoClaw · Management plane',a_nemo_d:'lifecycle · snapshots · recovery · manages node A / B',a_shell:'OpenShell · Enforcement plane',a_shell_d:'OPA (host/path/binary) + L7 MITM · all egress crosses here',a_mon:'monitor / fix (/monitor · /fix)',a_sec:'security (/cve · /source) · governed egress',a_fleet:'Managed fleet',a_egress:'Governed egress',a_egress_d:'Jira :3690 · mail :3993 · inference',a_legend:'● online　● offline　· click any box → its tab',a_manages:'governs / manages the whole agent stack below',a_t_mgmt:'MANAGEMENT PLANE',a_t_enf:'ENFORCEMENT PLANE · all egress',a_denydef:'deny-by-default',a_encl_d:'each agent its own sandbox · own OPA policy · interconnect only via openclaw_bridge · all egress crosses here',arch_view:'View',arch_flow:'Simple',arch_topo:'Detailed',arch_events:'Major events',arch_noevt:'No major events · all clear',arch_sankey:'Flow map',sk_title:'Governance flow (last 2h)',sk_sub:'Every network action is checked one-by-one by OpenShell. Below: which action, how many times, allowed or denied.',sk_h_src:'Source · all actions',sk_h_gate:'OpenShell checks each',sk_h_out:'Action type · result',sk_times:'×',sk_allow:'Green = allowed',sk_deny:'Red = denied',sk_via:'Blue = all via OpenShell',sk_width:'thicker = more times',sk_allow2:'allowed',sk_deny2:'denied',sk_denied:'Denied',sk_n_mail:'Email',sk_n_bridge:'Agent bridge',sk_n_ai:'AI inference',arch_explain:'Guide',xp_intro:'How this system works · step by step',x1_t:'User makes a request',x1_d:'Ask via Telegram or Email: check or fix my device',x2_t:'Hermes front desk',x2_d:'Understands the request and hands it to the back end — but cannot touch any device itself',x3_t:'OpenShell security check',x3_d:'Every action is checked one-by-one; anything not authorized is blocked (deny-by-default)',x4_t:'OpenClaw operations',x4_d:'Actually inspects and fixes devices — only what policy allows',x5_t:'Report back / open ticket',x5_d:'Reports when done; if it cannot fix or needs approval, auto-opens a Jira ticket to admins',x_ok:'OK',x_online:'online',x_offline:'offline',x_guard:'guarding',x_gate_off:'gateway offline',x_blocked:'blocked today',x_times:'',x_hosts:'hosts up',x_pending:'open tickets',x_clear:'all clear',tl_entry:'Entry channels',tl_inter:'Interconnect · scoped',tl_enf:'Enforcement · all egress',tl_egress:'Governed egress',tl_fleet:'Fleet',governed:'governed',pol_title:'OpenShell policy',pol_ro:'read-only',pol_allowlist:'egress allowlist · deny-by-default (only listed destinations permitted)',pol_fsrw:'writable paths',pol_edit:'Read-only view. Edit via openshell policy / nemoclaw policy-* CLI (authenticated · auditable · formally provable).',pol_more:'other egress presets',pol_edit_btn:'⚙ Edit (prove-gated)',pol_edit_title:'Policy editor',pol_loading:'Loading policy + formal proof…',pol_load_fail:'Load failed',pol_sb:'Sandbox',pol_pick_agent:'Select agent (edit its OpenShell policy)',pol_rules:'Egress rules (per-rule)',pol_rules_d:'Each = one network rule (host:port + allowed binaries). Remove individually, or add an endpoint below. Changes are dry-run previewed, then confirmed.',pol_rule_rm:'Remove',pol_add_ep:'＋ Add',pol_pick_agent_d:'Each agent has its own sandbox policy (deny-by-default). Presets / settings / raw YAML below apply to the selected agent.',pol_gaps:'critical/high gaps (current)',pol_gate_d:'Every apply runs openshell policy prove; a change is rejected if it raises the gap count (differential gate).',pol_presets:'Egress allowlist presets',pol_presets_d:'Each preset = an egress allow-list for a service. 🟢 open (agent may connect); ⚪ closed (deny-by-default blocks it). "Open" allows, "Revoke" blocks. Changes are dry-run previewed, then confirmed.',osh_settings:'OpenShell settings',osh_settings_d:'Sandbox-level OpenShell toggles (true / false / default=unset inherits global). Applied live, auditable.',osh_unset:'default',pol_on:'Open',pol_off:'Revoke',pol_raw:'Raw policy YAML (advanced)',pol_prove_btn:'Prove',pol_apply_btn:'Apply (only if prove passes)',pol_revert:'Revert edits',pol_history:'Policy version history',pol_confirm_apply:'Apply this change?',pol_apply_c:'Apply the edited raw policy to the live sandbox?\nSent only if prove passes (not worse).',
banner_ok:'✓ All systems normal · both nodes on duty · no alerts',sec_kpi:'Key metrics · click to drill in',sec_comp:'Four components',sec_nodes:'Two OpenClaw nodes · roles (click for detail)',
kpi_nodes:'OpenClaw nodes online',managed_dev:'Managed devices',dev_allok:'all ok',kpi_denied:'Blocked DENIED',kpi_cve:'CVE affected',kpi_mttr:'Remediation MTTR',kpi_snap:'NemoClaw snapshots',kpi_containers:'Containers up',
comp_nemo:'Control plane',comp_shell:'Enforcement',comp_hermes:'Human frontend',comp_oc:'IT fleet',herm_role:'Human front desk',herm_about:'The single conversational entry point for users: takes Telegram / Email requests, understands them via an OpenAI-compatible API, and delegates to OpenClaw. It never touches devices directly — every action goes through OpenShell governance.',herm_status:'Live status',herm_tg:'Telegram polling',herm_mail:'Email entry',herm_sandbox:'Sandbox / governance',herm_flow:'Role in the architecture',herm_flow_d:'User → Hermes (front desk, understands & delegates) → OpenShell (per-action deny-by-default review) → OpenClaw (actual inspect / fix) → report / auto Jira. Hermes interconnects with OpenClaw only via a scoped /32 + X-Bridge-Token.',nemo_role:'Management plane',nemo_about:'Lifecycle management for the whole agent stack: create / snapshot / restore sandboxes, manage OpenClaw A, B and Hermes. Rebuild to a known-good state when things break.',nemo_snaps:'Snapshots / restore points',a_total:'total',nemo_manages:'Managed sandboxes',nemo_recovery:'Recovery',nemo_recovery_d:'Each agent has its own snapshot chain; boot-stack uses snapshot restore --to to rebuild sandboxes (e.g. openclaw-2 built from an A snapshot). Boot self-heal via cron @reboot.',osh_role:'Enforcement plane',osh_about:'Every agent network / file action is reviewed here one-by-one: OPA (host/path/binary) + L7 MITM, deny-by-default, all egress crosses here.',osh_endpoints:'endpoints',osh_enf:'Enforcement',osh_enf_d:'Policy as code, formally provable (openshell policy prove). Non-allowlisted destinations are DENIED; allowlisted are visible & managed. Edit policy via Governance → ⚙ Edit, prove-gated.',c_lifecycle:'Lifecycle / recovery',snap_unit:'snapshots',c_restore:'Latest restore point',c_deny:'Blocked',c_tg:'Telegram polling',alive:'alive',stopped:'stopped',online:'online',offline:'offline',c_nodes_online:'Nodes online',unit_host:'',fleet_unit:'hosts',c_bridge:'Cross-agent channel',
node_word:'Node',node_net_health:'Network device health',node_cve_health:'Fleet vulnerabilities',node_detail:'View full detail →',dev_ok:'devices ok',dev_drift:'security drift(s)',benign:'benign',pol_ph_host:'host (e.g. api.example.com)',pol_ph_bin:'binary (optional, comma-separated)',scanned:'scanned',
filter_node:'Node filter',f_all:'All',f_a:'Ops A',f_b:'Sec B',
assets_title:'Connected assets',assets_unit:'',assets_unknown:'unauthorized',assets_none:'no connected assets',asset_known:'approved',
tr_title:'LAN traffic (WIRED)',tr_now:'now',tr_avg:'baseline avg',tr_peak:'peak',h_temp:'Temp',h_ports:'Ports',h_health:'Live health',tr_anom:'traffic spike anomaly',tr_norm:'normal · within baseline',
drw_managed:'NemoClaw-managed',drw_identity:'Identity',drw_compliance:'Security baseline',drw_clean:'matches baseline · no regression',di_model:'Model',di_fw:'Firmware',di_mac:'MAC',di_wan:'WAN',di_ssid:'SSID',di_remote:'Remote mgmt',drw_hint:'click for device detail →',
act_title:'Quick actions',act_sync:'Force sync',act_harden:'Apply baseline',act_restart:'Restart services',act_block:'Block unauthorized',audit_title:'Action audit',audit_none:'No actions yet',act_done:'Action submitted',act_warn_harden:'Apply security baseline to the physical EBG19P (UPnP/WPS off, DoS on) and restart firewall/wireless. Proceed?',act_warn_restart:'Restart EBG19P firewall/wireless services; WiFi will briefly drop. Proceed?',act_warn_block:'Block the unauthorized device wireless access. Proceed?',nodrift:'No drift · matches approved baseline',reg:'Regressions',pend:'Pending review',nomon:'No monitoring data',scen:'Remediation scenarios ready',scen_unit:'',nonode:'No node under this filter',
cve_grade:'Fleet CVE triage',aff_title:'Affected vulns',aff_jira:'Jira escalation opened',th_cve:'CVE',th_asset:'Asset',th_comp:'Component',th_ver:'Version',th_sev:'Severity',noaff:'No affected',src_title:'Source · design compliance',src_feed:'Live CVE feed',src_adv:'Upstream advisory reconcile',src_fixed:'fixed',src_recon:'backport false-positives corrected',src_sbom:'SBOM packages',src_prov:'baseline: RT-AX89X firmware line (not EBG19P)',src_sast:'SAST findings',sast_code:'Vulnerable code',sast_patch:'Suggested patch (diff)',sast_verified:'Patch verified',sast_ok:'verified',src_design:'Design violations',src_reqs:'Design conformance · machine-verifiable',st_violated:'Violated',st_compliant:'OK',st_na:'N/A',src_view:'Upstream source',src_evid:'Evidence',sast_fix:'Remediation',fix_risk:'Risk',fix_how:'Fix',patch_sugg:'line suggestion (verify data-flow)',th_cwe:'CWE',th_file:'File',th_line:'Line',btn_rescan:'↻ Rescan CVE',btn_source:'↻ Source analysis',sec_source:'Source / SBOM / SAST · design doc compliance',cve_off:'Node B (Security) offline or no CVE report yet.',
dl_title:'EBG19P device log',dl_sub:'live syslog aggregation · OCSF classified',dl_total:'lines',dl_sec:'security-relevant',dl_none:'no security-relevant events (device log clean)',dl_cats:'categories',
ev_title:'Live governance events',ev_sub:'OCSF · heartbeat filtered',e_all:'All',e_allow:'Allowed',e_deny:'Denied',ev_none:'No matching events',ev_hint:'click any row for full detail',ev_action:'Action',ev_process:'Process',ev_target:'Target',ev_engine:'Engine',ev_sev:'Severity',ev_policy:'Policy',ev_reason:'Reason',act_net:'attempted network connection',act_proc:'attempted to execute',act_file:'attempted file access',act_other:'governed action',deny_nopol:'(no allow policy → denied)',gov_title:'Governance coverage',gov_2h:'last 2h',gov_denytot:'Blocked DENIED (real)',gov_benign:'inference heartbeat handshake (benign · excluded)',gov_benign_t:'benign',gov_benign_why:'Benign: OpenClaw\'s periodic heartbeat to the inference backend inference.local:443 (the LLM). The TLS handshake is cut by the upstream (Azure rate-limit 429), not blocked by local policy, and is neither an attack nor unauthorized egress — so it is excluded from the blocked-DENIED count. Set NEMOCLAW_AGENT_HEARTBEAT_EVERY=0 to silence it.',collecting:'Collecting…',trend:'Trend',tr_actions:'Governance actions',tr_recent:'Recent samples · timestamps',tr_act_u:'actions',tr_deny_u:'denied',tr_hb_u:'beats',tr_tg:'Telegram heartbeat',tr_samples:'Samples',accruing:'Accruing…',sec_gov_trend:'Governance coverage · trend',
jira_title:'Jira escalation',jira_hil:'human-in-the-loop',jira_reset:'Reset ticket queue',jira_empty:'Queue empty',guard_title:'Guard history',guard_legend:'green pass · red fail · boxed = main chain',guard_recent:'Latest guard',mttr_row:'Remediation MTTR',mttr_base:'baseline',sec_snap_bridge:'Snapshots · cross-agent channel',snap_title:'NemoClaw snapshots',snap_restore:'restore points',snap_create_btn:'＋ Snapshot',snap_restore_btn:'Restore',snap_name_p:'Snapshot name (blank = auto):',snap_per_agent_d:'Each agent sandbox keeps its own snapshot chain; use ＋ Snapshot in each block to add a restore point. In-place restore needs the rebuild flow, not a live action here.',snap_del_btn:'Delete snapshot',snap_del_c1:'Delete snapshot %s? This cannot be undone.',snap_del_c2:'Confirm again: this cannot be undone. Type the version "%s" to delete:',snap_del_cancel:'Cancelled (input mismatch)',snap_del_sel:'Delete selected',snap_del_sel_c:'Delete %s selected snapshots? This cannot be undone.',snap_del_sel_done:'Deleted %s snapshots',snap_restore_c:'Restore the my-assistant sandbox to %s?\nThis rolls back the current agent working state (destructive).',bridge_title:'Cross-agent channel · scoped /32',bridge_auth:'authorized',bridge_note:'One /32 per node + X-Bridge-Token — the sole interconnect',
set_appearance:'Appearance',set_theme:'Theme',set_theme_d:'Light business / true black',th_light:'Light',th_dark:'Dark',set_lang:'Language',set_lang_d:'Interface language',set_density:'Density',set_density_d:'10 levels: 1 spacious ↔ 10 dense',acl_section:'Access control (admin)',aud_title:'Admin audit (tamper-evident)',aud_d:'Every admin action is hash-chained; altering any entry breaks the chain and is detected.',aud_intact:'chain intact',aud_broken:'chain tampered at',aud_verify:'Re-verify',anom_sec:'Security anomaly detection',anom_title:'Anomalies',anom_found:'found',anom_clear:'clear',anom_none:'No anomalies',mc_prompt:'Default password detected. Set a new password (min 6 chars):',mc_skip:'Not changed; you will be reminded next login',acl_accounts:'Accounts',acl_policy:'Session / security policy',acl_you:'you',acl_pw:'Reset pw',acl_online:'online sessions',acl_maxs:'Max sessions / account',acl_maxs_d:'Oldest evicted when exceeded; ∞=unlimited',acl_timeout:'Idle timeout',acl_timeout_d:'Re-login required after idle; ∞=never',acl_ipwl:'IP whitelist',acl_ipwl_d:'Empty=any; comma-separated, CIDR ok (loopback always allowed)',acl_del_c:'Delete this account?',acl_pw_p:'New password:',den_comfort:'Comfortable',den_compact:'Compact',den_loose:'Spacious',den_tight:'Dense',apply:'Apply',set_data:'Data',set_refresh:'Auto refresh',set_refresh_d:'Background poll /api/status interval',rf_off:'Off',set_defnode:'Default node filter',set_defnode_d:'Default fleet view',set_manual:'Manual refresh',set_manual_d:'Clear cache & refetch now',btn_now:'↻ Refresh now',set_about:'About',ab_fmt:'Event format',ab_cred:'Credential safety',ab_cred_v:'Token server-side only',ab_nature:'Data nature',ab_nature_v:'Read-only aggregate · 8s cache',ab_keys:'Keyboard shortcuts',ab_k_tabs:'switch tabs',ab_k_r:'refresh',ab_k_d:'theme',ab_k_f:'fullscreen',
toast_refresh:'Refreshed',toast_cve:'Node B rescanned fleet CVE',toast_source:'Node B re-ran source analysis (SBOM/SAST)',toast_jira:'Ticket queue reset',toast_done:'Done',toast_fail:'Action failed',role_a:'IT Ops / Network Mgmt',role_b:'Security / Source Analysis',stk_services:'Host services',sys_section:'System info · nemoclaw / openshell',sys_inf:'Inference route',sys_inf_model:'Model',sys_reach:'reachable',sys_unreach:'unreachable',sys_gw:'OpenShell Gateway',sys_gw_status:'Status',sys_fwd:'Port forwards (per agent)',sys_meta:'Providers / channels',sys_creds:'Credential providers',sys_chan:'Channels',sys_tools:'Diagnostics (on-demand)',sys_tools_d:'Run nemoclaw/openshell diagnostics live; results show in the drawer (heavier, not in the poll).',sys_doctor:'Doctor',sys_logs:'Logs',sys_global:'Global',sys_stale:'Check stale sandboxes',sys_gsettings:'Global settings',sys_recover:'Recover',sys_recover_c:'Run recover on this sandbox? Restarts its gateway + dashboard forward (brief disruption, idempotent).',sys_gwhealth:'Gateway health',sys_inf_set:'Switch inference model',sys_inf_set_btn:'Switch…',sys_inf_prov_p:'OpenShell provider name (e.g. compatible-endpoint):',sys_inf_model_p:'Model id (e.g. Kimi-K2.5):',sys_gc:'GC preview',sys_gcrun:'GC clean',sys_gc_c:'nemoclaw gc removes orphaned docker images (old disabled sandbox images). Proceed?',sys_chan_stop:'Stop',sys_chan_start:'Start',sys_chan_stop_c:'Disable this channel? Rebuilds the sandbox (brief disruption) but keeps credentials.',sys_chan_start_c:'Re-enable this channel? Rebuilds the sandbox.',sys_maint:'Maintenance / upgrade (admin)',sys_maint_d:'Heavier lifecycle actions: backup, upgrade, rebuild, debug bundle, host aliases, port forwards.',sys_backup:'Backup all',sys_backup_c:'Run nemoclaw backup-all to back up all sandbox state? May take tens of seconds.',sys_upgrade:'Upgrade stale',sys_upgrade_c:'Rebuild all running stale sandboxes to upgrade them? Slower, brief disruption.',sys_debug:'Debug bundle',sys_rebuild:'Rebuild',sys_rebuild_p:'Rebuild upgrades the sandbox to the current agent version (slow, disruptive). Type the sandbox name to confirm:',sys_rebuild_mismatch:'Name mismatch — cancelled',sys_hosts_list:'hosts',sys_hosts_add:'＋alias',sys_hosts_rm:'－alias',sys_hosts_name_p:'host alias (hostname):',sys_hosts_ip_p:'IP address (IPv4):',sys_hosts_rm_c:'Remove this host alias?',sys_fwd_start:'Start forward',sys_fwd_stop:'Stop forward',sys_fwd_port_p:'Local port (e.g. 8080 or 0.0.0.0:8080):',sys_fwd_sb_p:'Sandbox name (blank = last-used):',sys_fwd_stop_c:'Stop this port forward?',stk_containers:'Containers',stk_running:'up',stk_stopped:'stopped',stk_svc_gateway:'OpenShell gateway :18080',stk_svc_hermes:'Hermes API :8642',stk_svc_tg:'Telegram polling',stk_healthy:'All containers running',stk_none:'No container data',stk_grp_core:'Core governance',stk_grp_agent:'Agent nodes',stk_grp_infra:'Supporting services',stk_uptime:'status',ctr_detail:'Container detail',ctr_name:'Name',ctr_state:'State',ctr_status:'Status',ctr_group:'Group',ctr_image:'Image',ctr_ports:'Ports',ctr_uptime:'Uptime',svc_detail:'Service detail',svc_endpoint:'Endpoint',svc_about:'About',svc_gateway_d:'OpenShell enforcement gateway: every sandbox fetches policy here and all governed egress crosses it (deny-by-default + L7 MITM).',svc_hermes_d:'Hermes human-facing OpenAI-compatible API: takes Telegram/Email requests and delegates to OpenClaw via the scoped bridge.',svc_tg_d:'Hermes polling the Telegram Bot API (getUpdates); a recent count means it is alive.',tl_all:'All',tl_gov:'Governance',tl_jira:'Ticket',tl_audit:'Action',tl_guard:'Guard',tl_dev:'Device log',la_title:'Syslog analysis',la_sub:'anomaly · root-cause · cross-signal fusion',la_root:'Repeated-event root causes',la_clean:'No anomalies',tl_none:'No activity events',jira_id:'Ticket',jira_pri:'Priority',jira_asset:'Asset',jira_sum:'Summary',jira_tickets:'Escalation tickets',kpi_cert:'Cert / weak-crypto alerts',cert_title:'Certificates / weak crypto & protocols',cert_sub:'proactive · untrusted / weak alg / expiring / weak protocol',cert_high:'high',cert_med:'medium',cert_service:'Service',cert_issue:'Issue',cert_detail:'Detail',cert_clean:'No cert/crypto issues',ce_untrusted:'Untrusted',ce_weakalg:'Weak algorithm',ce_expired:'Expired',ce_expiring:'Expiring',ce_weakproto:'Weak protocol',ce_weakcipher:'Weak cipher',ce_weakssh:'Weak SSH',set_mgmt_scan:'Mgmt · Scan schedule',set_mgmt_thresh:'Mgmt · Alert thresholds',set_mgmt_notify:'Mgmt · Notify / escalation',set_cve_iv:'CVE scan interval',set_cve_iv_d:'How often Sec node B scans fleet CVEs',set_cert_iv:'Cert scan interval',set_cert_iv_d:'How often Ops node A audits certs / weak crypto',set_warn_days:'Cert expiry lead time',set_warn_days_d:'Warn when days-left drops below this',set_rsa_min:'Min RSA key bits',set_rsa_min_d:'Below this = weak algorithm',set_cert_thr:'Cert / crypto thresholds',set_dev_thr:'Device health alert thresholds (follows scope above: global or per-device)',set_cpu_hi:'CPU high-load threshold',set_cpu_hi_d:'Alert when device CPU exceeds this (≥95% = high)',set_ram_hi:'RAM high-usage threshold',set_ram_hi_d:'Alert when device RAM exceeds this',set_temp_hi:'Temperature threshold',set_temp_hi_d:'Alert when device temperature exceeds this',set_sig:'Signature algorithm',set_sig_d:'Signatures weaker than this = weak (SHA-256 recommended)',set_ec_min:'Min ECDSA curve',set_ec_min_d:'EC keys below this curve = weak algorithm (P-256<P-384<P-521)',set_cipher:'Cipher policy',set_cipher_d:'Which weak ciphers to flag (lax→strict)',ci_lax:'Lax',ci_std:'Standard',ci_strict:'Strict',ci_custom:'Custom',cp_global:'Global',cp_inherit:'inherit',cp_custom_fams:'Custom: ciphers to flag as weak',cp_custom_d:'highlighted (red) = flagged weak',cur_state:'Current state · openssl-parsed',set_escalate:'Auto-open Jira',set_escalate_d:'Auto-ticket high-risk findings (off = dashboard only)',set_quiet:'Quiet hours',set_quiet_d:'No auto-tickets on selected days + hours',q_from:'From',q_to:'to',d_mon:'Mon',d_tue:'Tue',d_wed:'Wed',d_thu:'Thu',d_fri:'Fri',d_sat:'Sat',d_sun:'Sun',set_channels:'Notify channels',set_channels_d:'Where alerts/escalations go (Jira always kept)',on_:'On',off_:'Off',ch_base:'Jira+board',ch_email:'+Email',ch_tg:'+Telegram',ch_dash:'Board only',set_mgmt_rec:'Mgmt · Recipients',rec_hint:'These admins get alert/ticket notifications',rec_none:'No recipients yet',rec_name:'Name',rec_tg:'Telegram chat id',rec_email:'Email',rec_add:'＋ Add',rec_del:'Delete',rec_need_name:'Name required',ch_all:'+Email+TG',rec_test:'Test',rec_del_confirm:'Remove this recipient?'}};
function t(k){var o=I18N[CFG.lang]||I18N.zh;return (k in o)?o[k]:k}
function L(o,f){if(!o)return '';return (CFG.lang==='en'&&o[f+'_en'])?o[f+'_en']:(o[f]||'')}  // 後端計算字串:英文模式優先用 _en 版
function roleT(r){if(!r)return '—';if(r.indexOf('運維')>=0||r.indexOf('網路')>=0||/ops|network/i.test(r))return t('role_a');if(r.indexOf('資安')>=0||r.indexOf('原始')>=0||/sec|source/i.test(r))return t('role_b');return r}
function loadColors(){const s=getComputedStyle(document.documentElement);
 const dk=document.documentElement.getAttribute('data-theme')==='dark';
 const def=dk?{danger:'#ff5a66',warn:'#e0a030',ok:'#2ecc8f',accent:'#4d8dff',purple:'#a18aff',card2:'#202024',tx:'#f2f2f4',tx2:'#a0a3ab'}
            :{danger:'#d11a2a',warn:'#946200',ok:'#0a875a',accent:'#0066ff',purple:'#6e56cf',card2:'#f3f4f7',tx:'#111114',tx2:'#5f636b'};
 const m={danger:'--danger',warn:'--warn',ok:'--ok',accent:'--accent',purple:'--purple',card2:'--card2',tx:'--tx',tx2:'--tx2'};
 CV=Object.assign({},def);for(const k in m){const v=s.getPropertyValue(m[k]).trim();if(v)CV[k]=v}}
function put(id,html){const e=el(id);if(e&&C[id]!==html){e.innerHTML=html;C[id]=html}}
const pill=(ok,txt)=>`<span class="pill ${ok?'ok':'bad'}">${txt}</span>`;
const sdot=s=>{if(s==='offline')return '<span class="dot" style="background:#8b909a"></span>';const c=(s&&(''+s).includes('ALERT'))?'r':(s==='ok'||s===true)?'g':'a';return `<span class="dot ${c}"></span>`};
function alertLbl(s){const m=(''+s).match(/ALERT\((\d+)/);if(!m)return s;return 'ALERT('+m[1]+' '+t('dev_drift')+')'}  // 把後端「N 安全偏離」轉雙語
const sevc=s=>{s=(''+s).toLowerCase();return s.includes('crit')||s.includes('high')?'high':s.includes('med')?'med':''};
function toast(m){const t=el('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove('show'),2200)}
function spark(arr,col){if(!arr||arr.length<2)return '<span class="mut" style="font-size:11px">'+t('accruing')+'</span>';const w=120,h=30,mx=Math.max(...arr),mn=Math.min(...arr),rg=(mx-mn)||1;
 const pts=arr.map((v,i)=>[i/(arr.length-1)*w,h-((v-mn)/rg)*h]);
 const ln=pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
 const ar=`0,${h} `+ln+` ${w},${h}`;const lp=pts[pts.length-1];
 return `<svg width=${w} height=${h} style="vertical-align:middle"><polygon points="${ar}" fill="${col}" opacity=".12"/><polyline points="${ln}" fill=none stroke="${col}" stroke-width=2 stroke-linejoin=round stroke-linecap=round/><circle cx="${lp[0].toFixed(1)}" cy="${lp[1].toFixed(1)}" r=2.4 fill="${col}"/></svg>`}
function tser(label,arr,ts,col){const n=arr.length;
 const head=`<div class="tserh"><span><i style="background:${col}"></i>${label}</span><b>${n?arr[n-1]:0}</b></div>`;
 if(n<2)return `<div class="tserc">${head}<div class="mut" style="font-size:12px">${t('accruing')}</div></div>`;
 const W=600,Hh=92,padL=42,padR=8,padT=8,padB=18,cw=W-padL-padR,ch=Hh-padT-padB;
 const mx=Math.max(...arr,0),mn=0,rg=(mx-mn)||1;   // 基線固定為 0(縱軸從 0 起,小幅資料不被放大失真)
 const X=i=>padL+(i/(n-1))*cw,Y=v=>padT+ch-((v-mn)/rg)*ch;
 const poly=`<polyline points="${arr.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ')}" fill="none" stroke="${col}" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>`;
 const yax=[mx,(mx+mn)/2,mn].map(v=>{const yy=Y(v);return `<line x1="${padL}" y1="${yy.toFixed(1)}" x2="${W-padR}" y2="${yy.toFixed(1)}" stroke="var(--line)" stroke-width="1" opacity=".4"/><text x="${padL-5}" y="${(yy+3).toFixed(1)}" text-anchor="end" class="tcx">${Math.round(v)}</text>`;}).join('');
 let xax='';const tk=Math.min(5,n);for(let k=0;k<tk;k++){const i=Math.round(k/(tk-1)*(n-1)),x=X(i);xax+=`<text x="${x.toFixed(1)}" y="${Hh-5}" text-anchor="${k===0?'start':k===tk-1?'end':'middle'}" class="tcx">${ts[i]||''}</text>`;}
 const dat=encodeURIComponent(JSON.stringify({ts:ts,v:arr,n:n,W:W,padL:padL,cw:cw,label:label}));
 return `<div class="tserc">${head}<div class="tchart" data-tc="${dat}"><svg viewBox="0 0 ${W} ${Hh}" width="100%" style="height:auto;display:block">${yax}${xax}${poly}<line class="tccur" x1="0" y1="${padT}" x2="0" y2="${padT+ch}" stroke="var(--tx3)" stroke-width="1" stroke-dasharray="3 3" style="visibility:hidden"/></svg><div class="tctip"></div></div></div>`;}
function tchart(H){const A=H.allowed||[],DN=H.denied||[],TG=H.telegram||[],TS=H.ts||[],n=A.length;
 if(n<2)return `<div class="mut" style="font-size:12px;padding:6px 0">${t('accruing')}</div>`;
 const W=600,Hh=140,padL=8,padR=8,padT=8,padB=20,cw=W-padL-padR,ch=Hh-padT-padB;
 const X=i=>padL+(i/(n-1))*cw;
 const line=(arr,col)=>{const mx=Math.max(...arr),mn=Math.min(...arr),rg=(mx-mn)||1;return `<polyline points="${arr.map((v,i)=>X(i).toFixed(1)+','+(padT+ch-((v-mn)/rg)*ch).toFixed(1)).join(' ')}" fill="none" stroke="${col}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>`;};
 let xax='';const ticks=Math.min(6,n);
 for(let k=0;k<ticks;k++){const i=Math.round(k/(ticks-1)*(n-1)),x=X(i);xax+=`<line x1="${x.toFixed(1)}" y1="${padT}" x2="${x.toFixed(1)}" y2="${padT+ch}" stroke="var(--line)" stroke-width="1" opacity=".4"/><text x="${x.toFixed(1)}" y="${Hh-6}" text-anchor="${k===0?'start':k===ticks-1?'end':'middle'}" class="tcx">${TS[i]||''}</text>`;}
 const dat=encodeURIComponent(JSON.stringify({ts:TS,a:A,d:DN,t:TG,n:n,W:W,padL:padL,cw:cw}));
 return `<div class="tchart" data-tc="${dat}"><svg viewBox="0 0 ${W} ${Hh}" width="100%" style="height:auto;display:block">${xax}${line(A,CV.accent)}${line(DN,CV.danger)}${line(TG,CV.ok)}<line class="tccur" x1="0" y1="${padT}" x2="0" y2="${padT+ch}" stroke="var(--tx3)" stroke-width="1" stroke-dasharray="3 3" style="visibility:hidden"/></svg><div class="tctip"></div></div>`;}
function donut(counts){
 const dk=document.documentElement.getAttribute('data-theme')==='dark';
 const cols=[['affected','#e0314a'],['needs_review','#e0a030'],['not_affected',dk?'#2ecc8f':'#1aa05e'],['unknown_inventory_gap','#aab2bf']];
 const total=cols.reduce((s,[k])=>s+(counts[k]||0),0)||1;let acc=0,stops=[];
 for(const [k,c] of cols){const v=counts[k]||0;if(!v)continue;const a=(acc/total*100).toFixed(2),b=((acc+v)/total*100).toFixed(2);stops.push(`${c} ${a}% ${b}%`);acc+=v}
 if(!stops.length)stops=[(dk?'#26262b':'#eceef2')+' 0 100%'];
 const txc=dk?'#f2f2f4':'#111114',txc2=dk?'#9398a1':'#6e6e73';
 return `<div class="donut" style="position:relative;width:108px;height:108px;flex:0 0 auto"><div style="width:108px;height:108px;border-radius:50%;background:conic-gradient(${stops.join(',')});-webkit-mask:radial-gradient(transparent 56%,#000 57%);mask:radial-gradient(transparent 56%,#000 57%)"></div><div style="position:absolute;inset:0;display:grid;place-items:center"><div style="text-align:center"><div style="font-size:27px;font-weight:600;color:${txc};line-height:1.05">${counts.affected||0}</div><div style="font-size:11px;color:${txc2}">affected</div></div></div></div>`}
function agg(d){const N=d.nodes||[];const nA=N.find(n=>n.label==='A')||{},nB=N.find(n=>n.label==='B')||{};
 return{N,nA,nB,up:N.filter(n=>n.alive).length,tot:N.length,
  devs:N.reduce((s,n)=>s+(n.monitor||[]).length,0),
  alerts:N.reduce((s,n)=>s+(n.alerts||0),0),
  aff:(nB.cve&&nB.cve.counts&&nB.cve.counts.affected)||0,
  den:(d.governance||{}).denied||0}}
const comp=(col,ic,name,role,rows)=>`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:${col}">${ic}</span>${name} · <b>${role}</b></div>${rows}</div>`;
const mtt=d=>{const m=''+(d.mttr||'—');return CFG.lang==='en'?m.replace(/\s*秒/,'s'):m};
function segNode(){return `<div class="seg">${[['all',t('f_all')],['A',t('f_a')],['B',t('f_b')]].map(([v,l])=>`<button data-act="node" data-v="${v}" class="${CFG.node===v?'on':''}">${l}</button>`).join('')}</div>`}
function actLabel(e){const c=e.cls||'';return c.indexOf('NET')===0?t('act_net'):c.indexOf('PROC')===0?t('act_proc'):c.indexOf('FILE')===0?t('act_file'):t('act_other')}
function evDetail(e){const dn=e.verb==='DENIED';const rows=[
  [t('ev_action'),actLabel(e)+(e.cls?' · '+e.cls:'')],[t('ev_process'),e.binary||'—'],[t('ev_target'),e.target||'—'],
  [t('ev_engine'),e.engine||'—'],[t('ev_sev'),e.sev||'—'],
  [t('ev_policy'),(e.policy&&e.policy!=='-')?e.policy:(dn?t('deny_nopol'):'—')],[t('ev_reason'),e.reason||'—']];
 const note=e.benign?`<div class="evbn">\u{1F4A1} ${t('gov_benign_why')}</div>`:'';
 return note+rows.map(([k,v])=>`<div class="evdk"><span>${k}</span><b>${v}</b></div>`).join('')}

/* ---- views ---- */
function vOverview(d){const a=agg(d),al=d.alerts_list||[];const cs=d.containers||[],cup=cs.filter(c=>/^Up\b/.test(c.status||'')).length;
 const certHi=(d.nodes||[]).reduce((s,n)=>s+(((n.cert||{}).severity||{}).High||0),0);
 const banner=al.length?`<div class="bn bad">⚠︎ ${al.map(x=>esc(L(x,'msg'))).join('　｜　')}</div>`:`<div class="bn ok">${t('banner_ok')}</div>`;
 const kpi=(h,n,sub,l)=>{const _p=(''+h).split('#');return `<a class="kpi" href="#${_p[0]}" data-anchor="${_p[1]||''}"><div class="n">${n}${sub?` <small>${sub}</small>`:''}</div><div class="l">${l}</div></a>`};
 const kpis=`<div class="sec">${t('sec_kpi')}</div><div class="kpis">`+
  kpi('fleet',a.up,'/ '+a.tot,t('kpi_nodes'))+
  kpi('fleet',a.devs,t('unit_host'),a.alerts?`${t('managed_dev')} · <span class="red">${a.alerts} ALERT</span>`:`${t('managed_dev')} · ${t('dev_allok')}`)+
  kpi('gov#govcard',`<span class="${a.den?'red':''}">${a.den}</span>`,'',t('kpi_denied'))+
  kpi('cve#aff',`<span class="${a.aff?'red':''}">${a.aff}</span>`,'',t('kpi_cve'))+
  kpi('ops#mttr',mtt(d),'',t('kpi_mttr'))+
  kpi('ops#snap',(d.snapshots||[]).length,'',t('kpi_snap'))+
  kpi('stack',`<span class="${cup<cs.length?'red':''}">${cup}</span>`,'/ '+cs.length,t('kpi_containers'))+
  kpi('fleet#certcard',`<span class="${certHi?'red':''}">${certHi}</span>`,'',t('kpi_cert'))+`</div>`;
 const comps=`<div class="sec">${t('sec_comp')}</div><div class="grid g4">`+
  comp('var(--purple)','◆','NemoClaw',t('comp_nemo'),`<div class="kv"><span class="k">${t('c_lifecycle')}</span><span class="v">${(d.snapshots||[]).length} ${t('snap_unit')}</span></div><div class="kv"><span class="k">${t('c_restore')}</span><span class="v mono">${(d.snapshots||[]).slice(-1)[0]||'—'}</span></div>`)+
  comp('var(--accent)','▣','OpenShell',t('comp_shell'),`<div class="kv"><span class="k">gateway :18080</span><span class="v">${pill(d.gateway,d.gateway?t('online'):t('offline'))}</span></div><div class="kv"><span class="k">${t('c_deny')}</span><span class="v red">${a.den} DENIED</span></div>`)+
  comp('var(--ok)','✦','Hermes',t('comp_hermes'),`<div class="kv"><span class="k">API :8642</span><span class="v">${pill(d.hermes_api,d.hermes_api?t('online'):t('offline'))}</span></div><div class="kv"><span class="k">${t('c_tg')}</span><span class="v">${pill(d.telegram_recent>0,d.telegram_recent>0?t('alive'):t('stopped'))}</span></div>`)+
  comp('var(--accent)','⬡','OpenClaw',t('comp_oc'),`<div class="kv"><span class="k">${t('c_nodes_online')}</span><span class="v">${a.up} ${t('unit_host')}</span></div><div class="kv"><span class="k">${t('c_bridge')}</span><span class="v mono">${(d.bridge_ips||[]).length} × /32</span></div>`)+`</div>`;
 const nodes=`<div class="sec">${t('sec_nodes')}</div><div class="grid g2">${nodeMini(a.nA,'fleet')}${nodeMini(a.nB,'cve')}</div>`;
 return banner+comps+kpis+nodes}
function nodeMini(n,href){if(!n.label)return '';const ops=(n.caps||[]).includes('fix');
 const okc=(n.monitor||[]).filter(x=>x.status==='ok').length,tot=(n.monitor||[]).length;
 const metric=ops?`${okc}/${tot} ${t('dev_ok')}`:(n.cve?`affected ${(n.cve.counts||{}).affected||0} · ${t('scanned')} ${n.cve.fleet||'?'} ${t('fleet_unit')}`:'—');
 return `<a class="card cardlink" href="#${href}"><div class="ct"><span class="ico" style="background:var(--card2);color:${ops?'var(--ok)':'var(--accent)'}">${ops?'🔧':'🛡'}</span>${t('node_word')} ${n.label} · <b>${roleT(n.role)}</b><span style="margin-left:auto">${n.alive?pill(true,t('online')):pill(false,t('offline'))}</span></div><div class="tags">${(n.caps||[]).map(x=>`<span class="tag">${x}</span>`).join('')}</div><div class="kv"><span class="k">${ops?t('node_net_health'):t('node_cve_health')}</span><span class="v">${metric}</span></div><div class="mut" style="font-size:12px;margin-top:9px">${t('node_detail')}</div></a>`}
function vArch(d){
 const seg=`<div class="filtrow" style="justify-content:flex-end;margin-bottom:14px"><span class="tlabel">${t('arch_view')}</span><div class="seg">${[['detail',t('arch_topo')],['explain',t('arch_explain')]].map(([v,l])=>`<button data-act="archview" data-v="${v}" class="${ARCHVIEW===v?'on':''}">${l}</button>`).join('')}</div></div>`;
 return seg+(ARCHVIEW==='explain'?vArchExplain(d):vArchFlow(d,true));}
function vArchExplain(d){const a=agg(d);
 const g=(txt,cls)=>`<span class="xst ${cls}">${txt}</span>`;
 const den=a.den||0, jiraN=Object.values(d.jira||{}).reduce((x,y)=>x+y,0);
 const s1=g('\u2705 '+t('x_ok'),'g');
 const s2=d.hermes_api?g('\u2705 '+t('x_online'),'g'):g('\u25cf '+t('x_offline'),'r');
 const s3=d.gateway?g('\ud83d\udee1 '+t('x_guard')+' \u00b7 '+t('x_blocked')+' '+den+' '+t('x_times'),'g'):g('\u25cf '+t('x_gate_off'),'r');
 const s4=(a.up===a.tot&&a.tot)?g('\u2705 '+a.up+'/'+a.tot+' '+t('x_hosts'),'g'):(a.up?g('\u26a0 '+a.up+'/'+a.tot+' '+t('x_hosts'),'a'):g('\u25cf '+t('x_offline'),'r'));
 const s5=jiraN?g('\u26a0 '+jiraN+' '+t('x_pending'),'a'):g('\u2705 '+t('x_clear'),'g');
 const step=(n,ic,ti,de,st)=>`<div class="xstep"><div class="xnum">${n}</div><div class="xbody"><div class="xhead"><span class="xico">${ic}</span><b>${ti}</b><span class="xstwrap">${st}</span></div><div class="xdesc">${de}</div></div></div>`;
 const arr=`<div class="xarrow">\u2193</div>`;
 return `<div class="explain"><div class="xpintro">${t('xp_intro')}</div>`+
  step('1','\u2708',t('x1_t'),t('x1_d'),s1)+arr+
  step('2','\u2726',t('x2_t'),t('x2_d'),s2)+arr+
  step('3','\u25a3',t('x3_t'),t('x3_d'),s3)+arr+
  step('4','\ud83d\udd27',t('x4_t'),t('x4_d'),s4)+arr+
  step('5','\ud83c\udfab',t('x5_t'),t('x5_d'),s5)+
  `</div>`;}
function vArchFlow(d,DET){const a=agg(d),nA=a.nA,nB=a.nB,tg=d.telegram_recent>0,ips=d.bridge_ips||[];
 const al=(d.governance||{}).allowed||{};const certHi=(d.nodes||[]).reduce((x,n)=>x+(((n.cert||{}).severity||{}).High||0),0);const T=(a.nA.traffic)||null;
 const meta=(proto,traf)=>DET?`<div class="aflow"><span class="tproto">${proto}</span>${traf?`<span class="ttraf">${traf}</span>`:''}</div>`:'';
 const evs=[];if(a.den)evs.push('DENIED ×'+a.den);if(certHi)evs.push('cert High ×'+certHi);if(a.aff)evs.push('CVE affected ×'+a.aff);if(T&&T.anomaly)evs.push(t('tr_anom'));(d.alerts_list||[]).forEach(x=>evs.push(typeof x==='string'?x:L(x,'msg')));
 const evbar=DET?`<div class="archev"><span class="archevh">\u26a0 ${t('arch_events')}</span>${evs.length?[...new Set(evs)].slice(0,6).map(x=>`<span class="tevt">${x}</span>`).join(''):`<span class="mut" style="font-size:12px">${t('arch_noevt')}</span>`}</div>`:'';
 const dot=ok=>`<span class="adot ${ok?'g':'r'}"></span>`;
 const ico=(c,g)=>`<span class="aico ${c}">${g}</span>`;
 const conn=l=>`<div class="conn"><span class="ln"></span>${l?`<span class="pill">${l}</span>`:''}<span class="tip"></span></div>`;
 const ocDesc=n=>((n.monitor||[]).map(x=>x.asset).join(' · ')||'—');
 const nemo=`<a class="aband nemo" data-drawer="nemo" style="cursor:pointer"><div class="aptag">${t('a_t_mgmt')}</div><div class="bt">${ico('p','◆')}${t('a_nemo')}<span style="margin-left:auto;font-weight:600;font-size:12.5px">${(d.snapshots||[]).length} ${t('snap_unit')}</span></div><div class="bd">${t('a_nemo_d')}</div></a>`;
 const entry=`<div class="atier"><a class="abox" href="#gov"><div class="bt">${dot(tg)}${ico('a','✈')}${t('a_tg')}</div><div class="bd">${tg?t('alive'):t('stopped')}${meta('HTTPS api.telegram.org:443','getUpdates ×'+(d.telegram_recent||0))}</div></a><a class="abox" href="#gov"><div class="bt">${dot(true)}${ico('w','✉')}${t('a_email')}</div><div class="bd">:3993${meta('IMAPS:3993 · SMTP:3587','ALLOWED ×'+(al.greenmail_mail||0))}</div></a></div>`;
 // OpenShell 強制層 = 把三個 agent 各自沙箱包起來,每個自有政策(deny-by-default)
 const sbox=(alive,c,g,name,sandbox,desc,pols,href,wide)=>`<a class="abox"${wide?' style="max-width:470px"':''} href="#${href}"><div class="bt">${dot(alive)}${ico(c,g)}${name}</div><div class="bd">${desc}</div><div class="sbpol"><span class="pc sb">⬡ ${sandbox}</span><span class="pc deny">${t('a_denydef')}</span>${(pols||[]).map(p=>`<span class="pc">policy:${p}</span>`).join('')}</div></a>`;
 const hpol=((d.policy||{}).networks||[]).slice(0,3).map(x=>x.name);
 const hsb=(d.policy||{}).sandbox||'hermes-demo';
 const hpols=(hpol.length?hpol:['greenmail_mail','telegram','openclaw_bridge']);
 const hermesBox=`<a class="abox" data-drawer="hermes" style="cursor:pointer;max-width:470px"><div class="bt">${dot(d.hermes_api)}${ico('g','✦')}Hermes · ${t('comp_hermes')}</div><div class="bd">API :8642 · ${d.hermes_api?t('online'):t('offline')} · Telegram ${tg?t('alive'):t('stopped')}</div><div class="sbpol"><span class="pc sb">⬡ ${hsb}</span><span class="pc deny">${t('a_denydef')}</span>${hpols.map(p=>`<span class="pc">policy:${p}</span>`).join('')}</div></a>`;
 const ocBox=(n,href,c,g,pols)=>sbox(!!n.alive,c,g,'OpenClaw '+(n.label||'—')+' · '+roleT(n.role),n.name||(n.label==='B'?'openclaw-2':'my-assistant'),ocDesc(n),pols,href);
 const bridgeConn=`<div class="conn"><span class="ln"></span><span class="pill">${t('a_bridge')}</span><span class="pill mono" style="margin-top:3px">${ips.join(' · ')||'172.18.0.2/32 · 172.18.0.4/32'}</span>${DET?`<span class="pill mono" style="margin-top:3px">:9099 · ALLOWED ×${al.openclaw_bridge||0}</span>`:''}<span class="tip"></span></div>`;
 const ocTier=`<div class="atier">${ocBox(nA,'fleet','g','🔧',['openclaw_bridge','jira'])}${ocBox(nB,'cve','a','🛡',['openclaw_bridge'])}</div>`;
 const encl=`<div class="encl"><a class="enclh" data-drawer="openshell" style="cursor:pointer" title="${t('comp_shell')}">${ico('a','▣')}${t('a_shell')}<span class="encltag">${t('a_t_enf')}</span><span style="margin-left:auto">gateway :18080 · <b class="${a.den?'red':''}">${a.den} DENIED</b> →</span></a><div class="encld">${t('a_encl_d')}</div><div class="atier">${hermesBox}</div>${bridgeConn}${ocTier}</div>`;
 const leaf=`<div class="atier"><a class="abox" href="#fleet"><div class="bt">${ico('a','⬡')}${t('a_fleet')}<span style="margin-left:auto;font-weight:600;font-size:12.5px">${a.devs} ${t('fleet_unit')}</span></div><div class="bd">${a.alerts?`<span class="red">${a.alerts} ALERT</span>`:'全 ok / all ok'}${DET?`<div class="aflow"><span class="tproto">WAN ${T?T.latest+' Mbps':'\u2014'}</span><span class="tst ${T&&T.anomaly?'r':'g'}">${T&&T.anomaly?t('tr_anom'):t('tr_norm')}</span></div>`:''}</div></a><a class="abox" href="#ops"><div class="bt">${ico('w','🎫')}${t('a_egress')}</div><div class="bd">${t('a_egress_d')}${DET?`<div class="aflow"><span class="tproto">:3690</span><span class="tst g">Jira</span><span class="tproto">:3993</span><span class="tst g">mail</span><span class="tproto">:443</span><span class="tst g">${t('sk_n_ai')}</span></div>`:''}</div></a></div>`;
 return `<div class="arch">${evbar}${nemo}${conn(t('a_manages'))}${entry}${conn(t('a_report'))}${encl}${conn(t('a_egress'))}${leaf}<div class="aleg">${t('a_legend')}</div></div>`}
function vFleet(d){const a=agg(d);let cards='';
 for(const n of [a.nA,a.nB]){if(!n.label)continue;if(CFG.node!=='all'&&n.label!==CFG.node)continue;
  const ops=(n.caps||[]).includes('fix'),col=ops?'var(--ok)':'var(--accent)';let body='';
  for(const x of (n.monitor||[])){const reg=x.regressions||[],pend=x.pending||[];const eb=(x.asset||'').includes('ebg19p');
   body+=`<div class="dev${eb?' clickable':''}"${eb?' data-drawer="ebg"':''}><div class="devh"><span>${sdot(x.status)}${x.asset}${eb?` <span class="mgd"><img src="/brand.svg" width="12" height="12">${t('drw_managed')}</span>`:''}</span><span>${(''+x.status).includes('ALERT')?`<span class="red">${alertLbl(x.status)}</span>`:(x.offline||x.status==='offline')?`<span class="mut">${t('offline')}</span>`:`<span class="ok">ok</span>`}${eb?` <span class="mut" style="font-size:11px;margin-left:8px">${t('drw_hint')}</span>`:''}</span></div>`
    +(reg.length?`<div class="devd"><span class="dl red">${t('reg')} ${reg.length}</span>${reg.map(r=>`<span class="chip">${r}</span>`).join('')}</div>`:'')
    +(pend.length?`<div class="devd"><span class="dl warn">${t('pend')} ${pend.length}</span>${pend.map(r=>`<span class="chip">${r}</span>`).join('')}</div>`:'')
    +((!reg.length&&!pend.length)?`<div class="devd mut">${t('nodrift')}</div>`:'')+(x.health?`<div class="devd" style="flex-direction:column;align-items:stretch;gap:7px;margin-top:3px;border-top:1px dashed var(--line);padding-top:8px"><div style="display:flex;gap:18px;flex-wrap:wrap;font-size:12px"><span style="color:var(--tx3)">${t('h_health')}</span><span>CPU <b class="${(x.health.cpu_pct||0)>=85?'red':''}">${x.health.cpu_pct==null?'—':x.health.cpu_pct+'%'}</b></span><span>RAM <b class="${(x.health.ram_pct||0)>=85?'red':''}">${x.health.ram_pct==null?'—':x.health.ram_pct+'%'}</b></span><span>${t('h_temp')} <b class="${(x.health.temp_c||0)>=80?'red':''}">${x.health.temp_c==null?'—':x.health.temp_c+'°C'}</b></span></div><div style="display:flex;gap:5px;flex-wrap:wrap;align-items:center"><span style="color:var(--tx3);font-size:11px">${t('h_ports')}</span>${(x.health.ports||[]).map(p=>`<span class="chip" style="${p.state==='up'?'border-color:var(--ok);color:var(--ok)':'opacity:.4'}" title="${p.port} · ${p.speed}">${p.port.replace('LAN ','L').replace('WAN ','W')}${p.state==='up'?' '+p.speed:''}</span>`).join('')}</div></div>`:'')+`</div>`}
  if(!(n.monitor||[]).length)body=`<div class="mut">${t('nomon')}</div>`;
  if(ops&&n.scenarios)body+=`<div class="dev"><div class="devh"><span class="mut">${t('scen')}</span><span class="v">${(n.scenarios||[]).length} ${t('scen_unit')}</span></div></div>`;
  let assetc='';
  if(n.assets){const A=n.assets;
   const rows=(A.list||[]).map(x=>`<div class="ast"><span class="adot ${x.known?'g':'r'}" style="box-shadow:0 0 0 3px ${x.known?'var(--okbg)':'var(--dangerbg)'}"></span><span>${x.name||'—'}</span><span class="am">${x.mac}</span><span class="ai">${x.ip}</span><span class="ab ${x.known?'k':'u'}">${x.known?t('asset_known'):t('assets_unknown')}</span></div>`).join('')||`<div class="mut">${t('assets_none')}</div>`;
   assetc=`<div class="card" style="margin-top:0"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🖧</span>${t('assets_title')} · <b>EBG19P</b><span style="margin-left:auto">${A.count} ${t('assets_unit')}${A.unknown?` · <span class="red">${A.unknown} ${t('assets_unknown')}</span>`:''}</span></div>${rows}</div>`}
  let trafc='';
  if(n.traffic){const T=n.traffic;
   trafc=`<div class="card" style="margin-top:0"><div class="ct"><span class="ico" style="background:var(--card2);color:${T.anomaly?'var(--danger)':'var(--accent)'}">📶</span>${t('tr_title')} · <b>EBG19P</b><span style="margin-left:auto">${T.anomaly?`<span class="red">⚠︎ ${t('tr_anom')}</span>`:`<span class="mut" style="font-weight:400">${t('tr_norm')}</span>`}</span></div><div class="split" style="gap:24px;align-items:center"><div style="flex:0 0 auto">${spark(T.series,T.anomaly?CV.danger:CV.accent)}</div><div class="stat" style="margin-top:0;flex:1"><div class="s"><b class="${T.anomaly?'red':''}">${T.latest}</b><span>${t('tr_now')} Mbps</span></div><div class="s"><b>${T.avg}</b><span>${t('tr_avg')}</span></div><div class="s"><b>${T.peak}</b><span>${t('tr_peak')}</span></div></div></div></div>`}
  let dlogc='';
  if(n.devlog){const L=n.devlog,cats=Object.entries(L.by_category||{}).sort((x,y)=>y[1]-x[1]),mx=Math.max(1,...cats.map(e=>e[1]));
   const wn=(L.by_severity||{}).warn||0,hi=(L.by_severity||{}).high||0;
   dlogc=`<div class="card clickable" data-drawer="ebg" style="margin-top:0"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🖹</span>${t('dl_title')} <span class="mut" style="font-weight:400;margin-left:2px">${t('dl_sub')}</span><span style="margin-left:auto">${L.total} ${t('dl_total')}${(wn+hi)?` · <span class="${hi?'red':''}" style="${!hi?'color:var(--warn)':''}">${wn+hi} ${t('dl_sec')}</span>`:''}</span></div>${cats.map(([k,v])=>`<div class="bar"><span class="bl">${k}</span><div class="bt"><div class="bf" style="width:${Math.max(6,v/mx*100).toFixed(0)}%"></div></div><span class="bv">${v}</span></div>`).join('')}<div class="mut" style="font-size:12px;margin-top:9px">${t('drw_hint')}</div></div>`}
  let loganac='';
  if(n.loganalysis){const LA=n.loganalysis,fs=(LA.findings||[]).concat(LA.fusion||[]),rc=LA.root_causes||[];
   const sc=s=>s==='high'?'var(--danger)':'var(--warn)';
   const frows=fs.map(x=>`<div class="kv" style="align-items:flex-start"><span class="k" style="flex:0 0 auto;color:${sc(x.sev)}">${x.sev==='high'?'⛔':'⚠︎'}</span><span class="v" style="text-align:left;flex:1">${esc(L(x,'title'))}${(L(x,'detail'))?`<div class="mut" style="font-size:11px;margin-top:1px">${esc(L(x,'detail'))}</div>`:''}</span></div>`).join('')||`<div class="mut">${t('la_clean')}</div>`;
   const rcrows=rc.length?`<div class="mut" style="font-size:11.5px;margin-top:9px;margin-bottom:2px">${t('la_root')}</div>`+rc.map(r=>`<div class="kv"><span class="k mono" style="flex:1;text-align:left;font-size:11.5px" title="${esc(r.sample||'')}">${esc(((r.tag||'')+' · '+(r.pattern||'')).slice(0,58))}</span><span class="v">×${r.count}</span></div>`).join(''):'';
   loganac=`<div class="card" style="margin-top:0"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🧠</span>${t('la_title')} · <b>EBG19P</b><span class="mut" style="font-weight:400;margin-left:6px">${t('la_sub')}</span></div>${(L(LA,'summary'))?`<div class="mut" style="font-size:12px;margin-bottom:9px;line-height:1.5">${esc(L(LA,'summary'))}</div>`:''}${frows}${rcrows}</div>`}
  let certc='';
  if(n.cert){const CE=n.cert,fs=CE.findings||[],sv=CE.severity||{};
   const issL={untrusted:t('ce_untrusted'),weak_algorithm:t('ce_weakalg'),expired:t('ce_expired'),expiring:t('ce_expiring'),weak_protocol:t('ce_weakproto'),weak_cipher:t('ce_weakcipher'),weak_ssh:t('ce_weakssh')};
   const rows=fs.map(f=>`<tr class="clickable" data-drawer="cert:${f.asset}" data-focus="${f.issue}|${f.service}"><td>${f.asset}</td><td class="mono" style="font-size:11.5px">${f.service}</td><td><span class="sev ${f.severity==='High'?'high':'med'}">${issL[f.issue]||f.issue}</span></td><td style="color:var(--tx2);font-size:12px">${esc(L(f,'detail'))} ›</td></tr>`).join('');
   certc=`<div class="card" style="margin-top:0" id="certcard"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--danger)">🔐</span>${t('cert_title')} <span class="mut" style="font-weight:400;margin-left:2px">${t('cert_sub')}</span><span style="margin-left:auto">${sv.High?`<span class="red">${sv.High} ${t('cert_high')}</span>`:''}${sv.Medium?` · <span style="color:var(--warn)">${sv.Medium} ${t('cert_med')}</span>`:''}</span></div>${fs.length?`<table class="tb"><thead><tr><th>${t('th_asset')}</th><th>${t('cert_service')}</th><th>${t('cert_issue')}</th><th>${t('cert_detail')}</th></tr></thead><tbody>${rows}</tbody></table>`:`<div class="mut">${t('cert_clean')}</div>`}</div>`}
  cards+=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:${col}">${ops?'🔧':'🛡'}</span>${t('node_word')} ${n.label} · <b>${roleT(n.role)}</b><span style="margin-left:auto">${n.alive?pill(true,t('online')):pill(false,t('offline'))}</span></div><div class="tags">${(n.caps||[]).map(x=>`<span class="tag">${x}</span>`).join('')}</div>${body}</div>`+assetc+trafc+dlogc+loganac+certc}
 if(!cards)cards=`<div class="card mut">${t('nonode')}</div>`;
 return `<div class="filtrow"><span class="tlabel">${t('filter_node')}</span>${segNode()}</div><div style="display:flex;flex-direction:column;gap:16px">${cards}</div>`}
function vCve(d){const a=agg(d),n=a.nB;
 if(!n.cve)return `<div class="card mut">${t('cve_off')}<div class="acts"><button class="btn" data-act="do" data-v="cve">${t('btn_rescan')}</button></div></div>`;
 const c=n.cve.counts||{};
 const left=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--danger)">🛡</span>${t('cve_grade')} · <b>${t('scanned')} ${n.cve.fleet||'?'} ${t('fleet_unit')}</b></div><div class="split"><div>${donut(c)}</div><div class="legend"><div><i style="background:var(--danger)"></i>affected ${c.affected||0}</div><div><i style="background:var(--warn)"></i>needs_review ${c.needs_review||0}</div><div><i style="background:#1aa05e"></i>not_affected ${c.not_affected||0}</div><div><i style="background:#9aa3af"></i>inventory_gap ${c.unknown_inventory_gap||0}</div></div></div><div class="acts"><button class="btn" data-act="do" data-v="cve">${t('btn_rescan')}</button></div></div>`;
 const aff=n.cve.affected_list||[];
 const afftb=`<div class="card" id="aff"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--danger)">⚠︎</span>${t('aff_title')} · <b>${t('aff_jira')}</b></div>${aff.length?`<table class="tb"><thead><tr><th>${t('th_cve')}</th><th>${t('th_asset')}</th><th>${t('th_comp')}</th><th>${t('th_ver')}</th><th>${t('th_sev')}</th></tr></thead><tbody>${aff.map(f=>`<tr><td class="mono">${f.cve?`<a href="https://nvd.nist.gov/vuln/detail/${f.cve}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">${f.cve} ↗</a>`:'—'}</td><td>${f.asset||'—'}</td><td>${f.component||'—'}</td><td class="mono">${f.ver||'—'}</td><td><span class="sev ${sevc(f.sev)}">${f.sev||'—'}</span></td></tr>`).join('')}</tbody></table>`:`<div class="mut">${t('noaff')}</div>`}</div>`;
 const s=n.source;
 const src=s?`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">⌗</span>${t('src_title')} <span class="mut" style="font-weight:400">${esc(s.sbom_source||'openwrt')}</span>${(s.sbom_source&&s.sbom_source.indexOf('asuswrt-merlin')>=0)?` <span class="mut" style="font-weight:400;opacity:.7">· ${t('src_prov')}</span>`:''}</div>${s.analysis_by?`<div class="mut" style="font-size:11.5px;margin:-2px 0 6px">⚙ ${esc(s.analysis_by)}</div>`:''}${(s.cve_feed&&s.cve_feed!=='—')?`<div class="mut" style="font-size:11.5px;margin:-2px 0 6px">🛰 ${t('src_feed')} · ${esc(s.cve_feed)}</div>`:''}${s.advisories_source?`<div class="mut" style="font-size:11.5px;margin:-2px 0 8px">📜 ${t('src_adv')} · ${esc(s.advisories_source)}(${t('src_fixed')} ${s.advisories_fixed||0})${(s.cve_reconciled||0)>0?` · ${t('src_recon')} <b class="grn">${s.cve_reconciled}</b>`:''}</div>`:''}<div class="stat"><div class="s"><b>${s.sbom||0}</b><span>${t('src_sbom')}</span></div><div class="s"><b>${s.sast||0}</b><span>${t('src_sast')}</span></div><div class="s"><b class="red">${s.design_violated||0}</b><span>${t('src_design')}</span></div></div>${(s.sast_list||[]).length?`${s.sast_source?`<div class="mut" style="margin-top:13px;font-size:12px">SAST · ${esc(s.sast_source)}</div>`:''}<table class="tb" style="margin-top:8px"><thead><tr><th>${t('th_cwe')}</th><th>${t('th_file')}</th><th>${t('th_line')}</th></tr></thead><tbody>${s.sast_list.map((x,i)=>`<tr class="clickable" data-drawer="sast:${i}"><td class="mono">${x.cwe||'—'}</td><td class="mono" style="word-break:break-all">${esc(x.upstream_path||x.file||'—')}</td><td class="mono">${x.line||'—'} ›</td></tr>`).join('')}</tbody></table>`:''}${(s.design||[]).length?`<div class="mut" style="margin-top:14px;font-size:12px">${t('src_reqs')}</div><table class="tb" style="margin-top:6px"><tbody>${s.design.map(x=>`<tr><td class="mono" style="white-space:nowrap;vertical-align:top;${x.status==='violated'?'color:var(--danger);font-weight:600':''}">${esc(x.req)}</td><td>${esc(L(x,'desc'))}${(L(x,'evidence'))?`<div class="mut" style="font-size:11px;margin-top:2px">${esc(L(x,'evidence'))}</div>`:''}</td><td style="text-align:right;vertical-align:top">${x.status==='violated'?`<span class="pill bad">${t('st_violated')}</span>`:x.status==='compliant'?`<span class="pill ok">${t('st_compliant')}</span>`:`<span class="pill">${t('st_na')}</span>`}</td></tr>`).join('')}</tbody></table>`:''}<div class="acts"><button class="btn" data-act="do" data-v="source">${t('btn_source')}</button></div></div>`:'';
 return `<div style="display:flex;flex-direction:column;gap:16px">${left}${afftb}${src}</div>`}
function vGov(d){const a=agg(d);
 const fseg=`<div class="seg">${[['all',t('e_all')],['ALLOWED',t('e_allow')],['DENIED',t('e_deny')]].map(([v,l])=>`<button data-act="evf" data-v="${v}" class="${EVF===v?'on':''}">${l}</button>`).join('')}</div>`;
 let evs=(d.events||[]);if(EVF!=='all')evs=evs.filter(e=>e.verb===EVF);
 const evlist=evs.map(e=>{const dn=e.verb==='DENIED',hp=e.policy&&e.policy!=='-',bn=e.binary?e.binary.replace(/^.*\//,''):'';
   const mid=dn?(bn?bn+' → '+(e.target||'?'):(e.target||e.cls||'blocked')):(hp?('policy:'+e.policy):(e.target||e.cls||e.verb));
   const rt=dn?(e.reason||e.cls||''):(bn?bn+' → '+(e.target||''):(hp?(e.target||''):(e.cls||'')));
   const pcls=dn?'d':(hp?'':'n'),op=OPEN_EV.has(e.ts);
   return `<div class="evrow" data-ev="${e.ts}"><div class="ev"><span class="t">${e.t}</span><span class="vb ${dn?(e.benign?'n':'d'):'a'}">${e.verb}</span>${e.benign?` <span class="bnt">${t('gov_benign_t')}</span>`:''}<span class="pol ${pcls}">${mid}</span><span class="tg" title="${rt}">${rt}</span><span class="evx">${op?'▾':'▸'}</span></div>${op?`<div class="evd">${evDetail(e)}</div>`:''}</div>`}).join('')||`<div class="mut">${t('ev_none')}</div>`;
 const evcard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">⚡</span>${t('ev_title')} <span class="mut" style="font-weight:400;margin-left:2px">${t('ev_sub')} · ${t('ev_hint')}</span><span style="margin-left:auto">${fseg}</span></div>${evlist}</div>`;
 const al2=(d.governance||{}).allowed||{},ents=Object.entries(al2).sort((x,y)=>y[1]-x[1]).slice(0,8),mx=Math.max(1,...ents.map(e=>e[1]));
 const bars=ents.map(([k,v])=>`<div class="bar"><span class="bl">policy:${k}</span><div class="bt"><div class="bf" style="width:${Math.max(5,v/mx*100).toFixed(0)}%"></div></div><span class="bv">${v}</span></div>`).join('')||`<div class="mut">${t('collecting')}</div>`;
 const govcard=`<div class="card" id="govcard"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">📊</span>${t('gov_title')} · <b>ALLOWED by policy</b> <span class="mut" style="font-weight:400">${t('gov_2h')}</span></div>${bars}<div class="kv"><span class="k red">${t('gov_denytot')}</span><span class="v red">${a.den}</span></div>${(d.governance&&d.governance.denied_benign)?`<div class="kv"><span class="k mut">${t('gov_benign')}</span><span class="v mut">${d.governance.denied_benign}</span></div>`:''}</div>`;
 const hi=d.history||{};
 const trend=(()=>{const A=hi.allowed||[],DN=hi.denied||[],TG=hi.telegram||[],TS=hi.ts||[],nn=A.length;
  const rng=nn?`${TS[0]||''} – ${TS[nn-1]||''} · ${nn} ${t('tr_samples')}`:t('accruing');
  let tl='';for(let i=nn-1;i>=0&&((nn-1-i)<8);i--){const da=i>0?(A[i]-A[i-1]):0,dd=i>0?(DN[i]-DN[i-1]):0;
    tl+=`<div class="tlrow"><span class="tlt">${TS[i]||'—'}</span><span class="tla">${A[i]||0} <small class="mut">${t('tr_act_u')}</small>${da>0?` <span class="ok">▲${da}</span>`:''}</span><span class="tlb">${t('tr_deny_u')} ${DN[i]||0}${dd>0?` <span class="red">▲${dd}</span>`:''} · ${t('tr_hb_u')} ${TG[i]||0}</span></div>`;}
  const lg=`<div class="tclg"><span><i style="background:${CV.accent}"></i>${t('tr_actions')}</span><span><i style="background:${CV.danger}"></i>${t('gov_denytot')}</span><span><i style="background:${CV.ok}"></i>${t('tr_tg')}</span></div>`;
  return `<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">📈</span><b>${t('trend')}</b> <span class="mut" style="font-weight:400;margin-left:2px">${rng}</span></div>`
   +`<div style="display:flex;flex-direction:column;gap:14px">${tser(t('tr_actions'),A,TS,CV.accent)}${tser(t('gov_denytot'),DN,TS,CV.danger)}${tser(t('tr_tg'),TG,TS,CV.ok)}</div>`
   +`<div class="sec" style="margin:16px 4px 8px">${t('tr_recent')}</div>${tl||`<div class="mut">${t('accruing')}</div>`}</div>`;})();
 const allsb=(d.policy||{}).sandboxes||[];
 const rsb=window.RO_SB||(d.policy||{}).sandbox;
 const p=((window.ROPOL&&window.ROPOL.sandbox===rsb)?window.ROPOL:(d.policy||{})),nets=p.networks||[];
 const rosel=allsb.length?`<div class="seg" style="flex-wrap:wrap;gap:6px;margin-bottom:10px">${allsb.map(s=>`<button class="${s.name===rsb?'on':''}" data-act="polro" data-sb="${esc(s.name)}">${esc(s.label)}</button>`).join('')}</div>`:'';
 const core=new Set(['greenmail_mail','telegram','telegram_bot','openclaw_bridge','nvidia']);
 const cn=nets.filter(n=>core.has(n.name)),rest=nets.filter(n=>!core.has(n.name));
 const prow=n=>`<div class="kv" style="align-items:flex-start;gap:14px"><span class="k mono" style="color:var(--accent);flex:0 0 146px">${n.name}</span><span class="v mono" style="font-weight:400;text-align:right;word-break:break-all">${(n.eps||[]).join(', ')||(n.nbin?n.nbin+' bin':'—')}</span></div>`;
 const polrows=(cn.length?cn:nets).map(prow).join('')||`<div class="mut">${t('collecting')}</div>`;
 const restline=rest.length?`<div class="kv" style="align-items:flex-start;gap:14px"><span class="k" style="flex:0 0 146px">${t('pol_more')} (${rest.length})</span><span class="v mono" style="font-weight:400;text-align:right;word-break:break-all">${rest.map(n=>n.name).join(', ')}</span></div>`:'';
 const fsrw=(p.fs_rw||[]).length?`<div class="kv" style="align-items:flex-start;gap:14px"><span class="k" style="flex:0 0 146px">${t('pol_fsrw')}</span><span class="v mono" style="font-weight:400;text-align:right;word-break:break-all">${p.fs_rw.join(' · ')}</span></div>`:'';
 const polcard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">▣</span>${t('pol_title')} <span class="mut" style="font-weight:400">${p.sandbox||''} · v${p.version||'?'}${p.hash?' · '+p.hash:''}</span><span class="pill ok" style="margin-left:auto">🔒 ${t('pol_ro')}</span></div>${rosel}<div class="mut" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px">${t('pol_allowlist')}</div>${polrows}${restline}${fsrw}<div class="mut" style="margin-top:11px;line-height:1.6">🔒 ${t('pol_edit')}</div></div>`;
 const poledit=(d._me&&d._me.role==='admin')?`<button class="btn" data-act="openpolicy" style="margin-left:auto">${t('pol_edit_btn')}</button>`:'';
 const anoms=d.anomalies||[];const acolor={high:'var(--danger)',warn:'var(--warn)',info:'var(--tx2)'};
 const nAlert=anoms.filter(a=>a.sev==='high'||a.sev==='warn').length;   // 只有 high/warn 算「警示」;info(如實機離線)中性
 const anomCard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:${nAlert?'var(--danger)':'var(--ok)'}">🛰</span><b>${t('anom_title')}</b><span class="pill ${nAlert?'bad':'ok'}" style="margin-left:auto">${nAlert?(nAlert+' '+t('anom_found')):t('anom_clear')}</span></div>${anoms.length?anoms.map(a=>`<div class="setrow" style="padding:7px 0"><div><div class="sk" style="font-size:12.5px;color:${acolor[a.sev]||'var(--tx)'}">${a.sev==='high'?'🔴':a.sev==='warn'?'🟠':'🔵'} ${esc(L(a,'msg'))}</div><div class="sd2">${esc(a.kind)}</div></div></div>`).join(''):`<div class="mut">${t('anom_none')}</div>`}</div>`;
 return `<div class="sec">${t('anom_sec')}</div>${anomCard}<div class="sec" style="display:flex;align-items:center;gap:10px">${t('pol_title')} · ${t('pol_ro')}${poledit}</div>${polcard}${evcard}<div class="sec">${t('sec_gov_trend')}</div><div style="display:flex;flex-direction:column;gap:16px">${govcard}${trend}</div>`}
function vOps(d){const jk=d.jira||{};const jt=d.jira_tickets||[];
 const jtbl=jt.length?`<div class="mut" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin:13px 0 4px">${t('jira_tickets')}</div><table class="tb"><thead><tr><th>${t('jira_id')}</th><th>${t('jira_pri')}</th><th>${t('jira_asset')}</th><th>${t('jira_sum')}</th></tr></thead><tbody>${jt.map(k=>`<tr><td class="mono">${k.id||'—'}</td><td><span class="sev ${sevc(k.priority)}">${k.priority||'—'}</span></td><td>${k.asset||'—'}</td><td style="max-width:330px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${(k.summary||'').replace(/"/g,'&quot;')}">${k.summary||''}</td></tr>`).join('')}</tbody></table>`:'';
 const jira=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--warn)">🎫</span>${t('jira_title')} · <b>${t('jira_hil')}</b></div>${Object.entries(jk).map(([k,v])=>`<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`).join('')||`<div class="mut">${t('jira_empty')}</div>`}${jtbl}<div class="acts"><button class="btn" data-act="do" data-v="jira_reset">${t('jira_reset')}</button></div></div>`;
 const g=d.guard||[];
 const guard=`<div class="card" id="mttr"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">🛡</span>${t('guard_title')} <span class="mut" style="font-weight:400">${t('guard_legend')}</span></div><div class="gh">${g.map(x=>`<span class="gb ${x.fails>0?'f':''} ${x.bridge?'br':''}" title="${x.ts} fails=${x.fails}"></span>`).join('')||'<span class="mut">—</span>'}</div><div class="kv" style="margin-top:13px"><span class="k">${t('guard_recent')}</span><span class="v ok">${g.length?('fails='+g.slice(-1)[0].fails):'—'}</span></div><div class="kv"><span class="k">${t('mttr_row')}</span><span class="v">${mtt(d)}<small class="mut" style="font-weight:400"> · ${d.mttr_n?('n='+d.mttr_n):t('mttr_base')}</small></span></div></div>`;
 const isAdm=(d._me||{}).role==='admin';
 const agcolor={'hermes-demo':'var(--ok)','my-assistant':'var(--accent)','openclaw-2':'var(--purple)'};
 const snapTime=ts=>{const m=(''+(ts||'')).match(/^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})/);return m?(m[1]+' '+m[2]+':'+m[3]):''};
 const agblock=(a)=>{const rows=(a.items||[]).slice().reverse();
   const ck=s=>a.sb+'|'+s.ts;
   const body=rows.length?rows.map(s=>`<div class="snap">${isAdm?`<input type="checkbox" data-act="snapsel" data-k="${esc(ck(s))}" ${SNAPSEL.has(ck(s))?'checked':''} style="flex:0 0 auto;margin:0;accent-color:var(--accent);cursor:pointer">`:'<span class="sd"></span>'}<span class="mono" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">${esc(s.name)} <small class="mut">${esc(s.ver)}</small></span><small class="mut" style="flex:0 0 auto;white-space:nowrap">🕑 ${snapTime(s.ts)}</small>${isAdm?`<button class="btn" style="flex:0 0 auto;padding:3px 8px" data-act="snapdel" data-sb="${esc(a.sb)}" data-ts="${esc(s.ts)}" data-v="${esc(s.ver)}" title="${t('snap_del_btn')}">🗑</button>`:''}</div>`).join(''):'<div class="mut">—</div>';
   const sel=(a.items||[]).filter(s=>SNAPSEL.has(ck(s))).length;
   const hdr=isAdm?`<span style="margin-left:auto;display:flex;gap:8px">${sel?`<button class="btn" data-act="snapdelsel" data-sb="${esc(a.sb)}">🗑 ${t('snap_del_sel')} (${sel})</button>`:''}<button class="btn" data-act="snapcreate" data-sb="${esc(a.sb)}">${t('snap_create_btn')}</button></span>`:'';
   return `<div class="card" style="margin-top:12px"><div class="ct"><span class="ico" style="background:var(--card2);color:${agcolor[a.sb]||'var(--purple)'}">◆</span>${esc(a.label)} <span class="mut" style="font-weight:400">${esc(a.sb)} · ${(a.items||[]).length}</span>${hdr}</div>${body}</div>`};
 const snaps=`<div class="card" id="snap"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">◆</span>${t('snap_title')} · <b>${t('snap_restore')}</b></div><div class="mut" style="line-height:1.6">${t('snap_per_agent_d')}</div></div>${(d.snapshots_by_agent||[]).map(agblock).join('')}`;
 const bridge=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">⬡</span>${t('bridge_title')}</div>${(d.bridge_ips||[]).map(ip=>`<div class="kv"><span class="k mono">${ip}</span><span class="v">${pill(true,t('bridge_auth'))}</span></div>`).join('')||'<div class="mut">—</div>'}<div class="mut" style="font-size:12px;margin-top:9px">${t('bridge_note')}</div></div>`;
 return `<div class="grid">${jira}${guard}</div><div class="sec">${t('sec_snap_bridge')}</div><div class="grid g2">${snaps}${bridge}</div>`}
function vSettings(d){
 const seg=(act,opts,cur)=>`<div class="seg">${opts.map(([v,l])=>`<button data-act="${act}" data-v="${v}" class="${(''+cur)===(''+v)?'on':''}">${l}</button>`).join('')}</div>`;
 const appearance=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">🎨</span><b>${t('set_appearance')}</b></div><div class="setrow"><div><div class="sk">${t('set_theme')}</div><div class="sd2">${t('set_theme_d')}</div></div>${seg('theme',[['light',t('th_light')],['dark',t('th_dark')]],CFG.theme)}</div><div class="setrow"><div><div class="sk">${t('set_lang')}</div><div class="sd2">${t('set_lang_d')}</div></div>${seg('lang',[['zh','繁體中文'],['en','English']],CFG.lang)}</div><div class="setrow"><div><div class="sk">${t('set_density')}</div><div class="sd2">${t('set_density_d')}</div></div>${`<div class="dbarwrap"><span class="dbe">${t('den_loose')}</span><input id="densbar" type="range" min="1" max="10" step="1" value="${CFG.density}" data-act="densbar" class="dbar"><span class="dbe">${t('den_tight')}</span><span class="dbv" id="densval">${CFG.density}</span><button class="btn" data-act="densapply">${t('apply')}</button></div>`}</div></div>`;
 const data=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">↻</span><b>${t('set_data')}</b></div><div class="setrow"><div><div class="sk">${t('set_refresh')}</div><div class="sd2">${t('set_refresh_d')}</div></div>${seg('refresh',[['0',t('rf_off')],['5','5s'],['15','15s'],['30','30s']],CFG.refresh)}</div><div class="setrow"><div><div class="sk">${t('set_defnode')}</div><div class="sd2">${t('set_defnode_d')}</div></div>${seg('node',[['all',t('f_all')],['A',t('f_a')],['B',t('f_b')]],CFG.node)}</div><div class="setrow"><div><div class="sk">${t('set_manual')}</div><div class="sd2">${t('set_manual_d')}</div></div><button class="btn" data-act="do" data-v="refresh">${t('btn_now')}</button></div></div>`;
 const S=d.settings||{};
 const cfgseg=(k,opts,cur)=>`<div class="seg">${opts.map(([v,l])=>`<button data-act="cfg" data-k="${k}" data-v="${v}" class="${(''+cur)===(''+v)?'on':''}">${l}</button>`).join('')}</div>`;
 const srow=(ti,de,ctl)=>`<div class="setrow"><div><div class="sk">${ti}</div><div class="sd2">${de}</div></div>${ctl}</div>`;
 const ivOpts=[['3600','1h'],['21600','6h'],['86400','24h'],['0',t('rf_off')]];
 const mgmtScan=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🛰</span><b>${t('set_mgmt_scan')}</b><span class="pill ok" style="margin-left:auto">🖧 server</span></div>${srow(t('set_cve_iv'),t('set_cve_iv_d'),cfgseg('cve_interval_sec',ivOpts,S.cve_interval_sec))}${srow(t('set_cert_iv'),t('set_cert_iv_d'),cfgseg('cert_interval_sec',ivOpts,S.cert_interval_sec))}</div>`;
 const _nA=(d.nodes||[]).find(n=>n.label==='A')||{};const ovAll=S.cert_overrides||{};
 const certDevs=[...new Set(((_nA.cert||{}).findings||[]).map(f=>f.asset))];
 const scopes=[['',t('cp_global')]].concat(certDevs.map(x=>['lab-'+x,x]));
 const ov=ovAll[CERTSCOPE]||{};
 const certsel=(k,opts)=>{const dev=!!CERTSCOPE;const o=dev?[['',t('cp_inherit')+'('+S[k]+')']].concat(opts):opts;const cur=dev?(ov[k]!==undefined?(''+ov[k]):''):(''+S[k]);return `<div class="seg">${o.map(([v,l])=>`<button data-act="certpol" data-scope="${CERTSCOPE}" data-k="${k}" data-v="${v}" class="${cur===(''+v)?'on':''}">${l}</button>`).join('')}</div>`;};
 const devOv=(S.dev_overrides||{})[CERTSCOPE]||{};
 const devsel=(k,opts)=>{const dev=!!CERTSCOPE;const o=dev?[['',t('cp_inherit')+'('+S[k]+')']].concat(opts):opts;const cur=dev?(devOv[k]!==undefined?(''+devOv[k]):''):(''+S[k]);return `<div class="seg">${o.map(([v,l])=>`<button data-act="certpol" data-scope="${CERTSCOPE}" data-k="${k}" data-v="${v}" class="${cur===(''+v)?'on':''}">${l}</button>`).join('')}</div>`;};
 const scopeSeg=`<div class="seg">${scopes.map(([v,l])=>`<button data-act="certscope" data-v="${v}" class="${CERTSCOPE===v?'on':''}">${l}</button>`).join('')}</div>`;
 const effPol=CERTSCOPE?(ov.cert_cipher_policy!==undefined?ov.cert_cipher_policy:S.cert_cipher_policy):S.cert_cipher_policy;
 const FAMS=[['RC4','RC4'],['3DES','3DES'],['DES','DES'],['NULL','NULL'],['EXPORT','EXPORT'],['-MD5','MD5-MAC'],['@SHA1MAC','SHA1-MAC'],['anon','anon'],['IDEA','IDEA'],['SEED','SEED'],['CAMELLIA','CAMELLIA']];
 const custom=S.cert_cipher_custom||[];
 const famChips=effPol==='custom'?`<div class="setrow" style="display:block;border-top:0;padding-top:2px"><div class="sk">${t('cp_custom_fams')}</div><div class="sd2" style="margin:2px 0 9px">${t('cp_custom_d')}</div><div class="famrow">${FAMS.map(([v,l])=>`<button data-act="certfam" data-v="${v}" class="fam ${custom.includes(v)?'on':''}">${l}</button>`).join('')}</div></div>`:'';
 const mgmtThresh=`<div class="card threshcard"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--warn)">🎯</span><b>${t('set_mgmt_thresh')}</b><span style="margin-left:auto">${scopeSeg}</span></div><div class="thsub">${t('set_cert_thr')}</div>${srow(t('set_warn_days'),t('set_warn_days_d'),certsel('cert_expire_warn_days',[['7','7d'],['14','14d'],['30','30d'],['60','60d'],['90','90d']]))}${srow(t('set_rsa_min'),t('set_rsa_min_d'),certsel('cert_rsa_min',[['2048','2048'],['3072','3072'],['4096','4096']]))}${srow(t('set_sig'),t('set_sig_d'),certsel('cert_sig_min',[['sha1','SHA-1'],['sha256','SHA-256'],['sha384','SHA-384']]))}${srow(t('set_ec_min'),t('set_ec_min_d'),certsel('cert_ec_min',[['256','P-256'],['384','P-384'],['521','P-521']]))}${srow(t('set_cipher'),t('set_cipher_d'),certsel('cert_cipher_policy',[['lax',t('ci_lax')],['standard',t('ci_std')],['strict',t('ci_strict')],['custom',t('ci_custom')]]))}${famChips}<div class="thsub" style="border-top:1px solid var(--line);margin-top:15px;padding-top:13px">${t('set_dev_thr')}</div>${srow(t('set_cpu_hi'),t('set_cpu_hi_d'),devsel('dev_cpu_hi',[['75','75%'],['80','80%'],['85','85%'],['90','90%'],['95','95%']]))}${srow(t('set_ram_hi'),t('set_ram_hi_d'),devsel('dev_ram_hi',[['75','75%'],['80','80%'],['85','85%'],['90','90%'],['95','95%']]))}${srow(t('set_temp_hi'),t('set_temp_hi_d'),devsel('dev_temp_hi',[['70','70°C'],['75','75°C'],['80','80°C'],['85','85°C'],['90','90°C']]))}</div>`;
;
 const qEn=!!S.quiet_enabled;
 const hsel=(k,cur)=>`<select data-act="cfgsel" data-k="${k}" class="hsel">${Array.from({length:24},(_,h)=>`<option value="${h}" ${(+cur===h)?'selected':''}>${('0'+h).slice(-2)}:00</option>`).join('')}</select>`;
 const QDAYS=[['0',t('d_mon')],['1',t('d_tue')],['2',t('d_wed')],['3',t('d_thu')],['4',t('d_fri')],['5',t('d_sat')],['6',t('d_sun')]];
 const qd=S.quiet_days||[0,1,2,3,4,5,6];
 const quietRow=`<div class="setrow" style="display:block"><div style="display:flex;align-items:center;justify-content:space-between;gap:14px"><div><div class="sk">${t('set_quiet')}</div><div class="sd2">${t('set_quiet_d')}</div></div>${cfgseg('quiet_enabled',[['true',t('on_')],['false',t('off_')]],''+S.quiet_enabled)}</div>${qEn?`<div class="qcfg"><span class="qlb">${t('q_from')}</span>${hsel('quiet_start',S.quiet_start)}<span class="qlb">${t('q_to')}</span>${hsel('quiet_end',S.quiet_end)}</div><div class="qdays">${QDAYS.map(([v,l])=>`<button data-act="qday" data-v="${v}" class="dchip ${qd.includes(+v)?'on':''}">${l}</button>`).join('')}</div>`:''}</div>`;
 const mgmtNotify=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">🔔</span><b>${t('set_mgmt_notify')}</b></div>${srow(t('set_escalate'),t('set_escalate_d'),cfgseg('auto_escalate',[['true',t('on_')],['false',t('off_')]],''+S.auto_escalate))}${quietRow}${srow(t('set_channels'),t('set_channels_d'),cfgseg('notify_channels',[['jira,dashboard',t('ch_base')],['jira,email,dashboard',t('ch_email')],['jira,telegram,dashboard',t('ch_tg')],['jira,email,telegram,dashboard',t('ch_all')],['dashboard',t('ch_dash')]],S.notify_channels))}</div>`;
 const R=((d.settings||{}).recipients)||[];
 const rrows=R.length?R.map(r=>`<div class="setrow"><div><div class="sk">${esc(r.name||'')}</div><div class="sd2">${r.telegram?('TG '+esc(r.telegram)):''}${(r.telegram&&r.email)?' · ':''}${esc(r.email||'')}</div></div><div style="display:flex;gap:8px"><button class="btn" data-act="rectest" data-nm="${esc(r.name||'')}" data-tg="${esc(r.telegram||'')}" data-em="${esc(r.email||'')}">${t('rec_test')}</button><button class="btn" data-act="recdel" data-v="${esc(r.email||r.name||'')}">${t('rec_del')}</button></div></div>`).join(''):`<div class="setrow"><div class="sd2">${t('rec_none')}</div></div>`;
 const radd=`<div class="recadd"><input id="rc_name" class="rcin" placeholder="${t('rec_name')}"><input id="rc_tg" class="rcin" placeholder="${t('rec_tg')}"><input id="rc_email" class="rcin" placeholder="${t('rec_email')}"><button class="btn" data-act="recadd">${t('rec_add')}</button></div>`;
 const mgmtRec=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">👥</span><b>${t('set_mgmt_rec')}</b><span class="mut" style="margin-left:auto;font-weight:400;font-size:11px">${t('rec_hint')}</span></div>${rrows}${radd}</div>`;
 const ME=d._me||{},ACL=d._acl;let acl='';
 if(ACL){const users=ACL.users||[],au=ACL.auth||{};
  const urows=users.map(u=>`<div class="setrow"><div><div class="sk">${esc(u.email)}${u.email===ME.email?` <small class="mut">(${t('acl_you')})</small>`:''}</div><div class="sd2">${u.role} · ${u.created||''}</div></div><div style="display:flex;gap:6px;flex-wrap:wrap"><button class="btn" data-act="usrrole" data-em="${esc(u.email)}" data-role="${u.role==='admin'?'viewer':'admin'}">→${u.role==='admin'?'viewer':'admin'}</button><button class="btn" data-act="usrpw" data-em="${esc(u.email)}">${t('acl_pw')}</button><button class="btn" data-act="usrdel" data-em="${esc(u.email)}">${t('rec_del')}</button></div></div>`).join('');
  const adduser=`<div class="recadd"><input id="ua_em" class="rcin" placeholder="email"><input id="ua_pw" class="rcin" type="password" placeholder="${t('acl_pw')}"><select id="ua_role" class="hsel"><option value="viewer">viewer</option><option value="admin">admin</option></select><button class="btn" data-act="usradd">${t('rec_add')}</button></div>`;
  const accCard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">👥</span><b>${t('acl_accounts')}</b><span class="mut" style="margin-left:auto;font-weight:400;font-size:11px">${t('acl_online')} ${au.sessions||0}</span></div>${urows}${adduser}</div>`;
  const aseg=(k,opts,cur)=>`<div class="seg">${opts.map(([v,l])=>`<button data-act="acfg" data-k="${k}" data-v="${v}" class="${(''+cur)===(''+v)?'on':''}">${l}</button>`).join('')}</div>`;
  const polCard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🔐</span><b>${t('acl_policy')}</b></div><div class="setrow"><div><div class="sk">${t('acl_maxs')}</div><div class="sd2">${t('acl_maxs_d')}</div></div>${aseg('max_sessions',[['1','1'],['3','3'],['5','5'],['10','10'],['0','∞']],au.max_sessions)}</div><div class="setrow"><div><div class="sk">${t('acl_timeout')}</div><div class="sd2">${t('acl_timeout_d')}</div></div>${aseg('timeout_min',[['15','15m'],['30','30m'],['60','60m'],['240','4h'],['480','8h'],['0','∞']],au.timeout_min)}</div><div class="setrow" style="display:block"><div class="sk">${t('acl_ipwl')}</div><div class="sd2" style="margin:2px 0 7px">${t('acl_ipwl_d')}</div><div class="recadd"><input id="acl_ip" class="rcin" placeholder="10.0.0.0/24, 192.168.1.5" value="${(au.ip_whitelist||[]).join(', ')}"><button class="btn" data-act="acfgip">${t('apply')}</button></div></div></div>`;
  const aud=d._audit;const audCard=aud?`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🔏</span><b>${t('aud_title')}</b><span class="pill ${aud.chain&&aud.chain.ok?'ok':'bad'}" style="margin-left:auto">${aud.chain&&aud.chain.ok?('🔒 '+t('aud_intact')+' · '+aud.chain.count):('⚠ '+t('aud_broken')+(aud.chain&&aud.chain.broken?(' #'+aud.chain.broken):''))}</span></div><div class="sd2" style="margin-bottom:8px;line-height:1.6">${t('aud_d')}</div>${(aud.recent||[]).map(e=>`<div class="setrow" style="padding:7px 0"><div style="min-width:0"><div class="sk" style="font-size:12.5px">${e.ok?'':'⚠ '}${esc(e.action)} ${e.detail?`<small class="mut">${esc(e.detail)}</small>`:''}</div><div class="sd2">${esc(e.actor)} · ${esc(e.ip||'')} · ${esc(e.ts||'')}</div></div><span class="mut mono" style="font-size:10px;flex:0 0 auto">#${e.seq}</span></div>`).join('')||'<div class="mut">—</div>'}<button class="btn" data-act="auditverify" style="margin-top:10px">${t('aud_verify')}</button></div>`:'';
  acl=`<div class="sec">${t('acl_section')}</div>${accCard}${polCard}${audCard}`;}
 const about=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">ⓘ</span><b>${t('set_about')}</b></div><div class="kv"><span class="k">${t('ab_fmt')}</span><span class="v">OCSF · engine:opa / l7</span></div><div class="kv"><span class="k">${t('ab_cred')}</span><span class="v">${t('ab_cred_v')}</span></div><div class="kv"><span class="k">${t('ab_nature')}</span><span class="v">${t('ab_nature_v')}</span></div><div style="margin-top:13px"><div class="sk">${t('ab_keys')}</div><div class="sd2" style="line-height:2.2;margin-top:4px"><span class="chip">1–9</span> ${t('ab_k_tabs')}　<span class="chip">r</span> ${t('ab_k_r')}　<span class="chip">d</span> ${t('ab_k_d')}　<span class="chip">f</span> ${t('ab_k_f')}</div></div></div>`;
 return `<div style="max-width:720px;display:flex;flex-direction:column;gap:16px">${appearance}${data}${mgmtScan}${mgmtThresh}${mgmtNotify}${mgmtRec}${acl}${about}</div>`}

function vTimeline(d){const items=d.timeline||[];
 const types=[['all',t('tl_all')],['gov',t('tl_gov')],['device',t('tl_dev')],['jira',t('tl_jira')],['audit',t('tl_audit')],['guard',t('tl_guard')]];
 const seg=`<div class="seg">${types.map(([v,l])=>`<button data-act="tlf" data-v="${v}" class="${TLF===v?'on':''}">${l}</button>`).join('')}</div>`;
 let its=items;if(TLF!=='all')its=its.filter(x=>x.type===TLF);
 const ic={gov:'⚡',device:'🖧',jira:'🎫',audit:'🔧',guard:'🛡'};
 const tone=x=>x.tone==='bad'?'d':(x.tone==='ok'?'a':(x.tone==='warn'?'w':''));
 const rows=its.map(x=>{const bb=L(x,'b')||x.b||'';return `<div class="tlrow"><span class="tlt">${x.tm||'—'}</span><span class="tlty ${x.type}">${ic[x.type]||'•'} ${t('tl_'+x.type)}</span><span class="tla ${tone(x)}">${x.a||''}</span><span class="tlb" title="${bb.replace(/"/g,'&quot;')}">${bb}</span></div>`}).join('')||`<div class="mut">${t('tl_none')}</div>`;
 const counts=['gov','device','jira','audit','guard'].map(k=>{const n=items.filter(x=>x.type===k).length;return n?`<span class="chip">${ic[k]} ${t('tl_'+k)} ${n}</span>`:''}).filter(Boolean).join(' ');
 return `<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">◷</span>${t('t_timeline')} <span class="mut" style="font-weight:400;margin-left:2px">${items.length}</span><span style="margin-left:auto">${seg}</span></div><div style="margin-bottom:6px">${counts}</div>${rows}</div>`}
function vStack(d){const cs=d.containers||[];const up=c=>/^Up\b/.test(c.status||'');
 const upn=cs.filter(up).length,tot=cs.length;
 const svcrow=(key,lbl,ok,okt)=>`<div class="kv clickable" data-drawer="svc:${key}"><span class="k">${lbl}</span><span class="v">${pill(ok,okt)} ›</span></div>`;
 const svc=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">✦</span>${t('stk_services')}</div>${svcrow('gateway',t('stk_svc_gateway'),d.gateway,d.gateway?t('online'):t('offline'))}${svcrow('hermes',t('stk_svc_hermes'),d.hermes_api,d.hermes_api?t('online'):t('offline'))}${svcrow('telegram',t('stk_svc_tg'),d.telegram_recent>0,d.telegram_recent>0?t('alive'):t('stopped'))}</div>`;
 const cls=n=>{n=(n||'').toLowerCase();if(/nemoclaw|gateway|openshell|opa/.test(n))return 'core';if(/openclaw|assistant|hermes/.test(n))return 'agent';return 'infra'};
 const crow=c=>{const u=up(c);return `<div class="kv clickable" data-drawer="ctr:${c.name}"><span class="k mono">${sdot(u?'ok':'ALERT')}${c.name}</span><span class="v ${u?'ok':'red'}" style="font-weight:400">${c.status||'—'} ›</span></div>`};
 const G={core:[],agent:[],infra:[]};cs.forEach(c=>G[cls(c.name)].push(crow(c)));
 const grp=(title,rows)=>rows.length?`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">▦</span>${title}<span style="margin-left:auto">${rows.length}</span></div>${rows.join('')}</div>`:'';
 const banner=`<div class="bn ${upn<tot?'bad':'ok'}">${upn<tot?('⚠︎ '+(tot-upn)+' '+t('stk_stopped')):t('stk_healthy')} · ${upn}/${tot}</div>`;
 const cont=cs.length?(grp(t('stk_grp_core'),G.core)+grp(t('stk_grp_agent'),G.agent)+grp(t('stk_grp_infra'),G.infra)):`<div class="card mut">${t('stk_none')}</div>`;
 // ── 系統資訊(nemoclaw / openshell)──
 const si=d.sysinfo||{},inf=si.inference||{},gw=si.gateway||{};
 const infcard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:${inf.reachable?'var(--ok)':'var(--danger)'}">🧠</span>${t('sys_inf')}</div><div class="kv"><span class="k">${t('sys_inf_model')}</span><span class="v mono">${esc(inf.model||'—')} <span class="mut">(${esc(inf.provider||'—')})</span></span></div><div class="kv"><span class="k">inference.local</span><span class="v">${inf.reachable?('<span class="ok">🟢 '+t('sys_reach')+'</span>'):('<span class="red">🔴 '+t('sys_unreach')+'</span>')} <span class="mut">HTTP ${esc(''+(inf.http||'—'))}</span></span></div>${(d._me&&d._me.role==='admin')?`<div class="kv"><span class="k">${t('sys_inf_set')}</span><span class="v"><button class="btn" data-act="infset">${t('sys_inf_set_btn')}</button></span></div>`:''}</div>`;
 const fwd=(si.forwards||[]).map(f=>`<div class="kv"><span class="k mono">${esc(f.sb)}</span><span class="v mono" style="font-weight:400">${esc(f.bind)}:${esc(f.port)} · ${esc(f.status)}</span></div>`).join('')||`<div class="mut">—</div>`;
 const gwcard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">▣</span>${t('sys_gw')}</div><div class="kv"><span class="k">${t('sys_gw_status')}</span><span class="v">${pill(/connected/i.test(gw.status||''),esc(gw.status||'—'))} <span class="mut">v${esc(gw.version||'?')}</span></span></div><div class="kv"><span class="k">${t('svc_endpoint')}</span><span class="v mono" style="font-weight:400">${esc(gw.server||'—')}</span></div><div class="dsec" style="margin:11px 0 5px">${t('sys_fwd')}</div>${fwd}</div>`;
 const creds=(si.credentials||[]).map(c=>`<span class="tag">${esc(c)}</span>`).join('')||'—';
 const chans=(si.channels||[]).map(c=>`<span class="tag">${esc(c)}</span>${isadm?` <button class="btn" data-act="sysdo" data-do="chanstop" data-chan="${esc(c)}" data-confirm="${t('sys_chan_stop_c')}">${t('sys_chan_stop')}</button> <button class="btn" data-act="sysdo" data-do="chanstart" data-chan="${esc(c)}" data-confirm="${t('sys_chan_start_c')}">${t('sys_chan_start')}</button>`:''}`).join(' ')||'—';
 const metacard=`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">🔑</span>${t('sys_meta')}</div><div class="kv"><span class="k">${t('sys_creds')}</span><span class="v">${creds}</span></div><div class="kv"><span class="k">${t('sys_chan')}</span><span class="v">${chans}</span></div></div>`;
 const isadm=(d._me&&d._me.role==='admin');
 const agents=[['hermes-demo','Hermes'],['my-assistant','OpenClaw A'],['openclaw-2','OpenClaw B']];
 const toolrows=agents.map(a=>`<div class="kv"><span class="k">${a[1]}</span><span class="v"><button class="btn" data-act="sysdo" data-do="doctor" data-sb="${a[0]}">${t('sys_doctor')}</button> <button class="btn" data-act="sysdo" data-do="logs" data-sb="${a[0]}">${t('sys_logs')}</button> <button class="btn" data-act="sysdo" data-do="recover" data-sb="${a[0]}" data-confirm="${t('sys_recover_c')}">${t('sys_recover')}</button> <button class="btn" data-act="rebuild" data-sb="${a[0]}">${t('sys_rebuild')}</button></span></div>`).join('');
 const toolcard=isadm?`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">🩺</span>${t('sys_tools')}</div><div class="sd2" style="margin-bottom:6px;line-height:1.6">${t('sys_tools_d')}</div>${toolrows}<div class="kv"><span class="k">${t('sys_global')}</span><span class="v"><button class="btn" data-act="sysdo" data-do="gwhealth">${t('sys_gwhealth')}</button> <button class="btn" data-act="sysdo" data-do="stale">${t('sys_stale')}</button> <button class="btn" data-act="sysdo" data-do="gsettings">${t('sys_gsettings')}</button> <button class="btn" data-act="sysdo" data-do="gc">${t('sys_gc')}</button> <button class="btn" data-act="sysdo" data-do="gcrun" data-confirm="${t('sys_gc_c')}">${t('sys_gcrun')}</button></span></div></div>`:'';
 const maintcard=isadm?`<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--warn)">🛠</span>${t('sys_maint')}</div><div class="sd2" style="margin-bottom:6px;line-height:1.6">${t('sys_maint_d')}</div><div class="kv"><span class="k">${t('sys_global')}</span><span class="v"><button class="btn" data-act="sysdo" data-do="backupall" data-confirm="${t('sys_backup_c')}">${t('sys_backup')}</button> <button class="btn" data-act="sysdo" data-do="upgrade" data-confirm="${t('sys_upgrade_c')}">${t('sys_upgrade')}</button> <button class="btn" data-act="sysdo" data-do="debug">${t('sys_debug')}</button></span></div>${agents.map(a=>`<div class="kv"><span class="k">${a[1]} · hosts</span><span class="v"><button class="btn" data-act="sysdo" data-do="hostslist" data-sb="${a[0]}">${t('sys_hosts_list')}</button> <button class="btn" data-act="syscmd" data-do="hostsadd" data-sb="${a[0]}" data-prompts="sys_hosts_name_p|sys_hosts_ip_p">${t('sys_hosts_add')}</button> <button class="btn" data-act="syscmd" data-do="hostsrm" data-sb="${a[0]}" data-prompts="sys_hosts_name_p" data-confirm="${t('sys_hosts_rm_c')}">${t('sys_hosts_rm')}</button></span></div>`).join('')}<div class="kv"><span class="k">${t('sys_fwd')}</span><span class="v"><button class="btn" data-act="syscmd" data-do="fwdstart" data-prompts="sys_fwd_port_p|sys_fwd_sb_p">${t('sys_fwd_start')}</button> <button class="btn" data-act="syscmd" data-do="fwdstop" data-prompts="sys_fwd_port_p|sys_fwd_sb_p" data-confirm="${t('sys_fwd_stop_c')}">${t('sys_fwd_stop')}</button></span></div></div>`:'';
 return `${banner}<div class="sec">${t('stk_services')}</div>${svc}<div class="sec">${t('sys_section')}</div><div style="display:flex;flex-direction:column;gap:16px">${infcard}${gwcard}${metacard}${toolcard}${maintcard}</div><div class="sec">${t('stk_containers')} · ${upn}/${tot} ${t('stk_running')}</div><div style="display:flex;flex-direction:column;gap:16px">${cont}</div>`}
function sysShow(title,out){DRW='sys';el('drwTitle').textContent=title;el('drwSub').textContent='nemoclaw / openshell';el('drwBody').innerHTML='<div class="card"><pre class="mono" style="white-space:pre-wrap;word-break:break-word;font-size:11px;color:var(--tx2);max-height:72vh;overflow:auto;margin:0">'+esc(out)+'</pre></div>';el('ovl').classList.add('on');el('drw').classList.add('on')}

/* ---- EBG19P device-detail slide-over(點龍蝦受管設備看細節)---- */
function ebgDrawerHTML(d){
 const info=d.ebg19p_info||{};
 const nA=(d.nodes||[]).find(n=>n.label==='A')||{};
 const mon=(nA.monitor||[]).find(x=>(x.asset||'').includes('ebg19p'))||{};
 const A=nA.assets,T=nA.traffic,L=nA.devlog;
 const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono">${v||'—'}</span></div>`;
 let h=`<div class="dsec">${t('drw_identity')}</div><div class="card">`
   +kv(t('di_model'),info['device.model'])+kv(t('di_fw'),info['device.firmware'])+kv(t('di_mac'),info['device.mac'])
   +kv(t('di_wan'),info['wan.proto'])+kv(t('di_ssid'),info['wifi.ssid'])
   +kv(t('di_remote'),info['webui.wan_access']==='true'?'WAN':t('offline'))+`</div>`;
 const reg=mon.regressions||[],pend=mon.pending||[];
 h+=`<div class="dsec">${t('drw_compliance')}</div><div class="card"><div class="kv"><span class="k">status</span><span class="v">${(''+mon.status).includes('ALERT')?`<span class="red">${alertLbl(mon.status)}</span>`:`<span class="ok">ok</span>`}</span></div>`
   +(reg.length?`<div class="devd"><span class="dl red">${t('reg')} ${reg.length}</span>${reg.map(r=>`<span class="chip">${r}</span>`).join('')}</div>`:'')
   +(pend.length?`<div class="devd"><span class="dl warn">${t('pend')} ${pend.length}</span>${pend.map(r=>`<span class="chip">${r}</span>`).join('')}</div>`:'')
   +((!reg.length&&!pend.length)?`<div class="mut" style="padding-top:6px">${t('drw_clean')}</div>`:'')+`</div>`;
 if(A){h+=`<div class="dsec">${t('assets_title')} · ${A.count}${A.unknown?` · <span class="red">${A.unknown} ${t('assets_unknown')}</span>`:''}</div><div class="card">`
   +((A.list||[]).map(x=>`<div class="ast"><span class="adot ${x.known?'g':'r'}"></span><span>${x.name||'—'}</span><span class="am">${x.mac}</span><span class="ai">${x.ip}</span><span class="ab ${x.known?'k':'u'}">${x.known?t('asset_known'):t('assets_unknown')}</span></div>`).join('')||`<div class="mut">${t('assets_none')}</div>`)+`</div>`}
 if(T){h+=`<div class="dsec">${t('tr_title')}${T.anomaly?` · <span class="red">${t('tr_anom')}</span>`:''}</div><div class="card"><div class="split" style="gap:20px;align-items:center"><div style="flex:0 0 auto">${spark(T.series,T.anomaly?CV.danger:CV.accent)}</div><div class="stat" style="margin-top:0;flex:1"><div class="s"><b class="${T.anomaly?'red':''}">${T.latest}</b><span>${t('tr_now')} Mbps</span></div><div class="s"><b>${T.avg}</b><span>${t('tr_avg')}</span></div><div class="s"><b>${T.peak}</b><span>${t('tr_peak')}</span></div></div></div></div>`}
 if(L){const cats=Object.entries(L.by_category||{}).sort((x,y)=>y[1]-x[1]),mx=Math.max(1,...cats.map(e=>e[1]));
  const wn=(L.by_severity||{}).warn||0,hi=(L.by_severity||{}).high||0;
  h+=`<div class="dsec">${t('dl_title')} · ${L.total} ${t('dl_total')}${(wn+hi)?` · ${wn+hi} ${t('dl_sec')}`:''}</div><div class="card">`
   +cats.map(([k,v])=>`<div class="bar"><span class="bl">${k}</span><div class="bt"><div class="bf" style="width:${Math.max(6,v/mx*100).toFixed(0)}%"></div></div><span class="bv">${v}</span></div>`).join('')
   +((L.security_events||[]).slice(-5).map(e=>`<div class="ev"><span class="t">${(e.t||'').slice(0,12)}</span><span class="vb" style="color:var(--warn);width:auto;flex:0 0 auto">${e.cat}</span><span class="tg" style="max-width:58%" title="${(e.msg||'').replace(/"/g,'')}">${e.msg||''}</span></div>`).join(''))+`</div>`}
 h+=`<div class="dsec">${t('act_title')}</div><div class="card"><div class="acts">`
   +`<button class="btn" data-dev="sync">↻ ${t('act_sync')}</button>`
   +`<button class="btn" data-dev="harden">🛡 ${t('act_harden')}</button>`
   +`<button class="btn" data-dev="restart">⟳ ${t('act_restart')}</button>`
   +`<button class="btn" data-dev="block">⛔ ${t('act_block')}</button></div>`
   +`<div class="mut" style="font-size:11px;margin-top:10px;line-height:1.6">🔒 ${t('drw_managed')} · ${t('ab_cred_v')} · ${t('pol_ro')==='read-only'?'host executor · audited':'host 端執行 · 全程稽核'}</div></div>`;
 const au=d.ebg19p_audit||[];
 h+=`<div class="dsec">${t('audit_title')}</div><div class="card">`
   +(au.length?au.map(a=>`<div class="ev"><span class="t">${(a.ts||'').slice(5,16)}</span><span class="vb ${a.result==='ok'?'a':(a.result==='failed'?'d':'')}" style="width:auto;flex:0 0 auto">${a.action}</span><span class="tg" style="max-width:56%">${a.detail||''}</span></div>`).join(''):`<div class="mut">${t('audit_none')}</div>`)+`</div>`;
 return h}
function certDrawerHTML(d,asset){
 const nA=(d.nodes||[]).find(n=>n.label==='A')||{};
 const fs=((nA.cert||{}).findings||[]).filter(f=>f.asset===asset);
 const issL={untrusted:t('ce_untrusted'),weak_algorithm:t('ce_weakalg'),expired:t('ce_expired'),expiring:t('ce_expiring'),weak_protocol:t('ce_weakproto'),weak_cipher:t('ce_weakcipher'),weak_ssh:t('ce_weakssh')};
 const hi=fs.filter(f=>f.severity==='High').length,me=fs.filter(f=>f.severity!=='High').length;
 // 依服務分組
 const bySvc={};fs.forEach(f=>{(bySvc[f.service]=bySvc[f.service]||[]).push(f)});
 let h=`<div class="dsec">${t('cert_title')}</div><div class="card"><div class="kv"><span class="k">${t('th_asset')}</span><span class="v mono">${asset}</span></div><div class="kv"><span class="k">${t('cert_issue')}</span><span class="v">${hi?`<span class="red">${hi} ${t('cert_high')}</span>`:''}${me?`${hi?' · ':''}<span style="color:var(--warn)">${me} ${t('cert_med')}</span>`:''}${(!hi&&!me)?t('cert_clean'):''}</span></div></div>`;
 for(const svc in bySvc){
  h+=`<div class="dsec">${svc}</div><div class="card">`+bySvc[svc].map(f=>`<div class="cfind" data-fid="${f.issue}|${f.service}"><div class="cfh"><span class="sev ${f.severity==='High'?'high':'med'}">${issL[f.issue]||f.issue}</span><span class="cfsev ${f.severity==='High'?'r':'w'}">${f.severity}</span></div><div class="cfd">${esc(L(f,'detail'))}</div>${(f.state&&f.state.length)?`<div class="cfst"><div class="cfsth">${t('cur_state')}</div>${f.state.map(p=>`<div class="cfstr"><span>${p[0]}</span><b class="mono">${p[1]||'—'}</b></div>`).join('')}</div>`:''}${(L(f,'fix'))?`<div class="cffix">💡 ${esc(L(f,'fix'))}</div>`:''}</div>`).join('')+`</div>`;
 }
 if(!fs.length)h+=`<div class="card mut">${t('cert_clean')}</div>`;
 return h;}
function esc(x){return (''+x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;')}
function sastDrawerHTML(d,idx){const nB=(d.nodes||[]).find(n=>n.label==='B')||{};const src=nB.source||{};const f=(src.sast_list||[])[idx]||{};
 const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="word-break:break-all;text-align:right">${v||'—'}</span></div>`;
 const lnk=(u,txt)=>`<a href="${esc(u)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;word-break:break-all">${esc(txt)} ↗</a>`;
 const pl=(f.patch||'').split('\n').map(l=>{const c=(l[0]==='+'&&l.slice(0,3)!=='+++')?'pl-a':((l[0]==='-'&&l.slice(0,3)!=='---')?'pl-d':(l.slice(0,2)==='@@'?'pl-h':''));return `<div class="pl ${c}">${esc(l)||'&nbsp;'}</div>`}).join('');
 let h=`<div class="dsec">${t('src_sast')}</div><div class="card">`+kv('CWE',f.cwe)+kv(t('th_file'),f.upstream_path||f.file)+kv(t('th_line'),f.line);
 if(f.url)h+=`<div class="kv"><span class="k">${t('src_view')}</span><span class="v" style="text-align:right">${lnk(f.url,'github')}</span></div>`;
 if(f.violates_design){const dz=(src.design||[]).find(x=>x.req===f.violates_design)||{};
   h+=`<div class="kv" style="display:block"><span class="k">${t('src_design')}</span><div class="v" style="margin-top:4px"><span style="color:var(--danger);font-weight:600">${esc(f.violates_design)}</span>${(L(dz,'desc'))?` — ${esc(L(dz,'desc'))}`:''}</div>${(L(dz,'evidence'))?`<div class="mut" style="font-size:11.5px;margin-top:3px">${t('src_evid')}:${esc(L(dz,'evidence'))}</div>`:''}</div>`;}
 h+=`<div class="kv"><span class="k">${t('sast_verified')}</span><span class="v">${f.patch_verified?`<span class="pill ok">✓ ${t('sast_ok')}</span>`:'—'}</span></div></div>`;
 if(f.code)h+=`<div class="dsec">${t('sast_code')}</div><div class="card"><div class="codeblk">${esc(f.code)}</div></div>`;
 if(f.patch)h+=`<div class="dsec">${t('sast_patch')}${f.patch_kind==='line-suggestion'?` <span class="mut" style="font-weight:400;font-size:11px">· ${t('patch_sugg')}</span>`:''}</div><div class="card"><div class="codeblk">${pl}</div></div>`;
 if(f.remediation){const r=f.remediation;
   h+=`<div class="dsec">${t('sast_fix')}</div><div class="card"><div class="kv" style="display:block"><span class="k">${t('fix_risk')}</span><div class="v" style="margin-top:3px;line-height:1.5">${esc(L(r,'risk'))}</div></div><div class="kv" style="display:block;margin-top:9px"><span class="k">${t('fix_how')}</span><div class="v" style="margin-top:3px;line-height:1.5">${esc(L(r,'fix'))}</div></div>${r.ref?`<div class="kv" style="margin-top:9px"><span class="k">CWE</span><span class="v" style="text-align:right">${lnk(r.ref,'mitre.org')}</span></div>`:''}</div>`;}
 return h;}
function ctrDrawerHTML(d,name){const c=(d.containers||[]).find(x=>x.name===name)||{};const u=/^Up\b/.test(c.status||'');
 const nl=(name||'').toLowerCase();const grp=/nemoclaw|gateway|openshell|opa/.test(nl)?t('stk_grp_core'):(/openclaw|assistant|hermes/.test(nl)?t('stk_grp_agent'):t('stk_grp_infra'));
 const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="word-break:break-all;text-align:right">${esc(v==null||v===''?'—':v)}</span></div>`;
 return `<div class="dsec">${t('ctr_detail')}</div><div class="card"><div class="kv"><span class="k">${t('ctr_state')}</span><span class="v">${u?'<span class="pill ok">'+t('online')+'</span>':'<span class="pill bad">'+t('offline')+'</span>'}</span></div>`
  +kv(t('ctr_name'),c.full||name)+kv(t('ctr_status'),c.status)+kv(t('ctr_group'),grp)+kv(t('ctr_image'),c.image)+kv(t('ctr_ports'),c.ports)+kv(t('ctr_uptime'),c.uptime)+kv('ID',c.id)+`</div>`;}
function svcDrawerHTML(d,key){
 const M={gateway:[t('stk_svc_gateway'),'http://127.0.0.1:18080',d.gateway,t('svc_gateway_d'),''],
          hermes:[t('stk_svc_hermes'),'http://127.0.0.1:8642/v1',d.hermes_api,t('svc_hermes_d'),''],
          telegram:[t('stk_svc_tg'),'api.telegram.org (getUpdates)',d.telegram_recent>0,t('svc_tg_d'),'getUpdates ×'+(d.telegram_recent||0)]};
 const m=M[key]||[key,'—',false,'',''];
 const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="word-break:break-all;text-align:right">${v||'—'}</span></div>`;
 return `<div class="dsec">${t('svc_detail')}</div><div class="card"><div class="kv"><span class="k">${t('ctr_state')}</span><span class="v">${m[2]?'<span class="pill ok">'+t('online')+'</span>':'<span class="pill bad">'+t('offline')+'</span>'}</span></div>`
  +kv(t('svc_endpoint'),m[1])+(m[4]?kv(t('tr_actions'),m[4]):'')+`</div><div class="dsec">${t('svc_about')}</div><div class="card"><div class="mut" style="line-height:1.65">${m[3]}</div></div>`;}
function flash(t2){if(t2){t2.classList.remove('flash');void t2.offsetWidth;t2.classList.add('flash')}}
function hermesDrawerHTML(d){const p=d.policy||{};
 const hsnap=((d.snapshots_by_agent||[]).find(a=>a.sb==='hermes-demo')||{}).items||[];
 const ctr=(d.containers||[]).find(c=>/hermes/.test(c.name||''))||{};
 const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="text-align:right;word-break:break-all">${v==null||v===''?'—':v}</span></div>`;
 return `<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--ok)">✦</span><b>${t('comp_hermes')}</b> · ${t('herm_role')}</div><div class="mut" style="line-height:1.7">${t('herm_about')}</div></div>
  <div class="dsec">${t('herm_status')}</div><div class="card">${kv('API :8642',d.hermes_api?('🟢 '+t('online')):('🔴 '+t('offline')))}${kv(t('herm_tg'),(d.telegram_recent>0?('🟢 '+t('alive')):('🔴 '+t('stopped')))+(d.telegram_recent?(' · ×'+d.telegram_recent):''))}${kv(t('herm_mail'),'GreenMail :3993')}${kv(t('ctr_status'),esc(ctr.status||'—'))}</div>
  <div class="dsec">${t('herm_sandbox')}</div><div class="card">${kv('sandbox','hermes-demo')}${kv(t('pol_title'),'v'+(p.version||'?')+(p.hash?(' · '+p.hash):''))}${kv(t('snap_title'),hsnap.length+' '+t('snap_unit'))}${kv(t('a_bridge'),(d.bridge_ips||[]).join(', ')||'—')}</div>
  <div class="dsec">${t('herm_flow')}</div><div class="card"><div class="mut" style="line-height:1.8">${t('herm_flow_d')}</div></div>`}
function nemoDrawerHTML(d){const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="text-align:right;word-break:break-all">${v==null||v===''?'—':v}</span></div>`;
 const ag=(d.snapshots_by_agent||[]),tot=(d.snapshots||[]).length;
 const rows=ag.map(a=>{const it=a.items||[];return kv(esc(a.label)+' · '+esc(a.sb), it.length+' '+t('snap_unit')+(it.length?(' · '+t('c_restore')+' '+esc(it[it.length-1].ver)):''))}).join('');
 return `<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--purple)">◆</span><b>${t('comp_nemo')}</b> · ${t('nemo_role')}</div><div class="mut" style="line-height:1.7">${t('nemo_about')}</div></div>
  <div class="dsec">${t('nemo_snaps')}</div><div class="card">${kv(t('snap_title')+' · '+t('a_total'),tot)}${rows}</div>
  <div class="dsec">${t('nemo_manages')}</div><div class="card">${kv('Hermes','hermes-demo')}${kv('OpenClaw A','my-assistant')}${kv('OpenClaw B','openclaw-2')}</div>
  <div class="dsec">${t('nemo_recovery')}</div><div class="card"><div class="mut" style="line-height:1.8">${t('nemo_recovery_d')}</div></div>`}
function openshellDrawerHTML(d){const kv=(k,v)=>`<div class="kv"><span class="k">${k}</span><span class="v mono" style="text-align:right;word-break:break-all">${v==null||v===''?'—':v}</span></div>`;
 const g=d.governance||{},p=d.policy||{};const allowed=Object.values(g.allowed||{}).reduce((s,v)=>s+v,0);
 return `<div class="card"><div class="ct"><span class="ico" style="background:var(--card2);color:var(--accent)">▣</span><b>${t('comp_shell')}</b> · ${t('osh_role')}</div><div class="mut" style="line-height:1.7">${t('osh_about')}</div></div>
  <div class="dsec">${t('herm_status')}</div><div class="card">${kv('gateway :18080',d.gateway?('🟢 '+t('online')):('🔴 '+t('offline')))}${kv(t('sk_allow2'),allowed)}${kv(t('sk_denied'),'<span class="'+(g.denied?'red':'')+'">'+(g.denied||0)+'</span>')}${g.denied_benign?kv(t('sk_denied')+' ('+t('benign')+')',g.denied_benign):''}</div>
  <div class="dsec">${t('pol_title')}</div><div class="card">${kv('sandbox',esc(p.sandbox||'hermes-demo'))}${kv('version','v'+(p.version||'?'))}${kv(t('pol_allowlist'),(p.networks||[]).length+' '+t('osh_endpoints'))}${kv(t('a_bridge'),(d.bridge_ips||[]).join(', ')||'—')}</div>
  <div class="dsec">${t('osh_enf')}</div><div class="card"><div class="mut" style="line-height:1.8">${t('osh_enf_d')}</div></div>`}
function openDrawer(which,focus){const d=LAST;if(!d)return;which=which||'ebg';DRW=which;
 if(which.indexOf('cert:')===0){const asset=which.slice(5);el('drwTitle').textContent=asset;el('drwSub').textContent=t('cert_title');el('drwBody').innerHTML=certDrawerHTML(d,asset);}
 else if(which.indexOf('sast:')===0){el('drwTitle').textContent='SAST';el('drwSub').textContent=t('src_sast');el('drwBody').innerHTML=sastDrawerHTML(d,+which.slice(5));} else if(which.indexOf('ctr:')===0){const nm=which.slice(4);el('drwTitle').textContent=nm;el('drwSub').textContent=t('ctr_detail');el('drwBody').innerHTML=ctrDrawerHTML(d,nm);} else if(which.indexOf('svc:')===0){el('drwTitle').textContent=t('stk_services');el('drwSub').textContent=t('svc_detail');el('drwBody').innerHTML=svcDrawerHTML(d,which.slice(4));} else if(which==='hermes'){el('drwTitle').textContent='Hermes';el('drwSub').textContent=t('comp_hermes');el('drwBody').innerHTML=hermesDrawerHTML(d);} else if(which==='nemo'){el('drwTitle').textContent='NemoClaw';el('drwSub').textContent=t('comp_nemo');el('drwBody').innerHTML=nemoDrawerHTML(d);} else if(which==='openshell'){el('drwTitle').textContent='OpenShell';el('drwSub').textContent=t('comp_shell');el('drwBody').innerHTML=openshellDrawerHTML(d);} else{el('drwTitle').textContent='EBG19P';el('drwSub').textContent=t('drw_managed')+' · '+((d.ebg19p_info||{})['device.firmware']||'');el('drwBody').innerHTML=ebgDrawerHTML(d);}
 el('ovl').classList.add('on');el('drw').classList.add('on');
 if(focus)setTimeout(()=>{const t2=[...el('drwBody').querySelectorAll('.cfind')].find(x=>x.dataset.fid===focus);if(t2){t2.scrollIntoView({block:'center'});flash(t2)}},130)}
function closeDrawer(){el('ovl').classList.remove('on');el('drw').classList.remove('on')}
function polOut(s){const o=el('polout');if(o)o.textContent=s}
const polSB=()=>(POLICY_DATA||{}).sb||'hermes-demo';
const polPost=o=>fetch('/api/policy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}).then(r=>r.json());
function policyDrawerHTML(){const pd=POLICY_DATA;if(!pd||!pd.ok)return '<div class="mut" style="padding:18px">'+((pd&&pd.msg)||t('pol_load_fail'))+'</div>';
 const presets=(pd.presets||[]).map(p=>`<div style="display:flex;align-items:center;gap:9px;padding:9px 0;border-top:1px solid var(--line)"><span style="flex:0 0 auto">${p.active?'🟢':'⚪'}</span><span class="sk" style="flex:0 0 auto;font-size:13px">${esc(p.name)}</span><span class="sd2" style="flex:1;min-width:0;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.desc)}</span><button class="btn" style="flex:0 0 auto;min-width:62px" data-act="polpreset" data-nm="${esc(p.name)}" data-on="${p.active?0:1}">${p.active?t('pol_off'):t('pol_on')}</button></div>`).join('')||'<div class="mut">—</div>';
 const oshdesc=CFG.lang==='en'?{ocsf_json_enabled:'OCSF JSON event output',providers_v2_enabled:'Providers v2 layer',agent_policy_proposals_enabled:'Allow agent policy proposals'}:{ocsf_json_enabled:'OCSF JSON 事件輸出',providers_v2_enabled:'Providers v2 供應層',agent_policy_proposals_enabled:'允許 agent 提政策提案'};
 const settings=(pd.settings||[]).map(s=>{const cur=s.value==='true'?'true':(s.value==='false'?'false':'unset');const seg=['true','false','unset'].map(v=>`<button class="${cur===v?'on':''}" data-act="polsetting" data-key="${esc(s.key)}" data-val="${v}">${v==='unset'?t('osh_unset'):v}</button>`).join('');return `<div style="display:flex;align-items:center;gap:9px;padding:9px 0;border-top:1px solid var(--line)"><div style="flex:1;min-width:0"><div class="sk" style="font-size:13px">${esc(s.key)}</div><div class="sd2" style="margin:0">${oshdesc[s.key]||''}${s.source?(' · '+esc(s.source)):''}</div></div><div class="seg" style="flex:0 0 auto">${seg}</div></div>`;}).join('')||'<div class="mut">—</div>';
 const rules=(pd.rules||[]).map(n=>`<div style="display:flex;align-items:flex-start;gap:9px;padding:9px 0;border-top:1px solid var(--line)"><div style="flex:1;min-width:0"><div class="sk mono" style="font-size:12.5px;color:var(--accent)">${esc(n.name)}${n.l7?' <span class="mut" style="font-size:10px">L7</span>':''}</div><div class="sd2 mono" style="margin:1px 0 0;word-break:break-all">${esc((n.eps||[]).join(', ')||'—')}${(n.bins&&n.bins.length)?(' · 🔑 '+esc(n.bins.join(', '))):''}</div></div><button class="btn" style="flex:0 0 auto;min-width:52px" data-act="polrule" data-nm="${esc(n.name)}">${t('pol_rule_rm')}</button></div>`).join('')||'<div class="mut">—</div>';
 const sbsel=(pd.sandboxes||[]).map(s=>`<button class="${s.name===pd.sb?'on':''}" data-act="polsb" data-sb="${esc(s.name)}">${esc(s.label)}</button>`).join('');
 const sbrow=sbsel?`<div class="card"><div class="sk" style="font-size:13px;margin-bottom:7px">${t('pol_pick_agent')}</div><div class="seg" style="flex-wrap:wrap;gap:6px">${sbsel}</div><div class="sd2" style="margin-top:8px;line-height:1.6">${t('pol_pick_agent_d')}</div></div>`:'';
 return sbrow+`<div class="card"><div class="kv"><span class="k">${t('pol_sb')}</span><span class="v mono">${esc(pd.sb)}</span></div><div class="kv"><span class="k">${t('pol_gaps')}</span><span class="v ${pd.baseline_gaps>0?'red':'ok'}">${pd.baseline_gaps}</span></div><div class="sd2" style="margin-top:8px;line-height:1.6">${t('pol_gate_d')}</div></div>
 <div class="dsec">${t('pol_presets')}</div><div class="card"><div class="sd2" style="margin-bottom:8px;line-height:1.6">${t('pol_presets_d')}</div>${presets}</div>
 <div class="dsec">${t('osh_settings')}</div><div class="card"><div class="sd2" style="margin-bottom:8px;line-height:1.6">${t('osh_settings_d')}</div>${settings}</div>
 <div class="dsec">${t('pol_rules')}</div><div class="card"><div class="sd2" style="margin-bottom:4px;line-height:1.6">${t('pol_rules_d')}</div>${rules}
  <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:11px;padding-top:10px;border-top:1px dashed var(--line)">
   <input id="polad_host" placeholder="${t('pol_ph_host')}" style="flex:1;min-width:150px;background:#0d0d10;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:12px">
   <input id="polad_port" value="443" style="width:64px;background:#0d0d10;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:12px">
   <select id="polad_acc" style="background:#0d0d10;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:12px"><option value="full">full</option><option value="rest">rest</option><option value="websocket">websocket</option></select>
   <input id="polad_bin" placeholder="${t('pol_ph_bin')}" style="flex:1;min-width:150px;background:#0d0d10;color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:12px">
   <button class="btn" data-act="poladdep">${t('pol_add_ep')}</button></div></div>
 <div class="dsec">${t('pol_raw')}</div><div class="card">
  <textarea id="polraw" spellcheck="false" style="width:100%;height:300px;box-sizing:border-box;background:#0d0d10;color:var(--tx);border:1px solid var(--line);border-radius:10px;padding:11px;font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.5;resize:vertical">${esc(pd.raw)}</textarea>
  <div style="display:flex;gap:8px;margin-top:9px;flex-wrap:wrap"><button class="btn" data-act="polprove">${t('pol_prove_btn')}</button><button class="btn" data-act="polapply">${t('pol_apply_btn')}</button><button class="btn" data-act="polreload">${t('pol_revert')}</button></div>
  <div id="polout" class="mono" style="margin-top:10px;white-space:pre-wrap;word-break:break-word;font-size:11px;color:var(--tx2);max-height:240px;overflow:auto"></div></div>
 <div class="dsec">${t('pol_history')}</div><div class="card"><div class="mono" style="white-space:pre-wrap;font-size:10.5px;color:var(--tx2);max-height:200px;overflow:auto">${esc(pd.history||'—')}</div></div>`}
let POL_SB='hermes-demo';
async function openPolicyEditor(sb){if(sb)POL_SB=sb;DRW='policy';el('drwTitle').textContent=t('pol_edit_title');el('drwSub').textContent='OpenShell · prove-gated';
 el('drwBody').innerHTML='<div class="mut" style="padding:20px">'+t('pol_loading')+'</div>';el('ovl').classList.add('on');el('drw').classList.add('on');
 try{const r=await fetch('/api/policy-get?sb='+encodeURIComponent(POL_SB),{cache:'no-store'});POLICY_DATA=await r.json();POL_SB=(POLICY_DATA||{}).sb||POL_SB;el('drwBody').innerHTML=policyDrawerHTML()}catch(e){el('drwBody').innerHTML='<div class="mut" style="padding:20px">'+t('pol_load_fail')+'</div>'}}

/* ---- shell ---- */
function skeleton(){return `<div class="bn" style="background:var(--card2);color:var(--tx2);border:1px solid var(--line)">${t('loading')}</div><div class="skgrid">${Array(6).fill('<div class="skel"></div>').join('')}</div>`}
function orderedTabs(){if(!TABORDER)return TABS;const m={};TABS.forEach(t=>m[t.id]=t);const out=[];TABORDER.forEach(id=>{if(m[id])out.push(m[id])});TABS.forEach(t=>{if(out.indexOf(t)<0)out.push(t)});return out}
function buildNav(){el('nav').innerHTML=orderedTabs().map(tb=>`<a href="#${tb.id}" data-tab="${tb.id}" draggable="true"><span class="ni">${tb.ni}</span><span>${t('t_'+tb.id)}</span><span class="nb off" id="nb-${tb.id}"></span></a>`).join('')+(TABORDER?`<a class="navreset" data-act="navreset" title="${t('nav_reset')}">↺ ${t('nav_reset')}</a>`:'')}
function wireNavDrag(){const nav=el('nav');if(!nav||nav._dw)return;nav._dw=1;
 nav.addEventListener('dragstart',e=>{const a=e.target.closest('[data-tab]');if(!a)return;DRAGTAB=a.dataset.tab;a.classList.add('dragging');try{e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',DRAGTAB)}catch(_){}});
 nav.addEventListener('dragend',()=>{const a=nav.querySelector('.dragging');if(a)a.classList.remove('dragging');DRAGTAB=null});
 nav.addEventListener('dragover',e=>{e.preventDefault();const dragged=nav.querySelector('.dragging');if(!dragged)return;const a=e.target.closest('[data-tab]');if(!a||a===dragged)return;const r=a.getBoundingClientRect();nav.insertBefore(dragged,(e.clientY>r.top+r.height/2)?a.nextSibling:a)});
 nav.addEventListener('drop',e=>{e.preventDefault();const order=[...nav.querySelectorAll('[data-tab]')].map(x=>x.dataset.tab);TABORDER=order;localStorage.setItem('nclaw-taborder',JSON.stringify(order));buildNav();route()})}
function setBadge(id,v,cls){const e=el('nb-'+id);if(!e)return;if(v>0){e.textContent=v;e.className='nb '+(cls||'bad')}else{e.textContent='';e.className='nb off'}}
function tabId(){const h=(location.hash||'').replace('#','');return TABS.some(x=>x.id===h)?h:'overview'}
function route(){const id=tabId();document.querySelectorAll('.nav a').forEach(a=>{const on=a.dataset.tab===id;a.classList.toggle('on',on);if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});el('ttitle').textContent=t('t_'+id);el('tsub').textContent=t('s_'+id);document.title='NemoClaw · '+t('t_'+id);window.scrollTo(0,0);C.view=null;if(LAST)render(LAST);
 const v=el('view');if(v){v.classList.remove('viewin');if(id!=='arch'){void v.offsetWidth;v.classList.add('viewin');clearTimeout(v._a);v._a=setTimeout(()=>v.classList.remove('viewin'),580)}}}
function applyChrome(){document.documentElement.lang=CFG.lang==='en'?'en':'zh-Hant';el('refreshBtn').title=t('refresh');el('refreshBtn').setAttribute('aria-label',t('refresh'));{var _lo=el('logoutBtn');if(_lo)_lo.textContent='⎋ '+t('logout')}buildNav();route()}
function render(d){LAST=d;if(d._me&&d._me.must_change&&!window.__mc){window.__mc=1;setTimeout(()=>{const np=prompt(t('mc_prompt'));if(np&&np.length>=6){fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'pw',email:d._me.email,password:np})}).then(r=>r.json()).then(r=>{toast(r.msg||t('toast_done'));window.__mc=0;tick()}).catch(()=>{window.__mc=0})}else{window.__mc=0;toast(t('mc_skip'))}},500)}{var _m=el('meuser');if(_m)_m.textContent=(d._me&&d._me.email)?('👤 '+d._me.email):''}el('upd').textContent='🕑 '+t('updated')+new Date().toLocaleTimeString(CFG.lang==='en'?'en-US':'zh-Hant');
 const a=agg(d);el('sft').innerHTML=`${t('node_word')} ${a.up}/${a.tot} · ${t('a_fleet')} ${a.devs}`;
 setBadge('fleet',a.alerts,'bad');setBadge('cve',a.aff,'bad');setBadge('gov',a.den,'bad');
 setBadge('stack',(d.containers||[]).filter(c=>!/^Up\b/.test(c.status||'')).length,'bad');
 const id=tabId();
 put('view', id==='arch'?vArch(d) : id==='fleet'?vFleet(d) : id==='cve'?vCve(d) : id==='gov'?vGov(d) : id==='timeline'?vTimeline(d) : id==='ops'?vOps(d) : id==='stack'?vStack(d) : id==='settings'?vSettings(d) : vOverview(d));
 if(el('drw').classList.contains('on')&&DRW!=='policy')el('drwBody').innerHTML=(DRW.indexOf('cert:')===0?certDrawerHTML(d,DRW.slice(5)):DRW.indexOf('ctr:')===0?ctrDrawerHTML(d,DRW.slice(4)):DRW.indexOf('svc:')===0?svcDrawerHTML(d,DRW.slice(4)):DRW.indexOf('sast:')===0?sastDrawerHTML(d,+DRW.slice(5)):DRW==='hermes'?hermesDrawerHTML(d):DRW==='nemo'?nemoDrawerHTML(d):DRW==='openshell'?openshellDrawerHTML(d):ebgDrawerHTML(d))}
function usrPost(o){fetch('/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>tick())}
function acfgPost(o){fetch('/api/auth-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>tick())}
async function tick(){try{const r=await fetch('/api/status',{cache:'no-store'});if(r.status===401){location.href='/login';return}render(await r.json());lastOk=Date.now()}catch(e){el('upd').textContent=t('upd_fail')}}
function arm(){if(timer)clearInterval(timer);if(CFG.refresh>0)timer=setInterval(tick,CFG.refresh*1000)}
function health(){const dot=el('liveDot'),txt=el('liveTxt');if(!dot)return;
 if(CFG.refresh===0){dot.style.background='var(--tx3)';txt.textContent=t('live_manual');document.body.classList.remove('stale');return}
 const age=Date.now()-lastOk,lim=Math.max(CFG.refresh*2000,12000);
 if(age>lim*2){dot.style.background='var(--danger)';txt.textContent=t('live_down')+Math.round(age/1000)+'s';document.body.classList.add('stale')}
 else if(age>lim){dot.style.background='var(--warn)';txt.textContent=t('live_lag');document.body.classList.add('stale')}
 else{dot.style.background='var(--ok)';txt.textContent=t('live_ok');document.body.classList.remove('stale')}}
function kiosk(){try{if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen()}catch(e){}}
const TOASTDO={refresh:'toast_refresh',cve:'toast_cve',source:'toast_source',jira_reset:'toast_jira'};
document.addEventListener('click',e=>{
 const dv=e.target.closest('[data-dev]');
 if(dv){const a=dv.dataset.dev,warn={harden:t('act_warn_harden'),restart:t('act_warn_restart'),block:t('act_warn_block')}[a];
  if(warn&&!confirm(warn))return;
  const old=dv.textContent;dv.disabled=true;dv.textContent=t('running');
  fetch('/api/device-action?do='+a,{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('act_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{dv.disabled=false;dv.textContent=old;tick()});return}
 if(e.target.id==='ovl'||e.target.id==='drwClose'||e.target.closest('#drwClose')){closeDrawer();return}
 {const dd=e.target.closest('[data-drawer]');if(dd){openDrawer(dd.dataset.drawer,dd.dataset.focus);return}}
 {const k=e.target.closest('.kpi');if(k&&k.dataset.anchor){const an=k.dataset.anchor;setTimeout(()=>{const t2=el(an);if(t2){t2.scrollIntoView({behavior:'smooth',block:'center'});flash(t2)}},170)}}
 const er=e.target.closest('.evrow');if(er&&er.dataset.ev){const id=er.dataset.ev;OPEN_EV.has(id)?OPEN_EV.delete(id):OPEN_EV.add(id);if(LAST)render(LAST);return}
 const b=e.target.closest('[data-act]');if(!b)return;const act=b.dataset.act,v=b.dataset.v;
 if(act==='theme'){CFG.theme=v;localStorage.setItem('nclaw-theme',v);document.documentElement.setAttribute('data-theme',v);loadColors();if(LAST)render(LAST)}
 else if(act==='lang'){CFG.lang=v;localStorage.setItem('nclaw-lang',v);applyChrome()}
 else if(act==='densapply'){var r=el('densbar');if(r){CFG.density=+r.value;localStorage.setItem('nclaw-density',r.value);applyDensity()}}
 else if(act==='refresh'){CFG.refresh=+v;localStorage.setItem('nclaw-refresh',v);arm();if(LAST)render(LAST)}
 else if(act==='node'){CFG.node=v;localStorage.setItem('nclaw-node',v);if(LAST)render(LAST)}
 else if(act==='evf'){EVF=v;if(LAST)render(LAST)}
 else if(act==='tlf'){TLF=v;if(LAST)render(LAST)}
 else if(act==='archview'){ARCHVIEW=v;localStorage.setItem('nclaw-archview',v);if(LAST)render(LAST)}
 else if(act==='certscope'){CERTSCOPE=v;if(LAST)render(LAST)}
 else if(act==='certpol'){const sc=b.dataset.scope||'',k=b.dataset.k;b.disabled=true;fetch('/api/cert-policy?scope='+encodeURIComponent(sc)+'&key='+encodeURIComponent(k)+'&value='+encodeURIComponent(v),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;tick()})}
 else if(act==='certfam'){const on=b.classList.contains('on')?0:1;b.disabled=true;fetch('/api/cert-policy?fam='+encodeURIComponent(v)+'&on='+on,{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;tick()})}
 else if(act==='qday'){b.classList.toggle('on');const sel=[...document.querySelectorAll('.dchip.on')].map(x=>x.dataset.v).join(',');b.disabled=true;fetch('/api/config?k=quiet_days&v='+encodeURIComponent(sel),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;tick()})}
 else if(act==='navreset'){TABORDER=null;localStorage.removeItem('nclaw-taborder');buildNav();route();toast(t('nav_reset'))}
 else if(act==='auditverify'){tick();toast(t('aud_verify'))}
 else if(act==='logout'){if(!confirm(t('logout_c')))return;fetch('/api/logout',{method:'POST'}).finally(()=>location.href='/login')}
 else if(act==='usradd'){const em=(el('ua_em')||{}).value||'',pw=(el('ua_pw')||{}).value||'',ro=(el('ua_role')||{}).value||'viewer';if(!em){toast(t('toast_fail'));return}usrPost({op:'add',email:em,password:pw,role:ro})}
 else if(act==='usrdel'){if(!confirm(t('acl_del_c')))return;usrPost({op:'del',email:b.dataset.em})}
 else if(act==='usrrole'){usrPost({op:'role',email:b.dataset.em,role:b.dataset.role})}
 else if(act==='usrpw'){const np=prompt(t('acl_pw_p')+' '+b.dataset.em);if(np)usrPost({op:'pw',email:b.dataset.em,password:np})}
 else if(act==='acfg'){const o={};o[b.dataset.k]=v;acfgPost(o)}
 else if(act==='acfgip'){acfgPost({ip_whitelist:(el('acl_ip')||{}).value||''})}
 else if(act==='cfg'){const k=b.dataset.k;b.disabled=true;b.textContent=t('running');fetch('/api/config?k='+encodeURIComponent(k)+'&v='+encodeURIComponent(v),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;tick()})}
 else if(act==='recadd'){const n=(el('rc_name')||{}).value||'',tg=(el('rc_tg')||{}).value||'',em=(el('rc_email')||{}).value||'';if(!n.trim()){toast(t('rec_need_name'));return}b.disabled=true;fetch('/api/recipient?op=add&name='+encodeURIComponent(n)+'&telegram='+encodeURIComponent(tg)+'&email='+encodeURIComponent(em),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;tick()})}
 else if(act==='recdel'){if(!confirm(t('rec_del_confirm')))return;fetch('/api/recipient?op=del&email='+encodeURIComponent(v),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>tick())}
 else if(act==='rectest'){const nm=b.dataset.nm||'',tg=b.dataset.tg||'',em=b.dataset.em||'';b.disabled=true;b.textContent=t('running');fetch('/api/recipient?op=test&name='+encodeURIComponent(nm)+'&telegram='+encodeURIComponent(tg)+'&email='+encodeURIComponent(em),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=t('rec_test')})}
 else if(act==='kiosk'){kiosk()}
 else if(act==='snapcreate'){const sb=b.dataset.sb||'my-assistant';const nm=prompt(t('snap_name_p'));if(nm===null)return;const old=b.textContent;b.disabled=true;b.textContent=t('running');fetch('/api/snapshot?op=create&sb='+encodeURIComponent(sb)+'&sel='+encodeURIComponent(nm||''),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old;tick()})}
 else if(act==='snapsel'){const k=b.dataset.k;if(b.checked)SNAPSEL.add(k);else SNAPSEL.delete(k);if(LAST)render(LAST);return}
 else if(act==='snapdelsel'){const sb=b.dataset.sb;const keys=[...SNAPSEL].filter(k=>k.indexOf(sb+'|')===0);if(!keys.length)return;
   if(!confirm(t('snap_del_sel_c').replace('%s',keys.length)))return;
   b.disabled=true;b.textContent='…';
   Promise.all(keys.map(k=>fetch('/api/snapshot?op=delete&sb='+encodeURIComponent(sb)+'&sel='+encodeURIComponent(k.split('|')[1]),{method:'POST'}).then(r=>r.json()).catch(()=>({ok:false})))).then(rs=>{const n=rs.filter(r=>r&&r.ok).length;keys.forEach(k=>SNAPSEL.delete(k));toast(t('snap_del_sel_done').replace('%s',n))}).catch(()=>toast(t('toast_fail'))).finally(()=>tick())}
 else if(act==='snapdel'){const sb=b.dataset.sb,ts=b.dataset.ts,ver=b.dataset.v;
   if(!confirm(t('snap_del_c1').replace('%s',ver)))return;
   const old=b.textContent;b.disabled=true;b.textContent='…';SNAPSEL.delete(sb+'|'+ts);
   fetch('/api/snapshot?op=delete&sb='+encodeURIComponent(sb)+'&sel='+encodeURIComponent(ts),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old;tick()})}
 else if(act==='openpolicy'){openPolicyEditor()}
 else if(act==='polsb'){openPolicyEditor(b.dataset.sb)}
 else if(act==='polro'){window.RO_SB=b.dataset.sb;fetch('/api/policy-ro?sb='+encodeURIComponent(b.dataset.sb),{cache:'no-store'}).then(r=>r.json()).then(r=>{if(r&&r.ok){window.ROPOL=r.policy;if(LAST)render(LAST)}}).catch(()=>toast(t('toast_fail')))}
 else if(act==='sysdo'){const dd=b.dataset.do,sb=b.dataset.sb||'',ch=b.dataset.chan||'';if(b.dataset.confirm&&!confirm(b.dataset.confirm))return;const old=b.textContent;b.disabled=true;b.textContent=t('running');sysShow(dd+(sb?(' · '+sb):'')+(ch?(' · '+ch):''),t('running')+'…');fetch('/api/sys?do='+encodeURIComponent(dd)+(sb?('&sb='+encodeURIComponent(sb)):'')+(ch?('&chan='+encodeURIComponent(ch)):''),{cache:'no-store'}).then(r=>r.json()).then(r=>{sysShow(r.title||dd,r.out||'(empty)');tick&&tick()}).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old})}
 else if(act==='infset'){const prov=prompt(t('sys_inf_prov_p'));if(!prov)return;const model=prompt(t('sys_inf_model_p'));if(!model)return;const old=b.textContent;b.disabled=true;b.textContent=t('running');sysShow(t('sys_inf_set')+' · '+prov+'/'+model,t('running')+'…');fetch('/api/sys?do=infset&provider='+encodeURIComponent(prov)+'&model='+encodeURIComponent(model),{cache:'no-store'}).then(r=>r.json()).then(r=>{sysShow(r.title||'inference set',r.out||'(empty)');tick&&tick()}).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old})}
 else if(act==='rebuild'){const sb=b.dataset.sb||'';const v=prompt(t('sys_rebuild_p')+' '+sb);if(v===null)return;if(v!==sb){toast(t('sys_rebuild_mismatch'));return}const old=b.textContent;b.disabled=true;b.textContent=t('running');sysShow('rebuild · '+sb,t('running')+'…');fetch('/api/sys?do=rebuild&sb='+encodeURIComponent(sb),{cache:'no-store'}).then(r=>r.json()).then(r=>{sysShow(r.title||'rebuild',r.out||'(empty)');tick&&tick()}).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old})}
 else if(act==='syscmd'){const dd=b.dataset.do,sb=b.dataset.sb||'';if(b.dataset.confirm&&!confirm(b.dataset.confirm))return;let url='/api/sys?do='+encodeURIComponent(dd)+(sb?('&sb='+encodeURIComponent(sb)):'');const ps=(b.dataset.prompts||'').split('|').filter(Boolean),nm=['a1','a2'];for(let i=0;i<ps.length;i++){const v=prompt(t(ps[i]));if(v===null)return;url+='&'+nm[i]+'='+encodeURIComponent(v)}const old=b.textContent;b.disabled=true;b.textContent=t('running');sysShow(dd+(sb?(' · '+sb):''),t('running')+'…');fetch(url,{cache:'no-store'}).then(r=>r.json()).then(r=>{sysShow(r.title||dd,r.out||'(empty)');tick&&tick()}).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old})}
 else if(act==='polpreset'){const nm=b.dataset.nm,on=b.dataset.on==='1';b.disabled=true;
   polPost({op:'preset',sb:polSB(),name:nm,on:on,dry:true}).then(r=>{if(!confirm((r.out||r.msg||'')+'\n\n'+t('pol_confirm_apply'))){b.disabled=false;return}
     return polPost({op:'preset',sb:polSB(),name:nm,on:on,dry:false}).then(r2=>{toast(r2.msg||t('toast_done'));if(r2.out&&(!r2.ok||r2.nochange))alert((r2.msg||'')+'\n\n'+r2.out);openPolicyEditor()})}).catch(()=>{toast(t('toast_fail'));b.disabled=false})}
 else if(act==='polprove'){const raw=(el('polraw')||{}).value||'';polOut(t('running'));polPost({op:'prove',sb:polSB(),raw:raw,baseline:(POLICY_DATA||{}).baseline_gaps}).then(r=>polOut((r.msg||'')+'\n\n'+(r.out||''))).catch(()=>polOut(t('toast_fail')))}
 else if(act==='polapply'){const raw=(el('polraw')||{}).value||'';if(!confirm(t('pol_apply_c')))return;polOut(t('running'));polPost({op:'apply',sb:polSB(),raw:raw}).then(r=>{polOut((r.msg||'')+'\n\n'+(r.out||''));toast(r.ok?t('toast_done'):(r.msg||t('toast_fail')));if(r.ok)setTimeout(openPolicyEditor,700)}).catch(()=>polOut(t('toast_fail')))}
 else if(act==='polreload'){const ta=el('polraw');if(ta&&POLICY_DATA)ta.value=POLICY_DATA.raw}
 else if(act==='polsetting'){const key=b.dataset.key,val=b.dataset.val;b.disabled=true;polPost({op:'setting',sb:polSB(),key:key,value:val}).then(r=>{toast(r.msg||t('toast_done'));openPolicyEditor()}).catch(()=>{toast(t('toast_fail'));b.disabled=false})}
 else if(act==='polrule'){const nm=b.dataset.nm;b.disabled=true;
   polPost({op:'rule_remove',sb:polSB(),name:nm,dry:true}).then(r=>{if(!confirm((r.out||r.msg||'')+'\n\n'+t('pol_confirm_apply'))){b.disabled=false;return}
     return polPost({op:'rule_remove',sb:polSB(),name:nm,dry:false}).then(r2=>{toast(r2.msg||t('toast_done'));if(r2.out&&!r2.ok)alert((r2.msg||'')+'\n\n'+r2.out);openPolicyEditor()})}).catch(()=>{toast(t('toast_fail'));b.disabled=false})}
 else if(act==='poladdep'){const host=(el('polad_host')||{}).value||'',port=(el('polad_port')||{}).value||'443',acc=(el('polad_acc')||{}).value||'full',bins=((el('polad_bin')||{}).value||'').split(',').map(x=>x.trim()).filter(Boolean);
   if(!host){toast(t('toast_fail'));return}b.disabled=true;
   polPost({op:'endpoint_add',sb:polSB(),host:host,port:port,access:acc,binaries:bins,dry:true}).then(r=>{if(!confirm((r.out||r.msg||'')+'\n\n'+t('pol_confirm_apply'))){b.disabled=false;return}
     return polPost({op:'endpoint_add',sb:polSB(),host:host,port:port,access:acc,binaries:bins,dry:false}).then(r2=>{toast(r2.msg||t('toast_done'));if(r2.out&&!r2.ok)alert((r2.msg||'')+'\n\n'+r2.out);openPolicyEditor()})}).catch(()=>{toast(t('toast_fail'));b.disabled=false})}
 else if(act==='do'){const old=b.textContent;b.disabled=true;b.textContent=t('running');fetch('/api/action?do='+v,{method:'POST'}).then(r=>r.json()).then(r=>toast(r.ok?t(TOASTDO[v]||'toast_done'):t('toast_fail'))).catch(()=>toast(t('toast_fail'))).finally(()=>{b.disabled=false;b.textContent=old;tick()})}});
document.addEventListener('input',e=>{var r=e.target.closest('input[data-act="densbar"]');if(!r)return;var lb=el('densval');if(lb)lb.textContent=r.value});
document.addEventListener('change',e=>{const sel=e.target.closest('select[data-act="cfgsel"]');if(!sel)return;fetch('/api/config?k='+encodeURIComponent(sel.dataset.k)+'&v='+encodeURIComponent(sel.value),{method:'POST'}).then(r=>r.json()).then(r=>toast(r.msg||t('toast_done'))).catch(()=>toast(t('toast_fail'))).finally(()=>tick())});
document.addEventListener('mousemove',e=>{const tc=e.target.closest('.tchart');
 document.querySelectorAll('.tchart').forEach(x=>{if(x!==tc){const c=x.querySelector('.tccur');if(c)c.style.visibility='hidden';const p=x.querySelector('.tctip');if(p)p.style.display='none'}});
 if(!tc)return;try{const d=JSON.parse(decodeURIComponent(tc.dataset.tc));const r=tc.getBoundingClientRect();const fx=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
 let i=Math.round((fx*d.W-d.padL)/d.cw*(d.n-1));i=Math.max(0,Math.min(d.n-1,i));
 const cx=d.padL+(i/(d.n-1))*d.cw,cur=tc.querySelector('.tccur');if(cur){cur.setAttribute('x1',cx);cur.setAttribute('x2',cx);cur.style.visibility='visible'}
 const tip=tc.querySelector('.tctip');if(tip){tip.style.display='block';tip.style.left=(fx*100)+'%';tip.innerHTML=`<b>${d.ts[i]||''}</b><br>${d.label||''}: ${d.v[i]}`}}catch(_){}});
document.addEventListener('keydown',e=>{if(/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))return;const k=e.key;
 if(k==='r'){tick();toast(t('toast_refresh'))}
 else if(k==='d'){const nx=CFG.theme==='dark'?'light':'dark';CFG.theme=nx;localStorage.setItem('nclaw-theme',nx);document.documentElement.setAttribute('data-theme',nx);loadColors();if(LAST)render(LAST)}
 else if(k==='f'){kiosk()}
 else if(k==='Escape'){closeDrawer()}
 else if(/^[1-9]$/.test(k)){const ot=orderedTabs();if(ot[+k-1])location.hash='#'+ot[+k-1].id}});
window.addEventListener('hashchange',route);
function applyDensity(){var F=[1.45,1.30,1.18,1.09,1.0,0.93,0.87,0.81,0.76,0.72];document.body.style.zoom=F[(CFG.density||3)-1]||1}applyDensity();loadColors();applyChrome();wireNavDrag();el('view').innerHTML=skeleton();tick();arm();health();setInterval(health,1000);
if(location.search.indexOf('drawer=ebg')>=0)setTimeout(()=>{if(LAST)openDrawer()},1000);  // 深連結 / demo:直接開設備詳情
setTimeout(()=>{if(location.search.indexOf('demoexpand')>=0&&LAST&&LAST.events){EVF='DENIED';LAST.events.filter(e=>e.verb==='DENIED').slice(0,2).forEach(e=>OPEN_EV.add(e.ts));if(tabId()==='gov')render(LAST)}},900);
</script></body></html>"""

ADMIN_AUDIT = os.path.expanduser("~/.config/nemoclaw/admin-audit.jsonl")
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
                # 真實實機(ebg19p/rt-ax89x)離線屬環境常態 → info(中性 offline,不發紅色告警/Telegram);其餘維持 warn
                _real_off = any(k in asset for k in ("ebg19p", "rt-ax89x"))
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
        xff = self.headers.get("X-Forwarded-For", "")
        return xff.split(",")[0].strip() if xff else self.client_address[0]
    def _sess(self):
        v = get_session(self._sid())
        return v if (v and _ip_ok(self._cip())) else None
    def _send_cookie(self, code, obj, sid=None):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        if sid is not None:
            self.send_header("Set-Cookie", f"sid={sid}; HttpOnly; Path=/; SameSite=Strict")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/brand.svg":
            return self._send(200, BRAND_SVG, "image/svg+xml; charset=utf-8")
        if p == "/login":
            return self._send(200, LOGIN_HTML, "text/html; charset=utf-8")
        sess = self._sess()
        if p in ("/", "/index.html"):
            if not sess:
                self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return
            return self._send(200, HTML, "text/html; charset=utf-8")
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
            sb = parse_qs(urlparse(self.path).query).get("sb", ["hermes-demo"])[0]
            try:
                return self._send(200, json.dumps(do_policy_get(sb), ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "msg": str(e)}), "application/json")
        if p == "/api/policy-ro":   # 唯讀:任一 agent 的 live 政策(治理頁唯讀卡 agent 選單)
            sb = parse_qs(urlparse(self.path).query).get("sb", ["hermes-demo"])[0]
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
            if do not in ("cve", "source", "jira_reset", "refresh"):
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
            op = q.get("op", [""])[0]; sel = q.get("sel", [""])[0]; sb = q.get("sb", ["my-assistant"])[0]
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
    _tls = bool(os.environ.get("DASH_TLS") and os.path.exists(_cert) and os.path.exists(_key))
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
