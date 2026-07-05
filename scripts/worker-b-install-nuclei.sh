#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-install-nuclei.sh — install projectdiscovery/nuclei into the worker-b (zone B) sandbox so
# its active-scan subsystem (wi_nuclei.py) works, and allow the binary in the OpenShell policy.
#
# Governed path: the sandbox is deny-by-default and its egress can't reach GitHub *release-download*
# hosts, so we fetch the arm64 binary + the template set on the HOST (open egress) and `docker cp`
# them in. The sandbox only gains permission to EXECUTE the binary (--binary); templates are pinned
# on disk (no runtime phone-home — wi_nuclei runs nuclei with -duc -t <dir>). Idempotent: re-fetches
# only what's missing, policy update is merge-semantics. boot-stack re-runs it after a rebuild.
set -uo pipefail
SB="${WORKERB_SANDBOX:-worker-b}"
CACHE="$NEMOFLEET_ROOT/.cache/nuclei"
BIN="$CACHE/nuclei"
TPL="$CACHE/templates"
DST_BIN="/usr/local/bin/nuclei"
DST_TPL="/usr/local/share/nuclei-templates"
mkdir -p "$CACHE"

log(){ echo "[nuclei] $*"; }

# ── 1) fetch the arm64 binary on the host if we don't have it ──────────────────────────────────
if [ ! -x "$BIN" ]; then
  ver="${NUCLEI_VER:-$(curl -s -m15 https://api.github.com/repos/projectdiscovery/nuclei/releases/latest \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["tag_name"].lstrip("v"))' 2>/dev/null)}"
  [ -n "$ver" ] || { log "找不到 nuclei 版本(GitHub API 無回應)"; exit 1; }
  log "下載 nuclei v$ver (linux_arm64)…"
  curl -sL -m180 -o "$CACHE/nuclei.zip" \
    "https://github.com/projectdiscovery/nuclei/releases/download/v${ver}/nuclei_${ver}_linux_arm64.zip" \
    || { log "下載失敗"; exit 1; }
  unzip -o -q "$CACHE/nuclei.zip" nuclei -d "$CACHE" && chmod 755 "$BIN"
fi

# ── 2) fetch the template set on the host if missing ───────────────────────────────────────────
if [ -z "$(ls -A "$TPL" 2>/dev/null)" ]; then
  log "clone nuclei-templates(shallow)…"
  git clone --depth 1 -q https://github.com/projectdiscovery/nuclei-templates "$TPL" \
    || { log "templates clone 失敗"; exit 1; }
fi

# ── 3) locate the running sandbox ──────────────────────────────────────────────────────────────
ct="$(docker ps --format '{{.Names}}' | grep -m1 "$SB" || true)"
[ -n "$ct" ] || { log "沙箱 $SB 未就緒(略過)"; exit 0; }

# ── 4) copy binary + templates into the sandbox (only if changed / absent) ─────────────────────
if ! docker exec "$ct" sh -c "cmp -s /dev/stdin $DST_BIN" < "$BIN" 2>/dev/null; then
  docker cp "$BIN" "$ct:$DST_BIN" && docker exec -u 0 "$ct" chmod 755 "$DST_BIN"
  log "binary → $ct:$DST_BIN"
fi
if ! docker exec "$ct" sh -c "[ -d $DST_TPL ] && [ -n \"\$(ls -A $DST_TPL 2>/dev/null)\" ]"; then
  docker exec -u 0 "$ct" mkdir -p "$DST_TPL"
  docker cp "$TPL/." "$ct:$DST_TPL/" && docker exec -u 0 "$ct" sh -c "chmod -R a+rX $DST_TPL"
  log "templates → $ct:$DST_TPL ($(find "$TPL" -name '*.yaml' | wc -l) yaml)"
fi

# ── 5) allow the binary in the OpenShell policy (merge; safe to re-run) ─────────────────────────
if command -v openshell >/dev/null 2>&1 && openshell policy get "$SB" >/dev/null 2>&1; then
  # --binary must ride with an --add-endpoint; re-assert an already-allowed github endpoint (merge = no-op)
  # purely to satisfy the CLI while adding nuclei to the allowed-binaries set. The worker-b→device
  # egress that nuclei's scan actually needs is opened separately (boot-stack, with EBG19P_TARGET).
  openshell policy update "$SB" --add-endpoint api.github.com:443:full --binary "$DST_BIN" --wait --timeout 60 2>&1 \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "submitted|loaded|error|denied" || true
  v="$(openshell policy get "$SB" 2>&1 | awk '/^Active:/{print $2}')"
  log "✓ $SB 允許執行 nuclei(active policy v${v:-?})"
else
  log "openshell 不可用 — binary 已就位,但需自行把 $DST_BIN 加入 $SB binaries policy"
fi

# ── 6) verify inside the sandbox ───────────────────────────────────────────────────────────────
if docker exec "$ct" sh -c "command -v nuclei >/dev/null && HOME=/tmp nuclei -version" >/dev/null 2>&1; then
  ver="$(docker exec "$ct" sh -c 'HOME=/tmp nuclei -version 2>&1' | awk -F': ' '/Version/{print $2}' | head -1)"
  log "✓ nuclei 就緒於 $SB(${ver:-installed})"
else
  log "⚠ nuclei 已 copy 但沙箱內無法執行(檢查 policy / 權限)"; exit 1
fi
