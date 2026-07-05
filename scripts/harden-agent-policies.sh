#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# harden-agent-policies.sh — least-privilege: strip the default OpenShell presets that ship with the
# base Hermes sandbox but that NO agent's job uses, so a compromised agent can't reach them.
#
# Rationale (see the security review): deny-by-default only helps if the allowlist is tight. Each
# agent shipped with brew / huggingface / npm / pypi (4 supply-chain package sources), weather (a
# demo skill) and local-inference (unused — the fleet uses managed_inference). None are needed at
# runtime; brew even ships a '*' wildcard binary allow reaching github.com + ghcr.io. What each
# agent actually needs (telegram / worker-bridge / managed_inference / the github+device endpoints)
# is either a kept preset or an --add-endpoint rule, so none of the removals below touch real needs.
#
# Idempotent: only revokes presets that are currently applied; safe to re-run. boot-stack calls it
# after the allow-* scripts so least-privilege is re-asserted on every rebuild.
set -uo pipefail

# presets no agent needs at runtime — revoked from ALL agents
BLOAT_ALL="weather brew huggingface local-inference npm"
# pypi: only *maybe* needed by worker-b (SBOM/SAST tooling) — left there for review; stripped elsewhere
declare -A EXTRA=( ["team-lead"]="pypi" ["worker-a"]="pypi" ["worker-c"]="pypi" )
# NOTE: nvidia + nous_research are base-image network config (not presets) → not removable here;
#       flagged in the review, needs a base-image change to drop.

command -v nemoclaw >/dev/null 2>&1 || { echo "[harden] nemoclaw CLI 不可用" >&2; exit 1; }

total_removed=0
for a in team-lead worker-a worker-b worker-c; do
  # applied presets for this agent (● = applied)
  applied="$(nemoclaw "$a" policy-list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk '/●/{print $2}')" || true
  [ -n "$applied" ] || { echo "[harden] $a 未就緒(略過)"; continue; }
  removed=""
  for preset in $BLOAT_ALL ${EXTRA[$a]:-}; do
    printf '%s\n' "$applied" | grep -qx "$preset" || continue   # only if currently applied
    if nemoclaw "$a" policy-remove "$preset" --yes >/dev/null 2>&1; then
      removed="$removed $preset"; total_removed=$((total_removed + 1))
    else
      echo "[harden] ⚠ $a: policy-remove $preset 失敗"
    fi
  done
  echo "[harden] $a — revoked:${removed:- (none, already lean)}"
done
echo "[harden] ✓ least-privilege sweep 完成($total_removed 個 preset 收回)"
