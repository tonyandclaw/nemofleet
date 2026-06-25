#!/usr/bin/env bash
# scenarios.sh — switchable IT bug scenarios (OpenClaw = ASUS 網路產品 IT).
# 用法:BUG=subnet bash demo/it-collab.sh   (fw|subnet|bandwidth|dhcp,預設 fw)
#
# bug_scenario <name> 設定:BUG_FILE / BUG_MARKER(grep 驗收) / BUG_REQ(人類需求預設)
#   / BUG_HCTX(Hermes 前台 triage 情境) / BUG_OC(給 OpenClaw 的 bug 描述,caller 補路徑與 read/write 指示)
bug_scenario() {
  case "${1:-fw}" in
    fw|firmware)
      BUG_FILE=fwcheck.py; BUG_MARKER='STATUS=UPDATE_AVAILABLE'
      BUG_REQ='AiMesh 路由器後台一直顯示「已是最新韌體」,但雲端其實有新版,客戶裝不到更新,請工程端查修。'
      BUG_HCTX='客戶回報:ASUS 路由器後台韌體檢查顯示『已是最新』,但雲端其實有新版(漏更新)。'
      BUG_OC='是路由器韌體更新檢查腳本,有 bug:現役版本 386_59、雲端最新 386_510,應印 STATUS=UPDATE_AVAILABLE(偵測到新版),卻印 UP_TO_DATE。根因是把版本號當「字串」比較("386_59" > "386_510")。請把版本號的 build number(底線後的數字)解析成整數再比較。' ;;
    subnet)
      BUG_FILE=subnet.py; BUG_MARKER='HOSTS=62'
      BUG_REQ='路由器 LAN 設定頁顯示 /26 子網路可用 IP 數是 64,但實際配到第 63、64 個就跟網路/廣播位址衝突,請工程端查修。'
      BUG_HCTX='客戶回報:路由器 LAN /26 可用 IP 數顯示 64(應為 62),沒扣掉網路位址與廣播位址。'
      BUG_OC='是子網路可用主機數計算腳本,有 bug:/26 應印 HOSTS=62,卻印 64。根因是 2**(32-prefix) 沒扣掉「網路位址」與「廣播位址」這兩個保留位址。請改成減 2。' ;;
    bandwidth|bw)
      BUG_FILE=throughput.py; BUG_MARKER='SECONDS=80'
      BUG_REQ='路由器 QoS 頁面估算 1000MB 檔案在 100Mbps 線路的傳輸時間,顯示約 10 秒明顯太樂觀,實際要 80 秒,請工程端查修。'
      BUG_HCTX='客戶回報:路由器頻寬/傳輸時間估算錯誤,把 Mbps 當成 MB/s,少除以 8。'
      BUG_OC='是傳輸時間估算腳本,有 bug:100 Mbps 傳 1000 MB 應印 SECONDS=80.0,卻印 10.0。根因是把 Mbps(bit/s)當成 MB/s(byte/s),漏了 bit→byte 要除以 8。請把頻寬除以 8 再算秒數。' ;;
    dhcp)
      BUG_FILE=dhcp.py; BUG_MARKER='POOL=101'
      BUG_REQ='路由器 DHCP 設定的位址池 192.168.1.100–192.168.1.200,後台顯示可配發 100 個,但含頭尾應該是 101 個,請工程端查修。'
      BUG_HCTX='客戶回報:DHCP 位址池 .100–.200 顯示 100 個(含頭尾應為 101),少算 1。'
      BUG_OC='是 DHCP 位址池大小計算腳本,有 bug:位址池 .100–.200 含頭尾應印 POOL=101,卻印 100。根因是 end-start 沒有 +1(區間含頭尾)。請改成 end-start+1。' ;;
    drift)
      # 真實機隊場景(素材:enterprise-deck RT-AX89X baseline/current)。多檔場景,
      # 僅 bridge 端點路徑支援(POST /fix {"bug":"drift"});it-collab/it-fix 的單檔流程不適用。
      BUG_FILE=rt-ax89x-current.conf; BUG_MARKER='REGRESSIONS=0'
      BUG_REQ='lab 一台 RT-AX89X 的設定被人改過:SSH 密碼登入被打開、遠端 logging 被關掉,都是安全退化,請工程端比對核准基準修回,其他變更列出待審。'
      BUG_HCTX='網管回報:RT-AX89X 設定漂移——SSH 密碼登入被打開(暴破風險)、遠端 logging 被關(出事查不到 log),須修回已核准 baseline;另有 wifi 頻道/頻寬、ssh.port 變更待人審。'
      BUG_OC='(drift 為多檔場景,由 bridge 端點植入 baseline/current/driftcheck 並驗收 REGRESSIONS=0;見 services/bridge/openclaw-fix-endpoint.py)' ;;
    *) echo "[lib] 未知 BUG 場景:$1 (可用:fw|subnet|bandwidth|dhcp|drift〔drift 僅 bridge 路徑〕)" >&2; return 2 ;;
  esac
}

# bug_emit <name> -> 把該場景「有 bug 的」python 印到 stdout(caller 重導成檔)
bug_emit() {
  case "${1:-fw}" in
    fw|firmware) cat <<'PY'
# fwcheck.py — 路由器韌體更新檢查
# 現役版本 386_59,雲端最新 386_510;應偵測到新版 → STATUS=UPDATE_AVAILABLE
cur, latest = "386_59", "386_510"
status = "UP_TO_DATE" if cur >= latest else "UPDATE_AVAILABLE"  # BUG: 版本號用字串比較,"59" > "510"
print(f"STATUS={status}")
PY
    ;;
    subnet) cat <<'PY'
# subnet.py — 路由器 LAN 子網路可用主機數;/26 應印 HOSTS=62
prefix = 26
hosts = 2 ** (32 - prefix)         # BUG: 漏扣網路位址與廣播位址(應 -2)
print(f"HOSTS={hosts}")
PY
    ;;
    bandwidth|bw) cat <<'PY'
# throughput.py — 100 Mbps 線路傳 1000 MB 的預估秒數;應印 SECONDS=80.0
mbps, size_mb = 100, 1000
seconds = size_mb / mbps           # BUG: Mbps(bit/s) 當成 MB/s(byte/s),漏除以 8
print(f"SECONDS={seconds}")
PY
    ;;
    dhcp) cat <<'PY'
# dhcp.py — DHCP 位址池 .100–.200(含頭尾);應印 POOL=101
start, end = 100, 200
pool = end - start                 # BUG: 含頭尾應 +1
print(f"POOL={pool}")
PY
    ;;
  esac
}
