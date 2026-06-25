---
name: it-delegate-openclaw
description: Delegate ASUS network-product IT bugs (router firmware / subnet / bandwidth / DHCP) to the OpenClaw IT operator via its inbound fix endpoint, then report the verified result. Use whenever a user reports a network-device bug that needs an engineering fix.
tags: [it, network, asus, router, delegation, openclaw, bugfix]
---
# 委派 IT 修復給 OpenClaw(ASUS 網路產品 IT operator)

你(Hermes)是對人前台。遇到「ASUS 網路產品的 bug / 需要工程端動手修」的請求時,**不要自己改 code**,而是把它委派給專職 IT 的 OpenClaw —— 透過它的入站修復端點。修完把驗證結果回報給使用者。

## 何時使用
- 使用者(Telegram / email)回報路由器/AiMesh/網路裝置的功能異常,需要工程端修復,例如:
  - 「路由器顯示已是最新韌體卻裝不到更新」→ bug=**fw**
  - 「LAN /26 可用 IP 數不對 / 子網路主機數算錯」→ bug=**subnet**
  - 「頻寬或傳輸時間估算明顯不對」→ bug=**bandwidth**
  - 「DHCP 位址池數量算錯」→ bug=**dhcp**
  - 「設定被亂改/設定漂移/SSH 密碼登入被打開/logging 被關/跟核准基準不一致」→ bug=**drift**(真實機隊案例:工程端會比對已核准 baseline,只修回安全退化,其他變更列出待人審)
  - **EBG19P 真實安全動作**(OpenClaw A 直接套用到設備,確定性、附驗證):
    - 關 WPS → bug=`ebg-wps`;關 UPnP → bug=`ebg-upnp`;關 WAN 遠端網頁管理 → bug=`ebg-wanweb`;開 DoS 防護 → bug=`ebg-dos`
    - 開啟 AiProtection 惡意網站封鎖 → bug=`ebg-aiprotect`(關閉用 `ebg-aiprotect-off`);關 Samba → `ebg-samba`;關 Telnet/SSH → `ebg-telnet`/`ebg-ssh`
    - OpenClaw A 持有 EBG19P 操作知識庫(`it-task/ebg19p-operations.md`);未列入的設定變更會由 A 開 Jira 升級工程師,不擅自猜

⚠️ **設備對應務必正確**:`drift` 是 RT-AX89X 的設定基準比對情境,**不要**拿來處理 EBG19P 的具體設定(如 WPS/UPnP)——那會修錯設備、回報錯資產。EBG19P 的具體開關用上面的 `ebg-*` 真實動作。回報時務必用回應裡的 `asset` 欄位(例:lab-asus-ebg19p-01),不要憑空講成別台。

## 怎麼做 —— 依職責路由給對應節點(務必照做)
機隊分兩個 OpenClaw 節點,各司其職。**先判斷需求屬「運維修復」還是「資安分析」,再 POST 到對應節點:**
- **節點 A · `172.18.0.2`(IT 運維 / 網路管理)**:設備報修、設定漂移(drift)修復、網管。管 RT-AX89X、ExpertWiFi **EBG19P**、XT12、AP 等。**大部分「設定怪怪的/報修/修一下」走這裡。**
- **節點 B · `172.18.0.4`(資安 / 原始碼分析)**:OpenWrt 相關、或要求「掃 CVE / 讀韌體原始碼 / 生 SBOM / SAST / 看設計文件」的資安需求。

判斷 bug 類型 + 設備歸屬後,立刻用 shell 執行對應那**一行** curl(不要反問型號/不要自己修/不要只呼叫 /health):

運維修復(設定漂移/設備報修 → 節點 A):
```
curl -s -X POST http://172.18.0.2:9099/fix -H 'Content-Type: application/json' -H 'X-Bridge-Token: BRIDGETOKEN' -d '{"bug":"drift"}'
```
EBG19P 真實設定動作(關 WPS/UPnP → 節點 A,bug 換成 ebg-wps / ebg-upnp):
```
curl -s -X POST http://172.18.0.2:9099/fix -H 'Content-Type: application/json' -H 'X-Bridge-Token: BRIDGETOKEN' -d '{"bug":"ebg-wps"}'
```
資安分析(OpenWrt/CVE/原始碼 → 節點 B):
```
curl -s -X POST http://172.18.0.4:9099/fix -H 'Content-Type: application/json' -H 'X-Bridge-Token: BRIDGETOKEN' -d '{"bug":"fw"}'
```
`bug` 換成你判斷的類型(fw|subnet|bandwidth|dhcp|drift|ebg-wps|ebg-upnp|ebg-wanweb|ebg-dos)、**IP 換成對應職責節點**。非同步:立刻拿到 `{"accepted":true,...}`(對應節點已接手,約 30-120s)。
(IP 與 X-Bridge-Token 已由部署程序填好當前實際值——照原樣執行,不要改或省略 token。判不準就用節點 A 運維。)

## 回報給使用者(兩步)
1. **委派確認**:拿到 `accepted:true` 後,立刻回覆使用者:「已將此問題委派給專職 IT 的 OpenClaw 工程端處理(修復中,約 30-60s)」。
2. **取結果**:若使用者追問結果(或你要主動確認),對**剛才委派的那個節點 IP** 執行 `curl -s -H 'X-Bridge-Token: BRIDGETOKEN' http://<節點IP>:9099/last`(節點 A=172.18.0.2、節點 B=172.18.0.4),讀 JSON 的 `ok` / `before` / `after` / `agent_tail` / `pending_review` / `jira`:
   - `ok:true` → 用對客戶口吻回報結案,帶上「修復前→修復後」的關鍵值(例:安全退化 REGRESSIONS 5→0,SSH 密碼登入關回、遠端 logging 開回)。
   - 若有 `pending_review`(需人工核准的變更)或 `jira`(已開工單)→ 一併告知:「另有 N 項變更非安全退化、需人工判斷,OpenClaw 已開 Jira 工單(編號 …)升級工程師審核,未自行更動」。
   - `ok:false` → 告知尚未自動修復,OpenClaw 已自動開 Jira 工單升級工程師(附 `jira` 編號),附上 `after` 實際值。
   - 強調這是交由專職 IT 的 OpenClaw 實作、並經實跑驗證(不是你自己猜的);能修的當場修、修不了或需人審的就開 Jira 升級(人在迴路)。

## 邊界
- 這兩個節點端點是**唯一**能讓你驅動 OpenClaw 的管道(scoped network policy `openclaw_bridge`,只通 172.18.0.2:9099 與 172.18.0.4:9099 兩個節點,各鎖 /32 + token)。除此之外兩個 agent 沙箱互相隔離。
- 只用於上述網路裝置 bug 修復;其他需求照你原本的前台/自我進化流程處理。
