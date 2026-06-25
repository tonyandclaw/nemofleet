# qa-prep.md — 評審 Q&A 預演題庫(上台/錄影前過一遍)

> 每題:**精簡答**(30–60 秒可講完)+ **佐證**(現場可秀的指令/檔案/數字,對得到 `EVIDENCE.md`)。答題原則:先給一句話結論,再給證據,誠實標限制。

## A. 差異化與實用價值(最常被問)

**Q1. 這跟「包一層 ChatGPT / Copilot」有什麼不同?**
答:那類是「會建議的 AI」——它告訴你該做什麼,但不動手、不負責、無治理。我們是「敢在治理下動手的維運勞動力」:監控發現 → 判型 → **實際改設定/修 code** → 驗收 → 修不了才升級人。差別是它真的把該做的事做完並留證據,不是給你一段建議。
佐證:`bash tests/bridge-regress.sh drift` → `[FIX DONE] REGRESSIONS=5→0`(真的改了設定、驗收通過),非文字建議。

**Q2. AI 修錯了怎麼辦?誰負責?**
答:三道防線。① 只修「安全退化」(偏離已核准 baseline 的安全鍵),判斷題一律不碰、列待審開 Jira;② 每次修完跑確定性驗收器(driftcheck/marker),沒通過就不算數、自動開 auto-fix-failed 工單升級人;③ 全程 OPA 治理 + 留證據,動作可追溯。所以「修錯」要嘛被驗收擋下、要嘛根本不在它敢動的範圍。
佐證:`/jira` 看 change-approval 工單(3 處漂移它不動、留人審);`driftcheck.py` 是確定性驗收。

**Q3. 為什麼不全自動?留人審不是更慢?**
答:這正是賣點——「治理下的自動化」不是「什麼都敢改」。安全退化(SSH 密碼登入被開、syslog 被關)有明確正確答案 → 當場自動修(44 秒);但「Wi-Fi 頻道改了」「SSH port 換了」這種是業務判斷、沒有唯一正確 → 留給人。把該自動的自動化、該人決定的留給人,才是企業敢用的前提。
佐證:demo A1 — 5 處退化自動修、3 處漂移開 Jira 待審。

**Q4. MTTR 44 秒怎麼算的?真有這麼快?**
答:`bridge-regress.sh drift` 從 Hermes 沙箱發出委派、到 OpenClaw 修完通過驗收的端到端實測,約 44 秒。對照的「7 天」是這類設定退化在人工流程(報修→轉單→排工程師)平均沒被處理的時間。我們壓的是「發現+排隊」那兩段,不是宣稱修一個 bug 只要 44 秒。
佐證:現場跑 `bridge-regress.sh drift` 計時。

**Q5. 這些 bug / drift 是真的還是 demo 造的?**
答:設定素材取自真實 ASUS lab 設備(RT-AX89X、OpenWrt 閘道、以及使用者實機 EBG19P 商用閘道)的 baseline/current 匯出;退化是真實會發生的(SSH 密碼登入、LuCI 暴露 WAN)。對外通道(Telegram/mail/Jira)demo 階段用 mock,但治理路徑、修復、驗收都是真的在跑。
佐證:`EVIDENCE.md` 每條宣稱對應可重現指令;`/monitor` 巡 3 台真實機型。

## B. 資訊安全

**Q6. 你怎麼保證 AI 不會亂改、不會把資料外洩?**
答:治理是 **code 不是 prompt**。OPA 在 host / path / binary 三層強制 + 跨 agent 通道收斂到 /32 + token。非白名單主機連不出去、未授權 binary 跑不了、憑證讀到的是 placeholder。不是「叫 AI 乖」,是程式碼層讓危險動作做不出來。
佐證:`security-demo.sh` — 外連 example.com → DENIED、換 curl → DENIED、要 API key → placeholder、log token → [CREDENTIAL]。

**Q7. 治理是 prompt 還是 code?能證明嗎?**
答:能。除了動態看 log(每個動作 ALLOWED/DENIED 帶 engine:opa/l7),我們還能**形式化證明**——`openshell policy prove` 對 policy 做靜態窮舉,把所有潛在外洩路徑列出來。這不是跑一次看結果,是數學上窮舉反例。
佐證:`bash demo/policy-prove-demo.sh`。

**Q8.(誠實題)policy prove 報 CRITICAL,那不就是不安全?**
答:好問題,而且我們選擇誠實面對。prove 報的反例**全部落在為了功能必開的白名單端點**:裝套件的 github/npm/brew、跨 agent 通道、本地 mail/jira,都是 L4-only。這跟攻擊 demo 不矛盾——非白名單主機是動態擋死的;prove 量化的是白名單內的放行面。成熟的安全不是宣稱零風險,是能把風險窮舉、量化、指名道姓,下一步上 L7 path 強制或登記 accepted-risks。
佐證:`policy-prove-demo.sh` 的 framing 段;對照 `security-demo.sh` S1 非白名單 DENIED。

**Q9. LLM 會幻覺,你怎麼敢信它的判斷?**
答:關鍵動作不靠模型自律。① 高風險路徑走確定性程式(CVE 比對、driftcheck 驗收、SAST 都是 deterministic、零 LLM);② 模型只負責「判型、寫修正」,結果一律過確定性驗收 + 治理;③ 修不了就升級人。模型錯了會被驗收擋下、被治理擋住,不會直接生效。
佐證:`cve-scan.sh` / `source-cve-demo.sh` 全確定性;`driftcheck.py` 驗收。

## C. 技術

**Q10. 兩個 agent 怎麼又隔離又能互通?委派安全嗎?**
答:預設兩沙箱完全隔離、無通道。我們只開一條 scoped 通道:OpenClaw 的 :9099 入站端點,egress policy 收斂到 `<OpenClaw IP>/32`(只通一台一埠)+ 端點要 X-Bridge-Token。OPA 放行「路徑」、token 擋「冒用」,雙鎖。
佐證:`openshell policy get hermes-demo --full | grep openclaw_bridge` → `/32`;攻擊 demo B1 無 token → 403。

**Q11. 換模型 / 換通道要重寫嗎?**
答:不用。通道是 Hermes 的 channel 抽象(Telegram/Email 同一套治理,換通道不換模型);模型由 NemoClaw 路由(已備好 NVIDIA 推理治理路徑,設 key 即切)。新機型上線也只要一份 baseline + 安全鍵——剛接入的 EBG19P 就是這樣加的。
佐證:`nvidia-inference-demo.sh`(provider 可切);EBG19P 接入(新機型只加設定)。

**Q12. 沒網路 / 離線能跑嗎?**
答:核心治理與確定性能力(監控、CVE 比對、SAST、policy prove、修復驗收)都在本地、不依賴外網,資料不離機——這正是企業敢讓它碰生產設備的關鍵。需要外網的只有 LLM 推理(可換本地/在地託管模型)和真正要送出去的動作(都受 egress policy 治理)。
佐證:`govboard.sh` / `cve-scan.sh` / `source-cve-demo.sh` 全本地零外呼。

## D. 商業

**Q13. 商業模式?怎麼賺錢?市場多大?**
答:三種:隨硬體出貨(把維運力當賣點)、維運訂閱(per-device/月)、企業 on-prem license(重視本地可控的客戶)。市場由內而外:ASUS 自家機隊 → 商用網通客戶 → 廣義企業/MSP 維運自動化。ROI 範例:管 200 台估省約 65% 人力 + MTTR 從天級壓到秒級。
佐證:`design/business-case.md`(數字標量級假設、待校準)。

**Q14. RMM/NMS/ITSM 已經有了,你贏在哪?為什麼是 ASUS 能做?**
答:它們停在「監控告警」或「開單流程」——不動手。我們動手修 + 修不了才升級人。而「為什麼是 ASUS」:我們有硬體權限、韌體**原始碼**、**設計文件**——能做別人做不到的 source SAST + 設計符合性檢查,從「不知道有沒有漏洞」到「指得出哪一行、附上 patch」。這是整合護城河。
佐證:`source-cve-demo.sh`(SBOM+SAST+設計符合性+建議 patch)。

## E. 落地與規模

**Q15. 只有一台 sample,怎麼證明能管機隊?**
答:架構天生水平擴展——多台 OpenClaw = 機隊,NemoClaw 管它們的生命週期。現在 `/monitor` 已經逐台巡 3 台真實機型(家用路由、OpenWrt 閘道、商用 VPN 閘道),CVE 掃描涵蓋 6 台,各台有自己的安全鍵。新機型上線只要一份 baseline,當天涵蓋。
佐證:`/monitor` managed=3、`/cve` fleet=6;EBG19P 當天接入即被監控。

**Q16. 正式環境接公司 Teams/Outlook/真 Jira 難嗎?**
答:不難——架構已抽象成 channel 與 egress policy。demo 用 Telegram/GreenMail/mock Jira 是為了零外部帳號、可重現;換成 Teams/Outlook/ServiceNow 是接 adapter + 加一條 egress policy 的工程工作,不是研究風險。治理模型一字不改。
佐證:`mail-demo`(GreenMail 接 Hermes 原生 email platform)、`policy:jira` 治理 egress 已是真的。

---
## 一句話收尾(被問「總結價值」時)
真正的價值不是 AI 會「建議」什麼,而是它能在政策、授權、驗收全部成立時,才有限度地把該做的事做完——而且做完留下完整證據。修得了當場修、修不了升級人,治理是 code 不是 prompt。
