#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# audit-rebaseline.sh — safely re-baseline the tamper-evident admin-audit chain after a *benign* HMAC
# key rotation (the usual cause: a whole-system restore/import that copied an older admin-audit.hmac-key
# over the running one, so entries written before the restore no longer verify under the current key).
#
# 這不是在「洗綠」帳本:絕不會用新金鑰重算任何一筆舊 hash(那等於偽造,正是 verify_audit() 該抓的)。
# 它做的是誠實的重定基線 —— 把整份舊鏈「原封封存」到 dated 檔案(留存供鑑識),再在現行金鑰下寫一筆
# `audit-rebaseline` genesis marker(其 detail 以雜湊指回封存鏈的最後一個 hash,讓這次輪替本身可稽核),
# 之後的稽核事件就從這個 marker 續鏈。
#
# When you'd run this: the dashboard footer / Overview attention strip shows "audit chain broken" AND
# you've confirmed the cause is a known-benign key rotation (not tampering). If you can't rule out
# tampering, DON'T run this — investigate the archived log first.
#
# Usage:
#   bash scripts/audit-rebaseline.sh --dry-run     # diagnose only: is it broken, where, how many orphaned
#   bash scripts/audit-rebaseline.sh               # interactive: diagnose → confirm → archive + re-baseline
#   bash scripts/audit-rebaseline.sh --yes         # non-interactive (skip the confirm prompt)
#
# Honors DASH_AUDIT_FILE / DASH_AUDIT_KEY_FILE overrides (same as agent-dashboard.py).
set -uo pipefail
export NEMOFLEET_ROOT

YES=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)     YES=1; shift ;;
    -n|--dry-run) DRY=1; shift ;;
    -h|--help)    sed -n '6,25p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ok(){   printf '  \033[32m✓\033[0m %s\n' "$1"; }
skip(){ printf '  \033[33m·\033[0m %s\n' "$1"; }
bad(){  printf '  \033[31m✗\033[0m %s\n' "$1"; }

dashboard_up(){ curl -sk -m3 -o /dev/null -w '%{http_code}' "https://127.0.0.1:$DASH_PORT/login" 2>/dev/null | grep -q 200 \
             || curl -s  -m3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$DASH_PORT/login"  2>/dev/null | grep -q 200; }

# audit_py <mode> [ts]  — reuses agent-dashboard.py's own audit()/verify_audit()/_audit_key() so the
# format + HMAC(current key) are byte-for-byte identical to what the live dashboard writes.
audit_py(){
  python3 - "$@" <<'PYEOF'
import importlib.util, os, json, sys, hmac, hashlib
mode = sys.argv[1]
root = os.environ["NEMOFLEET_ROOT"]
spec = importlib.util.spec_from_file_location("dash", os.path.join(root, "services/bridge/agent-dashboard.py"))
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
LOG = d.ADMIN_AUDIT

def load():
    try:
        return [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return None

if mode == "diagnose":
    rows = load()
    if rows is None:
        print("MISSING"); sys.exit(0)
    if not rows:
        print("EMPTY"); sys.exit(0)
    res = d.verify_audit()
    key = d._audit_key()
    match = [hmac.compare_digest(e.get("hash") or "",
             hmac.new(key, ((e.get("prev_hash") or "") + d._audit_canon(e)).encode(), hashlib.sha256).hexdigest())
             for e in rows]
    good = sum(match)
    # one clean rotation shows as a single False->True transition; report it if so
    trans = [rows[i].get("seq") for i in range(1, len(rows)) if match[i] != match[i-1]]
    print(f"COUNT={len(rows)}")
    print(f"VERIFY_OK={'1' if res['ok'] else '0'}")
    print(f"BREAK_SEQ={res.get('broken')}")
    print(f"VALID_UNDER_CURRENT_KEY={good}")
    print(f"ORPHANED={len(rows)-good}")
    print(f"TRANSITIONS={','.join(str(t) for t in trans) if trans else '-'}")
    print(f"FIRST_TS={rows[0].get('ts')}")
    print(f"LAST_TS={rows[-1].get('ts')}")
    print("STATE=" + ("ok" if res["ok"] else "broken"))
    sys.exit(0)

if mode == "rebaseline":
    ts = sys.argv[2]
    rows = load() or []
    old_count = len(rows)
    old_last_hash = rows[-1]["hash"] if rows else "0"*64
    old_first_ts = rows[0].get("ts") if rows else "-"
    old_last_ts  = rows[-1].get("ts") if rows else "-"
    archive = LOG + f".pre-rebaseline-{ts}"
    if os.path.exists(LOG):
        os.rename(LOG, archive)          # atomic; preserves the old bytes + perms verbatim (no rewrite)
    detail = (f"chain re-baselined after benign HMAC key rotation. prior {old_count}-entry chain "
              f"({old_first_ts} .. {old_last_ts}) archived verbatim to {os.path.basename(archive)}; "
              f"prior last hash={old_last_hash[:16]}")
    d.audit("system", "audit-rebaseline", detail, "127.0.0.1", True, detail_en=detail)
    res = d.verify_audit()
    print(f"ARCHIVE={archive}")
    print(f"ARCHIVED_COUNT={old_count}")
    print(f"NEW_VERIFY_OK={'1' if res['ok'] else '0'}")
    sys.exit(0 if res["ok"] else 1)

print("bad mode", file=sys.stderr); sys.exit(2)
PYEOF
}

echo "── audit chain 診斷 ─────────────────────────────────────────"
DIAG="$(audit_py diagnose)" || { bad "診斷失敗(無法載入 agent-dashboard.py)"; exit 1; }
STATE="$(printf '%s\n' "$DIAG" | sed -n 's/^STATE=//p')"

case "$STATE" in
  "")
    if printf '%s' "$DIAG" | grep -q MISSING; then skip "找不到 audit log(尚未有任何稽核事件)—— 無需處理"; exit 0; fi
    if printf '%s' "$DIAG" | grep -q EMPTY;   then skip "audit log 為空 —— 無需處理"; exit 0; fi
    bad "診斷輸出無法解析"; printf '%s\n' "$DIAG"; exit 1 ;;
  ok)
    ok "稽核鏈目前已通過驗證(verify_audit ok)—— 無需重定基線"
    printf '%s\n' "$DIAG" | sed -n 's/^/    /p'; exit 0 ;;
esac

# --- broken: show the forensic summary ---
_g(){ printf '%s\n' "$DIAG" | sed -n "s/^$1=//p"; }
echo "  狀態: 斷裂(broken)"
echo "  總筆數           : $(_g COUNT)   ($(_g FIRST_TS) .. $(_g LAST_TS))"
echo "  首個斷點 seq     : $(_g BREAK_SEQ)"
echo "  現行金鑰可驗證   : $(_g VALID_UNDER_CURRENT_KEY) 筆"
echo "  被孤立(舊金鑰)  : $(_g ORPHANED) 筆"
echo "  金鑰轉換點 seq   : $(_g TRANSITIONS)   (單一轉換點 = 乾淨的一次輪替,良性徵兆)"
echo "─────────────────────────────────────────────────────────────"

if [ "$DRY" = 1 ]; then skip "--dry-run:只診斷,不變更"; exit 0; fi

echo "將執行:把上述 $(_g COUNT) 筆舊鏈『原封封存』到 dated 檔案,再於現行金鑰下寫一筆 audit-rebaseline"
echo "genesis marker(指回封存鏈)。舊資料一筆都不會改寫。"
echo "⚠ 只有在你已確認斷裂是『良性金鑰輪替(如還原/匯入)』而非竄改時才繼續。"
if [ "$YES" != 1 ]; then
  if [ ! -t 0 ]; then bad "非互動環境且未帶 --yes,已中止(不擅自變更帳本)"; exit 1; fi
  printf "確定要重定基線?輸入 yes 繼續: "; read -r ans
  [ "$ans" = "yes" ] || { skip "已取消"; exit 0; }
fi

# --- stop the live dashboard (if up) to avoid a concurrent audit write racing the archive+genesis ---
WAS_UP=0
if dashboard_up; then
  WAS_UP=1
  pkill -f "$BRIDGE_DIR/agent-dashboard.py" >/dev/null 2>&1
  for i in $(seq 8); do dashboard_up || break; sleep 1; done
  dashboard_up && { bad "儀表板仍在跑,無法安全重定基線(請手動停止後重試)"; exit 1; } || ok "已暫停儀表板"
else
  skip "儀表板未在跑 —— 直接重定基線"
fi

TS="$(date +%Y%m%d-%H%M%S)"
OUT="$(audit_py rebaseline "$TS")"; RC=$?
printf '%s\n' "$OUT" | sed -n 's/^ARCHIVE=/  封存至: /p'
if [ "$RC" = 0 ] && printf '%s' "$OUT" | grep -q '^NEW_VERIFY_OK=1'; then
  ok "重定基線完成:封存 $(printf '%s' "$OUT" | sed -n 's/^ARCHIVED_COUNT=//p') 筆,新鏈 verify_audit ok"
else
  bad "重定基線後驗證未通過 —— 請檢查"; printf '%s\n' "$OUT" | sed -n 's/^/    /p'
fi

# --- restart the dashboard the same way boot-stack's ensure_dashboard does (mirror it if that drifts) ---
if [ "$WAS_UP" = 1 ]; then
  DASH_BIND=0.0.0.0 DASH_TLS=1 DASHBOARD_PORT="$DASH_PORT" DASH_TRUST_XFF="${DASH_TRUST_XFF:-}" \
    setsid python3 "$BRIDGE_DIR/agent-dashboard.py" >/tmp/agent-dashboard.log 2>&1 < /dev/null &
  for i in $(seq 8); do dashboard_up && break; sleep 1; done
  dashboard_up && ok "儀表板已重啟(:$DASH_PORT)" || bad "儀表板未重啟(cat /tmp/agent-dashboard.log)"
fi
