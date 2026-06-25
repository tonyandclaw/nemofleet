# EBG19P × NemoClaw 整套系統 — 整合設計

> 標的:ASUS ExpertWiFi **EBG19P**(商用 PoE+ VPN 有線閘道,使用者實機 192.168.50.1,韌體 3.0.0.6.102)。
> 目的:把這台真實商用閘道的能力面,結合 NemoClaw(管理)/ OpenShell(強制)/ Hermes(對人)/ OpenClaw(機隊 A 運維·B 資安)四元件,
> 形成「真實設備 × 受治理 AI 維運」的完整閉環。本檔為設計藍圖,落地順序見 §4。

## 1. EBG19P 真實能力盤點(2026-06-16 唯讀 API 探測實得,非臆測)

| 能力面 | API/來源 | 實測 |
|---|---|---|
| 設定/安全面 | `nvram_get(*)` | 防火牆/DoS/UPnP/WPS/SSH/Telnet/遠端管理/VPN/Samba/AiProtection… |
| 系統資源 | `cpu_usage()` `memory_usage()` `uptime()` | 雙核 CPU、512MB RAM、開機時長 |
| 用戶端清單 | `get_clientlist()` | MAC/IP/名稱/類型/所屬 SDN(資產自動發現) |
| DHCP 租約 | `dhcpLeaseMacList()` | MAC→hostname 對照 |
| 流量統計 | `netdev(appobj)` | INTERNET/BRIDGE/WIRED 各介面 rx/tx 位元組 |
| 網路分段 | `nvram_get(sdn_rl)` | 多個 SDN(DEFAULT/WEB…)= VLAN/訪客網路分段 |
| VPN | `wgs_enable` `vpn_server_state` | WireGuard server(目前關)、VPN client 清單 |
| PoE / 鏈路 | 商用 PoE+ 8 埠 123W、`lacp_enabled` | 埠供電 / 鏈路聚合 |
| 安全防護 | `bwdpi_db_enable` `wrs_protect_enable` | AiProtection/DPI IPS(目前關) |
| 韌體 | `innerver` `firmware.auto_check` | 版本 + 自動檢查 |
| 設備拓撲 | `cfg_device_list` | AiMesh/設備清單 |

## 2. 已整合(現況 P0,已上線)

- **設定 drift 監控**:`ebg19p-monitor-sync.sh` 唯讀拉真機設定 → node A `/monitor` 逐鍵比對核准基準。
- **安全合規告警 + 自動開 Jira**:硬合規鍵(DoS/UPnP/WPS/SSH/遠端管理…)偏離 → `POST /monitor-scan` 經 `policy:jira` 治理 egress 開單(去重)。
- **真機硬化(寫入)**:經 ASUS `applyapp.cgi` 實際改設備(WPS off/DoS on/UPnP off 已執行)。
- **定期排程**:cron `*/15` 同步真機 + 合規巡檢。
- **變更通知**:變更紀錄經 `policy:greenmail_mail` 治理 egress 寄出。
- **憑證衛生**:密碼僅存 host `~/.config/nemoclaw/ebg19p.cred`(600),不入 repo;token 即用即棄。

## 3. 整合設計矩陣(能力 × 元件 × 價值)

| # | EBG19P 能力 | 主責元件 | 設計 | 價值 |
|---|---|---|---|---|
| A | 用戶端清單 + DHCP 租約 | OpenClaw **A**(運維) | 資產自動盤點;新 MAC 出現→「未知設備接入」告警;清單存快照比對 | Shadow-IT / 未授權接入偵測 |
| B | 流量 netdev rx/tx | OpenClaw **A** | 建流量基線,突增→告警;趨勢進 dashboard sparkline | 外洩/DDoS/挖礦行為偵測 |
| C | 系統 syslog | OpenClaw **B**(資安) | **EBG19P 遠端 syslog 指向本 stack**,node B 把設備日誌正規化成 OCSF→併入 dashboard 治理事件流 | 把「合規缺口」變「集中日誌+AI 分析」閉環 |
| D | AiProtection/DPI IPS 事件 | OpenClaw **B** | 開啟 IPS;入侵嘗試事件→OCSF→dashboard;高危→Jira | 設備自身的真實攻擊告警納入統一治理 |
| E | SDN/VLAN/訪客網路分段 | OpenClaw **B** + 設計符合性 | 稽核網段隔離(訪客是否隔離、管理 VLAN)對照 SECURITY-DESIGN.md | 零信任分段驗證 |
| F | VPN(WireGuard server) | OpenShell 理念 + Hermes | VPN 連線=遠端存取事件,審計+推播;新連線 Hermes 通知 | 遠端存取治理可觀測 |
| G | PoE 埠供電/功耗 | OpenClaw **A**(monitor+fix) | 埠供電/功耗監控;掛掉的 PoE 設備→遠端 reset 該埠(API 寫入,受治理) | 商用場景(IP cam/AP/VoIP 靠 PoE)自癒 |
| H | 韌體版本 + auto_check | OpenClaw **A**→**B** | 版本監控,有更新→告警;版本→node B CVE 比對(已有機制) | 韌體生命週期 + 漏洞聯動 |
| I | 設定全量快照 | **NemoClaw** 理念 | 變更前自動快照設定;出事一鍵還原到上一個已知良好 | 設定生命週期/復原 |
| J | 一句話維運 | **Hermes** 對人前台 | 「EBG19P 幾台連線?」「流量正常?」「關訪客 WiFi」→經 OpenShell 治理 egress 打 ASUS API | 自然語維運真實設備 |

## 4. 落地優先順序

**P1 — Quick win(唯讀、低風險、高展示價值,建議先做)**
- **A 資產盤點**:擴 `ebg19p-monitor-sync.sh` 多拉 clientlist+dhcp,存 `ebg19p-assets.json`;新 MAC→pending/告警。
- **B 流量基線**:netdev rx/tx 入 dashboard 趨勢;簡單 z-score 突增告警。
- **C syslog 閉環**:把 EBG19P 遠端 syslog 指向 stack 接收端,node B 正規化進治理事件流(同時補回那項合規)。

**P2 — 進階(含寫入/控制,需治理把關)**
- **G PoE 自癒**(monitor+fix 真實閉環,商用亮點)、**D IPS 事件**、**F VPN 審計**、**J Hermes 自然語維運**。
- 寫入類一律經 OpenShell 治理 egress + Hermes 人核准(對齊「治理是 code 不是 prompt」)。

## 5. 兩個敘事亮點(對競賽/客戶)

1. **合規缺口 → 整合機會(C)**:EBG19P「無遠端 syslog」本是合規告警項;把它指向本 stack 當 syslog 接收端,缺口反而變成「設備日誌集中 + node B 資安 AI 分析 + 統一 OCSF 治理視圖」的閉環。
2. **端到端零信任分段(E+OpenShell)**:EBG19P 的 **實體網路分段(SDN/VLAN/訪客隔離)** + OpenShell 的 **agent 網路分段(/32 + token)** = 從實體網路到 AI agent 的端到端最小權限敘事,商用客戶極有感。

---
*探測與現況對應 EVIDENCE B6/B7;憑證/同步機制見 memory ebg19p-fleet-third-device。本檔為設計藍圖,實作前逐項與使用者確認(尤以 P2 寫入類)。*
