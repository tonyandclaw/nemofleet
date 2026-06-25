#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# lessons-to-skill.sh — 把 eval/lessons.json 的負案例糾正渲染成常駐 SKILL.md,沉澱進 Hermes 與/或 OpenClaw。
# 讓「教訓」從外部回灌檔升級成 agent 自身持久知識(跨 session、可隨 snapshot 還原)。
# 關鍵:docker cp 進沙箱後一律 chown 998(否則 agent EACCES、snapshot pre-backup audit 會 exit 1)。
# 用法:lessons-to-skill.sh [hermes|openclaw|both]   (預設 both)
set -euo pipefail
DIR=$NEMOFLEET_ROOT
:
TARGET="${1:-both}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 渲染 SKILL.md(讀 lessons.json + tasks.jsonl 的 desc 當情境)
python3 - "$DIR/eval/lessons.json" "$DIR/eval/tasks.jsonl" > "$TMP/SKILL.md" <<'PY'
import json,sys,os
lessons=json.load(open(sys.argv[1])) if os.path.exists(sys.argv[1]) else {}
desc={}
for l in open(sys.argv[2]):
    l=l.strip()
    if l:
        t=json.loads(l); desc[t["id"]]=t.get("desc","")
print("---")
print("name: lessons-learned")
print("description: 過去任務中犯過的錯與對應糾正(負案例)。在產出結構化/格式化內容、或引用內部資訊前,先讀本技能避免重蹈覆轍。")
print("---")
print("# 過去教訓(負案例 → 糾正)\n")
print("這些是 eval 中失敗過、已沉澱的具體糾正。產出前請逐條自我檢查:\n")
if not lessons:
    print("_(目前無未解教訓 — 全部任務通過)_")
else:
    for tid,items in lessons.items():
        print(f"## {tid}（{desc.get(tid,'')}）")
        for it in items:
            print(f"- {it}")
        print()
PY

n=$(python3 -c "import json,os;p='$DIR/eval/lessons.json';print(sum(len(v) for v in json.load(open(p)).values()) if os.path.exists(p) else 0)")
echo "[lessons2skill] 渲染 $n 條教訓,目標=$TARGET"

install_into() {  # $1=container $2=skill父目錄
  local ct="$1" base="$2"
  [ -n "$ct" ] || { echo "[lessons2skill] 略過(容器未找到)" >&2; return 0; }
  local sd="$base/lessons-learned"
  docker exec "$ct" sh -lc "mkdir -p $sd"
  docker cp "$TMP/SKILL.md" "$ct:$sd/SKILL.md"
  docker exec -u 0 "$ct" sh -lc "chown -R 998:998 $sd && chmod -R a+rX $sd"   # 必須:避免 EACCES / snapshot audit 失敗
  echo "[lessons2skill] ✓ 安裝 $ct:$sd/SKILL.md (chown 998)"
}

case "$TARGET" in
  hermes)   install_into "$CT_H" "$HSKILLS_SUB" ;;
  openclaw) install_into "$CT_O" "$OCSKILLS" ;;
  both)     install_into "$CT_H" "$HSKILLS_SUB"; install_into "$CT_O" "$OCSKILLS" ;;
  *) echo "用法:$0 [hermes|openclaw|both]" >&2; exit 2 ;;
esac
