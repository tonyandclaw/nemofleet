# nemofleet — Demo 走查腳本(每個 function 怎麼講)

一份給 demo/簡報用的走查腳本:先開「展示模式」把每個面板填滿資料,照著這頁一頁一頁講,講完關掉就回到真實資料。

---

## 0. 開始 / 結束(重要)

**開啟**:左側 `Admin` →「展示模式 / Demo mode」→ **Turn demo ON**。
- 上方會出現橘色 **DEMO MODE** 橫幅(每一頁都在),提醒「這是示範資料」。
- 這時裝置上線、有流量、掃描/guardrail/回滾都有內容,可以逐一講解。

**結束**:橫幅右邊 **Exit demo**(或 Admin →「Turn demo OFF」)。
- **立即**還原真實資料,不留任何殘留。

**安全保證(可以對評審講)**:
- 展示模式下**所有動作都是模擬**(Fix / Scan / Harden / Freeze…)—— **完全不觸及真實裝置、不寫稽核、不開 Jira**。
- 旗標只在記憶體、**預設關**;重開機自動回真實模式;開著超過 6 小時會自動關(保險)。
- 關掉那一刻會清掉快取,下一次輪詢就是真資料 —— **不可能把假資料當真資料**。

---

## 1. Overview(總覽)— 「一眼看懂治理現況」
- **看**:四個 KPI(治理放行 8,412 / 擋下 3 / 告警 2 / 升級 1)、上方**注意力條**(2 攻擊面暴露、1 未授權裝置、guardrail fail-open)、治理事件量趨勢圖。
- **講**:「所有異常自動聚合成一條**可點的治理告警**,點任一個直接跳到該頁。這是維運人員的第一眼。」

## 2. Architecture(架構)— 「四節點 + 唯一通道」
- **看**:team-lead + worker-a/b/c 的 hub-and-spoke 圖、指向本地 NIM。
- **講**:「workers 彼此**網路隔離**,只有 team-lead 經**唯一的 scoped 通道**委派。這是治理的第一道邊界。NIM 是本地推論,egress 受政策管。」

## 3. Flow(工作流)— 「跨節點的每一步都留痕」
- **看**:remediate(委派)、nuclei scan → Jira、config rollback → 讀回 ✓ 的事件流。
- **講**:「每個跨節點動作都記在這條 flow,human/auto 標得清清楚楚。」

## 4. Fleet(機隊)— 「節點 + 真實裝置 + 連線裝置」
- **看**:4 節點健康、EBG19P **上線**(CPU/記憶體/溫度 + sparkline)、**連線裝置**清單(nas-01、tony-mbp = 已知;IOT 那台 = **未授權**)。
- **講**:「這是唯一一台真實管理的 ASUS EBG19P。未授權 MAC 會被標出來 —— 這是偵測面的一部分。」

## 5. Security(資安)— 「攻擊面 + 一鍵治理修復」★ 主秀
- **看**:
  - **EBG19P 安全分數**(drift+CVE+nuclei+cert 融合)
  - **攻擊面面板**:WPS/WAN 遠端管理 = ⚠ exposed(旁邊有 **Fix** 鍵)、DoS/Telnet = ✓ hardened
  - **Active scan (nuclei)**:2 hits(CVE-2024-3080 critical → 已開 Jira),下面可設 targets/tags
  - **Cert / 弱加密**、**SAST**(Semgrep + Nemotron,CWE-798 confirmed)、**SBOM**、**CVE**
- **講**:「暴露的項目旁邊就有一顆 **Fix**。按下去走**治理閉環**:guardrail → 決策邊界閘 → 套用 → **讀回驗證**。」(可按 Fix 演示 —— 展示模式下是模擬,會回「已模擬」。)

## 6. Guardrail(守門)— 「攔得住 prompt-injection」
- **看**:攔截紀錄:擋下 prompt-injection(標 **ATLAS AML.T0051**)、destructive(factory reset),放行合法請求,一筆 **fail-open**;紅隊評測 catch rate 100%。
- **講**:「請求進來先過守門。prompt-injection、毀滅性指令**動手前就擋下**。NIM 掛掉時 fail-open 也會**記錄**,不是靜默放過。」

## 7. Decision boundary(決策邊界)— 「Agent 能做/禁止做什麼,寫在牆上」★
- **看**:auto(可逆)/ human(需 token）/ forbidden(閘門拒絕)三組動作目錄。
- **講**:「這是與客戶簽的**責任邊界合約**。採購資安不用讀程式,一頁看完。而且 **CI 強制**程式碼與這份目錄 1:1 綁定 —— 多一格少一格 CI 就紅。」

## 8. Governance(治理)— 「OPA / L7 事件」
- **看**:治理事件量、ALLOWED/DENIED 紀錄(egress 決策)、政策唯讀卡。
- **講**:「每一筆對外連線都經 OPA L7 判定,ALLOWED/DENIED 全留證。」

## 9. Change ctrl(變更治理)— 「回滾 + 讀回證據」
- **看**:兩筆 rollback —— 一筆讀回**全數 match ✓**、一筆**讀回不符**(wps_enable want 0 got 1)。
- **講**:「還原後**逐鍵讀回比對**,對就是對、不對就標出來。這就是評審要的『rollback 證據』。」

## 10. Audit(稽核)— 「防篡改治理帳本」
- **看**:`✓ chain verified · 1,204 entries`,近期含 remediate / gov-rollback / gov-review / gov-guardrail-block。
- **講**:「HMAC 鏈、金鑰分離。**改任一筆立即斷鏈**。管理動作和治理裁決都串在同一條可驗證的帳本。」

## 11. Scorecard(競爭力)— 「eval 分數趨勢」
- **看**:eval 分數趨勢(74→91)、分類分數。
- **講**:「跑真實任務、規則計分,失敗記 lessons 回饋下次 —— 一個閉環的品質度量。」

## 12. Proactive(主動)— 「team-lead 主動巡邏」
- **看**:auto cadence、最近巡邏「2 攻擊面暴露 → 已建議治理修復」。
- **講**:「不是等人問。team-lead **主動巡邏**,重複同一告警會**老化 backoff**(5 分 → 最多 12h),不吵人。」

## 13. Admin(管理)— 「kill-switch + 備份 + 展示開關」
- **看**:緊急 **kill-switch**(SIGSTOP 全隊)、whole-fleet **備份/還原**、Users/RBAC、**展示模式**開關。
- **講**:「一鍵凍結全隊、一鍵整套帶走。這裡也是你剛才開展示模式的地方。」

## 14. Settings(設定)— 「排程 / 門檻 / 通知」
- **看**:掃描排程、憑證/加密門檻、裝置健康門檻、通知管道。
- **講**:「所有掃描頻率、門檻、通知都可調,寫進 worker 持久化。」

---

## 收尾一句
> 「你剛看到的每一頁,都是**在治理框架內**跑的 —— 偵測、動手、證明,一條龍。現在我把展示模式關掉(按 Exit demo),它就回到真實系統。」
