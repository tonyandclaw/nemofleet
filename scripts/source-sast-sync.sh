#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# source-sast-sync.sh — [手動 fallback] 從 gnuton/asuswrt-merlin.ng 抓「真實含危險 sink 的 C 原始碼」放進 worker-b(zone B),
# 注:正常情況 worker-b 已會自己抓(endpoint fetch_upstream_sast,容器內經治理 egress);本腳本僅在容器無 egress 時手動補。
# 讓 /source-cve 的 SAST(CWE)是真 repo 內容而非 demo。host 端抓(API 列目錄 + raw 抓內容,不必開沙箱 egress)。
# 比對的 sink 與 endpoint _SAST_SINKS 一致:CWE-78 system(/popen(、CWE-798 硬編憑證。
# 12h 新鮮度守門。寫到容器 {base}/real/ + manifest;有真檔時 endpoint 會跳過 demo 檔只掃真檔。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
REPO="${SBOM_REPO:-gnuton/asuswrt-merlin.ng}"; REF="${SBOM_REF:-master}"
WD="/sandbox/.hermes/workspace/it-task"
SRC_ASSET="lab-asus-ebg19p-01"
BASE="$WD/source/$SRC_ASSET"
KEEP="${SAST_KEEP:-8}"        # 最多保留幾支有命中的檔
EXAMINE="${SAST_EXAMINE:-90}" # 最多檢視幾支候選檔(限流保護)
CTB="${CT_B:-$(docker ps --format '{{.Names}}'|grep -m1 worker-b)}"
[ -n "$CTB" ] || { echo "[sast] zone B(worker-b)容器未跑" >&2; exit 1; }
fresh=$(docker exec "$CTB" sh -c "[ -f $WD/source-sast-manifest.json ] && echo \$(( \$(date +%s) - \$(stat -c %Y $WD/source-sast-manifest.json) )) || echo 999999" 2>/dev/null)
if [ "${fresh:-999999}" -lt 43200 ]; then echo "[sast] 12h 內已更新($(( ${fresh:-0}/3600 ))h 前),跳過"; exit 0; fi  # nosemgrep: unquoted-variable-expansion-in-command -- inside $(( )) arithmetic context, no word-splitting/globbing applies

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
REPO="$REPO" REF="$REF" KEEP="$KEEP" EXAMINE="$EXAMINE" OUT="$TMP" python3 <<'PY' || { echo "[sast] 抓取失敗(github 限流?)" >&2; exit 1; }
import os, re, json, urllib.request
repo=os.environ["REPO"]; ref=os.environ["REF"]; keep=int(os.environ["KEEP"]); examine=int(os.environ["EXAMINE"]); out=os.environ["OUT"]
# 與 endpoint _SAST_SINKS 一致
SINKS=[("CWE-78 command-injection (non-literal arg)", re.compile(r"\b(system|popen)\s*\(\s*[A-Za-z_]")),
       ("CWE-798 hardcoded-credential", re.compile(r'(?i)(password|passwd|secret|api[_-]?key|token)\b\s*=\s*"[^"]{3,}"'))]
CAND_DIRS=["release/src/router/rc","release/src/router/httpd","release/src/router/shared",
           "release/src/router/networkmap","release/src/router/httpd/sysdeps","release/src/router/rc/sysdeps"]
def api(url):
    req=urllib.request.Request(url, headers={"User-Agent":"nemofleet-sast","Accept":"application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=25))
def raw(path):
    url=f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
    req=urllib.request.Request(url, headers={"User-Agent":"nemofleet-sast"})
    return urllib.request.urlopen(url, timeout=25).read().decode("utf-8","replace")
cands=[]
for d in CAND_DIRS:
    try: items=api(f"https://api.github.com/repos/{repo}/contents/{d}?ref={ref}")
    except Exception: continue
    for it in items:
        if it.get("type")=="file" and it.get("name","").endswith((".c",".h")):
            cands.append(it["path"])
kept=[]; seen_names=set(); examined=0
for path in cands:
    if len(kept)>=keep or examined>=examine: break
    examined+=1
    try: content=raw(path)
    except Exception: continue
    hits=[]
    for i,ln in enumerate(content.splitlines(),1):
        for cwe,rx in SINKS:
            if rx.search(ln): hits.append({"cwe":cwe,"line":i,"code":ln.strip()[:120]})
    if not hits: continue
    base=os.path.basename(path); d2=os.path.basename(os.path.dirname(path))
    rel=f"{d2}__{base}"
    if rel in seen_names: rel=f"{d2}__{len(kept)}__{base}"
    seen_names.add(rel)
    rd=os.path.join(out,"real"); os.makedirs(rd,exist_ok=True)
    open(os.path.join(rd,rel),"w",encoding="utf-8").write(content)
    kept.append({"path":path,"rel":f"real/{rel}","hits":len(hits),"sample":hits[0]})
import time
manifest={"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"source":"github","repo":repo,"ref":ref,
          "examined":examined,"kept":len(kept),"files":kept}
open(os.path.join(out,"manifest.json"),"w",encoding="utf-8").write(json.dumps(manifest,ensure_ascii=False,indent=2))
print(f"[sast] 檢視 {examined} 檔,保留 {len(kept)} 支有真實 sink 命中")
for f in kept: print(f"  + {f['path']} ({f['hits']} hits) {f['sample']['cwe']}")
if not kept: raise SystemExit(2)
PY

[ -d "$TMP/real" ] || { echo "[sast] 無命中檔,保留 demo SAST(endpoint 會 fallback)" >&2; exit 2; }
docker exec "$CTB" sh -c "rm -rf $BASE/real; mkdir -p $BASE" 2>/dev/null
docker cp "$TMP/real" "$CTB:$BASE/" >/dev/null
docker cp "$TMP/manifest.json" "$CTB:$WD/source-sast-manifest.json" >/dev/null
docker exec "$CTB" sh -c "chown -R 998:998 $BASE/real $WD/source-sast-manifest.json" 2>/dev/null
echo "[sast] ✓ 已寫入真實原始碼 → $CTB:$BASE/real ($REPO@$REF)"
