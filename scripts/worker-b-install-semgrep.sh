#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-install-semgrep.sh — install Semgrep (real AST + taint SAST engine) into the worker-b
# sandbox and stage its ruleset, so worker-b's source scan does real static analysis, not regex.
#
# worker-b keeps a scoped pypi egress (least-privilege review left it), so semgrep installs via pip
# in-sandbox. The ruleset (community rules per language + nemofleet's own taint rules) is staged once
# on the host by fetch-semgrep-rules.sh (shared with `make security-scan`, which runs the identical
# ruleset directly against nemofleet's own repo) → docker cp'd here to /usr/local/share/semgrep-rules.
# A scan never phones the semgrep registry. Idempotent; boot-stack re-runs it after a rebuild.
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

# ── 2) stage rules on the host (shared cache — see fetch-semgrep-rules.sh) ──────────────────────
bash "$NEMOFLEET_ROOT/scripts/fetch-semgrep-rules.sh" || exit 1
n="$(find "$CACHE" -name '*.yaml' | wc -l)"
[ "$n" -gt 0 ] || { log "無任何規則可用"; exit 1; }

# ── 3) copy rules into the sandbox ──────────────────────────────────────────────────────────────
docker exec -u 0 "$ct" sh -c "rm -rf $DST_RULES; mkdir -p $DST_RULES"
docker cp "$CACHE/." "$ct:$DST_RULES/" && docker exec -u 0 "$ct" sh -c "chmod -R a+rX $DST_RULES"
log "rules → $ct:$DST_RULES ($n yaml)"

# ── 4) verify a real scan runs end-to-end, per language actually staged ────────────────────────
verify() {  # $1=filename (under /tmp) $2=snippet
  docker exec "$ct" sh -c "printf '%s' '$2' > /tmp/$1 2>/dev/null; PATH=/root/.local/bin:\$PATH HOME=/root semgrep scan --config $DST_RULES --json --quiet --metrics=off --no-git-ignore /tmp/$1 2>/dev/null | grep -q results"
}
ok=1
verify _sgv.c 'int f(char*u){char*s=nvram_safe_get("x");system(s);return 0;}' || ok=0
[ -d "$CACHE/python" ] && { verify _sgv.py 'import subprocess
def f(u): subprocess.run(u, shell=True)' || ok=0; }
langs="$(find "$CACHE" -maxdepth 1 -mindepth 1 -type d ! -name nemofleet -exec basename {} \; | sort | tr '\n' ' ')"
if [ "$ok" = 1 ]; then
  log "✓ semgrep $ver 就緒於 $SB(real AST/taint SAST · $n rules · ${langs% })"
else
  log "⚠ semgrep 已裝但驗證掃描未通過(檢查 rules / PATH)"; exit 1
fi
