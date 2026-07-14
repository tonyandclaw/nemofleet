#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# export-fleet.sh — bundle the WHOLE fleet's portable state (Layer 1) into one archive so the system
# can be moved to another host. Captures the fleet's identity + memory that isn't in git and isn't
# re-derivable at boot:
#   · secrets (bridge/approval tokens, the self-signed dashboard CA + TLS, NVD key, .env, dash users)
#   · ~/.config/nemoclaw state (the tamper-evident admin-audit chain + its HMAC key, the governance
#     ledger seen-set, the EBG19P device credential + audit, the notify env)
#   · host runtime data (proactive snapshots/logs, eval ledgers/lessons, skill r_task stats)
#   · each worker sandbox's WD (agent settings incl. patrol_auto, all scan + governance verdict
#     histories, EBG19P baselines + the known-good config backups, asset inventory) — docker cp'd out
# NOT captured (by design): container names / IPs / ports / OpenShell policies — boot-stack re-renders
# those from the secrets above (Layer 2); and the NemoClaw/OpenShell install + NIM + the physical
# EBG19P (Layer 3 — prerequisites on the target host, see docs/design/backup-restore.md).
#
# Usage: bash scripts/export-fleet.sh [--out <path.tar.gz>] [--gpg <recipient>]
#   default out: $HOME/nemofleet-export-<UTC-timestamp>.tar.gz  (chmod 600 — it holds every secret)
set -uo pipefail
OUT=""; GPG_TO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --gpg) GPG_TO="$2"; shift 2 ;;
    -h|--help) sed -n '6,22p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
TS="$(date -u '+%Y%m%d-%H%M%SZ')"
OUT="${OUT:-$HOME/nemofleet-export-$TS.tar.gz}"
WD_IN="/sandbox/.hermes/workspace/it-task"
NC_CFG="$HOME/.config/nemoclaw"
ok(){ printf '  \033[32m✓\033[0m %s\n' "$1"; }
skip(){ printf '  \033[33m·\033[0m %s\n' "$1"; }

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/nemofleet-export-$TS"
mkdir -p "$ROOT"/{bridge-secrets,nemoclaw-config,host-data,sandboxes,env}

echo "== nemofleet export $TS =="

# ── copy one file if it exists (into a dest dir), reporting ────────────────────────────────────
cp1(){ # $1=src $2=destdir $3=label
  if [ -e "$1" ]; then cp -a "$1" "$2/" 2>/dev/null && ok "$3" || skip "$3(複製失敗)"; else skip "$3(不存在,略過)"; fi
}

# ── 1) bridge secrets (dotfiles + pem + user db) ───────────────────────────────────────────────
for f in .bridge-token .bridge-token.prev .approval-key .approval-key.prev .nvd-api-key \
         dash-ca.pem dash-ca-key.pem dash-cert.pem dash-key.pem dash-ca.srl dash-users.json dash-auth.json; do
  cp1 "$BRIDGE_DIR/$f" "$ROOT/bridge-secrets" "bridge:$f"
done

# ── 2) ~/.config/nemoclaw state (audit chain + key, ledger seen-set, device cred, notify) ──────
for f in admin-audit.jsonl admin-audit.hmac-key gov-ledger-seen.json ebg19p.cred ebg19p-audit.jsonl nemofleet-notify.env; do
  cp1 "$NC_CFG/$f" "$ROOT/nemoclaw-config" "nemoclaw:$f"
done

# ── 3) .env ────────────────────────────────────────────────────────────────────────────────────
cp1 "$NEMOFLEET_ROOT/.env" "$ROOT/env" ".env"

# ── 4) host runtime data (proactive / eval / skill stats) ──────────────────────────────────────
mkdir -p "$ROOT/host-data/data" "$ROOT/host-data/eval/ledgers" "$ROOT/host-data/skills"
for f in "$DATA_DIR"/proactive-*; do [ -e "$f" ] && cp -a "$f" "$ROOT/host-data/data/" 2>/dev/null; done; ok "host-data: proactive-*"
[ -d "$EVAL_DIR/ledgers" ] && { cp -a "$EVAL_DIR/ledgers/." "$ROOT/host-data/eval/ledgers/" 2>/dev/null; ok "host-data: eval/ledgers"; }
cp1 "$EVAL_DIR/lessons.json" "$ROOT/host-data/eval" "host-data: eval/lessons.json"
cp1 "$SKILLS_DIR/skill-stats.json" "$ROOT/host-data/skills" "host-data: skills/skill-stats.json"

# ── 5) each worker sandbox's WD (the fleet's operational memory) ────────────────────────────────
for frag in "$WORKERA_CT_NAME" "$WORKERB_CT_NAME" "$WORKERC_CT_NAME"; do
  ct="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -m1 "openshell-$frag-" || true)"
  dest="$ROOT/sandboxes/$frag"; mkdir -p "$dest"
  if [ -z "$ct" ]; then skip "sandbox $frag(容器沒在跑,略過 —— restore 時該台無資料)"; continue; fi
  if docker exec "$ct" sh -c "[ -d $WD_IN ]" 2>/dev/null; then
    if docker cp "$ct:$WD_IN/." "$dest/" >/dev/null 2>&1; then
      # prune re-derivable caches: the SAST source clone (worker-b re-fetches it from GitHub on the
      # next scan) + python caches. Keeps the scan RESULTS/histories, drops the bulky raw inputs.
      rm -rf "$dest/source" "$dest"/__pycache__ 2>/dev/null; find "$dest" -name '*.pyc' -delete 2>/dev/null
      ok "sandbox $frag WD → $(find "$dest" -type f 2>/dev/null | wc -l | tr -d ' ') files (source/ 快取已略,restore 後重掃即重建)"
    else
      skip "sandbox $frag(docker cp 失敗)"
    fi
  else
    skip "sandbox $frag(WD $WD_IN 不存在)"
  fi
done

# ── 6) manifest (provenance + what a restore needs) ────────────────────────────────────────────
GIT_COMMIT="$(git -C "$NEMOFLEET_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY="$(git -C "$NEMOFLEET_ROOT" status --porcelain 2>/dev/null | grep -qv '^ M \(data/\|eval/\)' && echo yes || echo no)"
CUR_IP="$(primary_ip)"
NC_VER="$(nemoclaw --version 2>/dev/null | head -1 || echo unknown)"
cat > "$ROOT/MANIFEST.json" <<EOF
{
  "kind": "nemofleet-full-export",
  "schema": 1,
  "created_utc": "$TS",
  "source_host": "$(hostname 2>/dev/null || echo unknown)",
  "source_ip": "$CUR_IP",
  "git_commit": "$GIT_COMMIT",
  "git_uncommitted_changes": "$GIT_DIRTY",
  "nemoclaw_version": "$NC_VER",
  "worker_fragments": ["$WORKERA_CT_NAME", "$WORKERB_CT_NAME", "$WORKERC_CT_NAME"],
  "restore_prereqs": [
    "target host has NemoClaw + OpenShell installed and a running NIM (Nemotron) endpoint",
    "the 4 OpenShell sandboxes (team-lead + worker-a/b/c) already created (provisioning/onboard)",
    "repo checked out at git_commit above (git clone + checkout)",
    "network reachability to the EBG19P device (or a replacement at the same address)"
  ],
  "restore_cmd": "bash scripts/import-fleet.sh <this-bundle>"
}
EOF
ok "MANIFEST.json (git $GIT_COMMIT · ip $CUR_IP)"

# ── 7) archive + lock down (it holds every secret) ─────────────────────────────────────────────
mkdir -p "$(dirname "$OUT")"
tar czf "$OUT" -C "$STAGE" "nemofleet-export-$TS" 2>/dev/null
chmod 600 "$OUT"
if [ -n "$GPG_TO" ]; then
  if command -v gpg >/dev/null 2>&1; then
    gpg --yes --batch -r "$GPG_TO" -o "$OUT.gpg" -e "$OUT" && { rm -f "$OUT"; chmod 600 "$OUT.gpg"; OUT="$OUT.gpg"; ok "gpg-encrypted → $GPG_TO"; } || echo "  ⚠ gpg 加密失敗,保留未加密檔"
  else
    echo "  ⚠ 指定了 --gpg 但找不到 gpg,保留未加密檔(chmod 600)"
  fi
fi

SZ="$(du -h "$OUT" 2>/dev/null | cut -f1)"
echo
echo "== 完成:$OUT ($SZ) =="
echo "   ⚠ 這包含全部 token / key / 憑證 / 裝置密碼 —— 當作最高機密保管、加密傳輸。"
echo "   還原:bash scripts/import-fleet.sh $OUT   (先確保目標機的 Layer 3 前置就緒,見 docs/design/backup-restore.md)"
