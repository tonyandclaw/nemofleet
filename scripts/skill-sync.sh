#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# skill-sync.sh — copy a learned skill from one agent's skills dir to the other.
# Cross-agent knowledge sharing (file-level). Hermes & worker use the same SKILL.md format.
# Usage: skill-sync.sh <lead2worker|worker2lead> <skill-name>
set -euo pipefail

:
DIR="${1:?direction: lead2worker|worker2lead}"
NAME="${2:?skill name}"
TMP="$BUS_DIR/skill-xfer-$$"
mkdir -p "$TMP"; trap 'rm -rf "$TMP"' EXIT

# 來源 root 用整棵 skills 樹(技能可能在任何分類子目錄,如 productivity/、devops/);目標 TO 用各自既定落點。
case "$DIR" in
  lead2worker) FROM_CT=$CT_LEAD; SRC_ROOT=$HSKILLS;  TO_CT=$CT_WA; TO=$WSKILLS ;;
  worker2lead) FROM_CT=$CT_WA; SRC_ROOT=$WSKILLS; TO_CT=$CT_LEAD; TO=$HSKILLS_SUB ;;
  *) echo "unknown direction: $DIR" >&2; exit 2 ;;
esac

# 動態解析來源技能目錄(不寫死分類)
SRC=$(docker exec "$FROM_CT" sh -lc "find $SRC_ROOT -maxdepth 3 -type d -name '$NAME' 2>/dev/null | head -1")
[ -n "$SRC" ] || { echo "[sync] 找不到技能 '$NAME' 於 $SRC_ROOT" >&2; exit 3; }
echo "[sync] $DIR  skill=$NAME  $SRC -> $TO/$NAME"
# overwrite-protection: skip if target already has it (unless --force as $3)
if docker exec "$TO_CT" sh -lc "[ -e $TO/$NAME ]" 2>/dev/null && [ "${3:-}" != "--force" ]; then
  echo "[sync] target already has '$NAME' — skipping (pass --force to overwrite)"; exit 0
fi
docker cp "$FROM_CT:$SRC" "$TMP/$NAME"                   # source sandbox -> host tmp
# provenance marker so we know it was synced, not native
printf 'synced_from=%s\nskill=%s\nat=%s\n' "$DIR" "$NAME" "$(date -Is)" > "$TMP/$NAME/.synced-from"
docker cp "$TMP/$NAME" "$TO_CT:$TO/$NAME"                # host tmp -> target sandbox
# docker cp 進來的檔由 root/node 擁有(0770),sandbox(998)進不去 → 會讓 snapshot 的 pre-backup audit(以 998 跑 find)exit 1。chown 998 根治。
docker exec -u 0 "$TO_CT" sh -lc "chown -R 998:998 $TO/$NAME" 2>/dev/null || true
echo "[sync] done. verifying on target:"
docker exec "$TO_CT" sh -lc "ls -d $TO/$NAME && head -3 $TO/$NAME/SKILL.md && echo '-- provenance --' && cat $TO/$NAME/.synced-from"
