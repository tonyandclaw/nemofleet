# PPTX-TODO.md — 待使用者在 PowerPoint 手改的清單

> loop **不碰 `.pptx` 二進位**(Linux 無 Microsoft JhengHei 字型,改了會破版)。這份是建議清單,你在 Windows PowerPoint 開 `ASUS-AgenticAI-Competition-2026.pptx` 手改。分「必改」與「建議補」。

## A. 必改 — 頁碼 stale(評審會注意到)
目前 footer 頁碼不連續、且與實際頁序對不上:
- slide 5 標 **3 / 8**、slide 8 也標 **3 / 8**(重複)
- slide 6 標 **2 / 8**,卻排在 slide 5 之後(逆序)
- 全簡報 18 頁,footer 仍寫 **/ 8**(總頁數過時)
建議:要嘛重編連續頁碼、要嘛整批移除 footer 頁碼(最省事且不會錯)。

## B. 建議補 — 讓投影片跟上 loop 期間新增的實作(都已實測,可加 talking point)
- **slide 10(四元件分工)**:OpenClaw 機隊現已逐台監控 **3 台真實機型** —— RT-AX89X(家用)、OpenWrt GL-AXT1800(閘道)、**ASUS ExpertWiFi EBG19P**(商用 PoE+ VPN 閘道,使用者實機)。把「現一台 sample」更新成「3 台真實設備、新機型上線只需一份 baseline」,坐實「機隊可橫向擴」。
- **slide 11(資安)**:可加一條 **形式化證明** —— `openshell policy prove` 對 policy 靜態窮舉外洩面(不只跑一次看 log)。誠實 framing:gap 全在套件/跨agent/本地 mail-jira 白名單 L4 端點。
- **slide 12(商業計畫)**:`design/business-case.md` 已深化(TAM/SAM/SOM、三種定價、競品對照、ROI 範例「200 台省約 65%」),可挑 1–2 個數字上 slide。
- **(可選)新增一頁「治理可量化」**:`govboard.sh` 一頁聚合 6 類 policy 的 ALLOWED + DENIED 計數、Jira 升級、CVE 分級、機隊台數、MTTR 44s —— 把「治理是可度量的運營」視覺化。

## C. 不需改 — 核心宣稱都已實測
slide 5–9 的痛點/爽點/省快數字、slide 11 的正常 vs 攻擊對照,全部對得到實測;逐條佐證見 `EVIDENCE.md`。上台 Q&A 見 `design/qa-prep.md`。

## 字型備忘
PPTX 用 ASUS 藍 `00589E` / 爽綠 `00846C` / 痛紅 `BE123C` / Microsoft JhengHei。Linux 端只能用 Pillow 幾何預覽驗版面,字型要在 Windows PowerPoint 才正確顯示。
