#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# policy-prove-demo.sh — 主題1 資安加值:把治理從「跑一次看 log 擋了」升級成「形式化證明」。
# openshell policy prove 對 sandbox policy 做**靜態窮舉**:列出所有潛在資料外洩路徑(可讀檔 → 外部端點),
# 找不到反例才 PASS。這是「治理是 code,可被工具證明」的最強佐證——不是動態觀察,是形式化分析。
#
# 誠實 framing(demo 時照講):prove 目前對兩台都報 1 個 CRITICAL gap,但**反例全部落在**
#   為了裝套件(github/npm/brew/ghcr)、跨 agent 通道(:9099)、本地 mail/jira(3993/3587/3690)
#   而**必開的白名單端點**,且都是 L4-only(沒有 HTTP body 檢查)。這跟攻擊 demo 不矛盾:
#   - 攻擊 demo(security-demo S1 / demo_telegram B2):**非白名單**主機 → 動態 DENIED(host 層)。
#   - prove 量化的是**白名單內**套件端點的 L4 放行面 —— 已知、必要、可收斂。
# 賣點:成熟的安全不是宣稱零風險,是能把風險**窮舉、量化、指名道姓**。下一步 least-privilege=
#   這些端點上 L7 path 強制,或用 --accepted-risks 登記為已知必要風險。
# 零成本(本地靜態分析,不耗 Azure)。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
cd "$DIR"; :
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

CREDS=$(mktemp /tmp/prove-creds.XXXX.yaml); printf 'version: 1\ncredentials: []\n' > "$CREDS"
trap 'rm -f "$CREDS" /tmp/prove-*.yaml' EXIT

prove_one() {  # $1 = sandbox 名
  local sb="$1" pf="/tmp/prove-${1}.yaml"
  openshell policy get "$sb" --full 2>/dev/null | awk 'f;/^---$/{f=1}' > "$pf"
  if [ ! -s "$pf" ]; then echo "  ⚠ 拿不到 $sb 的 active policy(gateway 在線?)"; return 0; fi
  echo "  policy: $(wc -l < "$pf") 行(active,直接取自 live gateway)"
  openshell policy prove --policy "$pf" --credentials "$CREDS" --compact 2>&1 | sed 's/^/    /'
}

hr "形式化證明:openshell policy prove(靜態窮舉外洩面,非跑一次看 log)"
echo "對兩個沙箱的**當前 active policy** 跑形式化分析:"
echo
echo "▶ Hermes(對人前台沙箱)"
prove_one hermes-demo
echo
echo "▶ OpenClaw(IT 機隊沙箱)"
prove_one my-assistant

hr "怎麼讀這個結果(demo 講點)"
cat <<'EOF'
  • prove 列出的反例,全部落在「為了功能必開的白名單端點」:
      - 套件登記:github.com / registry.npmjs.org / formulae.brew.sh / ghcr.io …(裝 npm/pypi/brew 用)
      - 跨 agent 通道:172.18.0.2:9099(已另有 /32 + X-Bridge-Token + binary 白名單三重鎖)
      - 本地服務:host.openshell.internal:3993/3587(mail)、3690(jira)—— 全在 host loopback,不出機器
    全是 L4-only(TCP 層放行、無 HTTP body 檢查)。
  • 對照攻擊 demo:**非白名單**主機(example.com / smtp.gmail.com)→ 動態 DENIED(host 層,security-demo S1)。
    prove 量化的是**白名單內**的 L4 放行面,不是「任意外洩」。兩者一致:白名單外擋死、白名單內可見可管。
  • 價值:治理不是嘴上說的。我們能用工具把外洩面**窮舉、量化、指名道姓**(Hermes 59 條路徑、12 個可讀來源)。
    這比宣稱「零風險」誠實得多 —— 安全的下一步(least-privilege)有了可度量的清單:
      上 L7 path 強制,或 --accepted-risks 登記這些已知必要端點 → 再 prove 即可收斂到 PASS。
EOF
