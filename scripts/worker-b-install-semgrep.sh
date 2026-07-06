#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-install-semgrep.sh — install Semgrep (real AST + taint SAST engine) into the worker-b
# sandbox and stage its ruleset, so worker-b's source scan does real static analysis, not regex.
#
# worker-b keeps a scoped pypi egress (least-privilege review left it), so semgrep installs via pip
# in-sandbox. The ruleset is deterministic + offline: the community C security rules (fetched to a
# host cache once) + nemofleet's own taint rules (config/semgrep/, versioned) → docker cp'd to
# /usr/local/share/semgrep-rules. A scan never phones the semgrep registry. Idempotent; boot-stack
# re-runs it after a rebuild.
set -uo pipefail
SB="${WORKERB_SANDBOX:-worker-b}"
CACHE="$NEMOFLEET_ROOT/.cache/semgrep-rules"
DST_RULES="/usr/local/share/semgrep-rules"
log(){ echo "[semgrep] $*"; }

ct="$(docker ps --format '{{.Names}}' | grep -m1 "$SB" || true)"
[ -n "$ct" ] || { log "沙箱 $SB 未就緒(略過)"; exit 0; }

# ── 1) install semgrep in-sandbox (pip; pypi egress is allowed on worker-b) ─────────────────────
if ! docker exec "$ct" sh -c 'test -x /root/.local/bin/semgrep'; then
  log "pip install semgrep(in-sandbox)…"
  docker exec -u 0 "$ct" sh -c 'pip3 install --user --break-system-packages --no-input semgrep >/tmp/semgrep-install.log 2>&1' \
    || { log "pip install 失敗(看容器 /tmp/semgrep-install.log)"; exit 1; }
fi
ver="$(docker exec "$ct" sh -c 'PATH=/root/.local/bin:$PATH HOME=/root semgrep --version 2>/dev/null' | head -1)"
[ -n "$ver" ] || { log "semgrep 安裝後無法執行"; exit 1; }

# ── 2) stage rules on the host: community C security rules + nemofleet custom taint rules ────────
mkdir -p "$CACHE"
if [ -z "$(ls -A "$CACHE"/lang 2>/dev/null)" ]; then
  log "fetch community C security rules…"
  tmp="$(mktemp -d)"
  if git clone --depth 1 -q https://github.com/semgrep/semgrep-rules "$tmp/src" 2>/dev/null; then
    cp -r "$tmp/src/c/." "$CACHE/" 2>/dev/null || true
  else
    log "⚠ 無法抓 community 規則(離線?)—— 只用 nemofleet 自訂規則"
  fi
  rm -rf "$tmp"
fi
mkdir -p "$CACHE/nemofleet"; cp "$NEMOFLEET_ROOT"/config/semgrep/*.yaml "$CACHE/nemofleet/" 2>/dev/null || true
n="$(find "$CACHE" -name '*.yaml' | wc -l)"
[ "$n" -gt 0 ] || { log "無任何規則可用"; exit 1; }

# ── 3) copy rules into the sandbox ──────────────────────────────────────────────────────────────
docker exec -u 0 "$ct" sh -c "rm -rf $DST_RULES; mkdir -p $DST_RULES"
docker cp "$CACHE/." "$ct:$DST_RULES/" && docker exec -u 0 "$ct" sh -c "chmod -R a+rX $DST_RULES"
log "rules → $ct:$DST_RULES ($n yaml)"

# ── 4) verify a real scan runs end-to-end ───────────────────────────────────────────────────────
if docker exec "$ct" sh -c "printf 'int f(char*u){char*s=nvram_safe_get(\"x\");system(s);return 0;}' > /tmp/_sgv.c 2>/dev/null; PATH=/root/.local/bin:\$PATH HOME=/root semgrep scan --config $DST_RULES --json --quiet --metrics=off --no-git-ignore /tmp/_sgv.c 2>/dev/null | grep -q results"; then
  log "✓ semgrep $ver 就緒於 $SB(real AST/taint SAST · $n rules)"
else
  log "⚠ semgrep 已裝但驗證掃描未通過(檢查 rules / PATH)"; exit 1
fi
