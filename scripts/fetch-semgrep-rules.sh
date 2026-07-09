#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# fetch-semgrep-rules.sh — stage the Semgrep ruleset into the HOST cache (.cache/semgrep-rules):
# community security rules per language (c/python/javascript/typescript/bash, one subdir each — see
# the namespacing note below) + nemofleet's own custom taint rules (config/semgrep/, versioned).
# Idempotent (checks the cache before re-cloning). Shared by:
#   - worker-b-install-semgrep.sh, which docker cp's this same cache into the worker-b sandbox
#   - `make security-scan`, which runs semgrep against this same cache directly on the host
# so nemofleet's own repo and any upstream repo worker-b syncs are checked against identical rules.
#
# Per-language subdirs (not a flat merge): the upstream semgrep-rules repo has same-named files across
# languages (e.g. lang/security/md5-used-as-password.yaml exists under both c/ and python/, with
# different `languages:` in each) — flattening them into one tree would silently clobber one with the
# other. Semgrep loads a --config dir recursively regardless of nesting, so namespacing costs nothing.
set -uo pipefail
CACHE="$NEMOFLEET_ROOT/.cache/semgrep-rules"
RULE_LANGS="c python javascript typescript bash"
log(){ echo "[semgrep-rules] $*"; }

mkdir -p "$CACHE"
if [ -z "$(ls -A "$CACHE/c" 2>/dev/null)" ]; then
  log "fetch community security rules ($RULE_LANGS)…"
  rm -rf "$CACHE"/lang   # pre-multi-lang layout marker (flat c-only tree); stale, drop it
  tmp="$(mktemp -d)"
  if git clone --depth 1 -q https://github.com/semgrep/semgrep-rules "$tmp/src" 2>/dev/null; then
    for lang in $RULE_LANGS; do
      mkdir -p "$CACHE/$lang"
      cp -r "$tmp/src/$lang/." "$CACHE/$lang/" 2>/dev/null || true
    done
  else
    log "⚠ 無法抓 community 規則(離線?)—— 只用 nemofleet 自訂規則"
  fi
  rm -rf "$tmp"
fi
mkdir -p "$CACHE/nemofleet"; cp "$NEMOFLEET_ROOT"/config/semgrep/*.yaml "$CACHE/nemofleet/" 2>/dev/null || true
n="$(find "$CACHE" -name '*.yaml' | wc -l)"
[ "$n" -gt 0 ] || { log "無任何規則可用"; exit 1; }
log "✓ $n rule files staged → $CACHE ($RULE_LANGS + nemofleet custom)"
