#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# stack-sbom.sh — 產生 agent stack「自身」的 SBOM + 完整性清單(B7)。
# 內容:各容器映像 digest、套件清單(pip/apt/npm 計數)、關鍵原始檔 sha256 基線。
# 用途:供應鏈完整性 — 之後可比對 digest/hash 是否被換掉。零外網。
# 用法:bash scripts/stack-sbom.sh [輸出檔]   預設 ./stack-sbom.json
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"; export PATH="$NEMOFLEET_NODE_BIN:$PATH"
OUT="${1:-$DIR/stack-sbom.json}"
python3 - "$OUT" <<'PY'
import json, subprocess, sys, hashlib, os, time
def sh(c, t=30):
    try: return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception: return ""
out = sys.argv[1]
sbom = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "nemoclaw-stack-sbom", "images": [], "files": []}
for n in [x for x in sh("docker ps --format '{{.Names}}'").splitlines() if x]:
    img = sh(f"docker inspect -f '{{{{.Config.Image}}}}' {n}")
    dig = sh(f"docker inspect -f '{{{{range .RepoDigests}}}}{{{{.}}}}{{{{end}}}}' {n}") or sh(f"docker inspect -f '{{{{.Image}}}}' {n}")
    pipc = len([l for l in sh(f"docker exec {n} sh -c 'pip3 freeze 2>/dev/null'").splitlines() if l])
    aptc = len([l for l in sh(f"docker exec {n} sh -c 'dpkg -l 2>/dev/null | grep -c ^ii'").splitlines() if l]) or sh(f"docker exec {n} sh -c 'dpkg -l 2>/dev/null | grep -c ^ii'")
    npmc = sh(f"docker exec {n} sh -c 'npm ls -g --depth=0 2>/dev/null | grep -c @' ")
    sbom["images"].append({"container": n, "image": img, "digest": dig, "pip_pkgs": pipc, "apt_pkgs": aptc, "npm_global": npmc})
for f in ["$BRIDGE_DIR/agent-dashboard.py", "$BRIDGE_DIR/openclaw-fix-endpoint.py", "scripts/boot-stack.sh", "scripts/rotate-bridge-token.sh"]:
    if os.path.exists(f):
        sbom["files"].append({"path": f, "sha256": hashlib.sha256(open(f, "rb").read()).hexdigest(), "bytes": os.path.getsize(f)})
json.dump(sbom, open(out, "w"), indent=2, ensure_ascii=False)
print(f"SBOM → {out}  ({len(sbom['images'])} images, {len(sbom['files'])} files)")
PY
