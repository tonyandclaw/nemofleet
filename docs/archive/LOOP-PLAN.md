# LOOP-PLAN.md — 自主疊代任務定義(2026-06-12 ~ 06-15 08:00 CST)

> 這是給 `/loop` 用的**單一真相來源**。每輪:讀本檔 → 挑下一個未完成工作項 → 做 → 驗證 → 勾選 + 記 PROGRESS → 判斷停止條件與下次節奏。主軸=**分階段全包**(前段擴張+沉澱證據,後段凍結轉守護收尾)。

## 每輪 SOP(照做)
1. `export PATH="/home/tony/.nvm/versions/node/v22.22.3/bin:$PATH"`;`cd ~/nemoclaw-combine`。
2. 讀「工作隊列」,挑**最上面一個未勾**的項(同 Phase 由上而下;Phase 1 全清才進 Phase 2)。
3. 做該項——**優先零 Azure**;改 code 前若屬「主線」(endpoint/boot-stack)先打當日快照。
4. 驗證:`bash scripts/healthcheck.sh` 必須全綠 **且** 該項自己的「驗收」通過。新腳本要 `bash -n`、py 要 `py_compile`。
5. 收尾:本檔把該項 `[ ]`→`[x]` + 一行結果。每**完成一個 Phase**(非每項)在 `PROGRESS.md` 記一段摘要,避免 PROGRESS 爆量。
6. 例外處理:healthcheck 紅→先嘗試修;**連兩輪紅**→還原 `combine-pre-loop-0612`、停 loop、把原因寫進 PROGRESS。
7. 時間閘:若 `date` ≥ **2026-06-15 08:00 CST**→停(不再排下次)。
8. 節奏(ScheduleWakeup):工作密集(Phase 1/3 還有未完成項)→約 **600s** 接續快推;隊列已清空→轉守護 **1800s+**。深夜照跑(系統無人值守)。

## 護欄(別把 DEMO-READY 的系統改壞)
- **還原點**:pre-loop = `combine-pre-loop-0612`;每進一個新日子打一個 `combine-loop-<MMDD>`。
- **不碰 `*.pptx` 二進位**(Linux 無 JhengHei 字型)——待改項只寫進 `PPTX-TODO.md`。
- **不大改主線** `bridge/openclaw-fix-endpoint.py` / `scripts/boot-stack.sh`(已穩、drift 44s e2e),除非修 bug;改前快照、改後 `bridge-regress.sh drift` 驗一次。
- **Azure 低頻**:Phase 1/3 幾乎零成本;主鏈 `bridge-regress.sh` 每天 ≤2 次;429 就跳過該輪 Azure、改做零成本項。
- **繁中**:Kimi 長結構化文會倒簡體(模型偏置,非設定可解)——demo 文案以 Telegram 短文為主;`design/*.md`、`EVIDENCE.md` 等由 loop 自己(Claude)寫繁中即可。
- 每項完成才勾;**寧可少做一項,不要留半成品**。

## 工作隊列

### Phase 1 — 擴張 + 沉澱(前 ~40h,低/零 Azure)
- [x] **P1-1 `EVIDENCE.md`(claim→證據矩陣)** → 完成 2026-06-12 17:50:四區(A 報修主線 / B 監控·CVE·原始碼 / C 資安正常vs攻擊對照 / D 技術·生命週期),每條宣稱對應指令+鐵證+成本;抽驗 B4(SBOM4/SAST2/設計違反2-5)、D3(/32)、healthcheck(10綠0紅)對得上。
- [x] **P1-2 `policy prove` 形式化證明** → 完成 2026-06-12 18:10:`openshell policy prove` 存在且能跑(需 `--policy`+`--credentials`,policy get --full 要砍 header 取 `---` 後)。做了 `scripts/policy-prove-demo.sh`(對兩台 active policy 靜態窮舉外洩面)+ EVIDENCE D5 + README。誠實 framing:gap(Hermes 59 路徑)全落在套件/跨agent/本地mail-jira 白名單 L4 端點,對照非白名單動態 DENIED。註:`--accepted-risks` 可做 FAIL→PASS 對照但需逐 endpoint schema,列為可選後續。
- [x] **P1-3 第二台機隊資產做成真** → 完成 2026-06-12 18:25:endpoint 加 OpenWrt GL-AXT1800 真實 baseline(UCI)+ `MANAGED` 清單(每台自己的安全鍵)+ `_conf_kv` 正則支援大寫 UCI 鍵 + `seed_monitor_assets`;`/monitor` 現 `managed_snapshots:2`(rt-ax89x + openwrt 各比對核准基準)。/health 加 `managed` marker、boot-stack gating 認它。驗證:healthcheck 10綠、逐台告警正確(植 rt-ax89x drift→只它 ALERT、openwrt ok)、bridge-regress drift PASS(fix 主鏈未壞)。當日快照 combine-loop-0612(hermes v10/openclaw v4)。可選後續:monitor-alert 加 openwrt 漂移注入(真實素材已在 enterprise-deck)。
- [x] **P1-4 治理指標聚合 `scripts/govboard.sh`** → 完成 2026-06-12 18:40:一頁聚合 OCSF 兩沙箱 ALLOWED by policy(6 類)+ DENIED(~2.5k)、Jira by kind(7 張)、CVE 分級、機隊 2 台監控、MTTR 44s。bash -n OK、實跑數字正確、零 Azure。EVIDENCE D6 + README。
- [x] **P1-5 `design/business-case.md` 草稿** → 完成 2026-06-12 18:55:8 段(市場客戶/痛點價值/TAM-SAM-SOM/定價三模式+good-better-best/競品對照表/ROI 範例試算 200 台省~65%+MTTR 44s vs 7天/GTM 三階段/誠實風險假設)。數字標量級假設待 Tony 校準。商業 20% 最弱項補上。零 Azure。

### Phase 2 — 可靠性守護(中段)
- [x] **P2-1 回歸守護 `scripts/loop-regress.sh` + `eval/LOOP-LEDGER.md`** → 完成 2026-06-12 19:06:6 項零成本檢查(containers/health/monitor/cve/source/prove)逐項 PASS/FAIL + 已知坑,append ledger 一行/輪。實跑 fails=0。
- [x] **P2-2 已知坑監測**(併進 loop-regress)→ 完成:telegram getUpdates 近 6 分存活計數(驗證撐過 2h)、近 30 分 Azure 429 計數。趨勢進 ledger。

### Phase 3 — 凍結 + 收斂(最後 ~24h)
- [x] **P3-1 FEATURE-FREEZE** → 2026-06-13 09:15(使用者要求提早進 Phase 3)。🔒 **功能凍結**:之後只做 P3-3/4 + 守護,不再加新功能(EBG19P 第三台機隊是凍結前最後一個新功能)。
- [x] **P3-2 `design/qa-prep.md`** → 完成 2026-06-13 09:15:16 題(A 差異化/實用 5、B 資安 4 含 policy-prove CRITICAL 誠實題、C 技術 3、D 商業 2、E 落地規模 2)+ 一句話收尾;每題精簡答 + 佐證指令(對得到 EVIDENCE)。
- [x] **P3-3 `PPTX-TODO.md`** → 完成 2026-06-13 09:28:A 必改(頁碼 stale)+ B 建議補講點(slide10 機隊3台含EBG19P / slide11 policy prove / slide12 business-case 數字 / 可選 govboard 一頁)+ C 不需改(指向 EVIDENCE)。不碰二進位。
- [x] **P3-4 最終驗收 + demo-ready 快照** → 完成 2026-06-13 09:30:bridge-regress drift PASS + jira-reset + healthcheck 10綠 + /monitor 3台 ok;打 `combine-demo-ready` 快照(hermes v12/openclaw v6,最終還原點)。終結報告已 append PROGRESS。

### Phase 4 — PPTX 架構對齊驗證(2026-06-13 使用者新主軸;**零風險:純驗證+文件,不碰 deploy/onboard/gateway**)
- [x] **P4-1 建 `design/pptx-architecture-map.md`** → 完成 2026-06-13 10:16:6 區(四元件/連線隔離/治理三層/代理流水線/監控機隊/未來願景)逐項 PPTX→實機對應+驗證指令+狀態。結論:slide 1–12 核心架構 ✓ 逐項對應、slide 18 分佈式願景誠實標 roadmap、機隊=1 OpenClaw 管 6 設備邏輯機隊。
- [x] **P4-2 缺口補齊** → 完成 2026-06-13 10:36:檢視對應表 ⚠/✗ 項,確認**無硬缺口要補** —— ⚠(邏輯機隊/NVIDIA 需 key)與 ✗(多機隊/中央大腦)都是誠實的現實/roadmap 標註,符合 PPTX「現一台 sample、可橫向擴」與 slide18 未來願景;不強做(且 06-13 事故證明本機強推多實例會破壞 stack)。
- [x] **P4-3 逐項實跑驗證** → 完成 2026-06-13 10:36:抽驗代表項全對(四元件2/通道 /32/端點 markers+managed=3/治理 5 類 policy);記入 pptx-architecture-map.md 抽驗紀錄。
> ⛔ Phase 4 鐵律(記取 06-13 事故):**絕不跑 `nemoclaw onboard`、不 deploy 第二沙箱、不動 gateway port**。要演「多台機隊」用既有 FLEET 邏輯(一台 OpenClaw 管 6 設備),不真起多個 OpenClaw 實例。

### Phase 5 — Dashboard UI/UX 卓越化(2026-06-15 使用者新主軸,做到 08:00)
目標:`bridge/agent-dashboard.py` 達到**商業客戶等級設計感 + 順 UX**。每輪 SOP:改 HTML → 重啟(`PID=$(ss -tlnp|grep :8899|grep -oE pid=[0-9]+|cut -d= -f2); kill $PID` **勿 pkill -f agent-dashboard.py 會殺 shell**)→ Windows Chrome 截圖(`/mnt/c/.../chrome.exe --headless=new --screenshot`)→ Read 自評 rubric → 記 PROGRESS → 排下輪(~900s)。每 3 輪跑一次 `loop-regress`(dashboard 靠 stack 資料,確保沒掛)。**只改 dashboard 前端,不動 stack/gateway/onboard。**
**自評 rubric(每輪逐項;答「能過關嗎」)**:① 視覺層級/一致性 ② 字體+tabular 數字 ③ 色彩對比 AA+雙主題 ④ 間距 8px 節奏 ⑤ 資料視覺化正確清楚 ⑥ 動態/微互動順、無閃爍 ⑦ 空/載入/錯誤狀態 ⑧ a11y(focus/鍵盤) ⑨ RWD ⑩ 商業質感(像企業 SaaS 非 AI demo)。
**迭代佇列**:
- [x] **I1 設計系統+無閃爍渲染+a11y+favicon** → 2026-06-15 01:42:token 精煉(tabular-nums/間距/AA 色卡)、分區 memo(內容沒變不重繪)、focus-visible、fade。自評:①②③④⑥(無閃爍)⑩ 過;**⑤ 不過 → donut/sparkline 用 `var()` 於 SVG stroke 不生效(圖表空白),I2 修**。
- [x] **I2 資料視覺化修正** → 2026-06-15 09:49:donut 改 **CSS conic-gradient**(SVG 多段 stroke 在 headless 不吃,conic 硬編色最穩,紅/琥珀/灰三段+中心 affected);sparkline 加末點圓點+area;事件流 target regex 清理(顯示 host:port 不再是 [policy:]);主題切換即時重新上色;移除每秒淡入→沉穩即時更新。自評 ⑤⑥ 過。(count-up/bar 動畫**故意不做**:denied/allowed 每 tick 變動,動畫會每 5s 重播=吵,商業 UX 求沉穩)。
- [x] **I3 分頁 IA 重構(用戶指定)** → 2026-06-15 10:08:單頁長捲→**側欄 menu + hash 路由分頁**(總覽/機隊監控/資安CVE/治理事件/升級守護/設定 6 tab)。①KPI 可點(`<a href="#tab">`+hover 箭頭)跳對應分頁:DENIED→治理事件、CVE affected→資安、設備/節點→機隊、MTTR/快照→升級守護。②設定收進**動態設定 tab**(主題/密度/自動刷新/節點篩選/手動重整 + 關於/鍵盤快捷)。③側欄 menu 列全 tab + 告警徽章(CVE 2/DENIED 64)。新增:密度切換(舒適/緊湊)、事件 ALLOWED/DENIED 篩選、affected 弱點表(CVE/資產/元件/版本/嚴重度)、SAST 命中表(CWE/檔案/行)、鍵盤 1–6/r/d、側欄即時狀態。修:DENIED 保證進事件流(否則被頻繁 ALLOWED 擠掉→篩選空白)、target regex 加一般網域(抓 inference.local:443 等 DENIED 外連)。4 分頁截圖驗證(dash-overview/cve/gov/settings.png)。原 slide-over→改用分頁內聯詳情(機隊分頁直接展開 regressions/pending),更貼合「menu 看每個 tab」需求。
- [x] **I4 監控新功能** → 2026-06-15 10:18:**連線健康徽章**(側欄底即時連線:資料新鮮=綠、逾 2×刷新=黃「資料延遲」、逾 4×=紅「連線中斷 Ns」,並 `body.stale` 淡化+降飽和畫面→誠實呈現「即時」失效);**kiosk 全螢幕 demo 模式**(topbar ⛶ 鈕 / `f` 鍵 requestFullscreen,大螢幕展示用);**告警視覺強化**(`.bn.bad` alertpulse 呼吸光暈,僅真告警時)。匯出 JSON/列印版→延到 I6 選做(分頁後優先級降);節點 A 空間平衡→分頁架構後已不成問題。截圖 dash-i4.png 確認鈕/徽章/門檻日期。
- [x] **I4b 國際化 + 設定垂直化(用戶指定)** → 2026-06-15 14:46:全 UI 抽成 **i18n 字典**(`I18N{zh,en}` + `t(k)`),加**語言切換 English / 繁體中文**(設定→外觀內,存 `nclaw-lang`,`applyChrome()` 即時重繪導覽/標題/按鈕);設定頁三 topic(外觀/資料/關於)**並排三欄→垂直堆疊**(max-width 660,iOS 設定風好讀)。細節:`roleT()` 譯節點職責、MTTR「44 秒↔44s」、時間 `toLocaleTimeString` 依語系、動作 toast 依語系、`?lang=`/`?theme=` 可分享連結、`html lang` 屬性切換。雙語×淺色截圖驗證(dash-set-zh/set-en/ov-en2)。Python 僅服務端不變。
- [x] **I5 UX 過關自評** → 2026-06-15 15:17:逐項 ①視覺層級 ②字體/tabular ③對比+雙主題 ④間距 ⑤資料視覺化 ⑥微互動/無閃爍 ⑦空/載入/錯誤 ⑧a11y ⑨RWD ⑩商業質感 = **10/10 PASS**。本輪補洞:⑦ 加**載入骨架**(shimmer,冷啟動 collect 慢時不再空白)+ ⑧ icon 按鈕 `aria-label`、導覽 `aria-current`、`document.title` 隨分頁。**誠實結論:可交付商業客戶**(內部維運監控盤/demo 級)。保留非阻斷項:(a) 8px 節奏非數學嚴格;(b) 極窄手機未逐一微調;(c) 後端 500 的前端降級可再硬化(目前處理 fetch 失敗+stale)。
- [x] **品質 plateau → 轉守護**(2026-06-15 15:17):UI 已達商業級且雙語/直式/kiosk 齊備,可做的高價值項已清。剩 I6 選做(匯出 JSON/列印版)非必要。**改長間隔(1800s)守護**:每輪 healthcheck + 保活,到 06-16 08:00 自動停;有壞掉/使用者新需求才介入。

## 停止條件
- `now ≥ 2026-06-16 08:00 CST`(主;原 06-15 08:00 於 06-15 10:18 已過,使用者重下 loop 指令→順延至下一個早上 08:00,已同步 dashboard stop_gate),或
- healthcheck **連兩輪紅**→還原 pre-loop 快照、停、留報告,或
- 全工作項完成→轉**純守護**(每輪只 healthcheck + 刷 `EVIDENCE.md`/ledger,間隔 1800s+),直到時間閘。

## 狀態(loop 每輪在此覆寫:上輪做了什麼、下輪要做什麼)
- 2026-06-16 07:56 — **🏁 LOOP 結束(抵達 08:00 停機門檻)**。最終 healthcheck 11/11 全綠、心跳關閉、dashboard 200。過夜守護全程零介入。Dashboard 最終功能:7 分頁 IA(總覽/線上架構/機隊/CVE/治理/升級守護/設定)、可點 KPI、中英雙語、直式版面、密度、kiosk、連線健康徽章、CVE→NVD、deny-log 完整展開、OpenShell 唯讀政策、暗色儀表板風線上架構、真品牌🦞icon。stack 全綠交付。
- 2026-06-15 23:00 — (用戶指定多項,晚間)真品牌🦞 icon、deny-log 完整展開面板、查清並**關閉 agent 心跳**(inference.local 429 噪音止血,openclaw.json heartbeat.every=0)、新增**「線上架構」分頁**(即時拓撲+NemoClaw/OpenShell 兩大治理面色塊+可點跳分頁+雙語,鍵盤 1–7)。守護 healthcheck 全程全綠。**回守護到 06-16 08:00**。
- 2026-06-15 16:1x — (用戶 4 項)**CVE→NIST 連結、deny log 補日期(UTC→CST)、DENIED 改顯示被擋目標+原因(消除 policy:-)、新增 `scripts/real-scan.sh`**(flawfinder+Semgrep+Trivy 現成工具實掃,兩個 SAST 工具獨立重現 demo 的 CWE-78@diag.c:9/CWE-798@auth.c:4)。截圖+端到端驗證。回守護。
- 2026-06-15 15:17 — **I5✅ UX 自評 10/10 PASS,結論=可交付商業客戶**(補載入骨架+a11y aria)。healthcheck 全綠。**品質 plateau → 轉守護模式**:長間隔 1800s,每輪 healthcheck + 保活到 06-16 08:00 自停;Dashboard 功能完備(分頁/可點KPI/雙語/直式/密度/kiosk/連線健康),非必要不再加。**下一步=守護**(壞掉或使用者新需求才介入)。
- 2026-06-15 14:52 — (用戶指定)**機隊監控 + 資安CVE 也改直式**(單欄上下堆疊,延續設定頁;max-width 840/900)。截圖驗證。總覽/治理/守護維持橫向。**下一步仍=I5 UX 過關自評**。
- 2026-06-15 14:46 — Phase 5 **I4b✅(用戶指定)**:i18n 雙語(English/繁中,設定內切換+持久+`?lang=`)、設定頁改**垂直堆疊**。全 UI 經 `t()` 字典,`applyChrome()` 即時切換;MTTR/時間/職責/toast 皆隨語系。雙語截圖驗證。**下一步=I5 UX 過關自評**(對 10 項 rubric 打分,答「能否交付商業客戶」),之後品質 plateau→轉長間隔守護到 06-16 08:00。
- 2026-06-15 10:18 — Phase 5 **I4✅**(連線健康徽章+stale 淡化、kiosk 全螢幕 ⛶/f、告警 alertpulse)。**停機門檻 06-15 08:00 已過→順延 06-16 08:00 CST**(使用者重下 loop)。**下一步=I5 UX 過關自評**(對 10 項 rubric 逐項打分,誠實答使用者「UIUX 能過關嗎」,補不足)。下一輪後品質應 plateau→轉守護。
- 2026-06-15 10:08 — Phase 5:I1✅ I2✅ **I3✅**(用戶指定 IA 重構=側欄 menu + 6 分頁 + 可點 KPI 跳轉 + 動態設定 tab + 密度/事件篩選/明細表/鍵盤;DENIED 進得了事件流)。4 分頁截圖驗證商業質感。**下一步=I4**(連線 stale 徽章、kiosk 全螢幕 demo 模式、匯出/列印、深色主題在新分頁版的截圖驗證)。每 3 輪 loop-regress(I1/I2/I3 已 3 輪→**本輪後跑一次 loop-regress**)。
- 2026-06-15 09:49 — Phase 5:I1 ✅、**I2 ✅**(donut 改 conic-gradient 修好空白圖、sparkline+末點、事件 target 清理、主題即時重色、沉穩更新)。截圖確認商業質感到位。每輪:改→重啟(port PID kill,勿 pkill -f)→Chrome 截圖→自評→排下輪;每 3 輪 loop-regress。
- 2026-06-15 01:42 — (互動)**新主軸=Phase 5 Dashboard UI/UX 卓越化(做到 08:00)**。I1 ✅(設計系統+無閃爍 memo 渲染+a11y+favicon)。
- 2026-06-14 01:55 — (互動)分工**改職責導向**(使用者要 A 運維/B 資安,非設備線):endpoint ZONE_CAPS/ZONE_MONITOR、cve 全機隊(B)、source(B)、A 運維 monitor+fix;loop-regress 適應(source 對 B)、SKILL 職責路由。守護 fails=0。**待同步**:EVIDENCE/pptx-map 文字(下輪)。
- 2026-06-14 01:25 — (互動)✅ **兩 OpenClaw 節點分工完整落地完成**(T7–T12,設備分區版,後改職責):endpoint BRIDGE_ZONE 分區、兩台 zone 端點、policy 兩節點各/32、Hermes SKILL 按設備路由、boot-stack 持久化(deploy_oc_endpoint)、loop-regress 兩節點合計。前台 Hermes→依設備路由→節點A(無線)或節點B(基礎設施)。守護 fails=0。待補(非阻塞):demo_telegram/README 路由說明。回純守護。
- 2026-06-14 01:30 — (互動)**兩 OpenClaw 節點分區 part 1/2**:endpoint BRIDGE_ZONE 過濾、節點A(my-assistant)=無線線、節點B(openclaw-2 172.18.0.4)=基礎設施線;monitor/cve 分區驗證正確、loop-regress 改兩節點合計 fails=0。**下一步=剩餘 task #10(policy 放行 →172.18.0.4/32)#11(Hermes 路由+boot-stack 裝 openclaw-2 端點)#12(文件)**。⚠ T11 前勿重開機(boot-stack 還沒裝 openclaw-2 zone-B 端點)。
- 2026-06-13 18:21 — (互動)**第二台 OpenClaw `openclaw-2` 建成並納管**:用 `snapshot restore --to`(非 onboard,安全)複製;dashboardPort 改 18790 避衝突;boot-stack §1b + loop-regress openclaw2 項納管;兩台共用 18080 gateway、UI 18789/18790。守護 fails=0。回純守護。
- 2026-06-13 10:36 — ✅ **Phase 4 完成**(P4-1~3:架構對應表 + 無硬缺口 + 抽驗全對)。PPTX slide 1–12 核心架構實機逐項對應、slide 18 願景誠實 roadmap。**整個 loop 工作隊列(Phase 1-4)全清空 → 回純守護**(每輪 loop-regress、1800s、每日一次 bridge-regress)直到 06-15 08:00。
- 2026-06-13 10:16 — P4-1 ✅(`design/pptx-architecture-map.md`)。下一步=P4-2→P4-3。
- 2026-06-13 10:15 — (事故+新主軸)deploy 第二 OpenClaw 實驗誤觸 `onboard --non-interactive`,破壞 gateway(18080→8080)+ 停 my-assistant/hermes 容器;以「registration 切回 18080 + boot-stack」修復全綠(見 PROGRESS + [[onboard-noninteractive-gateway-hazard]])。使用者改 loop 主軸=**Phase 4 PPTX 架構對齊驗證**(零風險)。**下一步=P4-1** 建 `design/pptx-architecture-map.md`。Phase 4 鐵律:不碰 onboard/deploy/gateway。
- 2026-06-13 09:30 — ✅ **Phase 3 完成 → 整個工作隊列(Phase 1+2+3)全清空**。P3-3 PPTX-TODO ✅、P3-4 最終驗收+`combine-demo-ready` 快照 ✅(hermes v12/openclaw v6)。**loop 轉純守護到 2026-06-15 08:00 自動停**:每輪 `loop-regress`(1800s)、每日一次 `bridge-regress drift`、連兩輪紅→還原 `combine-pre-loop-0612`。最終還原點=`combine-demo-ready`。
- 2026-06-13 09:15 — (使用者要求)**提早進 Phase 3**(凍結收斂)。P3-1 freeze 🔒 ✅、P3-2 `design/qa-prep.md` ✅(16 題評審 Q&A+佐證)。
- 2026-06-13 08:30 — (使用者插入)**ASUS EBG19P 接入機隊第三台**:endpoint FLEET/MANAGED/seed +EBG19P、`/monitor` 現 **managed=3**、`/cve` fleet=6;**loop-regress monitor 檢查已對齊 3**;主線改動快照 `combine-loop-0613`;bridge-regress drift PASS。回純守護。
- 2026-06-12 19:06 — 輪6:P2-1+P2-2 ✅。**Phase 1+2 全完成**。現轉 **🛡 純守護模式**直到 2026-06-14 08:00(再進 Phase 3)。
  - **守護輪 SOP**:每輪只跑 `bash scripts/loop-regress.sh`(零成本)→ 看 fails。fails=0 → 排下輪 **1800s(30 分,使用者 06-12 指定)**;**連兩輪 fails>0** → 還原 `combine-pre-loop-0612` + 停 + 報告。
  - **每日一次** Azure 主鏈驗證:看 `eval/LOOP-LEDGER.md`,當天若還沒跑過就加跑 `bash scripts/bridge-regress.sh drift`(1 turn)並在 ledger 行尾註 `+bridge=PASS`。今天(06-12)已跑多次,**明天(06-13)起每天一次**。
  - **時間閘**:每輪 `date`,≥2026-06-14 08:00 → 進 Phase 3(P3-1~4);≥2026-06-15 08:00 → 停 loop。
  - 當日快照=`combine-loop-0612`、pre-loop=`combine-pre-loop-0612`。
