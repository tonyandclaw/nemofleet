# 雙 Agent 結合 Use Case — OpenClaw × Hermes

_最後更新:2026-06-11(openclaw_bridge 上線:跨 agent scoped egress 已解;06-06 重定位:Hermes=對人前台/自我進化、OpenClaw=IT operator、harness=policy/strategy 治理)_

## 願景:對人前台 + IT operator,由 harness 治理
兩台 sandbox **都跑 Azure Kimi-K2.5**(同模型),但**分工取各自強項**,再由 harness 層用 policy/strategy 治理:

| | hermes-demo (Hermes) | my-assistant (OpenClaw) |
|---|---|---|
| 角色 | **對人前台 + 自我進化** | **IT 機隊(現用一台當 sample,可橫向擴多台)** |
| 負責 | 多通道接需求、規劃、解釋、產出給人看、派工;把重複模式寫成 SKILL.md | ①監控網路設備狀態+定期掃 CVE ②接 Hermes 轉來的報修動手修(網管/診斷/bug 修復)+自動驗收 ③修不了/需人工核准→開 Jira 升級工程師 |
| 介面 | OpenAI 相容 **HTTP API** `:8642`(可程式化) | 經 `nsenter` 進 gateway netns 用 `openclaw agent` 驅動;:9099 scoped 入站修復端點 |
| 強項 | 規劃力、對話、自我進化技能 | 沙箱內動手、機隊監控、可被治理地執行、人在迴路升級 |

> **機隊定位**:OpenClaw 代表一支可橫向擴充的 IT operator fleet——一台 = 機隊樣本,真環境可部署多台分擔不同設備/站點,由 NemoClaw 統一管它們的生命週期與復原。

## harness 治理層(本專案核心之一)
- **OpenShell `policy.yaml`**:控制每台能連哪些網路 egress、能跑哪些 binaries → 「OpenClaw 可達 IT 所需內網,Hermes 不行」這類差異化治理。
- **nemoclaw strategy**:model/route/policy tier → 控制用哪個模型、走哪條 route、套哪組策略。
- 效果可由 OpenShell log 的 `ALLOWED`/`DENIED` 佐證:治理是「程式碼層強制」,不是靠 prompt。

## 協作流程(人 → Hermes → OpenClaw → 人)
1. 人提需求 → 預設進 **Hermes**(對人前台)規劃/分流。
2. `route.sh`/`route_decide`:IT/網管/bug/部署/診斷 關鍵字 → 委派 **OpenClaw** 實作;其餘規劃/解釋/報告 → Hermes 自理。
3. OpenClaw 在沙箱內(受 policy 治理)動手完成 IT 工作。
4. 結果經 **bus** 回收,由 Hermes 整理成人看得懂的回報。
5. 過程中學到的教訓沉澱成兩台的 `lessons-learned` SKILL.md(eval 閉環)。

## 互相溝通通道(MVP:檔案匣 bus)
`~/nemofleet/bus/` 作為兩 agent 的共享信箱:
- `bus/inbox/<id>.json` — 待處理訊息 `{from, to, type, content, ts}`
- `bus/outbox/<id>.json` — 回覆
- `scripts/relay.sh <target> "<message>"` — 把訊息送到目標 agent 的 OpenAI 相容 API,回覆寫回 bus。

未來可升級為:雙方 API 互打(agent A 的工具直接 call agent B 的 /v1)、或共用 messaging channel。

## 介面非對稱性(round 2 確認)
- **Hermes**:有乾淨的入站 OpenAI 相容 API(`http://127.0.0.1:8642/v1/chat/completions`,免 token)→ 可直接 curl 驅動。
- **OpenClaw**:`:18789` 是 **Control UI(HTML SPA / websocket)**,**沒有**入站 OpenAI 相容 chat API(帶 token 打 `/v1/chat/completions` 回 Not Found;policy 裡的 `/v1/...` 是 egress 允許,非對外服務)。OpenClaw 只能經 UI websocket session / messaging channel / `nemoclaw my-assistant connect` 驅動。

## 修正後的溝通設計(round 2)
因介面非對稱,改採 **bus 為單一整合點**,而非雙向 curl:
- Hermes 腿:relay 直接 HTTP 呼叫(已通)。
- OpenClaw 腿:由 **OpenClaw 端的 poller/hook 輪詢 `bus/inbox`** 取任務、把結果寫 `bus/outbox`(sidestep 它沒有入站 API 的限制)。或 round 3 探 UI 用的 websocket session route。

## 開放問題 / 待確認
- OpenClaw Control UI 背後的 websocket/session route(若要免 poller 直接驅動)。
- ~~沙箱 egress 是否允許「agent 容器內」對另一台 API 發請求(目前用 host 端 relay 繞過)。~~ **已解(2026-06-09)**:可以,但必須走 scoped policy——預設 deny-by-default,僅 `openclaw_bridge` policy(`bridge/openclaw-bridge-preset.yaml`,boot-stack 自動套用)放行 Hermes→`172.18.0.2:9099`,log 佐證 `ALLOWED POST .../fix [policy:openclaw_bridge engine:opa]`。
- 知識同步方向與衝突處理(沿用記憶系統圖的「負案例」概念)。
