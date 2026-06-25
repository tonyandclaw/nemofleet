# nemoclaw-combine 自主迴圈 — 進度

cron job `6a265a5d`,每 15 分,直到 2026-06-05 09:00 CST 自我停止。每輪讀本檔上一輪 TODO 再推進。

---

## Round 1 — 2026-06-05 00:24 CST
**step1 盤點**
- my-assistant: agent=openclaw, 本地 nemotron-3-nano-4b, dashboard :18789, 容器 up 3h。
- hermes-demo: agent=hermes, Azure Kimi-K2.5, API :8642, 容器 up 13m。inference route = Kimi-K2.5。
- 兩台 host 埠都在聽(18789 / 8642)。

**step2 實作(可驗證進展)**
- 建立工作匣 `/home/tony/nemoclaw-combine/{bus,scripts,design}`。
- 設計「Dual-Agent Research Desk」結合 use case(見 design/combined-use-case.md):openclaw=前線/分流、hermes=專家/技能工廠。
- 實作檔案匣 **bus** + `scripts/relay.sh`(把訊息送到 agent 的 OpenAI 相容 API、回覆寫回 bus)。
- ✅ 驗證:`relay.sh hermes "..."` 成功,hermes 經 bus 回覆,inbox/outbox 產生檔案。

**step3 folder 更新**:design/combined-use-case.md、scripts/relay.sh、本 PROGRESS.md、DEMO_MATERIALS.md 建立。

**step4 demo 材料**:見 DEMO_MATERIALS.md(已起草)。

**驗證結果**:hermes 腿通;bus 流程通。openclaw 腿未驗證(API 未知)。

**下一輪 TODO（Round 2）**
1. 探查 openclaw(my-assistant :18789)是否有 `/v1/chat/completions`(curl + 讀 openclaw gateway 設定);若無,找 openclaw 的對話入口(可能是不同路徑或需 token)。
2. 補上 relay.sh 的 openclaw 腿並驗證(注意本地 nemotron 慢,max_tokens 壓小)。
3. 設計「轉派」最小情境:openclaw 收任務→判斷→relay 給 hermes→回收。先寫 dispatcher 草稿。

---
## Round 2 — 2026-06-05 00:33 CST
**step1**:兩台運行中(hermes up 13m+→已穩、my-assistant up 3h)。route=Kimi-K2.5。
**step2 調查結論(重要)**:探查 OpenClaw 對話入口 →
- OpenClaw `:18789` = **Control UI(HTML SPA/websocket)**,**無入站 OpenAI 相容 API**(帶 token 打 `/v1/chat/completions` 回 Not Found;openclaw-sandbox.yaml 的 `/v1/...` 是 egress 允許,非對外服務)。
- → 介面非對稱:Hermes 可直接 curl,OpenClaw 需經 UI websocket / messaging / connect 驅動。
- 修正設計:改用 **bus 為單一整合點**;OpenClaw 端用 **poller 輪詢 bus/inbox**(round 3 實作),sidestep 無入站 API 的限制。
- 已更新 design/combined-use-case.md;relay.sh 的 openclaw 腿改為明確報錯並指向 bus poller。
**step3**:design 與 relay.sh 已更新。
**step4**:DEMO_MATERIALS 驗證表的「openclaw 腿」改註記為「改用 bus poller」。
**驗證結果**:確認 openclaw 無 HTTP chat API(curl 證實)。hermes 腿仍可用。
**下一輪 TODO（Round 3）**
1. 實作 OpenClaw 端 bus poller:一個輪詢 `bus/inbox` 的小腳本/skill,取任務→(經 connect 或 UI session 餵給 openclaw)→結果寫 `bus/outbox`。先做「host 端腳本用 `nemoclaw my-assistant connect` 餵 prompt」的最小版,評估可行性(注意本地 nemotron 慢)。
2. 若 connect 不易腳本化,改探 Control UI 的 websocket session route。
3. 更新 DEMO_MATERIALS 的轉派情境。

## Round 3 — 2026-06-05 00:48 CST
**step1**:兩台運行中。確認 `connect` 只有互動式 SSH、無一次性 prompt → OpenClaw 不易用腳本驅動。
**step2 轉向更可驗證的「知識共享」**:
- 確認 OpenClaw 有 `/sandbox/.openclaw/workspace/skills`,且用**與 Hermes 相同的 SKILL.md 格式**。
- 實作 `scripts/skill-sync.sh`(docker cp 在兩沙箱 skills 目錄間搬技能,雙向)。
- ✅ 驗證:`skill-sync.sh hermes2openclaw weekly-status-report` 成功,OpenClaw 技能數 6→7,內容一致。→ **兩 agent 互相學習(技能共享)閉環成立**。
**step3**:新增 scripts/skill-sync.sh;更新 design/DEMO_MATERIALS。
**step4**:DEMO_MATERIALS 驗證表「知識共享」標 ✅。
**驗證結果**:跨 agent 技能同步可用且格式相容。
**下一輪 TODO（Round 4）**
1. 反向同步驗證(openclaw2hermes 一個技能)+ 加「避免覆蓋既有/標記來源」的保護。
2. 設計「轉派閉環」最小可 demo 版:dispatcher 收任務→丟 hermes 解(API)→若 hermes 產新技能則 skill-sync 給 openclaw。把這串成一個 `scripts/dispatch.sh`。
3. 評估「OpenClaw 主動寫 bus」:OpenClaw 端放一個 skill/hook 讓人在 UI 觸發時把結果寫 bus(設計即可,先不實作)。

## Round 4 — 2026-06-05 01:03 CST
**step1**:兩台運行中。沿用 round3 結論。
**step2**:
- skill-sync.sh 加**防覆蓋**(target 已存在則跳過,除非 `--force`)+ **provenance**(寫 `.synced-from` 標記來源/時間)。
- 實作 `scripts/dispatch.sh`:任務→relay 給 Hermes(1 次 bounded Azure 呼叫)→比對 Hermes skills before/after 偵測**新產技能**→有則自動 `skill-sync` 給 OpenClaw。串起 round1(relay)+round3(sync)成轉派閉環。
- ✅ 驗證:`dispatch.sh "...小任務..." 24` 通——Hermes 作答、diff=無新技能、乾淨結束。完整「authoring→auto-share」= 同管線 + round1/3 已分別驗證。
**step3**:新增 dispatch.sh;skill-sync.sh 強化;更新 DEMO_MATERIALS。
**step4**:DEMO_MATERIALS「任務轉派」標 ✅。
**驗證結果**:轉派管線可用;Azure 本輪僅 1 次小呼叫(24 tok)。
**下一輪 TODO（Round 5）**
1. 跑一次**完整 authoring 轉派**(dispatch 給 Hermes 一個「請建 XXX 技能」的任務,實際看新技能被產出並自動 sync 到 OpenClaw)——會多花一點 Azure(多輪),可接受但記得 max_turns 內完成。
2. 反向 openclaw2hermes sync 驗證(挑一個 openclaw 既有技能)。
3. 把整個結合架構畫成圖(可用 Hermes 的 architecture-diagram 技能產 SVG/markdown)放進 DEMO_MATERIALS。

## Round 5 — 2026-06-05 01:18 CST
**step1**:兩台運行中。route=Kimi-K2.5。
**step2 完整 authoring 轉派(進行中)**:
- ✅ 先 snapshot hermes(v2 name=pre-round5)安全回滾點。
- 把 relay.sh 的 curl 逾時 180→**600s**(agentic authoring 較久)。
- 啟動 `dispatch.sh "建 daily-standup-notes 技能..."`,Hermes 正在做多輪 Azure authoring(log 確認 POST→Azure;curl pid 在飛行)。**尚未結束**——authoring 在 11k+ 提示上每輪 ~20s+、多輪,較慢。
- dispatch.sh 會在 curl 返回時自動偵測新技能並 sync 給 OpenClaw。
**step3**:relay.sh 逾時調整;本記錄。
**step4**:待 round6 驗收後補 DEMO_MATERIALS。
**驗證結果**:authoring 進行中,round6 驗收(Hermes 是否多出 daily-standup-notes、是否自動 sync 到 OpenClaw)。
**下一輪 TODO（Round 6）**
1. 驗收 round5 authoring:檢查 hermes skills 是否 88→89(daily-standup-notes)、`/tmp/dispatch_r5.log` 是否出現 sync 行、OpenClaw 是否收到。若 dispatch 還在跑就等;若失敗(max_tokens 太小被截/未實際建檔)則記原因,考慮加大 max_tokens 或調整 prompt。
2. 反向 openclaw2hermes sync 驗證。
3. 用 Hermes architecture-diagram 技能產結合架構圖放進 DEMO_MATERIALS。

## Round 6 — 2026-06-05 01:33 CST
**step1**:兩台運行中。
**step2 驗收 round5 + 反向同步**:
- ✅ **完整 authoring 轉派端到端成功**(dispatch EXIT=0):Hermes 自我產出 `daily-standup-notes`(skills 88→89)→ dispatch 自動偵測 → sync 給 OpenClaw(7→8,含 provenance)。
- ✅ **反向同步**:`skill-sync.sh openclaw2hermes github` → Hermes skills/productivity/github(89→90,含 provenance)。→ **雙向知識共享完成**。
**step3**:更新 DEMO_MATERIALS(任務轉派=端到端 ✅、知識共享=雙向 ✅)。
**step4**:同上。
**驗證結果**:核心四能力全綠 + 結合層(轉派閉環、雙向技能共享)全部實測通過。
**下一輪 TODO（Round 7）**
1. 用 Hermes 的 architecture-diagram / excalidraw 技能產一張「OpenClaw×Hermes 結合架構圖」(SVG/markdown)放進 nemoclaw-combine,並在 DEMO_MATERIALS 引用。(1 次中量 Azure 呼叫)
2. 整理 DEMO_MATERIALS 成可直接照著走的「demo runbook」(把零散指令收斂成 1 條龍腳本 `scripts/demo.sh`)。
3. 考慮把結合設計重點寫入記憶(reference),供日後 session。

## Round 7 — 2026-06-05 01:48 CST(零 Azure)
**step2/3 收斂與文件化**:
- 新增 `design/architecture.md`:結合架構圖(mermaid + ASCII + 角色分工)。
- 新增 `scripts/demo.sh`:一條龍 demo runbook(現況→Hermes 在線→雙向共享 provenance→小轉派→快照;昂貴步驟以指引列出)。Azure 自畫圖→改自己畫(可靠且免費),「Hermes 現場產圖」留作 demo 亮點。
- 4 個腳本全部 `bash -n` 語法 OK。
**step4**:DEMO_MATERIALS 加入「一鍵 runbook」段(指向 architecture.md 與 demo.sh)。
**驗證結果**:scripts 語法全綠;folder 結構乾淨(design×3、scripts×4、PROGRESS、DEMO_MATERIALS、bus)。
**下一輪 TODO（Round 8）**
1. 實跑一次 `demo.sh` 全程(含 1 次小 Azure)確認 runbook 順、輸出乾淨;修任何不順的地方。
2. 把「OpenClaw×Hermes 結合」要點寫入記憶(新 reference memory + MEMORY.md 一行),供日後 session 重用。
3. 若還有餘裕:設計 OpenClaw 端 bus poller 草稿(讓 OpenClaw 也能主動消費 bus 任務),補上目前「OpenClaw 只能被動」的缺口。

## Round 8 — 2026-06-05 02:03 CST
**step1/2 驗收 runbook + 文件化記憶**:
- ✅ 實跑 `demo.sh` 全程順:5 段(現況/Hermes 在線/雙向共享+provenance/小轉派/快照清單)輸出正確。1 次小 Azure(24 tok)。
- ✅ 寫入記憶:新增 `project_openclaw_hermes_combine.md`(結合專案全貌)+ MEMORY.md 一行,供日後 session 重用。
**step3**:記憶更新。**step4**:DEMO_MATERIALS 已有 runbook 段。
**驗證結果**:runbook 可直接 demo;結合專案要點已持久化到記憶。
**下一輪 TODO（Round 9）**
1. 設計（不一定要實作）OpenClaw 端「bus poller」草稿:一個 OpenClaw 能用的 skill/hook,讓人在 OpenClaw UI 觸發時讀 `bus/inbox` 任務→處理→寫 `bus/outbox`,補上「OpenClaw 只能被動」缺口。寫進 design/。
2. DEMO_MATERIALS 補一段「失敗/限制與緩解」(本地模型慢、TPM、介面非對稱),讓 demo 更誠實完整。
3. 檢查 bus/ 是否累積過多 xfer 暫存,加個清理註記。

## Round 9 — 2026-06-05 02:18 CST(零 Azure)
**step1**:bus 乾淨(inbox/outbox 各 4、無殘留 xfer)。確認 `share mount` 是 sandbox→host 方向,不能把 host bus 掛進沙箱。
**step2/3 補缺口設計 + 誠實文件**:
- 新增 `design/openclaw-bus-poller.md`:OpenClaw 端消費 bus 的設計草稿(選項:host relay-by-cp〔推薦 MVP〕/ sandbox cron worker / messaging channel;含限制與驗收點)。標記未實作。
- DEMO_MATERIALS 新增 **5b 限制與緩解**表(本地模型慢/Azure TPM/介面非對稱/session 限制)+ **5c 清理**註記。
**step4**:DEMO_MATERIALS 更新完成。
**驗證結果**:文件更完整誠實;poller 缺口有明確設計與後續路徑。
**下一輪 TODO（Round 10）**
1. (可選實作)openclaw-bus-poller 選項1 MVP:`scripts/openclaw-cp-task.sh`(host→sandbox 投遞)+ OpenClaw `bus-worker` skill 草稿檔。先做投遞腳本與 skill SKILL.md,先不接 UI 觸發。
2. 通盤檢視 DEMO_MATERIALS 是否可被一個沒上下文的人照著跑完(查漏:前置條件、token 取得、埠號)。
3. 記錄目前 Azure 用量估計(本 session 累計呼叫次數/約略 token),供成本意識。

## Round 10 — 2026-06-05 02:33 CST(零 Azure)
**step2 OpenClaw 腿 MVP(補缺口)**:
- 新增 `scripts/openclaw-cp-task.sh`(host↔sandbox 投遞/取回任務:`put`/`get`)。
- 新增 OpenClaw skill `skills/bus-worker/SKILL.md`(指示 OpenClaw 讀 bus-task.md→處理→寫 bus-result.md)。
- ✅ 已 `docker cp` 把 bus-worker 裝進 OpenClaw(skills 8→9);✅ `put "..."` 測試任務正確落地沙箱 `bus-task.md`。
- 剩「UI 觸發 OpenClaw 處理」為手動(本地模型慢 + OpenClaw 無入站 API 的本質限制)。
**step3**:新增 2 檔。**step4**:DEMO_MATERIALS「openclaw 腿」標 ✅ MVP。
**驗證結果**:雙向轉派雛形成立(Hermes 腿全自動;OpenClaw 腿=投遞+skill 自動、處理需 UI 觸發)。
**下一輪 TODO（Round 11）**
1. DEMO_MATERIALS 通盤校對:確保無上下文者能照跑(列前置:PATH、容器名怎麼抓、token、各埠)。把所有腳本與用途列成一張表。
2. 估算本 session Azure 用量(數呼叫次數)寫進 PROGRESS 供成本意識。
3. 收尾整理:確認 design/×4、scripts/×5 一致,README 起草(nemoclaw-combine/README.md 指向各檔)。

## Round 11 — 2026-06-05 02:48 CST(零 Azure)
**step3/4 收尾文件化**:
- 新增 `README.md`:專案入口(前置條件、腳本總表含 Azure 標記與驗證狀態、文件索引、最快上手)。
- **Azure 用量估計(本 session,概略)**:hermes 對話約 ~7-8 次 —— 自我進化 demo 1(多輪)、持久化測試 0、dispatch 小測 1、完整 authoring 轉派 1(多輪)、demo.sh 內小測 2、setup 驗證數次小呼叫。每次 prompt ~11k token(系統提示為大宗,部分 cache)。屬節制範圍;大宗成本在兩次多輪 authoring。
**驗證結果**:文件齊全(README + DEMO_MATERIALS + design×3 + PROGRESS);scripts×5 + bus-worker skill 一致。
**下一輪 TODO（Round 12）**
1. 端到端「乾淨環境」演練:假裝沒上下文,只照 README + DEMO_MATERIALS 跑 demo.sh,記下任何卡點並修(例如容器名 rebuild 後失效的提醒是否夠清楚)。
2. 把容器名硬編碼改成動態抓取(`docker ps|grep`),降低 rebuild 後腳本失效風險 —— 改 scripts 頂端共用一段。
3. 視時間:幫 DEMO_MATERIALS 補一張「demo 流程時序」(5 分鐘講稿節奏)。

## Round 12 — 2026-06-05 03:03 CST(零 Azure)
**step2 穩定性改進(降 rebuild 脆弱性)**:
- 新增 `scripts/lib.sh`:用 `docker ps|grep openshell-<name>-` **動態解析容器名** + 共用路徑/API 常數 + `require_ct` 警示。
- 改 `skill-sync.sh`、`dispatch.sh`、`openclaw-cp-task.sh`、`demo.sh` 改 source lib.sh,移除硬編碼容器 id。
- ✅ 驗證:6 腳本語法全 OK;lib 正確抓到兩容器;`skill-sync` 走動態解析 + 防覆蓋(既有則跳過)正常。
**step3**:README 更新「容器名已動態抓取」。
**step4**:無需改 DEMO_MATERIALS。
**驗證結果**:腳本 rebuild 後不再因容器 id 變動失效;功能不變。
**下一輪 TODO（Round 13）**
1. 乾淨演練:只照 README → `bash scripts/demo.sh` 跑一遍,確認新讀者可順走;記/修卡點。
2. DEMO_MATERIALS 補「5 分鐘 demo 時序講稿」(每段講什麼、跑哪行、看什麼)。
3. 視時間:relay.sh 也可改用 lib.sh 的 HERMES_API 常數(目前硬編碼 :8642,可接受)。

## Round 13 — 2026-06-05 03:18 CST(零 Azure)
**step2/4**:
- relay.sh 改 source lib.sh、hermes URL 改用 `$HERMES_API` 常數(去最後一處硬編碼)。語法 OK、URL 解析正確。
- DEMO_MATERIALS 新增 **3b 5 分鐘 demo 時序講稿**(0:00–5:00 每段:講什麼/跑哪行/看什麼)。
**驗證結果**:relay 語法 OK;所有腳本現在統一走 lib.sh。文件含完整 demo 講稿。
**下一輪 TODO（Round 14）**
1. 整份文件一致性校對:README/DEMO_MATERIALS/design 之間的指令與檔名是否一致無矛盾;修任何 drift。
2. 視時間做一次真正的乾淨演練(只照 README 跑 demo.sh),記任何卡點。
3. 思考是否還有「更完整結合」的點子(如:讓 dispatch 依任務關鍵字自動選 openclaw vs hermes 的路由規則)——先記設計,不實作。

## Round 14 — 2026-06-05 03:33 CST(零 Azure)
**step1 一致性校對**:✅ 文件引用的 scripts 全存在;✅ 無殘留硬編碼容器 id(全走 lib.sh);檔案清單一致。
**step2 智慧路由(前線分流)**:
- 新增 `scripts/route.sh`:依關鍵字決定 openclaw(私密/本地/個資)vs hermes(技能/分析/設計/複雜),印決策+建議指令(不自動跑昂貴路徑,安全)。
- ✅ 驗證:設計技能→hermes、私密薪資→openclaw、一般→hermes 預設,三例皆正確。
**step3**:README 腳本表加 route.sh。
**step4**:(下輪把 route 納入 demo 講稿)。
**驗證結果**:路由層可用;結合 use case 更完整(分流→轉派→共享→持久化 全鏈)。
**下一輪 TODO（Round 15）**
1. DEMO_MATERIALS 把 route.sh 納入流程(分流是 demo 的好開場:同一介面智慧分派)。
2. 重跑 demo.sh 確認新增 route 後整體仍順(或把 route 示範加進 demo.sh 開頭)。
3. 全專案最終檢視:有沒有任何 TODO 卡住、或可一句話總結的「完成度」。

## Round 15 — 2026-06-05 03:48 CST(零 Azure)
**step2/4**:把 `route.sh` 智慧分流加進 `demo.sh` 開場(section 0)+ DEMO_MATERIALS 講稿 0:00 段。demo.sh 語法 OK。
**完成度檢視(專案已功能完整)**:驗證表 7 項能力全 ✅(Hermes 在線/自我進化/持久化/雙向溝通 hermes+openclaw/完整轉派/雙向知識共享)。全鏈:**route 分流 → dispatch 轉派 → Hermes 自我進化 → skill-sync 雙向共享 → snapshot 持久化**。檔案:scripts×7(lib/relay/skill-sync/dispatch/openclaw-cp-task/route/demo)、design×3、skills×1(bus-worker)、README/DEMO_MATERIALS/PROGRESS。
**驗證結果**:核心目標達成,文件可被新讀者照跑。
**後續輪次定位(維護/打磨,非新功能)**
- 之後輪次以「不破壞、低成本」為原則:健康檢查、文件微調、（可選)真的在 OpenClaw UI 跑一次 bus-worker 端到端、或等使用者醒來給新方向。
- 除非必要,避免重跑昂貴 Azure authoring(已驗證過)。
**下一輪 TODO（Round 16）**
1. 健康巡檢:兩 sandbox 還在跑?hermes API 還活?cron 還在?(輕量)
2. 若一切穩定且無新方向,僅在 PROGRESS 記「stable, holding」並等下一輪,不做多餘改動。

## Round 16 — 2026-06-05 04:03 CST(零 Azure,健康巡檢)
**巡檢全綠**:hermes 容器 up 4h / my-assistant up 7h;Hermes API 活;OpenClaw UI 200;Token_Hunter :8080 OK;gateway :18080 OK;cron 正常(第 16 次觸發)。
**狀態**:專案功能完整 + 系統穩定 → **stable, holding**。本輪不做改動。
**下一輪 TODO（Round 17）**:同 holding 原則——巡檢;若穩定且無新方向則僅記錄,不動。若使用者醒來給新方向再展開。

## Round 17 — 2026-06-05 04:18 CST(holding)
巡檢全綠:2/2 容器 up、Hermes API 活、bus 4/4 乾淨無殘留、2 快照、scripts×7 design×3 完整。專案功能完整;無新方向 → holding,不做改動。
**下一輪 TODO（Round 18）**:同 holding;巡檢→若穩定僅記錄。等使用者新指示再展開。

## Round 18 — 2026-06-05 04:33 CST(零 Azure)
**step2/3**:把每輪手動巡檢固化成 `scripts/healthcheck.sh`(容器/API/埠/bus/快照,一鍵)。✅ 跑出全綠。README 腳本表 +1(現 scripts×8)。
**驗證結果**:healthcheck 全綠;往後 holding 輪次只需 `healthcheck.sh`。
**下一輪 TODO（Round 19）**:holding;用 `scripts/healthcheck.sh` 巡檢,穩定則記錄。等使用者新方向。

## Round 19 — 2026-06-05 04:48 CST(holding)
`healthcheck.sh` 全綠;無改動。下一輪同 holding。

## Round 20 — 2026-06-05 05:03 CST(holding)
`healthcheck.sh` 全綠;無改動。下一輪同 holding。

## Round 21 — 2026-06-05 05:18 CST(holding)
healthcheck 全綠;無改動。

## Round 22 — 2026-06-05 05:33 CST(holding)
healthcheck 6/6 通過;無改動。

## Round 23 — 2026-06-05 05:48 CST(holding)
healthcheck 6/6;無改動。

## Round 24 — 2026-06-05 06:03 CST(holding)
healthcheck 6/6;無改動。

## Round 25 — 2026-06-05 06:18 CST(holding)
healthcheck 6/6;無改動。

## Round 26 — 2026-06-05 06:33 CST(holding)
healthcheck 6/6;無改動。

## Round 27 — 2026-06-05 06:48 CST(holding)
healthcheck 6/6;無改動。

## Round 28 — 2026-06-05 07:03 CST(holding)
healthcheck 6/6;無改動。

## Round 29 — 2026-06-05 07:18 CST(holding)
healthcheck 6/6;無改動。

## Round 30 — 2026-06-05 07:33 CST(holding)
healthcheck 6/6;無改動。

## Round 31 — 2026-06-05 07:48 CST(holding)
healthcheck 6/6;無改動。

## Round 32 — 2026-06-05 08:03 CST(holding)
healthcheck 6/6;無改動。

## Round 33 — 2026-06-05 08:18 CST(holding)
healthcheck 6/6;無改動。

## Round 34 — 2026-06-05 08:33 CST(holding)
healthcheck 6/6;無改動。下一輪(~08:48)同 holding;09:00 後自我停止。

## Round 35 — 2026-06-05 08:48 CST(holding,9:00 前最後一輪)
healthcheck 6/6;無改動。下一次觸發(~09:03)≥09:00 → 自我 CronDelete 停止。

---

# 🌙 夜間總結(00:24–08:48,35 輪)
**達成**:把 OpenClaw×Hermes 從「兩個獨立 sandbox」做成可 demo 的結合系統,全程未弄壞既有環境、Token_Hunter 未受影響。

**結合層全鏈(皆實測)**:`route.sh` 智慧分流 → `dispatch.sh` 轉派(Hermes 解+偵測新技能)→ Hermes 自我寫 SKILL.md → `skill-sync.sh` 雙向技能共享(含 provenance)→ `snapshot` 持久化。OpenClaw 腿用 `openclaw-cp-task.sh`+`bus-worker` skill(投遞+skill 已驗,UI 觸發手動)。

**關鍵驗證**:Hermes 自我進化(skills 87→89)、雙向知識共享(hermes↔openclaw)、完整 authoring 轉派端到端、技能持久化(snapshot/restore)。

**產出**:`/home/tony/nemoclaw-combine/` — scripts×8(lib/relay/skill-sync/dispatch/openclaw-cp-task/route/healthcheck/demo)、design×4、skills/bus-worker、README/DEMO_MATERIALS/PROGRESS。記憶:project_openclaw_hermes_combine。

**早上可做**:`bash scripts/demo.sh` 走一遍;或在 OpenClaw UI 觸發 bus-worker 把 OpenClaw 腿端到端跑通;或接 Slack/GitHub channel。

**已知限制**:本地 nemotron(CPU)極慢、OpenClaw 無入站 API(故 UI 觸發手動)、Azure 有 TPM、此迴圈僅本 session 存活。詳見 DEMO_MATERIALS 5b。

## (互動,非迴圈) 2026-06-05 ~09:16 CST — 暫停迴圈 + OpenClaw 切 Azure Kimi
- 使用者要求暫停迴圈(已 CronDelete 6a265a5d)並把 **OpenClaw 也換成 Azure Kimi-K2.5**。
- 做法同 hermes-demo:手動備份 openclaw 自訂技能(bus-worker/weekly-status-report/daily-standup-notes → `backups/openclaw-skills/`)→ 調大 onboard 探測逾時 → destroy my-assistant → 重新 onboard(--agent openclaw)指向 Azure Kimi(✓ Inference smoke passed)→ 還原探測檔 → 還原技能。
- ✅ 結果:**兩台 sandbox 皆 Azure Kimi-K2.5**;healthcheck 全綠;Token_Hunter 未動。
- ⚠️ 影響:「本地私密 OpenClaw vs 雲端 Hermes」分工故事消失;route.sh「私密→留本地」語意失效(待按新定位調整或移除)。OpenClaw 現在快了,bus-worker 腿變得可實際 demo(仍需 UI 觸發,因無入站 API)。
- snapshot 註:`nemoclaw my-assistant snapshot create` 報「Pre-backup audit failed」,改用 docker cp 手動備份成功。
**待辦(使用者醒後決定)**:1) DEMO_MATERIALS/architecture 改寫成「同模型、雙 harness」定位(或重新定位 route 規則);2) 真的在 OpenClaw UI 跑一次 bus-worker 端到端(現在快了)。

## (互動) 2026-06-05 ~09:25 CST — 改寫 demo 定位為「同模型、雙 harness」
- 使用者選 1:重新定位。改寫 `route.sh`(分流基準改為 harness 能力:互動/channel→openclaw、可程式化/產技能→hermes,已測正確)、`design/combined-use-case.md`、`design/architecture.md`(圖+角色)、`DEMO_MATERIALS.md`(0/1/3b/4/5b)、README、demo.sh 開場、openclaw-cp-task 訊息。
- 殘留舊「本地 nemotron/私密」字眼已清(僅 DEMO_MATERIALS 踩坑/變更說明刻意保留)。腳本語法全 OK。
- 新定位:同一顆 Azure Kimi,Hermes=可程式化 API+自我進化、OpenClaw=UI/訊息管道+互動前台;依 harness 能力分流。

## (互動) 2026-06-05 — ws 1006 根因 + OpenClaw 腿端到端跑通
- **ws 1006 根因 = netns 不一致**:docker exec 落外層 netns、gateway 在內層 netns listen 18789 → CLI 連不上被包成 1006。修法:`nsenter -t <gw-pid> -n` 進 gateway netns 跑 openclaw CLI(health/agent 立刻連通)。
- **bus-worker turn 三症狀真根因 = 單一 EACCES**:docker cp 的 bus-task.md 由 root/node 擁有、agent(998)讀不到 → 退用 exec → 撞 elevated gate → 繞圈 stuck。修:投遞後 chown 998+chmod 644、絕對路徑、只用 read/write 工具。
- ✅ **OpenClaw 腿端到端跑通**(免 UI):`openclaw-cp-task.sh all "<task>"`(put→nsenter 觸發 openclaw agent→get)兩次驗證成功寫出並取回 bus-result.md。
- 更新:openclaw-cp-task.sh(chown + run/all 子指令)、bus-worker SKILL.md(絕對路徑/禁 exec)、README/DEMO_MATERIALS、記憶。
- 結論:Hermes 腿(HTTP API)與 OpenClaw 腿(nsenter+cp)現在**都可程式化全自動驅動**。

## (互動) 2026-06-05 — dispatch.sh 接入雙腿(自動路由、無人值守)
- `lib.sh` 加 `route_decide`(互動/channel→openclaw;可程式化/產技能→hermes 預設,共用給 dispatch)。
- `dispatch.sh` 改:支援 `--to hermes|openclaw` 或自動 route_decide。openclaw 腿走 `openclaw-cp-task.sh all`(全自動);hermes 腿維持 API 轉派+新技能回流。
- ✅ 整合測試:`dispatch.sh "在 Slack 上回覆早安"` → route→openclaw → 寫出/取回 bus-result(「早安!☀️…」),EXIT=0。`route_decide` 三例選擇正確。
- 更新 README/記憶。→ 兩 harness 現在都能由 dispatch 自動分流、無人值守驅動。

## (互動) 2026-06-05 — dispatch 雙腿分流加進 demo.sh 與講稿
- demo.sh 開場(section 0)加說明:dispatch 用 route_decide 自動選 harness 無人值守執行;昂貴步驟段加 (A0) dispatch 雙腿示範(openclaw / hermes 各一)。
- DEMO_MATERIALS:section 2 (D) 改為 dispatch 雙腿、3b 講稿 2:30 段改成「dispatch 自動分流雙腿」亮點、talking points +1。
- demo.sh 語法 OK;section 0 route 決策實跑正確。

## 迴圈#2 Round 1 — 2026-06-05 14:04 CST(零 Azure)
- 新迴圈 cron a939cfed(每15分,到 2026-06-06 09:00 自停)。系統已完整,定位為穩定維護+小改善。
- step1:healthcheck 全綠(2/2 容器 Kimi、API、埠、bus inbox6/outbox9 無殘留、2 快照)。新 use-case 想法:**協作鏈**(一任務同時用兩 harness:Hermes 產技能→sync→OpenClaw 用),補足目前 dispatch「二選一」的缺口。
- step2/3:新增 `scripts/collab.sh`(骨架:dispatch --to hermes 產技能 → dispatch --to openclaw 用),語法 OK;README 腳本表 +1(標 ⬜ 待實測,因需 2 次 Azure turn)。
- 下一輪 TODO:實跑一次 collab.sh 驗證協作鏈端到端(2 turn,留意成本);順手清理殘留的 stuck session agent:main:main(舊 turn 遺留)。

## 迴圈#2 Round 2 — 2026-06-05 14:20 CST
- step2 ✅ **協作鏈 collab.sh 端到端驗證**:Hermes 產 `meeting-action-items` 技能→自動 sync→OpenClaw 用它把會議記錄輸出成「負責人|任務|截止日」表格。EXIT=0,結果取回 bus/outbox。
- step3/4:README(collab 標 ✅)、DEMO_MATERIALS 驗證表 +「協作鏈」列。
- 註:snapshot pre-collab 仍報 audit 失敗(已知、非阻斷);stuck session 清理未做(低優先)。
- 下一輪 TODO:holding 巡檢為主;若要再加值可考慮把 collab 流程加進 DEMO 講稿/demo.sh 指引。

## 迴圈#2 Round 3 — 2026-06-05 14:35 CST(零 Azure)
- healthcheck 全綠。step3/4:把協作鏈加進 demo.sh 指引 (A1) 與 DEMO_MATERIALS 講稿(3:20–4:00 段)。demo.sh 語法 OK。
- 結合系統現含:分流(route)→ 雙腿轉派(dispatch)→ 協作鏈(collab)→ 雙向技能共享 → 持久化。文件齊備。
- 下一輪 TODO:holding 巡檢;無新方向則僅記錄。

## 迴圈#2 Round 4 — 2026-06-05 14:50 CST(holding)
healthcheck 6/6;系統完整、無新方向 → holding,無改動。

## 迴圈#2 Round 5 — 2026-06-05 15:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 6 — 2026-06-05 15:20 CST(零 Azure,修 bug)
- 追到 **snapshot `Pre-backup audit failed` 根因**:skill-sync 的 docker cp 留下 root/node 擁有(0770)的技能(如 hermes 的 productivity/github),audit 以 sandbox(998)跑 find 進不去 → exit 1 → snapshot 被擋。
- 修:chown 該技能給 998 → ✅ snapshot 立刻成功(v3 post-fix-audit)。根治:`skill-sync.sh` 加 docker cp 後 `chown -R 998`;順手 chown openclaw 端已同步技能。
- step3/4:skill-sync.sh 更新;DEMO_MATERIALS 限制表新增「docker cp 擁有權 → EACCES/snapshot 失敗」+ nsenter 那條。
- 下一輪 TODO:holding 巡檢;snapshot/skill-sync 已穩。

## 迴圈#2 Round 7 — 2026-06-05 15:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 8 — 2026-06-05 15:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 9 — 2026-06-05 16:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 10 — 2026-06-05 16:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 11 — 2026-06-05 16:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 12 — 2026-06-05 16:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 13 — 2026-06-05 17:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 14 — 2026-06-05 17:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 15 — 2026-06-05 17:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 16 — 2026-06-05 17:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 17 — 2026-06-05 18:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 18 — 2026-06-05 18:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 19 — 2026-06-05 18:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 20 — 2026-06-05 18:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 21 — 2026-06-05 19:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 22 — 2026-06-05 19:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 23 — 2026-06-05 19:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 24 — 2026-06-05 19:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 25 — 2026-06-05 20:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 26 — 2026-06-05 20:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 27 — 2026-06-05 20:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 28 — 2026-06-05 20:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 29 — 2026-06-05 21:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 30 — 2026-06-05 21:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 31 — 2026-06-05 21:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 32 — 2026-06-05 21:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 33 — 2026-06-05 22:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 34 — 2026-06-05 22:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 35 — 2026-06-05 22:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 36 — 2026-06-05 22:50 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 37 — 2026-06-05 23:05 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 38 — 2026-06-05 23:20 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#2 Round 39 — 2026-06-05 23:35 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 1 — 2026-06-06 00:48 CST(零 Azure)
- 新迴圈 cron 20041e7d(每15分,到今天 09:00 自停)。healthcheck 全綠(scripts=9、snapshots=3)。
- step4 修兩個 DEMO 瑕疵:① 3b 講稿時間軸重排成不重疊(2:30–3:15 / 3:15–4:00 / 4:00–4:30 / 4:30–5:00);② 第 5 節「待補」(已完成)改寫成「未來可加值」(messaging channel、負案例共享、現場產圖、多步協作鏈)。
- 下一輪 TODO:holding 巡檢為主;系統+文件已完整。

## 迴圈#3 Round 2 — 2026-06-06 01:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 3 — 2026-06-06 01:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 4 — 2026-06-06 01:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 5 — 2026-06-06 01:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 6 — 2026-06-06 02:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 7 — 2026-06-06 02:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 8 — 2026-06-06 02:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 9 — 2026-06-06 02:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 10 — 2026-06-06 03:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 11 — 2026-06-06 03:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 12 — 2026-06-06 03:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 13 — 2026-06-06 03:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 14 — 2026-06-06 04:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 15 — 2026-06-06 04:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 16 — 2026-06-06 04:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 17 — 2026-06-06 04:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 18 — 2026-06-06 05:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 19 — 2026-06-06 05:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 20 — 2026-06-06 05:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 21 — 2026-06-06 05:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 22 — 2026-06-06 06:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 23 — 2026-06-06 06:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 24 — 2026-06-06 06:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 25 — 2026-06-06 06:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 26 — 2026-06-06 07:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 27 — 2026-06-06 07:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 28 — 2026-06-06 07:31 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 29 — 2026-06-06 07:46 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 30 — 2026-06-06 08:01 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 31 — 2026-06-06 08:16 CST(holding)
healthcheck 6/6;無改動。

## 迴圈#3 Round 32 — 2026-06-06 08:31 CST(holding)
healthcheck 6/6;無改動。下一輪(~08:46)為 09:00 前最後一輪;之後自停。

## 迴圈#3 Round 33 — 2026-06-06 08:46 CST(holding,9:00 前最後一輪)
healthcheck 6/6;無改動。下次觸發(~09:01)≥09:00 → 自我 CronDelete 停止。

---
# 🌙 迴圈#3 夜間總結(2026-06-06 00:48–08:46,33 輪)
- 系統本就完整,本夜定位=穩定維護。**全程 healthcheck 6/6 全綠、零事故、Token_Hunter 未受影響。**
- 唯一實質改動在 Round 1:修好 DEMO_MATERIALS 兩個瑕疵(3b 講稿時間軸重疊、第 5 節過時待補→改「未來可加值」)。其餘 32 輪皆 holding。
- 結合系統現狀(可直接 demo):route 分流 → dispatch 雙腿轉派 → collab 協作鏈 → 雙向技能共享 → snapshot 持久化;一鍵 `demo.sh`、`healthcheck.sh` 巡檢。
- Azure 用量:本夜幾乎為零(只跑本地 healthcheck)。
- 早上可:`bash scripts/demo.sh` 走一遍;或挑「未來可加值」項目(接 messaging channel、負案例共享、多步協作鏈)。

## ===== phase 迴圈(cron be270dda,每30分,到 2026-06-08 18:00 自停)=====
新主軸:Hermes=對人前台+自我進化;OpenClaw=IT operator(網管/診斷/bug 修復實作);harness=policy/strategy 治理。協作:人→Hermes 規劃→委派 OpenClaw 實作→回報。
Phase: A 重定位 / B OpenClaw IT 能力 / C Hermes 對人+自我進化 / D harness 治理(核心) / E 委派端到端 / F 收尾。

## phase迴圈 R1 — 2026-06-06 12:18 CST(Phase A,零 Azure)
- ✅ 改 `lib.sh route_decide`:IT/網管/連線/bug/部署/診斷/服務/log/監控/容器→openclaw;其餘(規劃/解釋/報告/需求)→hermes 預設。實測 4 例正確。
- ✅ 重寫 `design/combined-use-case.md`:新角色表 + harness 治理層 + 協作流程(人→Hermes→OpenClaw→人)。
- ✅ DEMO_MATERIALS 第 0 段一句話改成新故事。
- **目前 phase = A(未完)**;下一步:① 改 `design/architecture.md` 的角色/圖標籤成新定位;② DEMO_MATERIALS 第 1 段「架構說明」+ 講稿/talking points 對齊新故事;完成後進 Phase B。

## phase迴圈 R2 — 2026-06-06 13:11 CST(Phase A 完成,零 Azure)
- ✅ 重寫 `design/architecture.md`:mermaid + ASCII 改成「人→Hermes 前台→委派 OpenClaw IT→回報」+ harness 治理框;角色分工段更新。
- ✅ DEMO_MATERIALS 第 1 段「架構說明」改成新故事(角色/治理/協作流/學習)。
- (附:healthcheck.sh 已加時鐘漂移檢查;route_decide 已重定位。)
- **Phase A 完成**。下一步 → **Phase B**:設計+實測 OpenClaw 的真實 IT 任務(查連線/診斷/讀 log/範例 repo 修 bug),用 `openclaw agent`(nsenter)實跑 1 個驗收。先做「在 egress 允許內、最小、可驗證」的 IT 任務(如:沙箱內 curl 一個允許的端點並回報狀態,或讀某 log 找錯誤),記成 eval/it-tasks 草稿。

## phase迴圈 R3 — 2026-06-06 13:41 CST(Phase B 完成,1 Azure turn)
- ✅ 新增 `scripts/it-fix-demo.sh`:放有 bug 的 adder.py 進 OpenClaw 沙箱(chown 998)→ `openclaw agent`(nsenter)診斷+修(read/write 工具)→ host 跑驗證。
- ✅ 實測:OpenClaw 找出 `range(1,10)` 漏 10、改成 `range(1,11)`,輸出 SUM=45→**55 PASS**。→ **OpenClaw=IT operator(bug 修復實作)能力驗證**。
- DEMO_MATERIALS 驗證表 +「OpenClaw=IT operator」列。
- **Phase B 完成**。下一步 → **Phase C**:Hermes 接「人類需求」→ 產人看得懂的規劃/報告;遇重複型問題寫 SKILL.md,實測一次(1 Azure turn,bounded)。

## phase迴圈 R4 — 2026-06-06 14:11 CST(Phase C 撞 429;順手做 Phase D 唯讀盤點)
- ⚠️ **Phase C 嘗試 → Azure 429 速率限制**(Kimi-K2.5 eastus2 TPM 超標;Phase B turn + 此 authoring 太密集)。無新技能、無規劃產出。**不硬重試**,下一輪(速率重置後)再跑 Phase C。→ 證實 DEMO 5b 的 TPM 限制是真的。
- ✅ 零 Azure 利用:先做 **Phase D 唯讀 policy 盤點** → 新增 `design/governance-inventory.md`(現況:兩台 balanced;hermes egress 偏對人整合、openclaw 偏精簡;差異化治理提案;demo 佐證法 ALLOWED/DENIED;改 policy 守則=snapshot+dry-run+不切斷 inference.local)。
- **目前 phase = C(待重試)**;下一步:速率重置後重跑 Phase C 的 dispatch(customer-progress-report),成功後進 Phase D active(用盤點好的設計做差異化治理 demo,先 dry-run)。

## phase迴圈 R5 — 2026-06-06 14:41 CST(Phase C 完成,1 authoring turn)
- ✅ **Phase C 達成**:Hermes 自我進化出對人技能 `customer-progress-report`(skills 92→93),內容完整(什麼是/何時用/不適用/標準流程/模板,frontmatter 還自動連 related_skills),dispatch 自動 sync 給 OpenClaw。→ Hermes=對人前台+自我進化 角色坐實。
- 註:最後一句閒聊回覆撞 429,但技能(持久產出)已成功寫出,核心達標。DEMO 驗證表 +Phase C 列。
- **Phase A✅ B✅ C✅**。下一步 → **Phase D active(治理核心)**:用 governance-inventory.md 的設計,做差異化治理 demo —— 以**唯讀展示 + 行為佐證**為主(讓某 agent 連白名單外 host → log DENIED;允許的 ALLOWED),證明 code-層治理。真要 policy-add 才先 snapshot+--dry-run。先做「行為佐證」最小實驗(zero/low Azure):在沙箱內 curl 一個白名單外 host 看 DENIED、curl inference.local 看 ALLOWED。

## phase迴圈 R6 — 2026-06-06 15:11 CST(Phase D 核心完成,零 Azure)
- ✅ **治理行為佐證**(從 logs 撈到真實 ALLOWED/DENIED):OPA 三層強制 —— host(`ALLOWED inference.local`)、path/method(`DENIED ... POST /api/show`)、binary(`DENIED example.com/pypi.org [engine:opa] failed to resolve peer binary`)。→ 治理=code 非 prompt,鐵證。
- 寫進 `governance-inventory.md` 行為佐證段;DEMO 驗證表 +Phase D 列。
- 註:手動 curl 測 host 白名單會全 403,因 proxy 按 binary+path 治理(非純 host)——這本身就是 binary 層佐證。實際 policy-add(差異化 egress)屬不可逆,保留為「可選 live 步驟,需 snapshot+--dry-run」,demo 用現成 log 佐證即可,不貿然改。
- **Phase A✅ B✅ C✅ D✅(核心)**。下一步 → **Phase E**:把「Hermes 規劃→委派 OpenClaw 實作→回報」串成可重跑腳本(在 dispatch/collab/it-fix 之上),實測一個 IT 情境(例:Hermes 收「服務算錯」需求→委派 OpenClaw 修→Hermes 回報)。

## phase迴圈 R7 — 2026-06-06 15:41 CST(Phase E 腳本建好,零 Azure)
- ✅ 新增 `scripts/it-collab.sh`:端到端「人→① Hermes 前台確認+指派→② OpenClaw(nsenter+agent)修可驗證 bug(adder SUM 45→55)→[host 驗證]→③ Hermes 對人回報結案」。3 個 bounded Azure turn。語法 OK。
- 本輪刻意**不 live 測**(剛 R5/R6 用過 Azure,避免又撞 429;讓速率多恢復)。
- **目前 phase = E(腳本待 live 驗證)**;下一步:跑 `it-collab.sh` 一次,確認三段鏈通(Hermes 指派→OpenClaw 修→SUM=55→Hermes 回報);若 429 則下輪再試。通過後進 Phase F 收尾。

## phase迴圈 R8 — 2026-06-06 16:11 CST(Phase E 完成,3 bounded turns)
- ✅ **Phase E 端到端 PASS**:`it-collab.sh` 三段鏈全通 —— ① Hermes 前台確認問題+指派 ② OpenClaw 修 adder bug(range(1,10)→(1,11),驗證 SUM=55)③ Hermes 對客戶回報結案。EXIT=0。→ 「人→Hermes→OpenClaw→人」協作主線坐實,無 429。
- DEMO 驗證表 +Phase E 列。
- **Phase A✅ B✅ C✅ D✅ E✅**。下一步 → **Phase F 收尾**:① DEMO_MATERIALS 5 分鐘講稿改寫成新故事(對人前台/IT operator/治理/委派);② 跑 `eval.sh` 確保全綠且教訓沉澱兩台;③ 全綠後 PROGRESS 記「DEMO-READY」並降為輕量維護。

## phase迴圈 R9 — 2026-06-06 16:41 CST(Phase F 1/2,零 Azure)
- ✅ DEMO_MATERIALS 改寫成新主線:3b 5 分鐘講稿(人→Hermes 前台→OpenClaw IT→治理→回報,以 it-collab/治理 log/自我進化為核心段)+ Talking points(分工取長/治理/協作主線/自我進化持久化)。
- **目前 phase = F(1/2 完成,差 eval 全綠)**;下一步:跑 `eval.sh` 確認全綠且教訓沉澱兩台 → 全綠後 PROGRESS 記「DEMO-READY」、降為輕量維護(只 healthcheck)、回報可提早停。(本輪不跑 eval 避 429,下一輪跑。)

## phase迴圈 R10 — 2026-06-06 17:11 CST 🎯 DEMO-READY
- ✅ `eval.sh` **5/5 全綠**(T1-T5 全 PASS),教訓沉澱進兩台 lessons-learned SKILL.md(chown 998)。
- ✅ **全部 phase 完成:A✅ B✅ C✅ D✅ E✅ F✅**;DEMO_MATERIALS 已反映新故事;達成完成準則。
- **狀態 = DEMO-READY**(比 6/8 18:00 提早 ~2 天)。之後輪次**降為輕量維護**(每輪只 `healthcheck.sh`,無改動);可提早停(CronDelete be270dda)。
- demo 可秀:① `it-collab.sh` 委派主線(人→Hermes→OpenClaw→人)② 治理 log 三層 ALLOWED/DENIED ③ Hermes 自我進化(customer-progress-report)④ OpenClaw 修 bug(SUM 45→55)⑤ eval 負案例→沉澱兩台。
**下一輪起 TODO**:只 healthcheck 巡檢、記 holding;有紅燈才處理;等使用者驗收/給新方向或提早停。

## phase迴圈 R11 — 2026-06-06 17:41 CST(DEMO-READY,輕量維護)
healthcheck 全綠(含時鐘同步);無改動。已 DEMO-READY,後續僅巡檢到 6/8 18:00 或使用者提早停。

## phase迴圈 R12 — 2026-06-06 18:11 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R13 — 2026-06-06 18:41 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R14 — 2026-06-06 19:11 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R15 — 2026-06-06 19:41 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R16 — 2026-06-06 20:11 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R17 — 2026-06-06 20:41 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R18 — 2026-06-06 21:11 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## phase迴圈 R19 — 2026-06-06 21:41 CST(DEMO-READY,維護)
healthcheck 全綠;無改動。

## (互動 demo) 2026-06-06 21:5x CST — Hermes 自我進化現場展示 + 修 sync bug
- ✅ Hermes 現場自我進化:產 `incident-postmortem` 技能(skills 93→94,devops/ 分類,7 段含 5 Whys/MTTD-MTTR/Blameless/Action Items)。
- 🐛 **發現+修真 bug**:`skill-sync.sh` 來源路徑寫死 `productivity/`,但 Hermes 會自選分類(放 `devops/`)→ dispatch 自動 sync 失敗。已改成**動態 find 整棵 skills 樹**(`SRC_ROOT` + `find -name`),重跑成功 sync 到 OpenClaw。
- (it-fix-demo / it-collab / 治理三層 log 亦於本互動段現場跑過,皆 PASS。)

## 迴圈停止 — 2026-06-06 22:xx CST(使用者要求 CronDelete be270dda)
phase 迴圈停止。狀態 = DEMO-READY:A-F 全完成、eval 5/5、五個 demo 段現場驗過(OpenClaw 修 bug、it-collab 委派鏈、治理三層 log、Hermes 自我進化、eval 學習閉環)。需要時手動 `bash scripts/demo.sh` / `healthcheck.sh` / `it-collab.sh`。

<!-- 之後每輪在此之上 append 新的 Round N 區塊 -->

## 2026-06-06 — Telegram 通道接 Hermes(端到端 ✅)
- 需求:人可經 Telegram 跟 harness agent(Hermes 對人前台)對話。
- 做了:`channels add telegram`(讀 TELEGRAM_BOT_TOKEN/ALLOWED_IDS,排入變更)→ `rebuild --yes`(需 COMPATIBLE_API_KEY 在環境)→ bridge 上線。新用戶 tony(5488297243)經 `hermes pairing approve telegram <code>` 核准。
- 驗證:容器重建、Hermes 仍 Azure Kimi-K2.5、6 個自我進化技能全存活、log 持續 `ALLOWED POST api.telegram.org/.../getUpdates`、實機發訊 Hermes 有回。
- 坑(已記憶):`channels add` 不吃 `--yes`;非互動 rebuild 需 COMPATIBLE_API_KEY;勿自行 `( )&` 雙重 detach 誤判完成。
- 下一步:DEMO_MATERIALS 第 5 節該項標記為已完成(亮點)。維護模式,無待辦。

## 2026-06-06 — eval transient-timeout 沉澱 bug 修復
- 症狀:eval.sh 一次 4/5,T5 因 Azure 逾時 FAIL,卻把「呼叫失敗: timed out」當教訓沉澱進 lessons.json,覆蓋掉 T5 真正的「需含 ATLAS」教訓,並散播進兩台 lessons-learned SKILL.md(污染)。
- 修:eval.py 區分 errored(呼叫例外,transient)vs 內容檢查失敗。errored → 不沉澱、不清既有教訓、標記 ERR;只有內容失敗才沉澱。LEDGER/終端摘要加 ⚠️/ERR 標示與「未沉澱」說明。
- 還原 lessons.json={T5:["輸出必須包含「ATLAS」"]} 重新渲染兩台 → 重跑 eval.sh = 5/5,T5 recovered(含 ATLAS)、教訓自動清 0。閉環正確。

## 2026-06-06 — 快照還原參考點(DEMO-READY 乾淨狀態)
兩台同名快照 `telegram-eval-clean`,捕捉完整 demo 狀態,任何實驗壞掉可一鍵回此點:
- hermes-demo **v7** `telegram-eval-clean`:Telegram 通道 + 6 自我進化技能(customer-progress-report/weekly-status-report/daily-standup-notes/meeting-action-items/lessons-learned/incident-postmortem)+ 刷新 lessons-learned + Kimi-K2.5。
- my-assistant **v1** `telegram-eval-clean`:OpenClaw 同步的 lessons-learned + Kimi-K2.5。
- 還原:`nemoclaw <sandbox> snapshot restore telegram-eval-clean`(改 policy/大改前先回此點;先前還原點 v5 pre-telegram-check 為「未接 Telegram」狀態)。

## (補記) 2026-06-08 ~ 06-10 — bridge 真委派 + demo_telegram.md(迴圈停止後的互動工作,當時未入帳)
- **bridge/(06-09)**:OpenClaw 容器內 :9099 入站修復端點(`openclaw-fix-endpoint.py`,POST /fix 非同步、GET /last、/health)+ scoped `openclaw_bridge` policy(只放行 Hermes→172.18.0.2:9099)+ Hermes 端 `it-delegate-openclaw` 技能 → **Hermes 可自委派 OpenClaw**,「OpenClaw 無入站 API」限制有了 scoped 例外。`boot-stack.sh ensure_xagent()` 開機自動拉起。
- **demo_telegram.md(06-10)**:三主題全 Telegram 逐條腳本(含 bridge 委派實演 2-b)。
- **boot-stack `rebuild_mail_ca_bundle`(06-11 凌晨)**:每次 boot 以「當前」MITM CA 重建 ca-mail-bundle,修「Telegram ~2h 後靜默死(stale CA,gateway 重連 ~20 次放棄)」的坑。

## (互動) 2026-06-11 — 重開機復原 + 全機盤點 + demo 材料 post-bridge 大更新
- **重開機復原**:WSL 重啟後全 stack down → `boot-stack.sh` 拉回全綠。坑:開機後 1-2 分鐘內跑會在 step1 失敗(`could not inspect the OpenClaw gateway`,沙箱還在自癒),等一下重跑即過(冪等)。實機驗證:Telegram 輪詢中、:9099 health OK(4 場景待命)、mail 橋 3993/3587 就緒、ca-mail-bundle 已用當前 MITM CA 重建。
- **全機盤點(nemoclaw/openshell/hermes/openclaw/deck 五路並行調查+反駁式驗證)**:機會清單沉澱進 DEMO_MATERIALS §5(重排)。要點:nemoclaw 0.0.45(最新 0.0.63)、`hosts-list` 壞(docker flag bug)、Hermes 有 18 種 channel platform/cron/TTS/attachment+vision 未用、OpenClaw 有 22 種原生 channel/gateway cron/53 內建技能未用、OpenShell 有 `policy prove`/global policy lock/`policy update` 熱改/OCSF JSON sink/Prometheus 未展示、enterprise-deck 影片腳本仍是舊「單 agent 機隊稽核」故事且 sandbox 端 .network-ops 證據已隨 06-05 重建消失。
- **文件/腳本同步(post-bridge)**:DEMO_MATERIALS(標頭日期、新 §2b bridge 章節、驗證表+「跨 agent 真委派」列、3b 講稿 0:50/2:10 段、§6 主題2(b) 改「Hermes 自委派」、「四場景皆已實測 PASS」說法統一〔沙箱 it-task/ 四檔皆含 # FIX:〕、5b 介面非對稱加 :9099 例外、5c 補 openclaw-*.md 清理、§5 重排)、control-demo.sh(委派主路徑改 Hermes 自委派,it-collab 降為備援)、route.sh(改 source lib.sh `route_decide`,消除與 dispatch.sh 相反決策的翻車點)、demo.sh(Slack 例句換 IT 字眼句、GUIDE 加 (A2) bridge 段)、relay.sh/openclaw-cp-task.sh 過時註解、design/openclaw-bus-poller.md(標已實作)、design/combined-use-case.md(跨 agent egress 開放問題標已解)、bridge/it-delegate-openclaw-SKILL.md(去重複章節)、healthcheck.sh(納管 :9099/greenmail/:3587;Token_Hunter 降為 warn)、README(補 send-mail-as.sh)。
- 已知未做(全列 DEMO_MATERIALS §5):bridge IP 動態化、/last 持久化、eval 委派鏈回歸、policy 收斂、nemoclaw update 等。

## (互動) 2026-06-11 下午 — 決定拿 combine 參賽:BUG=drift 真實場景 + bridge 加固 + 競賽腳本 combine 版
**背景**:使用者定案以 combine 雙 agent 成果參賽(評分:實用 55%/商業 20%/技術 15%/資安 10%)。最大落差=實用價值原靠 deck 線真實機隊數字,combine 只有合成 bug → 把 deck 證據接進 combine 主線。
- **BUG=drift 場景(競賽主打)**:fix endpoint 泛化成多檔場景(files/fixfile/check/timeout),嵌入真實 RT-AX89X baseline/current(去掉答案註解)+`driftcheck.py` 驗收器。**設計:只修安全退化(ssh.password_login、logging.remote.*),一般漂移(ssh.port、wifi 頻道/頻寬)不動、列待審**——治理紀律本身就是賣點。lib.sh bug_scenario 加 drift(僅 bridge 路徑);it-collab BUG=drift 導引至 bridge-regress。
- **Bridge 加固三件套**:① IP 動態化——ensure_xagent 以 docker inspect 渲染 preset/SKILL,rebuild 不再靜默斷鏈;② `X-Bridge-Token` 認證(`bridge/.bridge-token`,403 否則;`policy-add` 同名 preset 實測會**升級替換**,allowed_ips 已收斂 `<IP>/32`,OPA broad-CIDR MED 警告來源消除);③ `/last` 落盤 `it-task/last-fix.json` + busy 409 防併發。Telegram 不受 policy bump 影響(實測輪詢正常)。
- **e2e 實測 PASS**:`bridge-regress.sh drift`(新增,從 Hermes netns 經 L7 proxy 走與 Hermes 完全相同路徑)——POST 接受→修復→驗收 `REGRESSIONS=5→0 DRIFTS=3(不動)`,**44 秒**;OPA 鐵證 `ALLOWED /usr/bin/curl → POST .../9099/fix [policy:openclaw_bridge engine:opa]`。
- **競賽腳本 combine 版**:enterprise-deck 新增 `*-video-script-combine.md`(PPT 8 頁:雙 agent 故事+保留痛/爽/省快機隊數字+44s MTTR)與 `*-demo-video-script-combine.md`(7 段分鏡:Telegram 報修→自委派→drift 實修→追問結案→email 通道→治理鐵證→自我進化→誠實收尾;實用價值段 ≥2/5;含錄影前 checklist 與 429 對策);舊兩檔標 superseded。
- 文件同步:DEMO_MATERIALS(§2b 加固版、驗證表+drift 列、場景速查 5 場景、§5 完成標記)、demo_telegram(drift 場景)、README(bridge-regress + bridge 段)。
- **剩餘(錄影前)**:PPT 檔(.pptx)依 combine 腳本改版;彩排 Telegram drift 劇本一次;可選:policy prove 段、TLS/CVE 第二場景。

## (互動) 2026-06-11 晚 — 參賽定案:主軸對齊 + Jira 升級 + CVE 監控 + 競賽 PPTX + demo 正常→攻擊重排
使用者定版主軸:**NemoClaw** 管 agent 生命週期與復原 · **OpenShell** 沙箱隔離+安全 policy · **Hermes** 對人前台+派工 · **OpenClaw**(可多台 IT 機隊,現一台 sample):①監控設備狀態+定期掃 CVE ②接報修實修+驗收 ③修不了/需人審→Jira 升級工程師(人在迴路)。
- **競賽 PPTX**:`nemoclaw-enterprise-deck/ASUS-NemoClaw-Competition-2026-combine.pptx`(8 頁,生成器 `build-combine-pptx.py` 可重生;沿用既有 ASUS 藍/痛紅/爽綠/JhengHei 視覺、自畫向量)。對齊評分(實用 55/商業 20/技術 15/資安 10);slide 3 流程含「修不了→Jira」、slide 5 四元件分工(OpenClaw 三職責+機隊、NemoClaw 生命週期)、slide 6 正常 vs 攻擊對照。兩份 *-combine.md 影片腳本同步補 監控/CVE/Jira/機隊/NemoClaw 復原。
- **Jira 升級路徑(真實)**:fix endpoint 加 `open_jira()` + `GET /jira`;drift 修完 5 退化後為 3 待審漂移開 change-approval 工單、任何 ok=False 開 auto-fix-failed 工單。實測 drift→開單 NETOPS-… assignee=network-engineer。
- **CVE 監控(真實、零 Azure)**:endpoint 加確定性 CVE 掃描 `GET /cve` + `GET /monitor` + `scripts/cve-scan.sh`(可 cron)。機隊 5 台(enterprise-deck 真實版本)× 3 CVE → 2 affected(openwrt dropbear/openssl,自動開 Jira)、1 needs_review、12 unknown_inventory_gap(ASUS 無 SBOM 不假裝安全)。去重:同 cve+asset 已 open 不重開。
- **bridge 加固延續**:/health 加 `jira`/`cve` 標記,boot-stack gating 升級;token 認證 + /32 + IP 動態渲染(前批次)維持。
- **demo 改「正常→攻擊」對照**(使用者要求):`demo_telegram.md` 重寫成 Part A 正常維運(報修→自委派→修退化+待審 Jira→結案 / A1b 監控+CVE / email / 自我進化)→ Part B 攻擊對照(B1 偷用端點無 token 403 / B2 外連 DENIED / B3 洩密 placeholder / B4 轉帳邊界 / B5 未授權寄件者);寫死容器名改開頭一行動態解析。`security-demo.sh` 加 S8(跨 agent 通道 token+/32 被鎖)。
- **主軸偏移修正(workflow 12 條)**:四元件角色描述全面補齊(DEMO_MATERIALS §0/§1/§6、design/combined-use-case、demo_telegram、it-collab/it-fix/userstory/control/security 口白、README 新增四元件角色段);NemoClaw 從「編排層」改「生命週期與復原層」;demo.sh 去「非雲端 SaaS/本地私密」論述;Hermes SKILL 補 Jira/pending_review 回報。
- **audit 25 條 + README**:全套修(provenance 技能名、bridge 同 turn+token、drift/bridge-regress、IP 動態、四場景→五場景、§6 日期、it-fix drift 導引、dispatch/relay/cp-task 註解…);README 加四元件角色段、競賽當天執行順序 runbook、cve-scan/it-collab/it-fix 腳本列。
- 驗證:所有 .sh `bash -n` 全綠;endpoint py compile OK;healthcheck 全綠(:9099 drift+auth+jira+cve);bridge-regress drift 44s PASS;cve-scan 2 affected→Jira 去重 OK;PPTX 8 頁無溢出(幾何+CJK 折行 linter + Pillow 目視)。demo 用工單佇列已重置乾淨。
- **剩給使用者**:① PPTX 用真 PowerPoint 開一遍(JhengHei 在 Windows 才有,Linux 端用 Pillow 幾何預覽驗過版面);② 真手機彩排 Telegram Part A/B 一輪;③(可選)把 cve-scan 排進 OpenClaw 原生 cron 展示「定期」。

## (互動) 2026-06-12 — 對齊使用者改版 PPTX:實作 Jira 治理 egress(slide 6 ALLOWED [policy:jira])
使用者在 PowerPoint 大改 combine pptx(Multi-Agent 品牌、加技術架構/核心優勢開場、slide2 加「有被最新 CVE 影響」、slide7 註「先用 telegram/greenmail/Jira 做 demo」、結尾加未來展望 Vera Rubin 中央大腦分佈式圖)。比對 local 找出唯一具體 demo-claim 落差 = slide 6「修不了→Jira→ALLOWED [policy:jira]」之前只寫本機檔、無治理 egress。
- 實作:`bridge/jira-mock.py`(host :3690 mock Jira/ITSM)+ `bridge/openclaw-jira-preset.yaml`(OpenClaw `jira` egress policy,放行 host.openshell.internal:3690)+ endpoint `open_jira` 經 `nsenter→L7 proxy(10.200.0.1:3128)→curl POST` 送單(best-effort,本機檔仍為來源真相);`boot-stack ensure_jira` 自動拉起 mock+policy;healthcheck 納管 :3690。
- 驗證 e2e:cve-scan 開 2 單 → 端點 log `[JIRA EGRESS] ok via policy:jira`;**OpenClaw OPA log `ALLOWED /usr/bin/curl(...) -> POST http://host.openshell.internal:3690/rest/api/2/issue [policy:jira engine:opa]`**;host mock Jira 收到 NETOPS-1001/1002。→ slide6 宣稱現為真。telegram/greenmail/jira 三條對外動作全部 code 治理。
- demo_telegram A1 / cve-scan / DEMO_MATERIALS §2b 補 policy:jira 鐵證行。
- 其餘 pptx 落差屬「願景/未來」(多台 OpenClaw 機隊、Vera Rubin 中央大腦)或「離線即優點」(CVE 比對 air-gapped)→ 列為 pptx 建議(不改檔)。

## (互動) 2026-06-12 — PPTX A/B/C 改進(就地)+ 10 分鐘 demo 影片腳本與驅動
- **PPTX 改進**(使用者編輯版 `ASUS-NemoClaw-Competition-2026-combine.pptx`,14 頁,就地改保留版式;備份 .bak.pptx;`edit-combine-pptx.py` 可重跑):A1 slide9 巡檢 ALLOWED→改「離線比對」框架;A2 slide6 scoped box + slide9 底線補回 /32+token;A3 slide5 錯字「改壞」;C6 slide7 中段加回 6×3 人工vs雙代理對比表;C7 slide11 補回「現在就在跑:44 秒…」收尾句。lint OOB=0 OVERFLOW=0,Pillow 目視 slide7 表不溢出/不疊。
- **10 分鐘影片**(`nemoclaw-enterprise-deck/ASUS-NemoClaw-Competition-2026-10min-demo-script.md`):純實機畫面、不帶 PPT;10 段約 2400 字旁白(NemoClaw 復原 / OpenShell 隔離治理 / 主線報修→自委派→修退化+待審開 Jira→結案 44s / CVE 機隊掃描 / email 通道 / 自我進化+快照 / 攻擊對照 / 治理全景 / 收尾)。
- **驅動腳本** `scripts/demo-video-driver.sh`:分段大字幕+跑指令+段尾暫停等旁白;`DRIVER_MODE=phone|auto`(auto 用 bridge-regress/API 免手機)、`AUTO_ADVANCE=<秒>`。所有 eval 嵌套引號行實測 OK。錄製前 boot-stack→healthcheck→bridge-regress 暖機。

## (互動) 2026-06-12 — NVIDIA 推理治理路徑 + 全 script 驗證一輪
- **NVIDIA(讓 NemoClaw 名副其實)**:`scripts/nvidia-inference-demo.sh`。無 key 但兩沙箱 egress 已放行 `integrate.api.nvidia.com:443`(`policy:nvidia`,含路徑層只准 /v1/chat/completions 等 + 授權 binary python3/hermes)。從 hermes 沙箱用 python3 經 L7 proxy 實打 NVIDIA → **OPA log `ALLOWED /usr/bin/python3 -> integrate.api.nvidia.com [policy:nvidia engine:opa]` + `ALLOWED POST .../v1/chat/completions [policy:nvidia engine:l7]`**;NVIDIA 回 401=路徑通、等 key。設 NVIDIA_API_KEY 即真打 Nemotron。加進 10 分鐘腳本(1:40 段)+ driver + README。
- **全 demo script 驗證一輪(2026-06-12)**:bash -n 26 支全綠。逐支實跑結果:
  - 零成本 ✅:healthcheck、route(4 決策正確)、control-demo、security-demo(S1 外連 403 / S4 binary DENIED / S7 遮罩 / S2 未授權寄件者 / S3 自動信 / S8 跨 agent token 403 全觸發)、cve-scan(2 affected+治理 jira)、nvidia-inference-demo、demo.sh、skill-sync(防覆蓋跳過)、lessons-to-skill、boot-stack。
  - Azure ✅:relay(hermes 回覆)、it-fix-demo fw(UP_TO_DATE→UPDATE_AVAILABLE PASS)、dispatch openclaw 腿(cp-task all 取回 hello)、it-collab fw(三段委派 e2e PASS)、eval(5/5)、collab(產技能→sync→OpenClaw 用,行動項表 PASS)、bridge-regress drift(44s,前批)。
  - ⚠️ userstory-demo:MAIL e2e + 治理 log ✅,但「內嵌 it-collab 單檔修復」本輪非確定性 FAIL(OpenClaw 該 turn 沒改檔、報「待原廠修復」)。同一支 it-collab 數分鐘前 standalone PASS → 屬 LLM 非確定性(非 code bug;DEMO_MATERIALS 5b 已記)。**競賽主線用 bridge/drift 路徑(端點驅動、明確指令+驗證,穩);it-collab 單檔為腳本備援、非確定。**
  - demo-video-driver.sh:orchestrator,語法 + 關鍵嵌套引號指令實測 OK;未整支跑(會串接所有 Azure)。
- 系統跑完一輪仍全綠;jira 佇列已重置乾淨。

## (互動) 2026-06-12 — source-CVE:有原始碼→SBOM+code 證據+SAST(補 unknown_inventory_gap)
使用者問「OpenClaw 若能看手冊/原始碼能加什麼應用」→ 選做 B6/B7。endpoint 加 `GET /source-cve` + `scripts/source-cve-demo.sh`:
- 植入 RT-AX89X 韌體 source(`it-task/source/<asset>/`:diag.c 命令注入 CWE-78、auth.c 硬編憑證 CWE-798、packages.manifest)。
- run_source_scan:① 由 manifest 生 SBOM;② 同台 CVE 由 `unknown_inventory_gap`(無 SBOM)升級為 **affected**(dropbear 2022.83<2024.84、openssl 3.0.12<3.0.13,版本+SBOM 證據);③ pattern-based SAST 命中危險樣式附 file:line+code;④ affected/SAST 去重後開 Jira(經 policy:jira 治理 egress)。/health 加 `source` marker、boot-stack gating。
- e2e 驗證:SBOM 4 套件、2 CVE gap→affected、2 SAST(diag.c:9、auth.c:4)、4 Jira(治理 log ALLOWED policy:jira)、去重 OK(2 run 仍 4)、開檔佐證秀出 source。
- 賣點:**補掉「ASUS 韌體無 SBOM」這唯一誠實弱點**(『不知道』→『指得出哪一行』);治理面=source IP 只在沙箱讀、egress deny 確保帶不出去。
- 文件:README 腳本表 +source-cve-demo;DEMO_MATERIALS §5 記;後續可做 code-patch 升級 Jira(B8)、跨機隊 patch 遷移。

## (互動) 2026-06-12 — B8:修不了→附建議 code patch 的 Jira
延續 source-CVE,把「SAST 發現→開單」升級成「附可合併 patch 的開單」:
- endpoint `SRC_FIXES`(diag.c 命令注入修法=valid_host 輸入驗證+execlp 參數化不經 shell;auth.c 硬編憑證修法=getenv hash+常數時間比對)。`run_source_scan` 為每個 SAST 發現產 `difflib.unified_diff`、寫 `it-task/patches/<file>.patch`、**驗證套用後 sink 消失**(窄化 CWE-78 sink 到 system|popen,execlp 修法才驗得過),patch 進 Jira 工單 description(```diff)。
- e2e 驗證:2 SAST→2 patch、patches_verified=2、Jira SAST 工單 patch=YES、host mock Jira 收到含 diff 工單、**兩 patch 皆 `git apply --check` 乾淨套用**、去重 OK。治理足跡 ALLOWED [policy:jira]。
- 文件:README 腳本表更新、DEMO_MATERIALS §5 B8。能力:端點 source+jira+cve+drift+auth 全在;22 支腳本語法全綠;jira 佇列重置乾淨。

## (互動) 2026-06-12 — it-cve-mail-demo:新 CVE 經 mail→OpenClaw 讀源碼產 patch→Jira
使用者要 it-fix-demo 的「真實版 case」:新 CVE 經 mail 進來 → 修 code patch。
- 新腳本 `scripts/it-cve-mail-demo.sh`(3 段):① 資安通報 email(命令注入 CVE-2026-1337)經授權寄件者進來 → Hermes 前台收+回信(實測真回:「收到,資安漏洞通報,我立即協助確認…」)② 委派 OpenClaw 讀韌體 source(`/source-cve`)→ 定位 diag.c:9 CWE-78 → 產**已驗證 patch**(execlp 參數化)→ 開 Jira(policy:jira 治理)③ 治理足跡(greenmail_mail + policy:jira ALLOWED)。
- 定位:it-fix-demo(合成算術 bug,留作簡單 beat)的真實版——真 CVE 通報→真 code patch,串起 email 通道+source-CVE+B8 patch。
- e2e 驗證 PASS;README 腳本表 +it-cve-mail-demo;jira 佇列重置。

## (互動) 2026-06-12 — 建最新配對快照 combine-2026-06-12 + 修 registry agent bug
使用者要一份最新的 hermes/openclaw 快照。
- **發現並修 registry bug**:`~/.nemoclaw/sandboxes.json` 的 **hermes-demo `agent` 是 null** → nemoclaw 當預設 openclaw → `snapshot create` 去備份 `/sandbox/.openclaw`(hermes 容器無此目錄)→ 抓到 **0 files**(空快照);`nemoclaw list` 也誤顯示 agent: openclaw。改成 `"agent": "hermes"`(備份 `sandboxes.json.bak-2026-06-12`)→ list 正確、snapshot 改抓 `/sandbox/.hermes`。my-assistant 維持 null(=openclaw,正確)。
  - ⚠ caveat:registry-recovery 用 `metadata.agent || null` 重建,未來某次 `nemoclaw recover` 可能把 hermes-demo agent 重置回 null → 若 hermes 快照又變空,重查 sandboxes.json 此欄。
- **配對快照 `combine-2026-06-12`**(最新還原點,取代 06-06 的 telegram-eval-clean):
  - hermes-demo **v8**:13 dirs + SOUL.md + state.db;25 技能(含 devops/it-delegate-openclaw)、pairing、memories、sessions。
  - my-assistant **v2**:13 dirs;workspace/skills 7 同步技能、workspace/it-task(source + patches 都在)。
  - 還原:`nemoclaw <sb> snapshot restore combine-2026-06-12`(改 policy/大改前回此點)。註:bridge 端點/policy/jira-mock 屬 host+boot-stack 管,不在快照內,還原後跑 boot-stack 補齊。

## (互動) 2026-06-12 — driver auto 跑出兩個 bug:snapshot 顯示 + Hermes 簡中
- **snapshot 顯示 bug**:demo-video-driver.sh 6:30 段 `snapshot list | head -3` 只截到「Snapshots for/空行/表頭」(資料列第 4 行才開始)→ 看不到快照。改 `| grep -aE 'Version|v[0-9]' | head -5`。
- **Hermes 回簡中**:Kimi 預設簡中。改 `/sandbox/.hermes/SOUL.md` 加「Always reply in Traditional Chinese (繁體中文,台灣用語)。Never use Simplified Chinese」→ **不用重啟即生效**(SOUL.md per-request 讀)。實測一般+IT 委派情境皆繁中。
  - ⚠ SOUL.md 在快照內(stateFile copy)→ 還原舊快照(如 telegram-eval-clean)會帶回舊 SOUL.md(簡中)。已重做 combine-2026-06-12 含繁中 SOUL.md。
- 重做 hermes 快照 combine-2026-06-12(含繁中 SOUL.md + demo 新長技能 drift-closure-report)。

## (互動) 2026-06-12 — driver auto 整段跑通 + 繁中調查(Kimi 長文硬限)
- **driver auto 整段 PASS**(零真實失敗;「1 ERR」是 S8 攻擊預期的 403)。逐段鐵證齊全:1:40 NVIDIA `ALLOWED policy:nvidia`(opa+l7)/ 2:40 drift `REGRESSIONS 5→0` + bridge-regress PASS + `policy:openclaw_bridge` / 4:30 CVE affected 2 + `policy:jira` / 5:30 email Re: + `greenmail_mail` / 6:30 自我進化長新技能 config-drift-closure / 7:20 攻擊 403×4 DENIED / 9:00 治理全景(ALLOWED+DENIED 同框,新 deny 探針生效)/ 9:40 全綠。
- 修兩 bug:① driver snapshot `head -3` → `grep -aE 'Version|v[0-9]'`(原本截在資料列前看不到快照);② SOUL.md 加繁中規則。
- **繁中調查結論(重要)**:Kimi-K2.5(陸製)**短回覆守得住繁體**(Telegram/API/委派 ack 實測繁中),**長的結構化 email 報告(表格/標題)會倒回簡體**——即使清空 session+memories+重啟+強化 SOUL.md(含字例)仍如此。屬模型偏置,非設定可解。
  - 緩解:① 強化 SOUL.md 已部署(短文有效)② demo 以 Telegram 為主(短、繁中穩)③ email 重點是治理 log(`greenmail_mail`),回覆 prose 偶簡體不影響該賣點 ④ 真解=換繁中友善模型(可接 NVIDIA 託管/台灣模型)或在 harness 出口接 OpenCC 簡→繁(需改 harness)。
- SOUL.md 在快照內 → 還原舊快照會帶回舊 SOUL.md;已重做 combine-2026-06-12 含強化版。系統穩定全綠、jira 重置。

## (互動) 2026-06-12 下午 — 四元件使用 case 強化(對齊新 ASUS-AgenticAI-Competition-2026.pptx)
使用者改拿 `nemoclaw-combine/ASUS-AgenticAI-Competition-2026.pptx`(6MB、18 頁,含 13-15 實測截圖頁、18 Vera Rubin 未來圖)參賽。review 四元件 vs 投影片宣稱,找出三個「有寫、未兌現」落差並全部做成真:
- **/monitor baseline 比對(主動發現)**:現況 vs 核准基準逐鍵比對,安全鍵偏離→`ALERT(n 安全退化)`+`[MONITOR ALERT]` log,一般漂移列 pending_review;確定性零 Azure。
- **主動告警 `monitor-alert-demo.sh`(凌晨兩點閉環;demo_telegram 新 A0 段)**:植入漂移(素材 import 自 endpoint 常數,單一真相來源)→/monitor ALERT→告警信進值班信箱→Hermes 真呼叫 send_message 推 Telegram(鐵證 `ALLOWED POST api.telegram.org/bot[CREDENTIAL]/sendMessage [policy:telegram]`)→手機回「修」接 A1。`--no-push`=零 Azure 彩排。e2e PASS。
  - **坑(已記 DEMO_MATERIALS 5b)**:Hermes API(:8642)的 turn **沒有 channel 工具**(relay 進來只會回「我沒有 Bot Token」);主動推播必須走通道入口(email 告警信),同 control-demo (d) 模式。
- **SECURITY-DESIGN.md 設計符合性(slide10「design document」宣稱落地)**:設計文件植入 source/,REQ-SEC-01~05 機器可驗(config 對現況 conf、code 對 SAST 命中);違反條款寫進 SAST Jira 工單(設計→實作可追溯)。drift 態 4/5 violated、修復後 2/5(code);SAST 掃描範圍收斂到 .c/.h/.py/.sh/.lua(不掃設計文件自己)。
- **定期 CVE 內建排程**:endpoint `BRIDGE_CVE_INTERVAL`(預設 86400;啟動 75s 後掃首輪)+ 每掃落 `it-task/cve-scan-history.jsonl`(trigger=schedule/api 時間戳=「定期」證據);cve-scan.sh 印排程+最近 3 筆歷史。
- 周邊:/health 加 `design`/`monitor`/`periodic_cve_sec`、boot-stack gating 升級(+design,舊端點會被換新);新 `jira-reset.sh`(重置工單,歷史保留);source-cve-demo 新 ③b 設計段;README(腳本表+runbook+角色)/demo_telegram(A0+A1b)/DEMO_MATERIALS(§5 完成+5b 新限制)同步。
- 驗證:py compile+bash -n 全綠;boot-stack 重部署 gating 正確;monitor-alert --no-push 與全程(sendMessage OCSF+遮罩)PASS;設計符合性 drift/fixed 兩態 PASS;**bridge-regress drift PASS(5→0、3 不動)主鏈未破**;cve-scan 歷史含 schedule 首輪;healthcheck 全綠;jira 佇列重置、monitor=ok。端點備份 `bridge/openclaw-fix-endpoint.py.bak-2026-06-12`。
- **PPTX 建議(未動檔,留使用者 PowerPoint 改)**:①頁碼 stale——slide5 與 slide8 都標「3/8」、slide6 標「2/8」在 slide5 之後、18 頁 footer 仍 /8;②slide10「OpenClaw ×N 水平擴展」現一台 sample——保留既有誠實講點或考慮 NemoClaw 現場 deploy 第二台(賽前風險高,不建議);③slide18 Vera Rubin 可口頭帶 nvidia policy 今日 hook(`ALLOWED [policy:nvidia]`)。

## (互動) 2026-06-12 — 規劃 64h 自主 loop(到 06-15 08:00)+ pre-loop 快照
使用者要用 /loop 疊代 repo 到 06-15 週一早 8 點(約 64h、跨週末)。判斷:repo 已 DEMO-READY,loop 該偏「確定性/可累積/低風險」工作,別把 demo 改脆、別狂打 Azure。主軸選定=**分階段全包**。
- 寫 `LOOP-PLAN.md`(loop 單一真相來源):每輪 SOP、護欄(不碰 pptx 二進位/不大改主線/Azure 低頻/每輪 healthcheck/連兩輪紅就還原)、Phase 1 擴張+沉澱(EVIDENCE 矩陣 / policy prove / 第二台機隊 / govboard 指標 / business-case)→ Phase 2 守護(loop-regress ledger + 已知坑監測)→ Phase 3 凍結收斂(FEATURE-FREEZE / qa-prep / PPTX-TODO / demo-ready 快照)、停止條件(時間閘 06-15 08:00)。
- pre-loop 還原點 `combine-pre-loop-0612`(hermes v9 / my-assistant v3)。
- 待使用者打 `/loop` 啟動;啟動後每輪照 LOOP-PLAN.md 推進、每日打 combine-loop-<MMDD>、到時間自動停。

## (loop) 2026-06-12 晚 — Phase 1 完成(擴張+沉澱證據;除 P1-3 主鏈驗證外全零 Azure)
LOOP-PLAN.md 自主 loop Phase 1 五項全成(輪1–5):
- **P1-1** `EVIDENCE.md`:18 頁 PPTX 宣稱→可重現指令+鐵證矩陣(A 報修/B 監控CVE源碼/C 資安正常vs攻擊對照/D 技術生命週期)。
- **P1-2** `scripts/policy-prove-demo.sh`:`openshell policy prove` 形式化窮舉外洩面;誠實 framing(gap 全在套件/跨agent/mail 白名單 L4 端點,對照非白名單動態 DENIED)。EVIDENCE D5。
- **P1-3** `/monitor` 巡 2 台機隊:endpoint 加 OpenWrt 真實 baseline(UCI)+ `MANAGED` 清單(各自安全鍵)+ `_conf_kv` 支援大寫 UCI 鍵 + `seed_monitor_assets` + `managed` health marker/gating。bridge-regress drift 驗 fix 主鏈未壞。EVIDENCE B6。
- **P1-4** `scripts/govboard.sh`:治理指標儀表板(6 類 policy ALLOWED + ~2.5k DENIED + Jira 7 張 by kind + CVE 分級 + 機隊 2 台 + MTTR 44s)。EVIDENCE D6。
- **P1-5** `design/business-case.md`:商業計畫草稿(市場/痛點價值/TAM/定價/競品/ROI 試算 200台省~65%/GTM/誠實風險);補商業 20% 最弱項,數字待 Tony 校準。
快照:pre-loop=`combine-pre-loop-0612`、當日=`combine-loop-0612`。系統全程零紅燈;主鏈 drift 44s e2e 維持。
下一階段=Phase 2(loop-regress 守護 + 已知坑監測)→ 純守護到 06-14 08:00 → Phase 3 凍結收斂。

## (loop) 2026-06-12 19:06 — Phase 2 完成 + 轉純守護
- **P2-1** `scripts/loop-regress.sh` + `eval/LOOP-LEDGER.md`:6 項零成本確定性檢查(containers/health/monitor/cve/source/prove)逐項 PASS/FAIL,append ledger 一行/輪;實跑 fails=0。
- **P2-2** 已知坑監測(併入):telegram getUpdates 近 6 分存活計數(驗 2h 不靜默死)、近 30 分 Azure 429 計數,趨勢進 ledger。
- **轉純守護模式**直到 06-14 08:00:每輪只跑 loop-regress(零 Azure)、長 interval ~3600s;每日一次 bridge-regress drift(Azure 主鏈);連兩輪紅→還原 combine-pre-loop-0612。06-14 08:00 進 Phase 3(凍結收斂)。
- Phase 1+2 共新增:EVIDENCE.md、LOOP-PLAN.md、design/business-case.md、scripts/{monitor-alert,jira-reset,policy-prove-demo,govboard,loop-regress}.sh、eval/LOOP-LEDGER.md;endpoint /monitor 擴 2 台機隊。系統零紅燈。

## (互動) 2026-06-13 08:30 — 使用者實機 EBG19P 接入機隊當真實第三台
使用者有 ASUS ExpertWiFi EBG19P(商用 PoE+ VPN 閘道,韌體 3.0.0.6.102_45537,2025/01)。接入為機隊真實第三台受管設備:
- **endpoint**:FLEET +EBG19P(第6台,無 SBOM)、`EBG19P_BASELINE`(ASUSWRT/ExpertWiFi 風格真實設定面:管理介面 https/wan_access、SSH、防火牆/DoS、VPN wireguard cipher、SDN-VLAN、PoE 8埠、遠端 logging、韌體自動更新)、`EBG19P_SECURITY`(7 安全鍵)、MANAGED +第三台、`seed_monitor_assets` 改 dict seed ebg19p。
- 主線改動前快照 `combine-loop-0613`(hermes v11/openclaw v5)。重部署驗證:/monitor managed=3 全 ok、/cve fleet=6(unknown_inventory_gap 15=5台×3)、EBG19P 告警測試(植 ssh.wan_access+webui.http→ALERT(2)→還原 ok)、healthcheck 10綠、**bridge-regress drift PASS(fix 主鏈未壞)**。
- **修 `loop-regress.sh` monitor 檢查 2→3**(否則守護輪誤報 FAIL→連紅觸發還原)。
- 文件:EVIDENCE B6(3台/各台安全鍵)、demo_telegram A1b(3台+gap15)、business-case GTM Phase1(EBG19P 實證:新機型上線只需 baseline+安全鍵)、README/cve-scan.sh(6台)。
- 賣點:新機型上線 = 一份核准 baseline + 安全鍵定義,監控/CVE/告警即時涵蓋;商用閘道安全面比家用廣(SSH/管理介面 WAN 暴露、VPN cipher、防火牆/DoS),正中 business-case 商用客群。回純守護模式。

## (loop) 2026-06-13 09:30 — Phase 3 完成 → LOOP-PLAN 工作隊列(Phase 1+2+3)全清空
- **P3-1** 功能凍結(使用者要求提早進 Phase 3,跳過 06-14 時間閘)。
- **P3-2** `design/qa-prep.md`:16 題評審 Q&A(差異化/資安含 policy-prove 誠實題/技術/商業/落地)+ 佐證指令 + 一句話收尾。
- **P3-3** `PPTX-TODO.md`:待使用者 PowerPoint 手改清單(頁碼 stale 必改 + 新能力建議補講點;loop 不碰二進位)。
- **P3-4** 最終驗收:bridge-regress drift PASS、jira-reset、healthcheck 10綠、/monitor 3台 ok;打 `combine-demo-ready` 快照(hermes v12/openclaw v6)= 最終還原點。
- **整個 loop 工作隊列做完**。轉純守護到 2026-06-15 08:00 自動停。
- **loop 期間總產出**:文件 EVIDENCE.md / LOOP-PLAN.md / PPTX-TODO.md / design/{business-case,qa-prep}.md;腳本 monitor-alert / jira-reset / policy-prove-demo / govboard / loop-regress;eval/LOOP-LEDGER.md;endpoint 強化(/monitor baseline 比對+3台機隊含實機 EBG19P、CVE 6台、定期排程、SECURITY-DESIGN 符合性)。系統全程零紅燈、drift 主鏈 44s 維持。
- **還原點**:`combine-demo-ready`(最終)、`combine-loop-0613`、`combine-pre-loop-0612`。

## (事故+修復) 2026-06-13 09:30–10:14 — deploy 第二 OpenClaw 破壞 gateway,已完全修復
- **起因**:量第二 OpenClaw 足跡,跑 `nemoclaw onboard --non-interactive --name openclaw-probe --agent openclaw`。非互動預設 NVIDIA provider(需 NVIDIA_API_KEY→失敗),但**失敗前已破壞現有環境**:把 host gateway 從 18080「當 stale 重建」到 8080、停 my-assistant forward、SIGKILL my-assistant 容器;連帶 hermes API down。
- **損害**:gateway 跑 8080、my-assistant+hermes 容器 Exited(非刪除,資料全在,快照都在)。greenmail 不受影響。
- **死結**:健康 gateway 已起在 18080(容器連著、OPA policy 正常),但 openshell **registration 還指死掉的 8080** → recover 連 8080 refused。中間 rebuild 也卡(需 COMPATIBLE_API_KEY + 容器停無法備份 state)。
- **解法(關鍵)**:`openshell gateway remove nemoclaw` + `openshell gateway add http://127.0.0.1:18080 --name nemoclaw` → registration 對齊 18080、`openshell status` Connected → `boot-stack.sh` 全綠。
- **驗證**:healthcheck 10綠、loop-regress fails=0、monitor managed=3(含 EBG19P)、cve 2 affected、source/prove OK。完全恢復。
- **教訓**:`onboard --non-interactive` 會接管/重建 gateway(預設 8080+NVIDIA),**絕不可對有現有 stack 的機器跑**。量足跡用現有 my-assistant 680MiB idle 推算即可(6 台 idle≈4GiB,WSL2 7.5GiB 會緊、active 會 OOM)。使用者貼了 COMPATIBLE_API_KEY 在對話 → 建議輪換。

## (loop) 2026-06-13 10:36 — Phase 4 完成(PPTX 架構對齊驗證)+ 回純守護
使用者事故後改 loop 主軸=PPTX 架構對齊驗證(零風險,Phase 4 鐵律:不碰 onboard/deploy/gateway)。
- **P4-1** `design/pptx-architecture-map.md`:6 區逐項 PPTX→實機對應(四元件/連線隔離/治理三層/代理流水線/監控機隊/未來願景)+ 驗證指令 + 狀態。
- **P4-2**:確認 ⚠/✗ 無硬缺口 —— 邏輯機隊、NVIDIA 需 key、多機隊/中央大腦都是誠實現實/roadmap 標註。
- **P4-3** 抽驗代表項全對:四元件=2 沙箱、scoped 通道 172.18.0.2/32、端點 5 場景+jira/cve/source/design+managed=3、hermes ALLOWED 5 類 policy。
- **結論**:PPTX slide 1–12 核心架構實機逐項 ✓ 對應;slide 18 分佈式願景誠實標 roadmap(本機 WSL2 7.5G 限制 + 06-13 事故證明強推會破壞 stack)。
- 整個 loop 工作隊列(Phase 1-4)全清空 → 純守護至 06-15 08:00。README 補 pptx-architecture-map + qa-prep。

## (互動) 2026-06-13 16:20 — 第二台 OpenClaw 達成(snapshot restore --to,安全;非 onboard)
使用者反覆要兩台 OpenClaw。改用 `nemoclaw my-assistant snapshot restore combine-demo-ready --to openclaw-2` —— 從現有 OpenClaw 快照複製出第二台,**用現有 18080 gateway、不重配 inference、不碰 gateway port、不停現有容器**(對比 onboard 的破壞)。
- 結果:nemoclaw list 三沙箱(my-assistant + hermes-demo + **openclaw-2**,都 openclaw/compatible-endpoint/Kimi);openclaw-2 容器 running + 連上 gateway(OPA policy reloaded)+ idle ~566MiB 趨穩。現有系統 healthcheck 10 綠完好、gateway :18080 沒被動。
- **足跡實測**:單台 OpenClaw idle ~300–570MiB(my-assistant 現 308、openclaw-2 566 趨穩,比之前估的 680 樂觀);三沙箱系統 used 3000MiB/7.5GiB、available 4.6GiB → 兩台輕鬆、3–4 台 idle 可行,同時多台 active 才 OOM。
- **方法修正(重要)**:建第二/多台 OpenClaw **不必 onboard**(危險,會破壞 gateway)——用 `snapshot restore --to <新名>` 安全。推翻 06-13 上午「只能 onboard」的結論。
- **待定**:openclaw-2 去留 —— 保留則需納入 boot-stack(目前只管 my-assistant+hermes,重開機不會自動恢復 openclaw-2)+ 可選納 loop 守護;或驗證完 destroy 省資源。

## (互動) 2026-06-13 18:21 — openclaw-2 納管完成(保留為真實第二台 OpenClaw)
使用者選「保留並納管」。
- **dashboardPort 衝突**(兩台都繼承 18789)→ 改 openclaw-2 → **18790**(備份 `/tmp/sandboxes.json.bak-openclaw2-port`);recover 後兩台 UI 各自通(:18789 my-assistant / :18790 openclaw-2 都 200)。
- **boot-stack 加 §1b**:`docker ps -a` 找 openclaw-2 容器 → `docker start` → `NEMOCLAW_GATEWAY_PORT=18080 nemoclaw openclaw-2 recover` → 等 :18790(**非致命**,失敗不擋主 stack)。重開機自動拉起。
- **loop-regress 加 openclaw2 項**(容器在=✓;不在=SKIP)。實跑 fails=0、openclaw2 ✓。
- 兩台 OpenClaw 都 compatible-endpoint/Kimi、共用 18080 gateway;系統 used 3000/7.5GiB、available 4.6GiB。
- 註:openclaw-2 是 my-assistant 快照複本(workspace/it-task/source/skills 相同);demo 展示「真的兩台 OpenClaw 代理」足夠。若要當「分管不同設備的獨立機隊節點」需另配(目前同內容複本)。

## (loop) 2026-06-13 21:30 — 修 loop-regress 的 429 假警報
ledger 之前的「azure429 近30分 429×N」是**假警報**:`grep '429'` 誤抓 mail 輪詢每 10 秒遞增的 socat 進程 PID(`socat1(4295)`、4296…),非 HTTP 429。查證:hermes 近 10 分 Azure(chat/completions)調用 0、my-assistant/openclaw-2 也 0。改精確 pattern(`too many requests|rate.?limit|HTTP…429|429 too/client/error`),重跑「近30分無 429」。系統一直健康,ledger 早前的 429×N 可忽略。守護 fails=0、兩台 OpenClaw 在。

## (互動) 2026-06-14 01:30 — 兩 OpenClaw 節點分區(完整落地 part 1/2)
使用者要兩台 OpenClaw 完整分工。設計:Hermes 前台 / 節點 A(my-assistant,zone A)=無線線(rt-ax89x/xt12/eba63)/ 節點 B(openclaw-2,zone B)=基礎設施線(openwrt/ebg19p/esc4000)。
- endpoint 加 `BRIDGE_ZONE` 過濾(run_cve_scan/run_monitor 按 zone、/health 加 zone)。備份 .bak-pre-split、快照 pre-split-fleet(my v7/openclaw-2 v1)。
- 部署:my-assistant BRIDGE_ZONE=A、openclaw-2(172.18.0.4)裝端點 BRIDGE_ZONE=B(同 token)。
- 驗證:節點A /monitor=rt-ax89x、/cve 3 台全 gap(9);節點B /monitor=openwrt+ebg19p、/cve 3 台 **2 affected**(openwrt SBOM)。分區正確。
- loop-regress 改兩節點合計(monitor A1+B2=3、cve affected A0+B2=2),fails=0。
- **剩 part 2**:T10 policy 放行 Hermes→172.18.0.4/32、T11 Hermes it-delegate 按設備路由 + boot-stack 納管 openclaw-2 端點(否則重開機後 B 端點沒、守護 cve 會 FAIL)、T12 文件/記憶。

## (互動) 2026-06-14 01:10 — 分工 part 2a:policy 放行兩節點(T10)
- openclaw-bridge-preset.yaml 加第二 endpoint(節點 B 占位 172.18.0.4 + allowed_ips 172.17.0.0/12 避 sed 撞)。
- 手動渲染兩台 IP + policy-add hermes-demo → policy v9,**兩節點各 /32**(172.18.0.2/32 + 172.18.0.4/32)。
- 驗證:Hermes netns 經 L7 proxy → 節點B(172.18.0.4:9099/monitor)→ 200,OPA `ALLOWED /usr/bin/curl → GET 172.18.0.4:9099/monitor [policy:openclaw_bridge engine:opa]`。跨節點通道真通。
- 剩:T11 boot-stack ensure_xagent 重構(部署兩台 zone 端點+渲染兩台 policy,持久化;否則重開機後節點B端點/policy 沒)、Hermes it-delegate 按設備路由;T12 文件。⚠ T11 前勿重開機。

## (互動) 2026-06-14 01:25 — 分工完整落地完成(part 2b:T11+T12)
- **T11 boot-stack 持久化**:加 `deploy_oc_endpoint`(冪等部署單台 zone 端點,health 對 zone 才 skip)、`oc2_ip`;ensure_xagent 部署兩台(節點A zone A、節點B zone B)+ 渲染兩台 policy(172.18.0.2/32 + 172.18.0.4/32)+ 兩節點 IP 進 SKILL。冪等跑 boot-stack 驗證全綠(兩端點當前版、policy 兩 /32)。重開機自動回來。
- **T11 Hermes 路由**:`it-delegate-openclaw-SKILL.md` 加分區路由(無線→節點A 172.18.0.2、閘道/商用→節點B 172.18.0.4),/last 對應節點、邊界兩節點。已渲染部署 Hermes(grep 確認兩節點 IP)。
- **T12 文件/記憶**:記憶 ebg19p-fleet-third-device 更新兩節點分區、EVIDENCE B6 改 2 節點+B7 路由、pptx-architecture-map §1 OpenClaw 改 2 實例分區 ✓。
- **待補(demo 腳本,非阻塞)**:demo_telegram 報修路由說明、README 兩節點分工段(下輪或 demo 前順手)。
- **完整分工達成**:前台 Hermes 判型→依設備路由→節點A(無線:rt-ax89x/xt12/eba63)或節點B(基礎設施:openwrt/ebg19p/esc4000)→該節點修自己那區。兩節點各自 monitor/cve/policy/端點,loop-regress 兩節點合計守護。系統全綠。

## (互動) 2026-06-14 01:55 — 分工改「職責導向」(使用者要 A 運維 / B 資安,非設備線)
使用者澄清:分工要按職責,不是設備線。重改:
- **endpoint 職責模型**:`ZONE_CAPS`(A=monitor+fix、B=cve+source+monitor)、`ZONE_MONITOR`(A=rt-ax89x+ebg19p、B=openwrt)、`_zone_has`/`_monitor_asset`。cve 改**全機隊掃**(B 才做)、source B 才做、A 的 cve/source 回「資安職責,本節點不做」。/health 加 role/caps。備份 `.bak-pre-role`。
- **驗證**:節點A role=IT運維 caps=[fix,monitor] monitor=rt-ax89x+ebg19p cve=不掃;節點B role=資安 caps=[cve,monitor,source] monitor=openwrt cve=全機隊6台 2 affected。
- **loop-regress 適應**:monitor A2+B1=3、cve A0+B2=2、**source 對節點B 檢查**(資安職責)。fails=0。
- **SKILL 職責路由**:運維報修/漂移→節點A、OpenWrt/CVE/原始碼/SBOM→節點B(ebg19p 歸 A 運維)。⚠ 上一版設備分區 SKILL 的 Edit 曾**憑記憶 old_string 不匹配靜默失敗**→這次 Read 後精確改、host grep 確認部署(容器內 grep 中文受 locale 影響,要用 host grep 驗)。
- 記憶 ebg19p 更新職責版。**待同步(下輪)**:EVIDENCE B6/B7、design/pptx-architecture-map §1 從「設備分區」文字改「職責分工」。

## (loop) 2026-06-14 02:06 — 職責分工文件同步完成 → 回守護
- EVIDENCE B6(機隊→2節點職責分工:A運維 monitor+fix/B資安 cve+source)、B7(Hermes 職責路由)、pptx-architecture-map §1(OpenClaw→2實例職責分工)文字同步(Read 後精確改,免重蹈 SKILL Edit 失敗)。
- 職責分工現全部一致:endpoint(ZONE_CAPS/ZONE_MONITOR)、loop-regress、SKILL、EVIDENCE、pptx-map、記憶 ebg19p。守護 fails=0。
- 回純守護到 06-15 08:00。

## (互動) 2026-06-15 00:20 — Web Agent Status Dashboard(競賽 web 視覺化)
使用者要「除了 pptx,web 可看整個 AGENT STATUS DASHBOARD」。
- **`bridge/agent-dashboard.py`**(host web server,:8899):`GET /` 出 HTML(深色 ASUS 配色、5s 自動刷新);`GET /api/status` 即時收集——四元件(NemoClaw 快照/OpenShell gateway+DENIED/Hermes API+Telegram 輪詢/OpenClaw 機隊)、**兩節點職責分工**(A 運維 caps+monitor rt-ax89x+ebg19p、B 資安 caps+CVE 全機隊+SBOM/SAST)、機隊 monitor、治理 ALLOWED by policy + DENIED、Jira by kind、bridge /32×2、NemoClaw 快照。唯讀為主(讀 health/monitor + cve/source 報表檔,不觸發掃描副作用)、每 call timeout、整體快取 8s、單項失敗降級;**X-Bridge-Token 只 server 端用,不入 HTML/JSON**(已驗無洩漏)。
- **納管**:boot-stack `ensure_dashboard`(早退+完整路徑都呼叫;`setsid` 啟動、非致命,重開機自動拉起);healthcheck 加 :8899 檢查(全 11 項綠)。
- 驗證:/api/status 回真實資料(4 容器、節點A運維 rt-ax89x+ebg19p、節點B資安 CVE 6台2affected+SBOM4/SAST2、ALLOWED greenmail/telegram、DENIED 64、Jira 4 kinds、bridge 2×/32、快照 6);token 洩漏檢查 OK。
- 坑:`pkill -f agent-dashboard.py` 會殺到自己的 Bash shell(命令列含該字串)→ 用 setsid 乾淨啟動;boot-stack 內 pkill 安全(boot-stack 命令列不含該字串)。
- 開啟:WSL2 下 Windows 瀏覽器開 http://127.0.0.1:8899(localhost 轉發)。

## (互動) 2026-06-15 01:0x — dashboard 視覺精進
使用者嫌不夠漂亮 → 重寫 agent-dashboard.py 前端(只改 HTML/CSS/JS,不動 stack):
- 頂部 KPI 大數字條(節點在線/受管設備+ALERT/越權DENIED/CVE affected/MTTR/快照);玻璃擬態卡片+backdrop-blur+漸層光暈+hover lift;四元件各自配色(紫NemoClaw/青OpenShell/綠Hermes/藍OpenClaw)+ accent 頂條。
- 資料視覺化:節點 B **CVE 甜甜圈 SVG**(affected/needs_review/gap)+ 圖例 + SBOM/SAST/設計違反 stat 方塊;治理 **ALLOWED by policy 橫條圖**;節點設備 status chip + 發光 dot;LIVE 脈動指示。
- collect 補 node scenarios/alerts。安全重啟(用 :8899 port PID 殺舊,不自殺)。Windows Chrome 重截(328KB,版面 1480×1000 全收)。screenshot 更新 agent-dashboard-screenshot.png。

## (互動) 2026-06-15 01:1x — dashboard Apple 風重設計 + 可操作 + monitor 新功能
使用者:太像 AI 生的、要參考 Apple 色調、網頁要可控、想 monitor 新功能。重寫 agent-dashboard.py:
- **Apple 美學**:淺色預設(#f5f5f7 底/白卡/細 hairline/大量留白/SF 字體/克制單一 accent #0071e3)+ **深色切換**(true black #000,localStorage 持久、開頁不閃白);圓角 18px、subtle shadow。
- **網頁可控**:控制列 segmented(主題 淺/深、自動刷新 關/5/15/30s、節點 全部/A/B)+ 一鍵動作按鈕 → **POST /api/action?do=cve|source|jira_reset|refresh**(server 端帶 token 執行;掃描確定性、jira-reset demo 重置;localhost only)+ toast 回饋。
- **monitor 新功能**(自己想+實作):① **告警橫幅**(有 ALERT/離線→紅,否則綠「全系統正常」)② **即時治理事件流**(OCSF ALLOWED/DENIED tail,濾 getUpdates 心跳,顯示時間/verb/policy/target)③ **趨勢 sparkline**(治理動作量、Telegram 心跳 rolling ring 40 點,server 端 HISTORY)④ **守護歷史**(讀 LOOP-LEDGER.md,綠/紅 dot + 主鏈驗 marker)。
- collect 補 events/history/guard/alerts_list;safe 重啟(port PID 殺)。Windows Chrome 重截淺色版(150KB,1340×1560)。

## (互動) 2026-06-15 01:42 — 新 loop 主軸:Dashboard UI/UX 卓越化(做到 08:00)
使用者:要商業客戶等級設計感(字體/色塊/色卡)+ 順 UX,用 loop 持續精進到 08:00,每輪(1)想加什麼(2)自評能否過關(3)實作。LOOP-PLAN 加 Phase 5 + 10 項自評 rubric + 迭代佇列。
- **I1 完成**:agent-dashboard.py 重寫——設計 token 精煉(tabular-nums 數字對齊、間距、AA 對比色卡、淺/深雙主題)、**分區 memo 渲染**(內容沒變不重繪→消除原本每 5s 整頁 innerHTML 的閃爍,這是最大 UX 病)、a11y focus-visible、favicon、進場 fade。Windows Chrome 截圖確認商業質感大幅提升。
- **自評(誠實)**:①視覺層級 ②字體/數字 ③色彩雙主題 ④間距 ⑥無閃爍 ⑩商業質感 → 過;**⑤ 資料視覺化不過**:donut/sparkline 在 SVG `stroke="var(--x)"` 用 CSS 變數**不生效**(SVG presentation 屬性不吃 var())→ 圖表空白。I2 修(JS getComputedStyle 取色 + theme 變更重取 + 加動畫)。
- 截圖法沿用 Windows Chrome headless(/mnt/c)。重啟用 :8899 port PID kill(勿 pkill -f agent-dashboard.py,會殺 shell)。

## (loop) 2026-06-15 09:49 — Phase 5 I2:資料視覺化修好
- **donut 改 CSS conic-gradient**(SVG 多段 stroke-dasharray + class 動畫在 Windows Chrome headless 渲不出來→改 conic 硬編色三段[紅 affected/琥珀 needs_review/灰 gap]+遮罩做圈+中心 affected 數,最穩);截圖確認正確顯示。
- sparkline 加末點圓點 + area 填色(趨勢藍/綠折線可見);事件流 target regex 清理(host:port,不再誤抓 [policy:]);主題切換即時 loadColors+重繪;移除每 tick 淡入(沉穩即時更新)。
- count-up/bar 動畫故意不做:denied/allowed 每 tick 變→動畫每 5s 重播會吵,商業 UX 求沉穩。
- 下一步 I3:互動 slide-over 抽屜(點設備看 drift/regressions)、密度切換、鍵盤快捷。

## (loop) 2026-06-15 10:08 — Phase 5 I3:分頁 IA 重構(用戶指定)
- 單頁長捲 → **側欄 menu + hash 路由分頁**(6 tab:總覽/機隊監控/資安CVE/治理事件/升級守護/設定)。
- ① **KPI 可點跳轉**:KPI tile 改 `<a href="#tab">`(hover 顯 → 箭頭),DENIED→治理事件、CVE affected→資安、設備/節點→機隊、MTTR/快照→升級守護。
- ② **設定收進動態 tab**:主題(淺/深)、顯示密度(舒適/緊湊)、自動刷新(關/5/15/30s)、預設節點篩選、手動重整 + 關於(停機門檻/OCSF/憑證安全/鍵盤快捷)。
- ③ **側欄 menu 列全 tab** + 即時告警徽章(資安 2 / 治理 64)+ 底部即時連線狀態。
- 新增:事件 ALLOWED/DENIED 篩選、CVE affected 弱點明細表、SAST 命中表(CWE/檔/行)、機隊分頁內聯展開 regressions/pending、鍵盤 1–6 切頁 / r 重整 / d 主題。
- 修:DENIED 保證進事件流(否則被高頻 ALLOWED 擠掉、篩選空白);target regex 加一般網域(抓 inference.local:443 等 DENIED 外連)。
- 驗證:dash-overview/cve/gov/settings.png 四分頁截圖,商業質感與資料正確皆確認。Python 邏輯(collect/do_action/handlers)僅 events 切片增強,未動 stack/gateway。
- 下一步 I4:連線 stale 徽章、kiosk demo 全螢幕、匯出/列印、深色主題新版截圖驗證;本輪後跑 loop-regress(I1/I2/I3 達 3 輪)。

### I3 收尾(同輪)
- 驗深色主題時抓到並修掉**真 bug**:`do_GET` 用 `self.path in ("/","/index.html")` 比對,`/?theme=dark` 帶 query → 404「not found」。改 `urlparse(self.path).path` 去 query。
- 順帶加 `?theme=dark|light` 可分享/kiosk 主題連結(inline 預設腳本讀 query 寫 localStorage)。
- 深色主題在新分頁版面截圖確認 OK(dash-dark.png):純黑底、深色側欄、藍色 active tab、徽章、AA 對比。
- loop-regress 全綠 fails=0(I1/I2/I3 三輪守護)。

## (loop) 2026-06-15 14:46 — Phase 5 I4b:國際化 + 設定垂直化(用戶指定)
- **語言切換 English / 繁體中文**:全 UI 字串抽成 i18n 字典(`I18N={zh,en}` + `t(k)`),設定→外觀內切換,存 `localStorage nclaw-lang`,`applyChrome()` 即時重繪導覽列/標題/副標/按鈕/側欄,無需重載。
- **設定頁垂直化(上下)**:外觀/資料/關於三 topic 從並排三欄 → 單欄垂直堆疊(max-width 660,iOS 設定風),較好讀。
- 細節:`roleT()` 翻節點職責(IT 運維↔IT Ops…)、MTTR「44 秒↔44s」、`toLocaleTimeString` 依語系(en-US 不再顯示「下午」)、動作 toast 依語系、`html lang` 屬性切換、`?lang=`/`?theme=` 可分享/kiosk 連結。
- 驗證:dash-set-zh / dash-set-en / dash-ov-en2 截圖,中英×淺色皆乾淨完整;Python(collect/do_action/handlers)未動。
- 下一步 I5:對 10 項 UX rubric 逐項自評,誠實答「能否交付商業客戶」,之後 plateau→守護。

## (loop) 2026-06-15 14:52 — 機隊監控 + 資安CVE 也改直式(用戶指定)
- 延續設定頁垂直化:**機隊監控**兩節點卡 → 單欄上下堆疊(max-width 840);**資安/CVE** 甜甜圈分級卡 / Affected 弱點表 / 原始碼卡 → 單欄上下堆疊(max-width 900,affected 表變寬更好讀,移除多餘區段標題)。
- 截圖 dash-fleet-v / dash-cve-v 驗證直式正確。總覽/治理/升級守護維持原排版(儀表板綜覽橫向較合適,用戶未要求改)。

## (loop) 2026-06-15 15:17 — Phase 5 I5:UX 過關自評 10/10 → 轉守護
- 對 10 項 rubric 逐項自評全過(視覺層級/字體tabular/對比雙主題/間距/資料視覺化/微互動無閃爍/空載入錯誤/a11y/RWD/商業質感)。
- 本輪補洞:⑦ **載入骨架**(shimmer skeleton,冷啟動 collect 慢時主內容不再空白)+ ⑧ a11y(icon 按鈕 aria-label、導覽 aria-current、document.title 隨分頁)。
- **誠實結論:可交付商業客戶**(內部維運監控盤 / demo 級)。非阻斷保留:8px 節奏非嚴格、極窄手機未逐一微調、後端 500 前端降級可再硬化。
- healthcheck 全綠(11 項含 Dashboard :8899)。**品質 plateau → 轉守護模式**(長間隔 1800s,每輪 healthcheck+保活到 06-16 08:00 自停)。Dashboard 至此功能完備:側欄分頁 IA、可點 KPI、雙語 i18n、直式版面、密度、事件篩選、明細表、連線健康徽章、kiosk、可分享連結。

## (loop) 2026-06-15 16:1x — 使用者 4 項:CVE→NIST、deny log 日期、DENIED 顯示被擋物、真掃描器
- **#2 CVE→NIST 連結**:資安/CVE 的 affected 表 CVE 欄改超連結 `https://nvd.nist.gov/vuln/detail/<id>`(藍字 + ↗,新分頁)。
- **#3 deny log 缺日期**:事件解析改抓完整 ISO 時戳(log 為 UTC `…Z`),轉 **CST(+8)** 顯示 `MM-DD HH:MM:SS`,與面板時鐘一致;排序改用完整時戳。
- **#4 DENIED 只有 policy:- 看不出擋了什麼**:DENIED 行本無 policy 欄→原本顯示無意義的 `policy:-`。改為解析 OCSF 類別(NET:OPEN)、`[reason:…]`、binary;DENIED 改紅字顯示**被擋目標**(inference.local:443)+ 原因;ALLOWED 顯示 `policy:X` 與 `binary → target`;無 policy 的行一律顯示目標(徹底消除 policy:-)。
- **#1 現成可跑的真掃描器**:新增 `scripts/real-scan.sh` —— flawfinder(C SAST)+ Semgrep(docker,本地規則)+ Trivy(docker,NVD)實掃真實源碼。**結果:flawfinder 與 Semgrep 兩個獨立業界工具都重現 demo 的 CWE-78@diag.c:9、CWE-798@auth.c:4**,證明 demo SAST findings 非編造。Trivy 跑通(firmware manifest 非標準 lockfile→需 SBOM PURL 才直掃,CVE 已可在 NVD 查證且面板已連結)。映像已拉(semgrep 2.13GB / trivy 252MB),flawfinder 已 --user 安裝。
- 驗證:dash-gov2/gov3(日期+DENIED 被擋目標)、dash-cve2(NIST 連結);real-scan.sh 端到端輸出對照表。

## (loop) 2026-06-15 17:0x — deny log 顯示「完整資訊:它嘗試做了什麼」(用戶 #4 延伸)
- 發現 DENIED 行其實含完整欄位(如 `NET:OPEN [MED] DENIED /usr/local/bin/node(N) -> openrouter.ai:443 [policy:- engine:opa] [reason:not in policy 'brave']`)。
- 後端解析補:**嚴重度 sev**、**判定引擎 engine(opa/l7)**、reason 放長到 150 字;沿用既有 cls/binary/target。
- 前端:緊湊列 DENIED 顯示「**發起程式 → 目標**」(如 node → openrouter.ai:443);**點任一列展開完整資訊面板**(動作[人話+OCSF類別] / 發起程式 / 目標 / 判定引擎 / 嚴重度 / 套用政策[DENIED 標『無放行政策→拒絕』] / 原因),`OPEN_EV` Set 跨刷新保留展開狀態,事件委派處理點擊。i18n 中英齊全。
- 加 `?demoexpand` 深連結(切 DENIED 篩選並展開前 2 筆,供 demo/截圖)。node --check 驗證內嵌 JS 語法;截圖 dash-deny-detail.png 確認展開面板。

## (loop) 2026-06-15 19:57 — 換真 NemoClaw/Claw 品牌 icon(用戶指定)
- 原本 favicon + 側欄品牌標是我放的佔位符 `◢`。NemoClaw 本身無獨立圖示(原始碼僅元件圖 PNG);Claw 家族真實品牌圖=OpenClaw control UI 的 🦞 龍蝦 `favicon.svg`(紅漸層+雙螯+青眼)。
- 存官方 SVG → `bridge/brand.svg`;server 載入為 `BRAND_SVG` 常數 + 開 `/brand.svg` 路由(image/svg+xml);favicon `<link type=image/svg+xml href=/brand.svg>` + 側欄 `.mk` 放 `<img src=/brand.svg>`(深色圓角磚襯托)。
- 四大元件卡的 `◆/▣/✦/⬡` 為元件區分小圖示,保留。截圖 dash-brand.png 確認。healthcheck 11/11。

## (loop) 2026-06-15 20:30 — 關閉 agent 心跳(止血 inference.local 429/TLS-EOF 噪音,用戶指定)
- 查清:deny-log 一直刷的 `inference.local:443 TLS handshake eof` = OpenClaw agent **每 30 分心跳**打 Kimi-K2.5、撞 Azure eastus2 **429 限流**、重試風暴中 TLS 被上游 EOF 切→記成 NET:OPEN DENIED。非資安事件。
- 關法:`/sandbox/.openclaw/openclaw.json` 設 `agents.defaults.heartbeat.every="0"`(`resolveHeartbeatIntervalMs` ms≤0→null→agent 略過→disabled)。備份 openclaw.json.bak-heartbeat。
- gateway **hot-reload** 即套用:log `[reload] config change detected (agents.defaults.heartbeat)` + `[heartbeat] disabled`;另跑 `nemoclaw my-assistant recover`(安全,非 onboard)。**healthcheck 11/11 全綠**,12:11 後無新 429 burst。
- 記憶:inference-local-heartbeat-429.md(含重開法 every=30m;⚠ 跨 recover 保留、rebuild 可能還原)。確定性 demo 全程不受影響。

## (loop) 2026-06-15 23:00 — 新增「線上架構」分頁(用戶指定)
- 第 7 個分頁 `#arch`(線上架構/Live Architecture),`vArch(d)` 用即時資料畫垂直拓撲+資料流:
  NemoClaw 管理層(紫帶,快照數)▽ → 人/入口(Telegram●/Email●)→ Hermes(●:8642)→ scoped/32+token → **OpenShell 強制層**(藍帶,● gateway:18080 + 即時 DENIED 數,OPA+L7 必經)→ 兩條 /32 分流 → OpenClaw A(運維,真設備名)| B(資安)→ 受管機隊(台數/ALERT)| 受治理 egress(Jira/mail/推理)。
- 兩大治理面(NemoClaw/OpenShell)用色塊邊框強調;每方塊即時在線狀態(綠/紅點)+ 可點跳對應分頁;中英雙語;鍵盤改 1–7。
- 純前端(沿用既有 agg/rolet/t());node --check 過;截圖 dash-arch.png。healthcheck 不受影響。

## (loop) 2026-06-15 23:22 — 治理分頁加「OpenShell 政策(唯讀)」(用戶指定)
- 設計取捨:dashboard 對 OpenShell 強制層**刻意唯讀**(避免 web 面板變成治理旁路)。新增唯讀政策檢視=看得到、改不了。
- collect 用 pyyaml 解析 `openshell policy get hermes-demo --full` → `d.policy`{version,hash,networks[{name,eps,nbin}],fs_rw};沿用同一次 policy get 也抓 /32 bridge_ips(未加額外開銷)。
- 治理分頁**頂部**(點架構圖 OpenShell 方塊→#gov 第一眼即見)顯示:政策版本/雜湊、EGRESS 白名單 deny-by-default(核心 mail/telegram/bridge/nvidia 完整列含 172.18.0.2/.4:9099 兩條 scoped 橋接,其餘 9 preset 收一行)、可寫路徑、🔒「改設定請用 openshell/nemoclaw CLI(認證+稽核+可證明)」。中英雙語。node --check 過、截圖 dash-policy.png。

## (loop) 2026-06-15 23:29 — 架構分頁精緻化(用戶:沒設計感)
- 加 `--accentbg` 色變數(淺/深)。兩大治理面 band:左側 4px 品牌色條(紫=NemoClaw/藍=OpenShell)+ 對角漸層底 + 面別標籤(管理面/強制面 · MANAGEMENT/ENFORCEMENT PLANE,uppercase tracking)。
- 節點配**彩色圖示磚** `.aico`(紫/藍/綠/琥珀 tint)、狀態點帶 3px 同色光環、hover 上浮。
- 連接線改 `.conn`:漸層細線 + **膠囊標籤 pill** + CSS 箭頭 tip;雙 /32 分流各自顯示 IP+職責 pill(mono)。
- 中英×淺深四種組合截圖驗證(dash-arch.png / dash-arch-dark.png);node --check 過。純前端 CSS/HTML。

## (loop) 2026-06-16 00:06 — 架構分頁參考暗色儀表板再升級(用戶給 Dribbble 參考)
- 無法抓外部 Dribbble,套用該類暗色儀表板語彙:整圖置於**深色舞台面板**(圓角+邊框,深色 linear-gradient 底 + 頂部徑向藍輝光 ::before);兩治理面加**色光暈**(box-shadow 帶品牌色)+ **發光色條**(::before glow);節點狀態點 `box-shadow 0 0 8px` 發光;連接線改**漸層流動動畫** `@keyframes aflow`(往下流);hover 加 accent 光暈;tip 箭頭改 accent 色。深色為主軸、淺色維持乾淨(徑向用 --accentbg)。截圖 dash-arch-dark.png 確認。純前端 CSS。

## (loop) 2026-06-16 07:56 — 抵達停機門檻 08:00,LOOP 結束
- 最終 healthcheck 11/11 全綠(hermes/openclaw/gateway:18080/端點:9099/mail/Jira/dashboard:8899)。心跳仍關(inference.local 近30m=0)。dashboard 200。
- 過夜守護(19:xx→07:56)每 ~50 分 healthcheck,全程全綠,零介入。
- 依「做到 08:00 自動停」指令,停止排程,loop 正常結束。

## 2026-06-16 16:45 — EBG19P 接成真機監控交給 node A(用戶指定)
- 學習真機 192.168.50.1(ASUS ExpertWiFi appGet API),新增唯讀收集器 scripts/ebg19p-monitor-sync.sh:登入→拉 nvram/狀態→正規化成 node A 沙箱 ebg19p-current.conf→/monitor 巡真機。
- /monitor 現:lab-asus-ebg19p-01 status ok、pending [upnp.enabled, wps.enabled];dashboard 機隊頁同步;node alerts=0。
- 憑證衛生:密碼存 ~/.config/nemoclaw/ebg19p.cred(600,非 repo/git),腳本讀檔不回顯,token mktemp 即刪,current.conf 剔除 WAN IP/密碼。
- 真機觀察:DoS off、無遠端 syslog、UPnP/WPS/Samba on、AiProtection off、http LAN admin;遠端管理/SSH/Telnet off(良好)。baseline=快照核准(UPnP/WPS 建議關=待審)。
- memory: ebg19p-fleet-third-device.md 已更新(真機 API/憑證/腳本/現況)。

## 2026-06-16 17:05 — EBG19P (a)排程 + (b)硬合規告警(用戶指定)
- (b) 端點:EBG19P_SECURITY 加 upnp.enabled/wps.enabled(dos_protection/logging.remote.enabled 已在內);baseline 設安全值(DoS=enabled, 遠端syslog=true, UPnP/WPS=false);新增 governed `POST /monitor-scan`(跑巡檢、對安全退化經 policy:jira egress 去重開 Jira;GET /monitor 仍唯讀不開單)。重部署端點到 node A(cp+restart zone A)。
- 結果:EBG19P status=ALERT(4 安全退化),自動開 compliance Jira NETOPS-…,治理足跡 `ALLOWED curl→POST :3690/rest/api/2/issue [policy:jira engine:opa]`;重跑去重不重開;dashboard 機隊頁/KPI/Jira(compliance:1)同步。
- (a) cron:scripts/ebg19p-compliance-cron.sh(同步真機→monitor-scan),crontab */15 已裝、cron 服務在跑、測跑 OK。收集器 baseline 初始化也帶安全值(沙箱重建可重現硬合規基準)。
- 持久:端點源在 repo(boot-stack 部署)、conf 在沙箱持久狀態、cron 在 host;憑證仍只在 600 檔。

## 2026-06-16 17:12 — 依用戶選擇「硬化真機」消除告警
- 透過 ASUS applyapp.cgi 實際改真機 EBG19P:wps_enable=0(WPS關)、fw_dos_x=1(DoS開)、upnp_enable=0(UPnP關);apply 回 {"modify":"1"},重讀 nvram 確認生效。
- 重新同步→node A /monitor:EBG19P 從 ALERT(4)→ALERT(1),已清 upnp/wps/dos 三項。
- 剩 logging.remote.enabled(遠端 syslog)需 syslog 伺服器 IP 才能啟用;待用戶提供 IP(我設上去)或選擇接受(降回非硬合規)。憑證仍只在 600 檔;裝置寫入經 ASUS API、唯讀同步不變。

## 2026-06-17 00:12 — EBG19P P1-A 資產自動盤點(整合設計第一個落地)
- 收集器 scripts/ebg19p-asset-sync.sh(唯讀):拉 get_clientlist()+dhcpLeaseMacList()→正規化(mac/ip/name/type/conn/sdn)→沙箱 ebg19p-assets.json;首見 MAC 以 ebg19p-assets-approved.json 初始化(首見即核准)。
- 端點 GET /assets(node A):current vs approved 比對,標 known/unknown,回 count/approved/unknown/assets。唯讀(不開單,先告警顯示)。
- dashboard:collect 對 node A 多打 /assets;機隊頁 node A 下新增「已連線資產 · EBG19P」卡(綠點=已核准/紅點=未授權,顯示 name/mac/ip/徽章)。i18n 中英。
- 未授權偵測驗證:注入 rogue MAC → /assets unknown=1 ⚠;還原正常。
- cron:資產同步併入 ebg19p-compliance-cron.sh(*/15)。憑證仍只在 600 檔,token 即用即棄。
- 設計藍圖 design/ebg19p-integration-design.md 的 P1-A 完成;P1-B(流量基線)/P1-C(syslog 閉環)/P2 待後續。

## 2026-06-17 00:24 — EBG19P P1-C syslog 閉環(唯讀,整合設計第二個落地)
- 發現可唯讀拉日誌:appGet hook=nvram_dump("syslog.log","")→免設備寫入、免跨網段 listener(保持唯讀原則)。
- 收集器 scripts/ebg19p-syslog-sync.sh:拉 syslog→python 解析每行(t/tag/msg)→分類 OCSF category(wifi/firewall/auth/upnp/dhcp/vpn/system/service)+ severity(high/warn/info)→node B(資安)沙箱 ebg19p-syslog.jsonl(最近 150 行)。
- 端點 GET /device-log(node B):讀 jsonl→統計 by_category/by_severity + 安全關注事件 + 最近事件。唯讀。
- dashboard:collect 對 node B 打 /device-log;資安/CVE 分頁底部新增「EBG19P 設備日誌·OCSF 分類」卡(分類橫條 + 安全關注事件流;total/安全關注數)。i18n 中英。
- 實測:150 行,分類 service51/system40/auth34/upnp15/wifi4/firewall3/dhcp3,severity info142/warn8;security_events 8(rfkill/upnp timeout 等,lab 環境無真攻擊)。
- cron 併入(設定+資產+syslog+巡檢);monitor 全機隊仍 ok、healthcheck 11/11。
- 敘事:把「無遠端 syslog 合規缺口」轉成「設備日誌集中+node B 資安 OCSF 分類+統一治理視圖」整合閉環(設計 §5 亮點1 落地)。
- 設計藍圖 P1-A✅ P1-C✅;剩 P1-B(流量基線)、P2(PoE自癒/VPN審計/Hermes 自然語維運)。

## 2026-06-17 00:29 — EBG19P P1-B 流量基線+異常(P1 收官,整合設計第三個落地)
- 收集器 scripts/ebg19p-traffic-sync.sh(唯讀):單次取兩樣本(間隔3s)算瞬時 WAN Mbps(netdev INTERNET rx+tx hex 差/時間差*8),append node A 沙箱 ebg19p-traffic.jsonl(ring 60)。counter 歸零→0。
- 端點 GET /traffic(node A):讀時序→latest/avg/peak + 突增異常(latest > max(avg*3, avg+2σ) 且 >1Mbps)。
- dashboard:collect 對 node A 打 /traffic;機隊頁 node A 下「WAN 流量·EBG19P」卡(spark 折線 + 目前/基線/峰值 Mbps;異常轉紅+「流量突增異常」)。i18n 中英。
- 異常驗證:注入 50Mbps→anomaly True;還原正常。cron 併入(現 5 步:設定+資產+syslog+流量+合規巡檢)。monitor alerts 0、healthcheck 11/11。
- **P1 全收官**:A 資產盤點✅ B(C) syslog✅ B 流量✅。設計藍圖剩 P2(PoE自癒/VPN審計/Hermes自然語維運)。

## 2026-06-17 00:40 — EBG19P 設備詳情 slide-over 抽屜(用戶:點龍蝦管理的 EBG19P 看細節)
- 點機隊頁 EBG19P 設備列(帶 🦞 NemoClaw 受管 mgd 標記 + 「點看設備細節 →」hint + clickable hover)→ 右側 slide-over 抽屜(遮罩+blur),標題龍蝦品牌 icon「EBG19P · NemoClaw 受管 · 韌體」。
- 抽屜集中全部偵測細節(彙整 A monitor/assets/traffic + B devlog + 身分):設備身分(型號/韌體/MAC/WAN/SSID/遠端管理)、安全合規基準(status+regressions+pending)、已連線資產(清單+未授權)、WAN 流量(spark+基線+異常)、設備日誌(OCSF 分類+安全事件)。
- collect 加 read_conf_in + d.ebg19p_info(讀 ebg19p-current.conf 身分欄位)。CSS .ovl/.drw/.dsec/.mgd;JS ebgDrawerHTML/openDrawer/closeDrawer;render 開啟時即時刷新;Esc/遮罩/✕ 關閉;?drawer=ebg 深連結(demo)。i18n 中英。node --check 過。
- 清掉流量 ring 的測試假值(50Mbps);流量基線 latest0.82/avg0.66/peak0.9 anomaly false;healthcheck 11/11。

## 2026-06-17 01:00 — EBG19P 設備日誌收容權改歸 node A(運維,用戶:導到 A 快速管理)
- 釐清:設備主動外送 syslog 到沙箱 A 不可行(沙箱網路隔離+跨網段+ingress 治理);改用 A 主動唯讀拉(nvram_dump)達成等效「日誌匯集到 A」且更安全(設備零設定/零外送暴露)。
- ebg19p-syslog-sync.sh 改寫 node A 沙箱(CT2→CTO);dashboard collect 的 /device-log 從 B(cve cap)移到 A(fix cap);設備詳情抽屜 devlog 改從 nA 撈;vCve 移除設備日誌卡;vFleet node A 新增「EBG19P 設備日誌·OCSF」卡(可點開抽屜)。清掉 node B 殘留 jsonl。
- 結果:node A 成為 EBG19P 單一管理中樞(機隊頁 A 下:設備列🦞受管 + 資產卡 + 流量卡 + 設備日誌卡;點任一→設備詳情抽屜)。資安頁回歸純 CVE/SBOM/SAST。/device-log 150 行、安全關注 8;JS check 過。
- 下一步候選 P2:設備詳情抽屜加運維快速處置動作(重啟服務/踢未授權設備/PoE reset),受 OpenShell 治理+Hermes 核准。

## 2026-06-17 01:xx — 換網路事件 + WSL mirrored(根因釐清)
- 用戶換網路後 dashboard/收集器連不到 EBG19P。診斷:設備**完全正常**(Windows curl 192.168.50.1 → HTTP 200、ARP 兩介面 a0:ad:9f:7a:a0:55 LAN + :30 WAN 在線);**非設備故障**。
- 兩獨立原因:(1) WSL2 NAT 模式換網路後連不到實體 LAN(WSL 連 Windows 自身 10.88.23.85 都不通);(2) 我密集登入(收集器登入不登出)致 ASUS httpd session 表暫滿(GET 200 但 POST login 被拒)。
- 處置:暫停 EBG19P cron;executor 加 Logout.asp + RESULT 標記;dashboard do_device_action ok 判斷改用 RESULT=ok。
- **用戶選 WSL mirrored**:寫 /mnt/c/Users/Asus_User/.wslconfig(networkingMode=mirrored)。待用戶在 Windows 端 `wsl --shutdown` 重啟。
- **重啟後待辦**:① ping 192.168.50.1 確認 WSL 可達 ② bash scripts/boot-stack.sh 重拉 stack ③ 給 4 收集器補 logout(根治 session) ④ 設備 session 釋放後測收集器+P2 ⑤ 恢復 cron(crontab */15 ebg19p-compliance-cron.sh) ⑥ 完成 task #23。
