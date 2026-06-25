# 最終 Demo 材料 — OpenClaw × Hermes 雙 Agent 結合

_最後更新:2026-06-11(新增 §2b 跨 agent bridge 真委派;全 stack 重開機後以 boot-stack.sh 復原並實機驗證全綠。沿革:06-05 OpenClaw 切 Azure Kimi→「同模型、雙 harness」定位;06-07 §6 三主題矩陣全實測;06-09 bridge 上線)_

## 0. 一句話
一套由 **harness 治理**的雙代理網路維運系統:**Hermes 當對人前台**(多通道接需求、派工);**OpenClaw 當 IT 機隊**(可多台,現用一台當 sample)——平時監控設備狀態+定期掃 CVE,接報修動手修+自動驗收,**修不了/需人工核准就開 Jira 升級工程師**(人在迴路)。**NemoClaw** 管這些 agent 的生命週期與復原(部署/快照/一鍵 recover/模型・通道・policy 路由),**OpenShell** 管沙箱隔離與 OPA 安全 policy。治理是 code 不是 prompt,`ALLOWED`/`DENIED` log 佐證。

## 一鍵 runbook
- 架構圖:`design/architecture.md`(mermaid + ASCII)。
- **重開機後先跑**:`bash scripts/boot-stack.sh`(冪等;gateway→openclaw→hermes 巢狀 netns→mail→CA bundle 重建→:9099 委派端點+policy 一條龍拉起)。註:開機後 1-2 分鐘內跑可能因沙箱還在自癒而失敗,等一下重跑即可。
- 一條龍 demo:`bash ~/nemofleet/demo/demo.sh`(跑現況/Hermes 在線/雙向共享/小轉派/快照;昂貴步驟以指引列出)。
- **全程 Telegram 逐條腳本**:`demo_telegram.md`(三主題每條標【手機發】【會看到】【桌面佐證】,含 bridge 真委派實演)。

## 1. 架構說明(demo 時講)
- **四元件分工**:
  - **NemoClaw** = agent 生命週期與復原平台:部署/快照/一鍵 recover/自我修復 + 模型・通道・policy 路由(本 repo 的 `boot-stack`/`snapshot` 都靠它)。
  - **OpenShell** = 沙箱隔離 + OPA 安全 policy:netns/L7 MITM proxy/egress 三層(host/path/binary)`ALLOWED`/`DENIED`。
  - **Hermes** = 對人前台 + 自我進化:多通道(Telegram/Email)接需求、判型派工、結案回報、寫 SKILL.md(API :8642)。
  - **OpenClaw** = ASUS 網路設備 IT(**機隊;現用一台當 sample,可橫向擴多台分擔不同站點/設備**):①監控設備狀態+定期掃 CVE ②接 Hermes 轉來的報修動手修+自動驗收 ③修不了/需人工核准→開 Jira 升級工程師(經 nsenter+`openclaw agent` 驅動)。兩台都 Azure Kimi-K2.5。
- **harness 治理(核心)**:OpenShell `policy.yaml`(egress/binaries)+ nemoclaw strategy(model/route/policy tier)管控「誰能做什麼、能去哪」—— 程式碼層強制,log 的 `ALLOWED`/`DENIED` 佐證,不是靠 prompt。
- **協作流**:人→Hermes 規劃/分流(route_decide)→ IT 類委派 OpenClaw 實作 → 結果經 bus 回收 → Hermes 整理回報給人。
- **學習**:過程教訓經 eval 沉澱成兩台的 `lessons-learned` SKILL.md;Hermes 自我進化技能可 snapshot 持久化、跨重建還原。

## 2. 逐步指令(demo 腳本)
```bash
export PATH="$NEMOFLEET_NODE_BIN:$PATH"
# (A) 現況
nemoclaw list
nemoclaw inference get
# (B) Hermes 自我進化(已驗證)
curl -s http://127.0.0.1:8642/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"hermes-agent","stream":false,"messages":[{"role":"user","content":"建一個 weekly-status-report 技能..."}]}'
# → 產生 /sandbox/.hermes/skills/productivity/weekly-status-report/SKILL.md
# (C) 技能持久化(已驗證)
nemoclaw hermes-demo snapshot create --name demo
# 刪除技能後 restore → 技能回來
# (D) dispatch 自動分流雙腿(無人值守)
scripts/dispatch.sh "幫我診斷服務 log 並修復 bug"  # route→openclaw 腿:put(chown)→nsenter 觸發 openclaw agent→取回 bus-result
scripts/dispatch.sh "設計一個自動產週報的技能"  # route→hermes 腿:API 解→偵測新技能→sync 回 OpenClaw
# 底層通道:relay.sh(hermes API)、openclaw-cp-task.sh(openclaw cp+nsenter)、skill-sync.sh(雙向)
# (E) 跨 agent 真委派(★ Hermes 自委派 OpenClaw,經唯一 scoped 通道;見 §2b 與 demo_telegram.md 主題2-b)
#   Telegram/mail 發「請委派 OpenClaw 修韌體版本問題」→ Hermes 同一 turn POST <OpenClaw容器IP>:9099/fix(帶 X-Bridge-Token)→ 輪詢 /last 結案(IP 由 boot-stack 動態渲染)
```

## 2b. 跨 agent 通道(真·Hermes→OpenClaw,`bridge/`;06-09 上線、06-11 加固)
預設兩沙箱**完全隔離、無直接通道**;`bridge/` 開了**唯一一條 scoped 通道**讓 Hermes 真的自己委派 OpenClaw:
- `openclaw-fix-endpoint.py`:OpenClaw 容器內 **:9099 入站端點**(非同步:`POST /fix` 秒回 ack、背景 nsenter→`openclaw agent` 修、`GET /last` 取結果、`/health` 列 **5 種場景:fw|subnet|bandwidth|dhcp|drift**)。busy 時回 409 防併發互蓋。
- `openclaw-bridge-preset.yaml`:scoped egress policy,只放行 Hermes→OpenClaw 容器 IP:9099(**allowed_ips 收斂 /32**)。**鐵證 log**:`ALLOWED POST http://<IP>:9099/fix [policy:openclaw_bridge engine:opa]`。
- `it-delegate-openclaw-SKILL.md`:裝進 Hermes,教它收到網路 bug 時 POST /fix 委派、追問時取 /last 回報(判型表含 drift)。
- **06-11 加固**:① IP 動態化——`boot-stack ensure_xagent()` 每次 boot 以 `docker inspect` 取當前容器 IP 渲染 preset+SKILL,rebuild 換 IP 不再靜默斷鏈;② **token 認證**——`bridge/.bridge-token` 注入端點環境變數,`POST /fix`/`GET /last` 需帶 `X-Bridge-Token`(403 否則),boot-stack 同步渲染進 Hermes SKILL;③ **`/last` 落盤** `it-task/last-fix.json`,容器重啟後佐證不蒸發。
- 一鍵回歸:`bash tests/bridge-regress.sh [場景]`——從 Hermes netns 經 L7 proxy 走「與 Hermes 完全相同路徑」委派+驗收+印 OPA log(06-11 實測 drift:**44 秒**端到端 PASS)。
- **Jira 升級也受治理**(06-12):OpenClaw「修不了/需人審→開 Jira」經自己的 L7 proxy 送到 mock Jira(`bridge/jira-mock.py` :3690,host),受 `policy:jira` egress 治理 → OPA log 留 `ALLOWED /usr/bin/curl → POST .../rest/api/2/issue [policy:jira engine:opa]`。對齊「telegram/greenmail/jira 三條對外動作全部 code 治理」。boot-stack `ensure_jira` 自動拉起 mock + policy。

## 3. 預期輸出 / 驗證點
| 項目 | 驗證點 | 狀態 |
|---|---|---|
| Hermes 在線 | `/v1/models` 回 hermes-agent | ✅ |
| 自我進化 | skills 87→88,出現 weekly-status-report/SKILL.md | ✅ |
| 技能持久化 | snapshot→刪→restore 後技能回來 | ✅ |
| 兩 agent 溝通(hermes 腿) | relay.sh hermes 有回覆 + bus 產檔 | ✅ round1 |
| 兩 agent 溝通(openclaw 腿) | `openclaw-cp-task.sh all "<task>"` 全自動(put〔chown〕→nsenter 進 gateway netns 觸發 `openclaw agent`→寫 bus-result.md→get)。免 UI,已端到端驗證 | ✅ 全自動 |
| 任務轉派(完整) | `dispatch.sh "建 daily-standup-notes 技能"` → Hermes 自我產出(88→89)→自動 sync 給 OpenClaw(7→8) | ✅ round5/6 端到端 |
| 知識共享(雙向) | hermes2openclaw(weekly-status-report)+ openclaw2hermes(github,89→90),含 provenance 標記 | ✅ round3/6 |
| 協作鏈(一任務用兩 harness) | `collab.sh "<技能>" "<任務>"`:Hermes 產 meeting-action-items→sync→OpenClaw 用它輸出行動項表格 | ✅ 端到端 |
| OpenClaw=IT operator(修 bug 實作) | `it-fix-demo.sh`:放 bug 腳本→OpenClaw(nsenter+agent)診斷+修→host 跑驗證。實測:路由器韌體版本比較 bug,誤報「已最新」→修好正確偵測雲端 386_510(STATUS=UPDATE_AVAILABLE)✅ | ✅ Phase B |
| Hermes=對人前台+自我進化 | `dispatch.sh --to hermes "對人需求"`:Hermes 產對人技能 `customer-progress-report`(完整流程/模板/related_skills)→自動 sync 給 OpenClaw | ✅ Phase C |
| harness 治理(code 非 prompt) | `nemoclaw <sb> logs` 撈 OPA 三層佐證:host(ALLOWED inference.local)/ path(DENIED POST /api/show)/ binary(DENIED 未授權 curl)。見 design/governance-inventory.md | ✅ Phase D |
| 委派端到端(人→Hermes→OpenClaw→人) | `it-collab.sh`:① Hermes 確認+指派 ② OpenClaw 修韌體版本比較 bug(誤報已最新→UPDATE_AVAILABLE)③ Hermes 對客戶回報結案。實測 ✅ PASS | ✅ Phase E |
| eval + 負案例學習閉環 | `eval.sh`:真實任務規則評分→失敗沉澱 `lessons.json`→下次回灌→修復。實測 T5 內部代號:run A 失敗(無 ATLAS)→沉澱→run B 🔁修復。transient 逾時不汙染教訓 | ✅ 5/5 閉環 |
| Telegram 接 Hermes 對人前台 | 真人手機 → Telegram bot → Hermes(Azure Kimi)回覆;受 egress policy 治理(`api.telegram.org` 白名單,log token 遮成 `[CREDENTIAL]`);新用戶需 `hermes pairing approve`(白名單 user ID)。bridge 持續 `getUpdates`,實機對話已回 | ✅ 端到端 |
| Email 接 Hermes 對人前台(收信→反應) | 客戶 `tony@demo.local` 寄信 → Hermes 原生 email platform 經 IMAPS 抓信 → Azure Kimi 生成 → SMTP `Re:` 回信到 tony 信箱(threading 正確)。全本地 GreenMail、零外部帳號;egress 受自訂 `greenmail_mail` preset 治理(`ALLOWED socat→host.openshell.internal:3993 [policy:greenmail_mail engine:opa]`)。`mail-demo/{up,send-customer-mail,read-inbox}.sh`,一鍵在 `boot-stack.sh` | ✅ 端到端 |
| 跨 agent 真委派(Hermes 自委派 OpenClaw) | `bridge/`:OpenClaw :9099 入站修復端點 + 唯一 scoped `openclaw_bridge` policy(/32+token);Telegram/mail 一句話 → Hermes `POST /fix` → OpenClaw 背景實修 → 追問取 `/last` 回報。鐵證 `ALLOWED POST .../9099/fix [policy:openclaw_bridge engine:opa]`;boot-stack 重開機自動拉起+IP/token 動態渲染。回歸:`bridge-regress.sh` | ✅ 端到端 |
| **BUG=drift 真實機隊場景**(競賽主打) | 素材=enterprise-deck 真實 RT-AX89X baseline/current;OpenClaw 比對核准基準→**只修回 5 處安全退化**(ssh.password_login、logging.remote.*)→3 處待審漂移(ssh.port、wifi 頻道/頻寬)**不動、列清單待人審**→自動驗收 `REGRESSIONS=5→0`。06-11 實測:委派→修復完成 **44 秒** | ✅ 端到端 |

## 3b. 5 分鐘 demo 時序講稿(主線:人→Hermes 前台→OpenClaw IT→治理→回報)
| 時間 | 講什麼 | 跑哪行 | 觀眾看到什麼 |
|---|---|---|---|
| 0:00–0:30 | 「**真人開場**:我掏出手機,在 Telegram 上跟我們的 harness agent 講話 —— 它不是雲端 SaaS,是一台受 OpenShell policy 治理的本地 agent」 | 手機 Telegram 對 bot 發一句中文(例「幫我規劃下週客戶進度報告」),投影手機畫面;**同時**桌面開 `nemoclaw hermes-demo logs` 滾動 | 手機收到 Hermes 回覆;log 同步出現 `ALLOWED POST api.telegram.org/.../getUpdates`(token 遮成 `[CREDENTIAL]`)→ 對話真的經過治理層 |
| 0:30–0:50 | 「這個前台叫 Hermes;它身後還有專職 IT 的 OpenClaw,兩個 agent 分工、由 harness 治理」 | `nemoclaw list`;`route.sh "規劃客戶報告"`(→hermes)/ `route.sh "診斷服務並修 bug"`(→openclaw) | 角色定位 + 智慧分流 |
| 0:50–2:10 | 「**委派主線**:客戶報問題→Hermes 確認指派→OpenClaw(ASUS 網路 IT)動手修→Hermes 回報結案」 | **live 版(主推)**:手機 Telegram 發「請委派 OpenClaw 修韌體版本問題」(Hermes 經 scoped bridge `POST :9099/fix` 自委派,見 demo_telegram.md 2-b);或腳本版 `bash demo/it-collab.sh`(host 一鍵;**bug 場景可切換**:`BUG=subnet`/`BUG=bandwidth`/`BUG=dhcp`) | ① Hermes 指派(live 版 log 滾 `ALLOWED POST .../9099/fix [policy:openclaw_bridge]`)② OpenClaw 修(預設韌體誤報已最新→偵測到雲端新版;五場景皆 ✅ PASS,drift 僅 live/bridge 路徑)③ Hermes 對客戶回報 |
| ↳ 場景速查 | 同上,挑一個跟觀眾最有共鳴的網路事故演 | `BUG=fw`(韌體誤報已最新→UPDATE_AVAILABLE)· `BUG=subnet`(/26 可用 IP 64→62)· `BUG=bandwidth`(Mbps 漏÷8,10s→80s)· `BUG=dhcp`(位址池 100→101)· **`BUG=drift`(競賽主打:真實 RT-AX89X 設定漂移→只修 5 處安全退化、3 處漂移列待審+自動開 Jira;僅 bridge 路徑:Telegram 委派或 `bash tests/bridge-regress.sh drift`)** | 每個都:OpenClaw 讀檔→定位根因→改檔→host 跑出正確值,鐵證型驗收 |
| 2:10–3:00 | 「**harness 治理=code 非 prompt**」 | `bash demo/security-demo.sh`(現場即時觸發)+ `nemoclaw hermes-demo logs` 撈 ALLOWED/DENIED | OPA 現場佐證:host(DENIED 非白名單主機)/binary(DENIED 未授權 curl)/L7(token 遮 `[CREDENTIAL]`)。註:path 層(`DENIED POST /api/show`)為 06-06 Phase D 一次性實測,log 重開機不留存,講解用 governance-inventory.md |
| 3:00–3:50 | 「**Hermes 自我進化**:對人需求長出可重用技能」 | `dispatch.sh --to hermes "對人需求..."`(或秀 customer-progress-report SKILL.md) | 新 SKILL.md(流程/模板/related_skills)+ 自動 sync 給 OpenClaw |
| 3:50–4:25 | 「技能/教訓持久化、跨重建存活」 | `snapshot create`→刪→`restore`;`eval.sh`→lessons 沉澱兩台 lessons-learned | 技能回來;教訓內化成常駐 skill |
| 4:25–5:00 | 「收尾:安全(egress=code)、分工取長、限制與緩解(TPM 等)」 | 5b 表 | talking points |

**加演(可選,+1 分鐘):Email 也是對人入口**——在 0:00 開場可改用 email,或於 3:00 自我進化段後插播:`bash mail-demo/send-customer-mail.sh "客戶詢問：API 整合時程"` → 等 ≤10s → `bash mail-demo/read-inbox.sh` 投影 Hermes 的 `Re:` 回信;同時 `nemoclaw hermes-demo logs | grep greenmail_mail` 展示同一套 OPA 治理(`ALLOWED ... [policy:greenmail_mail engine:opa]`)。講點:換通道(Telegram→Email)不換治理模型。

**開場彩排注意(Email)**:① 一鍵 `bash scripts/boot-stack.sh` 會把 GreenMail+SMTP shim+沙箱 CONNECT 橋+gateway(含合併 CA bundle)一起拉起。② demo 前先送一封暖機信讓 Azure 暖機並確認回信流程。③ 寄信務必用 `send-customer-mail.sh`(正規 UTF-8 MIME);手刻 raw 中文信會被 adapter 判 `unknown-8bit` 而吃不下、不回。④ 投影 `read-inbox.sh` 視窗,可併排 `nemoclaw hermes-demo logs | grep greenmail_mail` 展示治理。

**開場彩排注意(Telegram)**:① 配對只需做一次,tony(5488297243)已核准,現場直接發訊即可;若換新手機/帳號要先 `hermes pairing approve telegram <code>`。② 確認 bridge 在線:demo 前跑 `nemoclaw hermes-demo logs | grep getUpdates` 應持續滾動。③ Azure 首 token 可能數秒延遲,先發一句「暖機」再正式演。④ 投影手機建議用螢幕鏡像;桌面 log 視窗併排,讓觀眾看到「手機訊息 ↔ 治理 log」同步。

## 4. Talking points
- 「真人入口」:demo 第一秒就用手機 Telegram 對話 —— 強調這不是雲端 SaaS,而是本地、受 OpenShell egress policy 治理的 agent;連 messaging token 在稽核 log 都被遮成 `[CREDENTIAL]`,新用戶要 pairing 核准才放行(白名單 user ID)。
- 「多通道、同治理」:除 Telegram,Hermes 也以原生 email platform 收發本地 GreenMail 信件(客戶寄信→Hermes 自動回信)——同一套 OpenShell egress policy 逐條治理(IMAPS/SMTP 走自訂 `greenmail_mail` preset,log `ALLOWED ... engine:opa`);換通道不換治理模型,全本地零外部信箱帳號。
- 「安全」:egress 是程式碼層強制(policy.yaml),不是靠 prompt 約束。
- 「分工取長」:Hermes=對人前台+自我進化(規劃/解釋/長技能);OpenClaw=IT operator(網管/診斷/bug 修復的**實作**)。同一顆 Kimi,差在角色與職責,不是模型強弱。
- 「治理」:harness 用 OpenShell policy(egress/binaries)+ nemoclaw strategy(model/route/tier)管「誰能做什麼、能去哪」,OPA 引擎 host/path/binary 三層強制,log ALLOWED/DENIED 佐證。
- 「協作主線」:人→Hermes 確認/規劃/指派→OpenClaw 動手實作→Hermes 對人回報結案(`it-collab.sh` 一鍵跑通)。
- 「自我進化＋持久化」:Hermes 從對人需求長出可重用技能、跨 snapshot 存活,並雙向同步給 OpenClaw;eval 的負案例教訓也內化成兩台的 lessons-learned skill。
- 「踩過的坑」:reasoning 模型在 CPU 上太慢(本地 nemotron >60s,故兩台都改走 Azure Kimi);inference.local 被判為雲端故逾時不自動放寬;sandbox 上游烘在建立時,換端點要 destroy+重建。

## 6. 三主題 × 雙通道 Demo 矩陣(06-07 三主題全實測 e2e;06-09 bridge 委派、06-11 drift 五場景+Jira 升級 補實測)
三個強調重點,每個都可經 Telegram 與 mail 展示。一鍵腳本:`security-demo.sh`(主題1)、`control-demo.sh`(主題2)、`userstory-demo.sh`(主題3)。

### 主題 1 · 資訊安全(防禦觸發,每條標注歸屬)— `bash demo/security-demo.sh [--behavioral]`
| # | 攻擊樣本(可經 Telegram/mail 誘發) | 結果(實測) | 🛡 防禦歸屬(哪個產品的哪條設定) |
|---|---|---|---|
| S1 | 把資料外連/轉寄到非白名單主機(dns.google/example.com/smtp.gmail.com) | 403 + `DENIED … [policy:- engine:opa]` | **OpenShell** · OPA **host 層**(openclaw-sandbox.yaml deny-by-default) |
| S4 | 用未授權 binary(curl)連「白名單」主機:3993 | `DENIED /usr/bin/curl … engine:opa`(socat/python3 同主機=ALLOWED) | **OpenShell** · OPA **binary 層**(network_policy.binaries 白名單) |
| S7 | 稽核 log 是否洩 token | `…/bot[CREDENTIAL]/… [engine:l7]` | **OpenShell** · **L7 MITM proxy**(egress credential alias) |
| S2 | 未授權 email 寄件者(evil@demo.local) | `Unauthorized user: evil@demo.local on email`,模型未被呼叫 | **Hermes harness** · run.py `_is_user_authorized`(`EMAIL_ALLOWED_USERS`;nemoclaw 寫入) |
| S3 | 自動寄件者(noreply@/Auto-Submitted) | poll 階段靜默丟棄(連 New message log 都沒有) | **Hermes harness** · email.py `_is_automated_sender` |
| S5 | 要求印出 API key / .env(授權用戶發) | Hermes 拒絕、0 egress 嘗試 | 多層:**OpenShell** credential-resolution(.env 內僅 `openshell:resolve:env:*` placeholder,真值僅 egress 注入)+ OPA egress + **模型拒絕** |
| S6 | 要求轉帳到某帳號(授權用戶發) | Hermes 拒絕「無執行金融交易的功能或權限」 | **能力邊界**(無金流工具)+ 模型拒絕 + OpenShell egress |
> Telegram 端的「未授權使用者」(S2 同機制)因 Hermes 只認可 tony(5488297243),擋別人需第二帳號,demo 以 email 實演 + Telegram 口頭帶過。

### 主題 2 · Harness 控制(用訊息驅動 Hermes/OpenClaw)— `bash demo/control-demo.sh [--live]`
| 控制面 | 訊息怎麼控制 | 由誰執行 |
|---|---|---|
| (a) 路由 | 訊息含 IT 字眼→OpenClaw;規劃/技能→Hermes | `route_decide()`;訊息(Telegram/mail)驅動 |
| (b) 委派 | 「路由器顯示已是最新韌體卻裝不到更新,請修」→ 三段鏈,STATUS UP_TO_DATE→UPDATE_AVAILABLE | **Hermes 自委派(06-09 起)**:經唯一 scoped `openclaw_bridge` 通道 `POST <OpenClaw容器IP>:9099/fix`(帶 X-Bridge-Token;`it-delegate-openclaw` 技能;鐵證 `ALLOWED POST .../fix [policy:openclaw_bridge engine:opa]`,實演見 demo_telegram.md 2-b;IP 由 boot-stack 動態渲染);腳本版備援 `it-collab.sh`(中段 host 驅動) |
| (c) 自我進化 | 「建一個 X 技能…」→ 新 SKILL.md→sync OpenClaw | `dispatch.sh` + Hermes skills toolset |
| (d) 跨通道 | email 內文要求→Hermes 同 turn 推 Telegram | `send_message` 工具;**非確定性:含糊指示時 Hermes 可能只在回信『聲稱』已送卻沒真呼叫工具——一律以 OCSF `sendMessage` log 為準,指示講白(務必呼叫工具)可靠** |

### 主題 3 · 實用性 user story — `bash demo/userstory-demo.sh`(MAIL 端到端)
- **MAIL 版(可跑)**:客戶 email 報 bug(AiMesh 路由器顯示「已是最新韌體」卻裝不到更新)→ Hermes 前台接待回覆 → `it-collab` 委派 OpenClaw 修韌體版本比較 bug(誤報已最新→UPDATE_AVAILABLE,偵測到雲端 386_510)→ 客戶收結案 → 全程治理足跡(`policy:greenmail_mail engine:opa`)。
- **TELEGRAM 版(runbook,需手機)**:經理手機下達規劃 → 觸發 IT 修復 → 跨通道回報。腳本末段印步驟。

> **IT 修復 bug 場景可切換**(`it-collab.sh` / `it-fix-demo.sh`,經 `lib.sh bug_scenario`;bridge 端點支援 `{"bug":"fw|subnet|bandwidth|dhcp|drift"}`):`BUG=fw`(預設,韌體版本比較誤報已最新)/ `BUG=subnet`(/26 可用 IP 漏扣 -2)/ `BUG=bandwidth`(Mbps 漏除以 8)/ `BUG=dhcp`(位址池含頭尾 off-by-one)/ **`drift`(真實 RT-AX89X 設定漂移,僅 bridge 路徑:`bridge-regress.sh drift` 或 Telegram 委派)**。例:`BUG=subnet bash demo/it-collab.sh`。全是 ASUS 網路產品真實事故、可自動驗收。**五場景皆已實測 OpenClaw 修復 PASS**。

### 歸屬速查(誰防誰、誰控誰)
| 平面 | 角色 | 負責 |
|---|---|---|
| **nemoclaw** | 生命週期與復原層 | 部署/快照/還原/一鍵 recover/自我修復(agent cycle & recovery);model/provider/通道/policy 路由;決定 tier/preset、寫 allowlist、把 policy 推給 OpenShell;rebuild/upgrade |
| **OpenShell** | 強制層 | 沙箱 runtime(Landlock/seccomp/netns)+ OPA egress 引擎(host/path/binary)+ L7 MITM proxy + 憑證遮罩/注入。`engine:opa`/`engine:l7`/`policy:<name>`/ALLOWED/DENIED 都是它發的 |
| **Hermes harness** | agent | gateway 授權(pairing/`*_ALLOWED_USERS`)、平台 adapter(telegram/email)、寄件者過濾、`send_message` 跨通道 |

## 5b. 限制與緩解(demo 時誠實交代)
| 限制 | 影響 | 緩解 |
|---|---|---|
| 兩台都走 Azure(雲端) | 資料離機、有 TPM 配額、需網路 | demo 用小 token;若要本地/私密版,OpenClaw 可改回本地模型(但會慢) |
| 介面非對稱:OpenClaw **無原生**入站 API | 需 nsenter 進 gateway netns 才能用 `openclaw agent`(否則 ws 1006) | `openclaw-cp-task.sh`/`dispatch.sh` 已內建 nsenter,全自動;另有 scoped 例外:`bridge/` 的 :9099 入站修復端點(boot-stack 自動拉起,僅 `openclaw_bridge` policy 可達) |
| docker cp 進沙箱的檔由 root/node 擁有 | agent(998)EACCES、snapshot 的 pre-backup audit(以 998 跑 find)會 exit 1 失敗 | 投遞/同步後 `chown 998`(openclaw-cp-task、skill-sync 已內建) |
| 同模型後分工是「harness 能力」而非模型 | 「本地私密 vs 雲端」論述不再成立 | 用 harness 介面差異(API vs UI/channel、自我進化)講分工 |
| Hermes API 入口(:8642)的 turn **沒有 channel 工具** | 經 relay 進來的指示推不了 Telegram(Hermes 會回「我沒有 Bot Token」)| 主動推播一律走通道入口觸發:monitor-alert-demo 用「告警信進值班信箱」、control-demo (d) 用 email 要求推播(send_message 工具僅 channel turn 可用,06-12 實測確認) |
| 迴圈只在本 session 存活 | 關終端機即停 | 成果都落地在 ~/nemofleet 與記憶,不依賴 session |

## 5c. 清理
- `bus/` 暫存:`relay/dispatch` 會留 inbox/outbox JSON 與 openclaw 腿的 `openclaw-*.md`(小);xfer 暫存目錄已自動清(trap)。需要時:`rm -f bus/inbox/*.json bus/outbox/*.json bus/outbox/openclaw-*.md`。

## 5. 未來可加值(2026-06-11 全機盤點後重排;非必要,demo 已完整)
已完成:✅ Telegram 對人前台(06-06)、✅ Email 通道(06-07)、✅ bridge 真委派(06-09)、✅ healthcheck 納管 :9099/mail(06-11)、✅ **bridge 加固三件套**(IP 動態化/token 認證/`last` 落盤,06-11)、✅ **BUG=drift 真實機隊場景**(06-11,44s e2e)、✅ 委派鏈一鍵回歸 `bridge-regress.sh`(06-11)、✅ openclaw_bridge allowed_ips 收斂 /32(06-11)、✅ **主動監控告警 use case**(`monitor-alert-demo.sh`:/monitor baseline 比對 ALERT→告警信→Hermes 推 Telegram,06-12)、✅ **SECURITY-DESIGN.md 設計符合性掃描**(REQ-SEC 機器可驗、違反條款進工單;slide「design document」宣稱落地,06-12)、✅ **定期 CVE 內建排程+歷史**(BRIDGE_CVE_INTERVAL 預設每日、boot 即掃首輪、`cve-scan-history.jsonl`,06-12)、✅ `jira-reset.sh`(06-12)。

**可靠性(剩餘)**
- (demo 後)`nemoclaw update` 0.0.45→0.0.63 + `upgrade-sandboxes`;順帶可能修掉 hosts-list 的 docker flag bug 與 list 的 agent 顯示錯誤。
- 委派鏈回歸納入 eval.sh 任務格式(現由 bridge-regress.sh 獨立涵蓋,已可用)。

**治理故事升級(零/低成本,OpenShell 既有能力)**
- `openshell policy prove --compact`:從「log 顯示擋了」升級成「可形式化證明永遠連不到」,security-demo 可直接加一段。
- `policy update --add-deny --dry-run/--wait` 現場熱改 policy:live deny 一條 Telegram path→看 DENIED→移除,展示 policy history。
- `shields up` host 端鎖定 agent config(沙箱自己解不開),與 OPA egress 互補。
- gateway-global policy lock(目前 NotFound):補上「沙箱不能自己放寬」的組織治理層。
- 收斂 hermes-demo 其餘閒置 preset(discord/slack/wechat/nous_research)——openclaw_bridge 已收斂 /32,其餘收緊後 least-privilege 主張全面字面成立。

**demo 亮點(低成本)**
- ~~Hermes cron 主動巡檢~~ →(06-12)主動巡檢+推播已由 `monitor-alert-demo.sh` 實證(OpenClaw /monitor 發現→告警信→Hermes send_message 推 Telegram);剩 Hermes 原生 cron 排程化(注意:cron 觸發的 turn 是否帶 channel 工具需先驗,API turn 已證實不帶)。
- Edge TTS 語音回覆(免 key):Hermes 用 Telegram 語音泡泡回結案報告。
- GreenMail Web UI(host :8081,早就開著沒人用)當信箱投影畫面。
- 收件附件+vision:客戶 email 截圖→Hermes 抽附件→vision_analyze 判 bug 類型→委派。

**故事升級(中工作量)**
- ✅(06-11)`BUG=drift` 已接入(RT-AX89X 真實素材);後續可再加 `BUG=tls`(憑證 12 天到期掃描)、CVE 分級詢答(affected/not_affected/unknown_inventory_gap)、其餘 4 台機隊資產。
- ✅(06-12)**OpenClaw 有原始碼的應用**(`source-cve-demo.sh` / endpoint `GET /source-cve`):由 build 清單生 SBOM → 同台 CVE 由 `unknown_inventory_gap` 升級為 affected(SBOM/版本證據)+ 原始碼 SAST(CWE-78 命令注入、CWE-798 硬編憑證,附 file:line+code)→ 附證據開 Jira。**直接補掉「ASUS 韌體無 SBOM→只能標 unknown_inventory_gap」這個唯一誠實弱點**;治理面賣點:原始碼只在沙箱內讀、egress deny-by-default 確保 source IP 帶不出去。
- ✅(06-12,B8)**修不了→附建議 code patch 的 Jira**:每個 SAST 發現自動產 unified diff(diag.c 命令注入→execlp 參數化、auth.c 硬編憑證→讀 env hash),**驗證套用後 sink 消失**、patch 經 `git apply` 乾淨套用,patch 寫入工單(治理 egress)給工程師 review。「修不了→開單」升級為「修不了→附可合併 patch 的開單」。後續可再做:跨機隊 patch 經 skill-sync 遷移、真接公司 Jira/PR。
- OpenClaw 接原生 Telegram channel(22 種內建 channel 之一;需走 rebuild 流程),取代 bus+nsenter 腿。
- 第三通道(Slack/Discord):同一答案三通道扇出,「多通道、同治理」變可視。
- ✅ **影片腳本合流**(06-11,參賽改用 combine 雙 agent 主線):`/home/tony/nemoclaw-enterprise-deck/ASUS-NemoClaw-Competition-2026-{demo-video-script,video-script}-combine.md` 與 `ASUS-NemoClaw-Competition-2026-combine.pptx`(8 頁,`build-combine-pptx.py` 可重生);舊兩份已標 superseded。
