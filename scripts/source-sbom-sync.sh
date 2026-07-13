#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# source-sbom-sync.sh — [手動 fallback] 從 gnuton/asuswrt-merlin.ng 抽「元件→版本」真實 SBOM,寫進 worker-b(zone B)沙箱。
# 注:正常情況 worker-b 已會自己抓(endpoint fetch_upstream_sbom,容器內經治理 egress);本腳本僅在容器無 egress 時手動補。
# host 端抓(github API,不必開沙箱 egress)。B 的 /source-cve 會用真版本做版本式 CVE 比對。
# 12h 新鮮度守門(repo 變動慢,免狂打 github API 限流)。用法:bash scripts/source-sbom-sync.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
REPO="${SBOM_REPO:-gnuton/asuswrt-merlin.ng}"; REF="${SBOM_REF:-master}"
WD="/sandbox/.hermes/workspace/it-task"
CTB="${CT_B:-$(docker ps --format '{{.Names}}'|grep -m1 worker-b)}"
[ -n "$CTB" ] || { echo "[sbom] zone B(worker-b)容器未跑" >&2; exit 1; }
fresh=$(docker exec "$CTB" sh -c "[ -f $WD/source-sbom.json ] && echo \$(( \$(date +%s) - \$(stat -c %Y $WD/source-sbom.json) )) || echo 999999" 2>/dev/null)
if [ "${fresh:-999999}" -lt 43200 ]; then echo "[sbom] 12h 內已更新($(( ${fresh:-0}/3600 ))h 前),跳過"; exit 0; fi  # nosemgrep: unquoted-variable-expansion-in-command -- inside $(( )) arithmetic context, no word-splitting/globbing applies
JSON="$(REPO="$REPO" REF="$REF" python3 <<'PY'
import os, json, re, time, urllib.request
repo=os.environ["REPO"]; ref=os.environ["REF"]
url=f"https://api.github.com/repos/{repo}/contents/release/src/router?ref={ref}"
req=urllib.request.Request(url, headers={"User-Agent":"nemofleet-sbom","Accept":"application/vnd.github+json"})
data=json.load(urllib.request.urlopen(req, timeout=25))
def vt(s): return tuple(int(x) for x in re.findall(r"\d+", s))
pk={}
for it in data:
    if it.get("type")!="dir": continue
    m=re.match(r"^(.*?)-(\d[\w.+]*)$", it["name"])
    if not m: continue
    name, ver = m.group(1).lower(), m.group(2)
    if name not in pk or vt(ver) > vt(pk[name]):   # 同元件多版本 → 取最高(最可能是 build 用的)
        pk[name]=ver
packages=[{"name":n,"version":v} for n,v in sorted(pk.items())]
print(json.dumps({"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"source":"github","repo":repo,"ref":ref,"count":len(packages),"packages":packages}, ensure_ascii=False))
PY
)"
[ -n "$JSON" ] || { echo "[sbom] 抓取/解析失敗(github 限流?)" >&2; exit 1; }
printf '%s\n' "$JSON" | docker exec -i "$CTB" sh -c "cat > $WD/source-sbom.json && chown 998:998 $WD/source-sbom.json"
printf '%s\n' "$JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print('[sbom] ✓ 寫入',d['count'],'個元件 →',d['repo']+'@'+d['ref'])"
