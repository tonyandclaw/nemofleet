# EVIDENCE.md — 宣稱 → 證據矩陣(競賽 PPTX 每條可驗證宣稱對得到實測)

> 用途:評審問「這是真的嗎」時,逐條攤開可重現指令 + 預期鐵證。對應檔=`ASUS-AgenticAI-Competition-2026.pptx`。
> 前置:`bash scripts/boot-stack.sh` → `bash scripts/healthcheck.sh` 全綠。桌面變數(demo_telegram §0):
> ```bash
> cd ~/nemofleet
> CT_H=$(docker ps --format '{{.Names}}' | grep -m1 hermes-demo)
> CT_O=$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)
> TOKEN=$(cat bridge/.bridge-token)
> OCIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT_O")
> ```
> 「成本」欄:零=確定性無 LLM;Azure=耗 1 個 Kimi turn(段間留 ≥1 分鐘避 429)。

## A. 報修主線與修復(實用 55%;PPTX slide 8/9/10)

| # | 宣稱 | 可重現指令 | 預期鐵證 | 成本 |
|---|---|---|---|---|
| A1 | 一句話報修 → Hermes 自委派 OpenClaw(唯一 scoped 通道) | `bash tests/bridge-regress.sh drift`(或手機走 demo_telegram A1) | `ALLOWED /usr/bin/curl(...) -> POST http://<OCIP>:9099/fix [policy:openclaw_bridge engine:opa]` | Azure |
| A2 | 只修「安全退化」5→0 | 同 A1,看端點 log | `[FIX DONE] bug=drift ... REGRESSIONS=5 -> REGRESSIONS=0` | Azure |
| A3 | 一般漂移 3 處**不動**、列待審開 Jira | 同 A1 後:`docker exec "$CT_O" sh -c "curl -s -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/jira"` | `DRIFTS=3(ssh.port,wifi.5g.bandwidth,wifi.5g.channel)` + `NETOPS-...` change-approval 工單 assignee=network-engineer | 零 |
| A4 | 44 秒報修→修復(實測) | `bash tests/bridge-regress.sh drift`(腳本自計時) | `✅ 委派鏈端到端 PASS`,實測 ~44s | Azure |
| A5 | 2 入口 Telegram + Email,換通道不換治理 | Telegram=demo_telegram A1;Email=`bash mail-demo/send-customer-mail.sh ...; bash mail-demo/read-inbox.sh 1` | `ALLOWED /usr/bin/socat -> host.openshell.internal:3993 [policy:greenmail_mail engine:opa]` | 低 |

歸屬:Hermes 判型派工(對人前台)→ scoped `openclaw_bridge`(/32+token)→ OpenClaw 實修+驗收(driftcheck.py)→ Hermes 結案。

## B. 監控 / CVE / 原始碼(實用 + 資安;PPTX slide 5/6/10)

| # | 宣稱 | 可重現指令 | 預期鐵證 | 成本 |
|---|---|---|---|---|
| B1 | 主動監控「自己發現」(不靠人巡) | `bash demo/monitor-alert-demo.sh --no-push` | `[ALERT(5 安全退化)] lab-asus-rt-ax89x-01` + 端點 log `[MONITOR ALERT]` | 零 |
| B2 | **定期**掃 CVE、機隊分級、affected 開 Jira | `bash scripts/cve-scan.sh` | `affected 2 / needs_review 1 / unknown_inventory_gap 12` + 內建排程歷史 `cve-scan-history.jsonl`(trigger=schedule) | 零 |
| B3 | 修不了/affected → Jira 升級(受治理 egress) | 同 B2,看 OpenClaw log | `ALLOWED /usr/bin/curl(...) -> POST http://host.openshell.internal:3690/rest/api/2/issue [policy:jira engine:opa]` | 零 |
| B4 | 查 source code **及 design document** 自家安全掃描 | `bash demo/source-cve-demo.sh` | SBOM 4 套件 + SAST(CWE-78 diag.c:9 / CWE-798 auth.c:4)+ 設計符合性 `違反 2/5`(REQ-SEC-04/05),違反條款寫進工單 | 零 |
| B5 | 主動告警推手機(slide 5/6「凌晨兩點」痛點閉環) | `bash demo/monitor-alert-demo.sh`(去掉 --no-push) | `ALLOWED POST api.telegram.org:443/bot[CREDENTIAL]/sendMessage [policy:telegram engine:l7]`(看手機收到告警) | Azure |
| B6 | 機隊 **2 節點職責分工**(運維 vs 資安,非複本) | 節點A:`docker exec <my-assistant> .../monitor`、`/cve`;節點B 同對 `<openclaw-2>` | **節點A=IT 運維**(caps monitor+fix):巡 rt-ax89x+ebg19p、修報修/漂移、不掃 CVE(回職責提示);**節點B=資安**(caps cve+source+monitor):巡 openwrt、CVE 掃**全機隊 6 台 2 affected**、SBOM/SAST/讀設計文件;`BRIDGE_ZONE`+`ZONE_CAPS`、policy 兩節點各 /32 | 零 |
| B7 | Hermes 依**職責路由**到對應節點 | Hermes netns → `172.18.0.2:9099`(節點A 運維)或 `172.18.0.4:9099`(節點B 資安) | OPA `ALLOWED /usr/bin/curl → 172.18.0.4:9099 [policy:openclaw_bridge engine:opa]`;SKILL 教運維報修/漂移→A、OpenWrt/CVE/原始碼/SBOM→B | 低 |

歸屬:OpenClaw 監控職責=狀態巡檢(現況 vs 核准基準)+ 定期 CVE + 有 source/設計文件時加 SBOM/SAST/符合性。

## C. 資安對照:同一套系統,正常放行 / 越權擋下(資安 10%;PPTX slide 11)

正常行為(ALLOWED):

| # | 宣稱 | 指令 | 鐵證 |
|---|---|---|---|
| C1 | 跨 agent 委派受治理 | A1 | `ALLOWED POST :9099/fix [policy:openclaw_bridge engine:opa]` |
| C2 | 收發 Telegram / Email | A5 / demo A0 | `[policy:telegram]` / `[policy:greenmail_mail]` |
| C3 | 開 Jira 升級 | B3 | `[policy:jira engine:opa]` |

攻擊行為(DENIED / 遮罩):

| # | 宣稱 | 可重現指令 | 預期鐵證 | 成本 |
|---|---|---|---|---|
| C4 | 偷用委派端點不帶 token → 403 | `bash demo/security-demo.sh`(S8)或 demo_telegram B1 | `無 token POST /fix → 403`(端點拒收) | 零 |
| C5 | 外連非白名單主機 → DENIED(host 層) | `security-demo.sh`(S1)或 demo B2 | `DENIED ... [policy:- engine:opa]` | 低 |
| C6 | 換未授權 binary(curl)→ DENIED(binary 層) | `security-demo.sh`(S4) | `DENIED ... curl ...`(同主機同埠 socat/python3 反而 ALLOWED) | 低 |
| C7 | 要 API key → placeholder | demo_telegram B3 | `.env` 內 `TELEGRAM_BOT_TOKEN=openshell:resolve:env:...`(真值僅 egress 注入) | 零 |
| C8 | log 裡 token → 遮罩 | `security-demo.sh`(S7) | token 一律 `[CREDENTIAL]` | 零 |
| C9 | 要求轉帳 → 能力邊界擋下 | `security-demo.sh --behavioral`(S6) | Hermes 拒絕「無金融交易功能/權限」+ 0 筆金流 egress | Azure |
| C10 | 未授權寄件者 → 模型沒被呼叫 | `security-demo.sh`(S2)或 demo B5 | `Unauthorized user: evil@demo.local` | 低 |

歸屬:OpenShell OPA host/path/binary 三層 + L7 MITM 憑證遮罩 + 跨 agent /32+token + Hermes harness 授權層 + 能力邊界。

## D. 技術 / 生命週期 / 未來(技術 15%;PPTX slide 10/18)

| # | 宣稱 | 可重現指令 | 預期鐵證 | 成本 |
|---|---|---|---|---|
| D1 | NemoClaw 管 agent 生命週期(快照/復原) | `nemoclaw hermes-demo snapshot list` | 多版本快照(含 `combine-pre-loop-0612`);`snapshot restore <name>` 跨重建存活 | 零 |
| D2 | NemoClaw × NVIDIA:推理 provider 可切換 + 治理路徑 | `bash demo/nvidia-inference-demo.sh` | `ALLOWED /usr/bin/python3 -> integrate.api.nvidia.com [policy:nvidia engine:opa]` + `[policy:nvidia engine:l7]`(無 key 回 401=路徑通) | 零 |
| D3 | 兩沙箱完全隔離,唯一互通=scoped 通道 | `openshell policy get hermes-demo --full | grep openclaw_bridge` | `allowed_ips: <OCIP>/32`(只通一台一埠) | 零 |
| D4 | 治理是 code 不是 prompt(三層強制) | C4–C10 任一 | `engine:opa` / `engine:l7` 標記(程式碼層,非提示語) | — |
| D5 | 治理可被**形式化證明**(非跑一次看 log) | `bash demo/policy-prove-demo.sh` | `policy prove` 對 active policy 靜態窮舉外洩面(Hermes 59 路徑/12 可讀源);反例全落在套件登記/跨agent/本地mail-jira 的白名單 L4 端點,對照「非白名單→動態 DENIED」一致;誠實量化 least-privilege roadmap | 零 |
| D6 | 治理**可量化**(可觀測性儀表板) | `bash demo/govboard.sh` | 一頁聚合:6 類 policy 的 ALLOWED 累計 + DENIED 計數(實時,範例 ~2.5k 越權被擋)、Jira 升級 by kind(change-approval/cve-affected/sast)、CVE 分級、機隊 2 台監控、MTTR 44s | 零 |
| D7 | **Web 即時狀態盤**(整個 agent stack 一頁看) | 瀏覽器開 `http://127.0.0.1:8899`(boot-stack 自動拉起) | 即時顯示四元件 / 兩節點職責分工(A 運維·B 資安)/ 機隊 monitor / CVE / 治理 ALLOWED·DENIED / Jira / 快照;唯讀彙整、**不洩 token**、5s 自動刷新 | 零 |

## 抽驗紀錄(loop 每次更新時抽 ≥3 條實跑對照)
- 2026-06-12 17:xx:B2 cve-scan=2 affected + schedule 歷史 ✅;B4 source-cve=SBOM4/SAST2/設計違反 2/5 ✅;A1/A4 bridge-regress drift=5→0、PASS ✅(本輪稍早)。healthcheck 全綠。
- 2026-06-15 16:xx(real-scan):`bash scripts/real-scan.sh` 用**現成業界掃描器**實掃真實源碼 → flawfinder `diag.c:9 (shell) system`、Semgrep `CWE-78 diag.c:9 / CWE-798 auth.c:4` 皆命中,**獨立重現 demo 的 SAST findings**(B4 可信度補強)。Trivy 跑通(firmware 套件需 SBOM PURL 才直掃)。Dashboard:CVE→NVD 連結、deny log 補日期(UTC→CST)、DENIED 顯示被擋目標+原因。
